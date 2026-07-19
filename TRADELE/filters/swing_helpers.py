"""Shared helpers for swing tab scanners."""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

from TRADELE.db.models import SwingScanResult, SwingScanRun
from TRADELE.engines.indicators.calculator import IndicatorCalculator
from TRADELE.filters.swing_definitions import TAB_UNIVERSE
from TRADELE.services.zerodha_client import ZerodhaClient, get_client

logger = logging.getLogger(__name__)

_client_lock = threading.Lock()
HISTORICAL_DELAY_SEC = 0.3
CALC = IndicatorCalculator()


def get_universe_symbols(db: Session) -> list[str]:
    """Symbols from latest successful Universe scan."""
    run = (
        db.query(SwingScanRun)
        .filter(SwingScanRun.tab == TAB_UNIVERSE, SwingScanRun.status == "success")
        .order_by(SwingScanRun.finished_at.desc())
        .first()
    )
    if not run:
        return []
    rows = db.query(SwingScanResult.symbol).filter(SwingScanResult.run_id == run.id).all()
    return [r[0] for r in rows]


def check_zerodha() -> tuple[Optional[ZerodhaClient], Optional[dict[str, Any]]]:
    client = get_client()
    if not client._token:
        return None, {"error": "not_connected", "message": "Connect Zerodha first."}
    try:
        client.kite.profile()
    except Exception as e:
        return None, {"error": "not_connected", "message": f"Zerodha token invalid: {e}"}
    return client, None


def _fetch_candles(client: ZerodhaClient, symbol: str, lookback_days: int) -> list[dict[str, Any]]:
    to_date = date.today()
    from_date = to_date - timedelta(days=lookback_days)
    with _client_lock:
        data = client.get_historical(symbol, "NSE", "day", from_date, to_date, use_cache=False)
        time.sleep(HISTORICAL_DELAY_SEC)
    return data


def _return_pct(closes: list[float], days: int) -> Optional[float]:
    if len(closes) <= days:
        return None
    prev = closes[-1 - days]
    now = closes[-1]
    if not prev:
        return None
    return round((now - prev) / prev * 100, 2)


def get_index_return_pct(client: ZerodhaClient, days: int = 20) -> Optional[float]:
    """Nifty 50 index return over N trading days (via Zerodha historical)."""
    from_date = date.today() - timedelta(days=days + 30)
    to_date = date.today()
    for instrument in ("NIFTY 50", "NIFTYBEES"):
        try:
            with _client_lock:
                candles = client.get_historical(
                    instrument, "NSE", "day", from_date, to_date, use_cache=False
                )
            if len(candles) < days + 1:
                continue
            closes = [float(c["close"]) for c in candles]
            ret = _return_pct(closes, days)
            if ret is not None:
                return ret
        except Exception as e:
            logger.debug("Index return failed for %s: %s", instrument, e)
    return None


def scan_symbols(
    client: ZerodhaClient,
    symbols: list[str],
    evaluator: Callable[[str, list[dict], dict[str, Any]], Optional[dict[str, Any]]],
    lookback_days: int = 400,
    max_workers: int = 4,
) -> list[dict[str, Any]]:
    """Fetch candles per symbol and apply evaluator; return matching rows."""
    results: list[dict[str, Any]] = []

    def _job(sym: str) -> Optional[dict[str, Any]]:
        try:
            candles = _fetch_candles(client, sym, lookback_days)
            if len(candles) < 25:
                return None
            indicators = CALC.compute(sym, candles)
            if not indicators:
                return None
            return evaluator(sym, candles, indicators)
        except Exception as e:
            logger.debug("Scan failed for %s: %s", sym, e)
            return None

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_job, s): s for s in symbols}
        for fut in as_completed(futures):
            row = fut.result()
            if row:
                results.append(row)
    return results
