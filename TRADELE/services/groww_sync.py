"""Sync Groww orders, trades, positions into date-wise MyTrade tables."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from TRADELE.db.models import GrowwOrder, GrowwSyncRun, GrowwTrade, GrowwTradingDay, GrowwToken
from TRADELE.services.groww_client import (
    get_holdings_list,
    get_order_trades,
    get_positions_list,
    list_all_orders,
)
from TRADELE.services.groww_token_store import check_token_status, get_active_access_token, try_refresh_token
from TRADELE.services.mytrade_analytics import dedupe_positions, sum_realised_pnl

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")
SEGMENTS = ("CASH", "FNO")
EXECUTED_STATUSES = {"COMPLETE", "COMPLETED", "EXECUTED", "TRADED", "PARTIALLY_EXECUTED"}


def _now_naive_ist() -> datetime:
    return datetime.now(IST).replace(tzinfo=None)


def today_ist() -> date:
    return datetime.now(IST).date()


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        if val is None:
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def _safe_int(val: Any, default: int = 0) -> int:
    try:
        if val is None:
            return default
        return int(val)
    except (TypeError, ValueError):
        return default


def get_last_stored_date(db: Session, username: str) -> Optional[date]:
    return (
        db.query(func.max(GrowwTradingDay.trade_date))
        .filter(GrowwTradingDay.username == username)
        .scalar()
    )


def get_dates_to_sync(db: Session, username: str) -> tuple[list[date], Optional[date], date]:
    """
    Return dates that should be synced. Groww only exposes today's orders via API,
    so only today is fetchable; gaps between last stored date and today cannot be backfilled.
    """
    today = today_ist()
    last = get_last_stored_date(db, username)
    if last is None:
        return [today], None, today
    if last >= today:
        return [today], last, today
    # Missing calendar days cannot be fetched from Groww — sync today and append.
    return [today], last, today


def _upsert_order(
    db: Session,
    username: str,
    trade_date: date,
    order: dict[str, Any],
    *,
    segment: str,
) -> tuple[GrowwOrder, bool]:
    groww_order_id = str(order.get("groww_order_id") or "")
    if not groww_order_id:
        raise ValueError("Order missing groww_order_id")

    filled_qty = _safe_int(order.get("filled_quantity") or order.get("quantity"))
    row = (
        db.query(GrowwOrder)
        .filter(GrowwOrder.username == username, GrowwOrder.groww_order_id == groww_order_id)
        .first()
    )
    created = row is None
    if row is None:
        row = GrowwOrder(username=username, trade_date=trade_date, groww_order_id=groww_order_id)
        db.add(row)

    row.trade_date = trade_date
    row.order_reference_id = order.get("order_reference_id")
    row.trading_symbol = str(order.get("trading_symbol") or "")
    row.quantity = _safe_int(order.get("quantity"))
    row.filled_quantity = filled_qty
    row.price = _safe_float(order.get("price"), default=0.0) or None
    row.average_fill_price = _safe_float(order.get("average_fill_price") or order.get("average_price"), default=0.0) or None
    row.order_status = str(order.get("order_status") or "")
    row.transaction_type = str(order.get("transaction_type") or "")
    row.order_type = order.get("order_type")
    row.segment = segment
    row.exchange = order.get("exchange")
    row.product = order.get("product")
    row.raw = order
    row.synced_at = _now_naive_ist()
    return row, created


def _upsert_trade(
    db: Session,
    username: str,
    trade_date: date,
    trade: dict[str, Any],
    *,
    order: GrowwOrder,
    segment: str,
) -> tuple[GrowwTrade, bool]:
    trade_id = str(trade.get("trade_id") or trade.get("groww_trade_id") or "")
    if not trade_id:
        trade_id = f"{order.groww_order_id}-{_safe_int(trade.get('quantity'))}-{_safe_float(trade.get('price'))}"

    row = (
        db.query(GrowwTrade)
        .filter(GrowwTrade.username == username, GrowwTrade.groww_trade_id == trade_id)
        .first()
    )
    created = row is None
    if row is None:
        row = GrowwTrade(username=username, trade_date=trade_date, groww_trade_id=trade_id)
        db.add(row)

    row.trade_date = trade_date
    row.groww_order_id = order.groww_order_id
    row.trading_symbol = order.trading_symbol
    row.transaction_type = order.transaction_type
    row.quantity = _safe_int(trade.get("quantity"))
    row.price = _safe_float(trade.get("price"))
    row.segment = segment
    row.exchange = order.exchange
    row.product = order.product
    row.raw = trade
    row.synced_at = _now_naive_ist()
    return row, created


def _compute_trade_values(trades: list[GrowwTrade]) -> tuple[float, float]:
    buy = sell = 0.0
    for t in trades:
        value = t.quantity * t.price
        if t.transaction_type.upper() == "BUY":
            buy += value
        else:
            sell += value
    return buy, sell


def sync_groww_for_user(db: Session, username: str) -> dict[str, Any]:
    username = (username or "default").strip().lower()
    status = check_token_status(db, username, live_check=False)
    if not status.get("connected"):
        try:
            token = try_refresh_token(db, username)
        except Exception:
            token = None
        if token:
            status = check_token_status(db, username, live_check=True)
    if not status.get("connected"):
        return {
            "ok": False,
            "error": status.get("message") or "Groww not connected. Connect via the header first.",
            "connected": False,
        }

    access_token = get_active_access_token(db, username)
    if not access_token:
        return {"ok": False, "error": "No active Groww token", "connected": False}

    dates_to_sync, last_stored, today = get_dates_to_sync(db, username)
    run = GrowwSyncRun(username=username, started_at=_now_naive_ist(), status="running")
    db.add(run)
    db.commit()
    db.refresh(run)

    orders_added = trades_added = 0
    synced_dates: list[str] = []
    note = (
        "Groww API only exposes today's orders. Refresh daily to build history; "
        "past dates cannot be backfilled."
    )

    try:
        for trade_date in dates_to_sync:
            if trade_date != today:
                continue

            all_orders: list[tuple[dict[str, Any], str]] = []
            for segment in SEGMENTS:
                try:
                    for order in list_all_orders(access_token, segment=segment):
                        all_orders.append((order, segment))
                except Exception as e:
                    logger.warning("Groww order list failed segment=%s: %s", segment, e)

            stored_orders: list[GrowwOrder] = []
            stored_trades: list[GrowwTrade] = []

            for order_data, segment in all_orders:
                order_row, order_created = _upsert_order(
                    db, username, trade_date, order_data, segment=segment
                )
                if order_created:
                    orders_added += 1
                stored_orders.append(order_row)

                status_upper = (order_row.order_status or "").upper()
                if status_upper in EXECUTED_STATUSES or order_row.filled_quantity > 0:
                    try:
                        fills = get_order_trades(access_token, order_row.groww_order_id, segment=segment)
                    except Exception as e:
                        logger.warning("Trades fetch failed order=%s: %s", order_row.groww_order_id, e)
                        fills = []
                    for fill in fills:
                        trade_row, trade_created = _upsert_trade(
                            db,
                            username,
                            trade_date,
                            fill,
                            order=order_row,
                            segment=segment,
                        )
                        if trade_created:
                            trades_added += 1
                        stored_trades.append(trade_row)

            try:
                positions = get_positions_list(access_token)
            except Exception as e:
                logger.warning("Positions fetch failed: %s", e)
                positions = []

            try:
                holdings = get_holdings_list(access_token)
            except Exception as e:
                logger.warning("Holdings fetch failed: %s", e)
                holdings = []

            realised_pnl = sum_realised_pnl(positions)
            buy_value, sell_value = _compute_trade_values(stored_trades)
            unique_positions = dedupe_positions(positions)

            day_row = (
                db.query(GrowwTradingDay)
                .filter(GrowwTradingDay.username == username, GrowwTradingDay.trade_date == trade_date)
                .first()
            )
            if day_row is None:
                day_row = GrowwTradingDay(username=username, trade_date=trade_date)
                db.add(day_row)

            day_row.realised_pnl = realised_pnl
            day_row.order_count = len(stored_orders)
            day_row.trade_count = len(stored_trades)
            day_row.buy_value = buy_value
            day_row.sell_value = sell_value
            day_row.holdings_count = len(holdings)
            day_row.positions_count = len(unique_positions)
            day_row.summary = {
                "positions": unique_positions,
                "positions_raw_count": len(positions),
                "holdings_count": len(holdings),
                "note": note,
            }
            day_row.synced_at = _now_naive_ist()
            synced_dates.append(trade_date.isoformat())

        db.commit()
        run.status = "success"
        run.finished_at = _now_naive_ist()
        run.dates_synced = synced_dates
        run.orders_added = orders_added
        run.trades_added = trades_added
        db.commit()

        gap_days = 0
        if last_stored and last_stored < today - timedelta(days=1):
            gap_days = (today - last_stored).days - 1

        return {
            "ok": True,
            "connected": True,
            "username": username,
            "dates_synced": synced_dates,
            "orders_added": orders_added,
            "trades_added": trades_added,
            "last_stored_before": last_stored.isoformat() if last_stored else None,
            "today": today.isoformat(),
            "gap_days_not_backfilled": gap_days,
            "note": note if gap_days else None,
            "sync_run_id": run.id,
        }
    except Exception as e:
        logger.exception("Groww sync failed for %s", username)
        db.rollback()
        run.status = "failed"
        run.finished_at = _now_naive_ist()
        run.error_message = str(e)
        db.commit()
        return {"ok": False, "error": str(e), "connected": True, "sync_run_id": run.id}


def list_groww_usernames(db: Session) -> list[str]:
    """Usernames with a stored Groww access token."""
    rows = (
        db.query(GrowwToken.username)
        .filter(GrowwToken.access_token.isnot(None), GrowwToken.access_token != "")
        .distinct()
        .all()
    )
    return sorted({r[0].strip().lower() for r in rows if r[0]})


def sync_all_groww_users(db: Session) -> dict[str, Any]:
    """Run Groww sync for every user with a token (used by EOD scheduler)."""
    usernames = list_groww_usernames(db)
    if not usernames:
        logger.info("Groww EOD sync: no users with tokens")
        return {"ok": True, "users": 0, "synced": 0, "skipped": 0, "results": []}

    results: list[dict[str, Any]] = []
    synced = skipped = 0
    for username in usernames:
        try:
            result = sync_groww_for_user(db, username)
            results.append(result)
            if result.get("ok"):
                synced += 1
            else:
                skipped += 1
                logger.warning("Groww EOD sync skipped %s: %s", username, result.get("error"))
        except Exception as e:
            logger.exception("Groww EOD sync failed for %s", username)
            results.append({"ok": False, "username": username, "error": str(e)})
            skipped += 1

    return {
        "ok": synced > 0 or skipped == 0,
        "users": len(usernames),
        "synced": synced,
        "skipped": skipped,
        "trade_date": today_ist().isoformat(),
        "results": results,
    }
