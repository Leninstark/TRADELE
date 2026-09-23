"""Deep Agent analysis cache: same-day JSON reuse, refresh after midnight."""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from TRADELE.db.models import ExploreAnalysisCache
from TRADELE.engines.agents.stock_analyst import analyze_stock, resolve_symbol

logger = logging.getLogger(__name__)


def get_cached_analysis(
    db: Session,
    symbol: str,
    *,
    today: Optional[date] = None,
) -> Optional[ExploreAnalysisCache]:
    today = today or date.today()
    sym = (symbol or "").strip().upper()
    if not sym:
        return None
    row = (
        db.query(ExploreAnalysisCache)
        .filter(ExploreAnalysisCache.symbol == sym)
        .first()
    )
    if not row:
        return None
    if row.analysis_date != today:
        return None
    if not isinstance(row.payload, dict) or row.payload.get("error"):
        return None
    return row


def touch_access(db: Session, row: ExploreAnalysisCache) -> None:
    row.accessed_at = datetime.utcnow()
    try:
        db.commit()
    except Exception:
        db.rollback()


def upsert_analysis(db: Session, payload: dict[str, Any]) -> None:
    if not payload or payload.get("error"):
        return
    sym = str(payload.get("symbol") or "").strip().upper()
    if not sym:
        return
    today = date.today()
    company = str(payload.get("company") or sym)
    now = datetime.utcnow()
    row = (
        db.query(ExploreAnalysisCache)
        .filter(ExploreAnalysisCache.symbol == sym)
        .first()
    )
    stored = dict(payload)
    stored["from_cache"] = False
    stored["cached_date"] = today.isoformat()
    if row:
        row.company = company
        row.analysis_date = today
        row.payload = stored
        row.updated_at = now
        row.accessed_at = now
    else:
        db.add(
            ExploreAnalysisCache(
                symbol=sym,
                company=company,
                analysis_date=today,
                payload=stored,
                created_at=now,
                updated_at=now,
                accessed_at=now,
            )
        )
    try:
        db.commit()
    except Exception as e:
        logger.warning("explore cache upsert failed for %s: %s", sym, e)
        db.rollback()


def analyze_stock_cached(
    query: str,
    db: Session,
    *,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Return today's cached report when available; otherwise run AI and store JSON."""
    symbol, _company = resolve_symbol(query)
    if not symbol:
        return analyze_stock(query, db)

    if not force_refresh:
        row = get_cached_analysis(db, symbol)
        if row and isinstance(row.payload, dict):
            touch_access(db, row)
            out = dict(row.payload)
            out["from_cache"] = True
            out["cached_date"] = row.analysis_date.isoformat()
            return out

    result = analyze_stock(query, db)
    if not result.get("error"):
        upsert_analysis(db, result)
        result = dict(result)
        result["from_cache"] = False
        result["cached_date"] = date.today().isoformat()
    return result


def list_recent_analyses(db: Session, limit: int = 30) -> list[dict[str, str]]:
    rows = (
        db.query(ExploreAnalysisCache)
        .order_by(ExploreAnalysisCache.accessed_at.desc())
        .limit(max(1, min(limit, 60)))
        .all()
    )
    return [
        {
            "symbol": r.symbol,
            "company": r.company or r.symbol,
            "analysis_date": r.analysis_date.isoformat() if r.analysis_date else "",
            "accessed_at": r.accessed_at.isoformat() if r.accessed_at else "",
        }
        for r in rows
    ]
