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

EXCHANGE_NSE = "NSE"
# Non-EQ series trade under a suffixed tradingsymbol (BE = trade-for-trade,
# SM/ST = SME platform, BZ = surveillance).
SERIES_SUFFIXES = ("-BE", "-BZ", "-BL", "-SM", "-ST", "-IL", "-EQ")


class KiteRateLimitError(RuntimeError):
    """Zerodha/Kite returned Too many requests — stop further historical calls."""

    def __init__(self, message: str = "Too many requests"):
        super().__init__(message)


def _is_rate_limit(exc: BaseException) -> bool:
    parts = [
        str(exc),
        str(getattr(exc, "message", "") or ""),
        type(exc).__name__,
    ]
    blob = " ".join(parts).lower()
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if code in (429, "429"):
        return True
    return "too many requests" in blob or "rate limit" in blob or "ratelimit" in blob


def make_kite(api_key: Optional[str] = None, access_token: Optional[str] = None) -> KiteConnect:
    """Build a KiteConnect client that ignores HTTP(S)_PROXY env vars.

    Cursor/sandbox shells inject a local proxy that 403s tunnels to api.kite.trade,
    which breaks OAuth token exchange and live API calls.
    """
    kite = KiteConnect(api_key=api_key or settings.kite_api_key)
    # requests Session: do not pick up HTTP_PROXY / HTTPS_PROXY / ALL_PROXY
    kite.reqsession.trust_env = False
    if access_token:
        kite.set_access_token(access_token)
    return kite


class ZerodhaClient:
    """Kite client wrapper with token refresh and candle caching."""

    def __init__(self, access_token: Optional[str] = None):
        self._token = access_token or settings.kite_access_token
        self._kite: Optional[KiteConnect] = None

    @property
    def kite(self) -> KiteConnect:
        if self._kite is None:
            self._kite = make_kite(access_token=self._token)
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
            if _is_rate_limit(e):
                logger.warning("Kite rate limit on %s — stopping historical fetches", instrument)
                raise KiteRateLimitError("Too many requests") from e
            logger.warning("Kite historical_data failed for %s: %s", instrument, e)
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

    def get_historical_minute(
        self,
        symbol: str,
        exchange: str,
        trade_date: date,
        db: Optional[Session] = None,
        use_cache: bool = True,
    ) -> list[dict[str, Any]]:
        """Fetch 1-minute OHLCV for a single NSE session day and cache it."""
        from datetime import datetime as dt

        from_str = trade_date.isoformat()
        to_str = trade_date.isoformat()
        interval = "minute"
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
            if row and row.data and len(row.data) > 10:
                return row.data

        start = dt(trade_date.year, trade_date.month, trade_date.day, 9, 15)
        end = dt(trade_date.year, trade_date.month, trade_date.day, 15, 30)
        try:
            data = self.kite.historical_data(
                self._get_instrument_token(instrument),
                start,
                end,
                interval,
            )
        except Exception as e:
            if _is_rate_limit(e):
                logger.warning("Kite rate limit on %s 1-min — stopping", instrument)
                raise KiteRateLimitError("Too many requests") from e
            logger.warning("Kite 1-min historical failed for %s: %s", instrument, e)
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
                existing = (
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
                if existing:
                    existing.data = result
                else:
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
                logger.warning("1-min cache write failed: %s", e)
                db.rollback()

        return result

    def _load_instruments_map(self) -> dict[str, int]:
        # KiteConnect has get_instruments(); we cache in memory for session
        if not hasattr(self, "_instruments_map"):
            self._instruments_map = {}
            self._instrument_names = {}
            try:
                instruments = self.kite.instruments()
                for i in instruments:
                    key = f"{i['exchange']}:{i['tradingsymbol']}"
                    self._instruments_map[key] = i["instrument_token"]
                    if i.get("name"):
                        self._instrument_names[key] = i["name"]
            except Exception as e:
                logger.exception("Failed to load instruments: %s", e)
        return self._instruments_map

    def get_instrument_name(self, instrument: str) -> Optional[str]:
        """Company name for an instrument (e.g. NSE:STLTECH -> STERLITE TECHNOLOGIES)."""
        try:
            key, _ = self.resolve_instrument(instrument)
        except ValueError:
            return None
        return getattr(self, "_instrument_names", {}).get(key)

    def search_equity(self, query: str, exchange: str = EXCHANGE_NSE) -> Optional[tuple[str, str]]:
        """
        Find an equity by company name. Returns (tradingsymbol, name).

        The tradingsymbol keeps any series suffix stripped so callers get the
        plain ticker (STLTECH rather than STLTECH-BE).
        """
        q = (query or "").strip().upper()
        if not q:
            return None
        self._load_instruments_map()
        names = getattr(self, "_instrument_names", {})
        prefix = f"{exchange}:"
        best: Optional[tuple[str, str]] = None
        for key, name in names.items():
            if not key.startswith(prefix):
                continue
            upper = name.upper()
            symbol = key.split(":", 1)[1]
            for suffix in SERIES_SUFFIXES:
                if symbol.endswith(suffix):
                    symbol = symbol[: -len(suffix)]
                    break
            if upper == q:
                return symbol, name
            if q in upper and (best is None or len(name) < len(best[1])):
                best = (symbol, name)
        return best

    def resolve_instrument(self, instrument: str) -> tuple[str, int]:
        """
        Resolve 'NSE:RELIANCE' -> ('NSE:RELIANCE', token).

        Stocks outside the regular EQ series trade under a suffixed symbol
        (e.g. STLTECH is listed as STLTECH-BE), so fall back to those series
        variants and finally to BSE before giving up.
        """
        mapping = self._load_instruments_map()
        token = mapping.get(instrument)
        if token is not None:
            return instrument, token

        exchange, _, symbol = instrument.partition(":")
        if not symbol:
            exchange, symbol = EXCHANGE_NSE, exchange

        candidates = [f"{exchange}:{symbol}{s}" for s in SERIES_SUFFIXES]
        if exchange == EXCHANGE_NSE:
            candidates.append(f"BSE:{symbol}")
            candidates.extend(f"BSE:{symbol}{s}" for s in SERIES_SUFFIXES)

        for key in candidates:
            token = mapping.get(key)
            if token is not None:
                logger.info("Resolved %s via %s", instrument, key)
                return key, token

        raise ValueError(f"Instrument not found: {instrument}")

    def _get_instrument_token(self, instrument: str) -> int:
        """Resolve NSE:RELIANCE -> instrument_token. Uses instruments dump or live API."""
        return self.resolve_instrument(instrument)[1]

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
