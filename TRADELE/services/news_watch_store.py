"""CRUD for Market News watchlist + feed cache."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from TRADELE.db.models import NewsWatchFeed, NewsWatchItem
from TRADELE.filters.universe import load_full_symbol_company_map, load_full_symbol_industry_map

logger = logging.getLogger(__name__)


def list_news_watch(db: Session, username: str) -> list[dict[str, Any]]:
    rows = (
        db.query(NewsWatchItem)
        .filter(NewsWatchItem.username == username.strip().lower())
        .order_by(NewsWatchItem.added_at.desc())
        .all()
    )
    return [
        {
            "id": r.id,
            "symbol": r.symbol,
            "company": r.company,
            "sector": r.sector,
            "added_at": r.added_at.isoformat() if r.added_at else None,
        }
        for r in rows
    ]


def add_news_watch(
    db: Session,
    username: str,
    symbol: str,
    *,
    company: Optional[str] = None,
) -> dict[str, Any]:
    username = username.strip().lower()
    sym = symbol.strip().upper()
    if not sym:
        raise ValueError("Symbol required")

    company_map = load_full_symbol_company_map()
    industry_map = load_full_symbol_industry_map()
    co = company or company_map.get(sym) or sym
    sector = industry_map.get(sym)

    row = (
        db.query(NewsWatchItem)
        .filter(NewsWatchItem.username == username, NewsWatchItem.symbol == sym)
        .first()
    )
    if row:
        row.company = co
        row.sector = sector
    else:
        row = NewsWatchItem(username=username, symbol=sym, company=co, sector=sector)
        db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "symbol": row.symbol,
        "company": row.company,
        "sector": row.sector,
        "added_at": row.added_at.isoformat() if row.added_at else None,
    }


def remove_news_watch(db: Session, username: str, symbol: str) -> bool:
    username = username.strip().lower()
    sym = symbol.strip().upper()
    n1 = (
        db.query(NewsWatchItem)
        .filter(NewsWatchItem.username == username, NewsWatchItem.symbol == sym)
        .delete()
    )
    db.query(NewsWatchFeed).filter(
        NewsWatchFeed.username == username, NewsWatchFeed.symbol == sym
    ).delete()
    db.commit()
    return n1 > 0


def get_feed(db: Session, username: str, symbol: str) -> Optional[dict[str, Any]]:
    row = (
        db.query(NewsWatchFeed)
        .filter(
            NewsWatchFeed.username == username.strip().lower(),
            NewsWatchFeed.symbol == symbol.strip().upper(),
        )
        .first()
    )
    if not row:
        return None
    return {
        "symbol": row.symbol,
        "payload": row.payload,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def save_feed(
    db: Session,
    username: str,
    symbol: str,
    payload: dict[str, Any],
    seen_links: list[str],
) -> None:
    username = username.strip().lower()
    sym = symbol.strip().upper()
    row = (
        db.query(NewsWatchFeed)
        .filter(NewsWatchFeed.username == username, NewsWatchFeed.symbol == sym)
        .first()
    )
    if row:
        row.payload = payload
        row.seen_links = seen_links
        row.updated_at = datetime.utcnow()
    else:
        db.add(
            NewsWatchFeed(
                username=username,
                symbol=sym,
                payload=payload,
                seen_links=seen_links,
            )
        )
    db.commit()


def acknowledge_feed(db: Session, username: str, symbol: str) -> bool:
    """Mark all current headlines as read — clears unread badge."""
    username = username.strip().lower()
    sym = symbol.strip().upper()
    row = (
        db.query(NewsWatchFeed)
        .filter(NewsWatchFeed.username == username, NewsWatchFeed.symbol == sym)
        .first()
    )
    if not row or not isinstance(row.payload, dict):
        return False
    payload = dict(row.payload)
    links = list(payload.get("seen_links") or row.seen_links or [])
    payload["ack_links"] = links
    payload["has_new"] = False
    payload["new_count"] = 0
    row.payload = payload
    row.updated_at = datetime.utcnow()
    db.commit()
    return True


def list_feeds(db: Session, username: str) -> list[dict[str, Any]]:
    username = username.strip().lower()
    watches = list_news_watch(db, username)
    watch_by_sym = {w["symbol"]: w for w in watches}
    out: list[dict[str, Any]] = []
    for sym in watch_by_sym:
        feed = get_feed(db, username, sym)
        watch = watch_by_sym[sym]
        out.append(
            {
                "symbol": sym,
                "company": watch.get("company"),
                "sector": watch.get("sector"),
                "added_at": watch.get("added_at"),
                "feed": feed["payload"] if feed else None,
                "updated_at": feed["updated_at"] if feed else None,
            }
        )
    return out
