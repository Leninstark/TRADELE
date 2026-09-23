"""LLM agent: analyze historical + current data and suggest with justification.

Providers (LLM_PROVIDER + LLM_FALLBACK):
  - claude_cli — local Claude Code CLI (`claude -p`), Pro/Max subscription via `claude auth login`
  - gemini     — Google Gemini API (GEMINI_API_KEY)
  - openai     — OpenAI-compatible API (OPENAI_API_KEY, optional LLM_BASE_URL)
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Optional

from TRADELE.config import settings
from TRADELE.services.scoring_engine import StockScore

logger = logging.getLogger(__name__)

PROVIDER_CLAUDE_CLI = "claude_cli"
PROVIDER_GEMINI = "gemini"
PROVIDER_OPENAI = "openai"
ALL_PROVIDERS = (PROVIDER_CLAUDE_CLI, PROVIDER_GEMINI, PROVIDER_OPENAI)

_last_llm_provider: Optional[str] = None
_last_llm_error: Optional[str] = None

# Optional: openai package for OpenAI-compatible API
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


def build_analysis_prompt(
    top_longs: list[StockScore],
    top_shorts: list[StockScore],
    news_snippets: list[dict],
    market_context: Optional[str] = None,
) -> str:
    """Build prompt for LLM to summarize and justify intraday picks."""
    lines = [
        "You are an intraday trading analyst. Based on the following rule-based scan results and news, "
        "provide a concise summary and justification for the top intraday picks.",
        "",
        "## Top 10 LONG candidates (buy)",
    ]
    for i, s in enumerate(top_longs[:10], 1):
        lines.append(f"{i}. {s.symbol} (score: {s.score:.0f})")
        for r in s.reasons:
            lines.append(f"   - {r.reason} [source: {r.source}]")
        if s.key_levels:
            lines.append(f"   Key levels: {s.key_levels}")
        lines.append("")
    lines.append("## Top 10 SHORT candidates (avoid/sell)")
    for i, s in enumerate(top_shorts[:10], 1):
        lines.append(f"{i}. {s.symbol} (score: {s.score:.0f})")
        for r in s.reasons:
            lines.append(f"   - {r.reason} [source: {r.source}]")
        if s.key_levels:
            lines.append(f"   Key levels: {s.key_levels}")
        lines.append("")
    if news_snippets:
        lines.append("## Relevant news headlines")
        for n in news_snippets[:15]:
            lines.append(f"- [{n.get('source','')}] {n.get('title','')}")
        lines.append("")
    if market_context:
        lines.append("## Market context")
        lines.append(market_context)
    lines.append("")
    lines.append(
        "Respond with: (1) Brief market take. (2) Top 3 LONG with 1-line reason each. "
        "(3) Top 3 SHORT with 1-line reason each. (4) Disclaimer: Past performance and signals "
        "do not guarantee future results; trade at your own risk."
    )
    return "\n".join(lines)


def _normalize_provider(name: str) -> str:
    return (name or "").strip().lower().replace("-", "_")


def resolve_provider_order(
    primary: Optional[str] = None,
    fallback: Optional[str] = None,
) -> list[str]:
    """Primary provider first, then configured fallbacks (deduped, known only)."""
    primary_n = _normalize_provider(primary if primary is not None else settings.llm_provider)
    fb_raw = fallback if fallback is not None else settings.llm_fallback
    order: list[str] = []
    if primary_n in ALL_PROVIDERS:
        order.append(primary_n)
    for part in (fb_raw or "").split(","):
        p = _normalize_provider(part)
        if p in ALL_PROVIDERS and p not in order:
            order.append(p)
    if not order:
        order = list(ALL_PROVIDERS)
    return order


def find_claude_cli() -> Optional[str]:
    """Resolve Claude Code CLI binary path."""
    configured = (settings.claude_cli_path or "").strip()
    if configured:
        p = Path(configured).expanduser()
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
        logger.warning("CLAUDE_CLI_PATH set but not executable: %s", configured)

    which = shutil.which("claude")
    if which:
        return which

    # Common install locations (npm global / Cursor / Homebrew)
    home = Path.home()
    candidates = [
        home / ".local" / "bin" / "claude",
        Path("/opt/homebrew/bin/claude"),
        Path("/usr/local/bin/claude"),
        home / ".npm-global" / "bin" / "claude",
        home / "Library" / "Application Support" / "Claude" / "claude",
    ]
    for c in candidates:
        if c.is_file() and os.access(c, os.X_OK):
            return str(c)
    return None


def llm_is_configured() -> bool:
    """True if at least one configured provider in the resolve order looks usable."""
    for name in resolve_provider_order():
        if name == PROVIDER_CLAUDE_CLI and find_claude_cli():
            return True
        if name == PROVIDER_GEMINI and settings.gemini_api_key:
            return True
        if name == PROVIDER_OPENAI and settings.openai_api_key and OpenAI is not None:
            return True
    return False


def call_llm(prompt: str, api_key: Optional[str] = None, base_url: Optional[str] = None) -> Optional[str]:
    """Call OpenAI-compatible API. Set OPENAI_API_KEY and optionally LLM_BASE_URL."""
    global _last_llm_error
    api_key = api_key or settings.openai_api_key
    base_url = base_url or settings.llm_base_url
    if not api_key or not OpenAI:
        _last_llm_error = "OpenAI not configured (OPENAI_API_KEY missing)"
        logger.debug(_last_llm_error)
        return None
    try:
        client = OpenAI(api_key=api_key, base_url=base_url if base_url else None)
        r = client.chat.completions.create(
            model=getattr(settings, "openai_model", None) or "gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1500,
        )
        return r.choices[0].message.content if r.choices else None
    except Exception as e:
        _last_llm_error = f"OpenAI: {e}"
        logger.warning("LLM call failed: %s", e)
        return None


def call_gemini(prompt: str, api_key: Optional[str] = None) -> Optional[str]:
    """Call Google Gemini Pro for news summarisation. Uses GEMINI_API_KEY when set."""
    global _last_llm_error
    api_key = api_key or getattr(settings, "gemini_api_key", None)
    if not api_key:
        _last_llm_error = "Gemini not configured (GEMINI_API_KEY missing)"
        return None
    try:
        import google.generativeai as genai
        # Use REST transport: the default gRPC transport can hang indefinitely
        # in some network environments.
        genai.configure(api_key=api_key, transport="rest")
        model = genai.GenerativeModel(getattr(settings, "gemini_model", None) or "gemini-flash-latest")
        response = model.generate_content(prompt, request_options={"timeout": 90})
        if response and response.text:
            return response.text
        _last_llm_error = "Gemini returned empty response"
        return None
    except ImportError:
        _last_llm_error = "google-generativeai not installed"
        logger.debug(_last_llm_error)
        return None
    except Exception as e:
        _last_llm_error = f"Gemini: {e}"
        logger.warning("Gemini call failed: %s", e)
        return None


def _claude_child_env() -> dict[str, str]:
    """Env for Claude CLI. Scrub pay-per-token API keys so Pro login is used.

    Keep CLAUDE_CODE_OAUTH_TOKEN if present (from `claude setup-token`).
    Do not use --bare — bare mode ignores subscription OAuth.
    """
    env = os.environ.copy()
    if getattr(settings, "claude_cli_use_subscription", True):
        for key in (
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_AUTH_TOKEN",
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "CLOUD_ML_REGION",
        ):
            env.pop(key, None)
    return env


def _extract_claude_text(stdout: str) -> Optional[str]:
    """Parse `claude -p --output-format json|text` stdout into model text."""
    text = (stdout or "").strip()
    if not text:
        return None
    if text.startswith("{"):
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                if data.get("is_error"):
                    return None
                for key in ("result", "text", "content", "message"):
                    val = data.get(key)
                    if isinstance(val, str) and val.strip():
                        return val.strip()
                result = data.get("result")
                if result is not None and not isinstance(result, str):
                    return str(result)
        except json.JSONDecodeError:
            pass
    return text


def _claude_error_message(stdout: str, stderr: str) -> str:
    blob = (stdout or stderr or "").strip()
    if not blob:
        return "Claude CLI returned no output"
    if blob.startswith("{"):
        try:
            data = json.loads(blob)
            if isinstance(data, dict):
                msg = data.get("result") or data.get("message") or data.get("error")
                if isinstance(msg, str) and msg.strip():
                    return msg.strip()
        except json.JSONDecodeError:
            pass
    return blob[:400]


def call_claude_cli(prompt: str) -> Optional[str]:
    """
    Call Claude Code CLI non-interactively (`claude -p`).

    Uses local login from `claude auth login` (Claude Pro/Max).
    Prompt is sent on stdin so large fact bundles fit (watchlist analyst).
    """
    global _last_llm_error
    cli = find_claude_cli()
    if not cli:
        _last_llm_error = "Claude CLI not found — install Claude Code and run `claude auth login`"
        logger.debug(_last_llm_error)
        return None

    model = (settings.claude_cli_model or "sonnet").strip()
    timeout = int(getattr(settings, "claude_cli_timeout", 180) or 180)
    # stdin for large prompts; no --bare (needs subscription OAuth); no empty --allowedTools
    cmd = [
        cli,
        "-p",
        "--output-format",
        "json",
        "--model",
        model,
    ]
    try:
        proc = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_claude_child_env(),
            cwd=str(Path.home()),
            check=False,
        )
    except FileNotFoundError:
        _last_llm_error = f"Claude CLI binary missing: {cli}"
        logger.warning(_last_llm_error)
        return None
    except subprocess.TimeoutExpired:
        _last_llm_error = f"Claude CLI timed out after {timeout}s"
        logger.warning(_last_llm_error)
        return None
    except Exception as e:
        _last_llm_error = f"Claude CLI invoke failed: {e}"
        logger.warning(_last_llm_error)
        return None

    if proc.returncode != 0:
        err = _claude_error_message(proc.stdout or "", proc.stderr or "")
        _last_llm_error = f"Claude CLI: {err}"
        logger.warning("Claude CLI exited %s: %s", proc.returncode, err)
        return None

    # Even exit 0 can be an error envelope
    raw_out = (proc.stdout or "").strip()
    if raw_out.startswith("{"):
        try:
            data = json.loads(raw_out)
            if isinstance(data, dict) and data.get("is_error"):
                err = _claude_error_message(raw_out, proc.stderr or "")
                _last_llm_error = f"Claude CLI: {err}"
                logger.warning(_last_llm_error)
                return None
        except json.JSONDecodeError:
            pass

    result = _extract_claude_text(proc.stdout or "")
    if not result:
        result = _extract_claude_text(proc.stderr or "")
    if not result:
        _last_llm_error = "Claude CLI returned empty response"
        logger.warning(_last_llm_error)
        return None
    return result


_PROVIDER_CALLERS: dict[str, Callable[[str], Optional[str]]] = {
    PROVIDER_CLAUDE_CLI: call_claude_cli,
    PROVIDER_GEMINI: call_gemini,
    PROVIDER_OPENAI: call_llm,
}


def last_llm_provider() -> Optional[str]:
    """Provider name that succeeded on the most recent call_llm_auto()."""
    return _last_llm_provider


def last_llm_error() -> Optional[str]:
    """Last failure reason when call_llm_auto() returned None."""
    return _last_llm_error


def call_llm_auto(prompt: str, primary: Optional[str] = None) -> Optional[str]:
    """
    Call LLM using LLM_PROVIDER, then LLM_FALLBACK chain until one succeeds.

    Example .env:
      LLM_PROVIDER=claude_cli
      LLM_FALLBACK=gemini,openai
    """
    global _last_llm_provider, _last_llm_error
    _last_llm_provider = None
    _last_llm_error = None
    order = resolve_provider_order(primary=primary)
    errors: list[str] = []
    last_name = None
    for name in order:
        last_name = name
        caller = _PROVIDER_CALLERS.get(name)
        if not caller:
            continue
        try:
            out = caller(prompt)
        except Exception as e:
            msg = f"{name}: {e}"
            errors.append(msg)
            logger.warning("Provider %s raised: %s", name, e)
            out = None
        if out:
            _last_llm_provider = name
            _last_llm_error = None
            if name != order[0]:
                logger.info("LLM used fallback provider: %s (primary was %s)", name, order[0])
            return out
        if _last_llm_error:
            errors.append(f"{name}: {_last_llm_error}")
        else:
            errors.append(f"{name}: no result")
        logger.info("Provider %s returned no result; trying next", name)
    if last_name:
        _last_llm_error = " | ".join(errors) if errors else f"All providers failed ({','.join(order)})"
        logger.warning("All LLM providers failed: %s", _last_llm_error)
    return None


def enrich_alerts_with_llm(
    top_longs: list[StockScore],
    top_shorts: list[StockScore],
    news_snippets: list[dict],
    market_context: Optional[str] = None,
) -> str:
    """Return LLM summary string for notifications; empty if LLM not configured."""
    prompt = build_analysis_prompt(top_longs, top_shorts, news_snippets, market_context)
    return call_llm_auto(prompt) or ""


def build_news_impact_prompt(
    news_headlines: list[dict],
    screener_context: Optional[str] = None,
) -> str:
    """Build prompt for LLM to infer which stocks/sectors may go up or down from market-impact news."""
    lines = [
        "You are a market analyst. Below are recent financial and market news headlines that can move the market (macro, policy, sector, global).",
        "Infer which Indian stocks or sectors might move UP (positive) or DOWN (negative) based on these headlines.",
        "Do NOT base your answer on user-provided symbol lists; base it only on the news content.",
        "",
        "## News headlines",
    ]
    for n in news_headlines[:25]:
        lines.append(f"- [{n.get('source', '')}] {n.get('title', '')}")
        if n.get("summary"):
            lines.append(f"  {n['summary'][:200]}")
    if screener_context:
        lines.append("")
        lines.append("## Optional context (top screened stocks / sectors)")
        lines.append(screener_context[:1500])
    lines.append("")
    lines.append(
        "Respond in this exact JSON format only, no other text:\n"
        '{"positive": [{"symbol_or_sector": "name", "reason": "one line"}], '
        '"negative": [{"symbol_or_sector": "name", "reason": "one line"}], '
        '"market_take": "one paragraph summary"}\n'
        "Use Indian NSE stock symbols or sector names (e.g. RELIANCE, Bank Nifty, IT sector)."
    )
    return "\n".join(lines)


def infer_stocks_from_news(
    news_headlines: list[dict],
    screener_context: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """
    Use LLM to infer which stocks/sectors may go up or down from market-impact news.
    Returns {"positive": [...], "negative": [...], "market_take": "..."} or None.
    """
    prompt = build_news_impact_prompt(news_headlines, screener_context)
    raw = call_llm_auto(prompt)
    if not raw:
        return None
    try:
        # Try to extract JSON from response (in case LLM adds markdown or extra text)
        raw = raw.strip()
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("LLM did not return valid JSON for news impact")
        return {"raw_response": raw, "positive": [], "negative": [], "market_take": ""}
