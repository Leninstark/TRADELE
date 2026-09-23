"""Fetch 1y daily OHLCV for NIFTY, BANK NIFTY, SENSEX via yfinance.

Usage:
    python -m TRADELE.tools.fetch_index_daily
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import yfinance as yf

from TRADELE.config import ROOT_DIR

logger = logging.getLogger(__name__)

OUT_DIR = ROOT_DIR / "data" / "indices"

TICKERS = {
    "NIFTY": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "SENSEX": "^BSESN",
}

_PROXY_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "SOCKS_PROXY",
    "SOCKS5_PROXY",
    "socks_proxy",
    "socks5_proxy",
)


def _prepare_yfinance() -> None:
    """Clear Cursor/sandbox proxies and keep yfinance cache inside the repo."""
    for key in _PROXY_KEYS:
        os.environ.pop(key, None)
    cache_dir = ROOT_DIR / "data" / ".yf_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    yf.set_tz_cache_location(str(cache_dir))


def fetch_and_save(*, period: str = "1y", out_dir: Path | None = None) -> dict[str, Path]:
    """Download daily history and write one CSV per index. Returns {name: path}."""
    _prepare_yfinance()
    dest = out_dir or OUT_DIR
    dest.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    for name, ticker in TICKERS.items():
        logger.info("Fetching %s (%s) period=%s …", name, ticker, period)
        hist = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=True)
        if hist is None or hist.empty:
            raise RuntimeError(f"No data returned for {name} ({ticker})")

        df = hist.reset_index()
        # Normalize column names
        df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
        if "date" in df.columns:
            df["date"] = df["date"].dt.tz_localize(None).dt.strftime("%Y-%m-%d")
        cols = [c for c in ("date", "open", "high", "low", "close", "volume") if c in df.columns]
        df = df[cols]

        path = dest / f"{name}_1y_daily.csv"
        df.to_csv(path, index=False)
        written[name] = path
        logger.info("Wrote %s (%d rows)", path, len(df))

    return written


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    paths = fetch_and_save()
    print("Saved:")
    for name, path in paths.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
