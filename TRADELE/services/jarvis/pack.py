"""Load JARVIS Test Lab 1-minute Excel pack for replay."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
LATEST = ROOT / "data" / "jarvis" / "testlab_1m_latest.xlsx"


def pack_path() -> Path:
    return LATEST


def pack_exists() -> bool:
    return LATEST.exists()


@lru_cache(maxsize=1)
def _load_frames() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if not LATEST.exists():
        raise FileNotFoundError(f"Missing Test Lab pack: {LATEST}")
    meta = pd.read_excel(LATEST, sheet_name="meta")
    symbols = pd.read_excel(LATEST, sheet_name="symbols")
    candles = pd.read_excel(LATEST, sheet_name="candles")
    candles["datetime"] = pd.to_datetime(candles["datetime"], utc=True).dt.tz_convert("Asia/Kolkata")
    candles["symbol"] = candles["symbol"].astype(str).str.upper()
    return meta, symbols, candles


def clear_cache() -> None:
    _load_frames.cache_clear()


def pack_info() -> dict[str, Any]:
    if not pack_exists():
        return {"ok": False, "exists": False, "path": str(LATEST)}
    meta, symbols, candles = _load_frames()
    m = meta.iloc[0].to_dict() if len(meta) else {}
    return {
        "ok": True,
        "exists": True,
        "path": str(LATEST),
        "meta": {k: (None if pd.isna(v) else v) for k, v in m.items()},
        "symbols_with_data": int((symbols["bars"] > 0).sum()) if "bars" in symbols.columns else 0,
        "total_bars": int(len(candles)),
        "sources": symbols["source"].value_counts().to_dict() if "source" in symbols.columns else {},
        "symbol_list": [
            str(r.symbol)
            for r in symbols.itertuples()
            if getattr(r, "bars", 0) and int(r.bars) > 0
        ][:120],
    }


def list_symbols() -> list[str]:
    info = pack_info()
    return list(info.get("symbol_list") or [])


def candles_for(symbol: str) -> list[dict[str, Any]]:
    _, _, candles = _load_frames()
    sym = symbol.upper().strip()
    sub = candles[candles["symbol"] == sym].sort_values("datetime")
    out = []
    for r in sub.itertuples():
        out.append(
            {
                "symbol": sym,
                "datetime": r.datetime.isoformat(),
                "open": float(r.open),
                "high": float(r.high),
                "low": float(r.low),
                "close": float(r.close),
                "volume": int(r.volume or 0),
                "source": getattr(r, "source", "zerodha"),
            }
        )
    return out


def timeline_minutes() -> list[str]:
    """Unique minute timestamps across the pack (IST)."""
    _, _, candles = _load_frames()
    stamps = sorted(candles["datetime"].unique())
    return [pd.Timestamp(t).isoformat() for t in stamps]


def snapshot_at(minute_iso: str, symbols: Optional[list[str]] = None) -> list[dict[str, Any]]:
    """OHLCV row per symbol at or before the given minute (as-of)."""
    _, _, candles = _load_frames()
    ts = pd.Timestamp(minute_iso)
    if ts.tzinfo is None:
        ts = ts.tz_localize("Asia/Kolkata")
    else:
        ts = ts.tz_convert("Asia/Kolkata")
    frame = candles[candles["datetime"] <= ts]
    if symbols:
        want = {s.upper() for s in symbols}
        frame = frame[frame["symbol"].isin(want)]
    if frame.empty:
        return []
    idx = frame.groupby("symbol")["datetime"].idxmax()
    rows = frame.loc[idx]
    return [
        {
            "symbol": str(r.symbol),
            "datetime": r.datetime.isoformat(),
            "open": float(r.open),
            "high": float(r.high),
            "low": float(r.low),
            "close": float(r.close),
            "volume": int(r.volume or 0),
            "source": getattr(r, "source", "zerodha"),
        }
        for r in rows.itertuples()
    ]
