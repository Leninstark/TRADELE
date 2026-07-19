"""Scanner API — intraday, swing, and positional scans."""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from TRADELE.db.session import get_db
from TRADELE.engines.scanners.runner import run_live_scan
from TRADELE.rules.registry import all_strategies, get_strategy

router = APIRouter()


@router.get("/strategies")
def list_strategies(style: Optional[str] = Query(None, pattern="^(intraday|swing|positional)$")):
    """List available scanner strategies."""
    strategies = all_strategies(include_disabled=True)
    if style:
        strategies = [s for s in strategies if s.style == style]
    return [
        {
            "id": s.id,
            "name": s.name,
            "style": s.style,
            "description": s.description,
            "condition_count": len(s.conditions),
            "min_confidence": s.min_confidence,
            "enabled": s.enabled,
        }
        for s in strategies
    ]


@router.get("/run")
def run_scanners(
    style: Optional[str] = Query(None, pattern="^(intraday|swing|positional)$"),
    strategy_id: Optional[str] = None,
    top_n: int = Query(20, le=50),
    db: Session = Depends(get_db),
):
    """Run scanners for a trading style or single strategy."""
    if strategy_id:
        strategy = get_strategy(strategy_id)
        if not strategy:
            return {"error": f"Unknown strategy: {strategy_id}"}
        from TRADELE.services.data_fetcher import apply_liquidity_filters, fetch_eod_batch
        from TRADELE.engines.scanners.runner import run_scan
        from TRADELE.services.zerodha_client import get_client

        client = get_client()
        symbol_data = apply_liquidity_filters(fetch_eod_batch(client, db))
        results = run_scan(symbol_data, strategy, top_n=top_n)
        return {
            "strategy": strategy_id,
            "matches": [m.to_dict() for m in results],
        }

    return run_live_scan(db, style=style, top_n_per_strategy=top_n)
