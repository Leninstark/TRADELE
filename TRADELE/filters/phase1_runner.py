"""Run Phase 1 stock filter against Zerodha + NSE data."""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from typing import Any, Optional

from TRADELE.config import settings
from TRADELE.filters.definitions import FILTER_PHASE_1, filter_to_dict
from TRADELE.filters.engine import apply_filter
from TRADELE.filters.nse_data import fetch_delivery_map, fetch_market_cap_cr
from TRADELE.filters.universe import load_phase1_universe
from TRADELE.services.screener_service import run_screener_query
from TRADELE.services.zerodha_client import get_client

logger = logging.getLogger(__name__)

_client_lock = threading.Lock()

CIRCUIT_PCT = 9.8
VOLUME_LOOKBACK_DAYS = 20
QUOTE_BATCH = 400
NSE_WORKERS = 4
HISTORICAL_DELAY_SEC = 0.35


def _screener_query_string() -> str:
    return (
        "Current price > 100 AND "
        "Market Capitalization > 3000 AND "
        "Average delivery percent > 35 AND "
        "Average Volume 1month > 500000"
    )


def _parse_screener_row(item: dict[str, Any]) -> Optional[dict[str, Any]]:
    symbol = (
        item.get("Symbol")
        or item.get("symbol")
        or item.get("NSE Code")
        or item.get("nse_code")
        or ""
    )
    symbol = str(symbol).strip().upper()
    if not symbol:
        return None

    def _num(*keys: str) -> Optional[float]:
        for k in keys:
            if k in item and item[k] not in (None, "", "-"):
                try:
                    return float(str(item[k]).replace(",", "").replace("₹", "").strip())
                except ValueError:
                    continue
        return None

    return {
        "symbol": symbol,
        "price": _num("CMP", "Current Price", "current_price", "Price"),
        "market_cap_cr": _num("Mar Cap", "Market Capitalization", "market_cap"),
        "avg_daily_volume": _num("Avg Vol 1Mth", "Average Volume 1month", "avg_volume"),
        "delivery_pct": _num("Del %", "Average delivery percent", "delivery_pct"),
        "is_circuit": False,
        "source": "screener",
    }


def _is_circuit_from_bars(bars: list[dict[str, Any]]) -> bool:
    if len(bars) < 2:
        return False
    last = bars[-1]
    prev = bars[-2]
    prev_close = float(prev.get("close") or 0)
    close = float(last.get("close") or 0)
    high = float(last.get("high") or 0)
    low = float(last.get("low") or 0)
    if prev_close <= 0:
        return False
    day_chg = abs((close - prev_close) / prev_close * 100)
    if day_chg >= CIRCUIT_PCT:
        return True
    if high > 0 and low > 0 and high == low:
        return True
    return False


def _avg_volume(bars: list[dict[str, Any]], days: int = VOLUME_LOOKBACK_DAYS) -> Optional[float]:
    if not bars:
        return None
    vols = [float(b.get("volume") or 0) for b in bars[-days:]]
    if not vols:
        return None
    return sum(vols) / len(vols)


def _batch_quote_prices(client, symbols: list[str]) -> dict[str, float]:
    prices: dict[str, float] = {}
    for i in range(0, len(symbols), QUOTE_BATCH):
        chunk = symbols[i : i + QUOTE_BATCH]
        keys = [f"NSE:{s}" for s in chunk]
        try:
            quotes = client.get_quote(keys)
            for key, q in quotes.items():
                sym = key.split(":", 1)[-1]
                lp = q.get("last_price") or (q.get("ohlc") or {}).get("close")
                if lp:
                    prices[sym] = float(lp)
        except Exception as e:
            logger.warning("Quote batch failed: %s", e)
        time.sleep(0.2)
    return prices


def _enrich_symbol(
    symbol: str,
    client,
    delivery_map: dict[str, float],
    from_date: date,
    to_date: date,
) -> Optional[dict[str, Any]]:
    try:
        with _client_lock:
            bars = client.get_historical(
                symbol, "NSE", "day", from_date, to_date, use_cache=False
            )
            time.sleep(HISTORICAL_DELAY_SEC)
    except Exception as e:
        logger.debug("Historical failed for %s: %s", symbol, e)
        return None

    if not bars:
        return None

    price = float(bars[-1].get("close") or 0)
    avg_vol = _avg_volume(bars)
    delivery = delivery_map.get(symbol)
    market_cap = fetch_market_cap_cr(symbol)

    row = {
        "symbol": symbol,
        "price": round(price, 2),
        "market_cap_cr": market_cap,
        "avg_daily_volume": round(avg_vol, 0) if avg_vol is not None else None,
        "delivery_pct": round(delivery, 2) if delivery is not None else None,
        "is_circuit": _is_circuit_from_bars(bars),
        "source": "zerodha+nse",
    }
    return row if apply_filter(row, FILTER_PHASE_1) else None


