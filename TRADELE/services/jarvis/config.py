"""JARVIS default settings — agent must abide by these."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

DEFAULT_CONFIG: dict[str, Any] = {
    "mode": "SCAN_ONLY",
    "claude_role": "veto_and_explain",
    "avoid_large_cap": True,
    "large_cap_only": False,
    "prefer_mid_small": True,
    "min_price": 50.0,
    "max_price": 5000.0,
    "min_avg_volume": 200_000,
    "max_spread_bps": 20,
    "min_atr_pct": 0.8,
    "max_atr_pct": 8.0,
    "exclude_gsm_asm": True,
    "allow_short": True,
    "max_candidates_scan": 400,
    "top_n_long": 5,
    "top_n_short": 5,
    "min_score_to_trade": 70,
    "sl_mode": "hybrid",
    "tp_mode": "r_multiple",
    "atr_length": 14,
    "sl_atr_mult": 1.2,
    "tp_atr_mult": 2.4,
    "sl_pct": 0.8,
    "tp_pct": 1.6,
    "target_r_multiple": 2.0,
    "min_r_multiple": 1.5,
    "max_sl_pct_hard": 1.5,
    "min_sl_pct_hard": 0.35,
    "trail_enabled": True,
    "trail_activate_r": 1.0,
    "move_to_be_at_r": 1.0,
    "risk_per_trade_pct": 0.75,
    "max_concurrent_positions": 3,
    "max_daily_loss_rupees": 5000,
    "max_trades_per_day": 8,
    "session_start": "09:20",
    "session_end_entries": "14:45",
    "force_square_off": "15:15",
    "orb_minutes": 15,
    "enable_j_a": True,
    "enable_j_b": True,
    "enable_j_c": True,
    "enable_j_d": True,
    "require_index_align": True,
    "webhook_secret": "",
    "observe_lane": "time",  # time = Lane A · mind = Lane B
}

# Compact Nifty-50 style large-cap set for filter toggles
LARGE_CAP = frozenset(
    {
        "RELIANCE",
        "TCS",
        "HDFCBANK",
        "ICICIBANK",
        "INFY",
        "ITC",
        "SBIN",
        "BHARTIARTL",
        "HINDUNILVR",
        "LT",
        "KOTAKBANK",
        "AXISBANK",
        "BAJFINANCE",
        "ASIANPAINT",
        "MARUTI",
        "SUNPHARMA",
        "TITAN",
        "ULTRACEMCO",
        "NTPC",
        "POWERGRID",
        "NESTLEIND",
        "TATAMOTORS",
        "M&M",
        "WIPRO",
        "HCLTECH",
        "ADANIENT",
        "ADANIPORTS",
        "ONGC",
        "COALINDIA",
        "JSWSTEEL",
        "TATASTEEL",
        "TECHM",
        "BAJAJFINSV",
        "HDFCLIFE",
        "SBILIFE",
        "GRASIM",
        "CIPLA",
        "DRREDDY",
        "BPCL",
        "INDUSINDBK",
        "EICHERMOT",
        "APOLLOHOSP",
        "HEROMOTOCO",
        "DIVISLAB",
        "BRITANNIA",
        "TATACONSUM",
        "BAJAJ-AUTO",
        "HINDALCO",
        "LTIM",
        "BEL",
    }
)

_config: dict[str, Any] = deepcopy(DEFAULT_CONFIG)


def get_config() -> dict[str, Any]:
    return deepcopy(_config)


def update_config(patch: dict[str, Any]) -> dict[str, Any]:
    global _config
    clean = {k: v for k, v in (patch or {}).items() if k in DEFAULT_CONFIG}
    _config = {**_config, **clean}
    return get_config()


def reset_config() -> dict[str, Any]:
    global _config
    _config = deepcopy(DEFAULT_CONFIG)
    return get_config()
