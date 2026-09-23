"""Day review: 1-min candles + entry/exit markers + symbol-level AI coaching."""
from __future__ import annotations

import json
import logging
import math
import re
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from TRADELE.db.models import CandleCache, GrowwOrder, GrowwTradingDay
from TRADELE.engines.indicators.calculator import IndicatorCalculator
from TRADELE.services.data_fetcher import candles_to_dataframe
from TRADELE.services.groww_client import get_historical_candles
from TRADELE.services.groww_token_store import get_active_access_token
from TRADELE.services.llm_agent import call_llm_auto
from TRADELE.services.mytrade_analytics import (
    INTRADAY_PRODUCTS,
    SWING_PRODUCTS,
    Style,
    filter_orders_for_style,
    filter_positions_for_style,
    products_for_calendar_style,
    sum_realised_pnl,
)
from TRADELE.services.zerodha_client import get_client
from TRADELE.services.zerodha_token_store import get_active_access_token as get_zerodha_token

logger = logging.getLogger(__name__)


def _products_for_style(style: Style) -> set[str]:
    prods = products_for_calendar_style(style)
    if prods is None:
        return {"MIS", "CNC", "NRML"}
    return prods


def _order_time_iso(order: GrowwOrder) -> Optional[str]:
    raw = order.raw if isinstance(order.raw, dict) else {}
    for key in ("exchange_time", "created_at"):
        if raw.get(key):
            return str(raw[key])
    return None


def _parse_ts(val: str) -> Optional[datetime]:
    """Parse to naive datetime (drop tz) so candle vs order times can be compared."""
    s = (val or "").strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt
    except ValueError:
        pass
    s = s.replace("Z", "")
    # Strip trailing offset like +05:30 / -0530 if still present
    if len(s) > 19 and (s[-6] in "+-" or s[-5] in "+-"):
        for i, ch in enumerate(s):
            if ch in "+-" and i >= 19:
                s = s[:i]
                break
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(s[:26], fmt)
        except ValueError:
            continue
    return None


def _cache_get(db: Session, symbol: str, trade_date: date) -> Optional[list[dict[str, Any]]]:
    row = (
        db.query(CandleCache)
        .filter(
            CandleCache.symbol == symbol,
            CandleCache.exchange == "NSE",
            CandleCache.interval == "minute",
            CandleCache.from_date == trade_date.isoformat(),
            CandleCache.to_date == trade_date.isoformat(),
        )
        .first()
    )
    if row and isinstance(row.data, list) and len(row.data) > 10:
        return row.data
    return None


def _cache_put(db: Session, symbol: str, trade_date: date, candles: list[dict[str, Any]]) -> None:
    if not candles:
        return
    try:
        existing = (
            db.query(CandleCache)
            .filter(
                CandleCache.symbol == symbol,
                CandleCache.exchange == "NSE",
                CandleCache.interval == "minute",
                CandleCache.from_date == trade_date.isoformat(),
                CandleCache.to_date == trade_date.isoformat(),
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
                    interval="minute",
                    from_date=trade_date.isoformat(),
                    to_date=trade_date.isoformat(),
                    data=candles,
                )
            )
        db.commit()
    except Exception as e:
        logger.warning("minute cache put failed: %s", e)
        db.rollback()


def _provider_error_message(exc: BaseException, provider: str) -> str:
    """Human-readable candle fetch error (preserve HTTP status / body when present)."""
    try:
        import httpx

        if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
            code = exc.response.status_code
            body = (exc.response.text or "").strip()
            snippet = body[:180].replace("\n", " ")
            if code == 403:
                return (
                    f"{provider} historical candles returned 403 Forbidden"
                    + (f" — {snippet}" if snippet else "")
                    + ". Trading APIs may work while candle history is blocked on this API key/plan."
                )
            if code == 429:
                return (
                    f"{provider} rate limit (429). Wait a minute and retry, or reduce refreshes."
                    + (f" Detail: {snippet}" if snippet else "")
                )
            return f"{provider} HTTP {code}" + (f": {snippet}" if snippet else "")
    except Exception:
        pass
    return f"{provider}: {exc}"


