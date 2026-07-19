"""APIs for Kite/NSE historical and live market data."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from TRADELE.db.session import get_db
from TRADELE.services.zerodha_client import get_client

router = APIRouter()


def _json_safe(obj: Any) -> Any:
    """Convert Decimal and other non-JSON types for quote response."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(x) for x in obj]
    return obj

# Kite interval values
INTERVALS = ["minute", "3minute", "5minute", "10minute", "15minute", "30minute", "60minute", "day"]
DEFAULT_EXCHANGE = "NSE"


@router.get("/historical")
def get_historical(
    symbol: str = Query(..., description="Trading symbol, e.g. RELIANCE, INFY"),
    exchange: str = Query(DEFAULT_EXCHANGE, description="Exchange code (NSE, BSE)"),
    interval: str = Query("day", description="Candle interval: minute, 5minute, 15minute, day, etc."),
    from_date: Optional[date] = Query(None, description="Start date (YYYY-MM-DD)"),
    to_date: Optional[date] = Query(None, description="End date (YYYY-MM-DD)"),
    use_cache: bool = Query(True, description="Use DB cache when available"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Get historical OHLCV data from Kite for a symbol.
    Requires valid KITE_ACCESS_TOKEN. Candle keys: date, open, high, low, close, volume.
    """
    if interval not in INTERVALS:
        raise HTTPException(400, f"interval must be one of: {INTERVALS}")
    to_date = to_date or date.today()
    from_date = from_date or (to_date - timedelta(days=60))
    if from_date > to_date:
        raise HTTPException(400, "from_date must be <= to_date")
    try:
        client = get_client()
        candles = client.get_historical(
            symbol=symbol.strip().upper(),
            exchange=exchange.strip().upper(),
            interval=interval,
            from_date=from_date,
            to_date=to_date,
            db=db if use_cache else None,
            use_cache=use_cache,
        )
        return {
            "symbol": symbol.upper(),
            "exchange": exchange.upper(),
            "interval": interval,
            "from_date": from_date.isoformat(),
            "to_date": to_date.isoformat(),
            "count": len(candles),
            "candles": candles,
        }
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(502, f"Kite error: {e!s}")


@router.get("/quote")
def get_quote(
    instruments: str = Query(
        ...,
        description="Comma-separated instruments, e.g. NSE:RELIANCE,NSE:INFY",
    ),
) -> dict[str, Any]:
    """
    Get live quote from Kite for one or more instruments.
    Format: EXCHANGE:SYMBOL (e.g. NSE:RELIANCE).
    """
    try:
        client = get_client()
        keys = [s.strip() for s in instruments.split(",") if s.strip()]
        if not keys:
            raise HTTPException(400, "At least one instrument required")
        data = client.get_quote(keys)
        return {"instruments": keys, "quote": _json_safe(data)}
    except Exception as e:
        raise HTTPException(502, f"Kite error: {e!s}")


@router.get("/ltp/{exchange}/{symbol}")
def get_ltp(
    exchange: str,
    symbol: str,
) -> dict[str, Any]:
    """Get last traded price for a single symbol (e.g. exchange=NSE, symbol=RELIANCE)."""
    try:
        client = get_client()
        ltp = client.get_ltp(exchange.strip().upper(), symbol.strip().upper())
        if ltp is None:
            raise HTTPException(404, f"Instrument not found or no data: {exchange}:{symbol}")
        return {
            "instrument": f"{exchange.upper()}:{symbol.upper()}",
            "ltp": ltp,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Kite error: {e!s}")


@router.get("/instruments")
def list_instruments(
    exchange: str = Query(DEFAULT_EXCHANGE, description="Filter by exchange (NSE, BSE)"),
    segment: Optional[str] = Query(None, description="Filter by segment if supported"),
) -> dict[str, Any]:
    """
    List instruments from Kite (NSE/BSE equity, etc.).
    Optional segment filter; large response for full list.
    """
    try:
        client = get_client()
        raw = client.kite.instruments()
        out = []
        for i in raw:
            if exchange and (i.get("exchange") or "").upper() != exchange.upper():
                continue
            if segment and (i.get("segment") or "").upper() != segment.upper():
                continue
            out.append({
                "instrument_token": i.get("instrument_token"),
                "exchange": i.get("exchange"),
                "tradingsymbol": i.get("tradingsymbol"),
                "name": i.get("name"),
                "segment": i.get("segment"),
            })
        return {"exchange": exchange, "count": len(out), "instruments": out[:500]}
    except Exception as e:
        raise HTTPException(502, f"Kite error: {e!s}")
