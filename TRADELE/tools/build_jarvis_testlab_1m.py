#!/usr/bin/env python3
"""
Build JARVIS Test Lab Excel: ~100 NSE stocks × 1 full session of 1-minute OHLCV.

Source priority:
  1) Zerodha Kite 1-minute historical (when access token is valid)
  2) Yahoo Finance NSE 1-minute (actual market bars) as fallback

Output:
  data/jarvis/testlab_1m_<YYYY-MM-DD>.xlsx
  data/jarvis/testlab_1m_latest.xlsx  (copy)

Sheets:
  meta     — session, sources, counts
  symbols  — per-symbol bar counts / first-last / source
  candles  — long format: symbol, datetime, open, high, low, close, volume, source
"""
from __future__ import annotations

import argparse
import logging
import shutil
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("jarvis_testlab_1m")

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "jarvis"

# Liquid NSE names for Test Lab (100) — mix large/mid for scanner realism
DEFAULT_UNIVERSE = [
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", "ITC", "SBIN", "BHARTIARTL",
    "HINDUNILVR", "LT", "KOTAKBANK", "AXISBANK", "BAJFINANCE", "ASIANPAINT", "MARUTI",
    "SUNPHARMA", "TITAN", "ULTRACEMCO", "NTPC", "POWERGRID", "NESTLEIND", "TATAMOTORS",
    "M&M", "WIPRO", "HCLTECH", "ADANIENT", "ADANIPORTS", "ONGC", "COALINDIA", "JSWSTEEL",
    "TATASTEEL", "TECHM", "BAJAJFINSV", "HDFCLIFE", "SBILIFE", "GRASIM", "CIPLA", "DRREDDY",
    "BPCL", "INDUSINDBK", "EICHERMOT", "APOLLOHOSP", "HEROMOTOCO", "DIVISLAB", "BRITANNIA",
    "TATACONSUM", "BAJAJ-AUTO", "HINDALCO", "LTIM", "BEL", "TRENT", "PIDILITIND", "GODREJCP",
    "SIEMENS", "DLF", "HAVELLS", "VEDL", "AMBUJACEM", "SHREECEM", "ICICIPRULI", "ICICIGI",
    "SBICARD", "CHOLAFIN", "PNB", "BANKBARODA", "CANBK", "UNIONBANK", "IOC", "GAIL",
    "RECLTD", "PFC", "IRFC", "NHPC", "NMDC", "SAIL", "HINDZINC", "JINDALSTEL", "POLYCAB",
    "DIXON", "PERSISTENT", "COFORGE", "MPHASIS", "OFSS", "PAGEIND", "INDIGO", "ZOMATO",
    "PAYTM", "NYKAA", "POLICYBZR", "DMART", "LODHA", "PRESTIGE", "GODREJPROP", "OBEROIRLTY",
    "TVSMOTOR", "ASHOKLEY", "BOSCHLTD", "MRF", "BALKRISIND", "VOLTAS", "BLUESTARCO",
]


def _last_weekday(before: Optional[date] = None) -> date:
    d = before or date.today()
    if before is None:
        d = d - timedelta(days=1)
    for _ in range(10):
        if d.weekday() < 5:
            return d
        d -= timedelta(days=1)
    return d


def _load_universe(n: int) -> list[str]:
    path = ROOT / "data" / "universe" / "nifty500.csv"
    syms: list[str] = []
    if path.exists():
        try:
            df = pd.read_csv(path)
            col = None
            for c in df.columns:
                if str(c).lower() in ("symbol", "tradingsymbol", "ticker"):
                    col = c
                    break
            if col is None:
                col = df.columns[0]
            syms = [str(x).strip().upper() for x in df[col].tolist() if str(x).strip()]
        except Exception as e:
            logger.warning("nifty500.csv read failed: %s", e)
    if len(syms) < n:
        for s in DEFAULT_UNIVERSE:
            if s not in syms:
                syms.append(s)
    # Prefer DEFAULT order first for liquidity
    ordered = []
    seen = set()
    for s in DEFAULT_UNIVERSE + syms:
        if s in seen:
            continue
        seen.add(s)
        ordered.append(s)
        if len(ordered) >= n:
            break
    return ordered[:n]


def _fetch_zerodha(symbol: str, session: date) -> list[dict[str, Any]]:
    from TRADELE.config import settings
    from TRADELE.db.session import SessionLocal
    from TRADELE.services.zerodha_client import ZerodhaClient
    from TRADELE.services.zerodha_token_store import get_active_access_token

    db = SessionLocal()
    try:
        token = get_active_access_token(db, "leninstark") or settings.kite_access_token
        if not token:
            return []
        client = ZerodhaClient(access_token=token)
        bars = client.get_historical_minute(symbol, "NSE", session, db=db, use_cache=True)
        out = []
        for b in bars or []:
            out.append(
                {
                    "symbol": symbol,
                    "datetime": b.get("date"),
                    "open": b.get("open"),
                    "high": b.get("high"),
                    "low": b.get("low"),
                    "close": b.get("close"),
                    "volume": b.get("volume", 0),
                    "source": "zerodha",
                }
            )
        return out
    except Exception as e:
        logger.debug("Zerodha miss %s: %s", symbol, e)
        return []
    finally:
        db.close()


