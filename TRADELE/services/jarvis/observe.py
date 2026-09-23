"""JARVIS live observation — TIME (Lane A) vs MIND (Lane B).

TIME: Zerodha 1m candles → best 5 intraday candidates → observe 30m (selection only).
MIND: User picks symbols; same observation loop.

No broker execution — scan + score + watch only.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from typing import Any, Optional

from TRADELE.services.jarvis import bus
from TRADELE.services.jarvis.config import get_config

logger = logging.getLogger(__name__)

OBSERVE_WINDOW_SEC = 30 * 60
INITIAL_N = 10  # top candidates to watch for manual entry
ROTATE_N = 10
QUOTE_BATCH = 200
PREFILTER_N = 35  # deep-score pool (throttled workers)
TICK_SEC = 60  # one candle cadence during 30m watch
HIST_WORKERS = 2
HIST_GAP_SEC = 0.35
ENTRY_BAND = 0.002  # ±0.2% = "entry range"

_lock = threading.Lock()
_thread: Optional[threading.Thread] = None
_stop = threading.Event()

_state: dict[str, Any] = {
    "active": False,
    "lane": "time",
    "status": "idle",
    "message": "",
    "zerodha_connected": False,
    "universe": 0,
    "candidates": [],
    "observed_symbols": [],
    "entries": [],
    "alerts": [],
    "round": 0,
    "observe_until": None,
    "started_at": None,
    "updated_at": None,
    "error": None,
    "live_ui": {
        "running": False,
        "phase": "idle",
        "progress": 0,
        "title": "Idle",
        "detail": "",
        "scan_log": [],
        "decisions": [],
        "picked": None,
        "charts": None,
        "execution": [],
    },
}


def observe_state() -> dict[str, Any]:
    with _lock:
        return deepcopy(_state)


def _set(**kwargs: Any) -> None:
    with _lock:
        _state.update(kwargs)
        _state["updated_at"] = time.time()
        snap = deepcopy(_state)
    bus.publish("jarvis.observe", snap)
    if "live_ui" in kwargs or "status" in kwargs or "message" in kwargs:
        bus.publish("jarvis.think", snap.get("live_ui") or {})
    bus.publish(
        "jarvis.tape",
        {
            "kind": "observe",
            "message": snap.get("message") or f"Observe · {snap.get('status')}",
            "lane": snap.get("lane"),
            "status": snap.get("status"),
        },
    )
    try:
        from TRADELE.services.jarvis.memory import append_event

        append_event(
            "observe.tick",
            {
                "status": snap.get("status"),
                "lane": snap.get("lane"),
                "message": snap.get("message"),
                "candidates": [
                    {
                        "symbol": c.get("symbol"),
                        "side": c.get("side"),
                        "action": c.get("action"),
                        "score": c.get("score"),
                    }
                    for c in (snap.get("candidates") or [])
                ],
                "round": snap.get("round"),
            },
        )
    except Exception:
        pass


def _ui(**kwargs: Any) -> None:
    with _lock:
        ui = dict(_state.get("live_ui") or {})
        ui.update(kwargs)
        _state["live_ui"] = ui
        _state["updated_at"] = time.time()
        snap = deepcopy(_state)
    bus.publish("jarvis.observe", snap)
    bus.publish("jarvis.think", snap.get("live_ui") or {})


def _zerodha_client():
    from TRADELE.config import settings
    from TRADELE.db.session import SessionLocal
    from TRADELE.services.zerodha_client import ZerodhaClient
    from TRADELE.services.zerodha_token_store import get_active_access_token

    db = SessionLocal()
    try:
        token = get_active_access_token(db, "leninstark") or settings.kite_access_token
        if not token:
            return None, False
        return ZerodhaClient(access_token=token), True
    finally:
        db.close()


def _batch_quotes(client, symbols: list[str]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for i in range(0, len(symbols), QUOTE_BATCH):
        if _stop.is_set():
            break
        chunk = symbols[i : i + QUOTE_BATCH]
        keys = [f"NSE:{s}" for s in chunk]
        try:
            quotes = client.get_quote(keys)
            for key, q in (quotes or {}).items():
                sym = key.split(":", 1)[-1]
                ohlc = q.get("ohlc") or {}
                last = float(q.get("last_price") or ohlc.get("close") or 0)
                prev = float(ohlc.get("close") or 0)
                open_ = float(ohlc.get("open") or last or 0)
                vol = float(q.get("volume") or 0)
                chg = ((last - prev) / prev * 100) if prev else 0.0
                day_from_open = ((last - open_) / open_ * 100) if open_ else chg
                out[sym] = {
                    "last": last,
                    "prev_close": prev,
                    "open": open_,
                    "volume": vol,
                    "change_pct": chg,
                    "day_return_pct": day_from_open,
                }
        except Exception as e:
            logger.warning("JARVIS observe quote batch: %s", e)
        time.sleep(0.12)
    return out


def _universe_symbols() -> list[str]:
    """Midcap 150 + Smallcap 250 only (no large caps) when prefer_mid_small / avoid_large_cap."""
    from TRADELE.filters.universe import load_phase1_universe
    from TRADELE.services.jarvis.config import LARGE_CAP
    from TRADELE.services.universe import get_tradeable_equity_symbols

    cfg = get_config()
    mid_small_only = bool(cfg.get("prefer_mid_small", True)) or bool(cfg.get("avoid_large_cap", True))
    large_only = bool(cfg.get("large_cap_only"))

    symbols: list[str] = []
    if mid_small_only and not large_only:
        try:
            symbols = load_phase1_universe()
        except Exception as e:
            logger.warning("mid/small universe load failed: %s", e)
            symbols = []
    if not symbols:
        try:
            symbols = get_tradeable_equity_symbols()
        except Exception:
            symbols = list(LARGE_CAP)[:80]

    out: list[str] = []
    seen: set[str] = set()
    for s in symbols:
        u = str(s).upper().strip()
        if not u or u in seen:
            continue
        if large_only and u not in LARGE_CAP:
            continue
        # Hard exclude large caps whenever mid/small mode is on
        if (mid_small_only or cfg.get("avoid_large_cap")) and not large_only and u in LARGE_CAP:
            continue
        seen.add(u)
        out.append(u)

    if mid_small_only and not large_only:
        return out  # full Mid+Small (~400)

    cap = int(cfg.get("max_candidates_scan") or 200)
    return out[: max(cap, 80)]


def _rank_movers(
    quotes: dict[str, dict[str, float]],
    *,
    exclude: set[str],
    top_n: int,
) -> list[str]:
    cfg = get_config()
    min_p = float(cfg.get("min_price") or 50)
    max_p = float(cfg.get("max_price") or 5000)
    min_vol = float(cfg.get("min_avg_volume") or 50_000)
    scored: list[tuple[float, str]] = []
    for sym, q in quotes.items():
        if sym in exclude:
            continue
        last = float(q.get("last") or 0)
        if last < min_p or last > max_p:
            continue
        vol = float(q.get("volume") or 0)
        if vol < min_vol * 0.25:
            continue
        day_ret = abs(float(q.get("day_return_pct") or q.get("change_pct") or 0))
        if day_ret < 0.4:
            continue
        score = day_ret * math.log10(max(vol, 10))
        scored.append((score, sym))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [s for _, s in scored[:top_n]]


def _publish_candidates(cands: list[dict[str, Any]], *, regime: str) -> None:
    longs = [c for c in cands if c.get("side") == "LONG"]
    shorts = [c for c in cands if c.get("side") == "SHORT"]

    def row(c: dict[str, Any]) -> dict[str, Any]:
        return {
            "symbol": c.get("symbol"),
            "side": c.get("side"),
            "score": c.get("score"),
            "strategy": (c.get("votes") or ["J-B"])[0],
            "label": "observe",
            "entry": c.get("entry"),
            "sl": c.get("stop_loss"),
            "tp": c.get("target"),
            "rr": get_config().get("target_r_multiple"),
            "action": c.get("action"),
            "lane": c.get("lane"),
            "reasons": c.get("reasons") or [],
        }

    bus.publish(
        "jarvis.candidates",
        {
            "longs": [row(c) for c in longs],
            "shorts": [row(c) for c in shorts],
            "regime": regime,
        },
    )


def _analyse_live_stream(symbols: list[str], *, lane: str, n: int) -> list[dict[str, Any]]:
    """Score Zerodha 1m bars live; stream scan_log into live_ui.

    Throttled (2 workers + gap) to avoid Kite 'Too many requests'.
    """
    from TRADELE.services.jarvis.brain_charts import build_brain_activity
    from TRADELE.services.jarvis.watch import analyse_symbol
    from TRADELE.services.zerodha_client import KiteRateLimitError

    plans: list[dict[str, Any]] = []
    scan_log: list[dict[str, Any]] = []
    total = max(len(symbols), 1)
    rate_hit = False

    with ThreadPoolExecutor(max_workers=HIST_WORKERS) as ex:
        futs = {}
        for i, s in enumerate(symbols):
            if _stop.is_set() or rate_hit:
                break
            futs[ex.submit(analyse_symbol, s, live=True)] = s
            if i + 1 < len(symbols):
                time.sleep(HIST_GAP_SEC)
        done = 0
        for fut in as_completed(futs):
            if _stop.is_set():
                break
            sym = futs[fut]
            done += 1
            try:
                p = fut.result()
            except KiteRateLimitError:
                rate_hit = True
                p = {"symbol": sym, "ok": False, "error": "rate_limit", "action": "skip"}
                logger.warning("Kite rate limit mid-scan — stopping further 1m fetches")
            except Exception as e:
                p = {"symbol": sym, "ok": False, "error": str(e), "action": "skip"}
            ok = bool(p.get("ok") and p.get("side") in ("LONG", "SHORT"))
            row = {
                "symbol": sym,
                "status": "keep" if ok else ("skip" if p.get("ok") else "err"),
                "score": p.get("score"),
                "side": p.get("side"),
                "reason": " · ".join((p.get("reasons") or [])[:3]) or p.get("error") or p.get("action"),
                "strategy": (p.get("votes") or ["J-B"])[0] if ok else None,
            }
            scan_log.append(row)
            if ok:
                p = {**p, "lane": "pack" if lane == "time" else "user"}
                plans.append(p)
            prog = 15 + int(70 * done / total)
            _ui(
                phase="scan",
                progress=min(prog, 85),
                title="Scanning Zerodha 1m",
                detail=f"{done}/{total} · {sym}" + (" · rate-limited" if rate_hit else ""),
                scan_log=list(scan_log)[-80:],
                charts={"activity": build_brain_activity(scan_log, []), "mode": "live"},
            )
            if rate_hit:
                break

    plans.sort(
        key=lambda p: (float(p.get("probability") or 0), float(p.get("score") or 0)),
        reverse=True,
    )
    enters = [p for p in plans if p.get("action") == "enter"]
    waits = [p for p in plans if p.get("action") != "enter"]
    return (enters + waits)[:n]


def _scan_time_candidates(*, n: int, exclude: set[str]) -> tuple[list[dict[str, Any]], bool, int]:
    _ui(phase="boot", progress=5, title="Connecting Zerodha", detail="Loading quotes…", running=True)
    client, ok = _zerodha_client()
    if not ok or client is None:
        return [], False, 0
    symbols = _universe_symbols()
    _ui(phase="scan", progress=10, title="Quote prefilter", detail=f"Mid/Small universe {len(symbols)}")
    quotes = _batch_quotes(client, symbols)
    movers = _rank_movers(quotes, exclude=exclude, top_n=PREFILTER_N)
    if not movers:
        soft = sorted(
            (
                (abs(float(q.get("day_return_pct") or 0)), s)
                for s, q in quotes.items()
                if s not in exclude
            ),
            reverse=True,
        )
        movers = [s for _, s in soft[:PREFILTER_N]]
    _ui(
        phase="scan",
        progress=15,
        title="Deep 1m score",
        detail=f"Scoring top {len(movers)} mid/small movers on Zerodha 1m",
    )
    picked = _analyse_live_stream(movers, lane="time", n=n)
    return picked, True, len(symbols)


def _finalize_picks(picked: list[dict[str, Any]], *, lane: str, universe: int, zok: bool, round_n: int) -> None:
    from TRADELE.services.jarvis.brain_charts import build_brain_activity

    # Arm each plan for observe: wait until price reaches entry (manual exec notify)
    armed: list[dict[str, Any]] = []
    for p in picked:
        entry = p.get("entry")
        side = p.get("side")
        row = {
            **p,
            "watch_status": "WAITING_ENTRY",
            "pulled_back": False,
            "notified": False,
            "entry": entry,
            "action": "wait",  # never auto-enter — notify only
        }
        # Seed: if already away from entry at pick, mark pulled so reclaim can fire
        # (pick LTP often == entry; we require a pullback then reclaim before notify)
        armed.append(row)

    decisions = []
    for i, p in enumerate(armed):
        reasons = p.get("reasons") or []
        why_bits = [
            f"#{i + 1} of mid/small day-movers by 1m score",
            f"score {p.get('score')} · p={float(p.get('probability') or 0):.0%}",
            f"WATCH entry {p.get('entry')} — notify when LTP reaches range",
            " · ".join(str(r) for r in reasons[:3]),
        ]
        decisions.append(
            {
                "symbol": p.get("symbol"),
                "side": p.get("side"),
                "score": p.get("score"),
                "strategy": (p.get("votes") or ["J-B"])[0],
                "verdict": "WAITING_ENTRY",
                "why": " · ".join(b for b in why_bits if b),
                "entry": p.get("entry"),
                "sl": p.get("stop_loss"),
                "tp": p.get("target"),
            }
        )
    primary = armed[0] if armed else None
    scan_log = list((observe_state().get("live_ui") or {}).get("scan_log") or [])
    charts = {
        "focus": (primary or {}).get("chart"),
        "activity": build_brain_activity(scan_log, decisions),
        "mode": "live_pick",
        "asof": time.time(),
        "focus_symbol": (primary or {}).get("symbol"),
    }
    regime = "OBSERVE_TIME" if lane == "time" else "OBSERVE_MIND"
    _publish_candidates(armed, regime=regime)
    _set(
        status="observing",
        candidates=armed,
        observed_symbols=[p.get("symbol") for p in armed if p.get("symbol")],
        entries=[],
        alerts=[],
        observe_until=time.time() + OBSERVE_WINDOW_SEC,
        zerodha_connected=zok,
        universe=universe,
        round=round_n,
        message=(
            f"{'TIME' if lane == 'time' else 'MIND'} · watching top {len(armed)} · "
            f"notify when entry hit (manual exec)"
        ),
        focus_symbol=(primary or {}).get("symbol"),
    )
    _ui(
        running=True,
        phase="observe",
        progress=100,
        title=f"Watching {len(armed)} · waiting for entry",
        detail="Quotes every 1m · alert when any name reaches entry · no auto order",
        decisions=decisions,
        alerts=[],
        picked={
            "symbol": primary.get("symbol"),
            "side": primary.get("side"),
            "score": primary.get("score"),
            "strategy": (primary.get("votes") or ["J-B"])[0],
            "entry": primary.get("entry"),
            "sl": primary.get("stop_loss"),
            "tp": primary.get("target"),
            "reasons": primary.get("reasons") or [],
        }
        if primary
        else None,
        charts=charts,
        execution=[
            {
                "step": "select",
                "message": (
                    f"Top {len(armed)} mid/small locked · observing entry levels · "
                    f"you execute manually when notified"
                ),
            }
        ],
    )


def _check_entries_quotes(cands: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Watch all candidates via LTP. Notify only after pullback then reclaim into entry range.

    Returns (updated_candidates, fresh_hits).
    """
    client, ok = _zerodha_client()
    if not ok or client is None or not cands:
        return cands, []
    syms = [str(c.get("symbol")).upper() for c in cands if c.get("symbol")]
    quotes = _batch_quotes(client, syms)
    updated: list[dict[str, Any]] = []
    hits: list[dict[str, Any]] = []
    band = ENTRY_BAND

    for c in cands:
        row = dict(c)
        sym = str(row.get("symbol") or "").upper()
        q = quotes.get(sym)
        if not q:
            updated.append(row)
            continue
        last = float(q.get("last") or 0)
        entry = float(row.get("entry") or 0)
        side = str(row.get("side") or "")
        row["last"] = last
        if not last or not entry or side not in ("LONG", "SHORT"):
            updated.append(row)
            continue

        lo = entry * (1 - band)
        hi = entry * (1 + band)

        if side == "LONG":
            # Away below entry → armed for reclaim
            if last < lo:
                row["pulled_back"] = True
                row["watch_status"] = "WAITING_ENTRY"
            in_range = last >= lo
            reclaim = bool(row.get("pulled_back")) and in_range
        else:
            if last > hi:
                row["pulled_back"] = True
                row["watch_status"] = "WAITING_ENTRY"
            in_range = last <= hi
            reclaim = bool(row.get("pulled_back")) and in_range

        if reclaim and not row.get("notified"):
            row["notified"] = True
            row["watch_status"] = "ENTRY_HIT"
            row["action"] = "enter"
            hit = {
                **row,
                "last": last,
                "ok": True,
                "signal_via": "quote",
                "alert": (
                    f"ENTRY HIT · {sym} {side} @ {last:.2f} "
                    f"(entry {entry:.2f} ±{band * 100:.1f}%) — execute manually"
                ),
            }
            hits.append(hit)
        elif row.get("notified"):
            row["watch_status"] = "ENTRY_HIT"
        elif in_range and not row.get("pulled_back"):
            # Sitting on entry at pick — still waiting for a pullback first
            row["watch_status"] = "AT_ENTRY_WAIT_PULLBACK"
        else:
            row["watch_status"] = "WAITING_ENTRY"

        updated.append(row)

    return updated, hits


