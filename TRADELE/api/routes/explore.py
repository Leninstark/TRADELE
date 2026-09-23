"""Explore endpoints: deep single-stock LLM analysis + symbol search + recent cache."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from TRADELE.db.session import get_db
from TRADELE.filters.universe import search_universe_symbols
from TRADELE.engines.agents.stock_analyst import list_universe_symbols
from TRADELE.services.explore_cache import analyze_stock_cached, list_recent_analyses

router = APIRouter()


@router.get("/symbols")
def explore_symbols(q: str = Query("", description="Filter by symbol/company substring")):
    """Symbol + company list for the search box (full NSE EQ universe, ranked)."""
    if q.strip():
        symbols = search_universe_symbols(q, limit=40)
    else:
        symbols = list_universe_symbols()[:40]
    return {"count": len(symbols), "symbols": symbols}


@router.get("/recent")
def explore_recent(
    limit: int = Query(30, ge=1, le=60),
    db: Session = Depends(get_db),
):
    """Last N Deep Agent searches (symbol + company) for the recent grid."""
    items = list_recent_analyses(db, limit=limit)
    return {"count": len(items), "items": items}


@router.get("/analyze")
def explore_analyze(
    symbol: str = Query(..., min_length=1, description="Stock symbol or company name"),
    force_refresh: bool = Query(False, description="Bypass same-day JSON cache"),
    db: Session = Depends(get_db),
):
    """
    Deep analysis of one stock. Serves today's cached JSON when available;
    regenerates (and overwrites cache) if the calendar day has changed.
    """
    return analyze_stock_cached(symbol, db, force_refresh=force_refresh)
