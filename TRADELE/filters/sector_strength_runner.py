"""Sector Strength swing tab — prefer stocks in strongest sectors."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from TRADELE.filters.swing_definitions import TAB_SECTOR_STRENGTH, filter_tooltip_dict
from TRADELE.filters.swing_helpers import _fetch_candles, _return_pct, check_zerodha
from TRADELE.filters.universe import load_symbol_industry_map
from TRADELE.engines.indicators.calculator import IndicatorCalculator

CALC = IndicatorCalculator()
SECTOR_LOOKBACK_DAYS = 10
TOP_SECTOR_PERCENTILE = 0.5  # top half of sectors by return


def run_sector_strength_scan(symbols: list[str]) -> dict[str, Any]:
    client, err = check_zerodha()
    if err:
        return {
            "tab": TAB_SECTOR_STRENGTH,
            "filter": filter_tooltip_dict(TAB_SECTOR_STRENGTH),
            "stocks": [],
            "meta": err,
        }

    if not symbols:
        return {
            "tab": TAB_SECTOR_STRENGTH,
            "filter": filter_tooltip_dict(TAB_SECTOR_STRENGTH),
            "stocks": [],
            "meta": {"error": "no_universe", "message": "Run Universe scan first."},
        }

    industry_map = load_symbol_industry_map()
    stock_returns: dict[str, dict[str, Any]] = {}

    for sym in symbols:
        try:
            candles = _fetch_candles(client, sym, 60)
            if len(candles) < SECTOR_LOOKBACK_DAYS + 1:
                continue
            closes = [float(c["close"]) for c in candles]
            ret_10d = _return_pct(closes, SECTOR_LOOKBACK_DAYS)
            if ret_10d is None:
                continue
            indicators = CALC.compute(sym, candles)
            stock_returns[sym] = {
                "return_10d_pct": ret_10d,
                "price": round(closes[-1], 2),
                "industry": industry_map.get(sym, "Unknown"),
                "indicators": indicators or {},
            }
        except Exception:
            continue

    if not stock_returns:
        return {
            "tab": TAB_SECTOR_STRENGTH,
            "filter": filter_tooltip_dict(TAB_SECTOR_STRENGTH),
            "stocks": [],
            "meta": {"error": "scan_failed", "message": "Could not compute returns for universe symbols."},
        }

    sector_returns: dict[str, list[float]] = defaultdict(list)
    for sym, data in stock_returns.items():
        sector_returns[data["industry"]].append(data["return_10d_pct"])

    sector_avg = {
        sector: round(sum(vals) / len(vals), 2)
        for sector, vals in sector_returns.items()
        if vals
    }
    if not sector_avg:
        return {
            "tab": TAB_SECTOR_STRENGTH,
            "filter": filter_tooltip_dict(TAB_SECTOR_STRENGTH),
            "stocks": [],
            "meta": {"error": "no_sectors", "message": "No sector data available."},
        }

    ranked_sectors = sorted(sector_avg.items(), key=lambda x: x[1], reverse=True)
    cutoff_idx = max(1, int(len(ranked_sectors) * TOP_SECTOR_PERCENTILE))
    strong_sectors = {s for s, _ in ranked_sectors[:cutoff_idx]}

    stocks: list[dict[str, Any]] = []
    for sym, data in stock_returns.items():
        industry = data["industry"]
        sec_ret = sector_avg.get(industry)
        if sec_ret is None or industry not in strong_sectors:
            continue
        stocks.append({
            "symbol": sym,
            "price": data["price"],
            "extra": {
                "sector": industry,
                "sector_return_10d_pct": sec_ret,
                "stock_return_10d_pct": data["return_10d_pct"],
                "sector_rank": next(
                    i + 1 for i, (s, _) in enumerate(ranked_sectors) if s == industry
                ),
            },
        })

    stocks.sort(
        key=lambda r: (
            r.get("extra", {}).get("sector_return_10d_pct", 0),
            r.get("extra", {}).get("stock_return_10d_pct", 0),
        ),
        reverse=True,
    )

    sector_summary = [
        {"sector": s, "return_10d_pct": v} for s, v in ranked_sectors[:10]
    ]

    return {
        "tab": TAB_SECTOR_STRENGTH,
        "filter": filter_tooltip_dict(TAB_SECTOR_STRENGTH),
        "stocks": stocks,
        "meta": {
            "universe_count": len(symbols),
            "matched": len(stocks),
            "sectors_tracked": len(sector_avg),
            "top_sectors": sector_summary,
            "note": "Stocks filtered to top-performing sectors (10-day return).",
        },
    }
