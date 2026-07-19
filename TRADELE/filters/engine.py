"""Apply filter conditions to stock metric rows."""
from __future__ import annotations

from typing import Any

from TRADELE.filters.definitions import FilterCondition, StockFilter


def _compare(field: str, operator: str, threshold: float | bool, row: dict[str, Any]) -> bool:
    if operator == "exclude":
        if field == "circuit_stocks":
            return not row.get("is_circuit", False)
        return True

    actual = row.get(field)
    if actual is None:
        return False

    if not isinstance(threshold, (int, float)):
        return bool(actual) == bool(threshold)

    if operator == ">":
        return float(actual) > float(threshold)
    if operator == ">=":
        return float(actual) >= float(threshold)
    if operator == "<":
        return float(actual) < float(threshold)
    if operator == "<=":
        return float(actual) <= float(threshold)
    if operator == "==":
        return float(actual) == float(threshold)
    return False


def passes_condition(row: dict[str, Any], condition: FilterCondition) -> bool:
    return _compare(condition.field, condition.operator, condition.value, row)


def apply_filter(row: dict[str, Any], stock_filter: StockFilter) -> bool:
    return all(passes_condition(row, c) for c in stock_filter.conditions)
