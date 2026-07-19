"""Zerodha Kite API client with historical data and caching."""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Optional

from kiteconnect import KiteConnect
from sqlalchemy.orm import Session

from TRADELE.config import settings
from TRADELE.db.models import CandleCache

logger = logging.getLogger(__name__)


class ZerodhaClient:
    """Kite client wrapper with token refresh and candle caching."""

    def __init__(self, access_token: Optional[str] = None):
        self._token = access_token or settings.kite_access_token
        self._kite: Optional[KiteConnect] = None

    @property
    def kite(self) -> KiteConnect:
        if self._kite is None:
            self._kite = KiteConnect(api_key=settings.kite_api_key)
            if self._token:
                self._kite.set_access_token(self._token)
        return self._kite

    def set_access_token(self, token: str) -> None:
        self._token = token
        if self._kite:
            self._kite.set_access_token(token)

    def get_historical(
        self,
        symbol: str,
        exchange: str,
        interval: str,
        from_date: date,
        to_date: date,
        db: Optional[Session] = None,
        use_cache: bool = True,
    ) -> list[dict[str, Any]]:
        """Fetch OHLCV; use cache if available and fresh (same day)."""
        from_str = from_date.isoformat()
        to_str = to_date.isoformat()
        instrument = f"{exchange}:{symbol}"

        if use_cache and db:
            row = (
                db.query(CandleCache)
                .filter(
                    CandleCache.symbol == symbol,
                    CandleCache.exchange == exchange,
                    CandleCache.interval == interval,
                    CandleCache.from_date == from_str,
                    CandleCache.to_date == to_str,
                )
                .first()
            )
            if row and row.data:
                return row.data

        try:
            data = self.kite.historical_data(
                self._get_instrument_token(instrument),
                from_date,
                to_date,
                interval,
            )
        except Exception as e:
            logger.exception("Kite historical_data failed for %s: %s", instrument, e)
            raise

        result = [
            {
                "date": d["date"].isoformat() if hasattr(d["date"], "isoformat") else str(d["date"]),
                "open": d["open"],
                "high": d["high"],
                "low": d["low"],
                "close": d["close"],
                "volume": d.get("volume", 0),
            }
            for d in data
        ]

        if use_cache and db and result:
            try:
                db.add(
                    CandleCache(
                        symbol=symbol,
                        exchange=exchange,
                        interval=interval,
                        from_date=from_str,
                        to_date=to_str,
                        data=result,
                    )
                )
                db.commit()
            except Exception as e:
                logger.warning("Cache write failed: %s", e)
                db.rollback()

        return result

    def _get_instrument_token(self, instrument: str) -> int:
        """Resolve NSE:RELIANCE -> instrument_token. Uses instruments dump or live API."""
        # KiteConnect has get_instruments(); we cache in memory for session
        if not hasattr(self, "_instruments_map"):
            self._instruments_map = {}
            try:
                instruments = self.kite.instruments()
                for i in instruments:
                    key = f"{i['exchange']}:{i['tradingsymbol']}"
                    self._instruments_map[key] = i["instrument_token"]
            except Exception as e:
                logger.exception("Failed to load instruments: %s", e)
        token = self._instruments_map.get(instrument)
        if token is None:
            raise ValueError(f"Instrument not found: {instrument}")
        return token

    def get_quote(self, instruments: list[str]) -> dict:
        """Live quote for given instruments (e.g. ['NSE:RELIANCE'])."""
        return self.kite.quote(instruments)

    def get_ltp(self, exchange: str, symbol: str) -> Optional[float]:
        """Last traded price for one symbol."""
        key = f"{exchange}:{symbol}"
        try:
            q = self.kite.quote([key])
            return float(q[key]["last_price"])
        except Exception as e:
            logger.warning("LTP failed for %s: %s", key, e)
            return None


def get_client(access_token: Optional[str] = None) -> ZerodhaClient:
    """Return Kite client using explicit token, else active token from DB, else .env."""
    token = access_token
    if not token:
        try:
            from TRADELE.db.session import SessionLocal
            from TRADELE.services.zerodha_token_store import get_active_access_token

            db = SessionLocal()
            try:
                token = get_active_access_token(db)
            finally:
                db.close()
        except Exception as e:
            logger.debug("DB token lookup failed: %s", e)
    if not token:
        token = settings.kite_access_token or None
    return ZerodhaClient(access_token=token)
