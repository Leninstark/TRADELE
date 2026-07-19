"""Build per-symbol metrics for dashboard and stock score."""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from typing import Any, Optional

from TRADELE.engines.indicators.calculator import IndicatorCalculator
from TRADELE.filters.nse_data import fetch_delivery_map, fetch_delivery_snapshots
from TRADELE.filters.stock_score import compute_stock_score
from TRADELE.filters.swing_helpers import (
    _client_lock,
    _fetch_candles,
    _return_pct,
    get_index_return_pct,
)
from TRADELE.filters.universe import load_symbol_company_map, load_symbol_industry_map
from TRADELE.services.zerodha_client import ZerodhaClient

logger = logging.getLogger(__name__)

CALC = IndicatorCalculator()
QUOTE_BATCH = 400


def batch_quote_details(client: ZerodhaClient, symbols: list[str]) -> dict[str, dict[str, Any]]:
    """Batch Zerodha quotes: ltp, change_pct."""
    out: dict[str, dict[str, Any]] = {}
    for i in range(0, len(symbols), QUOTE_BATCH):
        chunk = symbols[i : i + QUOTE_BATCH]
        keys = [f"NSE:{s}" for s in chunk]
        try:
            with _client_lock:
                quotes = client.get_quote(keys)
            for key, q in quotes.items():
                sym = key.split(":", 1)[-1]
                ohlc = q.get("ohlc") or {}
                prev = float(ohlc.get("close") or 0)
                ltp = float(q.get("last_price") or prev or 0)
                change_pct = round((ltp - prev) / prev * 100, 2) if prev else 0.0
                out[sym] = {"ltp": round(ltp, 2), "change_pct": change_pct}
        except Exception as e:
            logger.warning("Quote batch failed: %s", e)
        time.sleep(0.2)
    return out


def _avg_volume(candles: list[dict], days: int = 20) -> Optional[float]:
    if not candles:
        return None
    vols = [float(c.get("volume") or 0) for c in candles[-days:]]
    return sum(vols) / len(vols) if vols else None


def _dist_52w_high_pct(close: float, high_52w: Optional[float]) -> Optional[float]:
    if not high_52w or high_52w <= 0:
        return None
    return round((high_52w - close) / high_52w * 100, 2)


def _compute_sector_ranks(
    symbol_returns: dict[str, float],
    industry_map: dict[str, str],
) -> tuple[dict[str, int], dict[str, float], int]:
    """Sector rank (1=best) and sector 10d return per symbol."""
    sector_returns: dict[str, list[float]] = defaultdict(list)
    sym_sector: dict[str, str] = {}
    for sym, ret in symbol_returns.items():
        sector = industry_map.get(sym, "Unknown")
        sym_sector[sym] = sector
        sector_returns[sector].append(ret)

    sector_avg = {
        s: round(sum(v) / len(v), 2) for s, v in sector_returns.items() if v
    }
    ranked = sorted(sector_avg.items(), key=lambda x: x[1], reverse=True)
    sector_rank_map = {s: i + 1 for i, (s, _) in enumerate(ranked)}
    total = len(ranked)

    sym_rank: dict[str, int] = {}
    sym_sec_ret: dict[str, float] = {}
    for sym in symbol_returns:
        sec = sym_sector[sym]
        sym_rank[sym] = sector_rank_map.get(sec, total)
        sym_sec_ret[sym] = sector_avg.get(sec, 0.0)
    return sym_rank, sym_sec_ret, total


