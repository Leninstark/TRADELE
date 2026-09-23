"""Orchestrate Trader DNA: sync fills → stats → narrative → cache."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from TRADELE.db.models import JournalFill, TraderDnaReport
from TRADELE.services.journal_ingest import get_fills_cutoff, sync_groww_into_fills
from TRADELE.services.trader_dna_engine import build_trader_dna_stats
from TRADELE.services.trader_dna_narrative import generate_trader_dna_narrative

logger = logging.getLogger(__name__)


def _latest_report(db: Session, username: str) -> Optional[TraderDnaReport]:
    return (
        db.query(TraderDnaReport)
        .filter(TraderDnaReport.username == username)
        .order_by(TraderDnaReport.generated_at.desc())
        .first()
    )


def report_to_dict(row: TraderDnaReport) -> dict[str, Any]:
    return {
        "id": row.id,
        "username": row.username,
        "generated_at": row.generated_at.isoformat() if row.generated_at else None,
        "fills_through": row.fills_through.isoformat() if row.fills_through else None,
        "fill_count": row.fill_count,
        "stats": row.stats or {},
        "narrative": row.narrative or {},
        "llm_provider": row.llm_provider,
        "llm_used": bool(row.llm_used),
        "status": row.status,
        "error_message": row.error_message,
        "from_cache": False,
    }


def get_trader_dna(db: Session, username: str) -> Optional[dict[str, Any]]:
    username = username.strip().lower()
    row = _latest_report(db, username)
    if not row:
        return None
    out = report_to_dict(row)
    out["from_cache"] = True
    return out


def run_trader_dna(
    db: Session,
    *,
    username: str,
    force: bool = False,
) -> dict[str, Any]:
    username = username.strip().lower()
    groww_sync = sync_groww_into_fills(db, username)

    fills = (
        db.query(JournalFill)
        .filter(JournalFill.username == username)
        .order_by(JournalFill.trade_datetime.asc(), JournalFill.id.asc())
        .all()
    )
    if not fills:
        return {
            "ok": False,
            "error": "no_fills",
            "message": "No journal fills yet. Upload an Excel/CSV trade history and/or sync Groww.",
            "groww_sync": groww_sync,
        }

    fills_through = max(f.trade_datetime for f in fills)
    cached = _latest_report(db, username)
    if (
        not force
        and cached
        and cached.status == "success"
        and cached.fills_through
        and cached.fills_through >= fills_through
        and cached.stats
    ):
        out = report_to_dict(cached)
        out["from_cache"] = True
        out["ok"] = True
        out["groww_sync"] = groww_sync
        out["message"] = "Reused cached DNA — no fills newer than last report. Pass force=true to rebuild."
        return out

    try:
        stats = build_trader_dna_stats(fills)
        narrative = generate_trader_dna_narrative(stats)
        row = TraderDnaReport(
            username=username,
            generated_at=datetime.utcnow(),
            fills_through=fills_through,
            fill_count=len(fills),
            stats=stats,
            narrative=narrative,
            llm_provider=narrative.get("llm_provider"),
            llm_used=bool(narrative.get("llm_used")),
            status="success",
            error_message=None,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        out = report_to_dict(row)
        out["ok"] = True
        out["from_cache"] = False
        out["groww_sync"] = groww_sync
        out["cutoff"] = (get_fills_cutoff(db, username) or fills_through).isoformat()
        return out
    except Exception as e:
        logger.exception("Trader DNA failed")
        db.rollback()
        fail = TraderDnaReport(
            username=username,
            generated_at=datetime.utcnow(),
            fills_through=fills_through,
            fill_count=len(fills),
            stats={},
            narrative={},
            status="failed",
            error_message=str(e)[:500],
        )
        db.add(fail)
        db.commit()
        return {
            "ok": False,
            "error": "dna_failed",
            "message": str(e),
            "groww_sync": groww_sync,
        }
