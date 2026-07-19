"""Technical indicators API."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from TRADELE.db.session import get_db
from TRADELE.engines.indicators.calculator import compute_indicators
from TRADELE.services.zerodha_client import get_client

router = APIRouter()


@router.get("/{symbol}")
def get_indicators(
    symbol: str,
    exchange: str = "NSE",
    lookback_days: int = Query(60, le=365),
    db: Session = Depends(get_db),
):
    """Compute all technical indicators for a symbol."""
    from datetime import date, timedelta

    client = get_client()
    candles = client.get_historical(
        symbol=symbol.upper(),
        exchange=exchange,
        interval="day",
        from_date=date.today() - timedelta(days=lookback_days),
        to_date=date.today(),
        db=db,
        use_cache=True,
    )
    if not candles:
        return {"error": f"No data for {exchange}:{symbol}"}

    indicators = compute_indicators(symbol.upper(), candles)
    return {"symbol": symbol.upper(), "exchange": exchange, "indicators": indicators}
