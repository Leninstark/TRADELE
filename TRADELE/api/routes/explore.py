"""Explore endpoints: deep single-stock LLM analysis + symbol search."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from TRADELE.db.session import get_db
from TRADELE.engines.agents.stock_analyst import analyze_stock, list_universe_symbols

router = APIRouter()


@router.get("/symbols")
def explore_symbols(q: str = Query("", description="Filter by symbol/company substring")):
    """Symbol + company list for the search box (optionally filtered)."""
    symbols = list_universe_symbols()
    if q:
        ql = q.strip().lower()
        symbols = [
            s for s in symbols
            if ql in s["symbol"].lower() or ql in s["company"].lower()
        ]
    return {"count": len(symbols), "symbols": symbols[:30]}


@router.get("/analyze")
def explore_analyze(
    symbol: str = Query(..., min_length=1, description="Stock symbol or company name"),
    db: Session = Depends(get_db),
):
    """
    Deep analysis of one stock: technicals + fundamentals + news, then a Gemini
    evidence-backed report with next-week / month / 3-month outlook.
    """
    return analyze_stock(symbol, db)
