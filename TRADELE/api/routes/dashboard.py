"""Dashboard API — morning overview for the AI Trading Intelligence Platform."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from TRADELE.db.session import get_db
from TRADELE.engines.market_data.overview import get_market_overview
from TRADELE.engines.scanners.runner import run_live_scan
from TRADELE.api.routes.alerts import latest_alerts

router = APIRouter()


@router.get("")
def dashboard(db: Session = Depends(get_db)):
    """Full dashboard payload: market overview, top picks, scanner counts, portfolio placeholder."""
    market = get_market_overview()
    swing = run_live_scan(db, style="swing", top_n_per_strategy=5)
    intraday = run_live_scan(db, style="intraday", top_n_per_strategy=5)
    positional = run_live_scan(db, style="positional", top_n_per_strategy=5)

    alerts = latest_alerts(db)

    return {
        "market": market,
        "top_swing": swing["top_picks"][:5],
        "intraday_scanners": {
            "counts": intraday["counts"],
            "top": intraday["top_picks"][:5],
        },
        "positional_scanners": {
            "counts": positional["counts"],
            "top": positional["top_picks"][:3],
        },
        "alerts": alerts,
        "portfolio": {
            "overall_pnl_pct": None,
            "ai_rating": "N/A",
            "message": "Connect Zerodha holdings (Phase 2)",
        },
    }


@router.get("/market")
def market_only():
    return get_market_overview()
