"""Watchlist CRUD + analysis persistence."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from TRADELE.db.models import WatchlistAnalysis, WatchlistItem
from TRADELE.filters.universe import load_full_symbol_company_map, load_full_symbol_industry_map

logger = logging.getLogger(__name__)


def list_watchlist(db: Session, username: str) -> list[dict[str, Any]]:
    """List symbols with most recently chatted first (then newly added)."""
    username = username.strip().lower()
    last_chat = (
        db.query(
            WatchlistAnalysis.symbol.label("sym"),
            func.max(WatchlistAnalysis.created_at).label("last_at"),
        )
        .filter(
            WatchlistAnalysis.username == username,
            WatchlistAnalysis.analysis_type == "chat",
            WatchlistAnalysis.symbol.isnot(None),
        )
        .group_by(WatchlistAnalysis.symbol)
        .subquery()
    )
    rows = (
        db.query(WatchlistItem, last_chat.c.last_at)
        .outerjoin(last_chat, WatchlistItem.symbol == last_chat.c.sym)
        .filter(WatchlistItem.username == username)
        .order_by(last_chat.c.last_at.desc().nulls_last(), WatchlistItem.added_at.desc())
        .all()
    )
    out: list[dict[str, Any]] = []
    for r, last_at in rows:
        out.append(
            {
                "id": r.id,
                "symbol": r.symbol,
                "company": r.company,
                "sector": r.sector,
                "notes": r.notes,
                "added_at": r.added_at.isoformat() if r.added_at else None,
                "last_chatted_at": last_at.isoformat() if last_at else None,
                "sort_order": r.sort_order,
            }
        )
    return out


def bump_symbol_to_top(db: Session, username: str, symbol: str) -> None:
    """Move a symbol to the top of the watchlist after a chat enquiry."""
    username = username.strip().lower()
    sym = (symbol or "").strip().upper()
    if not sym:
        return
    row = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.username == username, WatchlistItem.symbol == sym)
        .first()
    )
    if not row:
        return
    # Keep sort_order as a secondary signal; list order is driven by last chat time
    row.sort_order = -int(datetime.utcnow().timestamp())
    db.commit()


def add_to_watchlist(
    db: Session,
    username: str,
    symbol: str,
    *,
    company: Optional[str] = None,
    notes: Optional[str] = None,
) -> dict[str, Any]:
    username = username.strip().lower()
    sym = symbol.strip().upper()
    if not sym:
        raise ValueError("Symbol required")

    company_map = load_full_symbol_company_map()
    industry_map = load_full_symbol_industry_map()
    co = company or company_map.get(sym) or sym
    sector = industry_map.get(sym)

    existing = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.username == username, WatchlistItem.symbol == sym)
        .first()
    )
    if existing:
        existing.company = co
        existing.sector = sector
        if notes is not None:
            existing.notes = notes
        db.commit()
        db.refresh(existing)
        row = existing
    else:
        count = db.query(WatchlistItem).filter(WatchlistItem.username == username).count()
        row = WatchlistItem(
            username=username,
            symbol=sym,
            company=co,
            sector=sector,
            notes=notes,
            sort_order=count,
        )
        db.add(row)
        db.commit()
        db.refresh(row)

    return {
        "id": row.id,
        "symbol": row.symbol,
        "company": row.company,
        "sector": row.sector,
        "notes": row.notes,
        "added_at": row.added_at.isoformat() if row.added_at else None,
    }


def remove_from_watchlist(db: Session, username: str, symbol: str) -> bool:
    username = username.strip().lower()
    sym = symbol.strip().upper()
    deleted = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.username == username, WatchlistItem.symbol == sym)
        .delete()
    )
    db.commit()
    return deleted > 0


def save_analysis(
    db: Session,
    *,
    username: str,
    symbol: Optional[str],
    analysis_type: str,
    payload: dict[str, Any],
    question: Optional[str] = None,
    sources: Optional[list[str]] = None,
) -> int:
    row = WatchlistAnalysis(
        username=username.strip().lower(),
        symbol=(symbol or "").upper() or None,
        analysis_type=analysis_type,
        question=question,
        payload=payload,
        sources=sources or [],
        created_at=datetime.utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    if symbol and analysis_type == "chat":
        try:
            bump_symbol_to_top(db, username, symbol)
        except Exception as e:
            logger.warning("bump watchlist order failed for %s: %s", symbol, e)
    return row.id


def list_analyses(
    db: Session,
    username: str,
    *,
    symbol: Optional[str] = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    q = db.query(WatchlistAnalysis).filter(WatchlistAnalysis.username == username.strip().lower())
    if symbol:
        q = q.filter(WatchlistAnalysis.symbol == symbol.strip().upper())
    rows = q.order_by(WatchlistAnalysis.id.desc()).limit(limit).all()
    return [
        {
            "id": r.id,
            "symbol": r.symbol,
            "analysis_type": r.analysis_type,
            "question": r.question,
            "payload": r.payload,
            "sources": r.sources,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "outcome_return_pct": r.outcome_return_pct,
            "outcome_hit": r.outcome_hit,
            "outcome_label": r.outcome_label,
            "outcome_labeled_at": r.outcome_labeled_at.isoformat() if r.outcome_labeled_at else None,
        }
        for r in rows
    ]