def fetch_minute_candles(
    db: Session, username: str, symbol: str, trade_date: date
) -> tuple[list[dict[str, Any]], str, Optional[str]]:
    """Fetch & store 1-min candles. Prefer Zerodha, fall back to Groww.

    Returns (candles, source, error). error is set when no candles were obtained.
    """
    cached = _cache_get(db, symbol, trade_date)
    if cached:
        return cached, "cache", None

    errors: list[str] = []
    z_token = get_zerodha_token(db, username)
    if z_token:
        try:
            client = get_client(z_token)
            candles = client.get_historical_minute(symbol, "NSE", trade_date, db=db, use_cache=True)
            if candles:
                return candles, "zerodha", None
            errors.append("Zerodha returned no 1-min bars for this session.")
        except Exception as e:
            msg = _provider_error_message(e, "Zerodha")
            errors.append(msg)
            logger.warning("Zerodha 1-min fetch failed %s: %s", symbol, e)
    else:
        errors.append("Zerodha not connected.")

    g_token = get_active_access_token(db, username)
    if g_token:
        try:
            start = f"{trade_date.isoformat()} 09:15:00"
            end = f"{trade_date.isoformat()} 15:30:00"
            candles = get_historical_candles(
                g_token,
                trading_symbol=symbol,
                exchange="NSE",
                segment="CASH",
                start_time=start,
                end_time=end,
                candle_interval="1minute",
            )
            if candles:
                _cache_put(db, symbol, trade_date, candles)
                return candles, "groww", None
            errors.append("Groww returned no 1-min bars for this session.")
        except Exception as e:
            msg = _provider_error_message(e, "Groww")
            errors.append(msg)
            logger.warning("Groww 1-min fetch failed %s: %s", symbol, e)
    else:
        errors.append("Groww access token missing or expired.")

    return [], "none", " · ".join(errors)


