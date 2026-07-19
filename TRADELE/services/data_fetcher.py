"""EOD and pre-market data fetcher using Zerodha + cache."""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Optional

import pandas as pd
from sqlalchemy.orm import Session

from TRADELE.config import settings
from TRADELE.services.universe import get_tradeable_equity_symbols
from TRADELE.services.zerodha_client import ZerodhaClient

logger = logging.getLogger(__name__)

EXCHANGE = "NSE"
DAY_INTERVAL = "day"
INTRADAY_INTERVAL = "5minute"


def fetch_eod_batch(
    client: ZerodhaClient,
    db: Session,
    symbols: Optional[list[str]] = None,
    as_of: Optional[date] = None,
    lookback_days: int = 25,
    max_symbols: Optional[int] = None,
) -> dict[str, list[dict[str, Any]]]:
    """Fetch day candles for symbols; return {symbol: list of OHLCV}."""
    as_of = as_of or date.today()
    from_date = as_of - timedelta(days=lookback_days)
    symbols = symbols or get_tradeable_equity_symbols(client=client)
    if max_symbols and len(symbols) > max_symbols:
        symbols = symbols[:max_symbols]
    out: dict[str, list[dict[str, Any]]] = {}
    has_token = bool(client._token or settings.kite_access_token)
    for sym in symbols:
        try:
            if not has_token:
                candles = _load_from_cache_only(db, sym, EXCHANGE, DAY_INTERVAL, from_date, as_of)
            else:
                candles = client.get_historical(
                symbol=sym,
                exchange=EXCHANGE,
                interval=DAY_INTERVAL,
                from_date=from_date,
                to_date=as_of,
                db=db,
                use_cache=True,
            )
            if candles:
                out[sym] = candles
        except Exception as e:
            logger.debug("EOD fetch failed for %s: %s", sym, e)
    return out


def candles_to_dataframe(candles: list[dict]) -> pd.DataFrame:
    if not candles:
        return pd.DataFrame()
    df = pd.DataFrame(candles)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
    return df


def apply_liquidity_filters(
    symbol_data: dict[str, list[dict[str, Any]]],
    min_avg_volume: Optional[int] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
) -> dict[str, list[dict[str, Any]]]:
    """Drop symbols that don't meet min volume and price (using last close)."""
    min_avg_volume = min_avg_volume or settings.min_avg_volume
    min_price = min_price or settings.min_price
    max_price = max_price or settings.max_price
    filtered = {}
    for sym, candles in symbol_data.items():
        if len(candles) < 5:
            continue
        df = candles_to_dataframe(candles)
        last = df.iloc[-1]
        close = float(last.get("close", 0))
        if close < min_price or close > max_price:
            continue
        avg_vol = df["volume"].mean() if "volume" in df.columns else 0
        if avg_vol < min_avg_volume:
            continue
        filtered[sym] = candles
    return filtered
