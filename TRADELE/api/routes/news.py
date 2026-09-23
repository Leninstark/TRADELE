"""Unified news API + per-symbol Market News watchlist with live WebSocket feed."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from TRADELE.db.session import SessionLocal, get_db
from TRADELE.services.market_brief import (
    build_and_save_market_brief,
    get_latest_market_brief,
)
from TRADELE.services.news_aggregator import SOURCES, NewsItem, aggregate_news, news_for_symbol
from TRADELE.services.news_agent import run_news_agent
from TRADELE.services.news_symbol_service import refresh_symbol_feed, refresh_user_feeds
from TRADELE.services.news_watch_store import (
    acknowledge_feed,
    add_news_watch,
    list_feeds,
    list_news_watch,
    remove_news_watch,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _news_item_to_dict(n: NewsItem) -> dict:
    return {
        "title": n.title,
        "link": n.link,
        "source": n.source,
        "published": n.published.isoformat() if n.published else None,
        "summary": n.summary,
    }


class NewsWatchAddPayload(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=32)
    username: str = Field(default="leninstark")
    company: Optional[str] = None


@router.get("/sources")
def list_news_sources():
    """List configured RSS sources used for harvesting (India-focused)."""
    return {
        "sources": [{"name": name, "url": url} for name, url in SOURCES],
        "count": len(SOURCES),
    }


@router.get("")
def get_news_impact_tomorrow(
    skip_agent: bool = Query(
        False,
        description="If true, return only raw news items without running the LLM agent (no impact summary).",
    ),
):
    """
    Single unified news API: fetches all important news that may affect Indian stock prices today,
    then runs a LangGraph agent to produce an LLM-based summary with impact for TOMORROW.
    """
    if skip_agent:
        items = aggregate_news(symbols=None)[:50]
        return {
            "news_items": [_news_item_to_dict(n) for n in items],
            "impact_summary": None,
            "stocks_impact": None,
            "stocks_list": None,
            "message": "Agent skipped; raw news only.",
        }
    result: dict[str, Any] = run_news_agent()
    return {
        "news_items": result.get("news_items") or [],
        "impact_summary": result.get("impact_summary") or "",
        "stocks_impact": result.get("stocks_impact") or {},
        "stocks_list": result.get("stocks_list") or [],
    }


@router.get("/symbol/{symbol}")
def news_by_symbol(
    symbol: str,
    limit: int = Query(30, ge=1, le=100),
):
    """Get news items that mention the given symbol (e.g. RELIANCE, INFY)."""
    items = news_for_symbol(symbol.upper())[:limit]
    return {
        "symbol": symbol.upper(),
        "count": len(items),
        "items": [_news_item_to_dict(n) for n in items],
    }


# ── Market News watchlist (per-user tracked symbols) ─────────────────


@router.get("/watch")
def get_news_watch(username: str = Query("leninstark"), db: Session = Depends(get_db)):
    return {"items": list_news_watch(db, username)}


@router.post("/watch")
def post_news_watch(payload: NewsWatchAddPayload, db: Session = Depends(get_db)):
    try:
        item = add_news_watch(
            db,
            payload.username,
            payload.symbol,
            company=payload.company,
        )
        result = refresh_symbol_feed(
            db,
            payload.username,
            item["symbol"],
            item["company"],
            item.get("sector"),
            force=True,
        )
        return {"item": item, "feed": result}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.delete("/watch/{symbol}")
def delete_news_watch(
    symbol: str,
    username: str = Query("leninstark"),
    db: Session = Depends(get_db),
):
    ok = remove_news_watch(db, username, symbol)
    if not ok:
        raise HTTPException(404, f"{symbol} not on news watchlist")
    return {"removed": True, "symbol": symbol.upper()}


@router.get("/feed")
def get_news_feed(
    username: str = Query("leninstark"),
    q: str = Query("", description="Search filter across symbols and headlines"),
    db: Session = Depends(get_db),
):
    feeds = list_feeds(db, username)
    ql = q.strip().lower()
    if ql:
        filtered = []
        for f in feeds:
            blob = " ".join(
                [
                    f.get("symbol") or "",
                    f.get("company") or "",
                    f.get("sector") or "",
                    str((f.get("feed") or {}).get("analysis", {}).get("impact_summary", "")),
                ]
            ).lower()
            items = (f.get("feed") or {}).get("company_news") or []
            items += (f.get("feed") or {}).get("sector_news") or []
            items += (f.get("feed") or {}).get("rss_hits") or []
            for it in items:
                blob += " " + (it.get("title") or "").lower()
            if ql in blob:
                filtered.append(f)
        feeds = filtered
    return {"feeds": feeds, "count": len(feeds)}


@router.post("/feed/refresh")
def post_feed_refresh(
    username: str = Query("leninstark"),
    symbol: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    if symbol:
        watches = list_news_watch(db, username)
        row = next((w for w in watches if w["symbol"] == symbol.strip().upper()), None)
        if not row:
            raise HTTPException(404, f"{symbol} not tracked")
        result = refresh_symbol_feed(
            db,
            username,
            row["symbol"],
            row["company"],
            row.get("sector"),
            force=True,
        )
        return {"refreshed": [result]}
    return {"refreshed": refresh_user_feeds(db, username, force=True)}


@router.post("/feed/{symbol}/ack")
def post_feed_ack(
    symbol: str,
    username: str = Query("leninstark"),
    db: Session = Depends(get_db),
):
    """Mark symbol feed as read — clears unread notification badge."""
    ok = acknowledge_feed(db, username, symbol)
    if not ok:
        raise HTTPException(404, f"No feed for {symbol}")
    return {"acknowledged": True, "symbol": symbol.upper()}


@router.get("/brief")
def get_market_brief(
    brief_type: Optional[str] = Query(
        None,
        description="Optional filter: night | morning | manual. Default = latest of any type.",
    ),
    db: Session = Depends(get_db),
):
    """Latest overnight/morning Market Brief (index + sector risk regime)."""
    report = get_latest_market_brief(db, brief_type=brief_type)
    if not report:
        return {
            "ok": False,
            "error": "no_brief",
            "message": "No Market Brief yet. Click Refresh brief or wait for the night/morning job.",
        }
    return report


@router.post("/brief/run")
def run_market_brief(
    brief_type: str = Query("manual", description="night | morning | manual"),
    send_alert: bool = Query(False, description="Telegram on risk_off/crisis (off by default)"),
    db: Session = Depends(get_db),
):
    """Harvest global+India news, build risk brief. Alerts optional (default off)."""
    result = build_and_save_market_brief(
        db,
        brief_type=brief_type,
        send_alert=send_alert,
    )
    if not result.get("ok") and result.get("status") == "failed":
        raise HTTPException(500, result.get("error") or "Brief failed")
    return result


def _build_ws_payload(username: str) -> dict[str, Any]:
    db = SessionLocal()
    try:
        refresh_user_feeds(db, username, force=False)
        return {
            "type": "feed_update",
            "feeds": list_feeds(db, username),
            "at": datetime.utcnow().isoformat() + "Z",
        }
    finally:
        db.close()


@router.websocket("/ws")
async def news_watch_websocket(websocket: WebSocket, username: str = "leninstark"):
    """
    Live feed: polls all tracked symbols every ~90s, re-runs AI when new headlines appear.
    """
    await websocket.accept()
    try:
        # Push immediately on connect
        try:
            payload = await asyncio.to_thread(_build_ws_payload, username)
            await websocket.send_json(payload)
        except Exception as e:
            logger.warning("news ws initial tick failed: %s", e)
        while True:
            await asyncio.sleep(60)
            try:
                payload = await asyncio.to_thread(_build_ws_payload, username)
                await websocket.send_json(payload)
            except Exception as e:
                logger.warning("news ws tick failed: %s", e)
                await websocket.send_json({"type": "error", "message": str(e)})
    except WebSocketDisconnect:
        logger.debug("news ws disconnected: %s", username)
    except Exception as e:
        logger.warning("news ws closed: %s", e)
