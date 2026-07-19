"""Rule-based intraday scoring: breakout, volume spike, trend, gaps."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd

from TRADELE.services.data_fetcher import candles_to_dataframe

logger = logging.getLogger(__name__)

# Defaults for intraday
LOOKBACK_DAYS = 20
VOLUME_MULTIPLIER = 2.0
GAP_PCT_THRESHOLD = 1.0
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30
MA_FAST, MA_SLOW = 20, 50


@dataclass
class ScoreReason:
    reason: str
    source: str  # e.g. "EOD", "volume", "breakout"
    value: Optional[Any] = None


@dataclass
class StockScore:
    symbol: str
    score: float
    direction: str  # "long" | "short"
    reasons: list[ScoreReason] = field(default_factory=list)
    key_levels: Optional[dict[str, float]] = None


def _sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period, min_periods=1).mean()


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.rolling(period, min_periods=1).mean()
    avg_loss = loss.rolling(period, min_periods=1).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    return 100 - (100 / (1 + rs))


def score_symbol_long(symbol: str, candles: list[dict]) -> Optional[StockScore]:
    """Score one symbol for intraday LONG: breakout, volume, trend, gap up."""
    if len(candles) < LOOKBACK_DAYS + 1:
        return None
    df = candles_to_dataframe(candles)
    df = df.tail(LOOKBACK_DAYS + 5).reset_index(drop=True)
    reasons: list[ScoreReason] = []
    score = 0.0
    key_levels: dict[str, float] = {}

    last = df.iloc[-1]
    prev = df.iloc[-2]
    high_20 = df["high"].tail(LOOKBACK_DAYS).max()
    low_20 = df["low"].tail(LOOKBACK_DAYS).min()
    close = float(last["close"])
    key_levels["support_20d"] = low_20
    key_levels["resistance_20d"] = high_20
    key_levels["last_close"] = close

    # Breakout above 20D high with volume
    if close > high_20 and float(last.get("volume", 0)) > 0:
        vol_avg_20 = df["volume"].tail(LOOKBACK_DAYS).mean()
        if vol_avg_20 and float(last["volume"]) >= VOLUME_MULTIPLIER * vol_avg_20:
            score += 30
            reasons.append(
                ScoreReason(
                    reason=f"Breakout above 20D high ({high_20:.2f}) with volume confirmation",
                    source="breakout",
                    value={"20d_high": high_20, "close": close},
                )
            )

    # Volume spike
    vol_avg_20 = df["volume"].tail(LOOKBACK_DAYS).mean()
    if vol_avg_20 and float(last["volume"]) >= VOLUME_MULTIPLIER * vol_avg_20:
        mult = float(last["volume"]) / vol_avg_20
        score += 15
        reasons.append(
            ScoreReason(
                reason=f"Volume spike {mult:.1f}x 20D average",
                source="volume",
                value={"multiplier": round(mult, 2), "20d_avg_vol": int(vol_avg_20)},
            )
        )

    # Trend: MA alignment
    df["ma20"] = _sma(df["close"], 20)
    df["ma50"] = _sma(df["close"], 50)
    if close > float(df["ma20"].iloc[-1]) and float(df["ma20"].iloc[-1]) > float(df["ma50"].iloc[-1]):
        score += 20
        reasons.append(
            ScoreReason(
                reason="Uptrend: close > MA20 > MA50",
                source="trend",
                value={"ma20": float(df["ma20"].iloc[-1]), "ma50": float(df["ma50"].iloc[-1])},
            )
        )

    # RSI not overbought
    df["rsi"] = _rsi(df["close"], 14)
    rsi_val = float(df["rsi"].iloc[-1])
    if rsi_val < RSI_OVERBOUGHT:
        if rsi_val < RSI_OVERSOLD:
            score += 10  # oversold bounce
            reasons.append(ScoreReason(reason=f"RSI oversold ({rsi_val:.0f}) - bounce potential", source="rsi", value=rsi_val))
        else:
            score += 5
        key_levels["rsi"] = rsi_val
    else:
        score -= 15
        reasons.append(ScoreReason(reason=f"RSI overbought ({rsi_val:.0f}) - caution", source="rsi", value=rsi_val))

    # Gap up from previous close
    prev_close = float(prev["close"])
    gap_pct = (close - prev_close) / prev_close * 100 if prev_close else 0
    if gap_pct >= GAP_PCT_THRESHOLD:
        score += 15
        reasons.append(
            ScoreReason(
                reason=f"Gap up {gap_pct:.2f}% from previous close",
                source="gap",
                value={"gap_pct": round(gap_pct, 2), "prev_close": prev_close},
            )
        )
    key_levels["prev_close"] = prev_close

    if not reasons:
        return None
    return StockScore(
        symbol=symbol,
        score=max(0, score),
        direction="long",
        reasons=reasons,
        key_levels=key_levels,
    )


def score_symbol_short(symbol: str, candles: list[dict]) -> Optional[StockScore]:
    """Score for intraday SHORT: breakdown, volume, downtrend, gap down."""
    if len(candles) < LOOKBACK_DAYS + 1:
        return None
    df = candles_to_dataframe(candles)
    df = df.tail(LOOKBACK_DAYS + 5).reset_index(drop=True)
    reasons: list[ScoreReason] = []
    score = 0.0
    key_levels: dict[str, float] = {}

    last = df.iloc[-1]
    prev = df.iloc[-2]
    high_20 = df["high"].tail(LOOKBACK_DAYS).max()
    low_20 = df["low"].tail(LOOKBACK_DAYS).min()
    close = float(last["close"])
    key_levels["support_20d"] = low_20
    key_levels["resistance_20d"] = high_20
    key_levels["last_close"] = close

    # Breakdown below 20D low with volume
    if close < low_20 and float(last.get("volume", 0)) > 0:
        vol_avg_20 = df["volume"].tail(LOOKBACK_DAYS).mean()
        if vol_avg_20 and float(last["volume"]) >= VOLUME_MULTIPLIER * vol_avg_20:
            score += 30
            reasons.append(
                ScoreReason(
                    reason=f"Breakdown below 20D low ({low_20:.2f}) with volume",
                    source="breakdown",
                    value={"20d_low": low_20, "close": close},
                )
            )

    # Volume spike (selling pressure)
    vol_avg_20 = df["volume"].tail(LOOKBACK_DAYS).mean()
    if vol_avg_20 and float(last["volume"]) >= VOLUME_MULTIPLIER * vol_avg_20:
        mult = float(last["volume"]) / vol_avg_20
        score += 15
        reasons.append(
            ScoreReason(
                reason=f"Volume spike {mult:.1f}x 20D average (selling)",
                source="volume",
                value={"multiplier": round(mult, 2)},
            )
        )

    # Downtrend
    df["ma20"] = _sma(df["close"], 20)
    df["ma50"] = _sma(df["close"], 50)
    if close < float(df["ma20"].iloc[-1]) and float(df["ma20"].iloc[-1]) < float(df["ma50"].iloc[-1]):
        score += 20
        reasons.append(
            ScoreReason(
                reason="Downtrend: close < MA20 < MA50",
                source="trend",
                value={"ma20": float(df["ma20"].iloc[-1]), "ma50": float(df["ma50"].iloc[-1])},
            )
        )

    # RSI overbought (short signal) or not oversold
    df["rsi"] = _rsi(df["close"], 14)
    rsi_val = float(df["rsi"].iloc[-1])
    if rsi_val > RSI_OVERBOUGHT:
        score += 15
        reasons.append(ScoreReason(reason=f"RSI overbought ({rsi_val:.0f}) - short", source="rsi", value=rsi_val))
    else:
        score += 5
    key_levels["rsi"] = rsi_val

    # Gap down
    prev_close = float(prev["close"])
    gap_pct = (close - prev_close) / prev_close * 100 if prev_close else 0
    if gap_pct <= -GAP_PCT_THRESHOLD:
        score += 15
        reasons.append(
            ScoreReason(
                reason=f"Gap down {gap_pct:.2f}% from previous close",
                source="gap",
                value={"gap_pct": round(gap_pct, 2), "prev_close": prev_close},
            )
        )
    key_levels["prev_close"] = prev_close

    if not reasons:
        return None
    return StockScore(
        symbol=symbol,
        score=max(0, score),
        direction="short",
        reasons=reasons,
        key_levels=key_levels,
    )


def run_scoring(
    symbol_data: dict[str, list[dict]],
    top_n: int = 10,
) -> tuple[list[StockScore], list[StockScore]]:
    """Return (top N long, top N short) by score."""
    longs: list[StockScore] = []
    shorts: list[StockScore] = []
    for sym, candles in symbol_data.items():
        l = score_symbol_long(sym, candles)
        if l:
            longs.append(l)
        s = score_symbol_short(sym, candles)
        if s:
            shorts.append(s)
    longs.sort(key=lambda x: x.score, reverse=True)
    shorts.sort(key=lambda x: x.score, reverse=True)
    return longs[:top_n], shorts[:top_n]


def reasons_to_dict(reasons: list[ScoreReason]) -> list[dict]:
    return [
        {"reason": r.reason, "source": r.source, "value": r.value}
        for r in reasons
    ]
