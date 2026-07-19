"""NSE equity universe with penny/small-cap filter."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from TRADELE.config import settings
from TRADELE.services.zerodha_client import ZerodhaClient

logger = logging.getLogger(__name__)

# NIFTY 500 symbols - fallback if we don't have Kite; user can replace with full list
# In production, load from Kite instruments() filtered by segment EQ and optional list
NIFTY500_SAMPLE = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "HINDUNILVR", "SBIN",
    "BHARTIARTL", "ITC", "KOTAKBANK", "LT", "AXISBANK", "ASIANPAINT", "MARUTI",
    "BAJFINANCE", "WIPRO", "HCLTECH", "TITAN", "ULTRACEMCO", "SUNPHARMA",
]


def get_tradeable_equity_symbols(
    client: Optional[ZerodhaClient] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    exclude_small_cap: Optional[bool] = None,
    nifty_500_only: Optional[bool] = None,
) -> list[str]:
    """
    Return NSE EQ symbols after applying filters.
    Uses Kite instruments() when client is provided; else static NIFTY 500 sample.
    """
    min_price = min_price if min_price is not None else settings.min_price
    max_price = max_price if max_price is not None else settings.max_price
    exclude_small_cap = exclude_small_cap if exclude_small_cap is not None else settings.exclude_small_cap
    nifty_500_only = nifty_500_only if nifty_500_only is not None else settings.nifty_500_only

    symbols: list[str] = []
    if client and not (client._token or settings.kite_access_token):
        logger.info("No Kite access token — using sample universe (%d symbols)", len(NIFTY500_SAMPLE))
        return list(NIFTY500_SAMPLE)

    if client:
        try:
            instruments = client.kite.instruments()
            for i in instruments:
                if i.get("exchange") != "NSE" or i.get("segment") != "NSE":
                    continue
                if i.get("segment", "").upper() == "NFO":
                    continue
                name = i.get("tradingsymbol") or i.get("name", "")
                if not name or "-" in name or name.endswith("ETF"):
                    continue
                # Optional: filter by instrument_type == "EQ" if available
                symbols.append(name)
        except Exception as e:
            logger.warning("Kite instruments failed, using static list: %s", e)
            symbols = list(NIFTY500_SAMPLE)
    else:
        symbols = list(NIFTY500_SAMPLE)

    # Load NIFTY 500 list from file if present (user can drop nifty500.txt)
    nifty500_path = Path(__file__).resolve().parent.parent.parent / "data" / "nifty500.txt"
    if nifty_500_only and nifty500_path.exists():
        try:
            n500 = set(s.strip() for s in nifty500_path.read_text().splitlines() if s.strip())
            symbols = [s for s in symbols if s in n500]
        except Exception as e:
            logger.warning("Could not load nifty500.txt: %s", e)

    # Penny / price filter (we don't have live price here; applied later in scoring with EOD close)
    # So we return all symbols and filter in scoring by last close
    return symbols


def load_nifty500_from_kite(client: ZerodhaClient, save_path: Optional[Path] = None) -> list[str]:
    """Fetch NSE EQ symbols from Kite and optionally save to data/nifty500.txt."""
    instruments = client.kite.instruments()
    symbols = []
    for i in instruments:
        if i.get("exchange") != "NSE":
            continue
        seg = (i.get("segment") or "").upper()
        if "NSE" not in seg or "FUT" in seg or "OPT" in seg:
            continue
        name = i.get("tradingsymbol") or ""
        if name and "-" not in name and not name.endswith("ETF"):
            symbols.append(name)
    symbols = sorted(set(symbols))
    if save_path:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_text("\n".join(symbols), encoding="utf-8")
    return symbols
