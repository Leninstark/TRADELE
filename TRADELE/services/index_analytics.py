"""Index daily analytics from data/indices/*_1y_daily.csv."""
from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np
import pandas as pd

from TRADELE.config import ROOT_DIR

logger = logging.getLogger(__name__)

INDICES_DIR = ROOT_DIR / "data" / "indices"

INDEX_META = {
    "NIFTY": {"label": "NIFTY 50", "file": "NIFTY_1y_daily.csv", "lot_hint": "Index futures/options"},
    "BANKNIFTY": {"label": "Bank Nifty", "file": "BANKNIFTY_1y_daily.csv", "lot_hint": "Banking index F&O"},
    "SENSEX": {"label": "SENSEX", "file": "SENSEX_1y_daily.csv", "lot_hint": "BSE index F&O"},
}

GAP_PCT = 0.35
SUDDEN_FALL_PCT = 1.25
SUDDEN_RALLY_PCT = 1.25
VOLUME_SPIKE = 1.75


def list_indices() -> list[dict[str, Any]]:
    out = []
    for key, meta in INDEX_META.items():
        path = INDICES_DIR / meta["file"]
        out.append(
            {
                "id": key,
                "label": meta["label"],
                "lot_hint": meta["lot_hint"],
                "available": path.is_file(),
                "path": str(path) if path.is_file() else None,
            }
        )
    return out


def _load_df(index_id: str) -> pd.DataFrame:
    meta = INDEX_META.get(index_id.upper())
    if not meta:
        raise ValueError(f"Unknown index: {index_id}")
    path = INDICES_DIR / meta["file"]
    if not path.is_file():
        raise FileNotFoundError(
            f"Missing {path.name}. Run: python -m TRADELE.tools.fetch_index_daily"
        )
    df = pd.read_csv(path)
    df.columns = [str(c).strip().lower() for c in df.columns]
    required = {"date", "open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{path.name} missing columns: {sorted(missing)}")
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"]).sort_values("date").reset_index(drop=True)
    if df.empty:
        raise ValueError(f"No rows in {path.name}")
    return df


