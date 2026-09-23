"""Persist intraday momentum scans for RL / conviction audit.

One canonical successful run per (username, as_of) is preferred so conviction
stays deterministic for the full day.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session, joinedload

from TRADELE.db.models import IntradayMomentumCandidate, IntradayMomentumScanRun

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")


def _next_weekday(d: date) -> date:
    n = d + timedelta(days=1)
    while n.weekday() >= 5:
        n += timedelta(days=1)
    return n


def last_completed_session(now: Optional[datetime] = None) -> date:
    """
    Session date for late-session momentum.
    Before market close (15:30 IST) on a weekday → previous weekday.
    Weekends → prior Friday.
    """
    now = now or datetime.now(IST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    else:
        now = now.astimezone(IST)
    d = now.date()
    if d.weekday() >= 5:
        while d.weekday() >= 5:
            d -= timedelta(days=1)
        return d
    close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    if now < close:
        d = d - timedelta(days=1)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
    return d


def _by_conviction(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        items,
        key=lambda c: (
            int(c.get("conviction") or 0),
            float(c.get("score") or 0),
            int(c.get("checks_passed") or 0),
        ),
        reverse=True,
    )


def _rebuild_payload_from_run(run: IntradayMomentumScanRun) -> dict[str, Any]:
    """Rebuild API-shaped payload from DB rows (deterministic)."""
    if isinstance(run.payload, dict) and (run.payload.get("longs") or run.payload.get("shorts")):
        out = dict(run.payload)
    else:
        longs: list[dict[str, Any]] = []
        shorts: list[dict[str, Any]] = []
        for c in run.candidates or []:
            blob = dict(c.conviction_payload or {})
            blob.setdefault("symbol", c.symbol)
            blob.setdefault("direction", c.direction)
            blob.setdefault("conviction", c.conviction)
            blob.setdefault("score", c.score)
            blob.setdefault("can_trade_tomorrow", c.can_trade_tomorrow)
            blob.setdefault("checks_passed", c.checks_passed)
            blob.setdefault("checks_total", c.checks_total)
            blob.setdefault("data_source", c.data_source)
            if c.is_top_pick:
                if c.direction == "long":
                    longs.append(blob)
                else:
                    shorts.append(blob)
        longs = _by_conviction(longs)
        shorts = _by_conviction(shorts)
        out = {
            "as_of": run.as_of.isoformat() if run.as_of else None,
            "scanned": run.scanned,
            "prefiltered": run.prefiltered,
            "sources": run.sources or [],
            "rate_limited": run.rate_limited,
            "pattern": run.pattern,
            "longs": longs,
            "shorts": shorts,
            "message": run.error_message,
        }
    out["as_of"] = run.as_of.isoformat() if run.as_of else out.get("as_of")
    out["run_id"] = run.id
    out["saved"] = True
    out["from_cache"] = True
    out["target_date"] = run.target_date.isoformat() if run.target_date else None
    # Ensure sorted
    out["longs"] = _by_conviction(list(out.get("longs") or []))
    out["shorts"] = _by_conviction(list(out.get("shorts") or []))
    return out


def get_day_cached_scan(
    db: Session,
    *,
    username: str,
    as_of: date,
) -> Optional[dict[str, Any]]:
    """Return the best successful scan for this session day (has candidates)."""
    q = (
        db.query(IntradayMomentumScanRun)
        .options(joinedload(IntradayMomentumScanRun.candidates))
        .filter(
            IntradayMomentumScanRun.username == username,
            IntradayMomentumScanRun.as_of == as_of,
            IntradayMomentumScanRun.status.in_(("success", "partial")),
            IntradayMomentumScanRun.scanned > 0,
        )
        .order_by(IntradayMomentumScanRun.id.desc())
    )
    for run in q.all():
        tops = [c for c in (run.candidates or []) if c.is_top_pick]
        payload_has = isinstance(run.payload, dict) and (
            (run.payload.get("longs") or run.payload.get("shorts"))
        )
        if tops or payload_has:
            return _rebuild_payload_from_run(run)
    return None


def get_latest_good_scan(
    db: Session,
    *,
    username: str,
    max_age_days: int = 5,
) -> Optional[dict[str, Any]]:
    """Fallback: most recent good scan within a few sessions."""
    since = date.today() - timedelta(days=max_age_days + 2)
    rows = (
        db.query(IntradayMomentumScanRun)
        .options(joinedload(IntradayMomentumScanRun.candidates))
        .filter(
            IntradayMomentumScanRun.username == username,
            IntradayMomentumScanRun.as_of >= since,
            IntradayMomentumScanRun.status.in_(("success", "partial")),
            IntradayMomentumScanRun.scanned > 0,
        )
        .order_by(IntradayMomentumScanRun.as_of.desc(), IntradayMomentumScanRun.id.desc())
        .all()
    )
    for run in rows:
        tops = [c for c in (run.candidates or []) if c.is_top_pick]
        payload_has = isinstance(run.payload, dict) and (
            (run.payload.get("longs") or run.payload.get("shorts"))
        )
        if tops or payload_has:
            return _rebuild_payload_from_run(run)
    return None


def save_momentum_scan(
    db: Session,
    *,
    username: str,
    result: dict[str, Any],
    longs_all: Optional[list[dict[str, Any]]] = None,
    shorts_all: Optional[list[dict[str, Any]]] = None,
    status: str = "success",
    error_message: Optional[str] = None,
) -> Optional[int]:
    """
    Persist a scan. Empty/zero-scanned runs are stored as status=empty and are
    never used as the day cache. Good runs upsert the canonical day row.
    """
    try:
        as_of_raw = result.get("as_of")
        if isinstance(as_of_raw, date):
            as_of = as_of_raw
        elif as_of_raw:
            as_of = date.fromisoformat(str(as_of_raw)[:10])
        else:
            as_of = last_completed_session()

        top_longs = _by_conviction(list(result.get("longs") or []))
        top_shorts = _by_conviction(list(result.get("shorts") or []))
        result = {**result, "longs": top_longs, "shorts": top_shorts}

        all_longs = _by_conviction(list(longs_all) if longs_all is not None else top_longs)
        all_shorts = _by_conviction(list(shorts_all) if shorts_all is not None else top_shorts)

        scanned = int(result.get("scanned") or 0)
        has_picks = bool(top_longs or top_shorts)
        if result.get("error") and not has_picks:
            status = "failed"
        elif scanned <= 0 or not has_picks:
            status = "empty"

        # Do not let empty runs replace a good day cache — still log them lightly
        if status == "empty":
            run = IntradayMomentumScanRun(
                username=username or "leninstark",
                as_of=as_of,
                target_date=_next_weekday(as_of),
                started_at=datetime.utcnow(),
                finished_at=datetime.utcnow(),
                status="empty",
                error_message=error_message
                or result.get("message")
                or "No candidates for session (likely pre-open / no bars).",
                scanned=scanned,
                prefiltered=int(result.get("prefiltered") or 0),
                rate_limited=bool(result.get("rate_limited")),
                sources=list(result.get("sources") or []),
                pattern=result.get("pattern"),
                payload=result,
            )
            db.add(run)
            db.commit()
            logger.info("Saved empty momentum scan run_id=%s as_of=%s", run.id, as_of)
            return run.id

        top_long_syms = {c.get("symbol") for c in top_longs if c.get("symbol")}
        top_short_syms = {c.get("symbol") for c in top_shorts if c.get("symbol")}

        # Upsert: replace prior good run for same username+as_of
        existing = (
            db.query(IntradayMomentumScanRun)
            .filter(
                IntradayMomentumScanRun.username == (username or "leninstark"),
                IntradayMomentumScanRun.as_of == as_of,
                IntradayMomentumScanRun.status.in_(("success", "partial")),
                IntradayMomentumScanRun.scanned > 0,
            )
            .order_by(IntradayMomentumScanRun.id.desc())
            .first()
        )
        if existing:
            db.query(IntradayMomentumCandidate).filter(
                IntradayMomentumCandidate.run_id == existing.id
            ).delete()
            run = existing
            run.finished_at = datetime.utcnow()
            run.status = status if not result.get("error") else "partial"
            run.error_message = error_message or result.get("message")
            run.scanned = scanned
            run.prefiltered = int(result.get("prefiltered") or 0)
            run.rate_limited = bool(result.get("rate_limited"))
            run.sources = list(result.get("sources") or [])
            run.pattern = result.get("pattern")
            run.payload = result
            run.target_date = _next_weekday(as_of)
        else:
            run = IntradayMomentumScanRun(
                username=username or "leninstark",
                as_of=as_of,
                target_date=_next_weekday(as_of),
                started_at=datetime.utcnow(),
                finished_at=datetime.utcnow(),
                status=status if not result.get("error") else "partial",
                error_message=error_message or result.get("message") or result.get("error"),
                scanned=scanned,
                prefiltered=int(result.get("prefiltered") or 0),
                rate_limited=bool(result.get("rate_limited")),
                sources=list(result.get("sources") or []),
                pattern=result.get("pattern"),
                payload=result,
            )
            db.add(run)
            db.flush()

        def _add_rows(items: list[dict[str, Any]], direction: str, top_syms: set) -> None:
            for i, c in enumerate(items, start=1):
                sym = (c.get("symbol") or "").upper()
                if not sym:
                    continue
                metrics = c.get("metrics") or {}
                db.add(
                    IntradayMomentumCandidate(
                        run_id=run.id,
                        symbol=sym,
                        direction=direction,
                        rank=i,
                        is_top_pick=sym in top_syms,
                        conviction=int(c.get("conviction") or 0),
                        score=float(c["score"]) if c.get("score") is not None else None,
                        can_trade_tomorrow=bool(c.get("can_trade_tomorrow")),
                        checks_passed=int(c.get("checks_passed") or 0),
                        checks_total=int(c.get("checks_total") or 0),
                        close=float(metrics["close"]) if metrics.get("close") is not None else None,
                        data_source=c.get("data_source"),
                        conviction_payload=c,
                    )
                )

        _add_rows(all_longs, "long", top_long_syms)
        _add_rows(all_shorts, "short", top_short_syms)

        db.commit()
        logger.info(
            "Saved intraday momentum scan run_id=%s as_of=%s longs=%s shorts=%s",
            run.id,
            as_of,
            len(all_longs),
            len(all_shorts),
        )
        return run.id
    except Exception as e:
        logger.exception("Failed to persist intraday momentum scan: %s", e)
        try:
            db.rollback()
        except Exception:
            pass
        return None


def list_momentum_runs(
    db: Session,
    *,
    username: Optional[str] = None,
    limit: int = 30,
) -> list[dict[str, Any]]:
    q = db.query(IntradayMomentumScanRun).order_by(IntradayMomentumScanRun.id.desc())
    if username:
        q = q.filter(IntradayMomentumScanRun.username == username)
    rows = q.limit(limit).all()
    out = []
    for r in rows:
        tops = [c for c in (r.candidates or []) if c.is_top_pick]
        out.append(
            {
                "id": r.id,
                "username": r.username,
                "as_of": r.as_of.isoformat() if r.as_of else None,
                "target_date": r.target_date.isoformat() if r.target_date else None,
                "status": r.status,
                "scanned": r.scanned,
                "prefiltered": r.prefiltered,
                "rate_limited": r.rate_limited,
                "sources": r.sources,
                "candidate_count": len(r.candidates or []),
                "top_picks": [
                    {
                        "symbol": c.symbol,
                        "direction": c.direction,
                        "rank": c.rank,
                        "conviction": c.conviction,
                        "can_trade_tomorrow": c.can_trade_tomorrow,
                        "outcome_hit": c.outcome_hit,
                        "outcome_return_pct": c.outcome_return_pct,
                    }
                    for c in sorted(tops, key=lambda x: (x.direction, x.rank))
                ],
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            }
        )
    return out


def get_momentum_run(db: Session, run_id: int) -> Optional[dict[str, Any]]:
    r = (
        db.query(IntradayMomentumScanRun)
        .options(joinedload(IntradayMomentumScanRun.candidates))
        .filter(IntradayMomentumScanRun.id == run_id)
        .first()
    )
    if not r:
        return None
    return {
        "id": r.id,
        "username": r.username,
        "as_of": r.as_of.isoformat() if r.as_of else None,
        "target_date": r.target_date.isoformat() if r.target_date else None,
        "status": r.status,
        "error_message": r.error_message,
        "scanned": r.scanned,
        "prefiltered": r.prefiltered,
        "rate_limited": r.rate_limited,
        "sources": r.sources,
        "pattern": r.pattern,
        "payload": r.payload,
        "candidates": [
            {
                "id": c.id,
                "symbol": c.symbol,
                "direction": c.direction,
                "rank": c.rank,
                "is_top_pick": c.is_top_pick,
                "conviction": c.conviction,
                "score": c.score,
                "can_trade_tomorrow": c.can_trade_tomorrow,
                "checks_passed": c.checks_passed,
                "checks_total": c.checks_total,
                "close": c.close,
                "data_source": c.data_source,
                "conviction_payload": c.conviction_payload,
                "outcome_return_pct": c.outcome_return_pct,
                "outcome_mfe_pct": c.outcome_mfe_pct,
                "outcome_mae_pct": c.outcome_mae_pct,
                "outcome_hit": c.outcome_hit,
                "outcome_label": c.outcome_label,
                "outcome_notes": c.outcome_notes,
                "outcome_labeled_at": c.outcome_labeled_at.isoformat() if c.outcome_labeled_at else None,
            }
            for c in sorted(r.candidates or [], key=lambda x: (x.direction, x.rank))
        ],
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
    }
