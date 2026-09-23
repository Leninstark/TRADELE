"""Groww Trading API client and token refresh."""
from __future__ import annotations

import hashlib
import logging
import time
from typing import Any, Optional

import httpx

from TRADELE.config import settings

logger = logging.getLogger(__name__)

GROWW_BASE = "https://api.groww.in"
GROWW_TOKEN_URL = f"{GROWW_BASE}/v1/token/api/access"
GROWW_HOLDINGS_URL = f"{GROWW_BASE}/v1/holdings/user"
GROWW_POSITIONS_URL = f"{GROWW_BASE}/v1/positions/user"
GROWW_ORDERS_URL = f"{GROWW_BASE}/v1/order/list"
GROWW_ORDER_TRADES_URL = f"{GROWW_BASE}/v1/order/trades"
GROWW_CANDLES_URL = f"{GROWW_BASE}/v1/historical/candles"
GROWW_API_DOCS = "https://groww.in/trade-api/docs/curl"
GROWW_KEYS_PAGE = "https://groww.in/trade-api"


def groww_headers(access_token: str) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Authorization": f"Bearer {access_token}",
        "X-API-VERSION": "1.0",
    }


def generate_checksum(secret: str, timestamp: str) -> str:
    """SHA256(secret + timestamp) per Groww docs."""
    payload = f"{secret}{timestamp}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def refresh_access_token(api_key: str, api_secret: str) -> dict[str, Any]:
    """
    Exchange API key + secret for a daily access token (approval flow).
    Requires daily approval on Groww Cloud API Keys page.
    """
    timestamp = str(int(time.time()))
    checksum = generate_checksum(api_secret, timestamp)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    body = {
        "key_type": "approval",
        "checksum": checksum,
        "timestamp": timestamp,
    }
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(GROWW_TOKEN_URL, headers=headers, json=body)
        resp.raise_for_status()
        data = resp.json()

    # Response may be wrapped in status/payload or flat
    if isinstance(data, dict) and data.get("status") == "SUCCESS" and isinstance(data.get("payload"), dict):
        payload = data["payload"]
    elif isinstance(data, dict) and "token" in data:
        payload = data
    else:
        raise ValueError(f"Unexpected Groww token response: {data}")

    token = payload.get("token")
    if not token:
        raise ValueError("Groww did not return an access token")
    return {
        "access_token": token,
        "expiry": payload.get("expiry"),
        "token_ref_id": payload.get("tokenRefId"),
        "session_name": payload.get("sessionName"),
    }


def validate_access_token(access_token: str) -> bool:
    """Live check via holdings endpoint."""
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(GROWW_HOLDINGS_URL, headers=groww_headers(access_token))
            if resp.status_code == 401:
                return False
            resp.raise_for_status()
            data = resp.json()
            return data.get("status") == "SUCCESS" or resp.status_code == 200
    except Exception as e:
        logger.info("Groww token validation failed: %s", e)
        return False


def get_holdings(access_token: str) -> dict[str, Any]:
    with httpx.Client(timeout=20.0) as client:
        resp = client.get(GROWW_HOLDINGS_URL, headers=groww_headers(access_token))
        resp.raise_for_status()
        return resp.json()


def _unwrap_payload(data: dict[str, Any]) -> Any:
    if isinstance(data, dict) and data.get("status") == "SUCCESS" and "payload" in data:
        return data["payload"]
    return data


def get_orders(access_token: str, *, segment: str = "CASH", page: int = 0, page_size: int = 100) -> dict[str, Any]:
    with httpx.Client(timeout=20.0) as client:
        resp = client.get(
            GROWW_ORDERS_URL,
            headers=groww_headers(access_token),
            params={"segment": segment, "page": page, "page_size": page_size},
        )
        resp.raise_for_status()
        return resp.json()


def list_all_orders(access_token: str, *, segment: str = "CASH") -> list[dict[str, Any]]:
    """Paginated fetch of today's orders for a segment."""
    all_orders: list[dict[str, Any]] = []
    page = 0
    page_size = 100
    while True:
        data = get_orders(access_token, segment=segment, page=page, page_size=page_size)
        payload = _unwrap_payload(data)
        batch = []
        if isinstance(payload, dict):
            batch = payload.get("order_list") or []
        elif isinstance(payload, list):
            batch = payload
        if not batch:
            break
        all_orders.extend(batch)
        if len(batch) < page_size:
            break
        page += 1
    return all_orders


def get_order_trades(access_token: str, groww_order_id: str, *, segment: str = "CASH") -> list[dict[str, Any]]:
    with httpx.Client(timeout=20.0) as client:
        resp = client.get(
            f"{GROWW_ORDER_TRADES_URL}/{groww_order_id}",
            headers=groww_headers(access_token),
            params={"segment": segment},
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        payload = _unwrap_payload(resp.json())
        if isinstance(payload, dict):
            return payload.get("trade_list") or []
        return []


def get_positions(access_token: str) -> dict[str, Any]:
    with httpx.Client(timeout=20.0) as client:
        resp = client.get(GROWW_POSITIONS_URL, headers=groww_headers(access_token))
        resp.raise_for_status()
        return resp.json()


def get_positions_list(access_token: str) -> list[dict[str, Any]]:
    payload = _unwrap_payload(get_positions(access_token))
    if isinstance(payload, dict):
        return payload.get("positions") or []
    return []


def get_holdings_list(access_token: str) -> list[dict[str, Any]]:
    payload = _unwrap_payload(get_holdings(access_token))
    if isinstance(payload, dict):
        return payload.get("holdings") or []
    return []


def get_orders_legacy(access_token: str, *, segment: str = "CASH") -> dict[str, Any]:
    return get_orders(access_token, segment=segment)


def get_historical_candles(
    access_token: str,
    *,
    trading_symbol: str,
    exchange: str = "NSE",
    segment: str = "CASH",
    start_time: str,
    end_time: str,
    candle_interval: str = "1minute",
) -> list[dict[str, Any]]:
    """
    Groww backtesting candles.
    groww_symbol format: NSE-RELIANCE
    Returns list of {date, open, high, low, close, volume}.
    """
    groww_symbol = f"{exchange}-{trading_symbol}"
    with httpx.Client(timeout=45.0) as client:
        resp = client.get(
            GROWW_CANDLES_URL,
            headers=groww_headers(access_token),
            params={
                "exchange": exchange,
                "segment": segment,
                "groww_symbol": groww_symbol,
                "start_time": start_time,
                "end_time": end_time,
                "candle_interval": candle_interval,
            },
        )
        resp.raise_for_status()
        payload = _unwrap_payload(resp.json())

    candles_raw = []
    if isinstance(payload, dict):
        candles_raw = payload.get("candles") or payload.get("candle") or []
    elif isinstance(payload, list):
        candles_raw = payload

    out: list[dict[str, Any]] = []
    for c in candles_raw:
        if isinstance(c, dict):
            ts = c.get("timestamp") or c.get("date") or c.get("time")
            out.append(
                {
                    "date": str(ts),
                    "open": float(c.get("open") or 0),
                    "high": float(c.get("high") or 0),
                    "low": float(c.get("low") or 0),
                    "close": float(c.get("close") or 0),
                    "volume": float(c.get("volume") or 0),
                }
            )
        elif isinstance(c, (list, tuple)) and len(c) >= 5:
            # [timestamp, open, high, low, close, volume?]
            out.append(
                {
                    "date": str(c[0]),
                    "open": float(c[1]),
                    "high": float(c[2]),
                    "low": float(c[3]),
                    "close": float(c[4]),
                    "volume": float(c[5]) if len(c) > 5 else 0,
                }
            )
    return out

