"""Alerts API: list and latest."""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from TRADELE.db.session import get_db
from TRADELE.db.models import Alert

router = APIRouter()


@router.get("")
def list_alerts(
    direction: Optional[str] = None,
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
):
    """List stored alerts (audit trail). Filter by direction=long|short."""
    q = db.query(Alert).order_by(Alert.created_at.desc())
    if direction in ("long", "short"):
        q = q.filter(Alert.direction == direction)
    return [alert_to_dict(a) for a in q.limit(limit).all()]


@router.get("/latest")
def latest_alerts(db: Session = Depends(get_db)):
    """Latest scan result: top 10 long and top 10 short from most recent run."""
    latest_run = (
        db.query(Alert.scan_run_id)
        .filter(Alert.scan_run_id.isnot(None))
        .order_by(Alert.created_at.desc())
        .first()
    )
    if not latest_run:
        return {"long": [], "short": []}
    run_id = latest_run[0]
    longs = db.query(Alert).filter(Alert.scan_run_id == run_id, Alert.direction == "long").order_by(Alert.rank).all()
    shorts = db.query(Alert).filter(Alert.scan_run_id == run_id, Alert.direction == "short").order_by(Alert.rank).all()
    return {
        "long": [alert_to_dict(a) for a in longs],
        "short": [alert_to_dict(a) for a in shorts],
    }


def alert_to_dict(a: Alert):
    return {
        "id": a.id,
        "symbol": a.symbol,
        "exchange": a.exchange,
        "direction": a.direction,
        "rank": a.rank,
        "score": a.score,
        "reasons": a.reasons,
        "key_levels": a.key_levels,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }
