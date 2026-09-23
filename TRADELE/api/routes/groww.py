"""Groww Trading API — status, save token, refresh via API key + secret."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from TRADELE.config import settings
from TRADELE.db.session import get_db
from TRADELE.services.groww_client import GROWW_API_DOCS, GROWW_KEYS_PAGE
from TRADELE.services.groww_token_store import (
    check_token_status,
    save_access_token,
    save_api_credentials,
    try_refresh_token,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class GrowwTokenPayload(BaseModel):
    access_token: str = Field(..., min_length=20)
    username: str = Field(default="leninstark", min_length=1)


class GrowwCredentialsPayload(BaseModel):
    api_key: str = Field(..., min_length=8)
    api_secret: str = Field(..., min_length=8)
    username: str = Field(default="leninstark", min_length=1)


@router.get("/login-info")
def groww_login_info():
    """Where to generate a Groww access token (manual daily flow)."""
    return {
        "docs_url": GROWW_API_DOCS,
        "keys_page_url": GROWW_KEYS_PAGE,
        "message": (
            "Generate an Access Token on Groww → Profile → Settings → Trading APIs. "
            "Tokens reset daily at 6 AM IST."
        ),
    }


@router.get("/status")
def groww_status(
    username: str = Query("leninstark"),
    live_check: bool = Query(True),
    db: Session = Depends(get_db),
):
    result = check_token_status(db, username, live_check=live_check)
    return {
        **result,
        "api_key_set": bool(settings.groww_api_key),
        "api_secret_set": bool(settings.groww_api_secret),
        "keys_page_url": GROWW_KEYS_PAGE,
    }


@router.post("/token")
def save_token(payload: GrowwTokenPayload, db: Session = Depends(get_db)):
    try:
        row = save_access_token(db, payload.username, payload.access_token)
        status = check_token_status(db, payload.username, live_check=True)
        if not status["connected"]:
            raise HTTPException(
                400,
                status.get("error") or "Token rejected by Groww. Paste a fresh access token.",
            )
        return {
            "saved": True,
            "connected": True,
            "status": "connected",
            "message": "Connected",
            "expires_at": row.expires_at.isoformat(),
            "username": payload.username.strip().lower(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Save Groww token failed")
        raise HTTPException(502, f"Could not save token: {e!s}") from e


@router.post("/credentials")
def save_credentials(payload: GrowwCredentialsPayload, db: Session = Depends(get_db)):
    """Store API key + secret for daily auto-refresh (approval flow)."""
    try:
        save_api_credentials(db, payload.username, payload.api_key, payload.api_secret)
    except Exception as e:
        logger.exception("Save Groww credentials failed")
        msg = str(e)
        if "StringDataRightTruncation" in msg or "value too long" in msg.lower():
            raise HTTPException(
                400,
                "Groww API key is too long for the database column. Restart the backend to apply the schema fix.",
            ) from e
        raise HTTPException(502, f"Could not save credentials: {e!s}") from e
    return {"saved": True, "message": "API credentials saved. Use Refresh to generate today's token."}


@router.post("/refresh")
def refresh_token(username: str = Query("leninstark"), db: Session = Depends(get_db)):
    """Refresh access token using DB or .env API key + secret."""
    username = username.strip().lower()
    try:
        token = try_refresh_token(db, username)
    except Exception as e:
        logger.warning("Groww refresh failed for %s: %s", username, e)
        raise HTTPException(502, f"Groww refresh failed: {e!s}") from e
    if not token:
        raise HTTPException(
            400,
            "No Groww API key/secret in .env (GROWW_API_KEY / GROWW_API_SECRET) or Connect form.",
        )
    status = check_token_status(db, username, live_check=True)
    return status
