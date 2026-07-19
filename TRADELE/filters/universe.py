"""Load NSE index symbol lists for scanning."""
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

MID_SMALL_INDEX_FILES = ("midcap150", "smallcap250")


def _symbols_from_csv(path: Path) -> list[str]:
    if not path.exists():
        logger.warning("Universe file missing: %s", path)
        return []
    symbols: list[str] = []
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sym = (row.get("Symbol") or row.get("symbol") or "").strip()
            if sym and row.get("Series", "EQ") == "EQ":
                symbols.append(sym)
    return symbols


def load_symbol_company_map() -> dict[str, str]:
    """Symbol -> Company Name from mid/small cap index CSVs."""
    mapping: dict[str, str] = {}
    for key in MID_SMALL_INDEX_FILES:
        path = INDEX_FILES[key]
        if not path.exists():
            continue
        with path.open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                sym = (row.get("Symbol") or row.get("symbol") or "").strip()
                company = (
                    row.get("Company Name")
                    or row.get("company_name")
                    or row.get("Company")
                    or sym
                ).strip()
                if sym and row.get("Series", "EQ") == "EQ":
                    mapping[sym] = company
    return mapping


def load_full_symbol_company_map() -> dict[str, str]:
    """Symbol -> Company Name across ALL index CSVs (nifty500 + mid + small)."""
    mapping: dict[str, str] = {}
    for path in INDEX_FILES.values():
        if not path.exists():
            continue
        with path.open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                sym = (row.get("Symbol") or row.get("symbol") or "").strip()
                company = (
                    row.get("Company Name")
                    or row.get("company_name")
                    or row.get("Company")
                    or sym
                ).strip()
                if sym and row.get("Series", "EQ") == "EQ":
                    mapping.setdefault(sym, company)
    return mapping


def load_symbol_industry_map() -> dict[str, str]:
    """Symbol -> Industry from mid/small cap index CSVs."""
    mapping: dict[str, str] = {}
    for key in MID_SMALL_INDEX_FILES:
        path = INDEX_FILES[key]
        if not path.exists():
            continue
        with path.open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                sym = (row.get("Symbol") or row.get("symbol") or "").strip()
                industry = (row.get("Industry") or row.get("industry") or "Unknown").strip()
                if sym and row.get("Series", "EQ") == "EQ":
                    mapping[sym] = industry
    return mapping


def load_full_symbol_industry_map() -> dict[str, str]:
    """Symbol -> Industry across ALL index CSVs (nifty500 + mid + small)."""
    mapping: dict[str, str] = {}
    for path in INDEX_FILES.values():
        if not path.exists():
            continue
        with path.open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                sym = (row.get("Symbol") or row.get("symbol") or "").strip()
                industry = (row.get("Industry") or row.get("industry") or "").strip()
                if sym and industry and row.get("Series", "EQ") == "EQ":
                    mapping.setdefault(sym, industry)
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