def _run_via_screener(client) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    items = run_screener_query(query_string=_screener_query_string())
    if not items:
        return [], {"screener_used": False, "screener_count": 0}

    candidates = [r for r in (_parse_screener_row(i) for i in items) if r]
    allowed = set(load_phase1_universe())
    candidates = [c for c in candidates if c["symbol"] in allowed]
    symbols = [c["symbol"] for c in candidates]
    circuit_flags: dict[str, bool] = {}

    for i in range(0, len(symbols), QUOTE_BATCH):
        chunk = symbols[i : i + QUOTE_BATCH]
        keys = [f"NSE:{s}" for s in chunk]
        try:
            quotes = client.get_quote(keys)
            for key, q in quotes.items():
                sym = key.split(":", 1)[-1]
                ohlc = q.get("ohlc") or {}
                prev = float(ohlc.get("close") or 0)
                last = float(q.get("last_price") or prev)
                if prev > 0 and abs((last - prev) / prev * 100) >= CIRCUIT_PCT:
                    circuit_flags[sym] = True
        except Exception as e:
            logger.warning("Circuit quote check failed: %s", e)

    results: list[dict[str, Any]] = []
    for row in candidates:
        sym = row["symbol"]
        row["is_circuit"] = circuit_flags.get(sym, False)
        if apply_filter(row, FILTER_PHASE_1):
            results.append(row)

    results.sort(key=lambda r: r.get("market_cap_cr") or 0, reverse=True)
    meta = {
        "screener_used": True,
        "screener_count": len(candidates),
        "universe_size": len(symbols),
    }
    return results, meta


def _run_via_zerodha(client, max_symbols: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    universe = load_phase1_universe()
    delivery_map = fetch_delivery_map()
    prices = _batch_quote_prices(client, universe)

    pre_filtered = [
        s for s in universe
        if prices.get(s, 0) > 100 and delivery_map.get(s, 0) > 35
    ]
    if max_symbols > 0:
        pre_filtered = pre_filtered[:max_symbols]

    to_date = date.today()
    from_date = to_date - timedelta(days=45)
    results: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=NSE_WORKERS) as pool:
        futures = {
            pool.submit(
                _enrich_symbol,
                sym,
                client,
                delivery_map,
                from_date,
                to_date,
            ): sym
            for sym in pre_filtered
        }
        for fut in as_completed(futures):
            row = fut.result()
            if row:
                results.append(row)

    results.sort(key=lambda r: r.get("market_cap_cr") or 0, reverse=True)
    meta = {
        "screener_used": False,
        "universe_size": len(universe),
        "universe_scope": "mid_small_cap",
        "pre_filtered": len(pre_filtered),
        "delivery_symbols": len(delivery_map),
    }
    return results, meta


def run_phase1_filter(max_symbols: int = 400) -> dict[str, Any]:
    """
    Run Phase 1 filter.
    Uses Screener.in (Apify) when APIFY_API_TOKEN is set; otherwise Zerodha historical + NSE.
    """
    client = get_client()
    if not client._token:
        return {
            "filter": filter_to_dict(FILTER_PHASE_1),
            "stocks": [],
            "meta": {"error": "not_connected", "message": "Connect Zerodha first."},
        }

    try:
        client.kite.profile()
    except Exception as e:
        return {
            "filter": filter_to_dict(FILTER_PHASE_1),
            "stocks": [],
            "meta": {
                "error": "not_connected",
                "message": f"Zerodha token invalid or expired: {e}",
            },
        }

    if settings.apify_api_token:
        stocks, meta = _run_via_screener(client)
        if stocks:
            return {"filter": filter_to_dict(FILTER_PHASE_1), "stocks": stocks, "meta": meta}

    stocks, meta = _run_via_zerodha(client, max_symbols=max_symbols)
    if not settings.apify_api_token:
        meta["note"] = (
            "Using Zerodha + NSE bhavcopy. Set APIFY_API_TOKEN for faster Screener.in scan."
        )
    elif not meta.get("screener_used"):
        meta["note"] = (
            "Screener.in unavailable; using Zerodha historical + NSE delivery data."
        )
    return {"filter": filter_to_dict(FILTER_PHASE_1), "stocks": stocks, "meta": meta}
