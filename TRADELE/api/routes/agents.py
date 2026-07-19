"""LangGraph agent endpoints."""
from fastapi import APIRouter, Query

from TRADELE.engines.agents.momentum_agent import run_momentum_agent

router = APIRouter()


@router.get("/momentum")
def momentum_scan(
    lookback_days: int = Query(30, ge=10, le=90),
    top_n: int = Query(15, ge=5, le=30),
    max_symbols: int = Query(50, ge=10, le=200),
):
    """
    LangGraph agent: scan last N days for momentum stocks.
    Fetches OHLCV → scores momentum → Gemini ranks and explains top picks.
    """
    return run_momentum_agent(
        lookback_days=lookback_days,
        top_n=top_n,
        max_symbols=max_symbols,
    )


@router.post("/momentum")
def momentum_scan_post(
    lookback_days: int = Query(30, ge=10, le=90),
    top_n: int = Query(15, ge=5, le=30),
    max_symbols: int = Query(50, ge=10, le=200),
):
    """POST trigger — same as GET (for schedulers / webhooks)."""
    return run_momentum_agent(
        lookback_days=lookback_days,
        top_n=top_n,
        max_symbols=max_symbols,
    )
