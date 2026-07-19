"""Price Momentum swing tab scanner."""
from __future__ import annotations

from typing import Any, Optional

from TRADELE.filters.swing_definitions import TAB_PRICE_MOMENTUM, filter_tooltip_dict
from TRADELE.filters.swing_helpers import _return_pct, check_zerodha, scan_symbols


def _evaluate(symbol: str, candles: list[dict], indicators: dict[str, Any]) -> Optional[dict[str, Any]]:
    closes = [float(c["close"]) for c in candles]
    r5 = _return_pct(closes, 5)
    r10 = _return_pct(closes, 10)
    r20 = _return_pct(closes, 20)
    if r5 is None or r5 <= 5:
        return None
    if r10 is None or r10 <= 8:
        return None
    if r20 is None or r20 <= 15:
        return None

    close = float(indicators["close"])
    ema20 = indicators.get("ema_20")
    ema50 = indicators.get("ema_50")
    high_52w = indicators.get("high_52w")
    if ema20 is None or close <= ema20:
        return None
    if ema50 is None or close <= ema50:
        return None
    if not high_52w:
        return None
    dist_from_high = (float(high_52w) - close) / float(high_52w) * 100
    if dist_from_high >= 10:
        return None

    return {
        "symbol": symbol,
        "price": round(close, 2),
        "extra": {
            "return_5d_pct": r5,
            "return_10d_pct": r10,
            "return_20d_pct": r20,
            "ema_20": ema20,
            "ema_50": ema50,
            "dist_52w_high_pct": round(dist_from_high, 2),
        },
    }


def run_price_momentum_scan(symbols: list[str]) -> dict[str, Any]:
    client, err = check_zerodha()
    if err:
        return {"tab": TAB_PRICE_MOMENTUM, "filter": filter_tooltip_dict(TAB_PRICE_MOMENTUM), "stocks": [], "meta": err}

    if not symbols:
        return {
            "tab": TAB_PRICE_MOMENTUM,
            "filter": filter_tooltip_dict(TAB_PRICE_MOMENTUM),
            "stocks": [],
            "meta": {"error": "no_universe", "message": "Run Universe scan first."},
        }

    stocks = scan_symbols(client, symbols, _evaluate, lookback_days=400)
    stocks.sort(key=lambda r: r.get("extra", {}).get("return_20d_pct", 0), reverse=True)
    return {
        "tab": TAB_PRICE_MOMENTUM,
        "filter": filter_tooltip_dict(TAB_PRICE_MOMENTUM),
        "stocks": stocks,
        "meta": {"universe_count": len(symbols), "matched": len(stocks)},
    }
