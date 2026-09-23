"""Ingest Groww trades + Excel/CSV uploads into journal_fills (dedupe + incremental)."""
from __future__ import annotations

import hashlib
import io
import logging
import re
from datetime import date, datetime, time
from typing import Any, BinaryIO, Optional

import pandas as pd
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from TRADELE.db.models import GrowwOrder, GrowwTrade, JournalFill

logger = logging.getLogger(__name__)

COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "symbol": ("symbol", "trading_symbol", "tradingsymbol", "stock", "scrip", "name", "instrument"),
    "side": ("side", "transaction_type", "transaction", "buy/sell", "buy_sell", "type", "order_side"),
    "quantity": ("quantity", "qty", "traded_qty", "filled_quantity", "fill_qty", "traded quantity"),
    "price": ("price", "trade_price", "avg_price", "average_price", "average_fill_price", "ltp", "rate"),
    "date": ("date", "trade_date", "order_date", "activity_date", "exchange_date"),
    "time": ("time", "trade_time", "order_time", "exchange_time", "created_at"),
    "datetime": ("datetime", "trade_datetime", "timestamp", "exchange_timestamp"),
    "product": ("product", "product_type", "order_product", "product type"),
    "segment": ("segment", "segment_name", "market_segment"),
    "exchange": ("exchange", "exch"),
    "order_id": ("order_id", "groww_order_id", "orderid", "order id", "order_reference_id"),
    "trade_id": ("trade_id", "groww_trade_id", "tradeid", "trade id", "fill_id"),
}


