"""In-memory realtime event bus for JARVIS desk + webhooks."""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Callable, Optional

_lock = threading.Lock()
_events: deque[dict[str, Any]] = deque(maxlen=500)
_listeners: list[Callable[[dict[str, Any]], None]] = []
_seq = 0

# Latest snapshot for UI bootstrap
_state: dict[str, Any] = {
    "mode": "SCAN_ONLY",
    "day_pnl": 0.0,
    "unrealized_pnl": 0.0,
    "groww": {"connected": False, "positions": [], "orders": [], "updated_at": None},
    "last_run": None,
    "candidates": {"longs": [], "shorts": []},
    "observe": {},
    "tape": [],
    "config": {},
}


def publish(event_type: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    global _seq
    with _lock:
        _seq += 1
        evt = {
            "seq": _seq,
            "type": event_type,
            "at": time.time(),
            "payload": payload or {},
        }
        _events.appendleft(evt)
        listeners = list(_listeners)
        if event_type == "jarvis.state":
            _state.update(payload or {})
        elif event_type == "jarvis.candidates":
            _state["candidates"] = payload or {"longs": [], "shorts": []}
        elif event_type == "jarvis.groww":
            _state["groww"] = payload or _state.get("groww") or {}
        elif event_type == "jarvis.tape":
            tape = list(_state.get("tape") or [])
            tape.insert(0, payload or {})
            _state["tape"] = tape[:80]
        elif event_type == "jarvis.pnl":
            if payload:
                if "day_pnl" in payload:
                    _state["day_pnl"] = payload["day_pnl"]
                if "unrealized_pnl" in payload:
                    _state["unrealized_pnl"] = payload["unrealized_pnl"]
        elif event_type == "jarvis.mode":
            if payload and "mode" in payload:
                _state["mode"] = payload["mode"]
        elif event_type == "jarvis.config":
            if payload:
                _state["config"] = payload
        elif event_type == "jarvis.think":
            _state["think"] = payload
        elif event_type == "jarvis.run":
            _state["last_run"] = payload
        elif event_type == "jarvis.observe":
            _state["observe"] = payload or {}
    for fn in listeners:
        try:
            fn(evt)
        except Exception:
            pass
    return evt


def subscribe(fn: Callable[[dict[str, Any]], None]) -> Callable[[], None]:
    with _lock:
        _listeners.append(fn)

    def _unsub() -> None:
        with _lock:
            if fn in _listeners:
                _listeners.remove(fn)

    return _unsub


def recent(limit: int = 50, after_seq: int = 0) -> list[dict[str, Any]]:
    with _lock:
        items = [e for e in list(_events) if int(e.get("seq") or 0) > after_seq]
    return items[:limit]


def snapshot() -> dict[str, Any]:
    with _lock:
        return dict(_state)
