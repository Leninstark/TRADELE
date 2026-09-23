"""Overnight / morning Market Brief — global+India news → index/sector risk verdict."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from TRADELE.config import settings
from TRADELE.db.models import MarketBrief
from TRADELE.services.llm_agent import call_llm_auto, last_llm_provider
from TRADELE.services.news_aggregator import NewsItem, aggregate_news, fetch_google_news, fetch_rss
from TRADELE.services.notification_service import send_telegram

logger = logging.getLogger(__name__)
IST = ZoneInfo(settings.tz)

NSE_SECTORS = [
    "IT",
    "Banks",
    "NBFCs",
    "Auto",
    "Pharma",
    "Metals",
    "Oil & Gas",
    "FMCG",
    "Realty",
    "Infra",
    "Power",
    "Chemicals",
    "Telecom",
    "Aviation",
    "Defence",
    "PSU",
]

GLOBAL_QUERIES = [
    "US stock market futures overnight",
    "Federal Reserve interest rates markets",
    "crude oil price markets",
    "geopolitical risk markets stocks",
    "China markets stocks commodities",
    "dollar index USDINR",
    "global risk off equities",
]

INDIA_QUERIES = [
    "Nifty Sensex pre market",
    "FII DII India markets",
    "RBI India markets",
    "India sector stocks news",
]

GLOBAL_RSS = [
    ("BBC Business", "https://feeds.bbci.co.uk/news/business/rss.xml"),
    ("CNBC Top News", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=2000&keyword=markets"),
    ("Reuters Business", "https://feeds.reuters.com/reuters/businessNews"),
]

# Keyword → sector transmission (rule prior before LLM)
TRANSMISSION_RULES: list[tuple[re.Pattern[str], dict[str, Any]]] = [
    (re.compile(r"\b(fed|fomc|rate hike|treasury yield|bond yield|powell)\b", re.I), {
        "stance_nudge": "risk_off",
        "bad": ["Banks", "NBFCs", "Realty", "IT"],
        "good": ["Banks"],  # sometimes banks benefit from higher NIMs — LLM decides
        "note": "Rates/Fed cue — rate-sensitives and growth under watch",
    }),
    (re.compile(r"\b(crude|brent|wti|oil price|opec)\b", re.I), {
        "stance_nudge": "neutral",
        "bad": ["Aviation", "Auto", "FMCG"],
        "good": ["Oil & Gas"],
        "note": "Oil move — OMCs/aviation/auto sensitive; upstream energy mixed",
    }),
    (re.compile(r"\b(war|missile|invasion|sanction|geopolit|middle east|taiwan|conflict)\b", re.I), {
        "stance_nudge": "risk_off",
        "bad": ["IT", "Auto", "Metals", "Realty"],
        "good": ["Defence", "Oil & Gas"],
        "note": "Geopolitical shock — risk-off bias, defence/oil may diverge",
    }),
    (re.compile(r"\b(nasdaq|tech selloff|Magnificent|FAANG|semiconductor)\b", re.I), {
        "stance_nudge": "risk_off",
        "bad": ["IT"],
        "good": [],
        "note": "US tech weakness often transmits to India IT next session",
    }),
    (re.compile(r"\b(china|yuan|evergrande|property china|commodity demand)\b", re.I), {
        "stance_nudge": "risk_off",
        "bad": ["Metals", "Chemicals"],
        "good": [],
        "note": "China/commodity demand cue — metals/chem under pressure risk",
    }),
    (re.compile(r"\b(usd|dollar index|dxy|rupee|usdinr)\b", re.I), {
        "stance_nudge": "neutral",
        "bad": ["IT", "Pharma"],  # INR weak can help exporters — LLM refines
        "good": ["IT", "Pharma"],
        "note": "USD/INR move — exporters vs importers split",
    }),
    (re.compile(r"\b(bank|nifty bank|rbi|npa|credit)\b", re.I), {
        "stance_nudge": "neutral",
        "bad": ["Banks", "NBFCs"],
        "good": ["Banks"],
        "note": "Banking/credit cue — Bank Nifty sensitive",
    }),
    (re.compile(r"\b(crash|selloff|plunge|bloodbath|circuit|panic|collapse)\b", re.I), {
        "stance_nudge": "crisis",
        "bad": ["IT", "Banks", "Auto", "Metals", "Realty"],
        "good": ["FMCG", "Pharma"],
        "note": "Panic language in headlines — treat as elevated risk-off until prices confirm",
    }),
]


def _item_dict(n: NewsItem) -> dict[str, Any]:
    return {
        "title": n.title,
        "link": n.link,
        "source": n.source,
        "published": n.published.isoformat() if n.published else None,
        "summary": (n.summary or "")[:300],
    }


def harvest_market_headlines(limit_per_query: int = 6) -> list[dict[str, Any]]:
    """India RSS + global RSS + targeted Google News queries."""
    items: list[NewsItem] = []
    items.extend(aggregate_news()[:40])
    for name, url in GLOBAL_RSS:
        items.extend(fetch_rss(url, name)[:15])
    for q in GLOBAL_QUERIES + INDIA_QUERIES:
        items.extend(fetch_google_news(q, limit=limit_per_query))

    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for n in items:
        key = (n.title or "")[:90].lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(_item_dict(n))
    return out[:80]


def apply_transmission_rules(headlines: list[dict[str, Any]]) -> dict[str, Any]:
    """Rule priors from keyword hits — not final verdict."""
    hits: list[dict[str, Any]] = []
    bad_votes: dict[str, int] = {}
    good_votes: dict[str, int] = {}
    stance_score = 0  # negative = risk_off

    for h in headlines:
        blob = f"{h.get('title') or ''} {h.get('summary') or ''}"
        for pat, rule in TRANSMISSION_RULES:
            if not pat.search(blob):
                continue
            hits.append({"title": h.get("title"), "note": rule["note"], "source": h.get("source")})
            nudge = rule.get("stance_nudge")
            if nudge == "crisis":
                stance_score -= 3
            elif nudge == "risk_off":
                stance_score -= 2
            elif nudge == "risk_on":
                stance_score += 2
            for s in rule.get("bad") or []:
                bad_votes[s] = bad_votes.get(s, 0) + 1
            for s in rule.get("good") or []:
                good_votes[s] = good_votes.get(s, 0) + 1
            break  # one rule per headline

    if stance_score <= -6:
        stance = "crisis"
    elif stance_score <= -2:
        stance = "risk_off"
    elif stance_score >= 2:
        stance = "risk_on"
    else:
        stance = "neutral"

    sectors = []
    for s in NSE_SECTORS:
        b, g = bad_votes.get(s, 0), good_votes.get(s, 0)
        if b > g and b >= 1:
            bias = "bad"
        elif g > b and g >= 1:
            bias = "good"
        elif b or g:
            bias = "watch"
        else:
            bias = "neutral"
        sectors.append({"sector": s, "bias": bias, "rule_hits": b + g})

    return {
        "stance_prior": stance,
        "stance_score": stance_score,
        "rule_hits": hits[:20],
        "sectors_prior": sectors,
    }


def fetch_market_crosscheck() -> dict[str, Any]:
    """Best-effort overnight proxies via yfinance (no invention if unavailable)."""
    out: dict[str, Any] = {"available": False, "notes": [], "series": {}}
    try:
        import yfinance as yf
    except ImportError:
        out["notes"].append("yfinance not installed — price cross-check skipped")
        return out

    tickers = {
        "NIFTY": "^NSEI",
        "BANKNIFTY": "^NSEBANK",
        "US_FUTURES_PROXY": "ES=F",
        "NASDAQ_FUTURES": "NQ=F",
        "CRUDE": "CL=F",
        "USDINR": "USDINR=X",
        "GOLD": "GC=F",
        "INDIA_VIX": "^INDIAVIX",
    }
    try:
        for label, tk in tickers.items():
            t = yf.Ticker(tk)
            hist = t.history(period="5d")
            if hist is None or hist.empty or len(hist) < 2:
                continue
            last = float(hist["Close"].iloc[-1])
            prev = float(hist["Close"].iloc[-2])
            chg = ((last - prev) / prev * 100) if prev else 0.0
            out["series"][label] = {
                "last": round(last, 4),
                "prev_close": round(prev, 4),
                "chg_pct": round(chg, 3),
                "ticker": tk,
            }
        out["available"] = bool(out["series"])
        if not out["available"]:
            out["notes"].append("No overnight proxy series returned")
        else:
            # Simple confirmation flags
            nifty = out["series"].get("NIFTY") or out["series"].get("US_FUTURES_PROXY")
            if nifty and nifty["chg_pct"] <= -1.0:
                out["notes"].append("Price proxy confirms soft tape (≤ −1%)")
            elif nifty and nifty["chg_pct"] >= 1.0:
                out["notes"].append("Price proxy confirms firm tape (≥ +1%)")
    except Exception as e:
        logger.warning("Market cross-check failed: %s", e)
        out["notes"].append(f"Cross-check error: {e}")
    return out


def _default_indices(stance: str) -> list[dict[str, Any]]:
    bias = {
        "crisis": "down",
        "risk_off": "down",
        "risk_on": "up",
        "neutral": "flat",
    }.get(stance, "flat")
    return [
        {"index": "NIFTY", "bias": bias, "confidence": 55},
        {"index": "BANKNIFTY", "bias": bias, "confidence": 50},
        {"index": "INDIA_VIX", "bias": "up" if bias == "down" else "flat", "confidence": 50},
    ]


def _template_brief(
    brief_type: str,
    headlines: list[dict[str, Any]],
    rules: dict[str, Any],
    cross: dict[str, Any],
) -> dict[str, Any]:
    stance = rules.get("stance_prior") or "neutral"
    # Confirm with prices if available
    us = (cross.get("series") or {}).get("US_FUTURES_PROXY") or {}
    if us.get("chg_pct") is not None and us["chg_pct"] <= -1.2 and stance in ("neutral", "risk_on"):
        stance = "risk_off"
    if us.get("chg_pct") is not None and us["chg_pct"] <= -2.5:
        stance = "crisis"

    sectors = rules.get("sectors_prior") or [
        {"sector": s, "bias": "neutral", "rule_hits": 0} for s in NSE_SECTORS
    ]
    catalysts = [
        {"title": h.get("title"), "why": h.get("note"), "source": h.get("source")}
        for h in (rules.get("rule_hits") or [])[:5]
    ]
    if not catalysts:
        catalysts = [
            {"title": h.get("title"), "why": "Top harvested headline", "source": h.get("source")}
            for h in headlines[:5]
        ]

    action = {
        "risk_on": "Normal size OK if setups align; still respect stops.",
        "neutral": "Trade selective setups; avoid oversized overnight risk.",
        "risk_off": "Cut position size. Prefer no fresh aggressive longs. Wait 30–60 min after open.",
        "crisis": "Capital preservation: no new longs, reduce open risk, consider hedges / flat.",
    }[stance if stance in ("risk_on", "neutral", "risk_off", "crisis") else "neutral"]

    return {
        "stance": stance,
        "confidence": 55 if rules.get("rule_hits") else 40,
        "market_summary": (
            f"Template brief ({brief_type}). Stance prior={stance} from keyword transmission rules "
            f"on {len(headlines)} headlines. "
            + ("Price cross-check available. " if cross.get("available") else "No reliable overnight price cross-check. ")
            + "This is a risk regime brief, not a guaranteed prediction."
        ),
        "indices": _default_indices(stance),
        "sectors": sectors,
        "catalysts": catalysts,
        "invalidate_if": [
            "Futures/proxies reverse sharply higher into the open",
            "Headlines are rumor-only with no price confirmation",
        ],
        "action_card": {
            "guidance": action,
            "max_risk_today": "Needs further testing" if stance == "neutral" else ("½ size" if stance == "risk_off" else "minimal / flat"),
            "avoid_sectors": [s["sector"] for s in sectors if s.get("bias") == "bad"][:6],
            "watch_sectors": [s["sector"] for s in sectors if s.get("bias") == "good"][:6],
            "wait_first_hour": stance in ("risk_off", "crisis"),
        },
        "llm_used": False,
    }


def _extract_json(text: str) -> Optional[dict[str, Any]]:
    text = (text or "").strip()
    if "```" in text:
        text = re.sub(r"```(?:json)?", "", text).replace("```", "").strip()
    if not text.startswith("{"):
        m = re.search(r"\{[\s\S]*\}", text)
        text = m.group(0) if m else text
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def synthesize_brief_with_llm(
    brief_type: str,
    headlines: list[dict[str, Any]],
    rules: dict[str, Any],
    cross: dict[str, Any],
) -> dict[str, Any]:
    base = _template_brief(brief_type, headlines, rules, cross)
    prompt = f"""You are a risk manager for Indian equities (NSE).
