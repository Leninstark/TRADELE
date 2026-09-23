"""F&O index study APIs — NIFTY / BANKNIFTY / SENSEX daily analytics."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from TRADELE.services import index_analytics as ia
from TRADELE.services.llm_agent import (
    call_llm_auto,
    last_llm_error,
    last_llm_provider,
    llm_is_configured,
)

router = APIRouter()


class ExplainRequest(BaseModel):
    index: str = Field(..., description="NIFTY | BANKNIFTY | SENSEX")
    topic: str = Field(..., description="kpi:avg_range_pts | pattern:gap_down_… | note:… | extreme:…")
    title: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)


@router.get("/indices")
def get_indices() -> dict[str, Any]:
    return {"indices": ia.list_indices()}


@router.get("/index/{index_id}")
def get_index_analytics(index_id: str) -> dict[str, Any]:
    key = index_id.upper().strip()
    if key not in ia.INDEX_META:
        raise HTTPException(404, f"Unknown index. Use one of: {', '.join(ia.INDEX_META)}")
    try:
        return ia.analyze_index(key)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        raise HTTPException(500, f"Analytics failed: {e}") from e


@router.post("/explain")
def explain_metric(body: ExplainRequest) -> dict[str, Any]:
    key = body.index.upper().strip()
    if key not in ia.INDEX_META:
        raise HTTPException(404, f"Unknown index. Use one of: {', '.join(ia.INDEX_META)}")

    payload = dict(body.payload or {})
    if body.title:
        payload.setdefault("title", body.title)

    slice_ctx: dict[str, Any] = {"index": key}
    try:
        full = ia.analyze_index(key)
        slice_ctx.update(
            {
                "from_date": full.get("from_date"),
                "to_date": full.get("to_date"),
                "sessions": full.get("sessions"),
                "period_change_pct": full.get("period_change_pct"),
                "pattern_counts": full.get("pattern_counts"),
                "streaks": full.get("streaks"),
            }
        )
    except Exception:
        pass

    prompt = ia.build_explain_prompt(key, body.topic, payload, slice_ctx)
    text: Optional[str] = None
    source = "rules"
    provider = None
    error = None

    if llm_is_configured():
        text = call_llm_auto(prompt)
        provider = last_llm_provider()
        if text:
            source = "llm"
        else:
            error = last_llm_error()
            text = ia.rule_based_explain(key, body.topic, payload)
    else:
        text = ia.rule_based_explain(key, body.topic, payload)
        error = "LLM not configured — showing rule-based take"

    return {
        "index": key,
        "topic": body.topic,
        "title": body.title or payload.get("title") or body.topic,
        "explanation": text,
        "source": source,
        "provider": provider,
        "error": error,
    }
