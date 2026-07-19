"""Stock Score swing tab — weighted composite from saved DB results."""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from TRADELE.filters.stock_score import SCORE_WEIGHTS
from TRADELE.filters.stock_score_from_db import compute_stock_scores_from_db
from TRADELE.filters.swing_definitions import TAB_STOCK_SCORE, filter_tooltip_dict


def _metrics_to_row(m: dict[str, Any]) -> dict[str, Any]:
    extra = {
        "rank": m.get("rank"),
        "score": m.get("score"),
        "score_components": m.get("score_components"),
        "active_weights": m.get("active_weights"),
        "weights": SCORE_WEIGHTS,
        "return_5d_pct": m.get("return_5d_pct"),
        "return_10d_pct": m.get("return_10d_pct"),
        "return_20d_pct": m.get("return_20d_pct"),
        "relative_strength_pct": m.get("relative_strength_pct"),
        "volume_ratio": m.get("volume_ratio"),
        "delivery_pct": m.get("delivery_pct"),
        "sector_rank": m.get("sector_rank"),
        "news_sentiment": m.get("news_sentiment"),
    }
    return {
        "symbol": m["symbol"],
        "price": m.get("ltp") or m.get("close"),
        "delivery_pct": m.get("delivery_pct"),
        "avg_daily_volume": m.get("avg_daily_volume"),
        "extra": extra,
    }


def run_stock_score_scan(
    symbols: list[str],
    db: Optional[Session] = None,
    news_by_symbol: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Recalculate scores from DB — no live Zerodha/NSE fetch."""
    if db is None:
        return {
            "tab": TAB_STOCK_SCORE,
            "filter": filter_tooltip_dict(TAB_STOCK_SCORE),
            "stocks": [],
            "meta": {"error": "no_db", "message": "Database session required."},
        }

    metrics_list, meta = compute_stock_scores_from_db(db, symbols)
    if meta.get("error"):
        return {
            "tab": TAB_STOCK_SCORE,
            "filter": filter_tooltip_dict(TAB_STOCK_SCORE),
            "stocks": [],
            "meta": meta,
        }

    stocks = [_metrics_to_row(m) for m in metrics_list]
    meta["weights"] = SCORE_WEIGHTS

    return {
        "tab": TAB_STOCK_SCORE,
        "filter": filter_tooltip_dict(TAB_STOCK_SCORE),
        "stocks": stocks,
        "meta": meta,
    }