def _enrich(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["prev_close"] = out["close"].shift(1)
    out["change"] = out["close"] - out["prev_close"]
    out["change_pct"] = (out["change"] / out["prev_close"]) * 100
    out["range_pts"] = out["high"] - out["low"]
    out["range_pct"] = (out["range_pts"] / out["close"]) * 100
    out["gap_pts"] = out["open"] - out["prev_close"]
    out["gap_pct"] = (out["gap_pts"] / out["prev_close"]) * 100
    out["body_pts"] = out["close"] - out["open"]
    out["vol_ma20"] = out["volume"].rolling(20, min_periods=5).mean()
    out["weekday"] = out["date"].dt.day_name()
    return out


def _day_row(r: pd.Series) -> dict[str, Any]:
    return {
        "date": r["date"].strftime("%Y-%m-%d"),
        "weekday": str(r.get("weekday") or r["date"].strftime("%A")),
        "open": _f(r["open"]),
        "high": _f(r["high"]),
        "low": _f(r["low"]),
        "close": _f(r["close"]),
        "volume": int(r["volume"]) if pd.notna(r["volume"]) else 0,
        "change": _f(r.get("change")),
        "change_pct": _f(r.get("change_pct")),
        "range_pts": _f(r.get("range_pts")),
        "gap_pts": _f(r.get("gap_pts")),
        "gap_pct": _f(r.get("gap_pct")),
    }


def _f(v: Any, nd: int = 2) -> Optional[float]:
    if v is None or (isinstance(v, float) and np.isnan(v)) or pd.isna(v):
        return None
    try:
        return round(float(v), nd)
    except (TypeError, ValueError):
        return None


def _extreme(df: pd.DataFrame, col: str, how: str = "max") -> Optional[dict[str, Any]]:
    series = df[col].dropna()
    if series.empty:
        return None
    idx = series.idxmax() if how == "max" else series.idxmin()
    row = df.loc[idx]
    return {**_day_row(row), "metric": _f(row[col]), "metric_name": col}


def _weekday_stats(df: pd.DataFrame) -> list[dict[str, Any]]:
    valid = df.dropna(subset=["change_pct", "range_pts"])
    if valid.empty:
        return []
    rows = []
    for name in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday"):
        g = valid[valid["weekday"] == name]
        if g.empty:
            continue
        rows.append(
            {
                "weekday": name,
                "sessions": int(len(g)),
                "avg_change_pct": _f(g["change_pct"].mean()),
                "avg_range_pts": _f(g["range_pts"].mean()),
                "avg_volume": _f(g["volume"].mean(), 0),
                "green_pct": _f((g["change"] > 0).mean() * 100),
            }
        )
    return rows


def _streaks(df: pd.DataFrame) -> dict[str, Any]:
    valid = df.dropna(subset=["change"])
    if valid.empty:
        return {"longest_green": 0, "longest_red": 0, "current": None}
    signs = np.sign(valid["change"].to_numpy())
    best_g = best_r = cur = 0
    cur_sign = 0
    for s in signs:
        if s == 0:
            cur = 0
            cur_sign = 0
            continue
        if s == cur_sign:
            cur += 1
        else:
            cur_sign = int(s)
            cur = 1
        if cur_sign > 0:
            best_g = max(best_g, cur)
        else:
            best_r = max(best_r, cur)
    current = None
    if len(signs):
        last = int(signs[-1])
        n = 0
        for s in reversed(signs):
            if int(s) == last and last != 0:
                n += 1
            else:
                break
        if last != 0:
            current = {"direction": "green" if last > 0 else "red", "length": n}
    return {"longest_green": best_g, "longest_red": best_r, "current": current}


def _detect_patterns(df: pd.DataFrame) -> list[dict[str, Any]]:
    patterns: list[dict[str, Any]] = []
    valid = df.dropna(subset=["prev_close", "change_pct", "gap_pct"]).copy()
    med_range = float(valid["range_pts"].median() or 0) if len(valid) else 0.0

    for _, r in valid.iterrows():
        day = _day_row(r)
        vol_ratio = None
        if pd.notna(r.get("vol_ma20")) and r["vol_ma20"]:
            vol_ratio = float(r["volume"] / r["vol_ma20"])

        gap = float(r["gap_pct"] or 0)
        chg = float(r["change_pct"] or 0)
        body = float(r["body_pts"] or 0)
        rng = float(r["range_pts"] or 0)

        if gap >= GAP_PCT:
            patterns.append(
                {
                    "id": f"gap_up_{day['date']}",
                    "type": "gap_up",
                    "severity": "medium" if gap < 0.7 else "high",
                    "title": f"Gap up {gap:+.2f}%",
                    "summary": (
                        f"Opened {_f(r['gap_pts'])} pts above prior close ({day['date']}). "
                        f"Close change {chg:+.2f}%."
                    ),
                    "day": day,
                    "metrics": {"gap_pct": _f(gap), "gap_pts": _f(r["gap_pts"]), "change_pct": _f(chg)},
                }
            )
        elif gap <= -GAP_PCT:
            patterns.append(
                {
                    "id": f"gap_down_{day['date']}",
                    "type": "gap_down",
                    "severity": "medium" if gap > -0.7 else "high",
                    "title": f"Gap down {gap:+.2f}%",
                    "summary": (
                        f"Opened {_f(r['gap_pts'])} pts below prior close ({day['date']}). "
                        f"Close change {chg:+.2f}%."
                    ),
                    "day": day,
                    "metrics": {"gap_pct": _f(gap), "gap_pts": _f(r["gap_pts"]), "change_pct": _f(chg)},
                }
            )

        if chg <= -SUDDEN_FALL_PCT:
            patterns.append(
                {
                    "id": f"sudden_fall_{day['date']}",
                    "type": "sudden_fall",
                    "severity": "high" if chg <= -2 else "medium",
                    "title": f"Sudden fall {chg:+.2f}%",
                    "summary": f"{day['date']}: closed {_f(r['change'])} pts lower (range {_f(rng)} pts).",
                    "day": day,
                    "metrics": {"change_pct": _f(chg), "change": _f(r["change"]), "range_pts": _f(rng)},
                }
            )
        elif chg >= SUDDEN_RALLY_PCT:
            patterns.append(
                {
                    "id": f"sudden_rally_{day['date']}",
                    "type": "sudden_rally",
                    "severity": "high" if chg >= 2 else "medium",
                    "title": f"Sudden rally {chg:+.2f}%",
                    "summary": f"{day['date']}: closed {_f(r['change'])} pts higher (range {_f(rng)} pts).",
                    "day": day,
                    "metrics": {"change_pct": _f(chg), "change": _f(r["change"]), "range_pts": _f(rng)},
                }
            )

        if med_range and rng >= med_range * 2.2:
            patterns.append(
                {
                    "id": f"wide_range_{day['date']}",
                    "type": "wide_range",
                    "severity": "medium",
                    "title": f"Wide-range day ({_f(rng)} pts)",
                    "summary": f"{day['date']}: intraday range {_f(rng)} pts — ~{rng / med_range:.1f}× median.",
                    "day": day,
                    "metrics": {"range_pts": _f(rng), "median_range": _f(med_range)},
                }
            )

        if vol_ratio is not None and vol_ratio >= VOLUME_SPIKE:
            patterns.append(
                {
                    "id": f"vol_spike_{day['date']}",
                    "type": "volume_spike",
                    "severity": "medium" if vol_ratio < 2.5 else "high",
                    "title": f"Volume spike ×{vol_ratio:.1f}",
                    "summary": (
                        f"{day['date']}: volume {int(r['volume']):,} vs 20d avg {int(r['vol_ma20']):,}."
                    ),
                    "day": day,
                    "metrics": {
                        "volume": int(r["volume"]),
                        "vol_ma20": int(r["vol_ma20"]),
                        "vol_ratio": _f(vol_ratio),
                        "change_pct": _f(chg),
                    },
                }
            )

        if gap >= GAP_PCT and body < 0 and chg < 0:
            patterns.append(
                {
                    "id": f"gap_fade_{day['date']}",
                    "type": "gap_fade",
                    "severity": "medium",
                    "title": "Gap-up fade",
                    "summary": (
                        f"{day['date']}: gapped up {gap:+.2f}% then closed red ({chg:+.2f}%) — "
                        "bullish open rejected."
                    ),
                    "day": day,
                    "metrics": {"gap_pct": _f(gap), "change_pct": _f(chg)},
                }
            )
        if gap <= -GAP_PCT and body > 0 and chg > 0:
            patterns.append(
                {
                    "id": f"gap_recover_{day['date']}",
                    "type": "gap_recovery",
                    "severity": "medium",
                    "title": "Gap-down recovery",
                    "summary": (
                        f"{day['date']}: gapped down {gap:+.2f}% then closed green ({chg:+.2f}%) — "
                        "dip bought."
                    ),
                    "day": day,
                    "metrics": {"gap_pct": _f(gap), "change_pct": _f(chg)},
                }
            )

    sev = {"high": 3, "medium": 2, "low": 1}
    by_id: dict[str, dict] = {}
    for p in patterns:
        prev = by_id.get(p["id"])
        if not prev or sev.get(p["severity"], 0) > sev.get(prev["severity"], 0):
            by_id[p["id"]] = p

    weekday = _weekday_stats(valid)
    extras: list[dict[str, Any]] = []
    if weekday:
        best = max(weekday, key=lambda x: x.get("avg_change_pct") or -999)
        worst = min(weekday, key=lambda x: x.get("avg_change_pct") or 999)
        if best["weekday"] != worst["weekday"]:
            extras.append(
                {
                    "id": "weekday_edge",
                    "type": "weekday_seasonality",
                    "severity": "medium",
                    "title": f"Weekday edge: {best['weekday']} vs {worst['weekday']}",
                    "summary": (
                        f"Avg close-to-close: {best['weekday']} {best['avg_change_pct']:+.3f}% vs "
                        f"{worst['weekday']} {worst['avg_change_pct']:+.3f}% over this sample."
                    ),
                    "day": None,
                    "metrics": {"best": best, "worst": worst, "by_weekday": weekday},
                }
            )

    streaks = _streaks(valid)
    if streaks["longest_green"] >= 5 or streaks["longest_red"] >= 5:
        extras.append(
            {
                "id": "streak_extremes",
                "type": "streak",
                "severity": "medium",
                "title": "Streak extremes",
                "summary": (
                    f"Longest green run {streaks['longest_green']} sessions; "
                    f"longest red run {streaks['longest_red']}."
                ),
                "day": None,
                "metrics": streaks,
            }
        )

    merged = list(by_id.values()) + extras

    def sort_key(p: dict) -> tuple:
        d = (p.get("day") or {}).get("date") or ""
        return (sev.get(p.get("severity"), 0), d)

    seen: set[str] = set()
    ordered: list[dict] = []
    for p in sorted(merged, key=sort_key, reverse=True):
        if p["id"] in seen:
            continue
        seen.add(p["id"])
        ordered.append(p)
    return ordered[:80]


def _fmt_vol(v: Any) -> str:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "—"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return f"{int(n):,}"


def _max_drawdown_pct(closes: pd.Series) -> float:
    if closes.empty:
        return 0.0
    peak = closes.cummax()
    dd = (closes / peak - 1.0) * 100
    return float(dd.min()) if len(dd) else 0.0


def _kpis(df: pd.DataFrame) -> list[dict[str, Any]]:
    valid = df.dropna(subset=["change", "range_pts", "prev_close"])
    green = int((valid["change"] > 0).sum())
    red = int((valid["change"] < 0).sum())
    total = max(len(valid), 1)
    abs_move = valid["change"].abs()
    gaps = valid["gap_pct"].dropna()

    return [
        {
            "key": "avg_volume",
            "label": "Avg daily volume",
            "value": _f(valid["volume"].mean(), 0),
            "display": _fmt_vol(valid["volume"].mean()),
            "unit": "shares",
            "hint": "Mean Yahoo daily volume over the sample (activity proxy).",
        },
        {
            "key": "avg_range_pts",
            "label": "Avg daily range",
            "value": _f(valid["range_pts"].mean()),
            "display": f"{_f(valid['range_pts'].mean())} pts",
            "unit": "points",
            "hint": "Average high−low range per session — typical intraday swing size.",
        },
        {
            "key": "avg_abs_move",
            "label": "Avg |daily move|",
            "value": _f(abs_move.mean()),
            "display": f"{_f(abs_move.mean())} pts",
            "unit": "points",
            "hint": "Average absolute close-to-close change.",
        },
        {
            "key": "avg_change_pct",
            "label": "Avg daily % move",
            "value": _f(valid["change_pct"].mean()),
            "display": f"{_f(valid['change_pct'].mean()):+.3f}%",
            "unit": "percent",
            "hint": "Mean signed daily return. Near zero is normal.",
        },
        {
            "key": "green_pct",
            "label": "Green days",
            "value": _f(100.0 * green / total),
            "display": f"{green}/{total} ({_f(100.0 * green / total)}%)",
            "unit": "percent",
            "hint": f"{green} up closes vs {red} down closes in this window.",
        },
        {
            "key": "avg_gap_pct",
            "label": "Avg |gap|",
            "value": _f(gaps.abs().mean()) if len(gaps) else None,
            "display": f"{_f(gaps.abs().mean())}%" if len(gaps) else "—",
            "unit": "percent",
            "hint": "Mean absolute overnight gap (open vs prior close).",
        },
        {
            "key": "volatility",
            "label": "Daily vol (σ)",
            "value": _f(valid["change_pct"].std()),
            "display": f"{_f(valid['change_pct'].std())}%",
            "unit": "percent",
            "hint": "Stdev of daily % returns — higher = choppier index.",
        },
        {
            "key": "max_drawdown_pct",
            "label": "Max drawdown",
            "value": _f(_max_drawdown_pct(valid["close"])),
            "display": f"{_f(_max_drawdown_pct(valid['close']))}%",
            "unit": "percent",
            "hint": "Largest peak-to-trough decline in close over the sample.",
        },
    ]


def _interesting_notes(
    df: pd.DataFrame,
    patterns: list[dict[str, Any]],
    counts: dict[str, int],
) -> list[dict[str, Any]]:
    notes: list[dict[str, Any]] = []
    valid = df.dropna(subset=["change_pct", "gap_pct", "range_pts"])
    if valid.empty:
        return notes

    gap_days = int((valid["gap_pct"].abs() >= GAP_PCT).sum())
    notes.append(
        {
            "key": "gap_frequency",
            "title": "Gap frequency",
            "text": (
                f"{gap_days} sessions ({100 * gap_days / len(valid):.0f}%) opened with a "
                f"≥{GAP_PCT}% gap vs prior close."
            ),
            "context": {"gap_days": gap_days, "threshold_pct": GAP_PCT, "sessions": len(valid)},
        }
    )

    fall_n = counts.get("sudden_fall", 0)
    rally_n = counts.get("sudden_rally", 0)
    notes.append(
        {
            "key": "shock_asymmetry",
            "title": "Shock asymmetry",
            "text": (
                f"{fall_n} sudden falls vs {rally_n} sudden rallies "
                f"(≥{SUDDEN_FALL_PCT}% close-to-close). "
                + (
                    "Down-shocks dominate — fat left tail."
                    if fall_n > rally_n + 2
                    else (
                        "Up-shocks dominate — strong upside impulse days."
                        if rally_n > fall_n + 2
                        else "Shocks are roughly balanced."
                    )
                )
            ),
            "context": {"sudden_fall": fall_n, "sudden_rally": rally_n},
        }
    )

    if len(valid) >= 40:
        recent = valid.tail(20)["range_pts"].mean()
        base = valid["range_pts"].mean()
        if base:
            ratio = recent / base
            notes.append(
                {
                    "key": "recent_range_regime",
                    "title": "Recent range regime",
                    "text": (
                        f"Last 20 sessions avg range {_f(recent)} pts vs sample avg {_f(base)} pts "
                        f"({ratio:.2f}×). "
                        + (
                            "Volatility expanding."
                            if ratio >= 1.15
                            else "Volatility compressing." if ratio <= 0.85 else "Range in line with sample."
                        )
                    ),
                    "context": {
                        "recent_avg_range": _f(recent),
                        "sample_avg_range": _f(base),
                        "ratio": _f(ratio),
                    },
                }
            )

    fade = counts.get("gap_fade", 0)
    recover = counts.get("gap_recovery", 0)
    if fade or recover:
        notes.append(
            {
                "key": "gap_behavior",
                "title": "Gap behavior",
                "text": (
                    f"{fade} gap-up fades and {recover} gap-down recoveries detected — "
                    "useful for opening-drive vs mean-reversion study."
                ),
                "context": {"gap_fade": fade, "gap_recovery": recover},
            }
        )

    return notes


def analyze_index(index_id: str) -> dict[str, Any]:
    key = index_id.upper().strip()
    meta = INDEX_META[key]
    df = _enrich(_load_df(key))
    valid = df.dropna(subset=["change", "range_pts"])

    first = df.iloc[0]
    last = df.iloc[-1]
    period_chg = None
    if first["close"]:
        period_chg = (float(last["close"]) - float(first["close"])) / float(first["close"]) * 100

    patterns = _detect_patterns(df)
    type_counts: dict[str, int] = {}
    for p in patterns:
        type_counts[p["type"]] = type_counts.get(p["type"], 0) + 1

    series = [
        {
            "date": r["date"].strftime("%Y-%m-%d"),
            "close": _f(r["close"]),
            "volume": int(r["volume"]) if pd.notna(r["volume"]) else 0,
            "change_pct": _f(r.get("change_pct")),
            "range_pts": _f(r.get("range_pts")),
        }
        for _, r in df.iterrows()
    ]

    return {
        "id": key,
        "label": meta["label"],
        "lot_hint": meta["lot_hint"],
        "from_date": first["date"].strftime("%Y-%m-%d"),
        "to_date": last["date"].strftime("%Y-%m-%d"),
        "sessions": int(len(df)),
        "last": _day_row(last),
        "period_change_pct": _f(period_chg),
        "kpis": _kpis(df),
        "extremes": {
            "highest_close": _extreme(df, "close", "max"),
            "lowest_close": _extreme(df, "close", "min"),
            "biggest_up_day": _extreme(valid, "change", "max"),
            "biggest_down_day": _extreme(valid, "change", "min"),
            "highest_volume": _extreme(df, "volume", "max"),
            "lowest_volume": _extreme(
                df[df["volume"] > 0] if (df["volume"] > 0).any() else df, "volume", "min"
            ),
            "widest_range": _extreme(df, "range_pts", "max"),
            "tightest_range": _extreme(df, "range_pts", "min"),
            "largest_gap_up": _extreme(valid, "gap_pct", "max"),
            "largest_gap_down": _extreme(valid, "gap_pct", "min"),
        },
        "weekday": _weekday_stats(df),
        "streaks": _streaks(df),
        "pattern_counts": type_counts,
        "patterns": patterns,
        "interesting": _interesting_notes(df, patterns, type_counts),
        "series": series,
    }


def build_explain_prompt(
    index_id: str,
    topic: str,
    payload: dict[str, Any],
    analytics_slice: Optional[dict[str, Any]] = None,
) -> str:
    label = INDEX_META.get(index_id.upper(), {}).get("label", index_id)
    lines = [
        f"You are an index market researcher helping a trader study {label} daily behavior.",
        "Explain what this number/pattern means for F&O / index trading study.",
        "Be concrete, skeptical of overfitting, and avoid trade advice as guarantees.",
        "Respond in 3 short sections: (1) What the number says (2) Why it may matter "
        "(3) Caveats / what to check next. Keep under 220 words.",
        "",
        f"Topic key: {topic}",
        f"Payload JSON: {payload}",
    ]
    if analytics_slice:
        lines.append(f"Supporting context: {analytics_slice}")
    return "\n".join(lines)


def rule_based_explain(index_id: str, topic: str, payload: dict[str, Any]) -> str:
    """Fallback narrative when LLM is unavailable."""
    label = INDEX_META.get(index_id.upper(), {}).get("label", index_id)
    t = (topic or "").lower()
    key = t.split(":", 1)[-1]

    hints = {
        "avg_volume": f"Average daily volume on {label} is an activity proxy. Spikes often cluster with event days.",
        "avg_range_pts": "Average high−low range is the typical intraday playing field for premium and stop studies.",
        "avg_abs_move": "Average absolute close-to-close move shows how far the index usually finishes from yesterday.",
        "avg_change_pct": "Mean daily % return is usually near zero. Edge lives in gaps, tails, and weekday effects.",
        "green_pct": "Green-day share near 50% is normal. Large skew may reflect a trending sample window.",
        "avg_gap_pct": "Average |gap| measures overnight risk that shows up in the open auction.",
        "volatility": "Daily σ of returns is a simple realized-vol proxy.",
        "max_drawdown_pct": "Max drawdown is the worst peak-to-trough pain in this window.",
    }

    if key in hints or t.startswith("kpi:"):
        base = hints.get(key, f"Metric `{key}` on {label}.")
        return (
            f"**What it says**\n{base}\n\n"
            f"**Context**\nValue: {payload.get('display') or payload.get('value')}. "
            f"{payload.get('hint') or ''}\n\n"
            "**Caveat**\nOne-year Yahoo daily data is a study sample, not live exchange microstructure."
        )

    summary = payload.get("summary") or payload.get("text") or payload.get("title") or topic
    return (
        f"**What it says**\n{summary}\n\n"
        f"**Why it may matter**\nOn {label}, gaps, sudden falls, and volume spikes often cluster around "
        "macro prints and heavy flow days. Check whether the move continued next day or mean-reverted.\n\n"
        "**Caveat**\nThese are threshold heuristics on daily bars — confirm on lower timeframes before "
        "treating as an edge."
    )
