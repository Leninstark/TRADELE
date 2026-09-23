"""Persist and validate Groww access tokens in Postgres."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from TRADELE.config import settings
from TRADELE.db.models import GrowwToken
from TRADELE.services.groww_client import refresh_access_token, validate_access_token
from TRADELE.services.zerodha_token_store import kite_token_expiry

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")


def _now_naive_ist() -> datetime:
    return datetime.now(IST).replace(tzinfo=None)


def save_access_token(
    db: Session,
    username: str,
    access_token: str,
    *,
    api_key: Optional[str] = None,
    api_secret: Optional[str] = None,
) -> GrowwToken:
    username = (username or "default").strip().lower()
    token = access_token.strip()
    expires_at = kite_token_expiry()  # same 6 AM IST rule as Zerodha
    row = db.query(GrowwToken).filter(GrowwToken.username == username).first()
    if row:
        row.access_token = token
        row.created_at = _now_naive_ist()
        row.expires_at = expires_at
        row.is_valid = True
        if api_key:
            row.api_key = api_key
        if api_secret:
            row.api_secret = api_secret
    else:
        row = GrowwToken(
            username=username,
            access_token=token,
            api_key=api_key,
            api_secret=api_secret,
            created_at=_now_naive_ist(),
            expires_at=expires_at,
            is_valid=True,
        )
        db.add(row)
    db.commit()
    db.refresh(row)
    settings.groww_access_token = token
    return row


def save_api_credentials(db: Session, username: str, api_key: str, api_secret: str) -> GrowwToken:
    username = (username or "default").strip().lower()
    row = db.query(GrowwToken).filter(GrowwToken.username == username).first()
    if row:
        row.api_key = api_key.strip()
        row.api_secret = api_secret.strip()
    else:
        row = GrowwToken(
            username=username,
            access_token="",
            api_key=api_key.strip(),
            api_secret=api_secret.strip(),
            created_at=_now_naive_ist(),
            expires_at=kite_token_expiry(),
            is_valid=False,
        )
        db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_token_row(db: Session, username: str) -> Optional[GrowwToken]:
    username = (username or "default").strip().lower()
    return db.query(GrowwToken).filter(GrowwToken.username == username).first()


def get_active_access_token(db: Session, username: Optional[str] = None) -> Optional[str]:
    now = _now_naive_ist()
    if username:
        row = get_token_row(db, username)
        if row and row.is_valid and row.expires_at > now and row.access_token:
            return row.access_token
        return None
    row = (
        db.query(GrowwToken)
        .filter(GrowwToken.is_valid.is_(True), GrowwToken.expires_at > now)
        .order_by(GrowwToken.created_at.desc())
        .first()
    )
    return row.access_token if row else None


def mark_invalid(db: Session, username: str) -> None:
    row = get_token_row(db, username)
    if row:
        row.is_valid = False
        db.commit()


def resolve_api_credentials(db: Session, username: str) -> tuple[Optional[str], Optional[str]]:
    """Prefer DB-stored key/secret; fall back to GROWW_API_KEY / GROWW_API_SECRET from .env."""
    row = get_token_row(db, username)
    if row and row.api_key and row.api_secret:
        return row.api_key, row.api_secret
    if settings.groww_api_key and settings.groww_api_secret:
        return settings.groww_api_key, settings.groww_api_secret
    return None, None


def has_refresh_credentials(db: Session, username: str) -> bool:
    key, secret = resolve_api_credentials(db, username)
    return bool(key and secret)


def try_refresh_token(db: Session, username: str) -> Optional[str]:
    """Refresh using DB or .env API key + secret.

    Raises on API/network failure when credentials exist so callers can surface
    the real error instead of a misleading "no credentials" message.
    """
    api_key, api_secret = resolve_api_credentials(db, username)
    if not api_key or not api_secret:
        return None
    result = refresh_access_token(api_key, api_secret)
    save_access_token(
        db,
        username,
        result["access_token"],
        api_key=api_key,
        api_secret=api_secret,
    )
    return result["access_token"]


def check_token_status(db: Session, username: str, *, live_check: bool = True) -> dict[str, Any]:
    username = (username or "default").strip().lower()
    row = get_token_row(db, username)
    now = _now_naive_ist()
    can_refresh = has_refresh_credentials(db, username)

    if not row or not row.access_token:
        return {
            "connected": False,
            "status": "not_connected",
            "message": "Not connected",
            "expires_at": None,
            "username": username,
            "can_refresh": can_refresh,
        }

    expired_by_time = row.expires_at <= now or not row.is_valid
    if expired_by_time:
        try:
            refreshed = try_refresh_token(db, username)
        except Exception as e:
            logger.warning("Groww token refresh failed for %s: %s", username, e)
            refreshed = None
        if refreshed:
            row = get_token_row(db, username)
        else:
            if row:
                row.is_valid = False
                db.commit()
            return {
                "connected": False,
                "status": "expired",
                "message": "Token expired — click Refresh (uses API key/secret from .env or Connect)",
                "expires_at": row.expires_at.isoformat() if row and row.expires_at else None,
                "username": username,
                "can_refresh": can_refresh,
            }

    if live_check:
        if not validate_access_token(row.access_token):
            try:
                refreshed = try_refresh_token(db, username)
            except Exception as e:
                logger.warning("Groww token refresh failed for %s: %s", username, e)
                refreshed = None
            if refreshed and validate_access_token(refreshed):
                row = get_token_row(db, username)
            else:
                row.is_valid = False
                db.commit()
                return {
                    "connected": False,
                    "status": "not_connected",
                    "message": "Not connected",
                    "expires_at": row.expires_at.isoformat() if row.expires_at else None,
                    "username": username,
                    "can_refresh": can_refresh,
                }

    return {
        "connected": True,
        "status": "connected",
        "message": "Connected",
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "username": username,
        "can_refresh": can_refresh,
    }