def _refresh_focus_chart(symbol: str, cand: Optional[dict[str, Any]] = None) -> bool:
    """One Zerodha 1m historical fetch for the focused symbol (once per minute)."""
    from TRADELE.services.jarvis.watch import analyse_symbol
    from TRADELE.services.zerodha_client import KiteRateLimitError

    try:
        plan = analyse_symbol(symbol, live=True)
    except KiteRateLimitError:
        logger.warning("Skip chart refresh %s — Kite rate limit", symbol)
        return False
    except Exception as e:
        logger.debug("chart refresh %s: %s", symbol, e)
        return False
    if not plan.get("ok") or not plan.get("chart"):
        return False

    st = observe_state()
    cands = list(st.get("candidates") or [])
    for i, c in enumerate(cands):
        if str(c.get("symbol") or "").upper() == symbol.upper():
            merged = {**c, "chart": plan["chart"], "score": plan.get("score", c.get("score"))}
            # keep original entry/sl/tp from pick unless missing
            for k_src, k_dst in (("entry", "entry"), ("stop_loss", "stop_loss"), ("target", "target")):
                if plan.get(k_src) is not None and c.get(k_dst) is None:
                    merged[k_dst] = plan[k_src]
            cands[i] = merged
            break
    charts = dict((st.get("live_ui") or {}).get("charts") or {})
    charts["focus"] = plan["chart"]
    charts["asof"] = time.time()
    charts["focus_symbol"] = symbol
    charts["mode"] = "live_1m"
    _set(candidates=cands, focus_symbol=symbol)
    left = 0
    until = float(st.get("observe_until") or 0)
    if until:
        left = max(0, int(until - time.time()))
    _ui(
        charts=charts,
        detail=f"1m candle · {symbol} · {left // 60}m {left % 60}s left",
    )
    return True


