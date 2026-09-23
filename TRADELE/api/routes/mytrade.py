"""MyTrade — Groww P&L dashboard, calendar, journal, sync."""
from __future__ import annotations

import calendar
import logging
from datetime import date, datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from TRADELE.db.models import GrowwOrder, GrowwSyncRun, GrowwTrade, GrowwTradingDay
from TRADELE.db.session import get_db
from TRADELE.services.day_review import build_day_review, build_symbol_chart
from TRADELE.services.groww_sync import get_last_stored_date, sync_groww_for_user, today_ist
from TRADELE.services.groww_token_store import check_token_status
from TRADELE.services.journal_ingest import ingest_upload, list_journal_fills
from TRADELE.services.mytrade_analytics import build_dashboard_payload
from TRADELE.services.trader_dna import get_trader_dna, run_trader_dna

logger = logging.getLogger(__name__)
router = APIRouter()


def _parse_date(val: Optional[str], default: Optional[date] = None) -> Optional[date]:
    if not val:
        return default
    try:
        return date.fromisoformat(val[:10])
    except ValueError as e:
        raise HTTPException(400, f"Invalid date: {val}") from e


@router.get("/status")
def mytrade_status(username: str = Query("leninstark"), db: Session = Depends(get_db)):
    username = username.strip().lower()
    groww = check_token_status(db, username, live_check=False)
    last_date = get_last_stored_date(db, username)
    first_date = (
        db.query(func.min(GrowwTradingDay.trade_date))
        .filter(GrowwTradingDay.trade_date.isnot(None), GrowwTradingDay.username == username)
        .scalar()
    )
    last_sync = (
        db.query(GrowwSyncRun)
        .filter(GrowwSyncRun.username == username, GrowwSyncRun.status == "success")
        .order_by(GrowwSyncRun.finished_at.desc())
        .first()
    )
    day_count = (
        db.query(func.count(GrowwTradingDay.id))
        .filter(GrowwTradingDay.username == username)
        .scalar()
        or 0
    )
    return {
        "groww_connected": groww.get("connected", False),
        "groww_message": groww.get("message"),
        "username": username,
        "today": today_ist().isoformat(),
        "first_stored_date": first_date.isoformat() if first_date else None,
        "last_stored_date": last_date.isoformat() if last_date else None,
        "trading_days_stored": day_count,
        "last_sync_at": last_sync.finished_at.isoformat() if last_sync and last_sync.finished_at else None,
        "last_sync_orders": last_sync.orders_added if last_sync else 0,
        "last_sync_trades": last_sync.trades_added if last_sync else 0,
    }


@router.post("/refresh")
def mytrade_refresh(username: str = Query("leninstark"), db: Session = Depends(get_db)):
    """Fetch Groww data for dates not yet stored and append to tables."""
    result = sync_groww_for_user(db, username.strip().lower())
    if not result.get("ok"):
        raise HTTPException(400, result.get("error") or "Sync failed")
    return result


@router.get("/dashboard")
def mytrade_dashboard(username: str = Query("leninstark"), db: Session = Depends(get_db)):
    username = username.strip().lower()
    today = today_ist()

    days: list[GrowwTradingDay] = (
        db.query(GrowwTradingDay)
        .filter(GrowwTradingDay.username == username)
        .order_by(GrowwTradingDay.trade_date.desc())
        .all()
    )
    trades: list[GrowwTrade] = (
        db.query(GrowwTrade).filter(GrowwTrade.username == username).all()
    )
    orders: list[GrowwOrder] = (
        db.query(GrowwOrder).filter(GrowwOrder.username == username).all()
    )

    return build_dashboard_payload(
        username=username,
        trades=trades,
        orders=orders,
        days=days,
        today=today,
    )


