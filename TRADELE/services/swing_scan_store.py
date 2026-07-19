"""Persist and load latest swing tab scan results."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from sqlalchemy.orm import Session

from TRADELE.db.models import SwingScanResult, SwingScanRun
from TRADELE.filters.definitions import FILTER_PHASE_1, filter_to_dict
from TRADELE.filters.dashboard_runner import run_dashboard_scan
from TRADELE.filters.delivery_percentage_runner import run_delivery_percentage_scan
from TRADELE.filters.institutional_runner import run_institutional_scan
from TRADELE.filters.news_sentiment_runner import run_news_sentiment_scan
from TRADELE.filters.phase1_runner import run_phase1_filter
from TRADELE.filters.price_momentum_runner import run_price_momentum_scan
from TRADELE.filters.sector_strength_runner import run_sector_strength_scan
from TRADELE.filters.stock_score_runner import run_stock_score_scan
from TRADELE.filters.swing_definitions import (
    PARALLEL_SCAN_TABS,
    TAB_DASHBOARD,
    TAB_DELIVERY_PERCENTAGE,
    TAB_INSTITUTIONAL,
    TAB_NEWS_SENTIMENT,
    TAB_PRICE_MOMENTUM,
    TAB_SECTOR_STRENGTH,
    TAB_STOCK_SCORE,
    TAB_UNIVERSE,
    TAB_VOLUME_EXPLOSION,
    filter_tooltip_dict,
)
from TRADELE.filters.swing_helpers import get_universe_symbols
from TRADELE.filters.volume_explosion_runner import run_volume_explosion_scan

TAB_RUNNERS: dict[str, Callable[..., dict[str, Any]]] = {
    TAB_UNIVERSE: lambda _syms, max_symbols=400, **_: run_phase1_filter(max_symbols=max_symbols),
    TAB_DASHBOARD: run_dashboard_scan,
    TAB_STOCK_SCORE: run_stock_score_scan,
    TAB_PRICE_MOMENTUM: run_price_momentum_scan,
    TAB_VOLUME_EXPLOSION: run_volume_explosion_scan,
    TAB_INSTITUTIONAL: run_institutional_scan,
    TAB_NEWS_SENTIMENT: run_news_sentiment_scan,
    TAB_DELIVERY_PERCENTAGE: run_delivery_percentage_scan,
    TAB_SECTOR_STRENGTH: run_sector_strength_scan,
}


def _load_news_map(db: Session) -> dict[str, dict[str, Any]]:
    res = get_tab_results(db, TAB_NEWS_SENTIMENT)
    out: dict[str, dict[str, Any]] = {}
    for s in res.get("stocks") or []:
        extra = s.get("extra") or {}
        out[s["symbol"]] = {
            "sentiment": extra.get("sentiment"),
            "score": extra.get("score"),
        }
    return out


def _row_to_dict(row: SwingScanResult) -> dict[str, Any]:
    out: dict[str, Any] = {
        "symbol": row.symbol,
        "price": row.price,
        "market_cap_cr": row.market_cap_cr,
        "avg_daily_volume": row.avg_daily_volume,
        "delivery_pct": row.delivery_pct,
        "is_circuit": row.is_circuit,
    }
    if row.extra:
        out["extra"] = row.extra
    return out


def _run_to_dict(run: SwingScanRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "tab": run.tab,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "status": run.status,
        "error_message": run.error_message,
    }


def _filter_for_tab(tab: str) -> dict[str, Any]:
    if tab == TAB_UNIVERSE:
        return filter_to_dict(FILTER_PHASE_1)
    return filter_tooltip_dict(tab)


def _delete_tab_runs(db: Session, tab: str) -> None:
    runs = db.query(SwingScanRun).filter(SwingScanRun.tab == tab).all()
    for run in runs:
        db.query(SwingScanResult).filter(SwingScanResult.run_id == run.id).delete()
        db.delete(run)


def _save_scan(db: Session, tab: str, payload: dict[str, Any], started: datetime) -> dict[str, Any]:
    stocks = payload.get("stocks") or []
    meta = payload.get("meta") or {}
    _delete_tab_runs(db, tab)

    run = SwingScanRun(
        tab=tab,
        started_at=started,
        finished_at=datetime.utcnow(),
        status="success",
        metadata_=meta,
    )
    db.add(run)
    db.flush()

    for stock in stocks:
        extra = stock.get("extra")
        db.add(
            SwingScanResult(
                run_id=run.id,
                symbol=stock["symbol"],
                price=stock.get("price"),
                market_cap_cr=stock.get("market_cap_cr"),
                avg_daily_volume=stock.get("avg_daily_volume"),
                delivery_pct=stock.get("delivery_pct"),
                is_circuit=bool(stock.get("is_circuit", False)),
                extra=extra,
            )
        )
    db.commit()
    db.refresh(run)

    return {
        "tab": tab,
        "filter": payload.get("filter", _filter_for_tab(tab)),
        "stocks": stocks,
        "meta": meta,
        "run": _run_to_dict(run),
    }


def get_tab_results(db: Session, tab: str) -> dict[str, Any]:
    run = (
        db.query(SwingScanRun)
        .filter(SwingScanRun.tab == tab, SwingScanRun.status == "success")
        .order_by(SwingScanRun.finished_at.desc())
        .first()
    )
    if not run:
        return {"tab": tab, "filter": _filter_for_tab(tab), "stocks": [], "meta": {}, "run": None}

    rows = db.query(SwingScanResult).filter(SwingScanResult.run_id == run.id).all()
    return {
        "tab": tab,
        "filter": _filter_for_tab(tab),
        "stocks": [_row_to_dict(r) for r in rows],
        "meta": run.metadata_ or {},
        "run": _run_to_dict(run),
    }


def get_universe_results(db: Session) -> dict[str, Any]:
    return get_tab_results(db, TAB_UNIVERSE)


def run_and_save_tab_scan(db: Session, tab: str, max_symbols: int = 400) -> dict[str, Any]:
    started = datetime.utcnow()
    runner = TAB_RUNNERS.get(tab)
    if not runner:
        return {
            "tab": tab,
            "filter": _filter_for_tab(tab),
            "stocks": [],
            "meta": {"error": "unknown_tab", "message": f"Unknown tab: {tab}"},
            "run": None,
        }

    if tab == TAB_UNIVERSE:
        payload = runner([], max_symbols=max_symbols)
    else:
        symbols = get_universe_symbols(db)
        if tab == TAB_STOCK_SCORE:
            payload = runner(symbols, db=db)
        elif tab == TAB_DASHBOARD:
            news = _load_news_map(db)
            payload = runner(symbols, news_by_symbol=news)
        else:
            payload = runner(symbols)

    if payload.get("meta", {}).get("error"):
        return {
            "tab": tab,
            "filter": payload.get("filter", _filter_for_tab(tab)),
            "stocks": [],
            "meta": payload.get("meta", {}),
            "run": None,
        }

    return _save_scan(db, tab, payload, started)


def run_and_save_universe_scan(db: Session, max_symbols: int = 400) -> dict[str, Any]:
    return run_and_save_tab_scan(db, TAB_UNIVERSE, max_symbols=max_symbols)


def run_refresh_all(db: Session, max_symbols: int = 400) -> dict[str, Any]:
    """
    Full refresh: Universe → parallel filter tabs → Stock Score → Dashboard.
    Returns dashboard payload plus per-step summary.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from TRADELE.db.session import SessionLocal

    started = datetime.utcnow()
    step_summary: dict[str, Any] = {}

    universe_result = run_and_save_tab_scan(db, TAB_UNIVERSE, max_symbols=max_symbols)
    step_summary[TAB_UNIVERSE] = _step_meta(universe_result)
    if universe_result.get("meta", {}).get("error"):
        return {
            "status": "failed",
            "message": universe_result.get("meta", {}).get("message", "Universe scan failed."),
            "steps": step_summary,
            "dashboard": None,
            "started_at": started.isoformat(),
            "finished_at": datetime.utcnow().isoformat(),
        }

    def _run_tab_in_session(tab_id: str) -> tuple[str, dict[str, Any]]:
        sess = SessionLocal()
        try:
            return tab_id, run_and_save_tab_scan(sess, tab_id)
        finally:
            sess.close()

    with ThreadPoolExecutor(max_workers=len(PARALLEL_SCAN_TABS)) as pool:
        futures = [pool.submit(_run_tab_in_session, t) for t in PARALLEL_SCAN_TABS]
        for fut in as_completed(futures):
            tab_id, result = fut.result()
            step_summary[tab_id] = _step_meta(result)

    score_result = run_and_save_tab_scan(db, TAB_STOCK_SCORE)
    step_summary[TAB_STOCK_SCORE] = _step_meta(score_result)

    dashboard_result = run_and_save_tab_scan(db, TAB_DASHBOARD)
    step_summary[TAB_DASHBOARD] = _step_meta(dashboard_result)

    failed = [k for k, v in step_summary.items() if v.get("error")]

    return {
        "status": "success" if not failed else "partial",
        "steps": step_summary,
        "dashboard": dashboard_result,
        "stock_score": score_result,
        "started_at": started.isoformat(),
        "finished_at": datetime.utcnow().isoformat(),
        "failed_steps": failed,
    }


def _step_meta(result: dict[str, Any]) -> dict[str, Any]:
    meta = result.get("meta") or {}
    return {
        "matched": meta.get("matched"),
        "error": meta.get("error"),
        "message": meta.get("message"),
        "run_id": (result.get("run") or {}).get("id"),
    }
