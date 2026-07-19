"""Admin API — configure scanner rules stored in data/scanner_rules.json."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from TRADELE.rules.config_store import get_rules_path, get_schema, load_config_dict, reset_to_builtin
from TRADELE.rules.registry import reload_strategies, update_strategies_from_config

router = APIRouter()


class RulesConfigPayload(BaseModel):
    version: int = 1
    strategies: list[dict[str, Any]] = Field(..., min_length=1)


@router.get("/rules/schema")
def rules_schema():
    """Operators, indicator fields, and styles for the admin UI."""
    return get_schema()


@router.get("/rules")
def get_rules():
    """Return full scanner rules config from JSON."""
    config = load_config_dict()
    return {
        **config,
        "file_path": str(get_rules_path()),
    }


@router.put("/rules")
def save_rules(payload: RulesConfigPayload):
    """Validate and save scanner rules to JSON; reload in-memory registry."""
    try:
        data = payload.model_dump()
        strategies = update_strategies_from_config(data)
        return {
            "status": "saved",
            "strategy_count": len(strategies),
            "file_path": str(get_rules_path()),
            "config": load_config_dict(),
        }
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/rules/reset")
def reset_rules():
    """Reset scanner rules to built-in defaults and save to JSON."""
    strategies = reset_to_builtin()
    reload_strategies()
    return {
        "status": "reset",
        "strategy_count": len(strategies),
        "file_path": str(get_rules_path()),
        "config": load_config_dict(),
    }
