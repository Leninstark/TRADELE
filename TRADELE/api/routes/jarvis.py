"""JARVIS Infinity API — config, run agent, Groww webhooks, realtime WS."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import time
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from TRADELE.db.session import SessionLocal, get_db
from TRADELE.engines.agents.jarvis_agent import run_jarvis_agent
from TRADELE.services.jarvis import bus
from TRADELE.services.jarvis.config import get_config, reset_config, update_config
from TRADELE.services.jarvis.groww_live import fetch_groww_live

logger = logging.getLogger(__name__)
router = APIRouter()

INFINITY_USER = "leninstark"


def _require_infinity_user(username: str) -> str:
    u = (username or "").strip().lower()
    if u != INFINITY_USER:
        raise HTTPException(403, "INFINITY / JARVIS is restricted to leninstark")
    return u


class ConfigPatch(BaseModel):
    patch: dict[str, Any] = Field(default_factory=dict)


@router.get("/status")
def jarvis_status(username: str = Query("leninstark")):
    _require_infinity_user(username)
    snap = bus.snapshot()
    return {
        "ok": True,
        "agent": "jarvis",
        "username": username,
        "snapshot": snap,
        "config": get_config(),
    }


@router.get("/config")
def jarvis_get_config(username: str = Query("leninstark")):
    _require_infinity_user(username)
    return {"ok": True, "config": get_config()}


@router.put("/config")
def jarvis_put_config(body: ConfigPatch, username: str = Query("leninstark")):
    _require_infinity_user(username)
    cfg = update_config(body.patch or {})
    bus.publish("jarvis.config", cfg)
    bus.publish("jarvis.mode", {"mode": cfg.get("mode")})
    bus.publish("jarvis.tape", {"kind": "settings", "message": "Config updated — JARVIS will abide"})
    return {"ok": True, "config": cfg}


@router.post("/config/reset")
def jarvis_reset_config(username: str = Query("leninstark")):
    _require_infinity_user(username)
    cfg = reset_config()
    bus.publish("jarvis.config", cfg)
    return {"ok": True, "config": cfg}


@router.post("/run")
def jarvis_run(username: str = Query("leninstark")):
    _require_infinity_user(username)
    t0 = time.time()
    result = run_jarvis_agent(username=username)
    result["elapsed_ms"] = int((time.time() - t0) * 1000)
    return {"ok": True, **result}


@router.post("/groww/refresh")
def jarvis_groww_refresh(username: str = Query("leninstark"), db: Session = Depends(get_db)):
    _require_infinity_user(username)
    snap = fetch_groww_live(db, username)
    return {"ok": True, "groww": snap}


@router.post("/webhook/groww")
async def jarvis_groww_webhook(
    request: Request,
    username: str = Query("leninstark"),
    x_jarvis_signature: Optional[str] = Header(None, alias="X-Jarvis-Signature"),
):
    """
    Inbound Groww / worker webhook. Verifies optional HMAC with config.webhook_secret.
    Body is forwarded onto the realtime bus for UI.
    """
    _require_infinity_user(username)
    raw = await request.body()
    secret = (get_config().get("webhook_secret") or "").strip()
    if secret:
        sig = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        if not x_jarvis_signature or not hmac.compare_digest(sig, x_jarvis_signature.strip()):
            raise HTTPException(401, "Invalid webhook signature")
    try:
        payload = await request.json()
    except Exception:
        payload = {"raw": raw.decode("utf-8", errors="replace")}
    bus.publish("jarvis.webhook", {"source": "groww", "data": payload})
    bus.publish(
        "jarvis.tape",
        {"kind": "webhook", "message": "Groww webhook received", "keys": list(payload)[:8] if isinstance(payload, dict) else []},
    )
    # Best-effort refresh
    db = SessionLocal()
    try:
        fetch_groww_live(db, username)
    except Exception as e:
        logger.info("webhook groww refresh: %s", e)
    finally:
        db.close()
    return {"ok": True}


@router.get("/events")
def jarvis_events(username: str = Query("leninstark"), after_seq: int = Query(0), limit: int = Query(40)):
    _require_infinity_user(username)
    return {"ok": True, "events": bus.recent(limit=limit, after_seq=after_seq)}


def _ws_tick(username: str) -> dict[str, Any]:
    from TRADELE.services.jarvis.sim import sim_state

    sim = sim_state()
    if not sim.get("active"):
        db = SessionLocal()
        try:
            fetch_groww_live(db, username)
        except Exception as e:
            logger.debug("jarvis ws groww tick: %s", e)
        finally:
            db.close()
    return {
        "type": "jarvis.tick",
        "at": time.time(),
        "snapshot": bus.snapshot(),
        "events": bus.recent(limit=25),
        "sim": {"active": bool(sim.get("active")), "scenario": sim.get("scenario")},
    }


class TestArmBody(BaseModel):
    mode: str = "PAPER"


class TestMarkBody(BaseModel):
    symbol: str
    ltp: float


class TestSideBody(BaseModel):
    side: str = "LONG"


class TestSymbolBody(BaseModel):
    symbol: Optional[str] = None


@router.get("/test/state")
def jarvis_test_state(username: str = Query("leninstark")):
    from TRADELE.services.jarvis.sim import GRAPH_STEPS, sim_state

    _require_infinity_user(username)
    return {
        "ok": True,
        "sim": sim_state(),
        "graph": GRAPH_STEPS,
        "snapshot": bus.snapshot(),
        "config": get_config(),
    }


@router.post("/test/reset")
def jarvis_test_reset(username: str = Query("leninstark")):
    from TRADELE.services.jarvis.sim import reset_lab

    _require_infinity_user(username)
    return {"ok": True, "sim": reset_lab(), "snapshot": bus.snapshot()}


@router.post("/test/arm")
def jarvis_test_arm(body: TestArmBody, username: str = Query("leninstark")):
    from TRADELE.services.jarvis.sim import start_lab

    _require_infinity_user(username)
    return start_lab(mode=body.mode)


@router.post("/test/mock-groww")
def jarvis_test_mock_groww(username: str = Query("leninstark")):
    from TRADELE.services.jarvis.sim import inject_mock_groww

    _require_infinity_user(username)
    return inject_mock_groww()


@router.post("/test/run-agent")
def jarvis_test_run_agent(username: str = Query("leninstark")):
    from TRADELE.services.jarvis.sim import run_agent_test

    _require_infinity_user(username)
    return run_agent_test(username=username)


@router.post("/test/paper-exec")
def jarvis_test_paper_exec(body: TestSideBody, username: str = Query("leninstark")):
    from TRADELE.services.jarvis.sim import paper_execute_top

    _require_infinity_user(username)
    return paper_execute_top(side=body.side)


@router.post("/test/mark")
def jarvis_test_mark(body: TestMarkBody, username: str = Query("leninstark")):
    from TRADELE.services.jarvis.sim import mark_price

    _require_infinity_user(username)
    return mark_price(symbol=body.symbol, ltp=body.ltp)


@router.post("/test/hit-sl")
def jarvis_test_hit_sl(body: TestSymbolBody, username: str = Query("leninstark")):
    from TRADELE.services.jarvis.sim import hit_sl

    _require_infinity_user(username)
    return hit_sl(body.symbol)


@router.post("/test/hit-tp")
def jarvis_test_hit_tp(body: TestSymbolBody, username: str = Query("leninstark")):
    from TRADELE.services.jarvis.sim import hit_tp

    _require_infinity_user(username)
    return hit_tp(body.symbol)


@router.post("/test/scenario")
def jarvis_test_scenario(username: str = Query("leninstark")):
    from TRADELE.services.jarvis.sim import run_full_scenario

    _require_infinity_user(username)
    return run_full_scenario(username=username)


@router.get("/test/pack")
def jarvis_test_pack(username: str = Query("leninstark")):
    from TRADELE.services.jarvis.pack import pack_info
    from TRADELE.services.jarvis.sim import load_excel_pack

    _require_infinity_user(username)
    return load_excel_pack() if pack_info().get("exists") else {"ok": False, **pack_info()}


@router.post("/test/pack/load")
def jarvis_test_pack_load(username: str = Query("leninstark")):
    from TRADELE.services.jarvis.sim import load_excel_pack

    _require_infinity_user(username)
    return load_excel_pack()


@router.post("/test/pack/replay-sample")
def jarvis_test_pack_replay(username: str = Query("leninstark")):
    from TRADELE.services.jarvis.sim import replay_session_sample

    _require_infinity_user(username)
    return replay_session_sample()


class TestReplayBody(BaseModel):
    minute: str
    top_n: int = 8


@router.post("/test/pack/replay-minute")
def jarvis_test_pack_replay_minute(body: TestReplayBody, username: str = Query("leninstark")):
    from TRADELE.services.jarvis.sim import replay_minute

    _require_infinity_user(username)
    return replay_minute(body.minute, top_n=body.top_n)


class TestLiveBody(BaseModel):
    use_claude: bool = True
    pace: float = 0.08


@router.post("/test/pack/run")
def jarvis_test_pack_run(body: TestLiveBody = TestLiveBody(), username: str = Query("leninstark")):
    """Start Excel-pack live thinking demo (async). Claude CLI always on. Poll GET /test/think."""
    from TRADELE.services.jarvis.sim import start_excel_live_demo_async

    _require_infinity_user(username)
    return start_excel_live_demo_async(use_claude=True, pace=max(0.02, min(body.pace, 0.5)))


@router.get("/test/think")
def jarvis_test_think(username: str = Query("leninstark")):
    from TRADELE.services.jarvis.sim import sim_state, thinking_state
    from TRADELE.services.jarvis.watch import watch_state

    _require_infinity_user(username)
    return {
        "ok": True,
        "think": thinking_state(),
        "sim": sim_state(),
        "snapshot": bus.snapshot(),
        "watch": watch_state(),
    }


class WatchSymbolBody(BaseModel):
    symbol: str


class ObserveStartBody(BaseModel):
    lane: str = "time"  # time | mind
    symbols: list[str] = Field(default_factory=list)


class ObserveFocusBody(BaseModel):
    symbol: str = ""


@router.get("/observe")
def jarvis_observe_get(username: str = Query("leninstark")):
    from TRADELE.services.jarvis.observe import observe_state

    _require_infinity_user(username)
    return {"ok": True, "observe": observe_state()}


@router.post("/observe/start")
def jarvis_observe_start(body: ObserveStartBody = ObserveStartBody(), username: str = Query("leninstark")):
    from TRADELE.services.jarvis.observe import start_observe

    _require_infinity_user(username)
    lane = (body.lane or "time").strip().lower()
    update_config({"observe_lane": lane if lane in ("time", "mind") else "time"})
    return start_observe(lane=lane, symbols=body.symbols or None)


@router.post("/observe/stop")
def jarvis_observe_stop(username: str = Query("leninstark")):
    from TRADELE.services.jarvis.observe import stop_observe

    _require_infinity_user(username)
    return {"ok": True, "observe": stop_observe()}


@router.post("/observe/focus")
def jarvis_observe_focus(body: ObserveFocusBody = ObserveFocusBody(), username: str = Query("leninstark")):
    from TRADELE.services.jarvis.observe import set_focus_symbol

    _require_infinity_user(username)
    return set_focus_symbol(body.symbol or "")


@router.get("/memory/sessions")
def jarvis_memory_sessions(username: str = Query("leninstark"), limit: int = Query(40)):
    from TRADELE.services.jarvis.memory import list_sessions

    _require_infinity_user(username)
    return {"ok": True, "sessions": list_sessions(limit=min(limit, 100))}


@router.get("/memory/sessions/{session_id}")
def jarvis_memory_session(session_id: str, username: str = Query("leninstark"), limit: int = Query(2000)):
    from TRADELE.services.jarvis.memory import read_session

    _require_infinity_user(username)
    return read_session(session_id, limit=min(limit, 5000))


@router.get("/watch")
def jarvis_watch_get(username: str = Query("leninstark")):
    from TRADELE.services.jarvis.watch import watch_state

    _require_infinity_user(username)
    return {"ok": True, "watch": watch_state()}


@router.post("/watch/add")
def jarvis_watch_add(body: WatchSymbolBody, username: str = Query("leninstark")):
    from TRADELE.services.jarvis.watch import add_symbol

    _require_infinity_user(username)
    return add_symbol(body.symbol)


@router.post("/watch/remove")
def jarvis_watch_remove(body: WatchSymbolBody, username: str = Query("leninstark")):
    from TRADELE.services.jarvis.watch import remove_symbol

    _require_infinity_user(username)
    return remove_symbol(body.symbol)


@router.post("/watch/clear")
def jarvis_watch_clear(username: str = Query("leninstark")):
    from TRADELE.services.jarvis.watch import clear_watch

    _require_infinity_user(username)
    return clear_watch()


@router.post("/watch/analyse")
def jarvis_watch_analyse(
    username: str = Query("leninstark"),
    mode: str = Query("both", description="both | user | pack"),
):
    from TRADELE.services.jarvis.watch import analyse_both_lanes, analyse_watch_parallel, scan_pack_top5

    _require_infinity_user(username)
    key = (mode or "both").strip().lower()
    if key == "user":
        return analyse_watch_parallel()
    if key == "pack":
        return scan_pack_top5(top_n=5)
    return analyse_both_lanes(top_n=5)


@router.websocket("/ws")
async def jarvis_ws(websocket: WebSocket, username: str = "leninstark"):
    if (username or "").strip().lower() != INFINITY_USER:
        await websocket.close(code=4403)
        return
    await websocket.accept()
    try:
        await websocket.send_json(
            {
                "type": "jarvis.hello",
                "snapshot": bus.snapshot(),
                "config": get_config(),
                "events": bus.recent(limit=30),
            }
        )
        while True:
            await asyncio.sleep(3)
            payload = await asyncio.to_thread(_ws_tick, username)
            await websocket.send_json(payload)
    except WebSocketDisconnect:
        logger.debug("jarvis ws disconnected")
    except Exception as e:
        logger.warning("jarvis ws closed: %s", e)
