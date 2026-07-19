"""Institutional Buying swing tab scanner (NSE delivery + flow proxies)."""
from __future__ import annotations

from typing import Any, Optional

from TRADELE.filters.nse_data import fetch_delivery_map
from TRADELE.filters.swing_definitions import TAB_INSTITUTIONAL, filter_tooltip_dict
from TRADELE.filters.swing_helpers import check_zerodha, scan_symbols


def _evaluate(
    symbol: str,
    candles: list[dict],
    indicators: dict[str, Any],
    delivery_map: dict[str, float],
) -> Optional[dict[str, Any]]:
    delivery = delivery_map.get(symbol)
    if delivery is None or delivery <= 40:
        return None

    cmf = indicators.get("cmf")
    if cmf is None or float(cmf) <= 0:
        return None

    close = float(indicators["close"])
    ema20 = indicators.get("ema_20")
    if ema20 is None or close <= ema20:
        return None

    vol_ratio = indicators.get("volume_ratio")
    if vol_ratio is None or float(vol_ratio) < 1.2:
        return None

    return {
        "symbol": symbol,
        "price": round(close, 2),
        "delivery_pct": round(delivery, 2),
        "avg_daily_volume": indicators.get("volume"),
        "extra": {
            "cmf": round(float(cmf), 4),
            "volume_ratio": round(float(vol_ratio), 2),
            "ema_20": ema20,
            "data_note": "FII/MF/Promoter/OI require additional NSE/BSE feeds",
        },
    }


def run_institutional_scan(symbols: list[str]) -> dict[str, Any]:
    client, err = check_zerodha()
    if err:
        return {"tab": TAB_INSTITUTIONAL, "filter": filter_tooltip_dict(TAB_INSTITUTIONAL), "stocks": [], "meta": err}

    if not symbols:
        return {
            "tab": TAB_INSTITUTIONAL,
            "filter": filter_tooltip_dict(TAB_INSTITUTIONAL),
            "stocks": [],
            "meta": {"error": "no_universe", "message": "Run Universe scan first."},
        }

    delivery_map = fetch_delivery_map()
    if not delivery_map:
        return {
            "tab": TAB_INSTITUTIONAL,
            "filter": filter_tooltip_dict(TAB_INSTITUTIONAL),
            "stocks": [],
            "meta": {"error": "nse_data", "message": "Could not load NSE delivery data."},
        }

    def evaluator(sym: str, candles: list[dict], indicators: dict[str, Any]) -> Optional[dict[str, Any]]:
        return _evaluate(sym, candles, indicators, delivery_map)

    stocks = scan_symbols(client, symbols, evaluator, lookback_days=60)
    stocks.sort(key=lambda r: r.get("delivery_pct") or 0, reverse=True)
    return {
        "tab": TAB_INSTITUTIONAL,
        "filter": filter_tooltip_dict(TAB_INSTITUTIONAL),
        "stocks": stocks,
        "meta": {
            "universe_count": len(symbols),
            "matched": len(stocks),
            "note": "Using NSE delivery % and CMF proxy. FII/MF/Promoter/OI feeds not yet integrated.",
        },
    }
