"""Compute stock scores from saved swing tab results in DB (no live fetch)."""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from TRADELE.filters.stock_score import SCORE_WEIGHTS, compute_stock_score
from TRADELE.filters.swing_definitions import (
    TAB_DASHBOARD,
    TAB_DELIVERY_PERCENTAGE,
    TAB_INSTITUTIONAL,
    TAB_NEWS_SENTIMENT,
    TAB_PRICE_MOMENTUM,
    TAB_SECTOR_STRENGTH,
    TAB_UNIVERSE,
    TAB_VOLUME_EXPLOSION,
)
from TRADELE.db.models import SwingScanResult, SwingScanRun
from TRADELE.filters.stock_score import SCORE_WEIGHTS, compute_stock_score
from TRADELE.filters.swing_definitions import (
    TAB_DASHBOARD,
    TAB_DELIVERY_PERCENTAGE,
    TAB_INSTITUTIONAL,
    TAB_NEWS_SENTIMENT,
    TAB_PRICE_MOMENTUM,
    TAB_SECTOR_STRENGTH,
    TAB_UNIVERSE,
    TAB_VOLUME_EXPLOSION,
)


def _load_tab_stocks(db: Session, tab: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load latest successful scan rows for a tab without importing swing_scan_store."""
    run = (
        db.query(SwingScanRun)
        .filter(SwingScanRun.tab == tab, SwingScanRun.status == "success")
        .order_by(SwingScanRun.finished_at.desc())
        .first()
    )
    if not run:
        return [], {}
    rows = db.query(SwingScanResult).filter(SwingScanResult.run_id == run.id).all()
    stocks = []
    for row in rows:
        item: dict[str, Any] = {
            "symbol": row.symbol,
            "price": row.price,
            "market_cap_cr": row.market_cap_cr,
            "avg_daily_volume": row.avg_daily_volume,
            "delivery_pct": row.delivery_pct,
            "is_circuit": row.is_circuit,
        }
        if row.extra:
            item["extra"] = row.extra
        stocks.append(item)
    return stocks, run.metadata_ or {}


def _by_symbol(stocks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {s["symbol"]: s for s in stocks if s.get("symbol")}


def _merge_metrics(
    symbol: str,
    universe: dict[str, Any],
    dashboard: Optional[dict[str, Any]],
    price_momentum: Optional[dict[str, Any]],
    volume: Optional[dict[str, Any]],
    institutional: Optional[dict[str, Any]],
    news: Optional[dict[str, Any]],
    delivery: Optional[dict[str, Any]],
    sector: Optional[dict[str, Any]],
    total_sectors: int,
) -> dict[str, Any]:
    """Merge fields from all available tab rows for one symbol."""
    m: dict[str, Any] = {"symbol": symbol}
    u_extra = universe.get("extra") or {}

    close = universe.get("price")
    m["close"] = close
    m["ltp"] = close
    m["delivery_pct"] = universe.get("delivery_pct")
    m["avg_daily_volume"] = universe.get("avg_daily_volume")
    m["delivery_change_pct"] = u_extra.get("delivery_change_pct")

    if dashboard:
        dex = dashboard.get("extra") or {}
        m["close"] = dex.get("ltp") or close
        m["ltp"] = dex.get("ltp") or close
        for key in (
            "return_5d_pct", "return_10d_pct", "return_20d_pct",
            "volume_ratio", "delivery_pct", "rsi", "adx", "atr",
            "ema_20", "ema_50", "ema_200", "dist_52w_high_pct",
            "breakout", "relative_strength_pct", "sector_rank",
            "change_pct",
        ):
            if dex.get(key) is not None:
                m[key] = dex[key]
        if dex.get("momentum_score") is not None:
            m["news_score"] = dex.get("news_score")

    if price_momentum:
        ex = price_momentum.get("extra") or {}
        for key in ("return_5d_pct", "return_10d_pct", "return_20d_pct", "ema_20", "ema_50", "dist_52w_high_pct"):
            if ex.get(key) is not None:
                m[key] = ex[key]

    if volume:
        ex = volume.get("extra") or {}
        if ex.get("volume_ratio") is not None:
            m["volume_ratio"] = ex["volume_ratio"]

    if institutional:
        ex = institutional.get("extra") or {}
        if ex.get("volume_ratio") is not None:
            m["volume_ratio"] = ex["volume_ratio"]
        if institutional.get("delivery_pct") is not None:
            m["delivery_pct"] = institutional["delivery_pct"]
        if ex.get("ema_20") is not None:
            m["ema_20"] = ex["ema_20"]

    if delivery:
        ex = delivery.get("extra") or {}
        for key in (
            "delivery_change_pct", "relative_strength_pct",
            "ema_20", "ema_50", "ema_200", "stock_return_20d_pct",
        ):
            if ex.get(key) is not None:
                m[key] = ex[key]
        if delivery.get("delivery_pct") is not None:
            m["delivery_pct"] = delivery["delivery_pct"]
        if ex.get("stock_return_20d_pct") is not None and m.get("return_20d_pct") is None:
            m["return_20d_pct"] = ex["stock_return_20d_pct"]

    if sector:
        ex = sector.get("extra") or {}
        if ex.get("sector_rank") is not None:
            m["sector_rank"] = ex["sector_rank"]
        if ex.get("stock_return_10d_pct") is not None and m.get("return_10d_pct") is None:
            m["return_10d_pct"] = ex["stock_return_10d_pct"]

    if news:
        ex = news.get("extra") or {}
        if ex.get("sentiment") is not None:
            m["news_sentiment"] = ex["sentiment"]
        if ex.get("score") is not None:
            m["news_score"] = ex["score"]

    m["total_sectors"] = total_sectors
    return m


def compute_stock_scores_from_db(db: Session, symbols: list[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Build scores for universe symbols using whatever tab data exists in DB.
    No Zerodha/NSE fetch — recalculates from saved scan results only.
    """
    universe_stocks, _ = _load_tab_stocks(db, TAB_UNIVERSE)
    universe_map = _by_symbol(universe_stocks)

    if not universe_map and not symbols:
        return [], {"error": "no_universe", "message": "Run Universe scan first."}

    target_symbols = symbols or list(universe_map.keys())

    dash_map = _by_symbol(_load_tab_stocks(db, TAB_DASHBOARD)[0])
    pm_map = _by_symbol(_load_tab_stocks(db, TAB_PRICE_MOMENTUM)[0])
    vol_map = _by_symbol(_load_tab_stocks(db, TAB_VOLUME_EXPLOSION)[0])
    inst_map = _by_symbol(_load_tab_stocks(db, TAB_INSTITUTIONAL)[0])
    news_map = _by_symbol(_load_tab_stocks(db, TAB_NEWS_SENTIMENT)[0])
    del_map = _by_symbol(_load_tab_stocks(db, TAB_DELIVERY_PERCENTAGE)[0])
    sec_stocks, sec_meta = _load_tab_stocks(db, TAB_SECTOR_STRENGTH)
    sec_map = _by_symbol(sec_stocks)
    total_sectors = int(sec_meta.get("sectors_tracked") or 1)

    sources_used = {
        "universe": bool(universe_map),
        "dashboard": bool(dash_map),
        "price_momentum": bool(pm_map),
        "volume_explosion": bool(vol_map),
        "institutional_buying": bool(inst_map),
        "news_sentiment": bool(news_map),
        "delivery_percentage": bool(del_map),
        "sector_strength": bool(sec_map),
    }

    results: list[dict[str, Any]] = []
    for sym in target_symbols:
        universe_row = universe_map.get(sym)
        if not universe_row:
            continue

        metrics = _merge_metrics(
            sym,
            universe_row,
            dash_map.get(sym),
            pm_map.get(sym),
            vol_map.get(sym),
            inst_map.get(sym),
            news_map.get(sym),
            del_map.get(sym),
            sec_map.get(sym),
            total_sectors,
        )
        scored = compute_stock_score(metrics)
        metrics["score"] = scored["score"]
        metrics["score_components"] = scored["components"]
        metrics["active_weights"] = scored["active_weights"]
        results.append(metrics)

    results.sort(key=lambda r: r.get("score", 0), reverse=True)
    for i, r in enumerate(results, 1):
        r["rank"] = i

    return results, {
        "universe_count": len(target_symbols),
        "matched": len(results),
        "weights": SCORE_WEIGHTS,
        "sources_used": sources_used,
        "top_score": results[0]["score"] if results else None,
        "note": "Calculated from saved DB results — no live fetch.",
    }
