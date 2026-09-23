"""Trigger scan manually and list scan runs."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from TRADELE.db.session import get_db
from TRADELE.db.models import ScanRun
from TRADELE.scheduler.jobs import run_eod_scan, run_groww_eod_sync, run_morning_alert

router = APIRouter()


@router.post("/eod")
def trigger_eod_scan():
    """Run EOD scan now (same logic as scheduled 4 PM)."""
    run_eod_scan()
    return {"status": "triggered", "job": "eod"}


@router.post("/morning")
def trigger_morning_alert():
    """Run morning alert now (same as 9:25 AM)."""
    run_morning_alert()
    return {"status": "triggered", "job": "morning"}


@router.post("/groww-eod")
def trigger_groww_eod_sync():
    """Run Groww MyTrade sync now (same as scheduled post-market job)."""
    run_groww_eod_sync()
    return {"status": "triggered", "job": "groww_eod_sync"}


@router.get("/runs")
def list_runs(
    run_type: str | None = None,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    """List recent scan runs (eod / pre_market)."""
    q = db.query(ScanRun).order_by(ScanRun.started_at.desc())
    if run_type in ("eod", "pre_market"):
        q = q.filter(ScanRun.run_type == run_type)
    runs = q.limit(limit).all()
    return [
        {
            "id": r.id,
            "run_type": r.run_type,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "status": r.status,
            "error_message": r.error_message,
        }
        for r in runs
    ]
