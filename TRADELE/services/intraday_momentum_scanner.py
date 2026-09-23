"""Late-session momentum scanner for tomorrow's intraday Long / Short picks.

Pattern: compression → volume expansion → breakout (or breakdown) with
VWAP / EMA / RCI alignment — not a clock-based “3 PM” rule.
"""
from __future__ import annotations

import logging
import math
import time
from datetime import date, datetime, timedelta
from typing import Any, Optional

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from TRADELE.config import settings
from TRADELE.filters.nse_data import fetch_delivery_map, fetch_market_cap_cr
from TRADELE.services.groww_client import get_historical_candles
from TRADELE.services.groww_token_store import get_active_access_token as get_groww_token
from TRADELE.services.news_aggregator import fetch_google_news
from TRADELE.services.universe import get_tradeable_equity_symbols
from TRADELE.services.zerodha_client import (
    KiteRateLimitError,
    ZerodhaClient,
    get_client,
)
from TRADELE.services.zerodha_token_store import get_active_access_token as get_zerodha_token

logger = logging.getLogger(__name__)

QUOTE_BATCH = 200
HISTORICAL_DELAY_SEC = 0.35
DEFAULT_PREFILTER = 40
RCI_PERIOD = 9
COMPRESS_BARS = 8
BREAKOUT_LOOKBACK = 20
VOL_AVG_BARS = 20
MAX_VWAP_EXT_PCT = 4.5  # avoid chasing extremes


def _f(v: Any, nd: int = 4) -> Optional[float]:
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(x) or math.isinf(x):
        return None
    return round(x, nd)


def _rankdata(arr: np.ndarray) -> np.ndarray:
    order = np.argsort(arr, kind="mergesort")
    ranks = np.empty(len(arr), dtype=float)
    ranks[order] = np.arange(1, len(arr) + 1, dtype=float)
    # average ties
    vals = arr[order]
    i = 0
    while i < len(vals):
        j = i + 1
        while j < len(vals) and vals[j] == vals[i]:
            j += 1
        if j - i > 1:
            avg = (i + 1 + j) / 2.0
            ranks[order[i:j]] = avg
        i = j
    return ranks


def compute_rci(closes: np.ndarray, period: int = RCI_PERIOD) -> Optional[float]:
    """Spearman rank correlation of price vs time in [-1, 1]."""
    if len(closes) < period:
        return None
    window = np.asarray(closes[-period:], dtype=float)
    if np.any(~np.isfinite(window)):
        return None
    price_ranks = _rankdata(window)
    time_ranks = np.arange(1, period + 1, dtype=float)
    d2 = float(np.sum((price_ranks - time_ranks) ** 2))
    denom = period * (period * period - 1)
    if denom <= 0:
        return None
    return _f(1.0 - (6.0 * d2) / denom, 4)


def _session_date(candles: list[dict]) -> Optional[date]:
    if not candles:
        return None
    raw = str(candles[-1].get("date") or "")
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return None