def _build_one_symbol(
    sym: str,
    client: ZerodhaClient,
    nifty_ret: float,
    delivery_today: dict[str, float],
    delivery_yest: dict[str, float],
    quotes: dict[str, dict[str, Any]],
    company_map: dict[str, str],
    industry_map: dict[str, str],
) -> Optional[dict[str, Any]]:
    try:
        candles = _fetch_candles(client, sym, 400)
        if len(candles) < 25:
            return None
        indicators = CALC.compute(sym, candles)
        if not indicators:
            return None

        closes = [float(c["close"]) for c in candles]
        close = float(indicators["close"])
        ret5 = _return_pct(closes, 5)
        ret10 = _return_pct(closes, 10)
        ret20 = _return_pct(closes, 20)
        rel_str = round(ret20 - nifty_ret, 2) if ret20 is not None else None

        del_today = delivery_today.get(sym)
        del_yest = delivery_yest.get(sym)
        del_change = round(del_today - del_yest, 2) if del_today is not None and del_yest is not None else None

        q = quotes.get(sym, {})
        ltp = q.get("ltp") or close
        high_20d = indicators.get("high_20d")
        high_52w = indicators.get("high_52w")
        breakout = bool(high_20d and close >= float(high_20d) * 0.995)

        return {
            "symbol": sym,
            "company": company_map.get(sym, sym),
            "industry": industry_map.get(sym, "Unknown"),
            "close": close,
            "ltp": ltp,
            "change_pct": q.get("change_pct", indicators.get("change_pct")),
            "return_5d_pct": ret5,
            "return_10d_pct": ret10,
            "return_20d_pct": ret20,
            "volume_ratio": indicators.get("volume_ratio"),
            "avg_daily_volume": round(_avg_volume(candles) or 0, 0),
            "delivery_pct": del_today,
            "delivery_change_pct": del_change,
            "rsi": indicators.get("rsi"),
            "adx": indicators.get("adx"),
            "atr": indicators.get("atr"),
            "ema_20": indicators.get("ema_20"),
            "ema_50": indicators.get("ema_50"),
            "ema_200": indicators.get("ema_200"),
            "high_20d": high_20d,
            "high_52w": high_52w,
            "dist_52w_high_pct": _dist_52w_high_pct(close, high_52w),
            "breakout": breakout,
            "relative_strength_pct": rel_str,
            "nifty_return_20d_pct": nifty_ret,
        }
    except Exception as e:
        logger.debug("Metrics failed for %s: %s", sym, e)
        return None


def build_symbol_metrics(
    client: ZerodhaClient,
    symbols: list[str],
    news_by_symbol: Optional[dict[str, dict[str, Any]]] = None,
    max_workers: int = 4,
) -> list[dict[str, Any]]:
    """Fetch and compute full metrics + stock score for universe symbols."""
    if not symbols:
        return []

    company_map = load_symbol_company_map()
    industry_map = load_symbol_industry_map()
    nifty_ret = get_index_return_pct(client, 20) or 0.0

    delivery_map = fetch_delivery_map()
    snapshots = fetch_delivery_snapshots()
    delivery_yest: dict[str, float] = {}
    if len(snapshots) >= 2:
        delivery_yest = {s: v["delivery_pct"] for s, v in snapshots[1][1].items()}
    delivery_today = delivery_map or (
        {s: v["delivery_pct"] for s, v in snapshots[0][1].items()} if snapshots else {}
    )

    quotes = batch_quote_details(client, symbols)
    raw_metrics: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(
                _build_one_symbol,
                sym,
                client,
                nifty_ret,
                delivery_today,
                delivery_yest,
                quotes,
                company_map,
                industry_map,
            ): sym
            for sym in symbols
        }
        for fut in as_completed(futures):
            row = fut.result()
            if row:
                raw_metrics.append(row)

    ret10_map = {m["symbol"]: m["return_10d_pct"] or 0 for m in raw_metrics}
    sector_rank_map, sector_ret_map, total_sectors = _compute_sector_ranks(ret10_map, industry_map)

    news_by_symbol = news_by_symbol or {}
    results: list[dict[str, Any]] = []
    for m in raw_metrics:
        sym = m["symbol"]
        news = news_by_symbol.get(sym, {})
        m["sector"] = m["industry"]
        m["sector_rank"] = sector_rank_map.get(sym)
        m["sector_return_10d_pct"] = sector_ret_map.get(sym)
        m["total_sectors"] = total_sectors
        m["news_sentiment"] = news.get("sentiment")
        m["news_score"] = news.get("score")

        scored = compute_stock_score(m)
        m["score"] = scored["score"]
        m["score_components"] = scored["components"]
        results.append(m)

    results.sort(key=lambda r: r.get("score", 0), reverse=True)
    for i, r in enumerate(results, 1):
        r["rank"] = i
    return results
