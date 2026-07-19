"""Load and persist scanner rules to JSON."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from TRADELE.rules.conditions import Condition, Operator
from TRADELE.rules.registry_types import ScannerStrategy

logger = logging.getLogger(__name__)

RULES_VERSION = 1
VALID_STYLES = frozenset({"intraday", "swing", "positional"})

INDICATOR_FIELDS = [
    "close", "open", "high", "low", "volume",
    "change_pct", "gap_pct",
    "ema_5", "ema_9", "ema_20", "ema_50", "ema_100", "ema_200",
    "sma_20", "sma_50", "sma_200",
    "rsi", "macd", "macd_signal", "macd_hist",
    "adx", "atr", "vwap",
    "bb_upper", "bb_middle", "bb_lower",
    "supertrend", "obv", "cmf", "cci", "stoch_rsi",
    "high_20d", "low_20d", "high_52w", "low_52w",
    "volume_ratio", "is_nr7",
    "dist_ema_20_pct", "dist_ema_50_pct", "dist_ema_200_pct",
]

OPERATOR_LABELS = {
    Operator.GT: "Greater than",
    Operator.GTE: "Greater or equal",
    Operator.LT: "Less than",
    Operator.LTE: "Less or equal",
    Operator.EQ: "Equals",
    Operator.BETWEEN: "Between (range)",
    Operator.CROSS_ABOVE: "Crossed above",
    Operator.CROSS_BELOW: "Crossed below",
    Operator.WITHIN_PCT: "Within % of reference",
}


def get_rules_path() -> Path:
    root = Path(__file__).resolve().parents[2]
    return root / "data" / "scanner_rules.json"


def get_schema() -> dict[str, Any]:
    return {
        "version": RULES_VERSION,
        "styles": sorted(VALID_STYLES),
        "operators": [
            {"value": op.value, "label": OPERATOR_LABELS[op]}
            for op in Operator
        ],
        "fields": INDICATOR_FIELDS,
        "ref_operators": [
            Operator.GT.value, Operator.GTE.value, Operator.LT.value,
            Operator.LTE.value, Operator.CROSS_ABOVE.value,
            Operator.CROSS_BELOW.value, Operator.WITHIN_PCT.value,
        ],
        "value_operators": [
            Operator.GT.value, Operator.GTE.value, Operator.LT.value,
            Operator.LTE.value, Operator.EQ.value, Operator.BETWEEN.value,
            Operator.WITHIN_PCT.value,
        ],
    }


def strategy_to_dict(strategy: ScannerStrategy) -> dict[str, Any]:
    return {
        "id": strategy.id,
        "name": strategy.name,
        "style": strategy.style,
        "description": strategy.description,
        "min_confidence": strategy.min_confidence,
        "enabled": strategy.enabled,
        "conditions": [condition_to_dict(c) for c in strategy.conditions],
    }


def condition_to_dict(cond: Condition) -> dict[str, Any]:
    value = cond.value
    if isinstance(value, tuple):
        value = list(value)
    return {
        "id": cond.id,
        "label": cond.label,
        "field": cond.field,
        "operator": cond.operator.value if isinstance(cond.operator, Operator) else cond.operator,
        "value": value,
        "ref_field": cond.ref_field,
        "weight": cond.weight,
        "reason_template": cond.reason_template,
    }


def config_to_dict(strategies: list[ScannerStrategy]) -> dict[str, Any]:
    return {
        "version": RULES_VERSION,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "strategies": [strategy_to_dict(s) for s in strategies],
    }


def condition_from_dict(data: dict[str, Any]) -> Condition:
    op = data.get("operator", "gt")
    if isinstance(op, str):
        op = Operator(op)
    value = data.get("value")
    if isinstance(value, list) and len(value) == 2:
        value = tuple(value)
    return Condition(
        id=data["id"],
        label=data.get("label", data["id"]),
        field=data["field"],
        operator=op,
        value=value,
        ref_field=data.get("ref_field"),
        weight=float(data.get("weight", 1.0)),
        reason_template=data.get("reason_template", ""),
    )


def strategy_from_dict(data: dict[str, Any]) -> ScannerStrategy:
    return ScannerStrategy(
        id=data["id"],
        name=data["name"],
        style=data["style"],
        description=data.get("description", ""),
        min_confidence=float(data.get("min_confidence", 0.55)),
        enabled=bool(data.get("enabled", True)),
        conditions=[condition_from_dict(c) for c in data.get("conditions", [])],
    )


def validate_config(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    strategies = data.get("strategies")
    if not isinstance(strategies, list):
        return ["strategies must be a list"]
    if not strategies:
        return ["at least one strategy is required"]

    seen_ids: set[str] = set()
    for i, raw in enumerate(strategies):
        prefix = f"strategies[{i}]"
        if not isinstance(raw, dict):
            errors.append(f"{prefix} must be an object")
            continue
        sid = raw.get("id", "")
        if not sid or not isinstance(sid, str):
            errors.append(f"{prefix}.id is required")
        elif sid in seen_ids:
            errors.append(f"duplicate strategy id: {sid}")
        else:
            seen_ids.add(sid)
        if raw.get("style") not in VALID_STYLES:
            errors.append(f"{prefix}.style must be one of {sorted(VALID_STYLES)}")
        if not raw.get("name"):
            errors.append(f"{prefix}.name is required")
        conditions = raw.get("conditions", [])
        if not conditions:
            errors.append(f"{prefix} must have at least one condition")
        cond_ids: set[str] = set()
        for j, cond in enumerate(conditions):
            cp = f"{prefix}.conditions[{j}]"
            if not isinstance(cond, dict):
                errors.append(f"{cp} must be an object")
                continue
            cid = cond.get("id", "")
            if not cid:
                errors.append(f"{cp}.id is required")
            elif cid in cond_ids:
                errors.append(f"{prefix}: duplicate condition id {cid}")
            else:
                cond_ids.add(cid)
            if not cond.get("field"):
                errors.append(f"{cp}.field is required")
            try:
                Operator(cond.get("operator", ""))
            except ValueError:
                errors.append(f"{cp}.operator is invalid")
    return errors


def load_strategies(*, seed_if_missing: bool = True) -> list[ScannerStrategy]:
    path = get_rules_path()
    if not path.exists():
        if not seed_if_missing:
            from TRADELE.rules.builtin_strategies import get_builtin_strategies
            return get_builtin_strategies()
        from TRADELE.rules.builtin_strategies import get_builtin_strategies
        strategies = get_builtin_strategies()
        save_strategies(strategies)
        logger.info("Seeded scanner rules at %s", path)
        return strategies

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        errors = validate_config(raw)
        if errors:
            raise ValueError("; ".join(errors))
        return [strategy_from_dict(s) for s in raw["strategies"]]
    except Exception as e:
        logger.exception("Failed to load scanner rules from %s: %s", path, e)
        from TRADELE.rules.builtin_strategies import get_builtin_strategies
        return get_builtin_strategies()


def load_config_dict() -> dict[str, Any]:
    path = get_rules_path()
    if not path.exists():
        strategies = load_strategies()
        return config_to_dict(strategies)
    return json.loads(path.read_text(encoding="utf-8"))


def save_config_dict(data: dict[str, Any]) -> list[ScannerStrategy]:
    errors = validate_config(data)
    if errors:
        raise ValueError("; ".join(errors))
    strategies = [strategy_from_dict(s) for s in data["strategies"]]
    save_strategies(strategies)
    return strategies


def save_strategies(strategies: list[ScannerStrategy]) -> Path:
    path = get_rules_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = config_to_dict(strategies)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    logger.info("Saved %d scanner strategies to %s", len(strategies), path)
    return path


def reset_to_builtin() -> list[ScannerStrategy]:
    from TRADELE.rules.builtin_strategies import get_builtin_strategies
    strategies = get_builtin_strategies()
    save_strategies(strategies)
    return strategies
