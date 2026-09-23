"""Persist and validate Zerodha access tokens in Postgres."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from TRADELE.config import settings
from TRADELE.db.models import ZerodhaToken

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")


def kite_token_expiry(now: Optional[datetime] = None) -> datetime:
    """Zerodha access tokens expire at 6:00 AM IST (same day if before 6 AM, else next day)."""
    now_ist = now or datetime.now(IST)
    if now_ist.tzinfo is None:
        now_ist = now_ist.replace(tzinfo=IST)
    else:
        now_ist = now_ist.astimezone(IST)
    six_am = now_ist.replace(hour=6, minute=0, second=0, microsecond=0)
    expiry = six_am if now_ist < six_am else six_am + timedelta(days=1)
    return expiry.replace(tzinfo=None)  # store naive UTC-comparable IST wall time


def _now_naive_ist() -> datetime:
    return datetime.now(IST).replace(tzinfo=None)


def save_access_token(db: Session, username: str, access_token: str) -> ZerodhaToken:
    username = (username or "default").strip().lower()
    token = access_token.strip()
    expires_at = kite_token_expiry()
    row = db.query(ZerodhaToken).filter(ZerodhaToken.username == username).first()
    if row:
        row.access_token = token
        row.created_at = _now_naive_ist()
        row.expires_at = expires_at
        row.is_valid = True
    else:
        row = ZerodhaToken(
            username=username,
            access_token=token,
            created_at=_now_naive_ist(),
            expires_at=expires_at,
            is_valid=True,
        )
        db.add(row)
    db.commit()
    db.refresh(row)

    # Keep settings + live client in sync for this process
    settings.kite_access_token = token
    try:
        from TRADELE.services.zerodha_client import get_client
        get_client().set_access_token(token)
    except Exception as e:
        logger.warning("Could not refresh live client: %s", e)

    return row


def get_token_row(db: Session, username: str) -> Optional[ZerodhaToken]:
    username = (username or "default").strip().lower()
    return db.query(ZerodhaToken).filter(ZerodhaToken.username == username).first()


def get_active_access_token(db: Session, username: Optional[str] = None) -> Optional[str]:
    """Return a non-expired token for user, or any latest valid token."""
    now = _now_naive_ist()
    if username:
        row = get_token_row(db, username)
        if row and row.is_valid and row.expires_at > now and row.access_token:
            return row.access_token
        return None
    row = (
        db.query(ZerodhaToken)
        .filter(ZerodhaToken.is_valid.is_(True), ZerodhaToken.expires_at > now)
        .order_by(ZerodhaToken.created_at.desc())
        .first()
    )
    return row.access_token if row else None


def mark_invalid(db: Session, username: str) -> None:
    row = get_token_row(db, username)
    if row:
        row.is_valid = False
        db.commit()


def check_token_status(db: Session, username: str, *, live_check: bool = True) -> dict[str, Any]:
    """
    Check whether the user's Zerodha access token is still valid.
    Uses expires_at and optionally a live Kite profile call.
    """
    username = (username or "default").strip().lower()
    row = get_token_row(db, username)
    now = _now_naive_ist()

    if not row or not row.access_token:
        return {
            "connected": False,
            "status": "not_connected",
            "message": "Not connected",
            "expires_at": None,
            "username": username,
        }

    expired_by_time = row.expires_at <= now or not row.is_valid
    if expired_by_time:
        row.is_valid = False
        db.commit()
        return {
            "connected": False,
            "status": "not_connected",
            "message": "Not connected",
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            "username": username,
        }

    if live_check:
        try:
            from TRADELE.services.zerodha_client import make_kite

            kite = make_kite(access_token=row.access_token)
            kite.profile()
        except Exception as e:
            logger.info("Zerodha live check failed for %s: %s", username, e)
            row.is_valid = False
            db.commit()
            return {
                "connected": False,
                "status": "not_connected",
                "message": "Not connected",
                "expires_at": row.expires_at.isoformat() if row.expires_at else None,
                "username": username,
                "error": str(e),
            }

    return {
        "connected": True,
        "status": "connected",
        "message": "Connected",
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "username": username,
    }
