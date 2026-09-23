"""Tomorrow intraday momentum scanner API — Long/Short top candidates + conviction."""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from TRADELE.db.session import get_db
from TRADELE.services.intraday_momentum_scanner import build_setup_chart, run_tomorrow_intraday_scan
from TRADELE.services.intraday_momentum_store import (
    get_momentum_run,
    last_completed_session,
    list_momentum_runs,
    save_momentum_scan,
)
from TRADELE.services.zerodha_client import KiteRateLimitError

router = APIRouter()


@router.get("/tomorrow-momentum")
def tomorrow_momentum(
    username: str = Query("leninstark"),
    top_n: int = Query(3, ge=1, le=5),
    max_symbols: int = Query(40, ge=10, le=80),
    as_of: Optional[date] = Query(
        None,
        description="Session date (defaults to last completed NSE session, not calendar midnight)",
    ),
    force_refresh: bool = Query(
        False,
        description="If false, return saved day conviction when present (deterministic).",
    ),
    db: Session = Depends(get_db),
):
    """
    Scan late-session momentum setups for tomorrow's intraday.
    Default: serve DB-saved conviction for the session day (deterministic).
    force_refresh=true re-runs live scoring and upserts the day cache.
    """
    session = as_of or last_completed_session()
    try:
        return run_tomorrow_intraday_scan(
            db,
            username=username,
            max_symbols=max_symbols,
            top_n=top_n,
            trade_date=session,
            force_refresh=force_refresh,
        )
    except KiteRateLimitError:
        from TRADELE.services.intraday_momentum_store import get_day_cached_scan, get_latest_good_scan

        cached = get_day_cached_scan(db, username=username, as_of=session) or get_latest_good_scan(
            db, username=username
        )
        if cached:
            cached["message"] = "Rate limited — showing saved conviction."
            cached["rate_limited"] = True
            return cached
        payload = {
            "error": "rate_limit",
            "message": "Too many requests from Zerodha. Wait a minute, then scan again.",
            "longs": [],
            "shorts": [],
            "as_of": session.isoformat(),
            "scanned": 0,
            "prefiltered": 0,
            "sources": [],
            "rate_limited": True,
        }
        run_id = save_momentum_scan(
            db,
            username=username,
            result=payload,
            status="failed",
            error_message=payload["message"],
        )
        payload["run_id"] = run_id
        payload["saved"] = bool(run_id)
        return payload


@router.get("/tomorrow-momentum/chart")
def tomorrow_momentum_chart(
    symbol: str = Query(..., min_length=1),
    username: str = Query("leninstark"),
    direction: str = Query("long"),
    as_of: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    """5m setup chart with VWAP/EMA levels and numbered callouts for a candidate."""
    session = as_of or last_completed_session()
    try:
        return build_setup_chart(
            db,
            username=username,
            symbol=symbol,
            direction=direction,
            trade_date=session,
        )
    except KiteRateLimitError:
        return {
            "error": "rate_limit",
            "message": "Too many requests from Zerodha. Wait a minute, then retry the chart.",
            "symbol": symbol.strip().upper(),
            "as_of": session.isoformat(),
            "bars": [],
            "levels": {},
            "callouts": [],
        }


@router.get("/tomorrow-momentum/runs")
def momentum_scan_history(
    username: str = Query("leninstark"),
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """List saved momentum scans (for RL / conviction review)."""
    return {"runs": list_momentum_runs(db, username=username, limit=limit)}


@router.get("/tomorrow-momentum/runs/{run_id}")
def momentum_scan_detail(run_id: int, db: Session = Depends(get_db)):
    """Full saved scan payload + candidates (including near-misses and outcome fields)."""
    row = get_momentum_run(db, run_id)
    if not row:
        return {"error": "not_found", "run_id": run_id}
    return row
