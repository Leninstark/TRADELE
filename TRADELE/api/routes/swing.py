"""Swing trading tab scans."""
from fastapi import APIRouter, Depends, HTTPException, Query

from TRADELE.db.session import get_db
from TRADELE.filters.swing_definitions import SWING_TABS, TAB_DASHBOARD
from TRADELE.services.swing_scan_store import get_tab_results, run_and_save_tab_scan, run_refresh_all

router = APIRouter()


def _validate_tab(tab: str) -> str:
    if tab not in SWING_TABS:
        raise HTTPException(status_code=404, detail=f"Unknown swing tab: {tab}")
    return tab


@router.get("/{tab}/results")
def tab_results(tab: str, db=Depends(get_db)):
    """Latest saved scan results for a swing tab."""
    tab = _validate_tab(tab)
    return get_tab_results(db, tab)


@router.post("/{tab}/scan")
def tab_scan(
    tab: str,
    max_symbols: int = Query(400, ge=50, le=900),
    db=Depends(get_db),
):
    """Run scan for tab, store latest results, return them."""
    tab = _validate_tab(tab)

    if tab == TAB_DASHBOARD:
        result = run_refresh_all(db, max_symbols=max_symbols)
        if result.get("status") == "failed":
            from TRADELE.filters.swing_definitions import filter_tooltip_dict

            return {
                "tab": TAB_DASHBOARD,
                "filter": filter_tooltip_dict(TAB_DASHBOARD),
                "stocks": [],
                "meta": {
                    "error": "refresh_failed",
                    "message": result.get("message", "Universe scan failed."),
                    "steps": result.get("steps"),
                },
                "run": None,
            }
        dash = result.get("dashboard") or {}
        meta = dict(dash.get("meta") or {})
        meta["refresh_steps"] = result.get("steps")
        meta["refresh_status"] = result.get("status")
        if result.get("failed_steps"):
            meta["failed_steps"] = result.get("failed_steps")
        dash["meta"] = meta
        return dash

    if tab == "universe":
        return run_and_save_tab_scan(db, tab, max_symbols=max_symbols)
    return run_and_save_tab_scan(db, tab)