def make_dedupe_key(
    username: str,
    *,
    symbol: str,
    side: str,
    quantity: float,
    price: float,
    trade_datetime: datetime,
    product: str,
    segment: str,
) -> str:
    raw = "|".join(
        [
            username.strip().lower(),
            symbol.strip().upper(),
            side.strip().upper(),
            f"{float(quantity):.6f}",
            f"{float(price):.6f}",
            trade_datetime.strftime("%Y-%m-%d %H:%M:%S"),
            (product or "").strip().upper(),
            (segment or "CASH").strip().upper(),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def _norm_col(name: Any) -> str:
    s = str(name or "").strip().lower()
    s = re.sub(r"[\s\-/]+", "_", s)
    return s


def _map_columns(df: pd.DataFrame) -> dict[str, str]:
    cols = {_norm_col(c): c for c in df.columns}
    mapping: dict[str, str] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for a in aliases:
            key = _norm_col(a)
            if key in cols:
                mapping[canonical] = cols[key]
                break
    return mapping


def _parse_side(val: Any) -> Optional[str]:
    s = str(val or "").strip().upper()
    if s in ("B", "BUY", "BOUGHT", "LONG"):
        return "BUY"
    if s in ("S", "SELL", "SOLD", "SHORT"):
        return "SELL"
    if "BUY" in s:
        return "BUY"
    if "SELL" in s:
        return "SELL"
    return None


def _parse_dt(date_val: Any, time_val: Any = None) -> Optional[datetime]:
    if date_val is None or (isinstance(date_val, float) and pd.isna(date_val)):
        return None
    # Combined datetime column
    if time_val is None:
        ts = pd.to_datetime(date_val, errors="coerce", dayfirst=True)
        if pd.isna(ts):
            return None
        return ts.to_pydatetime().replace(tzinfo=None)

    d = pd.to_datetime(date_val, errors="coerce", dayfirst=True)
    if pd.isna(d):
        return None
    base = d.to_pydatetime().replace(tzinfo=None)
    if time_val is None or (isinstance(time_val, float) and pd.isna(time_val)):
        return datetime.combine(base.date(), time(15, 30))
    t = pd.to_datetime(time_val, errors="coerce")
    if pd.isna(t):
        # try HH:MM:SS string
        try:
            parts = str(time_val).strip().split(":")
            hh, mm = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
            ss = int(float(parts[2])) if len(parts) > 2 else 0
            return datetime.combine(base.date(), time(hh, mm, ss))
        except Exception:
            return datetime.combine(base.date(), time(15, 30))
    tt = t.to_pydatetime()
    return datetime.combine(base.date(), tt.time())


def _infer_instrument(symbol: str, segment: str, product: str) -> str:
    seg = (segment or "").upper()
    if seg in ("FNO", "F&O", "FO", "DERIVATIVE", "DERIVATIVES"):
        return "fno"
    sym = symbol.upper()
    if re.search(r"\d{2}(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)", sym):
        return "fno"
    if product.upper() == "NRML" and ("CE" in sym or "PE" in sym or "FUT" in sym):
        return "fno"
    return "equity"


def _row_to_fill(username: str, source: str, row: dict[str, Any]) -> Optional[dict[str, Any]]:
    symbol = str(row.get("symbol") or "").strip().upper()
    side = _parse_side(row.get("side"))
    try:
        qty = float(row.get("quantity") or 0)
        price = float(row.get("price") or 0)
    except (TypeError, ValueError):
        return None
    if not symbol or not side or qty <= 0 or price < 0:
        return None

    if row.get("datetime") is not None:
        dt = _parse_dt(row.get("datetime"))
    else:
        dt = _parse_dt(row.get("date"), row.get("time"))
    if not dt:
        return None

    product = str(row.get("product") or "").strip().upper() or None
    segment = str(row.get("segment") or "CASH").strip().upper() or "CASH"
    if segment in ("F&O", "FO", "DERIVATIVE", "DERIVATIVES"):
        segment = "FNO"
    exchange = str(row.get("exchange") or "").strip().upper() or None
    instrument = _infer_instrument(symbol, segment, product or "")
    order_id = str(row.get("order_id") or "").strip() or None
    trade_id = str(row.get("trade_id") or "").strip() or None
    dedupe = make_dedupe_key(
        username,
        symbol=symbol,
        side=side,
        quantity=qty,
        price=price,
        trade_datetime=dt,
        product=product or "",
        segment=segment,
    )
    return {
        "username": username.strip().lower(),
        "source": source,
        "trade_datetime": dt,
        "trade_date": dt.date(),
        "symbol": symbol,
        "side": side,
        "quantity": qty,
        "price": price,
        "product": product,
        "segment": segment,
        "exchange": exchange,
        "instrument": instrument,
        "order_id": order_id,
        "trade_id": trade_id,
        "dedupe_key": dedupe,
        "raw": row.get("raw") if isinstance(row.get("raw"), dict) else {"source_row": True},
    }


def get_fills_cutoff(db: Session, username: str) -> Optional[datetime]:
    row = (
        db.query(JournalFill.trade_datetime)
        .filter(JournalFill.username == username.strip().lower())
        .order_by(JournalFill.trade_datetime.desc())
        .first()
    )
    return row[0] if row else None


def _upsert_fills(db: Session, fills: list[dict[str, Any]]) -> tuple[int, int]:
    """Insert fills ignoring duplicates. Returns (added, duplicates)."""
    if not fills:
        return 0, 0
    added = 0
    duplicates = 0
    # Chunk inserts for large uploads
    chunk = 200
    for i in range(0, len(fills), chunk):
        batch = fills[i : i + chunk]
        stmt = pg_insert(JournalFill).values(batch)
        stmt = stmt.on_conflict_do_nothing(constraint="uq_journal_fill_dedupe")
        result = db.execute(stmt)
        # rowcount is inserted rows on PG
        n = result.rowcount if result.rowcount is not None else 0
        if n < 0:
            n = 0
        added += n
        duplicates += len(batch) - n
    db.commit()
    return added, duplicates


def parse_upload_bytes(filename: str, data: bytes) -> pd.DataFrame:
    name = (filename or "").lower()
    bio = io.BytesIO(data)
    if name.endswith(".csv"):
        df = pd.read_csv(bio)
    elif name.endswith(".xlsx") or name.endswith(".xls"):
        df = pd.read_excel(bio, engine="openpyxl" if name.endswith(".xlsx") else None)
    else:
        # try excel then csv
        try:
            bio.seek(0)
            df = pd.read_excel(bio, engine="openpyxl")
        except Exception:
            bio.seek(0)
            df = pd.read_csv(bio)
    if df is None or df.empty:
        raise ValueError("Upload file has no rows")
    return df


def _json_safe(v: Any) -> Any:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, (str, int, float, bool)):
        return v
    if hasattr(v, "isoformat"):
        try:
            return v.isoformat()
        except Exception:
            return str(v)
    if hasattr(v, "item"):
        try:
            return v.item()
        except Exception:
            return str(v)
    return str(v)


def dataframe_to_fills(username: str, df: pd.DataFrame, source: str = "upload") -> list[dict[str, Any]]:
    mapping = _map_columns(df)
    if "symbol" not in mapping or "side" not in mapping or "quantity" not in mapping or "price" not in mapping:
        raise ValueError(
            "Could not map required columns (need Symbol, Buy/Sell, Qty, Price). "
            f"Found: {list(df.columns)}"
        )
    if "datetime" not in mapping and "date" not in mapping:
        raise ValueError("Could not find a Date or Datetime column in the upload")

    out: list[dict[str, Any]] = []
    for _, series in df.iterrows():
        row: dict[str, Any] = {}
        for canon, col in mapping.items():
            row[canon] = series.get(col)
        row["raw"] = {str(k): _json_safe(v) for k, v in series.to_dict().items()}
        fill = _row_to_fill(username, source, row)
        if fill:
            out.append(fill)
    return out


def ingest_upload(
    db: Session,
    *,
    username: str,
    filename: str,
    data: bytes,
) -> dict[str, Any]:
    """Parse upload and insert only rows after existing cutoff (incremental) + dedupe."""
    username = username.strip().lower()
    df = parse_upload_bytes(filename, data)
    fills = dataframe_to_fills(username, df, source="upload")
    cutoff = get_fills_cutoff(db, username)

    skipped_before = 0
    to_insert = fills
    if cutoff is not None:
        to_insert = []
        for f in fills:
            if f["trade_datetime"] > cutoff:
                to_insert.append(f)
            else:
                skipped_before += 1

    added, duplicates = _upsert_fills(db, to_insert)
    total = db.query(JournalFill).filter(JournalFill.username == username).count()
    return {
        "ok": True,
        "filename": filename,
        "parsed_rows": len(fills),
        "added": added,
        "skipped_before_cutoff": skipped_before,
        "duplicates": duplicates,
        "cutoff": cutoff.isoformat() if cutoff else None,
        "fills_total": total,
    }


def _groww_trade_datetime(trade: GrowwTrade, order: Optional[GrowwOrder]) -> datetime:
    raw = trade.raw if isinstance(trade.raw, dict) else {}
    order_raw = order.raw if order and isinstance(order.raw, dict) else {}
    for key in ("exchange_time", "trade_time", "created_at", "timestamp", "order_timestamp"):
        for blob in (raw, order_raw):
            if key in blob and blob[key]:
                dt = _parse_dt(blob[key])
                if dt:
                    return dt
    # Default: trade_date at 15:30 IST-naive (session end placeholder)
    return datetime.combine(trade.trade_date, time(15, 30))


def sync_groww_into_fills(db: Session, username: str) -> dict[str, Any]:
    """Copy GrowwTrade rows into journal_fills (dedupe; no cutoff skip — IDs may be new)."""
    username = username.strip().lower()
    trades = db.query(GrowwTrade).filter(GrowwTrade.username == username).all()
    if not trades:
        return {"ok": True, "added": 0, "duplicates": 0, "groww_trades": 0}

    order_ids = {t.groww_order_id for t in trades if t.groww_order_id}
    orders = (
        db.query(GrowwOrder)
        .filter(GrowwOrder.username == username, GrowwOrder.groww_order_id.in_(list(order_ids)))
        .all()
        if order_ids
        else []
    )
    by_oid = {o.groww_order_id: o for o in orders}

    fills: list[dict[str, Any]] = []
    for t in trades:
        order = by_oid.get(t.groww_order_id)
        dt = _groww_trade_datetime(t, order)
        product = (t.product or (order.product if order else None) or "").strip().upper() or None
        segment = (t.segment or "CASH").strip().upper() or "CASH"
        fill = _row_to_fill(
            username,
            "groww",
            {
                "symbol": t.trading_symbol,
                "side": t.transaction_type,
                "quantity": t.quantity,
                "price": t.price,
                "datetime": dt,
                "product": product,
                "segment": segment,
                "exchange": t.exchange,
                "order_id": t.groww_order_id,
                "trade_id": t.groww_trade_id,
                "raw": {"groww_trade_id": t.groww_trade_id, "groww_order_id": t.groww_order_id},
            },
        )
        if fill:
            fills.append(fill)

    added, duplicates = _upsert_fills(db, fills)
    return {
        "ok": True,
        "added": added,
        "duplicates": duplicates,
        "groww_trades": len(trades),
    }


def list_journal_fills(db: Session, username: str, limit: int = 2000) -> list[dict[str, Any]]:
    username = username.strip().lower()
    rows = (
        db.query(JournalFill)
        .filter(JournalFill.username == username)
        .order_by(JournalFill.trade_datetime.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "source": r.source,
            "trade_datetime": r.trade_datetime.isoformat(),
            "trade_date": r.trade_date.isoformat(),
            "symbol": r.symbol,
            "side": r.side,
            "quantity": r.quantity,
            "price": r.price,
            "value": round(float(r.quantity) * float(r.price), 2),
            "product": r.product,
            "segment": r.segment,
            "exchange": r.exchange,
            "instrument": r.instrument,
        }
        for r in rows
    ]
