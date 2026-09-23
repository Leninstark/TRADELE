"""Zerodha Kite Connect — status, save access token to DB, OAuth helpers."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from TRADELE.config import settings
from TRADELE.db.session import get_db
from TRADELE.services.zerodha_token_store import (
    check_token_status,
    save_access_token,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class TokenPayload(BaseModel):
    access_token: str = Field(..., min_length=8)
    username: str = Field(default="leninstark", min_length=1)


@router.get("/login-url")
def get_login_url():
    """Return Kite Connect OAuth login URL (open in a new tab)."""
    from TRADELE.services.zerodha_client import make_kite

    if not settings.kite_api_key:
        raise HTTPException(400, "KITE_API_KEY is not set in .env")
    kite = make_kite()
    return {
        "login_url": kite.login_url(),
        "message": "Open in a new tab, complete login, then paste access_token in TRADELE.",
    }


@router.get("/status")
def kite_status(
    username: str = Query("leninstark"),
    live_check: bool = Query(True),
    db: Session = Depends(get_db),
):
    """Check access token expiry / validity for the logged-in user."""
    result = check_token_status(db, username, live_check=live_check)
    return {
        **result,
        "api_key_set": bool(settings.kite_api_key),
        "api_secret_set": bool(settings.kite_api_secret),
        "login_url": (
            f"https://kite.zerodha.com/connect/login?api_key={settings.kite_api_key}&v=3"
            if settings.kite_api_key
            else None
        ),
    }


@router.post("/token")
def save_token(payload: TokenPayload, db: Session = Depends(get_db)):
    """Save access token entered by the user into the database."""
    try:
        row = save_access_token(db, payload.username, payload.access_token)
        # Optional live validation
        status = check_token_status(db, payload.username, live_check=True)
        if not status["connected"]:
            raise HTTPException(
                400,
                status.get("error") or "Token rejected by Zerodha. Paste a fresh access_token.",
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
        logger.exception("Save token failed")
        raise HTTPException(502, f"Could not save token: {e!s}") from e


@router.get("/session")
def set_session(
    request_token: str,
    username: str = Query("leninstark"),
    db: Session = Depends(get_db),
):
    """Exchange request_token → access_token and store in DB."""
    from TRADELE.services.zerodha_client import make_kite

    try:
        kite = make_kite()
        data = kite.generate_session(request_token, api_secret=settings.kite_api_secret)
        token = data["access_token"]
        row = save_access_token(db, username, token)
        return {
            "access_token": token,
            "saved": True,
            "expires_at": row.expires_at.isoformat(),
            "message": "Access token saved to database.",
        }
    except Exception as e:
        raise HTTPException(502, f"Kite session error: {e!s}") from e


@router.get("/callback", response_class=HTMLResponse)
def oauth_callback(
    request_token: str = Query(""),
    status: str = Query(""),
    db: Session = Depends(get_db),
):
    """OAuth redirect: exchange token, save to DB, show token to copy into TRADELE popup."""
    if status and status != "success":
        return HTMLResponse(f"<h2>Login failed</h2><p>status={status}</p>", status_code=400)
    if not request_token:
        return HTMLResponse("<h2>Missing request_token</h2>", status_code=400)
    try:
        from TRADELE.services.zerodha_client import make_kite

        kite = make_kite()
        data = kite.generate_session(request_token, api_secret=settings.kite_api_secret)
        token = data["access_token"]
        save_access_token(db, "leninstark", token)
        return HTMLResponse(
            f"""
            <html><body style="font-family:system-ui;padding:40px;max-width:560px;margin:auto">
              <h2 style="color:#00b386">Zerodha connected</h2>
              <p>Token saved to TRADELE database. You can close this tab.</p>
              <p>Or copy the access token into the Connect popup:</p>
              <textarea readonly style="width:100%;height:80px;font-size:13px">{token}</textarea>
              <p><a href="http://localhost:5173/explore">Back to TRADELE</a></p>
            </body></html>
            """
        )
    except Exception as e:
        logger.exception("Kite callback failed")
        return HTMLResponse(f"<h2>Token exchange failed</h2><pre>{e!s}</pre>", status_code=502)
