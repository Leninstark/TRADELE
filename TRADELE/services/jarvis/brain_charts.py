"""Build JARVIS brain chart payloads from Excel 1m OHLC pack."""
from __future__ import annotations

from typing import Any, Optional


def _ema(values: list[float], length: int) -> list[Optional[float]]:
    out: list[Optional[float]] = [None] * len(values)
    if not values or length < 1:
        return out
    k = 2 / (length + 1)
    seed = sum(values[:length]) / length if len(values) >= length else values[0]
    start = length - 1 if len(values) >= length else 0
    ema = seed
    for i, v in enumerate(values):
        if i < start:
            continue
        if i == start:
            ema = seed if len(values) >= length else v
        else:
            ema = v * k + ema * (1 - k)
        out[i] = ema
    return out


def build_symbol_price_action(
    *,
    symbol: str,
    asof: str,
    pick: Optional[dict[str, Any]] = None,
    bars: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Build OHLC chart payload. Prefer explicit bars (live Zerodha); else Excel pack."""
    if bars:
        series = list(bars)
    else:
        from TRADELE.services.jarvis.pack import candles_for

        series = candles_for(symbol)
    upto = [b for b in series if str(b.get("datetime") or "") <= asof] if asof else series
    if len(upto) < 5:
        upto = series[: max(5, min(len(series), 60))]
    closes = [float(b["close"]) for b in upto]
    volumes = [float(b.get("volume") or 0) for b in upto]
    highs = [float(b["high"]) for b in upto]
    lows = [float(b["low"]) for b in upto]
    orb_n = min(15, len(upto))
    orb_high = max(highs[:orb_n]) if orb_n else None
    orb_low = min(lows[:orb_n]) if orb_n else None
    ema9 = _ema(closes, 9)
    ema20 = _ema(closes, 20)

    mom15: list[Optional[float]] = []
    for i in range(len(closes)):
        if i < 15:
            mom15.append(None)
        else:
            mom15.append(round((closes[i] / closes[i - 15] - 1) * 100, 3))

    candles = []
    for i, b in enumerate(upto):
        dt = str(b.get("datetime") or "")
        candles.append(
            {
                "datetime": dt,
                "label": dt[11:16] if len(dt) >= 16 else dt,
                "open": float(b["open"]),
                "high": float(b["high"]),
                "low": float(b["low"]),
                "close": float(b["close"]),
                "volume": int(b.get("volume") or 0),
                "ema9": ema9[i],
                "ema20": ema20[i],
                "mom15": mom15[i],
            }
        )

    return {
        "symbol": symbol,
        "asof": asof,
        "bars": len(candles),
        "candles": candles,
        "orb_high": orb_high,
        "orb_low": orb_low,
        "orb_minutes": orb_n,
        "entry": (pick or {}).get("entry"),
        "sl": (pick or {}).get("sl"),
        "tp": (pick or {}).get("tp"),
        "side": (pick or {}).get("side"),
        "score": (pick or {}).get("score"),
        "strategy": (pick or {}).get("strategy"),
        "reasons": (pick or {}).get("reasons") or [],
        "last_close": closes[-1] if closes else None,
        "vol_last": volumes[-1] if volumes else 0,
    }


def build_brain_activity(scan_log: list[dict[str, Any]], decisions: list[dict[str, Any]]) -> dict[str, Any]:
    """Score feed + strategy vote mix for brain graphs."""
    scores = []
    for row in scan_log:
        if row.get("status") != "ok" or row.get("score") is None:
            continue
        scores.append(
            {
                "symbol": row.get("symbol"),
                "score": float(row["score"]),
                "side": row.get("side"),
                "strategy": row.get("strategy"),
            }
        )
    vote_counts: dict[str, int] = {"J-A": 0, "J-B": 0, "J-C": 0, "other": 0}
    long_n = short_n = 0
    for s in scores:
        side = (s.get("side") or "").upper()
        if side == "LONG":
            long_n += 1
        elif side == "SHORT":
            short_n += 1
        st = s.get("strategy") or "other"
        if st in vote_counts:
            vote_counts[st] += 1
        else:
            vote_counts["other"] += 1

    # histogram buckets
    buckets = {f"{i}-{i+10}": 0 for i in range(0, 100, 10)}
    for s in scores:
        sc = int(s["score"])
        key = f"{sc // 10 * 10}-{sc // 10 * 10 + 10}"
        if key in buckets:
            buckets[key] += 1

    return {
        "score_feed": scores[-80:],
        "histogram": [{"bucket": k, "count": v} for k, v in buckets.items()],
        "votes": [{"strategy": k, "count": v} for k, v in vote_counts.items() if v > 0],
        "long_n": long_n,
        "short_n": short_n,
        "decision_n": len(decisions),
        "scanned_ok": len(scores),
    }
