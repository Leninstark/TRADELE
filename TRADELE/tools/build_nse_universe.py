"""Download NSE EQUITY_L.csv and rebuild data/universe/nse_equity_all.csv.

Usage:
    python -m TRADELE.tools.build_nse_universe
"""
from __future__ import annotations

import csv
import logging
import urllib.request
from pathlib import Path

from TRADELE.config import ROOT_DIR

logger = logging.getLogger(__name__)

UNIVERSE_DIR = ROOT_DIR / "data" / "universe"
NSE_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
INDEX_CSVS = ("nifty500.csv", "midcap150.csv", "smallcap250.csv")
OUTPUT = UNIVERSE_DIR / "nse_equity_all.csv"


def _load_index_industries() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for name in INDEX_CSVS:
        path = UNIVERSE_DIR / name
        if not path.exists():
            continue
        with path.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                sym = (row.get("Symbol") or row.get("symbol") or "").strip()
                ind = (row.get("Industry") or row.get("industry") or "").strip()
                if sym and ind:
                    mapping.setdefault(sym, ind)
    return mapping


def build_nse_equity_csv(*, download: bool = True) -> Path:
    """Fetch NSE master list and write nse_equity_all.csv."""
    UNIVERSE_DIR.mkdir(parents=True, exist_ok=True)
    industry = _load_index_industries()

    if download:
        req = urllib.request.Request(NSE_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=90) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    else:
        local = UNIVERSE_DIR / "EQUITY_L.csv"
        if not local.exists():
            raise FileNotFoundError(f"Missing {local}; run with download=True")
        raw = local.read_text(encoding="utf-8", errors="replace")

    rows_out: list[dict[str, str]] = []
    for row in csv.DictReader(raw.splitlines()):
        sym = (row.get("SYMBOL") or row.get("Symbol") or "").strip()
        company = (row.get("NAME OF COMPANY") or "").strip()
        series = (row.get(" SERIES") or row.get("SERIES") or "").strip()
        isin = (row.get(" ISIN NUMBER") or row.get("ISIN NUMBER") or "").strip()
        if not sym or series != "EQ":
            continue
        rows_out.append(
            {
                "Company Name": company,
                "Industry": industry.get(sym, ""),
                "Symbol": sym,
                "Series": series,
                "ISIN Code": isin,
                "Exchange": "NSE",
            }
        )

    fieldnames = ["Company Name", "Industry", "Symbol", "Series", "ISIN Code", "Exchange"]
    rows_out.sort(key=lambda r: r["Symbol"])
    with OUTPUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows_out)

    logger.info("Wrote %s NSE EQ symbols to %s", len(rows_out), OUTPUT)
    return OUTPUT


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    build_nse_equity_csv()
