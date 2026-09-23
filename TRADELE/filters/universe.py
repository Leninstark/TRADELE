"""Load NSE equity symbol lists for scanning and search."""
from __future__ import annotations

import csv
import logging
from pathlib import Path

from TRADELE.config import ROOT_DIR

logger = logging.getLogger(__name__)

UNIVERSE_DIR = ROOT_DIR / "data" / "universe"

INDEX_FILES = {
    "nifty500": UNIVERSE_DIR / "nifty500.csv",
    "midcap150": UNIVERSE_DIR / "midcap150.csv",
    "smallcap250": UNIVERSE_DIR / "smallcap250.csv",
}

# Full NSE EQ list (~2100+ symbols) — built from NSE EQUITY_L.csv
NSE_EQUITY_ALL = UNIVERSE_DIR / "nse_equity_all.csv"

MID_SMALL_INDEX_FILES = ("midcap150", "smallcap250")


def _read_universe_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    rows: list[dict[str, str]] = []
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sym = (row.get("Symbol") or row.get("symbol") or "").strip()
            if not sym:
                continue
            series = (row.get("Series") or row.get("series") or "EQ").strip()
            if series and series != "EQ":
                continue
            company = (
                row.get("Company Name")
                or row.get("company_name")
                or row.get("Company")
                or sym
            ).strip()
            industry = (row.get("Industry") or row.get("industry") or "").strip()
            rows.append({"symbol": sym, "company": company, "industry": industry})
    return rows


def _symbols_from_csv(path: Path) -> list[str]:
    return [r["symbol"] for r in _read_universe_csv(path)]


def load_symbol_company_map() -> dict[str, str]:
    """Symbol -> Company Name from mid/small cap index CSVs."""
    mapping: dict[str, str] = {}
    for key in MID_SMALL_INDEX_FILES:
        for row in _read_universe_csv(INDEX_FILES[key]):
            mapping[row["symbol"]] = row["company"]
    return mapping


def load_full_symbol_company_map() -> dict[str, str]:
    """Symbol -> Company Name — full NSE EQ universe when available."""
    mapping: dict[str, str] = {}

    if NSE_EQUITY_ALL.exists():
        for row in _read_universe_csv(NSE_EQUITY_ALL):
            mapping[row["symbol"]] = row["company"]
    else:
        logger.warning("Full NSE universe missing at %s — using index CSVs only", NSE_EQUITY_ALL)

    # Index CSVs overlay (may have cleaner names) and backfill if master missing
    for path in INDEX_FILES.values():
        for row in _read_universe_csv(path):
            mapping.setdefault(row["symbol"], row["company"])
            if row["company"]:
                mapping[row["symbol"]] = row["company"]

    return mapping


def load_symbol_industry_map() -> dict[str, str]:
    """Symbol -> Industry from mid/small cap index CSVs."""
    mapping: dict[str, str] = {}
    for key in MID_SMALL_INDEX_FILES:
        for row in _read_universe_csv(INDEX_FILES[key]):
            if row["industry"]:
                mapping[row["symbol"]] = row["industry"]
    return mapping


def load_full_symbol_industry_map() -> dict[str, str]:
    """Symbol -> Industry — master CSV + index overlay."""
    mapping: dict[str, str] = {}

    if NSE_EQUITY_ALL.exists():
        for row in _read_universe_csv(NSE_EQUITY_ALL):
            if row["industry"]:
                mapping[row["symbol"]] = row["industry"]

    for path in INDEX_FILES.values():
        for row in _read_universe_csv(path):
            if row["industry"]:
                mapping[row["symbol"]] = row["industry"]

    return mapping


def load_phase1_universe() -> list[str]:
    """Nifty Midcap 150 + Smallcap 250 only (EQ series)."""
    seen: set[str] = set()
    ordered: list[str] = []
    for key in MID_SMALL_INDEX_FILES:
        path = INDEX_FILES[key]
        for sym in _symbols_from_csv(path):
            if sym not in seen:
                seen.add(sym)
                ordered.append(sym)
    return ordered


def search_universe_symbols(query: str, *, limit: int = 40) -> list[dict[str, str]]:
    """Ranked symbol search for autocomplete (symbol prefix > contains > company)."""
    ql = query.strip().lower()
    if not ql:
        return []

    company_map = load_full_symbol_company_map()
    scored: list[tuple[int, str, str]] = []

    for sym, company in company_map.items():
        sl = sym.lower()
        cl = company.lower()
        if ql not in sl and ql not in cl:
            continue
        score = 0
        if sl == ql:
            score = 100
        elif sl.startswith(ql):
            score = 80
        elif ql in sl:
            score = 60
        elif cl.startswith(ql):
            score = 50
        elif ql in cl:
            score = 40
        scored.append((score, sym, company))

    scored.sort(key=lambda x: (-x[0], x[1]))
    return [{"symbol": sym, "company": co} for _, sym, co in scored[:limit]]
