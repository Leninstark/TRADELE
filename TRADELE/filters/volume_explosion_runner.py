"""Volume Explosion swing tab scanner."""
from __future__ import annotations

from typing import Any, Optional

from TRADELE.filters.swing_definitions import TAB_VOLUME_EXPLOSION, filter_tooltip_dict
from TRADELE.filters.swing_helpers import check_zerodha, scan_symbols


def _evaluate(symbol: str, candles: list[dict], indicators: dict[str, Any]) -> Optional[dict[str, Any]]:
    volumes = [float(c.get("volume", 0)) for c in candles]
    if len(volumes) < 20:
        return None

    vol_ratio = indicators.get("volume_ratio")
    if vol_ratio is None or float(vol_ratio) < 2:
        return None

    vol_5 = sum(volumes[-5:]) / 5
    vol_20 = sum(volumes[-20:]) / 20
    if vol_20 <= 0 or vol_5 <= vol_20:
        return None

    close = float(indicators["close"])
    vol_trend = round(vol_5 / vol_20, 2)

    return {
        "symbol": symbol,
        "price": round(close, 2),
        "avg_daily_volume": round(vol_20, 0),
        "extra": {
            "volume_ratio": round(float(vol_ratio), 2),
            "volume_trend": vol_trend,
            "today_volume": volumes[-1],
            "vol_5d_avg": round(vol_5, 0),
            "vol_20d_avg": round(vol_20, 0),
            "strong_3x": float(vol_ratio) >= 3,
        },
    }


def run_volume_explosion_scan(symbols: list[str]) -> dict[str, Any]:
    client, err = check_zerodha()
    if err:
        return {"tab": TAB_VOLUME_EXPLOSION, "filter": filter_tooltip_dict(TAB_VOLUME_EXPLOSION), "stocks": [], "meta": err}

    if not symbols:
        return {
            "tab": TAB_VOLUME_EXPLOSION,
            "filter": filter_tooltip_dict(TAB_VOLUME_EXPLOSION),
            "stocks": [],
            "meta": {"error": "no_universe", "message": "Run Universe scan first."},
        }

    stocks = scan_symbols(client, symbols, _evaluate, lookback_days=60)
    stocks.sort(key=lambda r: r.get("extra", {}).get("volume_ratio", 0), reverse=True)
    return {
        "tab": TAB_VOLUME_EXPLOSION,
        "filter": filter_tooltip_dict(TAB_VOLUME_EXPLOSION),
        "stocks": stocks,
        "meta": {"universe_count": len(symbols), "matched": len(stocks)},
    }
