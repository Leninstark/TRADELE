"""Unified scanner runner across trading styles."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy.orm import Session

from TRADELE.engines.indicators.calculator import IndicatorCalculator
from TRADELE.rules.engine import RuleEngine, RuleResult
from TRADELE.rules.registry import all_strategies, get_strategy, strategies_by_style
from TRADELE.rules.registry_types import ScannerStrategy
from TRADELE.services.data_fetcher import apply_liquidity_filters, fetch_eod_batch
from TRADELE.services.zerodha_client import KiteRateLimitError, ZerodhaClient, get_client

logger = logging.getLogger(__name__)


@dataclass
class ScanMatch:
    symbol: str
    strategy_id: str
    strategy_name: str
    style: str
    confidence: float
    rating: str
    reasons: list[str] = field(default_factory=list)
    indicators: dict[str, Any] = field(default_factory=dict)
    close: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "strategy_id": self.strategy_id,
            "strategy_name": self.strategy_name,
            "style": self.style,
            "confidence": self.confidence,
            "rating": self.rating,
            "reasons": self.reasons,
            "close": self.close,
            "indicators": self.indicators,
        }


def _confidence_to_rating(confidence: float) -> str:
    if confidence >= 90:
        return "Strong Buy"
    if confidence >= 75:
        return "Buy"
    if confidence >= 60:
        return "Watch"
    return "Neutral"


def run_scan(
    symbol_data: dict[str, list[dict]],
    strategy: ScannerStrategy,
    *,
    top_n: int = 20,
) -> list[ScanMatch]:
    engine = RuleEngine()
    calc = IndicatorCalculator()
    matches: list[ScanMatch] = []

    for symbol, candles in symbol_data.items():
        indicators = calc.compute(symbol, candles)
        if not indicators:
            continue

        result = engine.evaluate(
            symbol,
            indicators,
            strategy.conditions,
            strategy_id=strategy.id,
            strategy_name=strategy.name,
            style=strategy.style,
            min_confidence=strategy.min_confidence,
        )
        if result and result.matched:
            matches.append(_to_match(result, indicators))

    matches.sort(key=lambda m: m.confidence, reverse=True)
    return matches[:top_n]


def run_all_scanners(
    symbol_data: dict[str, list[dict]],
    style: Optional[str] = None,
    *,
    top_n_per_strategy: int = 10,
) -> dict[str, list[ScanMatch]]:
    strategies = strategies_by_style(style) if style else all_strategies()
    out: dict[str, list[ScanMatch]] = {}
    for strategy in strategies:
        results = run_scan(symbol_data, strategy, top_n=top_n_per_strategy)
        if results:
            out[strategy.id] = results
    return out


def run_live_scan(
    db: Session,
    *,
    style: Optional[str] = None,
    symbols: Optional[list[str]] = None,
    top_n_per_strategy: int = 10,
) -> dict[str, Any]:
    """Fetch data and run scanners — main entry for API."""
    client = get_client()
    try:
        symbol_data = fetch_eod_batch(client, db, symbols=symbols)
    except KiteRateLimitError:
        return {
            "style": style or "all",
            "symbol_count": 0,
            "strategies": {},
            "top_picks": [],
            "counts": {},
            "error": "rate_limit",
            "message": "Too many requests",
        }

    symbol_data = apply_liquidity_filters(symbol_data)

    by_strategy = run_all_scanners(symbol_data, style=style, top_n_per_strategy=top_n_per_strategy)

    flat: list[ScanMatch] = []
    for results in by_strategy.values():
        flat.extend(results)
    flat.sort(key=lambda m: m.confidence, reverse=True)

    return {
        "style": style or "all",
        "symbol_count": len(symbol_data),
        "strategies": {k: [m.to_dict() for m in v] for k, v in by_strategy.items()},
        "top_picks": [m.to_dict() for m in flat[:20]],
        "counts": {k: len(v) for k, v in by_strategy.items()},
    }


def _to_match(result: RuleResult, indicators: dict[str, Any]) -> ScanMatch:
    return ScanMatch(
        symbol=result.symbol,
        strategy_id=result.strategy_id,
        strategy_name=result.strategy_name,
        style=result.style,
        confidence=result.confidence,
        rating=_confidence_to_rating(result.confidence),
        reasons=result.reasons,
        indicators=result.indicators,
        close=indicators.get("close"),
    )
