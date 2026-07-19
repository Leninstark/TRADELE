"""Screener.in API via Apify (https://apify.com/shashwattrivedi/screener-in)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from TRADELE.services.screener_service import run_screener_query

router = APIRouter()


@router.get("")
def screener_run(
    mode: str = Query("runQuery", description="runQuery or getstockdetails"),
    query_string: Optional[str] = Query(
        None,
        description="Screener query (e.g. 'Market Capitalization > 50000 AND Price to Earning < 20'). Used when mode=runQuery.",
    ),
    url: Optional[str] = Query(
        None,
        description="Company page URL (e.g. https://www.screener.in/company/RELIANCE/). Used when mode=getstockdetails.",
    ),
):
    """
    Run Screener.in via Apify. Requires APIFY_API_TOKEN in .env.
    - mode=runQuery: returns list of stocks matching query_string (default: Market Cap > 1000).
    - mode=getstockdetails: returns detailed company data for the given screener.in company url.
    """
    if mode not in ("runQuery", "getstockdetails"):
        raise HTTPException(400, "mode must be runQuery or getstockdetails")
    if mode == "getstockdetails" and not url:
        raise HTTPException(400, "url is required when mode=getstockdetails")
    try:
        data = run_screener_query(
            query_string=query_string,
            mode=mode,
            url=url,
        )
        return {"mode": mode, "count": len(data), "data": data}
    except Exception as e:
        raise HTTPException(502, f"Screener.in / Apify error: {e!s}")
