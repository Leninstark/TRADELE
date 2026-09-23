"""
LangGraph Watchlist Analyst — stock-only, tool-grounded answers.

Nodes: guard → resolve → collect → index → rag → graph → synthesize → persist
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from TRADELE.engines.agents.stock_analyst import resolve_symbol
from TRADELE.services.llm_agent import call_llm_auto, last_llm_error, last_llm_provider
from TRADELE.services.watchlist_collectors import collect_facts, is_stock_question
from TRADELE.services.watchlist_knowledge import (
    graph_context,
    index_facts,
    rebuild_sector_graph,
    retrieve_chunks,
    sector_peers,
)
from TRADELE.services.watchlist_store import list_watchlist, save_analysis

logger = logging.getLogger(__name__)

try:
    from langgraph.graph import END, START, StateGraph
    from typing import TypedDict

    LANGGRAPH_OK = True
except ImportError:
    LANGGRAPH_OK = False
    StateGraph = None
    START = END = None
    TypedDict = dict  # type: ignore


BLOCKED_MSG = (
    "I'm the Tradele Analyst — I only discuss Indian stocks and trading "
    "(NSE technicals, levels, news, swing/intraday setups). "
    "Please rephrase your question about the selected stock or another NSE ticker."
)


class AnalystAnswer(BaseModel):
    summary_plain: str = ""
    summary_technical: str = ""
    technical_metrics: list[dict[str, str]] = Field(default_factory=list)
    blocks: list[dict[str, Any]] = Field(default_factory=list)
    verdict: str = "neutral"
    conviction: int = Field(default=50, ge=0, le=100)
    key_levels: dict[str, list] = Field(default_factory=lambda: {"support": [], "resistance": []})
    catalysts: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    citations: list[dict[str, str]] = Field(default_factory=list)
    blocked: bool = False
    engine: str = "rule_based"
    answered_question: str = ""


class WatchlistAgentState(TypedDict, total=False):
    username: str
    symbol: str
    company: str
    sector: str
    question: str
    force_refresh: bool
    allowed: bool
    facts: dict[str, Any]
    sources: list[str]
    rag_chunks: list[dict[str, Any]]
    graph_peers: list[dict[str, Any]]
    answer: dict[str, Any]
    analysis_id: int


def _extract_json(raw: str) -> str:
    raw = raw.strip()
    if "```json" in raw:
        return raw.split("```json")[1].split("```")[0].strip()
    if "```" in raw:
        return raw.split("```")[1].replace("json", "", 1).strip()
    return raw


def _fmt_num(v: Any, *, prefix: str = "", suffix: str = "", digits: int = 2) -> str:
    if v is None or v == "":
        return "—"
    try:
        n = float(v)
        if abs(n - round(n)) < 1e-9 and abs(n) >= 10:
            return f"{prefix}{int(round(n))}{suffix}"
        return f"{prefix}{n:.{digits}f}{suffix}"
    except (TypeError, ValueError):
        return str(v)


def technical_metrics_from_facts(facts: dict[str, Any]) -> list[dict[str, str]]:
    """Structured snapshot cards from collected technicals (not LLM prose)."""
    tech = facts.get("technical") or {}
    if not tech:
        return []

    close = tech.get("close")
    chg = tech.get("change_pct")
    rsi = tech.get("rsi")
    stoch = tech.get("stoch_rsi")
    macd = tech.get("macd")
    macd_sig = tech.get("macd_signal")
    macd_hist = tech.get("macd_hist")
    adx = tech.get("adx")
    ema20 = tech.get("ema_20")
    ema50 = tech.get("ema_50")
    ema200 = tech.get("ema_200")
    bb_u = tech.get("bb_upper")
    bb_l = tech.get("bb_lower")
    vol_ratio = tech.get("volume_ratio")
    avg_vol = tech.get("avg_daily_volume")

    def _rsi_hint(r: Any) -> str:
        try:
            x = float(r)
        except (TypeError, ValueError):
            return ""
        if x >= 70:
            return "overbought"
        if x <= 30:
            return "oversold"
        return "neutral"

    def _adx_hint(a: Any) -> str:
        try:
            x = float(a)
        except (TypeError, ValueError):
            return ""
        if x < 20:
            return "weak trend"
        if x >= 25:
            return "strong trend"
        return "moderate trend"

    macd_hint = ""
    try:
        if macd is not None and macd_sig is not None:
            macd_hint = (
                f"line {_fmt_num(macd)} vs signal {_fmt_num(macd_sig)} — "
                + ("bearish cross" if float(macd) < float(macd_sig) else "bullish bias")
            )
    except (TypeError, ValueError):
        macd_hint = ""

    rows: list[dict[str, str]] = [
        {
            "label": "Close",
            "value": _fmt_num(close, prefix="₹"),
            "hint": _fmt_num(chg, suffix="% today") if chg is not None else "",
        },
        {
            "label": "1M return",
            "value": _fmt_num(tech.get("return_1m_pct"), suffix="%"),
            "hint": "",
        },
        {
            "label": "3M / 6M / 1Y",
            "value": " / ".join(
                [
                    _fmt_num(tech.get("return_3m_pct"), suffix="%"),
                    _fmt_num(tech.get("return_6m_pct"), suffix="%"),
                    _fmt_num(tech.get("return_1y_pct"), suffix="%"),
                ]
            ),
            "hint": "",
        },
        {
            "label": "RSI",
            "value": _fmt_num(rsi, digits=1),
            "hint": _rsi_hint(rsi),
        },
        {
            "label": "Stoch RSI",
            "value": _fmt_num(stoch, digits=1),
            "hint": "short-term momentum" if stoch is not None else "",
        },
        {
            "label": "MACD hist",
            "value": _fmt_num(macd_hist, digits=3),
            "hint": macd_hint,
        },
        {
            "label": "ADX",
            "value": _fmt_num(adx, digits=1),
            "hint": _adx_hint(adx),
        },
        {
            "label": "EMA 20 / 50 / 200",
            "value": " / ".join(
                [_fmt_num(ema20, prefix="₹"), _fmt_num(ema50, prefix="₹"), _fmt_num(ema200, prefix="₹")]
            ),
            "hint": "aligned bull" if tech.get("ema_aligned_bull") else "",
        },
        {
            "label": "vs EMAs",
            "value": " / ".join(
                [
                    _fmt_num(tech.get("dist_ema_20_pct"), suffix="%"),
                    _fmt_num(tech.get("dist_ema_50_pct"), suffix="%"),
                    _fmt_num(tech.get("dist_ema_200_pct"), suffix="%"),
                ]
            ),
            "hint": "20 / 50 / 200",
        },
        {
            "label": "Bollinger",
            "value": f"{_fmt_num(bb_l, prefix='₹')} – {_fmt_num(bb_u, prefix='₹')}",
            "hint": "",
        },
        {
            "label": "Volume ratio",
            "value": _fmt_num(vol_ratio, digits=2) if vol_ratio is not None else "—",
            "hint": f"avg ~{_fmt_num(avg_vol, digits=0)}" if avg_vol else "vs 20d avg",
        },
        {
            "label": "52W range",
            "value": (
                f"{_fmt_num(tech.get('low_52w'), prefix='₹')} – "
                f"{_fmt_num(tech.get('high_52w'), prefix='₹')}"
            ),
            "hint": (
                f"{_fmt_num(tech.get('dist_52w_high_pct'), suffix='% from high')}"
                if tech.get("dist_52w_high_pct") is not None
                else ""
            ),
        },
    ]
    # Drop empty-looking rows (all em-dash)
    cleaned: list[dict[str, str]] = []
    for r in rows:
        if r["value"] in ("—", "— / — / —", "₹— – ₹—"):
            continue
        cleaned.append({k: (v or "") for k, v in r.items()})
    return cleaned


def node_guard(state: dict[str, Any]) -> dict[str, Any]:
    """Stock/trading questions only — selected symbol alone does not bypass."""
    q = (state.get("question") or "").strip()
    sym = (state.get("symbol") or "").strip()
    allowed = is_stock_question(q, symbol=sym)
    return {"allowed": allowed}


def node_blocked(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "answer": AnalystAnswer(
            summary_plain=BLOCKED_MSG,
            blocked=True,
            verdict="wait",
            conviction=0,
            engine="blocked",
            answered_question=(state.get("question") or "").strip(),
            technical_metrics=[],
        ).model_dump()
    }


def node_resolve(state: dict[str, Any]) -> dict[str, Any]:
    sym = (state.get("symbol") or "").strip().upper()
    if not sym:
        resolved, company = resolve_symbol(state.get("question") or "")
        sym = resolved or ""
    else:
        _, company = resolve_symbol(sym)
    return {"symbol": sym, "company": company or sym}


def node_collect(state: dict[str, Any], db: Session) -> dict[str, Any]:
    if not state.get("allowed") or not state.get("symbol"):
        return {}
    facts, sources = collect_facts(
        db,
        state["symbol"],
        company=state.get("company"),
        sector=state.get("sector"),
        force_refresh=bool(state.get("force_refresh")),
    )
    return {"facts": facts, "sources": sources}


def node_index(state: dict[str, Any], db: Session) -> dict[str, Any]:
    facts = state.get("facts") or {}
    if facts:
        index_facts(db, facts)
    return {}


def node_rag(state: dict[str, Any], db: Session) -> dict[str, Any]:
    sym = state.get("symbol") or ""
    if not sym:
        return {"rag_chunks": []}
    chunks = retrieve_chunks(db, sym, question=state.get("question") or "", limit=8)
    return {"rag_chunks": chunks}


def node_graph(state: dict[str, Any], db: Session) -> dict[str, Any]:
    sym = state.get("symbol") or ""
    if not sym:
        return {"graph_peers": []}
    wl = list_watchlist(db, state.get("username") or "leninstark")
    rebuild_sector_graph(db, [w["symbol"] for w in wl])
    peers = graph_context(db, sym, limit=6)
    if not peers:
        peers = [{"symbol": p, "relation": "same_sector", "metadata": {}} for p in sector_peers(sym)]
    return {"graph_peers": peers}


def _rule_answer(facts: dict[str, Any], sym: str, company: str, *, question: str = "", llm_error: str = "") -> dict[str, Any]:
    tech = facts.get("technical") or {}
    close = tech.get("close") or 0
    rsi = tech.get("rsi") or 50
    news = (facts.get("news") or {}).get("company") or []
    verdict = "neutral"
    conv = 50
    if tech.get("ema_aligned_bull"):
        verdict, conv = "bullish", 65
    elif rsi < 40:
        verdict, conv = "bearish", 55
    err = (llm_error or "LLM unavailable").strip()
    news_items = [str(n.get("title") or "")[:120] for n in news[:4] if n.get("title")]
    blocks: list[dict[str, Any]] = [
        {
            "type": "paragraph",
            "text": (
                f"{company} ({sym}) is around ₹{close} with RSI near {rsi}. "
                "Full AI answer unavailable right now — here is a concise fact-based read."
            ),
        }
    ]
    if news_items:
        blocks.append({"type": "bullets", "title": "Recent headlines", "items": news_items})
    blocks.append(
        {
            "type": "paragraph",
            "text": f"Note: {err[:180]}" if err else "Ask again in a moment for a fuller view.",
        }
    )
    return AnalystAnswer(
        summary_plain=blocks[0]["text"],
        blocks=blocks,
        catalysts=news_items[:3],
        risks=[
            "AI synthesis unavailable — treat this as a partial fact read only",
            "Confirm catalysts and flows from primary filings before acting",
        ],
        verdict=verdict,
        conviction=conv,
        engine="rule_based",
        answered_question=question or "",
    ).model_dump()


def node_synthesize(state: dict[str, Any]) -> dict[str, Any]:
    if not state.get("allowed"):
        return node_blocked(state)

    sym = state.get("symbol") or ""
    facts = state.get("facts") or {}
    question = (state.get("question") or "").strip()
    if not sym:
        return {
            "answer": AnalystAnswer(
                summary_plain="Could not resolve a valid NSE symbol. Select a watchlist stock or name the ticker.",
                verdict="wait",
                conviction=0,
                engine="error",
            ).model_dump()
        }

    company = state.get("company") or sym
    # Slim facts for the question — keep news/fundamentals/technicals available to LLM
    slim = {
        "symbol": facts.get("symbol") or sym,
        "company": facts.get("company") or company,
        "sector": facts.get("sector"),
        "technical": facts.get("technical") or {},
        "news": facts.get("news") or {},
        "fundamentals": facts.get("fundamentals") or {},
        "nse": facts.get("nse") or {},
        "db": facts.get("db") or {},
        "yahoo": facts.get("yahoo") or {},
    }
    fact_blob = json.dumps(slim, default=str)
    if len(fact_blob) > 14000:
        fact_blob = fact_blob[:14000] + "…[truncated]"

    prompt = f"""You are a professional Indian equity research analyst for NSE stocks.
