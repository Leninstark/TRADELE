"""Label watchlist analyst predictions vs next-session move (RL / audit hook)."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from TRADELE.db.models import WatchlistAnalysis
from TRADELE.engines.agents.stock_analyst import build_metrics

logger = logging.getLogger(__name__)


def _verdict_direction(verdict: str) -> int:
    v = (verdict or "").lower()
    if "bull" in v or "buy" in v:
        return 1
    if "bear" in v or "sell" in v or "short" in v:
        return -1
    return 0


def label_pending_analyses(db: Session, *, as_of: date | None = None) -> dict[str, int]:
    """
    For analyses at least 1 calendar day old without outcome_label, compare
    verdict direction to latest 1-day change_pct from technical metrics.
    """
    today = as_of or date.today()
    cutoff = datetime.utcnow() - timedelta(hours=20)
    rows = (
        db.query(WatchlistAnalysis)
        .filter(
            WatchlistAnalysis.outcome_label.is_(None),
            WatchlistAnalysis.symbol.isnot(None),
            WatchlistAnalysis.created_at <= cutoff,
        )
        .order_by(WatchlistAnalysis.id.asc())
        .limit(200)
        .all()
    )
    labeled = skipped = 0
    for row in rows:
        sym = (row.symbol or "").upper()
        if not sym:
            skipped += 1
            continue
        payload = row.payload if isinstance(row.payload, dict) else {}
        if payload.get("blocked"):
            row.outcome_label = "blocked"
            row.outcome_labeled_at = datetime.utcnow()
            labeled += 1
            continue
        direction = _verdict_direction(str(payload.get("verdict") or ""))
        if direction == 0:
            row.outcome_label = "neutral"
            row.outcome_labeled_at = datetime.utcnow()
            labeled += 1
            continue
        metrics = build_metrics(sym, db)
        chg = metrics.get("change_pct") if metrics else None
        if chg is None:
            skipped += 1
            continue
        ret = float(chg)
        hit = (direction > 0 and ret > 0.15) or (direction < 0 and ret < -0.15)
        if abs(ret) <= 0.15:
            label = "scratch"
        elif hit:
            label = "win"
        else:
            label = "loss"
        row.outcome_return_pct = ret
        row.outcome_hit = hit
        row.outcome_label = label
        row.outcome_labeled_at = datetime.utcnow()
        labeled += 1
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning("watchlist outcome commit failed: %s", e)
    return {"labeled": labeled, "skipped": skipped, "as_of": today.isoformat()}