def _fetch_yfinance(symbol: str, session: date) -> list[dict[str, Any]]:
    import yfinance as yf

    ysym = f"{symbol}.NS"
    try:
        df = yf.Ticker(ysym).history(period="5d", interval="1m", auto_adjust=False)
    except Exception as e:
        logger.warning("yfinance failed %s: %s", symbol, e)
        return []
    if df is None or df.empty:
        return []
    if df.index.tz is None:
        idx = df.index.tz_localize("Asia/Kolkata")
    else:
        idx = df.index.tz_convert("Asia/Kolkata")
    df = df.copy()
    df.index = idx
    day = df[df.index.date == session]
    if day.empty:
        # nearest available session in frame
        days = sorted(set(df.index.date))
        if not days:
            return []
        session_use = days[-1]
        day = df[df.index.date == session_use]
        session_tag = session_use
    else:
        session_tag = session
    out = []
    for ts, row in day.iterrows():
        out.append(
            {
                "symbol": symbol,
                "datetime": ts.isoformat(),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": int(row.get("Volume") or 0),
                "source": "yfinance_nse",
                "session": session_tag.isoformat(),
            }
        )
    return out


def fetch_symbol(symbol: str, session: date, prefer_zerodha: bool = True) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if prefer_zerodha:
        rows = _fetch_zerodha(symbol, session)
    if len(rows) < 50:
        yrows = _fetch_yfinance(symbol, session)
        if len(yrows) > len(rows):
            rows = yrows
    return rows


def build(session: Optional[date], n_symbols: int, sleep_s: float) -> Path:
    session = session or _last_weekday()
    symbols = _load_universe(n_symbols)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    all_rows: list[dict[str, Any]] = []
    symbol_meta: list[dict[str, Any]] = []
    zerodha_ok = 0
    yf_ok = 0

    logger.info("Building Test Lab 1m pack · session=%s · symbols=%d", session, len(symbols))
    for i, sym in enumerate(symbols, 1):
        rows = fetch_symbol(sym, session, prefer_zerodha=True)
        src = rows[0]["source"] if rows else "none"
        if src == "zerodha":
            zerodha_ok += 1
        elif src.startswith("yfinance"):
            yf_ok += 1
        if rows:
            # normalize session column
            for r in rows:
                r.setdefault("session", session.isoformat())
            all_rows.extend(rows)
            symbol_meta.append(
                {
                    "symbol": sym,
                    "bars": len(rows),
                    "source": src,
                    "first": rows[0]["datetime"],
                    "last": rows[-1]["datetime"],
                    "open": rows[0]["open"],
                    "close": rows[-1]["close"],
                    "volume_sum": int(sum(float(r.get("volume") or 0) for r in rows)),
                }
            )
            logger.info("[%d/%d] %s · %d bars · %s", i, len(symbols), sym, len(rows), src)
        else:
            symbol_meta.append(
                {
                    "symbol": sym,
                    "bars": 0,
                    "source": "none",
                    "first": None,
                    "last": None,
                    "open": None,
                    "close": None,
                    "volume_sum": 0,
                }
            )
            logger.warning("[%d/%d] %s · no bars", i, len(symbols), sym)
        if sleep_s > 0:
            time.sleep(sleep_s)

    if not all_rows:
        raise SystemExit("No bars fetched — reconnect Zerodha or check network for yfinance")

    # Resolve actual dominant session from data
    sessions = [r.get("session") for r in all_rows if r.get("session")]
    session_used = max(set(sessions), key=sessions.count) if sessions else session.isoformat()

    candles = pd.DataFrame(all_rows)
    candles = candles.sort_values(["symbol", "datetime"]).reset_index(drop=True)
    sym_df = pd.DataFrame(symbol_meta)
    meta = pd.DataFrame(
        [
            {
                "built_at": datetime.now().isoformat(timespec="seconds"),
                "requested_session": session.isoformat(),
                "session_used": session_used,
                "symbols_requested": len(symbols),
                "symbols_with_data": int((sym_df["bars"] > 0).sum()),
                "total_bars": len(candles),
                "zerodha_symbols": zerodha_ok,
                "yfinance_symbols": yf_ok,
                "interval": "1minute",
                "exchange": "NSE",
                "purpose": "JARVIS Test Lab replay",
                "note": "Zerodha preferred; yfinance NSE 1m used when Kite token invalid/missing",
            }
        ]
    )

    out = OUT_DIR / f"testlab_1m_{session_used}.xlsx"
    latest = OUT_DIR / "testlab_1m_latest.xlsx"
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        meta.to_excel(writer, sheet_name="meta", index=False)
        sym_df.to_excel(writer, sheet_name="symbols", index=False)
        candles.to_excel(writer, sheet_name="candles", index=False)
    shutil.copy2(out, latest)
    logger.info("Wrote %s (%d bars, %d symbols)", out, len(candles), int((sym_df["bars"] > 0).sum()))
    logger.info("Also %s", latest)
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="Build JARVIS Test Lab 1-minute Excel pack")
    p.add_argument("--session", type=str, default="", help="YYYY-MM-DD (default: last weekday)")
    p.add_argument("--symbols", type=int, default=100)
    p.add_argument("--sleep", type=float, default=0.15, help="Pause between symbols")
    args = p.parse_args()
    session = date.fromisoformat(args.session) if args.session else None
    build(session=session, n_symbols=args.symbols, sleep_s=args.sleep)


if __name__ == "__main__":
    main()
