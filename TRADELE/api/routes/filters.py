"""Stock filter API routes."""
from fastapi import APIRouter, HTTPException, Query

from TRADELE.filters.definitions import FILTER_PHASE_1, filter_to_dict, get_filter
from TRADELE.filters.phase1_runner import run_phase1_filter

router = APIRouter()


@router.get("/definitions")
def list_filters():
    return [filter_to_dict(FILTER_PHASE_1)]


@router.get("/definitions/{filter_id}")
def get_filter_definition(filter_id: str):
    f = get_filter(filter_id)
    if not f:
        raise HTTPException(status_code=404, detail="Filter not found")
    return filter_to_dict(f)


@router.post("/phase1/run")
def run_phase1(max_symbols: int = Query(300, ge=50, le=900)):
    """Run Phase 1 filter against Zerodha + NSE (or Screener.in when configured)."""
    return run_phase1_filter(max_symbols=max_symbols)
