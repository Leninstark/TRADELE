"""Groww live snapshot for JARVIS — poll + publish to bus."""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from sqlalchemy.orm import Session

from TRADELE.services.groww_client import get_positions, list_all_orders
from TRADELE.services.groww_token_store import get_active_access_token, try_refresh_token
from TRADELE.services.jarvis import bus
from TRADELE.services.mytrade_analytics import filter_positions_for_style

logger = logging.getLogger(__name__)


def _flatten_positions(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        if payload.get("status") == "SUCCESS" and "payload" in payload:
            payload = payload["payload"]
        for key in ("positions", "position_list", "data"):
            if isinstance(payload.get(key), list):
                return [p for p in payload[key] if isinstance(p, dict)]
        # nested product books
        out: list[dict[str, Any]] = []
        for v in payload.values():
            if isinstance(v, list):
                out.extend(x for x in v if isinstance(x, dict))
            elif isinstance(v, dict):
                out.extend(_flatten_positions(v))
        return out
    if isinstance(payload, list):
        return [p for p in payload if isinstance(p, dict)]
    return []


def fetch_groww_live(db: Session, username: str) -> dict[str, Any]:
    token = get_active_access_token(db, username)
    if not token:
        try:
            token = try_refresh_token(db, username)
        except Exception as e:
            logger.info("JARVIS Groww refresh failed: %s", e)
            token = None
    if not token:
        snap = {
            "connected": False,
            "positions": [],
            "orders": [],
            "updated_at": time.time(),
            "error": "Groww not connected",
        }
        bus.publish("jarvis.groww", snap)
        return snap

    try:
        raw_pos = get_positions(token)
        positions = filter_positions_for_style(_flatten_positions(raw_pos), "intraday")
        orders = list_all_orders(token, segment="CASH")
        day_pnl = 0.0
        unreal = 0.0
        for p in positions:
            try:
                day_pnl += float(p.get("realised_pnl") or p.get("realized_pnl") or 0)
            except (TypeError, ValueError):
                pass
            try:
                unreal += float(p.get("unrealised_pnl") or p.get("unrealized_pnl") or 0)
            except (TypeError, ValueError):
                pass
        snap = {
            "connected": True,
            "positions": positions[:50],
            "orders": orders[:80],
            "updated_at": time.time(),
            "position_count": len(positions),
            "order_count": len(orders),
        }
        bus.publish("jarvis.groww", snap)
        bus.publish("jarvis.pnl", {"day_pnl": day_pnl, "unrealized_pnl": unreal})
        bus.publish(
            "jarvis.tape",
            {
                "kind": "groww_sync",
                "message": f"Groww live · {len(positions)} MIS pos · {len(orders)} orders",
                "day_pnl": day_pnl,
                "unrealized_pnl": unreal,
            },
        )
        return {**snap, "day_pnl": day_pnl, "unrealized_pnl": unreal}
    except Exception as e:
        logger.warning("JARVIS Groww live fetch failed: %s", e)
        snap = {
            "connected": False,
            "positions": [],
            "orders": [],
            "updated_at": time.time(),
            "error": str(e),
        }
        bus.publish("jarvis.groww", snap)
        return snap