def _to_df(candles: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(candles)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _enrich_intraday(df: pd.DataFrame) -> pd.DataFrame:
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"].fillna(0)
    df = df.copy()
    df["ema_9"] = c.ewm(span=9, adjust=False).mean()
    df["ema_20"] = c.ewm(span=20, adjust=False).mean()
    tp = (h + l + c) / 3.0
    cum_pv = (tp * v).cumsum()
    cum_v = v.cumsum().replace(0, np.nan)
    df["vwap"] = cum_pv / cum_v
    df["vol_sma"] = v.rolling(VOL_AVG_BARS, min_periods=5).mean()
    df["range"] = (h - l).abs()
    df["high_n"] = h.rolling(BREAKOUT_LOOKBACK, min_periods=5).max().shift(1)
    df["low_n"] = l.rolling(BREAKOUT_LOOKBACK, min_periods=5).min().shift(1)
    return df


def _compression_score(ranges: np.ndarray) -> float:
    """Higher = tighter recent range vs prior range."""
    if len(ranges) < COMPRESS_BARS + 5:
        return 0.0
    recent = float(np.nanmean(ranges[-COMPRESS_BARS:]))
    prior = float(np.nanmean(ranges[-(COMPRESS_BARS + 12) : -COMPRESS_BARS]))
    if prior <= 0 or not math.isfinite(prior) or not math.isfinite(recent):
        return 0.0
    ratio = recent / prior
    if ratio >= 1.0:
        return max(0.0, 1.0 - (ratio - 1.0))
    # tighter is better; floor at 0.25 of prior
    return float(min(1.0, (1.0 - ratio) / 0.75))


def _day_return_pct(df: pd.DataFrame) -> float:
    if df.empty:
        return 0.0
    o = float(df.iloc[0]["open"] or df.iloc[0]["close"])
    c = float(df.iloc[-1]["close"])
    if not o:
        return 0.0
    return (c - o) / o * 100.0


def score_direction(df: pd.DataFrame, direction: str) -> Optional[dict[str, Any]]:
    """Score long or short late-session momentum setup on 5m bars."""
    if len(df) < 30:
        return None
    last = df.iloc[-1]
    prev = df.iloc[-2]
    close = float(last["close"])
    ema9 = float(last["ema_9"]) if pd.notna(last["ema_9"]) else None
    ema20 = float(last["ema_20"]) if pd.notna(last["ema_20"]) else None
    vwap = float(last["vwap"]) if pd.notna(last["vwap"]) else None
    vol = float(last["volume"] or 0)
    vol_sma = float(last["vol_sma"]) if pd.notna(last["vol_sma"]) else None
    high_n = float(last["high_n"]) if pd.notna(last["high_n"]) else None
    low_n = float(last["low_n"]) if pd.notna(last["low_n"]) else None

    closes = df["close"].astype(float).values
    rci_now = compute_rci(closes)
    rci_prev = compute_rci(closes[:-1]) if len(closes) > RCI_PERIOD + 1 else None
    rci_rising = (
        rci_now is not None and rci_prev is not None and rci_now > rci_prev
    )
    rci_falling = (
        rci_now is not None and rci_prev is not None and rci_now < rci_prev
    )

    day_ret = _day_return_pct(df)
    compress = _compression_score(df["range"].astype(float).values)
    vol_ratio = (vol / vol_sma) if vol_sma and vol_sma > 0 else 0.0
    vwap_ext = abs((close - vwap) / vwap * 100) if vwap else 99.0

    # Prefer late-session evidence: last ~90 minutes of NSE (after ~14:00)
    late = df[df["date"].dt.hour >= 14]
    late_vol_ratio = 0.0
    if len(late) >= 3 and vol_sma:
        late_vol_ratio = float(late["volume"].astype(float).iloc[-3:].mean() / vol_sma)

    checks: list[dict[str, Any]] = []
    score = 0.0

    def add(cid: str, label: str, ok: bool, pts: float, detail: str) -> None:
        nonlocal score
        checks.append({"id": cid, "label": label, "passed": ok, "detail": detail})
        if ok:
            score += pts

    if direction == "long":
        add("vwap", "Price > VWAP", bool(vwap and close > vwap), 12,
            f"Close {_f(close)} vs VWAP {_f(vwap)}")
        add("ema_stack", "EMA9 > EMA20", bool(ema9 and ema20 and ema9 > ema20), 12,
            f"EMA9 {_f(ema9)} / EMA20 {_f(ema20)}")
        add("above_ema9", "Price > EMA9", bool(ema9 and close > ema9), 8,
            f"Close {_f(close)} vs EMA9 {_f(ema9)}")
        brk = bool(high_n and close > high_n)
        add("breakout", f"Break above prior {BREAKOUT_LOOKBACK}-bar high", brk, 14,
            f"Close {_f(close)} vs resistance {_f(high_n)}")
        add("vol_exp", "Volume > 2× average", vol_ratio >= 2.0, 14,
            f"Vol ratio {_f(vol_ratio, 2)}× (last bar)")
        add("rci_pos", "RCI > 0", bool(rci_now is not None and rci_now > 0), 8,
            f"RCI {_f(rci_now)}")
        add("rci_up", "RCI rising", bool(rci_rising), 8,
            f"RCI {_f(rci_prev)} → {_f(rci_now)}")
        add("day_ret", "Today's return > 1%", day_ret > 1.0, 8,
            f"Day return {_f(day_ret, 2)}%")
        add("compress", "Recent range compressed", compress >= 0.35, 8,
            f"Compression score {_f(compress, 2)}")
        add("not_extended", f"Not >{MAX_VWAP_EXT_PCT}% above VWAP", vwap_ext <= MAX_VWAP_EXT_PCT, 8,
            f"VWAP distance {_f(vwap_ext, 2)}%")
        # Structure held after spike (reaccumulation bias for tomorrow)
        pullback_held = False
        if len(df) >= 10 and high_n:
            spike_idx = int(df["high"].astype(float).values[-15:].argmax()) + max(0, len(df) - 15)
            spike_high = float(df.iloc[spike_idx]["high"])
            after = df.iloc[spike_idx:]
            if len(after) >= 3:
                trough = float(after["low"].min())
                pullback_held = trough > (spike_high * 0.985) and close > trough
        add("structure", "Higher structure held after expansion", pullback_held, 10,
            "Buyers defended pullback (reaccumulation) vs full giveback")
        if late_vol_ratio >= 1.5:
            score += 5
            checks.append({
                "id": "late_vol",
                "label": "Late-session volume expansion",
                "passed": True,
                "detail": f"Post-2 PM vol ~{_f(late_vol_ratio, 2)}× avg",
            })
    else:
        add("vwap", "Price < VWAP", bool(vwap and close < vwap), 12,
            f"Close {_f(close)} vs VWAP {_f(vwap)}")
        add("ema_stack", "EMA9 < EMA20", bool(ema9 and ema20 and ema9 < ema20), 12,
            f"EMA9 {_f(ema9)} / EMA20 {_f(ema20)}")
        add("below_ema9", "Price < EMA9", bool(ema9 and close < ema9), 8,
            f"Close {_f(close)} vs EMA9 {_f(ema9)}")
        brk = bool(low_n and close < low_n)
        add("breakdown", f"Break below prior {BREAKOUT_LOOKBACK}-bar low", brk, 14,
            f"Close {_f(close)} vs support {_f(low_n)}")
        add("vol_exp", "Volume > 2× average", vol_ratio >= 2.0, 14,
            f"Vol ratio {_f(vol_ratio, 2)}× (last bar)")
        add("rci_neg", "RCI < 0", bool(rci_now is not None and rci_now < 0), 8,
            f"RCI {_f(rci_now)}")
        add("rci_dn", "RCI falling", bool(rci_falling), 8,
            f"RCI {_f(rci_prev)} → {_f(rci_now)}")
        add("day_ret", "Today's return < −1%", day_ret < -1.0, 8,
            f"Day return {_f(day_ret, 2)}%")
        add("compress", "Recent range compressed", compress >= 0.35, 8,
            f"Compression score {_f(compress, 2)}")
        add("not_extended", f"Not >{MAX_VWAP_EXT_PCT}% below VWAP", vwap_ext <= MAX_VWAP_EXT_PCT, 8,
            f"VWAP distance {_f(vwap_ext, 2)}%")
        bounce_failed = False
        if len(df) >= 10 and low_n:
            spike_idx = int(df["low"].astype(float).values[-15:].argmin()) + max(0, len(df) - 15)
            spike_low = float(df.iloc[spike_idx]["low"])
            after = df.iloc[spike_idx:]
            if len(after) >= 3:
                bounce = float(after["high"].max())
                bounce_failed = bounce < (spike_low * 1.015) and close < bounce
        add("structure", "Lower structure held after expansion", bounce_failed, 10,
            "Sellers capped bounce (redistribution) vs full reclaim")
        if late_vol_ratio >= 1.5:
            score += 5
            checks.append({
                "id": "late_vol",
                "label": "Late-session volume expansion",
                "passed": True,
                "detail": f"Post-2 PM vol ~{_f(late_vol_ratio, 2)}× avg",
            })

    max_score = 110.0
    conviction = int(min(99, round(score / max_score * 100)))
    passed = sum(1 for c in checks if c["passed"])
    total = len(checks)

    reasons = [c["label"] for c in checks if c["passed"]]
    misses = [c["label"] for c in checks if not c["passed"]]

    return {
        "direction": direction,
        "score": _f(score, 1),
        "conviction": conviction,
        "checks_passed": passed,
        "checks_total": total,
        "reasons": reasons,
        "misses": misses,
        "checks": checks,
        "metrics": {
            "close": _f(close),
            "open_day": _f(float(df.iloc[0]["open"] or close)),
            "ema_9": _f(ema9),
            "ema_20": _f(ema20),
            "vwap": _f(vwap),
            "rci": rci_now,
            "rci_prev": rci_prev,
            "volume_ratio": _f(vol_ratio, 2),
            "day_return_pct": _f(day_ret, 2),
            "vwap_distance_pct": _f(vwap_ext, 2),
            "compression": _f(compress, 2),
            "resistance": _f(high_n),
            "support": _f(low_n),
            "late_vol_ratio": _f(late_vol_ratio, 2),
        },
    }


def _batch_quotes(client: ZerodhaClient, symbols: list[str]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for i in range(0, len(symbols), QUOTE_BATCH):
        chunk = symbols[i : i + QUOTE_BATCH]
        keys = [f"NSE:{s}" for s in chunk]
        try:
            quotes = client.get_quote(keys)
            for key, q in (quotes or {}).items():
                sym = key.split(":", 1)[-1]
                ohlc = q.get("ohlc") or {}
                last = float(q.get("last_price") or ohlc.get("close") or 0)
                prev = float(ohlc.get("close") or 0)
                open_ = float(ohlc.get("open") or last or 0)
                vol = float(q.get("volume") or 0)
                chg = ((last - prev) / prev * 100) if prev else 0.0
                day_from_open = ((last - open_) / open_ * 100) if open_ else chg
                out[sym] = {
                    "last": last,
                    "prev_close": prev,
                    "open": open_,
                    "volume": vol,
                    "change_pct": chg,
                    "day_return_pct": day_from_open,
                }
        except Exception as e:
            logger.warning("Quote batch failed: %s", e)
        time.sleep(0.15)
    return out


def _fetch_5m(
    db: Session,
    username: str,
    client: Optional[ZerodhaClient],
    symbol: str,
    trade_date: date,
) -> tuple[list[dict[str, Any]], str]:
    """Prefer Zerodha 5-minute; fall back to Groww."""
    from_str = trade_date.isoformat()
    to_str = trade_date.isoformat()

    # Cache first
    from TRADELE.db.models import CandleCache

    row = (
        db.query(CandleCache)
        .filter(
            CandleCache.symbol == symbol,
            CandleCache.exchange == "NSE",
            CandleCache.interval == "5minute",
            CandleCache.from_date == from_str,
            CandleCache.to_date == to_str,
        )
        .first()
    )
    if row and isinstance(row.data, list) and len(row.data) > 20:
        return row.data, "cache"

    if client:
        try:
            candles = client.get_historical(
                symbol,
                "NSE",
                "5minute",
                trade_date,
                trade_date,
                db=db,
                use_cache=True,
            )
            if candles and len(candles) > 20:
                return candles, "zerodha"
        except KiteRateLimitError:
            raise
        except Exception as e:
            logger.debug("Zerodha 5m failed %s: %s", symbol, e)

    g_token = get_groww_token(db, username)
    if g_token:
        start = f"{trade_date.isoformat()} 09:15:00"
        end = f"{trade_date.isoformat()} 15:30:00"
        candles: list[dict[str, Any]] = []
        for interval in ("5minute", "1minute"):
            try:
                raw = get_historical_candles(
                    g_token,
                    trading_symbol=symbol,
                    exchange="NSE",
                    segment="CASH",
                    start_time=start,
                    end_time=end,
                    candle_interval=interval,
                )
                if not raw:
                    continue
                candles = raw if interval == "5minute" else _resample_to_5m(raw)
                if candles and len(candles) > 20:
                    break
            except Exception as e:
                logger.debug("Groww %s failed %s: %s", interval, symbol, e)
        if candles and len(candles) > 20:
            try:
                existing = (
                    db.query(CandleCache)
                    .filter(
                        CandleCache.symbol == symbol,
                        CandleCache.exchange == "NSE",
                        CandleCache.interval == "5minute",
                        CandleCache.from_date == from_str,
                        CandleCache.to_date == to_str,
                    )
                    .first()
                )
                if existing:
                    existing.data = candles
                else:
                    db.add(
                        CandleCache(
                            symbol=symbol,
                            exchange="NSE",
                            interval="5minute",
                            from_date=from_str,
                            to_date=to_str,
                            data=candles,
                        )
                    )
                db.commit()
            except Exception:
                db.rollback()
            return candles, "groww"

    return [], "none"


def _resample_to_5m(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    df = _to_df(candles)
    if df.empty:
        return []
    df = df.set_index("date")
    ohlc = df.resample("5min").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna(subset=["close"])
    out: list[dict[str, Any]] = []
    for ts, row in ohlc.iterrows():
        out.append(
            {
                "date": ts.isoformat(),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"] or 0),
            }
        )
    return out


def _yahoo_checks(symbol: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "available": False,
        "market_cap_cr": None,
        "avg_volume": None,
        "recommendation": None,
        "headline": None,
        "notes": [],
    }
    try:
        import yfinance as yf

        t = yf.Ticker(f"{symbol}.NS")
        info = t.info or {}
        out["available"] = True
        cap = info.get("marketCap")
        if cap:
            out["market_cap_cr"] = round(float(cap) / 1e7, 2)
        avg_vol = info.get("averageVolume") or info.get("averageDailyVolume10Day")
        if avg_vol:
            out["avg_volume"] = int(avg_vol)
        rec = info.get("recommendationKey") or info.get("recommendationMean")
        if rec is not None:
            out["recommendation"] = str(rec)
        news = getattr(t, "news", None) or []
        if news and isinstance(news, list):
            first = news[0] if news else {}
            title = (first.get("title") or (first.get("content") or {}).get("title") or "")
            if title:
                out["headline"] = str(title)[:180]
        if out["market_cap_cr"] and out["market_cap_cr"] >= 500:
            out["notes"].append(f"Liquid mid/large cap (~₹{out['market_cap_cr']} Cr)")
        if out["avg_volume"] and out["avg_volume"] >= 200_000:
            out["notes"].append(f"Healthy avg volume ({out['avg_volume']:,})")
        if out["headline"]:
            out["notes"].append(f"Yahoo: {out['headline']}")
    except Exception as e:
        out["notes"].append(f"Yahoo unavailable: {e}")
    return out


def _news_checks(symbol: str) -> dict[str, Any]:
    items = []
    try:
        items = fetch_google_news(f"{symbol} stock NSE", limit=5)
    except Exception as e:
        logger.debug("News fetch failed %s: %s", symbol, e)
    headlines = [
        {
            "title": n.title,
            "source": n.source,
            "link": n.link,
            "published": n.published.isoformat() if n.published else None,
        }
        for n in items[:5]
    ]
    bullish_kw = ("surge", "profit", "growth", "beat", "record", "upgrade", "order", "win")
    bearish_kw = ("fall", "loss", "probe", "fraud", "downgrade", "ban", "raid", "penalty", "miss")
    blob = " ".join(h["title"].lower() for h in headlines)
    tone = "neutral"
    if any(k in blob for k in bullish_kw) and not any(k in blob for k in bearish_kw):
        tone = "positive"
    elif any(k in blob for k in bearish_kw) and not any(k in blob for k in bullish_kw):
        tone = "negative"
    return {
        "count": len(headlines),
        "tone": tone,
        "headlines": headlines,
        "ok_for_long": tone != "negative",
        "ok_for_short": tone != "positive",
    }


def _nse_checks(symbol: str, delivery_map: dict[str, float]) -> dict[str, Any]:
    delivery = delivery_map.get(symbol)
    mcap = None
    try:
        mcap = fetch_market_cap_cr(symbol)
    except Exception:
        pass
    notes = []
    # Lower delivery can mean more speculative/intraday flow; high delivery = positional
    if delivery is not None:
        if delivery < 40:
            notes.append(f"Delivery {delivery:.1f}% — speculative flow (good for intraday)")
        else:
            notes.append(f"Delivery {delivery:.1f}% — more delivery-driven")
    if mcap:
        notes.append(f"NSE/YF mcap ~₹{mcap} Cr")
    return {
        "delivery_pct": _f(delivery, 1) if delivery is not None else None,
        "market_cap_cr": mcap,
        "notes": notes,
        "intraday_friendly": delivery is None or delivery < 55,
    }


def build_conviction(
    symbol: str,
    direction: str,
    tech: dict[str, Any],
    delivery_map: dict[str, float],
    source: str,
) -> dict[str, Any]:
    news = _news_checks(symbol)
    nse = _nse_checks(symbol, delivery_map)
    yahoo = _yahoo_checks(symbol)

    external_checks: list[dict[str, Any]] = []
    if direction == "long":
        external_checks.append({
            "id": "news",
            "label": "News not hostile for long",
            "passed": news["ok_for_long"],
            "detail": f"Tone={news['tone']}, {news['count']} headlines",
        })
    else:
        external_checks.append({
            "id": "news",
            "label": "News not hostile for short",
            "passed": news["ok_for_short"],
            "detail": f"Tone={news['tone']}, {news['count']} headlines",
        })
    external_checks.append({
        "id": "nse_delivery",
        "label": "NSE delivery allows intraday flow",
        "passed": bool(nse["intraday_friendly"]),
        "detail": "; ".join(nse["notes"]) or "Delivery unavailable",
    })
    liquid = bool(
        (yahoo.get("avg_volume") or 0) >= 150_000
        or (yahoo.get("market_cap_cr") or 0) >= 400
        or (nse.get("market_cap_cr") or 0) >= 400
    )
    external_checks.append({
        "id": "liquidity",
        "label": "Yahoo/NSE liquidity OK",
        "passed": liquid,
        "detail": "; ".join(yahoo.get("notes") or []) or "Liquidity check soft-pass if quotes exist",
    })

    tech_checks = tech.get("checks") or []
    all_checks = list(tech_checks) + external_checks
    passed = sum(1 for c in all_checks if c.get("passed"))
    total = len(all_checks)
    tech_conv = int(tech.get("conviction") or 0)
    # Blend: technical dominates, externals nudge
    ext_pass = sum(1 for c in external_checks if c.get("passed"))
    ext_bonus = int(round(ext_pass / max(1, len(external_checks)) * 12))
    conviction = int(min(99, tech_conv + ext_bonus - (0 if news["ok_for_long" if direction == "long" else "ok_for_short"] else 8)))

    can_trade = (
        conviction >= 55
        and passed >= max(6, int(total * 0.55))
        and (tech.get("checks_passed") or 0) >= 5
    )

    m = tech.get("metrics") or {}
    if direction == "long":
        plan = (
            f"Tomorrow long plan: watch reclaim / hold of {_f(m.get('support') or m.get('ema_20'))} "
            f"with price > VWAP {_f(m.get('vwap'))}. Trigger on second push above "
            f"{_f(m.get('resistance') or m.get('close'))} with volume ≥2×. "
            f"Avoid chasing if already >{MAX_VWAP_EXT_PCT}% extended from VWAP."
        )
        narrative = (
            "Today showed compression → volume expansion → upside structure. "
            "That is the pre-spike setup — study the hold into close, not the spike alone."
        )
    else:
        plan = (
            f"Tomorrow short plan: watch rejection under {_f(m.get('resistance') or m.get('ema_20'))} "
            f"with price < VWAP {_f(m.get('vwap'))}. Trigger on second push below "
            f"{_f(m.get('support') or m.get('close'))} with volume ≥2×. "
            f"Cover if price reclaims VWAP with rising RCI."
        )
        narrative = (
            "Today showed compression → volume expansion → downside structure. "
            "Failed reclaim / lower highs into close favor a short bias tomorrow."
        )

    verdict = (
        "Yes — tomorrow this qualifies as an A-/B+ intraday candidate."
        if can_trade
        else "Not yet — wait for open confirmation; checklist incomplete."
    )

    return {
        "symbol": symbol,
        "direction": direction,
        "conviction": conviction,
        "can_trade_tomorrow": can_trade,
        "verdict": verdict,
        "narrative": narrative,
        "plan": plan,
        "checks": all_checks,
        "checks_passed": passed,
        "checks_total": total,
        "reasons": tech.get("reasons") or [],
        "misses": tech.get("misses") or [],
        "metrics": m,
        "news": news,
        "nse": nse,
        "yahoo": yahoo,
        "data_source": source,
        "score": tech.get("score"),
    }


def _persist(db: Session, username: str, result: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    try:
        from TRADELE.services.intraday_momentum_store import save_momentum_scan

        run_id = save_momentum_scan(db, username=username, result=result, **kwargs)
        result["run_id"] = run_id
        result["saved"] = bool(run_id)
    except Exception as e:
        logger.warning("Could not save momentum scan: %s", e)
        result["saved"] = False
    return result


def run_tomorrow_intraday_scan(
    db: Session,
    username: str = "leninstark",
    *,
    max_symbols: Optional[int] = None,
    top_n: int = 3,
    trade_date: Optional[date] = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """
    Scan for Top N Long + Top N Short candidates for tomorrow's intraday.
    Uses last completed NSE session by default. Serves saved day conviction
    when present (deterministic) unless force_refresh=True.
    """
    from TRADELE.services.intraday_momentum_store import (
        get_day_cached_scan,
        get_latest_good_scan,
        last_completed_session,
    )

    if trade_date is None:
        trade_date = last_completed_session()
    else:
        while trade_date.weekday() >= 5:
            trade_date -= timedelta(days=1)

    if not force_refresh:
        cached = get_day_cached_scan(db, username=username, as_of=trade_date)
        if cached and (cached.get("longs") or cached.get("shorts")):
            cached["message"] = (
                f"Loaded saved conviction for {trade_date.isoformat()} (deterministic day cache)."
            )
            return cached

    max_symbols = max_symbols or min(settings.momentum_max_symbols, DEFAULT_PREFILTER)
    z_token = get_zerodha_token(db, username)
    client: Optional[ZerodhaClient] = None
    if z_token or settings.kite_access_token:
        try:
            client = get_client(z_token)
        except Exception as e:
            logger.warning("Zerodha client init failed: %s", e)

    symbols = get_tradeable_equity_symbols(client=client)
    if not symbols:
        fallback = get_latest_good_scan(db, username=username)
        if fallback:
            fallback["message"] = "No universe; showing last saved conviction."
            return fallback
        return _persist(
            db,
            username,
            {
                "error": "no_universe",
                "message": "No tradeable symbols. Connect Zerodha or add nifty500.txt.",
                "longs": [],
                "shorts": [],
                "as_of": trade_date.isoformat(),
                "scanned": 0,
                "prefiltered": 0,
                "sources": [],
            },
            status="failed",
            error_message="no_universe",
        )

    # Phase 1 — quotes prefilter (cheap vs historical)
    movers: list[tuple[str, float, dict[str, float]]] = []
    if client:
        quotes = _batch_quotes(client, symbols)
        for sym, q in quotes.items():
            last = float(q.get("last") or 0)
            if last < settings.min_price or last > settings.max_price:
                continue
            day_ret = abs(q.get("day_return_pct") or q.get("change_pct") or 0)
            vol = q.get("volume") or 0
            # After hours / next calendar day, change% may still reflect last session
            if day_ret < 0.6:
                continue
            movers.append((sym, day_ret * math.log10(max(vol, 10)), q))
        movers.sort(key=lambda x: x[1], reverse=True)
        candidates = [m[0] for m in movers[:max_symbols]]
    else:
        candidates = symbols[:max_symbols]

    if not candidates:
        cached = get_day_cached_scan(db, username=username, as_of=trade_date) or get_latest_good_scan(
            db, username=username
        )
        if cached:
            cached["message"] = "No live movers; showing saved conviction."
            return cached
        return _persist(
            db,
            username,
            {
                "error": "no_movers",
                "message": "No liquid movers found for the momentum prefilter.",
                "longs": [],
                "shorts": [],
                "as_of": trade_date.isoformat(),
                "scanned": 0,
                "prefiltered": 0,
                "sources": [],
            },
            status="failed",
            error_message="no_movers",
        )

    delivery_map: dict[str, float] = {}
    try:
        delivery_map = fetch_delivery_map()
    except Exception as e:
        logger.debug("Delivery map failed: %s", e)

    long_scored: list[tuple[float, str, dict, str]] = []
    short_scored: list[tuple[float, str, dict, str]] = []
    scanned = 0
    sources_used: set[str] = set()
    rate_limited = False

    for sym in candidates:
        try:
            candles, src = _fetch_5m(db, username, client, sym, trade_date)
            time.sleep(HISTORICAL_DELAY_SEC)
        except KiteRateLimitError:
            rate_limited = True
            logger.warning("Rate limited mid-scan after %s symbols — switching to Groww-only", scanned)
            client = None  # force Groww for remainder
            try:
                candles, src = _fetch_5m(db, username, None, sym, trade_date)
            except Exception:
                continue
        if not candles:
            continue
        sources_used.add(src)
        df = _to_df(candles)
        if df.empty or len(df) < 30:
            continue
        # Keep session day; if bars are labeled otherwise, use the last bar's date
        day_df = df[df["date"].dt.date == trade_date]
        if len(day_df) < 30:
            last_day = df["date"].dt.date.iloc[-1]
            day_df = df[df["date"].dt.date == last_day]
        if len(day_df) < 30:
            continue
        df = _enrich_intraday(day_df.reset_index(drop=True))
        scanned += 1

        for direction in ("long", "short"):
            tech = score_direction(df, direction)
            if not tech:
                continue
            # Require minimum technical hits to enter board
            if (tech.get("checks_passed") or 0) < 4:
                continue
            key = float(tech.get("score") or 0)
            bucket = long_scored if direction == "long" else short_scored
            bucket.append((key, sym, tech, src))

    long_scored.sort(key=lambda x: x[0], reverse=True)
    short_scored.sort(key=lambda x: x[0], reverse=True)

    # Deduplicate across sides — prefer higher score
    used: set[str] = set()
    longs: list[dict[str, Any]] = []
    shorts: list[dict[str, Any]] = []
    longs_all: list[dict[str, Any]] = []
    shorts_all: list[dict[str, Any]] = []

    def _tech_row(sym: str, direction: str, tech: dict[str, Any], src: str) -> dict[str, Any]:
        """Lightweight row for near-miss persistence (no external API)."""
        return {
            "symbol": sym,
            "direction": direction,
            "conviction": int(tech.get("conviction") or 0),
            "can_trade_tomorrow": False,
            "verdict": "Near-miss — stored for learning; not a top pick.",
            "narrative": "",
            "plan": "",
            "checks": tech.get("checks") or [],
            "checks_passed": tech.get("checks_passed") or 0,
            "checks_total": tech.get("checks_total") or 0,
            "reasons": tech.get("reasons") or [],
            "misses": tech.get("misses") or [],
            "metrics": tech.get("metrics") or {},
            "data_source": src,
            "score": tech.get("score"),
            "enriched": False,
        }

    for score, sym, tech, src in long_scored:
        if sym in used:
            continue
        if len(longs) < top_n:
            conv = build_conviction(sym, "long", tech, delivery_map, src)
            conv["enriched"] = True
            longs.append(conv)
            longs_all.append(conv)
            used.add(sym)
        else:
            longs_all.append(_tech_row(sym, "long", tech, src))

    used_short = set(used)
    for score, sym, tech, src in short_scored:
        if sym in used_short:
            continue
        if len(shorts) < top_n:
            conv = build_conviction(sym, "short", tech, delivery_map, src)
            conv["enriched"] = True
            shorts.append(conv)
            shorts_all.append(conv)
            used_short.add(sym)
        else:
            shorts_all.append(_tech_row(sym, "short", tech, src))

    def _by_conviction(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            items,
            key=lambda c: (
                int(c.get("conviction") or 0),
                float(c.get("score") or 0),
                int(c.get("checks_passed") or 0),
            ),
            reverse=True,
        )

    longs = _by_conviction(longs)
    shorts = _by_conviction(shorts)
    longs_all = _by_conviction(longs_all)
    shorts_all = _by_conviction(shorts_all)

    # No bars for this session (e.g. scanned calendar midnight) → serve saved day
    if scanned == 0 or (not longs and not shorts):
        cached = get_day_cached_scan(db, username=username, as_of=trade_date) or get_latest_good_scan(
            db, username=username
        )
        if cached and (cached.get("longs") or cached.get("shorts")):
            cached["message"] = (
                f"No fresh 5m setups for {trade_date.isoformat()}; "
                f"showing saved conviction from {cached.get('as_of')}."
            )
            # Still record empty attempt without poisoning day cache
            _persist(
                db,
                username,
                {
                    "as_of": trade_date.isoformat(),
                    "scanned": scanned,
                    "prefiltered": len(candidates),
                    "sources": sorted(sources_used),
                    "rate_limited": rate_limited,
                    "longs": [],
                    "shorts": [],
                    "message": "empty live scan",
                },
                status="empty",
            )
            return cached

    result = {
        "as_of": trade_date.isoformat(),
        "scanned": scanned,
        "prefiltered": len(candidates),
        "sources": sorted(sources_used),
        "rate_limited": rate_limited,
        "from_cache": False,
        "pattern": (
            "Compression → volume expansion → breakout/breakdown with "
            "VWAP/EMA/RCI alignment (late-session momentum, not clock-based)"
        ),
        "longs": longs,
        "shorts": shorts,
        "message": (
            "Too many Zerodha requests mid-scan; completed with cache/Groww where possible."
            if rate_limited
            else None
        ),
    }

    return _persist(
        db,
        username,
        result,
        longs_all=longs_all,
        shorts_all=shorts_all,
        status="partial" if rate_limited else "success",
    )


def build_setup_chart(
    db: Session,
    *,
    username: str,
    symbol: str,
    direction: str = "long",
    trade_date: Optional[date] = None,
) -> dict[str, Any]:
    """5m candles + levels + numbered callouts for Equity Intraday conviction panel."""
    from TRADELE.services.intraday_momentum_store import last_completed_session
    from TRADELE.services.zerodha_client import get_client

    sym = symbol.strip().upper()
    direction = "short" if str(direction).lower().startswith("short") else "long"
    session = trade_date or last_completed_session()
    client = None
    try:
        client = get_client()
    except Exception:
        client = None

    candles, src = _fetch_5m(db, username, client, sym, session)
    if not candles or len(candles) < 10:
        return {
            "error": "no_chart",
            "message": f"No 5-minute bars for {sym} on {session.isoformat()}",
            "symbol": sym,
            "as_of": session.isoformat(),
            "bars": [],
            "levels": {},
            "callouts": [],
        }

    df = _enrich_intraday(_to_df(candles))
    tech = score_direction(df, direction) or {}
    metrics = tech.get("metrics") or {}
    checks = tech.get("checks") or []

    bars: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        ts = row["date"]
        bars.append(
            {
                "t": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                "label": ts.strftime("%H:%M") if hasattr(ts, "strftime") else str(ts)[11:16],
                "open": _f(row.get("open")),
                "high": _f(row.get("high")),
                "low": _f(row.get("low")),
                "close": _f(row.get("close")),
                "volume": _f(row.get("volume"), 0),
                "ema_9": _f(row.get("ema_9")) if pd.notna(row.get("ema_9")) else None,
                "ema_20": _f(row.get("ema_20")) if pd.notna(row.get("ema_20")) else None,
                "vwap": _f(row.get("vwap")) if pd.notna(row.get("vwap")) else None,
            }
        )

    levels = {
        "vwap": metrics.get("vwap"),
        "ema_9": metrics.get("ema_9"),
        "ema_20": metrics.get("ema_20"),
        "resistance": metrics.get("resistance"),
        "support": metrics.get("support"),
        "close": metrics.get("close"),
        "open_day": metrics.get("open_day"),
    }

    # Numbered callouts for chartable checks (same order as checklist when possible)
    chartable = {
        "vwap": ("VWAP", "level", "vwap"),
        "ema_stack": ("EMA stack", "ema_pair", None),
        "above_ema9": ("Above EMA9", "level", "ema_9"),
        "below_ema9": ("Below EMA9", "level", "ema_9"),
        "breakout": ("Breakout level", "level", "resistance"),
        "breakdown": ("Breakdown level", "level", "support"),
        "vol_exp": ("Volume expansion", "last_volume", None),
        "late_vol": ("Late-session volume", "late_zone", None),
        "day_ret": ("Day move", "day_path", None),
        "structure": ("Structure", "last_price", None),
    }
    callouts: list[dict[str, Any]] = []
    n = 0
    for ch in checks:
        cid = str(ch.get("id") or "")
        if cid not in chartable:
            continue
        n += 1
        title, kind, key = chartable[cid]
        callouts.append(
            {
                "n": n,
                "check_id": cid,
                "title": title,
                "kind": kind,
                "level_key": key,
                "passed": bool(ch.get("passed")),
                "label": ch.get("label") or title,
                "detail": ch.get("detail") or "",
            }
        )

    return {
        "symbol": sym,
        "direction": direction,
        "as_of": session.isoformat(),
        "interval": "5minute",
        "data_source": src,
        "bars": bars,
        "levels": levels,
        "callouts": callouts,
        "checks": checks,
    }
