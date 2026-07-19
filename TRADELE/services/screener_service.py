"""Screener.in integration via Apify API (https://apify.com/shashwattrivedi/screener-in)."""
from __future__ import annotations

import logging
from typing import Any, Optional

from TRADELE.config import settings

logger = logging.getLogger(__name__)

ACTOR_ID = "shashwattrivedi/screener-in"


def run_screener_query(
    query_string: Optional[str] = None,
    mode: str = "runQuery",
    url: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
) -> list[dict[str, Any]]:
    """
    Run Screener.in Apify actor.
    - mode=runQuery: pass query_string (e.g. "Market Capitalization > 50000 AND Price to Earning < 20")
    - mode=getstockdetails: pass url (e.g. "https://www.screener.in/company/RELIANCE/")
    Returns list of items from the actor's default dataset.
    """
    if not settings.apify_api_token:
        logger.warning("APIFY_API_TOKEN not set; cannot call Screener.in")
        return []

    try:
        from apify_client import ApifyClient
    except ImportError:
        logger.warning("apify-client not installed; pip install apify-client")
        return []

    run_input: dict[str, Any] = {"mode": mode}
    if mode == "runQuery":
        run_input["queryString"] = query_string or "Market Capitalization > 1000"
        if username:
            run_input["username"] = username
        if password:
            run_input["password"] = password
    elif mode == "getstockdetails" and url:
        run_input["url"] = url
    else:
        logger.warning("Screener: invalid mode or missing url/queryString")
        return []

    try:
        client = ApifyClient(settings.apify_api_token)
        run = client.actor(ACTOR_ID).call(run_input=run_input)
        out = []
        for item in client.dataset(run["defaultDatasetId"]).iterate_items():
            out.append(item)
        return out
    except Exception as e:
        err = str(e)
        if "approvePermissions" in err or "Forbidden" in type(e).__name__:
            logger.warning("Screener.in Apify not authorized: %s", err)
        else:
            logger.exception("Screener.in Apify call failed: %s", e)
        return []
