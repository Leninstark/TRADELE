"""Shared types for scanner rule configuration."""
from __future__ import annotations

from dataclasses import dataclass

from TRADELE.rules.conditions import Condition


@dataclass
class ScannerStrategy:
    id: str
    name: str
    style: str  # intraday | swing | positional
    description: str
    conditions: list[Condition]
    min_confidence: float = 0.55
    enabled: bool = True