Answer ONLY the USER QUESTION — simple, precise, professional tone.
Use FACTS below (news, fundamentals, technicals, DB). Never invent FII flows, contracts, or expansion news.
If data is missing, say so clearly (e.g. "No FII / futures / expansion news found in available sources").

Do NOT dump a full technical snapshot, support/resistance list, or source citations unless the user explicitly asks for levels/technicals.

Stock: {sym} ({company})
USER QUESTION: {question or "Give a concise 6-month view with any relevant news catalysts."}

FACTS:
{fact_blob}
{"WARNING: Zerodha rate-limited — do not invent numbers." if facts.get("rate_limited") else ""}

Extra context:
{json.dumps(state.get("rag_chunks") or [], default=str)[:2500]}

Respond with ONLY valid JSON (no markdown):
{{
  "summary_plain": "1-2 sentence direct answer to the question",
  "verdict": "bullish|bearish|neutral|wait",
  "conviction": 0-100,
  "blocked": false,
  "catalysts": ["2-4 concrete positives from news/facts — omit only if none exist"],
  "risks": ["2-4 concrete risks / unknowns — always include when giving an outlook"],
  "blocks": [
    {{"type": "paragraph", "text": "..."}},
    {{"type": "bullets", "title": "optional title", "items": ["..."]}},
    {{"type": "table", "title": "optional", "columns": ["Col A", "Col B"], "rows": [["a", "b"]]}},
    {{"type": "kv", "title": "optional", "items": [{{"label": "FII", "value": "Not in sources"}}]}},
    {{"type": "bars", "title": "optional returns", "items": [{{"label": "1M", "value": -5.0}}, {{"label": "3M", "value": 12.0}}]}}
  ]
}}