def _fnum(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(x) or math.isinf(x):
        return None
    return round(x, 4)


def enrich_minute_candles(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach intraday study pack: VWAP, EMAs, BB, RSI, ATR, vol SMA, OR levels."""
    if not candles:
        return []
    df = candles_to_dataframe(candles)
    if df.empty or "close" not in df.columns:
        return candles
    for col in ("high", "low", "volume"):
        if col not in df.columns:
            df[col] = df["close"] if col != "volume" else 0
    calc = IndicatorCalculator
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"].fillna(0)
    df["ema_9"] = c.ewm(span=9, adjust=False).mean()
    df["ema_20"] = c.ewm(span=20, adjust=False).mean()
    df["ema_50"] = c.ewm(span=50, adjust=False).mean()
    df["rsi"] = calc._rsi(c, 14)
    df["vwap"] = calc._vwap(h, l, c, v)
    bb_u, bb_m, bb_l = calc._bollinger(c, 20, 2.0)
    df["bb_upper"], df["bb_mid"], df["bb_lower"] = bb_u, bb_m, bb_l
    df["atr"] = calc._atr(h, l, c, 14)
    df["vol_sma"] = v.rolling(20, min_periods=1).mean()
    _macd, _sig, hist = calc._macd(c)
    df["macd_hist"] = hist

    # Opening range = first 15 one-minute bars (≈ 09:15–09:30 IST)
    or_n = min(15, len(df))
    or_high = float(h.iloc[:or_n].max()) if or_n else None
    or_low = float(l.iloc[:or_n].min()) if or_n else None

    out: list[dict[str, Any]] = []
    for i, row in df.iterrows():
        idx = int(i)
        base = candles[idx] if idx < len(candles) else {}
        date_val = base.get("date")
        if not date_val and hasattr(row.get("date"), "isoformat"):
            date_val = row["date"].isoformat()
        elif not date_val:
            date_val = str(row.get("date"))
        vol = float(row.get("volume") or 0)
        vol_sma = _fnum(row["vol_sma"])
        out.append(
            {
                "date": date_val,
                "open": _fnum(row.get("open", row["close"])) or 0,
                "high": _fnum(row["high"]) or 0,
                "low": _fnum(row["low"]) or 0,
                "close": _fnum(row["close"]) or 0,
                "volume": int(vol),
                "vwap": _fnum(row["vwap"]),
                "ema_9": _fnum(row["ema_9"]),
                "ema_20": _fnum(row["ema_20"]),
                "ema_50": _fnum(row["ema_50"]),
                "bb_upper": _fnum(row["bb_upper"]),
                "bb_mid": _fnum(row["bb_mid"]),
                "bb_lower": _fnum(row["bb_lower"]),
                "rsi": _fnum(row["rsi"]),
                "atr": _fnum(row["atr"]),
                "macd_hist": _fnum(row["macd_hist"]),
                "vol_sma": vol_sma,
                "vol_ratio": round(vol / vol_sma, 2) if vol_sma else None,
                "or_high": _fnum(or_high),
                "or_low": _fnum(or_low),
            }
        )
    return out


def _nearest_bar(candles: list[dict[str, Any]], ts: str) -> Optional[dict[str, Any]]:
    target = _parse_ts(ts)
    if not target or not candles:
        return None
    best = None
    best_diff = None
    for c in candles:
        ct = _parse_ts(str(c.get("date") or ""))
        if not ct:
            continue
        diff = abs((ct - target).total_seconds())
        if best_diff is None or diff < best_diff:
            best_diff = diff
            best = c
    return best


def _markers_from_orders(orders: list[GrowwOrder]) -> list[dict[str, Any]]:
    markers: list[dict[str, Any]] = []
    for o in orders:
        if (o.order_status or "").upper() not in {"EXECUTED", "COMPLETE", "COMPLETED", "TRADED"}:
            continue
        ts = _order_time_iso(o)
        if not ts:
            continue
        side = (o.transaction_type or "").upper()
        price = o.average_fill_price or o.price
        markers.append(
            {
                "time": ts,
                "side": side,
                "kind": "entry" if side == "BUY" else "exit",
                "price": float(price) if price is not None else None,
                "quantity": o.filled_quantity or o.quantity,
                "order_id": o.groww_order_id,
                "status": o.order_status,
            }
        )
    markers.sort(key=lambda m: m["time"])
    return markers


def _marker_indicator_context(markers: list[dict[str, Any]], candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ctx: list[dict[str, Any]] = []
    for m in markers:
        bar = _nearest_bar(candles, m["time"])
        fill = m["price"]
        vwap = bar.get("vwap") if bar else None
        ema9 = bar.get("ema_9") if bar else None
        ema20 = bar.get("ema_20") if bar else None
        ema50 = bar.get("ema_50") if bar else None
        or_high = bar.get("or_high") if bar else None
        or_low = bar.get("or_low") if bar else None
        ctx.append(
            {
                "time": m["time"],
                "side": m["side"],
                "qty": m["quantity"],
                "fill": fill,
                "bar_close": bar.get("close") if bar else None,
                "vwap": vwap,
                "ema_9": ema9,
                "ema_20": ema20,
                "ema_50": ema50,
                "bb_upper": bar.get("bb_upper") if bar else None,
                "bb_lower": bar.get("bb_lower") if bar else None,
                "rsi": bar.get("rsi") if bar else None,
                "atr": bar.get("atr") if bar else None,
                "macd_hist": bar.get("macd_hist") if bar else None,
                "vol_ratio": bar.get("vol_ratio") if bar else None,
                "or_high": or_high,
                "or_low": or_low,
                "vs_vwap": (
                    "above"
                    if vwap is not None and fill is not None and fill > vwap
                    else "below"
                    if vwap is not None and fill is not None and fill < vwap
                    else None
                ),
                "ema_stack": (
                    "bullish"
                    if ema9 is not None and ema20 is not None and ema9 > ema20
                    else "bearish"
                    if ema9 is not None and ema20 is not None and ema9 < ema20
                    else None
                ),
                "vs_or": (
                    "above_or_high"
                    if or_high is not None and fill is not None and fill > or_high
                    else "below_or_low"
                    if or_low is not None and fill is not None and fill < or_low
                    else "inside_or"
                    if or_high is not None and or_low is not None and fill is not None
                    else None
                ),
            }
        )
    return ctx


def _heuristic_symbol_ai(
    symbol: str,
    pnl: Optional[float],
    markers: list[dict[str, Any]],
    context: list[dict[str, Any]],
) -> dict[str, Any]:
    buys = [m for m in markers if m["side"] == "BUY"]
    sells = [m for m in markers if m["side"] == "SELL"]
    mistakes: list[str] = []
    improvements: list[str] = []
    observations: list[str] = [
        f"{symbol}: {len(buys)} buy / {len(sells)} sell · P&L {pnl if pnl is not None else 'n/a'}."
    ]
    for c in context:
        observations.append(
            f"{c['side']} @ {str(c['time'])[11:16]} fill {c['fill']} · "
            f"VWAP {c['vwap']} · EMA9 {c['ema_9']} · EMA20 {c['ema_20']} · RSI {c['rsi']} "
            f"({c['vs_vwap'] or '?'} VWAP, {c['ema_stack'] or '?'} EMA stack)."
        )
    if len(buys) >= 2:
        mistakes.append(
            f"Re-entered {symbol} after first exit — often chasing; wait for VWAP reclaim + EMA9>EMA20 + RSI pullback to 45–55."
        )
        improvements.append("One A+ setup per name: long only on pullback to VWAP/EMA20 with RSI rising from <50.")
    if any(c.get("vs_vwap") == "below" and c["side"] == "BUY" for c in context):
        mistakes.append("Bought while price was below VWAP — weak intraday long location.")
        improvements.append("Prefer longs above VWAP; if below, wait for reclaim candle closing back over VWAP.")
    if any((c.get("rsi") or 50) > 70 and c["side"] == "BUY" for c in context):
        mistakes.append("Bought with RSI already extended (>70) — late momentum entry.")
        improvements.append("Skip longs when RSI > 70; wait for RSI reset toward 50–55 near EMA9.")
    improvements.append(
        "A+ long: price > VWAP & EMA50, EMA9 > EMA20, OR breakout with vol_ratio > 1.5, RSI 50–65, stop = entry − 1×ATR."
    )
    improvements.append(
        "Exit: RSI roll from >65, MACD hist flips negative, or close back under EMA9; trail under EMA9."
    )
    return {
        "summary": f"{symbol}-only review using VWAP, EMA stack, OR, BB, RSI, ATR, volume.",
        "observations": observations,
        "mistakes": mistakes or ["No hard process break flagged from heuristics — still check timing vs VWAP/OR."],
        "best_setup": (
            "Long checklist: close > VWAP + EMA50, EMA9 > EMA20, break/hold above OR high on rising volume, "
            "RSI 50–65 (not >70), entry on pullback to EMA9/VWAP, stop under VWAP or 1×ATR."
        ),
        "what_could_have_been_done": improvements,
        "engine": "heuristic",
    }


def _ai_symbol_coaching(
    trade_date: date,
    style: Style,
    symbol: str,
    pnl: Optional[float],
    markers: list[dict[str, Any]],
    context: list[dict[str, Any]],
    candle_count: int,
) -> dict[str, Any]:
    prompt = f"""You are an intraday trading coach. Review ONLY {symbol} on {trade_date.isoformat()} ({style}).
Do NOT mention any other stock symbols. Talk only about {symbol}.

Symbol P&L: Rs {pnl}
1-min bars available: {candle_count}
Your fills with indicator snapshot at that minute (JSON):
{json.dumps(context, indent=2)}

Teach using this intraday toolkit (cite numbers from the JSON):
- VWAP: institutional mean — prefer longs above it
- EMA9 / EMA20 / EMA50: short/medium trend stack (bull when 9>20>50)
- Opening Range (or_high/or_low, first ~15 mins): breakout/hold levels
- Bollinger Bands: stretch vs mean; fading upper band without volume is risky
- RSI(14): 45–65 pullback entries; avoid chasing >70
- ATR(14): size stops (~1×ATR) and avoid tiny scratch targets
- Volume ratio vs 20-bar SMA: confirm breakouts (want >1.5)
- MACD histogram: momentum confirm / divergence warning

Respond ONLY with valid JSON (no markdown):
{{
  "summary": "2-4 sentences ONLY about {symbol}: what you did and outcome",
  "observations": ["indicator-aware bullets for {symbol} only"],
  "mistakes": ["detailed mistakes for {symbol} with times/prices/indicators"],
  "best_setup": "clear A+ checklist using VWAP, EMAs, OR, BB, RSI, ATR, volume for this tape",
  "what_could_have_been_done": ["concrete alternate plan for each hit — entry, stop (ATR), target"]
}}
Be specific to the timestamps. No other tickers. Educate, don't fluff."""

    raw = call_llm_auto(prompt)
    if not raw:
        return _heuristic_symbol_ai(symbol, pnl, markers, context)

    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        data["engine"] = "ai"
        data.setdefault("observations", [])
        data.setdefault("mistakes", [])
        data.setdefault("what_could_have_been_done", [])
        return data
    except json.JSONDecodeError:
        base = _heuristic_symbol_ai(symbol, pnl, markers, context)
        base["summary"] = text[:600]
        base["engine"] = "ai-raw"
        return base


def _day_context(
    db: Session,
    *,
    username: str,
    trade_date: date,
    style: Style,
) -> tuple[Optional[dict[str, Any]], list[GrowwOrder], dict[str, float], float, Optional[GrowwTradingDay]]:
    """Shared day orders + pnl. Returns (error_payload, style_orders, pnl_by_symbol, day_pnl, day_row)."""
    products = _products_for_style(style)
    orders = (
        db.query(GrowwOrder)
        .filter(
            GrowwOrder.username == username,
            GrowwOrder.trade_date == trade_date,
        )
        .order_by(GrowwOrder.id.asc())
        .all()
    )
    style_orders = filter_orders_for_style(orders, style)
    if not style_orders:
        return (
            {
                "ok": False,
                "error": f"No {style} orders on {trade_date.isoformat()}",
                "date": trade_date.isoformat(),
                "style": style,
            },
            [],
            {},
            0.0,
            None,
        )

    day_row = (
        db.query(GrowwTradingDay)
        .filter(GrowwTradingDay.username == username, GrowwTradingDay.trade_date == trade_date)
        .first()
    )
    positions: list[Any] = []
    if day_row and isinstance(day_row.summary, dict):
        positions = day_row.summary.get("positions") or []
    style_positions = filter_positions_for_style(positions, style)
    day_pnl = sum_realised_pnl(style_positions, products=products)

    pnl_by_symbol: dict[str, float] = {}
    for p in style_positions:
        if not isinstance(p, dict):
            continue
        sym = str(p.get("trading_symbol") or "").upper()
        if sym:
            pnl_by_symbol[sym] = float(p.get("realised_pnl") or 0)

    return None, style_orders, pnl_by_symbol, day_pnl, day_row


def build_day_review(
    db: Session,
    *,
    username: str,
    trade_date: date,
    style: Style = "intraday",
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Light day overview: tickers + order markers. AI loads per symbol with chart."""
    del force_refresh  # coaching is per-symbol on chart endpoint
    username = username.strip().lower()
    err, style_orders, pnl_by_symbol, day_pnl, _day_row = _day_context(
        db, username=username, trade_date=trade_date, style=style
    )
    if err:
        return err

    symbols = sorted({(o.trading_symbol or "").upper() for o in style_orders if o.trading_symbol})
    ticker_list: list[dict[str, Any]] = []
    for symbol in symbols:
        sym_orders = [o for o in style_orders if (o.trading_symbol or "").upper() == symbol]
        ticker_list.append(
            {
                "symbol": symbol,
                "pnl": pnl_by_symbol.get(symbol),
                "order_count": len(sym_orders),
                "markers": _markers_from_orders(sym_orders),
            }
        )

    return {
        "ok": True,
        "date": trade_date.isoformat(),
        "style": style,
        "day_pnl": day_pnl,
        "order_count": len(style_orders),
        "symbols": symbols,
        "tickers": ticker_list,
    }


def build_symbol_chart(
    db: Session,
    *,
    username: str,
    trade_date: date,
    symbol: str,
    style: Style = "intraday",
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Lazy-load 1-min candles + indicators + symbol-only AI coaching."""
    username = username.strip().lower()
    symbol = (symbol or "").strip().upper()
    if not symbol:
        return {"ok": False, "error": "symbol is required"}

    err, style_orders, pnl_by_symbol, _day_pnl, day_row = _day_context(
        db, username=username, trade_date=trade_date, style=style
    )
    if err:
        return err

    sym_orders = [o for o in style_orders if (o.trading_symbol or "").upper() == symbol]
    if not sym_orders:
        return {
            "ok": False,
            "error": f"No {style} orders for {symbol} on {trade_date.isoformat()}",
            "date": trade_date.isoformat(),
            "style": style,
            "symbol": symbol,
        }

    raw_candles, source, candle_error = fetch_minute_candles(db, username, symbol, trade_date)
    candles = enrich_minute_candles(raw_candles)
    markers = _markers_from_orders(sym_orders)
    context = _marker_indicator_context(markers, candles)
    pnl = pnl_by_symbol.get(symbol)

    cache_key = f"day_review_sym_{style}_{symbol}"
    ai: dict[str, Any]
    if (
        not force_refresh
        and day_row
        and isinstance(day_row.summary, dict)
        and isinstance(day_row.summary.get(cache_key), dict)
        and day_row.summary[cache_key].get("date") == trade_date.isoformat()
    ):
        ai = day_row.summary[cache_key].get("ai") or {}
    else:
        ai = _ai_symbol_coaching(
            trade_date, style, symbol, pnl, markers, context, len(candles)
        )
        if day_row:
            summary = dict(day_row.summary or {})
            summary[cache_key] = {
                "date": trade_date.isoformat(),
                "style": style,
                "symbol": symbol,
                "ai": ai,
                "generated_at": datetime.utcnow().isoformat(),
            }
            day_row.summary = summary
            try:
                db.commit()
            except Exception:
                db.rollback()

    return {
        "ok": True,
        "date": trade_date.isoformat(),
        "style": style,
        "symbol": symbol,
        "pnl": pnl,
        "order_count": len(sym_orders),
        "markers": markers,
        "candles": candles,
        "candle_source": source,
        "candle_count": len(candles),
        "candle_error": candle_error,
        "ai": ai,
    }