def _loop() -> None:
    """Background: finish initial scan if needed, then 30m observe / rotate."""
    st0 = observe_state()
    lane = st0.get("lane") or "time"
    try:
        if st0.get("status") == "scanning":
            if lane == "mind":
                from TRADELE.services.jarvis.watch import list_watch

                syms = list(st0.get("pending_symbols") or list_watch())
                _ui(phase="scan", progress=20, title="MIND live score", detail=f"{len(syms)} symbols", running=True)
                picked = _analyse_live_stream(syms, lane="mind", n=max(len(syms), 1))
                if not picked:
                    picked = [
                        {
                            "symbol": s,
                            "ok": True,
                            "action": "wait",
                            "side": "FLAT",
                            "score": 50,
                            "lane": "user",
                            "reasons": ["awaiting structure"],
                        }
                        for s in syms
                    ]
                _, zok = _zerodha_client()
                _finalize_picks(picked, lane="mind", universe=len(syms), zok=zok, round_n=1)
            else:
                picked, zok, universe = _scan_time_candidates(n=INITIAL_N, exclude=set())
                if not zok:
                    _set(
                        active=False,
                        status="error",
                        error="Zerodha not connected",
                        message="Connect Zerodha to run TIME lane",
                        zerodha_connected=False,
                    )
                    _ui(running=False, phase="error", title="Zerodha offline", detail="Connect Zerodha")
                    return
                if not picked:
                    _set(
                        active=False,
                        status="error",
                        error="No movers found",
                        message="Scan found no long/short candidates",
                        zerodha_connected=True,
                        universe=universe,
                    )
                    _ui(running=False, phase="error", title="No candidates", detail="No movers scored")
                    return
                _finalize_picks(picked, lane="time", universe=universe, zok=True, round_n=1)

        while not _stop.is_set():
            st = observe_state()
            if not st.get("active"):
                break
            if st.get("status") != "observing":
                time.sleep(1)
                continue
            until = float(st.get("observe_until") or 0)
            cands = list(st.get("candidates") or [])

            # Cheap: LTP quotes for all top-N — notify only on entry-range hit after pullback
            updated, hits = _check_entries_quotes(cands)
            _set(candidates=updated)

            # Sync decision verdicts with watch status
            decisions = []
            for i, p in enumerate(updated):
                decisions.append(
                    {
                        "symbol": p.get("symbol"),
                        "side": p.get("side"),
                        "score": p.get("score"),
                        "strategy": (p.get("votes") or ["J-B"])[0],
                        "verdict": p.get("watch_status") or "WAITING_ENTRY",
                        "why": (
                            f"#{i + 1} · entry {p.get('entry')} · LTP {p.get('last') or '—'} · "
                            f"{'NOTIFY — execute manually' if p.get('notified') else 'watching for entry range'}"
                        ),
                        "entry": p.get("entry"),
                        "sl": p.get("stop_loss"),
                        "tp": p.get("target"),
                        "last": p.get("last"),
                    }
                )
            _ui(decisions=decisions)

            if hits:
                with _lock:
                    existing = {e.get("symbol") for e in (_state.get("entries") or [])}
                    fresh = [h for h in hits if h.get("symbol") not in existing]
                    if fresh:
                        _state["entries"] = list(_state.get("entries") or []) + fresh
                        alerts = list(_state.get("alerts") or [])
                        exec_log = list((st.get("live_ui") or {}).get("execution") or [])
                        for h in fresh:
                            msg = h.get("alert") or (
                                f"ENTRY HIT · {h.get('symbol')} @ {h.get('last')} — execute manually"
                            )
                            alerts.append(
                                {
                                    "symbol": h.get("symbol"),
                                    "side": h.get("side"),
                                    "last": h.get("last"),
                                    "entry": h.get("entry"),
                                    "message": msg,
                                    "at": time.time(),
                                }
                            )
                            exec_log.append({"step": "ALERT", "message": msg})
                        _state["alerts"] = alerts[-20:]
                        names = ", ".join(str(h.get("symbol")) for h in fresh)
                        _ui(
                            title="ENTRY HIT — execute manually",
                            detail=names,
                            alerts=list(_state["alerts"]),
                            execution=exec_log[-40:],
                        )
                        _set(message=f"ENTRY HIT · {names} · execute manually")
                        _publish_candidates(fresh, regime="OBSERVE_ENTRY")
                        bus.publish(
                            "jarvis.tape",
                            {"kind": "alert", "message": f"ENTRY HIT · {names} — execute manually"},
                        )

            if time.time() >= until:
                _set(status="rotating", message="No fresh entry in 30m — hunting 10 new movers…")
                _ui(phase="scan", progress=20, title="Rescan", detail="30m elapsed · new movers")
                exclude = set(st.get("observed_symbols") or []) | {
                    c.get("symbol") for c in updated if c.get("symbol")
                }
                new_cands, zok, universe = _scan_time_candidates(n=ROTATE_N, exclude=exclude)
                if not new_cands:
                    _set(
                        status="stopped",
                        active=False,
                        message="No fresh movers — observation stopped",
                        zerodha_connected=zok,
                    )
                    _ui(running=False, phase="done", title="Stopped", detail="No fresh movers")
                    break
                _finalize_picks(
                    new_cands,
                    lane="time",
                    universe=universe or st.get("universe") or 0,
                    zok=zok,
                    round_n=int(st.get("round") or 0) + 1,
                )
                continue

            # One 1m historical fetch per minute for focus chart only
            focus = (
                st.get("focus_symbol")
                or (updated[0].get("symbol") if updated else None)
            )
            if focus:
                _refresh_focus_chart(str(focus), updated[0] if updated else None)

            left = max(0, int(until - time.time()))
            waiting = sum(1 for c in updated if not c.get("notified"))
            hit_n = sum(1 for c in updated if c.get("notified"))
            _ui(
                detail=(
                    f"Watching {waiting} · {hit_n} entry hit · "
                    f"{left // 60}m {left % 60}s left · manual exec"
                ),
            )
            # Align roughly to next minute boundary
            now = time.time()
            sleep_for = max(5.0, TICK_SEC - (now % 60))
            slept = 0.0
            while slept < sleep_for and not _stop.is_set():
                step = min(2.0, sleep_for - slept)
                time.sleep(step)
                slept += step
    except Exception as e:
        logger.exception("observe loop failed")
        _set(active=False, status="error", error=str(e), message=str(e))
        _ui(running=False, phase="error", title="Failed", detail=str(e))
    finally:
        with _lock:
            if _state.get("active") and _state.get("status") not in ("stopped", "error", "observing"):
                _state["active"] = False
                _state["status"] = "stopped"


