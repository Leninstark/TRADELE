"""Sector graph + knowledge chunk storage for watchlist RAG."""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Any, Optional

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

from TRADELE.config import settings
from TRADELE.db.models import WatchlistGraphEdge, WatchlistKnowledgeChunk
from TRADELE.db.session import engine
from TRADELE.filters.universe import load_full_symbol_industry_map
from TRADELE.services.watchlist_embeddings import embed_query, embed_text

logger = logging.getLogger(__name__)
_schema = settings.db_schema
_pgvector_ok: Optional[bool] = None


def _pgvector_available() -> bool:
    global _pgvector_ok
    if _pgvector_ok is not None:
        return _pgvector_ok
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'"))
            row = conn.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")).fetchone()
            _pgvector_ok = bool(row)
    except Exception:
        _pgvector_ok = False
    return _pgvector_ok


def _chunk_key(symbol: str, source: str, suffix: str) -> str:
    raw = f"{symbol}|{source}|{suffix}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def upsert_chunk(
    db: Session,
    *,
    symbol: str,
    source: str,
    content: str,
    suffix: str = "main",
    metadata: Optional[dict[str, Any]] = None,
    embedding: Optional[list[float]] = None,
) -> None:
    sym = symbol.strip().upper()
    key = _chunk_key(sym, source, suffix)
    emb = embedding if embedding is not None else embed_text(content)

    row = (
        db.query(WatchlistKnowledgeChunk)
        .filter(
            WatchlistKnowledgeChunk.symbol == sym,
            WatchlistKnowledgeChunk.chunk_key == key,
        )
        .first()
    )
    if row:
        row.content = content
        row.metadata_ = metadata
        row.embedding = emb
        row.updated_at = datetime.utcnow()
    else:
        db.add(
            WatchlistKnowledgeChunk(
                symbol=sym,
                source=source,
                chunk_key=key,
                content=content,
                metadata_=metadata,
                embedding=emb,
            )
        )
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning("chunk upsert failed %s: %s", sym, e)
        return

    if _pgvector_available() and emb:
        try:
            vec_lit = "[" + ",".join(str(float(x)) for x in emb[:768]) + "]"
            with engine.begin() as conn:
                conn.execute(
                    text(
                        f'UPDATE "{_schema}".watchlist_knowledge_chunks '
                        "SET embedding_vec = CAST(:vec AS vector) "
                        "WHERE symbol = :sym AND chunk_key = :key"
                    ),
                    {"vec": vec_lit, "sym": sym, "key": key},
                )
        except Exception as e:
            logger.debug("pgvector update skipped: %s", e)


def index_facts(db: Session, facts: dict[str, Any]) -> int:
    from TRADELE.services.watchlist_collectors import facts_to_chunks

    sym = str(facts.get("symbol") or "").upper()
    if not sym:
        return 0
    n = 0
    for source, suffix, content, meta in facts_to_chunks(facts):
        if not content.strip():
            continue
        upsert_chunk(db, symbol=sym, source=source, content=content, suffix=suffix, metadata=meta)
        n += 1
    return n


def retrieve_chunks(
    db: Session,
    symbol: str,
    *,
    question: str = "",
    limit: int = 8,
) -> list[dict[str, Any]]:
    sym = symbol.strip().upper()

    if _pgvector_available() and question.strip():
        try:
            q_emb = embed_query(question)
            vec_lit = "[" + ",".join(str(float(x)) for x in q_emb[:768]) + "]"
            with engine.connect() as conn:
                rows = conn.execute(
                    text(
                        f'SELECT source, content, metadata, '
                        f"1 - (embedding_vec <=> CAST(:vec AS vector)) AS score "
                        f'FROM "{_schema}".watchlist_knowledge_chunks '
                        f"WHERE symbol = :sym AND embedding_vec IS NOT NULL "
                        f"ORDER BY embedding_vec <=> CAST(:vec AS vector) "
                        f"LIMIT :lim"
                    ),
                    {"vec": vec_lit, "sym": sym, "lim": limit},
                ).fetchall()
            if rows:
                return [
                    {
                        "source": r[0],
                        "content": r[1],
                        "metadata": r[2] or {},
                        "score": float(r[3]) if r[3] is not None else None,
                    }
                    for r in rows
                ]
        except Exception as e:
            logger.debug("pgvector search failed: %s", e)

    rows = (
        db.query(WatchlistKnowledgeChunk)
        .filter(WatchlistKnowledgeChunk.symbol == sym)
        .order_by(WatchlistKnowledgeChunk.updated_at.desc())
        .limit(50)
        .all()
    )
    if not rows:
        return []

    if question.strip():
        q = embed_query(question)
        q_arr = np.asarray(q, dtype=float)
        scored: list[tuple[float, WatchlistKnowledgeChunk]] = []
        for r in rows:
            if not r.embedding or len(r.embedding) < 8:
                continue
            v = np.asarray(r.embedding, dtype=float)
            denom = np.linalg.norm(q_arr) * np.linalg.norm(v)
            sim = float(np.dot(q_arr, v) / denom) if denom else 0.0
            scored.append((sim, r))
        scored.sort(key=lambda x: x[0], reverse=True)
        picked = [r for _, r in scored[:limit]] or rows[:limit]
    else:
        picked = rows[:limit]

    return [
        {
            "source": r.source,
            "content": r.content,
            "metadata": r.metadata_ or {},
        }
        for r in picked
    ]


def rebuild_sector_graph(db: Session, symbols: list[str]) -> int:
    """Build same_sector edges among watchlist symbols + industry peers."""
    industry_map = load_full_symbol_industry_map()
    by_industry: dict[str, list[str]] = {}
    for sym in symbols:
        ind = industry_map.get(sym.upper())
        if ind:
            by_industry.setdefault(ind, []).append(sym.upper())

    added = 0
    for industry, peers in by_industry.items():
        if len(peers) < 2:
            continue
        for i, a in enumerate(peers):
            for b in peers[i + 1 :]:
                for fr, to in ((a, b), (b, a)):
                    existing = (
                        db.query(WatchlistGraphEdge)
                        .filter(
                            WatchlistGraphEdge.from_symbol == fr,
                            WatchlistGraphEdge.to_symbol == to,
                            WatchlistGraphEdge.relation == "same_sector",
                        )
                        .first()
                    )
                    if existing:
                        continue
                    db.add(
                        WatchlistGraphEdge(
                            from_symbol=fr,
                            to_symbol=to,
                            relation="same_sector",
                            weight=1.0,
                            metadata_={"industry": industry},
                        )
                    )
                    added += 1
    try:
        db.commit()
    except Exception:
        db.rollback()
    return added


def graph_context(db: Session, symbol: str, limit: int = 6) -> list[dict[str, Any]]:
    sym = symbol.strip().upper()
    edges = (
        db.query(WatchlistGraphEdge)
        .filter(WatchlistGraphEdge.from_symbol == sym)
        .limit(limit)
        .all()
    )
    return [
        {
            "symbol": e.to_symbol,
            "relation": e.relation,
            "weight": e.weight,
            "metadata": e.metadata_ or {},
        }
        for e in edges
    ]


def sector_peers(symbol: str, limit: int = 8) -> list[str]:
    """In-memory sector peers from industry map (no DB required)."""
    industry_map = load_full_symbol_industry_map()
    sym = symbol.upper()
    ind = industry_map.get(sym)
    if not ind:
        return []
    peers = [s for s, i in industry_map.items() if i == ind and s != sym]
    return peers[:limit]