Build an OVERNIGHT/PRE-OPEN market risk brief. Do NOT claim certainty. Do NOT invent prices.
Use the harvested headlines + rule priors + optional price cross-check.

brief_type: {brief_type}
rule_priors: {json.dumps(rules, default=str)[:6000]}
price_crosscheck: {json.dumps(cross, default=str)[:4000]}
headlines (top 40): {json.dumps(headlines[:40], default=str)[:12000]}

Return ONLY JSON:
{{
  "stance": "risk_on|neutral|risk_off|crisis",
  "confidence": 0-100,
  "market_summary": "6-10 sentences, brutally honest",
  "indices": [
    {{"index":"NIFTY","bias":"up|flat|down","confidence":0-100,"note":"..."}},
    {{"index":"BANKNIFTY","bias":"up|flat|down","confidence":0-100,"note":"..."}},
    {{"index":"INDIA_VIX","bias":"up|flat|down","confidence":0-100,"note":"..."}}
  ],
  "sectors": [
    {{"sector":"IT","bias":"good|bad|watch|neutral","reason":"cite headline theme"}}
  ],
  "catalysts": [{{"title":"...","why":"India transmission","severity":"high|med|low"}}],
  "invalidate_if": ["..."],
  "action_card": {{
    "guidance":"what trader should do before/at open",
    "max_risk_today":"...",
    "avoid_sectors":["..."],
    "watch_sectors":["..."],
    "wait_first_hour": true
  }},
  "personality_note": "This is regime risk intelligence, not a P&L guarantee."
}}
Cover these sectors when possible: {", ".join(NSE_SECTORS)}.
If evidence is thin, set confidence low and stance neutral.
"""
    raw = call_llm_auto(prompt)
    provider = last_llm_provider()
    if not raw:
        base["llm_used"] = False
        base["llm_provider"] = None
        return base
    parsed = _extract_json(raw)
    if not parsed:
        base["llm_used"] = False
        base["llm_provider"] = provider
        base["parse_failed"] = True
        return base

    # Merge with defaults
    stance = str(parsed.get("stance") or base["stance"]).lower()
    if stance not in ("risk_on", "neutral", "risk_off", "crisis"):
        stance = base["stance"]
    out = {
        **base,
        **{k: parsed[k] for k in parsed if k not in ("llm_used",)},
        "stance": stance,
        "confidence": int(parsed.get("confidence") or base["confidence"]),
        "llm_used": True,
        "llm_provider": provider,
    }
    if not out.get("indices"):
        out["indices"] = base["indices"]
    if not out.get("sectors"):
        out["sectors"] = base["sectors"]
    if not out.get("action_card"):
        out["action_card"] = base["action_card"]
    return out


def _maybe_alert(brief: dict[str, Any], row: MarketBrief, db: Session) -> None:
    stance = brief.get("stance")
    if stance not in ("risk_off", "crisis"):
        return
    conf = int(brief.get("confidence") or 0)
    if conf < 50:
        return
    action = (brief.get("action_card") or {}).get("guidance") or ""
    text = (
        f"TRADELE Market Brief ({row.brief_type.upper()}) — {stance.upper()} "
        f"(confidence {conf})\n"
        f"{(brief.get('market_summary') or '')[:500]}\n"
        f"Action: {action[:300]}"
    )
    try:
        if send_telegram(text):
            row.alerted = True
            db.commit()
    except Exception as e:
        logger.warning("Market brief telegram failed: %s", e)


def build_and_save_market_brief(
    db: Session,
    *,
    brief_type: str = "manual",
    send_alert: bool = True,
) -> dict[str, Any]:
    """Harvest → rules → cross-check → LLM → persist MarketBrief."""
    brief_type = (brief_type or "manual").strip().lower()
    if brief_type not in ("night", "morning", "manual"):
        brief_type = "manual"

    try:
        headlines = harvest_market_headlines()
        rules = apply_transmission_rules(headlines)
        cross = fetch_market_crosscheck()
        brief = synthesize_brief_with_llm(brief_type, headlines, rules, cross)

        payload = {
            "brief_type": brief_type,
            "generated_at_ist": datetime.now(IST).isoformat(),
            "headlines": headlines[:40],
            "rules": rules,
            "crosscheck": cross,
            "brief": brief,
            "disclaimer": (
                "Risk regime brief only. Does not predict exact crash magnitude. "
                "Combine with position limits and max daily loss rules."
            ),
        }

        row = MarketBrief(
            brief_type=brief_type,
            as_of=datetime.utcnow(),
            stance=str(brief.get("stance") or "neutral"),
            confidence=int(brief.get("confidence") or 50),
            payload=payload,
            headline_count=len(headlines),
            llm_provider=brief.get("llm_provider"),
            llm_used=bool(brief.get("llm_used")),
            status="success",
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        if send_alert:
            _maybe_alert(brief, row, db)

        return brief_to_dict(row)
    except Exception as e:
        logger.exception("Market brief failed")
        fail = MarketBrief(
            brief_type=brief_type,
            as_of=datetime.utcnow(),
            stance="neutral",
            confidence=0,
            payload={},
            status="failed",
            error_message=str(e)[:500],
        )
        db.add(fail)
        db.commit()
        return {
            "ok": False,
            "error": str(e),
            "status": "failed",
        }


def brief_to_dict(row: MarketBrief) -> dict[str, Any]:
    payload = row.payload or {}
    brief = payload.get("brief") or {}
    return {
        "ok": row.status == "success",
        "id": row.id,
        "brief_type": row.brief_type,
        "as_of": row.as_of.isoformat() if row.as_of else None,
        "stance": row.stance,
        "confidence": row.confidence,
        "headline_count": row.headline_count,
        "llm_used": bool(row.llm_used),
        "llm_provider": row.llm_provider,
        "alerted": bool(row.alerted),
        "status": row.status,
        "error_message": row.error_message,
        "market_summary": brief.get("market_summary"),
        "indices": brief.get("indices") or [],
        "sectors": brief.get("sectors") or [],
        "catalysts": brief.get("catalysts") or [],
        "invalidate_if": brief.get("invalidate_if") or [],
        "action_card": brief.get("action_card") or {},
        "crosscheck": payload.get("crosscheck") or {},
        "headlines": payload.get("headlines") or [],
        "disclaimer": payload.get("disclaimer"),
        "generated_at_ist": payload.get("generated_at_ist"),
    }


def get_latest_market_brief(db: Session, brief_type: Optional[str] = None) -> Optional[dict[str, Any]]:
    q = db.query(MarketBrief).filter(MarketBrief.status == "success")
    if brief_type:
        q = q.filter(MarketBrief.brief_type == brief_type.strip().lower())
    row = q.order_by(MarketBrief.as_of.desc()).first()
    return brief_to_dict(row) if row else None