@router.get("/calendar")
def mytrade_calendar(
    username: str = Query("leninstark"),
    month: str = Query(..., description="YYYY-MM"),
    style: str = Query(
        "intraday",
        description="intraday (equity MIS), swing (equity CNC/NRML), or fno (F&O segment)",
    ),
    db: Session = Depends(get_db),
):
    username = username.strip().lower()
    style_key = (style or "intraday").strip().lower()
    if style_key not in ("intraday", "swing", "fno"):
        raise HTTPException(400, "style must be intraday, swing, or fno")
    try:
        year_s, month_s = month.split("-", 1)
        year, mon = int(year_s), int(month_s)
        if mon < 1 or mon > 12:
            raise ValueError
    except ValueError as e:
        raise HTTPException(400, "month must be YYYY-MM") from e

    start = date(year, mon, 1)
    _, last_day = calendar.monthrange(year, mon)
    end = date(year, mon, last_day)

    rows: list[GrowwTradingDay] = (
        db.query(GrowwTradingDay)
        .filter(
            GrowwTradingDay.username == username,
            GrowwTradingDay.trade_date >= start,
            GrowwTradingDay.trade_date <= end,
        )
        .all()
    )
    by_date = {r.trade_date: r for r in rows}

    from TRADELE.services.mytrade_analytics import (
        filter_orders_for_style,
        filter_positions_for_style,
        filter_trades_for_style,
        fifo_realised_pnl_by_day_symbol,
        merge_day_style_pnl,
        products_for_calendar_style,
    )

    products = products_for_calendar_style(style_key)

    month_orders = (
        db.query(GrowwOrder)
        .filter(
            GrowwOrder.username == username,
            GrowwOrder.trade_date >= start,
            GrowwOrder.trade_date <= end,
        )
        .all()
    )
    style_orders = filter_orders_for_style(month_orders, style_key)
    orders_by_date: dict[date, int] = {}
    for o in style_orders:
        orders_by_date[o.trade_date] = orders_by_date.get(o.trade_date, 0) + 1

    # Fill-based FIFO (needs history before month start for swing cost basis)
    all_trades = (
        db.query(GrowwTrade)
        .filter(
            GrowwTrade.username == username,
            GrowwTrade.trade_date <= end,
        )
        .order_by(GrowwTrade.trade_date.asc(), GrowwTrade.id.asc())
        .all()
    )
    style_trades = filter_trades_for_style(all_trades, style_key)
    trade_pnl_by_day_symbol = fifo_realised_pnl_by_day_symbol(style_trades)

    days_out: list[dict[str, Any]] = []
    month_pnl = 0.0
    for day_num in range(1, last_day + 1):
        d = date(year, mon, day_num)
        row = by_date.get(d)
        order_count = orders_by_date.get(d, 0)
        positions = []
        if row and isinstance(row.summary, dict):
            positions = row.summary.get("positions") or []
        style_positions = filter_positions_for_style(positions, style_key)
        day_pnl = merge_day_style_pnl(
            positions=style_positions,
            products=products if products is not None else {"MIS", "CNC", "NRML"},
            fill_pnl_by_symbol=trade_pnl_by_day_symbol.get(d, {}),
        )

        has_data = bool(order_count or abs(day_pnl) > 0.009)
        if not has_data:
            days_out.append(
                {
                    "date": d.isoformat(),
                    "weekday": d.weekday(),
                    "realised_pnl": None,
                    "order_count": 0,
                    "trade_count": 0,
                    "has_data": False,
                }
            )
            continue

        month_pnl += day_pnl
        days_out.append(
            {
                "date": d.isoformat(),
                "weekday": d.weekday(),
                "realised_pnl": day_pnl,
                "order_count": order_count,
                "trade_count": row.trade_count if row else 0,
                "has_data": True,
            }
        )

    return {
        "username": username,
        "month": month,
        "style": style_key,
        "month_pnl": round(month_pnl, 2),
        "days": days_out,
    }


@router.get("/day-review")
def mytrade_day_review(
    date: str = Query(..., description="YYYY-MM-DD"),
    username: str = Query("leninstark"),
    style: str = Query("intraday"),
    force_refresh: bool = Query(False),
    db: Session = Depends(get_db),
):
    """Day overview: tickers + markers + AI. Candles load via /day-review/chart."""
    trade_date = _parse_date(date)
    if not trade_date:
        raise HTTPException(400, "date must be YYYY-MM-DD")
    style_norm = style.strip().lower()
    if style_norm not in ("intraday", "swing", "fno"):
        raise HTTPException(400, "style must be intraday, swing, or fno")
    result = build_day_review(
        db,
        username=username.strip().lower(),
        trade_date=trade_date,
        style=style_norm,  # type: ignore[arg-type]
        force_refresh=force_refresh,
    )
    if not result.get("ok"):
        raise HTTPException(404, result.get("error") or "No data for this day")
    return result


@router.get("/day-review/chart")
def mytrade_day_review_chart(
    date: str = Query(..., description="YYYY-MM-DD"),
    symbol: str = Query(..., description="Trading symbol"),
    username: str = Query("leninstark"),
    style: str = Query("intraday"),
    force_refresh: bool = Query(False),
    db: Session = Depends(get_db),
):
    """Lazy 1-min candles + VWAP/EMA/RSI + symbol-only coaching."""
    trade_date = _parse_date(date)
    if not trade_date:
        raise HTTPException(400, "date must be YYYY-MM-DD")
    style_norm = style.strip().lower()
    if style_norm not in ("intraday", "swing", "fno"):
        raise HTTPException(400, "style must be intraday, swing, or fno")
    result = build_symbol_chart(
        db,
        username=username.strip().lower(),
        trade_date=trade_date,
        symbol=symbol,
        style=style_norm,  # type: ignore[arg-type]
        force_refresh=force_refresh,
    )
    if not result.get("ok"):
        raise HTTPException(404, result.get("error") or "No chart data")
    return result