def stop_observe() -> dict[str, Any]:
    global _thread
    _stop.set()
    t = _thread
    if t and t.is_alive():
        t.join(timeout=2)
    _thread = None
    _set(active=False, status="stopped", message="Observation stopped")
    _ui(running=False, phase="done", title="Stopped", detail="Observation stopped")
    try:
        from TRADELE.services.jarvis.memory import end_session

        end_session(summary={"status": "stopped"})
    except Exception:
        pass
    return observe_state()


def set_focus_symbol(symbol: str) -> dict[str, Any]:
    """UI chip click — next 1m refresh targets this symbol."""
    sym = (symbol or "").strip().upper()
    if not sym:
        return {"ok": False, "error": "symbol required", "observe": observe_state()}
    _set(focus_symbol=sym)
    # Immediate one-shot refresh so chart updates without waiting a full minute
    cands = list(observe_state().get("candidates") or [])
    cand = next((c for c in cands if str(c.get("symbol") or "").upper() == sym), None)
    ok = _refresh_focus_chart(sym, cand)
    return {"ok": ok, "observe": observe_state()}


def start_observe(*, lane: str, symbols: Optional[list[str]] = None) -> dict[str, Any]:
    """Kick off live scan in background. Poll GET /observe for live_ui."""
    global _thread
    key = (lane or "time").strip().lower()
    if key not in ("time", "mind"):
        return {"ok": False, "error": "lane must be time or mind", "observe": observe_state()}

    if observe_state().get("active"):
        stop_observe()

    try:
        from TRADELE.services.jarvis.memory import start_session

        start_session(lane=key, source="observe_live", meta={"symbols": symbols or []})
    except Exception:
        pass

    pending: list[str] = []
    if key == "mind":
        from TRADELE.services.jarvis.watch import add_symbol, clear_watch, list_watch

        pending = [str(s).strip().upper() for s in (symbols or []) if str(s).strip()]
        if not pending:
            pending = list_watch()
        if not pending:
            return {
                "ok": False,
                "error": "Add at least one stock for MIND",
                "observe": observe_state(),
            }
        clear_watch()
        for s in pending:
            add_symbol(s)

    _stop.clear()
    with _lock:
        _state.update(
            {
                "active": True,
                "lane": key,
                "status": "scanning",
                "message": "Connecting Zerodha · Mid/Small 1m scan…" if key == "time" else "Scoring MIND list…",
                "zerodha_connected": False,
                "universe": 0,
                "candidates": [],
                "observed_symbols": [],
                "entries": [],
                "alerts": [],
                "pending_symbols": pending,
                "round": 1,
                "observe_until": None,
                "started_at": time.time(),
                "updated_at": time.time(),
                "error": None,
                "live_ui": {
                    "running": True,
                    "phase": "boot",
                    "progress": 1,
                    "title": "Starting live scan",
                    "detail": "Zerodha 1m · Mid/Small · top 10 · notify on entry",
                    "scan_log": [],
                    "decisions": [],
                    "alerts": [],
                    "picked": None,
                    "charts": None,
                    "execution": [],
                },
            }
        )

    _thread = threading.Thread(target=_loop, name="jarvis-observe-live", daemon=True)
    _thread.start()
    return {"ok": True, "observe": observe_state()}
