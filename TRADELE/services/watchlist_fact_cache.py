"""Same-day fact bundle cache for deterministic watchlist analyst answers."""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from TRADELE.db.models import WatchlistFactCache

logger = logging.getLogger(__name__)


def get_fact_cache(db: Session, symbol: str, *, cache_date: Optional[date] = None) -> Optional[dict[str, Any]]:
    d = cache_date or date.today()
    row = (
        db.query(WatchlistFactCache)
        .filter(WatchlistFactCache.symbol == symbol.strip().upper(), WatchlistFactCache.cache_date == d)
        .first()
    )
    if not row or not isinstance(row.facts, dict):
        return None
    return {"facts": row.facts, "sources": row.sources or [], "cache_date": d.isoformat()}


def put_fact_cache(
    db: Session,
    symbol: str,
    facts: dict[str, Any],
    sources: list[str],
    *,
    cache_date: Optional[date] = None,
) -> None:
    sym = symbol.strip().upper()
    d = cache_date or date.today()
    row = (
        db.query(WatchlistFactCache)
        .filter(WatchlistFactCache.symbol == sym, WatchlistFactCache.cache_date == d)
        .first()
    )
    if row:
        row.facts = facts
        row.sources = sources
        row.updated_at = datetime.utcnow()
    else:
        db.add(
            WatchlistFactCache(
                symbol=sym,
                cache_date=d,
                facts=facts,
                sources=sources,
            )
        )
    try:
        db.commit()
    except Exception as e:
        logger.warning("fact cache write failed %s: %s", sym, e)
        db.rollback()
