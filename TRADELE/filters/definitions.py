"""Stock filter definitions used by Explore scanners."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Operator = Literal[">", "<", ">=", "<=", "==", "exclude"]


@dataclass(frozen=True)
class FilterCondition:
    field: str
    operator: Operator
    value: float | bool
    label: str
    unit: str = ""


@dataclass(frozen=True)
class StockFilter:
    id: str
    name: str
    description: str
    conditions: tuple[FilterCondition, ...]


FILTER_PHASE_1 = StockFilter(
    id="phase_1",
    name="Phase 1",
    description="Mid cap & Small cap universe with price, market cap, volume, delivery, and circuit filters",
    conditions=(
        FilterCondition("price", ">", 100, "Price", "₹"),
        FilterCondition("market_cap_cr", ">", 3000, "Market Cap", "₹ Cr"),
        FilterCondition("avg_daily_volume", ">", 500_000, "Avg Daily Volume", "shares"),
        FilterCondition("delivery_pct", ">", 35, "Delivery %", "%"),
        FilterCondition("circuit_stocks", "exclude", True, "Circuit Stocks", ""),
    ),
)

_FILTERS: dict[str, StockFilter] = {
    FILTER_PHASE_1.id: FILTER_PHASE_1,
}


def get_filter(filter_id: str) -> StockFilter | None:
    return _FILTERS.get(filter_id)


def filter_to_dict(f: StockFilter) -> dict[str, Any]:
    return {
        "id": f.id,
        "name": f.name,
        "description": f.description,
        "conditions": [
            {
                "field": c.field,
                "operator": c.operator,
                "value": c.value,
                "label": c.label,
                "unit": c.unit,
            }
            for c in f.conditions
        ],
    }