@router.get("/journal")
def mytrade_journal(
    username: str = Query("leninstark"),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    db: Session = Depends(get_db),
):
    username = username.strip().lower()
    start = _parse_date(from_date)
    end = _parse_date(to_date, today_ist())

    q_orders = db.query(GrowwOrder).filter(GrowwOrder.username == username)
    q_trades = db.query(GrowwTrade).filter(GrowwTrade.username == username)
    if start:
        q_orders = q_orders.filter(GrowwOrder.trade_date >= start)
        q_trades = q_trades.filter(GrowwTrade.trade_date >= start)
    if end:
        q_orders = q_orders.filter(GrowwOrder.trade_date <= end)
        q_trades = q_trades.filter(GrowwTrade.trade_date <= end)

    orders = q_orders.order_by(GrowwOrder.trade_date.desc(), GrowwOrder.synced_at.desc()).all()
    trades = q_trades.order_by(GrowwTrade.trade_date.desc(), GrowwTrade.synced_at.desc()).all()

    return {
        "username": username,
        "from": start.isoformat() if start else None,
        "to": end.isoformat() if end else None,
        "orders": [
            {
                "id": o.id,
                "trade_date": o.trade_date.isoformat(),
                "groww_order_id": o.groww_order_id,
                "trading_symbol": o.trading_symbol,
                "transaction_type": o.transaction_type,
                "quantity": o.quantity,
                "filled_quantity": o.filled_quantity,
                "price": o.price,
                "average_fill_price": o.average_fill_price,
                "order_status": o.order_status,
                "order_type": o.order_type,
                "segment": o.segment,
                "exchange": o.exchange,
                "product": o.product,
                "synced_at": o.synced_at.isoformat() if o.synced_at else None,
            }
            for o in orders
        ],
        "trades": [
            {
                "id": t.id,
                "trade_date": t.trade_date.isoformat(),
                "groww_trade_id": t.groww_trade_id,
                "groww_order_id": t.groww_order_id,
                "trading_symbol": t.trading_symbol,
                "transaction_type": t.transaction_type,
                "quantity": t.quantity,
                "price": t.price,
                "value": round(t.quantity * t.price, 2),
                "segment": t.segment,
                "exchange": t.exchange,
                "product": t.product,
                "synced_at": t.synced_at.isoformat() if t.synced_at else None,
            }
            for t in trades
        ],
    }


@router.post("/journal/upload")
async def mytrade_journal_upload(
    username: str = Query("leninstark"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload Excel/CSV trade history. Only rows after last saved fill datetime are inserted."""
    username = username.strip().lower()
    name = file.filename or "upload.csv"
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file")
    if len(data) > 40 * 1024 * 1024:
        raise HTTPException(400, "File too large (max 40MB)")
    try:
        result = ingest_upload(db, username=username, filename=name, data=data)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        logger.exception("Journal upload failed")
        raise HTTPException(400, f"Could not parse upload: {e}") from e
    return result


@router.get("/journal/fills")
def mytrade_journal_fills(
    username: str = Query("leninstark"),
    limit: int = Query(2000, ge=1, le=10000),
    db: Session = Depends(get_db),
):
    username = username.strip().lower()
    fills = list_journal_fills(db, username, limit=limit)
    return {"username": username, "fills": fills, "count": len(fills)}


@router.get("/journal/dna")
def mytrade_journal_dna_get(
    username: str = Query("leninstark"),
    db: Session = Depends(get_db),
):
    username = username.strip().lower()
    report = get_trader_dna(db, username)
    if not report:
        return {
            "ok": False,
            "error": "no_report",
            "message": "No Trader DNA report yet. Upload history and click Run Trader DNA.",
        }
    report["ok"] = True
    return report


@router.post("/journal/dna")
def mytrade_journal_dna_run(
    username: str = Query("leninstark"),
    force: bool = Query(False),
    db: Session = Depends(get_db),
):
    """Merge Groww fills, rebuild stats + narrative unless cache is current."""
    username = username.strip().lower()
    result = run_trader_dna(db, username=username, force=force)
    if not result.get("ok") and result.get("error") == "no_fills":
        raise HTTPException(400, result.get("message") or "No fills")
    if not result.get("ok"):
        raise HTTPException(500, result.get("message") or "DNA failed")
    return result
