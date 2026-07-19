"""Evaluate composable rule conditions against indicator snapshots."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from TRADELE.rules.conditions import Condition, Operator


@dataclass
class RuleResult:
    symbol: str
    strategy_id: str
    strategy_name: str
    style: str
    confidence: float
    score: float
    matched: bool
    reasons: list[str] = field(default_factory=list)
    indicators: dict[str, Any] = field(default_factory=dict)
    direction: str = "long"


class RuleEngine:
    """Evaluate a list of conditions; confidence = weighted match ratio."""

    def evaluate(
        self,
        symbol: str,
        indicators: dict[str, Any],
        conditions: list[Condition],
        *,
        strategy_id: str = "custom",
        strategy_name: str = "Custom",
        style: str = "swing",
        min_confidence: float = 0.5,
    ) -> Optional[RuleResult]:
        if not conditions:
            return None

        total_weight = sum(c.weight for c in conditions)
        earned = 0.0
        reasons: list[str] = []

        for cond in conditions:
            ok, ctx = self._check(cond, indicators)
            if ok:
                earned += cond.weight
                reasons.append(cond.describe(ctx))

        confidence = round((earned / total_weight) * 100, 1) if total_weight else 0.0
        matched = confidence >= min_confidence * 100

        return RuleResult(
            symbol=symbol,
            strategy_id=strategy_id,
            strategy_name=strategy_name,
            style=style,
            confidence=confidence,
            score=earned,
            matched=matched,
            reasons=reasons,
            indicators={k: indicators.get(k) for k in self._relevant_keys(conditions)},
            direction="long",
        )

    def _relevant_keys(self, conditions: list[Condition]) -> set[str]:
        keys: set[str] = set()
        for c in conditions:
            keys.add(c.field)
            if c.ref_field:
                keys.add(c.ref_field)
        return keys

    def _check(self, cond: Condition, ind: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        left = ind.get(cond.field)
        right = ind.get(cond.ref_field) if cond.ref_field else cond.value
        ctx: dict[str, Any] = {
            "field": cond.field,
            "value": left,
            "ref": right,
            "symbol": ind.get("symbol", ""),
            "close": ind.get("close"),
        }

        if left is None:
            return False, ctx

        op = cond.operator
        if op == Operator.GT:
            ok = right is not None and left > right
        elif op == Operator.GTE:
            ok = right is not None and left >= right
        elif op == Operator.LT:
            ok = right is not None and left < right
        elif op == Operator.LTE:
            ok = right is not None and left <= right
        elif op == Operator.EQ:
            ok = right is not None and left == right
        elif op == Operator.BETWEEN:
            lo, hi = cond.value
            ok = lo <= left <= hi
            ctx["lo"], ctx["hi"] = lo, hi
        elif op == Operator.WITHIN_PCT:
            if right is None or right == 0:
                return False, ctx
            pct = abs(left - right) / abs(right) * 100
            ok = pct <= cond.value
            ctx["pct"] = round(pct, 2)
        elif op == Operator.CROSS_ABOVE:
            prev_left = ind.get(f"prev_{cond.field}")
            prev_right = ind.get(f"prev_{cond.ref_field}") if cond.ref_field else cond.value
            ok = (
                prev_left is not None
                and prev_right is not None
                and prev_left <= prev_right
                and left > right
            )
        elif op == Operator.CROSS_BELOW:
            prev_left = ind.get(f"prev_{cond.field}")
            prev_right = ind.get(f"prev_{cond.ref_field}") if cond.ref_field else cond.value
            ok = (
                prev_left is not None
                and prev_right is not None
                and prev_left >= prev_right
                and left < right
            )
        else:
            ok = False

        return ok, ctx
