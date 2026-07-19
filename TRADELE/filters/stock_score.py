"""Weighted stock score (0–100) from technical + flow metrics."""
from __future__ import annotations

from typing import Any, Optional

SCORE_WEIGHTS: dict[str, int] = {
    "price_momentum": 20,
    "volume": 15,
    "delivery": 15,
    "relative_strength": 10,
    "ema_alignment": 10,
    "rsi": 5,
    "adx": 5,
    "breakout": 10,
    "sector_strength": 5,
    "news": 5,
}


def _clamp(val: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, val))


def score_price_momentum(ret5: Optional[float], ret10: Optional[float], ret20: Optional[float]) -> float:
    r5 = min(max(ret5 or 0, 0), 15) / 15 * 35
    r10 = min(max(ret10 or 0, 0), 20) / 20 * 35
    r20 = min(max(ret20 or 0, 0), 30) / 30 * 30
    return _clamp(r5 + r10 + r20)


def score_volume(volume_ratio: Optional[float]) -> float:
    return _clamp((volume_ratio or 1.0) / 3.0 * 100)


def score_delivery(delivery_pct: Optional[float], delivery_change: Optional[float] = None) -> float:
    base = min((delivery_pct or 0) / 55 * 70, 70)
    if delivery_change and delivery_change > 0:
        base += min(delivery_change * 2, 30)
    return _clamp(base)


def score_relative_strength(rs: Optional[float]) -> float:
    return _clamp(((rs or 0) + 5) / 25 * 100)


def score_ema_alignment(
    close: float,
    ema20: Optional[float],
    ema50: Optional[float],
    ema200: Optional[float],
) -> float:
    if not ema20 or not ema50 or not ema200:
        return 30.0
    if close > ema20 > ema50 > ema200:
        return 100.0
    if close > ema20 > ema50:
        return 75.0
    if close > ema20:
        return 50.0
    if close > ema50:
        return 35.0
    return 15.0


def score_rsi(rsi: Optional[float]) -> float:
    r = rsi or 50.0
    if 55 <= r <= 70:
        return 100.0
    if 45 <= r < 55:
        return 65.0
    if 70 < r <= 80:
        return 70.0
    if 30 <= r < 45:
        return 40.0
    return 25.0


def score_adx(adx: Optional[float]) -> float:
    a = adx or 15.0
    if a >= 30:
        return 100.0
    if a >= 25:
        return 85.0
    if a >= 20:
        return 65.0
    if a >= 15:
        return 45.0
    return 25.0


def score_breakout(close: float, high_20d: Optional[float]) -> float:
    if not high_20d or high_20d <= 0:
        return 40.0
    if close >= high_20d:
        return 100.0
    dist_pct = (high_20d - close) / high_20d * 100
    return _clamp(100 - dist_pct * 12)


def score_sector(sector_rank: Optional[int], total_sectors: int) -> float:
    if not sector_rank or total_sectors <= 1:
        return 50.0
    return _clamp((1 - (sector_rank - 1) / (total_sectors - 1)) * 100)


def score_news(news_score: Optional[float], sentiment: Optional[str] = None) -> float:
    if sentiment == "Positive":
        return _clamp((news_score or 75))
    if sentiment == "Negative":
        return _clamp(30 - (100 - (news_score or 30)) * 0.3)
    return _clamp(news_score or 50)


def compute_stock_score(metrics: dict[str, Any]) -> dict[str, Any]:
    """Return total score (0–100) using only factors with available data; weights renormalized."""
    close = float(metrics.get("close") or metrics.get("ltp") or 0)

    candidates: list[tuple[str, float, bool]] = [
        (
            "price_momentum",
            score_price_momentum(
                metrics.get("return_5d_pct"),
                metrics.get("return_10d_pct"),
                metrics.get("return_20d_pct"),
            ),
            any(metrics.get(k) is not None for k in ("return_5d_pct", "return_10d_pct", "return_20d_pct")),
        ),
        (
            "volume",
            score_volume(metrics.get("volume_ratio")),
            metrics.get("volume_ratio") is not None,
        ),
        (
            "delivery",
            score_delivery(metrics.get("delivery_pct"), metrics.get("delivery_change_pct")),
            metrics.get("delivery_pct") is not None,
        ),
        (
            "relative_strength",
            score_relative_strength(metrics.get("relative_strength_pct")),
            metrics.get("relative_strength_pct") is not None,
        ),
        (
            "ema_alignment",
            score_ema_alignment(close, metrics.get("ema_20"), metrics.get("ema_50"), metrics.get("ema_200")),
            close > 0 and any(metrics.get(k) is not None for k in ("ema_20", "ema_50", "ema_200")),
        ),
        ("rsi", score_rsi(metrics.get("rsi")), metrics.get("rsi") is not None),
        ("adx", score_adx(metrics.get("adx")), metrics.get("adx") is not None),
        (
            "breakout",
            _score_breakout_from_metrics(metrics, close),
            _has_breakout_data(metrics),
        ),
        (
            "sector_strength",
            score_sector(metrics.get("sector_rank"), int(metrics.get("total_sectors") or 1)),
            metrics.get("sector_rank") is not None,
        ),
        (
            "news",
            score_news(metrics.get("news_score"), metrics.get("news_sentiment")),
            metrics.get("news_score") is not None or metrics.get("news_sentiment") is not None,
        ),
    ]

    components: dict[str, float] = {}
    active_weights: dict[str, int] = {}
    for key, sub_score, available in candidates:
        if available:
            components[key] = round(sub_score, 1)
            active_weights[key] = SCORE_WEIGHTS[key]

    if not active_weights:
        return {"score": 0.0, "components": {}, "weights": SCORE_WEIGHTS, "active_weights": {}}

    weight_sum = sum(active_weights.values())
    total = sum(components[k] * active_weights[k] for k in active_weights) / weight_sum
    return {
        "score": round(total, 1),
        "components": components,
        "weights": SCORE_WEIGHTS,
        "active_weights": active_weights,
    }


def _has_breakout_data(metrics: dict[str, Any]) -> bool:
    return (
        metrics.get("high_20d") is not None
        or metrics.get("breakout") is not None
        or metrics.get("dist_52w_high_pct") is not None
    )


def _score_breakout_from_metrics(metrics: dict[str, Any], close: float) -> float:
    if metrics.get("breakout") is True:
        return 100.0
    high_20d = metrics.get("high_20d")
    if high_20d and close:
        return score_breakout(close, float(high_20d))
    dist = metrics.get("dist_52w_high_pct")
    if dist is not None:
        return _clamp(100 - float(dist) * 2.5)
    return 40.0
