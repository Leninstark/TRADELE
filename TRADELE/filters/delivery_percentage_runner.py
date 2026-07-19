"""Delivery Percentage swing tab — rising delivery, relative strength, trend quality."""
from __future__ import annotations

from typing import Any, Optional

from TRADELE.filters.nse_data import fetch_delivery_snapshots
from TRADELE.filters.swing_definitions import TAB_DELIVERY_PERCENTAGE, filter_tooltip_dict
from TRADELE.filters.swing_helpers import (
    _return_pct,
    check_zerodha,
    get_index_return_pct,
    scan_symbols,
)

MIN_RELATIVE_STRENGTH = 5.0
MIN_DELIVERY_TODAY = 35.0


def _evaluate(
    symbol: str,
    candles: list[dict],
    indicators: dict[str, Any],
    today_snap: dict[str, dict[str, float]],
    yest_snap: dict[str, dict[str, float]],
    nifty_return_20d: float,
) -> Optional[dict[str, Any]]:
    t = today_snap.get(symbol)
    y = yest_snap.get(symbol)
    if not t or not y:
        return None

    del_today = t["delivery_pct"]
    del_yest = y["delivery_pct"]
    vol_today = t["volume"]
    vol_yest = y["volume"]

    if del_today <= del_yest or del_today < MIN_DELIVERY_TODAY:
        return None
    if vol_today <= vol_yest:
        return None

    closes = [float(c["close"]) for c in candles]
    stock_ret_20d = _return_pct(closes, 20)
    if stock_ret_20d is None:
        return None
    relative_strength = round(stock_ret_20d - nifty_return_20d, 2)
    if relative_strength < MIN_RELATIVE_STRENGTH:
        return None

    close = float(indicators["close"])
    ema20 = indicators.get("ema_20")
    ema50 = indicators.get("ema_50")
    ema200 = indicators.get("ema_200")
    if ema20 is None or ema50 is None or ema200 is None:
        return None
    if not (close > ema20 > ema50 > ema200):
        return None

    return {
        "symbol": symbol,
        "price": round(close, 2),
        "delivery_pct": round(del_today, 2),
        "avg_daily_volume": round(vol_today, 0),
        "extra": {
            "delivery_yesterday_pct": round(del_yest, 2),
            "delivery_change_pct": round(del_today - del_yest, 2),
            "volume_today": vol_today,
            "volume_yesterday": vol_yest,
            "stock_return_20d_pct": stock_ret_20d,
            "nifty_return_20d_pct": nifty_return_20d,
            "relative_strength_pct": relative_strength,
            "ema_20": ema20,
            "ema_50": ema50,
            "ema_200": ema200,
            "perfect_trend": True,
        },
    }


def run_delivery_percentage_scan(symbols: list[str]) -> dict[str, Any]:
    client, err = check_zerodha()
    if err:
        return {
            "tab": TAB_DELIVERY_PERCENTAGE,
            "filter": filter_tooltip_dict(TAB_DELIVERY_PERCENTAGE),
            "stocks": [],
            "meta": err,
        }

    if not symbols:
        return {
            "tab": TAB_DELIVERY_PERCENTAGE,
            "filter": filter_tooltip_dict(TAB_DELIVERY_PERCENTAGE),
            "stocks": [],
            "meta": {"error": "no_universe", "message": "Run Universe scan first."},
        }

    snapshots = fetch_delivery_snapshots()
    if len(snapshots) < 2:
        return {
            "tab": TAB_DELIVERY_PERCENTAGE,
            "filter": filter_tooltip_dict(TAB_DELIVERY_PERCENTAGE),
            "stocks": [],
            "meta": {"error": "nse_data", "message": "Need 2 days of NSE bhavcopy for delivery comparison."},
        }

    _, today_snap = snapshots[0]
    _, yest_snap = snapshots[1]

    nifty_ret = get_index_return_pct(client, 20)
    if nifty_ret is None:
        nifty_ret = 0.0

    def evaluator(sym: str, candles: list[dict], indicators: dict[str, Any]) -> Optional[dict[str, Any]]:
        return _evaluate(sym, candles, indicators, today_snap, yest_snap, nifty_ret)

    stocks = scan_symbols(client, symbols, evaluator, lookback_days=400)
    stocks.sort(key=lambda r: r.get("extra", {}).get("relative_strength_pct", 0), reverse=True)

    return {
        "tab": TAB_DELIVERY_PERCENTAGE,
        "filter": filter_tooltip_dict(TAB_DELIVERY_PERCENTAGE),
        "stocks": stocks,
        "meta": {
            "universe_count": len(symbols),
            "matched": len(stocks),
            "nifty_return_20d_pct": nifty_ret,
            "bhavcopy_days": [snapshots[0][0], snapshots[1][0]],
        },
    }
