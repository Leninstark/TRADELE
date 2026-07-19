"""NSE bhavcopy and quote helpers for delivery % and market cap."""
from __future__ import annotations

import csv
import io
import logging
from datetime import date, timedelta
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}


def _nse_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(_NSE_HEADERS)
    session.get("https://www.nseindia.com", timeout=15)
    return session


def fetch_delivery_map(max_days_back: int = 10) -> dict[str, float]:
    """Latest available bhavcopy: symbol -> delivery %."""
    session = _nse_session()
    today = date.today()
    for offset in range(1, max_days_back + 1):
        d = today - timedelta(days=offset)
        ddmmyyyy = d.strftime("%d%m%Y")
        url = (
            "https://nsearchives.nseindia.com/products/content/"
            f"sec_bhavdata_full_{ddmmyyyy}.csv"
        )
        try:
            resp = session.get(url, timeout=20)
            if resp.status_code != 200 or not resp.text.strip():
                continue
            out: dict[str, float] = {}
            reader = csv.DictReader(io.StringIO(resp.text))
            for row in reader:
                row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
                sym = row.get("SYMBOL", "")
                series = row.get("SERIES", "EQ")
                if not sym or series != "EQ":
                    continue
                raw = row.get("DELIV_PER", "")
                if not raw:
                    continue
                try:
                    out[sym] = float(raw)
                except ValueError:
                    continue
            if out:
                logger.info("Loaded delivery data for %d symbols from %s", len(out), ddmmyyyy)
                return out
        except Exception as e:
            logger.debug("Bhavcopy fetch failed for %s: %s", ddmmyyyy, e)
    return {}


def fetch_delivery_snapshots(max_days_back: int = 10) -> list[tuple[str, dict[str, dict[str, float]]]]:
    """
    Recent bhavcopy snapshots, newest first.
    Each snapshot: symbol -> {delivery_pct, volume}.
    """
    session = _nse_session()
    today = date.today()
    snapshots: list[tuple[str, dict[str, dict[str, float]]]] = []

    for offset in range(1, max_days_back + 1):
        d = today - timedelta(days=offset)
        ddmmyyyy = d.strftime("%d%m%Y")
        url = (
            "https://nsearchives.nseindia.com/products/content/"
            f"sec_bhavdata_full_{ddmmyyyy}.csv"
        )
        try:
            resp = session.get(url, timeout=20)
            if resp.status_code != 200 or not resp.text.strip():
                continue
            day_map: dict[str, dict[str, float]] = {}
            reader = csv.DictReader(io.StringIO(resp.text))
            for row in reader:
                row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
                sym = row.get("SYMBOL", "")
                series = row.get("SERIES", "EQ")
                if not sym or series != "EQ":
                    continue
                deliv_raw = row.get("DELIV_PER", "")
                vol_raw = row.get("TTL_TRD_QNTY", "") or row.get("TOTTRDQTY", "")
                if not deliv_raw:
                    continue
                try:
                    day_map[sym] = {
                        "delivery_pct": float(deliv_raw),
                        "volume": float(vol_raw) if vol_raw else 0.0,
                    }
                except ValueError:
                    continue
            if day_map:
                snapshots.append((ddmmyyyy, day_map))
        except Exception as e:
            logger.debug("Bhavcopy snapshot failed for %s: %s", ddmmyyyy, e)

    return snapshots


def fetch_market_cap_cr(symbol: str, session: Optional[requests.Session] = None) -> Optional[float]:
    """Market cap in ₹ Cr from NSE quote-equity, with yfinance fallback."""
    sess = session or _nse_session()
    try:
        resp = sess.get(
            "https://www.nseindia.com/api/quote-equity",
            params={"symbol": symbol},
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            price = float((data.get("priceInfo") or {}).get("lastPrice") or 0)
            issued = float((data.get("securityInfo") or {}).get("issuedSize") or 0)
            if price > 0 and issued > 0:
                return round((price * issued) / 1e7, 2)
    except Exception as e:
        logger.debug("NSE market cap failed for %s: %s", symbol, e)

    try:
        import yfinance as yf

        info = yf.Ticker(f"{symbol}.NS").info
        cap = info.get("marketCap")
        if cap:
            return round(float(cap) / 1e7, 2)
    except Exception as e:
        logger.debug("yfinance market cap failed for %s: %s", symbol, e)
    return None
