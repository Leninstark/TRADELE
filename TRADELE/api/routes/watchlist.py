"""Watchlist CRUD + Watchlist Analyst chat API."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from TRADELE.db.session import get_db
from TRADELE.engines.agents.watchlist_analyst import run_watchlist_chat
from TRADELE.services.watchlist_collectors import collect_facts
from TRADELE.services.watchlist_knowledge import index_facts, rebuild_sector_graph
from TRADELE.services.watchlist_store import (
    add_to_watchlist,
    list_analyses,
    list_watchlist,
    remove_from_watchlist,
)
from TRADELE.services.watchlist_outcome import label_pending_analyses

router = APIRouter()


class WatchlistAddPayload(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=32)
    username: str = Field(default="leninstark")
    company: Optional[str] = None
    notes: Optional[str] = None


class WatchlistChatPayload(BaseModel):
    symbol: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)
    username: str = Field(default="leninstark")
    force_refresh: bool = False


@router.get("/items")
def get_items(username: str = Query("leninstark"), db: Session = Depends(get_db)):
    return {"items": list_watchlist(db, username)}


@router.post("/items")
def post_item(payload: WatchlistAddPayload, db: Session = Depends(get_db)):
    try:
        item = add_to_watchlist(
            db,
            payload.username,
            payload.symbol,
            company=payload.company,
            notes=payload.notes,
        )
        wl = list_watchlist(db, payload.username)
        rebuild_sector_graph(db, [w["symbol"] for w in wl])
        return item
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.delete("/items/{symbol}")
def delete_item(symbol: str, username: str = Query("leninstark"), db: Session = Depends(get_db)):
    ok = remove_from_watchlist(db, username, symbol)
    if not ok:
        raise HTTPException(404, f"{symbol} not on watchlist")
    return {"removed": True, "symbol": symbol.upper()}


@router.post("/chat")
def chat(payload: WatchlistChatPayload, db: Session = Depends(get_db)):
    wl = list_watchlist(db, payload.username)
    sym = payload.symbol.strip().upper()
    row = next((w for w in wl if w["symbol"] == sym), None)
    if not row:
        raise HTTPException(404, f"{sym} not on your watchlist — add it first")

    result = run_watchlist_chat(
        db,
        username=payload.username,
        symbol=sym,
        question=payload.message,
        company=row.get("company"),
        sector=row.get("sector"),
        force_refresh=payload.force_refresh,
    )
    return result


@router.get("/chat/history")
def chat_history(
    username: str = Query("leninstark"),
    symbol: Optional[str] = Query(None),
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return {"history": list_analyses(db, username, symbol=symbol, limit=limit)}


@router.post("/reindex/{symbol}")
def reindex_symbol(
    symbol: str,
    username: str = Query("leninstark"),
    db: Session = Depends(get_db),
):
    sym = symbol.strip().upper()
    facts, sources = collect_facts(db, sym, force_refresh=True)
    n = index_facts(db, facts)
    return {"symbol": sym, "chunks_indexed": n, "sources": sources}


@router.post("/outcomes/label")
def label_outcomes(db: Session = Depends(get_db)):
    """Manual / cron hook: label prior analyst verdicts vs next-day move."""
    return label_pending_analyses(db)
