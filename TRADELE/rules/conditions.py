"""Reusable condition definitions for the rule engine."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class Operator(str, Enum):
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    EQ = "eq"
    BETWEEN = "between"
    CROSS_ABOVE = "cross_above"
    CROSS_BELOW = "cross_below"
    WITHIN_PCT = "within_pct"


@dataclass
class Condition:
    """A single evaluable condition against indicator snapshots."""

    id: str
    label: str
    field: str
    operator: Operator
    value: Any = None
    ref_field: Optional[str] = None
    weight: float = 1.0
    reason_template: str = ""
    tags: list[str] = field(default_factory=list)

    def describe(self, ctx: dict[str, Any]) -> str:
        if self.reason_template:
            try:
                return self.reason_template.format(**ctx)
            except (KeyError, ValueError):
                return self.label
        return self.label
