"""JARVIS session memory — JSONL event store for RL / self-correction / deep analysis."""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[3] / "data" / "jarvis" / "sessions"
_lock = threading.Lock()
_session_id: Optional[str] = None
_session_meta: dict[str, Any] = {}


def _ensure_dir() -> Path:
    _ROOT.mkdir(parents=True, exist_ok=True)
    return _ROOT


def _path(sid: str) -> Path:
    return _ensure_dir() / f"{sid}.jsonl"


def current_session_id() -> Optional[str]:
    return _session_id


def start_session(*, lane: str = "time", source: str = "lab", meta: Optional[dict[str, Any]] = None) -> str:
    global _session_id, _session_meta
    sid = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    _session_id = sid
    _session_meta = {
        "session_id": sid,
        "lane": lane,
        "source": source,
        "started_at": time.time(),
        **(meta or {}),
    }
    append_event("session.start", dict(_session_meta))
    return sid


def end_session(*, summary: Optional[dict[str, Any]] = None) -> Optional[str]:
    global _session_id
    sid = _session_id
    if not sid:
        return None
    append_event(
        "session.end",
        {
            "session_id": sid,
            "ended_at": time.time(),
            "summary": summary or {},
        },
    )
    _session_id = None
    return sid


def append_event(kind: str, payload: Optional[dict[str, Any]] = None) -> None:
    """Append one RL/analysis event. Safe to call from any thread."""
    sid = _session_id
    if not sid:
        # Auto-open a catch-all session so nothing is lost
        sid = start_session(lane="auto", source="auto")
    row = {
        "at": time.time(),
        "session_id": sid,
        "kind": kind,
        "payload": payload or {},
    }
    try:
        with _lock:
            with _path(sid).open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, default=str) + "\n")
    except Exception as e:
        logger.debug("jarvis memory append: %s", e)


def list_sessions(limit: int = 40) -> list[dict[str, Any]]:
    _ensure_dir()
    files = sorted(_ROOT.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    out: list[dict[str, Any]] = []
    for p in files[:limit]:
        meta: dict[str, Any] = {"session_id": p.stem, "path": str(p), "bytes": p.stat().st_size}
        try:
            with p.open(encoding="utf-8") as f:
                first = f.readline()
                if first:
                    row = json.loads(first)
                    if row.get("kind") == "session.start":
                        meta.update(row.get("payload") or {})
        except Exception:
            pass
        out.append(meta)
    return out


def read_session(session_id: str, limit: int = 2000) -> dict[str, Any]:
    p = _path(session_id)
    if not p.exists():
        return {"ok": False, "error": "session not found", "events": []}
    events: list[dict[str, Any]] = []
    with p.open(encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i >= limit:
                break
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return {
        "ok": True,
        "session_id": session_id,
        "events": events,
        "count": len(events),
        "active": session_id == _session_id,
    }
