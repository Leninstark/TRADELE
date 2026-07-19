"""Market data overview for dashboard."""
from __future__ import annotations

import logging
from typing import Any, Optional

from TRADELE.services.zerodha_client import ZerodhaClient, get_client

logger = logging.getLogger(__name__)

INDEX_SYMBOLS = {
    "NIFTY": "NSE:NIFTY 50",
    "BANKNIFTY": "NSE:NIFTY BANK",
    "FINNIFTY": "NSE:NIFTY FIN SERVICE",
    "MIDCAP": "NSE:NIFTY MIDCAP 100",
    "SENSEX": "BSE:SENSEX",
}


def _quote_direction(change_pct: float) -> str:
    if change_pct > 0.3:
        return "Bullish"
    if change_pct < -0.3:
        return "Bearish"
    return "Neutral"


def get_market_overview(client: Optional[ZerodhaClient] = None) -> dict[str, Any]:
    """Fetch index quotes and market context for dashboard."""
    client = client or get_client()
    indices: list[dict[str, Any]] = []

    try:
        instruments = list(INDEX_SYMBOLS.values())
        quotes = client.get_quote(instruments)
        for name, key in INDEX_SYMBOLS.items():
            q = quotes.get(key, {})
            ohlc = q.get("ohlc", {})
            last = q.get("last_price") or ohlc.get("close", 0)
            prev = ohlc.get("close", last)
            change_pct = round((last - prev) / prev * 100, 2) if prev else 0.0
            indices.append({
                "name": name,
                "last": last,
                "change_pct": change_pct,
                "direction": _quote_direction(change_pct),
                "confidence": min(95, 50 + abs(change_pct) * 10),
            })
    except Exception as e:
        logger.warning("Market overview fetch failed: %s", e)
        indices = [
            {"name": "NIFTY", "last": None, "change_pct": 0, "direction": "Neutral", "confidence": 50},
            {"name": "BANKNIFTY", "last": None, "change_pct": 0, "direction": "Neutral", "confidence": 50},
        ]

    return {
        "indices": indices,
        "india_vix": {"value": None, "level": "Unknown"},
        "pcr": {"value": None, "signal": "Neutral"},
        "market_breadth": {"advance": None, "decline": None, "unchanged": None, "adr_ratio": None},
        "fii_dii": {"fii_net": None, "dii_net": None},
    }
