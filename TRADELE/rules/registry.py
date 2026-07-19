"""Scanner strategy registry — loads from data/scanner_rules.json."""
from __future__ import annotations

from TRADELE.rules.config_store import load_strategies, save_config_dict
from TRADELE.rules.registry_types import ScannerStrategy

SCANNER_STRATEGIES: list[ScannerStrategy] = load_strategies()


def reload_strategies() -> list[ScannerStrategy]:
    """Reload strategies from JSON file into memory."""
    global SCANNER_STRATEGIES
    SCANNER_STRATEGIES = load_strategies(seed_if_missing=False)
    return SCANNER_STRATEGIES


def update_strategies_from_config(data: dict) -> list[ScannerStrategy]:
    """Validate, save config, and reload in-memory strategies."""
    global SCANNER_STRATEGIES
    SCANNER_STRATEGIES = save_config_dict(data)
    return SCANNER_STRATEGIES


def get_strategy(strategy_id: str) -> ScannerStrategy | None:
    for s in SCANNER_STRATEGIES:
        if s.id == strategy_id:
            return s
    return None


def strategies_by_style(style: str, *, include_disabled: bool = False) -> list[ScannerStrategy]:
    strategies = SCANNER_STRATEGIES
    if not include_disabled:
        strategies = [s for s in strategies if s.enabled]
    return [s for s in strategies if s.style == style]


def all_strategies(*, include_disabled: bool = False) -> list[ScannerStrategy]:
    if include_disabled:
        return list(SCANNER_STRATEGIES)
    return [s for s in SCANNER_STRATEGIES if s.enabled]