Choose block types that best fit the question (paragraph + bullets for news; table/kv for comparisons; bars only for numeric series from FACTS).
For outlook / investment / news questions, always fill catalysts and risks from FACTS when available.
Keep it tight — typically 2-4 blocks. No filler. No technical dump, support/resistance list, or source citations unless the user asks for levels/technicals.
"""
    raw = call_llm_auto(prompt)
    if not raw:
        return {
            "answer": _rule_answer(
                facts,
                sym,
                company,
                question=question,
                llm_error=last_llm_error() or "all providers failed",
            )
        }

    try:
        data = json.loads(_extract_json(raw))
        if data.get("blocked"):
            return node_blocked(state)
        # Drop forced technical dump fields from older schema if model still emits them
        data.pop("technical_metrics", None)
        data.pop("key_levels", None)
        data.pop("citations", None)
        data.pop("summary_technical", None)
        ans = AnalystAnswer.model_validate(data)
        ans.engine = last_llm_provider() or "llm"
        ans.answered_question = question
        ans.technical_metrics = []
        ans.key_levels = {"support": [], "resistance": []}
        ans.citations = []
        if not ans.blocks and ans.summary_plain:
            ans.blocks = [{"type": "paragraph", "text": ans.summary_plain}]
        return {"answer": ans.model_dump()}
    except Exception as e:
        logger.warning("LLM JSON parse failed: %s", e)
        return {
            "answer": _rule_answer(
                facts,
                sym,
                company,
                question=question,
                llm_error=f"LLM responded but JSON parse failed: {e}",
            )
        }


def node_persist(state: dict[str, Any], db: Session) -> dict[str, Any]:
    answer = state.get("answer") or {}
    aid = save_analysis(
        db,
        username=state.get("username") or "leninstark",
        symbol=state.get("symbol"),
        analysis_type="chat",
        payload=answer,
        question=state.get("question"),
        sources=state.get("sources") or [],
    )
    return {"analysis_id": aid}


def run_watchlist_chat(
    db: Session,
    *,
    username: str,
    symbol: str,
    question: str,
    company: Optional[str] = None,
    sector: Optional[str] = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Run analyst pipeline (LangGraph if available, else linear)."""
    initial: WatchlistAgentState = {
        "username": username,
        "symbol": symbol.upper() if symbol else "",
        "company": company or "",
        "sector": sector or "",
        "question": question,
        "force_refresh": force_refresh,
    }

    if LANGGRAPH_OK and StateGraph is not None:
        g = StateGraph(WatchlistAgentState)
        g.add_node("guard", node_guard)
        g.add_node("blocked", node_blocked)
        g.add_node("resolve", node_resolve)
        g.add_node("collect", lambda s: node_collect(s, db))
        g.add_node("index", lambda s: node_index(s, db))
        g.add_node("rag", lambda s: node_rag(s, db))
        g.add_node("graph", lambda s: node_graph(s, db))
        g.add_node("synthesize", node_synthesize)
        g.add_node("persist", lambda s: node_persist(s, db))
        g.add_edge(START, "guard")
        g.add_conditional_edges(
            "guard",
            lambda s: "blocked" if not s.get("allowed") else "resolve",
            {"blocked": "blocked", "resolve": "resolve"},
        )
        g.add_edge("blocked", "persist")
        g.add_edge("resolve", "collect")
        g.add_edge("collect", "index")
        g.add_edge("index", "rag")
        g.add_edge("rag", "graph")
        g.add_edge("graph", "synthesize")
        g.add_edge("synthesize", "persist")
        g.add_edge("persist", END)
        app = g.compile()
        final = app.invoke(initial)
    else:
        s = {**initial}
        s.update(node_guard(s))
        if not s.get("allowed"):
            s.update(node_blocked(s))
            s.update(node_persist(s, db))
        else:
            s.update(node_resolve(s))
            s.update(node_collect(s, db))
            s.update(node_index(s, db))
            s.update(node_rag(s, db))
            s.update(node_graph(s, db))
            s.update(node_synthesize(s))
            s.update(node_persist(s, db))
        final = s

    return {
        "symbol": final.get("symbol"),
        "company": final.get("company"),
        "question": question,
        "answer": final.get("answer"),
        "sources": final.get("sources") or [],
        "facts": final.get("facts"),
        "rag_chunks": final.get("rag_chunks"),
        "graph_peers": final.get("graph_peers"),
        "analysis_id": final.get("analysis_id"),
        "from_cache": not force_refresh and bool(final.get("facts")),
    }
