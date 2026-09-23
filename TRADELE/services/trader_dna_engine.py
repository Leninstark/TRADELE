"""Trader DNA quantitative engine — FIFO reconstruction + full performance audit stats."""
from __future__ import annotations

import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from statistics import median
from typing import Any, Optional

from TRADELE.db.models import JournalFill

logger = logging.getLogger(__name__)

STYLE_BUCKETS = (
    "intraday",
    "short_swing",
    "swing",
    "extended_swing",
    "positional",
)

HOLDING_BUCKETS = (
    ("same_day", 0, 0),
    ("1_day", 1, 1),
    ("2_3_days", 2, 3),
    ("4_7_days", 4, 7),
    ("8_14_days", 8, 14),
    ("15_30_days", 15, 30),
    ("31_60_days", 31, 60),
    ("61_90_days", 61, 90),
    ("90_plus_days", 91, 10_000),
)

ENTRY_BUCKETS = (
    ("09:15-09:30", 9, 15, 9, 30),
    ("09:30-10:00", 9, 30, 10, 0),
    ("10:00-11:00", 10, 0, 11, 0),
    ("11:00-12:00", 11, 0, 12, 0),
    ("12:00-13:00", 12, 0, 13, 0),
    ("13:00-14:00", 13, 0, 14, 0),
    ("14:00-15:00", 14, 0, 15, 0),
    ("15:00-15:30", 15, 0, 15, 30),
)


@dataclass
class Lot:
    qty: float
    price: float
    opened_at: datetime
    product: Optional[str] = None
    side: str = "LONG"  # LONG inventory or SHORT inventory


@dataclass
class CompletedTrade:
    symbol: str
    segment: str
    instrument: str
    direction: str  # long | short
    qty: float
    entry_price: float
    exit_price: float
    entry_at: datetime
    exit_at: datetime
    product: Optional[str]
    capital: float
    pnl: float
    pnl_pct: float
    hold_minutes: float
    hold_hours: float
    hold_calendar_days: int
    hold_trading_days: int
    style: str


def _r(v: float, n: int = 2) -> float:
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return 0.0
    return round(float(v), n)


def _safe_median(vals: list[float]) -> Optional[float]:
    if not vals:
        return None
    return _r(float(median(vals)), 4)


def _trading_days_between(a: date, b: date) -> int:
    """Approximate trading days (exclude Sat/Sun)."""
    if b < a:
        a, b = b, a
    days = 0
    cur = a
    while cur <= b:
        if cur.weekday() < 5:
            days += 1
        cur += timedelta(days=1)
    return max(days - 1, 0)  # exclusive of overnight count nuance; 0 = same day


def classify_style(hold_trading_days: int, entry_at: datetime, exit_at: datetime) -> str:
    if entry_at.date() == exit_at.date() or hold_trading_days <= 0:
        return "intraday"
    if hold_trading_days <= 3:
        return "short_swing"
    if hold_trading_days <= 20:
        return "swing"
    if hold_trading_days <= 60:
        return "extended_swing"
    return "positional"


def holding_bucket(hold_trading_days: int, same_day: bool) -> str:
    if same_day:
        return "same_day"
    d = max(hold_trading_days, 1)
    for name, lo, hi in HOLDING_BUCKETS:
        if name == "same_day":
            continue
        if lo <= d <= hi:
            return name
    return "90_plus_days"


def time_bucket(dt: datetime) -> str:
    mins = dt.hour * 60 + dt.minute
    for name, h1, m1, h2, m2 in ENTRY_BUCKETS:
        start = h1 * 60 + m1
        end = h2 * 60 + m2
        if start <= mins < end or (name.endswith("15:30") and start <= mins <= end):
            return name
    if mins < 9 * 60 + 15:
        return "pre_open"
    return "other"


def fifo_reconstruct(fills: list[JournalFill]) -> dict[str, Any]:
    """FIFO match per (symbol, segment). Returns completed, open, excluded meta."""
    by_key: dict[tuple[str, str], list[JournalFill]] = defaultdict(list)
    excluded: list[dict[str, Any]] = []
    for f in fills:
        if not f.symbol or float(f.quantity or 0) <= 0:
            excluded.append({"reason": "zero_qty_or_no_symbol", "id": f.id})
            continue
        by_key[(f.symbol.upper(), (f.segment or "CASH").upper())].append(f)

    completed: list[CompletedTrade] = []
    open_positions: list[dict[str, Any]] = []

    for (sym, seg), flist in by_key.items():
        flist = sorted(flist, key=lambda x: (x.trade_datetime, x.id or 0))
        long_lots: list[Lot] = []
        short_lots: list[Lot] = []
        instrument = flist[0].instrument or "equity"

        def close_against(
            lots: list[Lot],
            qty: float,
            px: float,
            when: datetime,
            product: Optional[str],
            direction: str,
        ) -> float:
            nonlocal completed
            remaining = qty
            while remaining > 1e-9 and lots:
                lot = lots[0]
                take = min(lot.qty, remaining)
                if direction == "long":
                    # closing long with sell
                    entry_px, exit_px = lot.price, px
                    entry_at, exit_at = lot.opened_at, when
                else:
                    # closing short with buy
                    entry_px, exit_px = lot.price, px
                    entry_at, exit_at = lot.opened_at, when
                pnl = (exit_px - entry_px) * take if direction == "long" else (entry_px - exit_px) * take
                capital = abs(entry_px * take)
                pnl_pct = (pnl / capital * 100) if capital else 0.0
                hold_min = max((exit_at - entry_at).total_seconds() / 60.0, 0)
                hold_td = _trading_days_between(entry_at.date(), exit_at.date())
                style = classify_style(hold_td, entry_at, exit_at)
                completed.append(
                    CompletedTrade(
                        symbol=sym,
                        segment=seg,
                        instrument=instrument,
                        direction=direction,
                        qty=take,
                        entry_price=_r(entry_px, 4),
                        exit_price=_r(exit_px, 4),
                        entry_at=entry_at,
                        exit_at=exit_at,
                        product=lot.product or product,
                        capital=_r(capital),
                        pnl=_r(pnl),
                        pnl_pct=_r(pnl_pct, 4),
                        hold_minutes=_r(hold_min, 1),
                        hold_hours=_r(hold_min / 60.0, 2),
                        hold_calendar_days=max((exit_at.date() - entry_at.date()).days, 0),
                        hold_trading_days=hold_td,
                        style=style,
                    )
                )
                lot.qty -= take
                remaining -= take
                if lot.qty <= 1e-9:
                    lots.pop(0)
            return remaining

        for f in flist:
            side = (f.side or "").upper()
            qty = float(f.quantity)
            px = float(f.price)
            when = f.trade_datetime
            product = f.product
            if side == "BUY":
                rem = close_against(short_lots, qty, px, when, product, "short")
                if rem > 1e-9:
                    long_lots.append(Lot(rem, px, when, product, "LONG"))
            elif side == "SELL":
                rem = close_against(long_lots, qty, px, when, product, "long")
                if rem > 1e-9:
                    short_lots.append(Lot(rem, px, when, product, "SHORT"))

        for lot in long_lots:
            open_positions.append(
                {
                    "symbol": sym,
                    "segment": seg,
                    "direction": "long",
                    "qty": _r(lot.qty, 4),
                    "avg_price": _r(lot.price, 4),
                    "opened_at": lot.opened_at.isoformat(),
                    "product": lot.product,
                }
            )
        for lot in short_lots:
            open_positions.append(
                {
                    "symbol": sym,
                    "segment": seg,
                    "direction": "short",
                    "qty": _r(lot.qty, 4),
                    "avg_price": _r(lot.price, 4),
                    "opened_at": lot.opened_at.isoformat(),
                    "product": lot.product,
                }
            )

    return {
        "completed": completed,
        "open_positions": open_positions,
        "excluded": excluded,
        "methodology": (
            "FIFO matching per (symbol, segment). Buys close short lots first then open longs; "
            "sells close long lots first then open shorts. Partial fills and scale-in/out are supported. "
            "Holding-period style is from actual dates (not product type)."
        ),
    }


def _trade_metrics(trades: list[CompletedTrade]) -> dict[str, Any]:
    if not trades:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "breakeven": 0,
            "win_rate": None,
            "gross_profit": 0,
            "gross_loss": 0,
            "net_pnl": 0,
            "avg_win": None,
            "avg_loss": None,
            "median_win": None,
            "median_loss": None,
            "largest_winner": None,
            "largest_loser": None,
            "profit_factor": None,
            "expectancy": None,
            "expectancy_pct": None,
            "avg_hold_hours": None,
            "median_hold_hours": None,
            "total_capital": 0,
            "avg_return_pct": None,
            "median_return_pct": None,
            "max_consec_wins": 0,
            "max_consec_losses": 0,
        }
    pnls = [t.pnl for t in trades]
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl < 0]
    be = [t for t in trades if t.pnl == 0]
    gp = sum(t.pnl for t in wins)
    gl = abs(sum(t.pnl for t in losses))
    net = sum(pnls)
    wr = len(wins) / len(trades) * 100
    pf = (gp / gl) if gl > 0 else (None if gp <= 0 else 99.0)
    exp = net / len(trades)
    rets = [t.pnl_pct for t in trades]
    holds = [t.hold_hours for t in trades]

    # consecutive
    max_w = max_l = cur_w = cur_l = 0
    for t in sorted(trades, key=lambda x: x.exit_at):
        if t.pnl > 0:
            cur_w += 1
            cur_l = 0
            max_w = max(max_w, cur_w)
        elif t.pnl < 0:
            cur_l += 1
            cur_w = 0
            max_l = max(max_l, cur_l)
        else:
            cur_w = cur_l = 0

    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": len(be),
        "win_rate": _r(wr, 2),
        "gross_profit": _r(gp),
        "gross_loss": _r(gl),
        "net_pnl": _r(net),
        "avg_win": _r(sum(t.pnl for t in wins) / len(wins)) if wins else None,
        "avg_loss": _r(sum(t.pnl for t in losses) / len(losses)) if losses else None,
        "median_win": _safe_median([t.pnl for t in wins]),
        "median_loss": _safe_median([t.pnl for t in losses]),
        "largest_winner": _r(max(pnls)) if pnls else None,
        "largest_loser": _r(min(pnls)) if pnls else None,
        "profit_factor": _r(pf, 3) if pf is not None else None,
        "expectancy": _r(exp),
        "expectancy_pct": _r(sum(rets) / len(rets), 4) if rets else None,
        "avg_hold_hours": _r(sum(holds) / len(holds), 2) if holds else None,
        "median_hold_hours": _safe_median(holds),
        "total_capital": _r(sum(t.capital for t in trades)),
        "avg_return_pct": _r(sum(rets) / len(rets), 4) if rets else None,
        "median_return_pct": _safe_median(rets),
        "max_consec_wins": max_w,
        "max_consec_losses": max_l,
    }


def _drawdown_curve(trades: list[CompletedTrade]) -> tuple[list[dict[str, Any]], float]:
    ordered = sorted(trades, key=lambda t: t.exit_at)
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    curve: list[dict[str, Any]] = []
    for t in ordered:
        equity += t.pnl
        peak = max(peak, equity)
        dd = peak - equity
        max_dd = max(max_dd, dd)
        curve.append(
            {
                "date": t.exit_at.date().isoformat(),
                "equity": _r(equity),
                "drawdown": _r(dd),
            }
        )
    return curve, _r(max_dd)


def build_trader_dna_stats(fills: list[JournalFill]) -> dict[str, Any]:
    recon = fifo_reconstruct(fills)
    completed: list[CompletedTrade] = recon["completed"]
    overall = _trade_metrics(completed)
    curve, max_dd = _drawdown_curve(completed)
    recovery = (_r(overall["net_pnl"] / max_dd, 3) if max_dd > 0 else None)

    # Style comparison
    by_style: dict[str, list[CompletedTrade]] = {s: [] for s in STYLE_BUCKETS}
    for t in completed:
        by_style.setdefault(t.style, []).append(t)
    style_table = {s: _trade_metrics(by_style.get(s, [])) for s in STYLE_BUCKETS}
    style_edge = None
    best_score = -1e18
    for s, m in style_table.items():
        n = m["trades"]
        if n < 5:
            continue
        score = (m.get("expectancy") or 0) * math.log1p(n) + (m.get("profit_factor") or 0)
        if score > best_score:
            best_score = score
            style_edge = s

    # Holding buckets
    hold_groups: dict[str, list[CompletedTrade]] = defaultdict(list)
    for t in completed:
        hold_groups[holding_bucket(t.hold_trading_days, t.entry_at.date() == t.exit_at.date())].append(t)
    holding_table = {
        name: _trade_metrics(hold_groups.get(name, []))
        for name, _, _ in HOLDING_BUCKETS
    }

    # Entry / exit timing
    entry_groups: dict[str, list[CompletedTrade]] = defaultdict(list)
    exit_groups: dict[str, list[CompletedTrade]] = defaultdict(list)
    for t in completed:
        entry_groups[time_bucket(t.entry_at)].append(t)
        exit_groups[time_bucket(t.exit_at)].append(t)
    entry_timing = {k: _trade_metrics(v) for k, v in sorted(entry_groups.items())}
    exit_timing = {k: _trade_metrics(v) for k, v in sorted(exit_groups.items())}
    opening = entry_groups.get("09:15-09:30", [])
    opening_bias = {
        "trades": len(opening),
        "share_pct": _r(len(opening) / len(completed) * 100, 2) if completed else 0,
        "metrics": _trade_metrics(opening),
        "note": (
            "Opening entries are a large share of activity."
            if completed and len(opening) / len(completed) >= 0.25
            else "No strong opening-period concentration."
        ),
    }

    # Winner vs loser behavior
    wins = [t for t in completed if t.pnl > 0]
    losses = [t for t in completed if t.pnl < 0]
    med_w = _safe_median([t.hold_hours for t in wins])
    med_l = _safe_median([t.hold_hours for t in losses])
    winner_loser = {
        "winners": {
            "count": len(wins),
            "median_hold_hours": med_w,
            "avg_hold_hours": _r(sum(t.hold_hours for t in wins) / len(wins), 2) if wins else None,
            "avg_capital": _r(sum(t.capital for t in wins) / len(wins)) if wins else None,
            "median_entry_bucket": None,
        },
        "losers": {
            "count": len(losses),
            "median_hold_hours": med_l,
            "avg_hold_hours": _r(sum(t.hold_hours for t in losses) / len(losses), 2) if losses else None,
            "avg_capital": _r(sum(t.capital for t in losses) / len(losses)) if losses else None,
        },
        "hold_ratio_winners_over_losers": _r(med_w / med_l, 3) if med_w and med_l and med_l > 0 else None,
        "interpretation": (
            "Data is consistent with holding losers longer than winners."
            if med_w is not None and med_l is not None and med_l > med_w * 1.15
            else (
                "Winners held longer than losers (ratio > 1)."
                if med_w is not None and med_l is not None and med_w > med_l * 1.15
                else "No clear winner/loser holding asymmetry."
            )
        ),
    }

    # Profit concentration
    win_sorted = sorted(wins, key=lambda t: t.pnl, reverse=True)
    total_gp = sum(t.pnl for t in wins) or 1.0
    top1 = sum(t.pnl for t in win_sorted[:1])
    top5 = sum(t.pnl for t in win_sorted[:5])
    top10 = sum(t.pnl for t in win_sorted[:10])
    without = {}
    for label, n in (("remove_top_1", 1), ("remove_top_5", 5), ("remove_top_10", 10)):
        skip = {id(t) for t in win_sorted[:n]}
        subset = [t for t in completed if id(t) not in skip]
        without[label] = _trade_metrics(subset)
    profit_distribution = {
        "top_1_pct_of_gross_profit": _r(top1 / total_gp * 100, 2) if wins else None,
        "top_5_pct_of_gross_profit": _r(top5 / total_gp * 100, 2) if wins else None,
        "top_10_pct_of_gross_profit": _r(top10 / total_gp * 100, 2) if wins else None,
        "bottom_5_losers": [
            {"symbol": t.symbol, "pnl": t.pnl, "exit": t.exit_at.isoformat()}
            for t in sorted(losses, key=lambda x: x.pnl)[:5]
        ],
        "bottom_10_losers": [
            {"symbol": t.symbol, "pnl": t.pnl, "exit": t.exit_at.isoformat()}
            for t in sorted(losses, key=lambda x: x.pnl)[:10]
        ],
        "performance_without": without,
        "note": (
            "Profitability is concentrated in a few winners."
            if wins and top5 / total_gp >= 0.5
            else "Profits look relatively broad-based across winners."
            if wins
            else "No winning trades."
        ),
    }

    # Stock-wise
    by_sym: dict[str, list[CompletedTrade]] = defaultdict(list)
    for t in completed:
        by_sym[t.symbol].append(t)
    stock_rows = []
    for sym, ts in by_sym.items():
        m = _trade_metrics(ts)
        stock_rows.append(
            {
                "symbol": sym,
                **m,
                "avg_hold_hours": m.get("avg_hold_hours"),
            }
        )
    stock_rows.sort(key=lambda r: r.get("net_pnl") or 0, reverse=True)
    repeated_poor = [
        r for r in stock_rows
        if (r.get("trades") or 0) >= 4 and (r.get("net_pnl") or 0) < 0 and (r.get("win_rate") or 0) < 45
    ]

    # Position sizing quintiles
    if completed:
        caps = sorted(t.capital for t in completed)
        def quintile(c: float) -> int:
            # 0..4
            rank = sum(1 for x in caps if x <= c) / len(caps)
            return min(4, max(0, int(math.ceil(rank * 5) - 1)))
        q_groups: dict[int, list[CompletedTrade]] = defaultdict(list)
        for t in completed:
            q_groups[quintile(t.capital)].append(t)
        size_table = {
            f"q{i+1}": _trade_metrics(q_groups.get(i, [])) for i in range(5)
        }
    else:
        size_table = {f"q{i+1}": _trade_metrics([]) for i in range(5)}

    # Sequence after win/loss
    ordered = sorted(completed, key=lambda t: t.exit_at)
    after_win: list[CompletedTrade] = []
    after_loss: list[CompletedTrade] = []
    size_after_win: list[float] = []
    size_after_loss: list[float] = []
    for i in range(len(ordered) - 1):
        cur, nxt = ordered[i], ordered[i + 1]
        if cur.pnl > 0:
            after_win.append(nxt)
            size_after_win.append(nxt.capital / cur.capital if cur.capital else 1)
        elif cur.pnl < 0:
            after_loss.append(nxt)
            size_after_loss.append(nxt.capital / cur.capital if cur.capital else 1)
    sequence = {
        "after_win": {
            **_trade_metrics(after_win),
            "avg_size_vs_prior": _r(sum(size_after_win) / len(size_after_win), 3) if size_after_win else None,
        },
        "after_loss": {
            **_trade_metrics(after_loss),
            "avg_size_vs_prior": _r(sum(size_after_loss) / len(size_after_loss), 3) if size_after_loss else None,
        },
        "caution": (
            "The data is consistent with size escalation after losses (possible revenge / loss chasing)."
            if size_after_loss and (sum(size_after_loss) / len(size_after_loss)) > 1.2
            else "No strong size-escalation pattern after losses in this sample."
        ),
    }

    # Overtrading
    by_day: dict[date, list[CompletedTrade]] = defaultdict(list)
    for t in ordered:
        by_day[t.entry_at.date()].append(t)
    day_counts = [len(v) for v in by_day.values()] if by_day else []
    med_day = _safe_median([float(x) for x in day_counts]) or 1
    high_days = {d: ts for d, ts in by_day.items() if len(ts) > max(med_day * 1.5, med_day + 1)}
    normal_days = {d: ts for d, ts in by_day.items() if d not in high_days}
    high_trades = [t for ts in high_days.values() for t in ts]
    normal_trades = [t for ts in normal_days.values() for t in ts]
    same_day_reentry = 0
    for d, ts in by_day.items():
        syms = defaultdict(int)
        for t in ts:
            syms[t.symbol] += 1
        same_day_reentry += sum(1 for c in syms.values() if c >= 2)
    overtrading = {
        "trades_per_day_avg": _r(sum(day_counts) / len(day_counts), 2) if day_counts else 0,
        "trades_per_day_median": med_day,
        "high_activity_days": len(high_days),
        "high_activity_metrics": _trade_metrics(high_trades),
        "normal_activity_metrics": _trade_metrics(normal_trades),
        "same_day_multi_symbol_sessions": same_day_reentry,
        "note": (
            "High-activity days underperform normal days on expectancy."
            if (high_trades and normal_trades
                and (_trade_metrics(high_trades).get("expectancy") or 0)
                < (_trade_metrics(normal_trades).get("expectancy") or 0))
            else "No clear penalty for high-activity days in this sample."
        ),
    }

    # Day of week / monthly
    dow_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    dow_groups: dict[str, list[CompletedTrade]] = defaultdict(list)
    month_groups: dict[str, list[CompletedTrade]] = defaultdict(list)
    for t in completed:
        dow_groups[dow_names[t.entry_at.weekday()]].append(t)
        month_groups[t.exit_at.strftime("%Y-%m")].append(t)
    day_of_week = {k: _trade_metrics(v) for k, v in dow_groups.items()}
    monthly = [
        {"month": m, **_trade_metrics(ts)}
        for m, ts in sorted(month_groups.items())
    ]

    # Style drift: losers becoming extended
    loser_ext = sum(1 for t in losses if t.style in ("extended_swing", "positional"))
    winner_ext = sum(1 for t in wins if t.style in ("extended_swing", "positional"))
    style_drift = {
        "pct_losers_extended": _r(loser_ext / len(losses) * 100, 2) if losses else None,
        "pct_winners_extended": _r(winner_ext / len(wins) * 100, 2) if wins else None,
        "potential_drift_trades": sum(
            1
            for t in completed
            if t.product and t.product.upper() == "MIS" and t.style != "intraday"
        ),
        "note": (
            "Losing trades are more likely to become extended holdings than winners."
            if losses and wins and (loser_ext / max(len(losses), 1)) > (winner_ext / max(len(wins), 1)) + 0.05
            else "No strong evidence that losers are preferentially held longer into extended styles."
        ),
        "intention_disclaimer": "Potential style drift — cannot confirm intention from fills alone.",
    }

    # Risk
    max_pos = max((t.capital for t in completed), default=0)
    total_cap = sum(t.capital for t in completed) or 1
    risk = {
        "largest_position": _r(max_pos),
        "largest_position_pct_of_total_deployed": _r(max_pos / total_cap * 100, 2),
        "largest_loss": overall.get("largest_loser"),
        "max_drawdown": max_dd,
        "recovery_factor": recovery,
        "max_consec_losses": overall.get("max_consec_losses"),
        "rating": (
            "Dangerous"
            if max_dd > 0 and overall["net_pnl"] < 0 and (overall.get("max_consec_losses") or 0) >= 6
            else "Weak"
            if max_dd > abs(overall["net_pnl"]) * 1.5 and overall["net_pnl"] > 0
            else "Average"
            if max_dd > 0
            else "Good"
        ),
    }

    # Scorecard (0-10 heuristic from metrics)
    def score_style(key: str) -> Any:
        m = style_table.get(key) or {}
        n = m.get("trades") or 0
        if n < 5:
            return "Insufficient evidence"
        exp = m.get("expectancy") or 0
        pf = m.get("profit_factor") or 0
        wr = m.get("win_rate") or 0
        s = 5
        s += 2 if exp > 0 else -2
        s += 1 if pf and pf >= 1.2 else -1
        s += 1 if wr >= 50 else 0
        s += 1 if n >= 20 else 0
        return max(1, min(10, int(round(s))))

    scorecard = {
        "intraday_ability": score_style("intraday"),
        "swing_ability": score_style("swing") if (style_table.get("swing") or {}).get("trades", 0) >= 5 else score_style("short_swing"),
        "positional_ability": score_style("positional"),
        "entry_timing": (
            7 if opening_bias["share_pct"] < 40 and (overall.get("expectancy") or 0) > 0 else 5
            if completed
            else "Insufficient evidence"
        ),
        "exit_discipline": (
            4 if winner_loser.get("hold_ratio_winners_over_losers") and winner_loser["hold_ratio_winners_over_losers"] < 0.85
            else 7 if winner_loser.get("hold_ratio_winners_over_losers") and winner_loser["hold_ratio_winners_over_losers"] >= 1
            else 5
        ),
        "risk_management": {"Excellent": 9, "Good": 7, "Average": 5, "Weak": 3, "Dangerous": 1}.get(risk["rating"], 5),
        "position_sizing": 5,
        "loss_control": max(1, 10 - int(overall.get("max_consec_losses") or 0)),
        "profit_capture": 4 if (profit_distribution.get("top_5_pct_of_gross_profit") or 0) >= 60 else 7,
        "consistency": 6 if len(monthly) >= 3 else "Insufficient evidence",
        "overtrading_control": 4 if "underperform" in overtrading["note"].lower() else 7,
        "emotional_discipline": "Insufficient evidence",
    }

    # What-if: avoid weakest style by expectancy (min 5 trades)
    weakest = None
    weak_exp = 1e18
    for s, m in style_table.items():
        if (m.get("trades") or 0) >= 5 and (m.get("expectancy") or 0) < weak_exp:
            weak_exp = m.get("expectancy") or 0
            weakest = s
    what_if_trades = [t for t in completed if t.style != weakest] if weakest else list(completed)
    what_if = {
        "avoid_style": weakest,
        "metrics": _trade_metrics(what_if_trades),
        "baseline_net": overall.get("net_pnl"),
        "assumption": f"Historical replay excluding all '{weakest}' classified trades." if weakest else "No style excluded.",
    }

    # Optimal holding: best expectancy with n>=8
    best_hold = None
    best_hold_score = -1e18
    for name, m in holding_table.items():
        n = m.get("trades") or 0
        if n < 8:
            continue
        sc = (m.get("expectancy") or 0) * math.log1p(n)
        if sc > best_hold_score:
            best_hold_score = sc
            best_hold = name

    # Charts
    cum = []
    eq = 0.0
    for t in ordered:
        eq += t.pnl
        cum.append({"date": t.exit_at.date().isoformat(), "pnl": _r(eq)})
    monthly_pnl = [{"date": m["month"] + "-01", "pnl": m.get("net_pnl") or 0} for m in monthly]
    style_pnl = [{"label": s, "pnl": (style_table[s].get("net_pnl") or 0), "n": style_table[s].get("trades") or 0} for s in STYLE_BUCKETS]
    hold_wr = [
        {
            "label": name,
            "win_rate": (holding_table[name].get("win_rate") or 0),
            "expectancy": (holding_table[name].get("expectancy") or 0),
            "n": holding_table[name].get("trades") or 0,
        }
        for name, _, _ in HOLDING_BUCKETS
    ]
    entry_chart = [
        {"label": k, "pnl": v.get("net_pnl") or 0, "n": v.get("trades") or 0, "expectancy": v.get("expectancy") or 0}
        for k, v in entry_timing.items()
    ]
    exit_chart = [
        {"label": k, "pnl": v.get("net_pnl") or 0, "n": v.get("trades") or 0}
        for k, v in exit_timing.items()
    ]
    size_chart = [
        {"label": k, "expectancy": v.get("expectancy") or 0, "win_rate": v.get("win_rate") or 0, "n": v.get("trades") or 0}
        for k, v in size_table.items()
    ]
    freq = [{"date": d.isoformat(), "count": len(ts)} for d, ts in sorted(by_day.items())]

    fills_through = max((f.trade_datetime for f in fills), default=None)
    equity_vs_fno = {
        "equity": _trade_metrics([t for t in completed if t.instrument != "fno"]),
        "fno": _trade_metrics([t for t in completed if t.instrument == "fno"]),
    }

    return {
        "data_quality": {
            "fill_count": len(fills),
            "completed_trades": len(completed),
            "open_positions": len(recon["open_positions"]),
            "excluded": len(recon["excluded"]),
            "fills_through": fills_through.isoformat() if fills_through else None,
            "date_range": {
                "from": min((f.trade_date for f in fills), default=None).isoformat()
                if fills
                else None,
                "to": max((f.trade_date for f in fills), default=None).isoformat()
                if fills
                else None,
            },
            "methodology": recon["methodology"],
            "limitations": [
                "FOMO/chasing cannot be reliably established from order history alone.",
                "MFE/MAE and post-exit path require candle data — not computed in v1.",
                "Market regime (NIFTY/VIX) analysis is stage-2 — not computed in v1.",
                "Costs/taxes/slippage not deducted — figures are gross from fills.",
            ],
        },
        "overall": {**overall, "max_drawdown": max_dd, "recovery_factor": recovery},
        "style_table": style_table,
        "strongest_style_by_stats": style_edge,
        "style_sample_warning": "Categories with fewer than 5 trades are unreliable.",
        "holding_table": holding_table,
        "optimal_holding_bucket": best_hold,
        "entry_timing": entry_timing,
        "exit_timing": exit_timing,
        "opening_bias": opening_bias,
        "winner_loser": winner_loser,
        "profit_distribution": profit_distribution,
        "stocks": {
            "ranked": stock_rows[:50],
            "best": stock_rows[:10],
            "worst": list(reversed(stock_rows[-10:])) if stock_rows else [],
            "repeated_poor": repeated_poor[:15],
        },
        "position_sizing": size_table,
        "sequence": sequence,
        "overtrading": overtrading,
        "fomo": {
            "status": "unavailable",
            "message": "FOMO/chasing cannot be reliably established from order history alone.",
        },
        "risk": risk,
        "market_condition": {
            "status": "stage_2",
            "message": "NIFTY/VIX regime split recommended as second-stage analysis.",
        },
        "style_drift": style_drift,
        "day_of_week": day_of_week,
        "monthly": monthly,
        "scorecard": scorecard,
        "what_if": what_if,
        "equity_vs_fno": equity_vs_fno,
        "open_positions": recon["open_positions"][:100],
        "sample_trades": [
            {
                "symbol": t.symbol,
                "direction": t.direction,
                "style": t.style,
                "pnl": t.pnl,
                "pnl_pct": t.pnl_pct,
                "hold_hours": t.hold_hours,
                "entry_at": t.entry_at.isoformat(),
                "exit_at": t.exit_at.isoformat(),
                "product": t.product,
            }
            for t in ordered[:30]
        ],
        "charts": {
            "cumulative_pnl": cum,
            "monthly_pnl": monthly_pnl,
            "style_pnl": style_pnl,
            "holding_win_rate": hold_wr,
            "entry_timing": entry_chart,
            "exit_timing": exit_chart,
            "position_sizing": size_chart,
            "drawdown": curve,
            "trade_frequency": freq,
            "top_stocks": [
                {"label": r["symbol"], "pnl": r.get("net_pnl") or 0, "n": r.get("trades") or 0}
                for r in stock_rows[:15]
            ],
            "winner_loser_hold": {
                "winners_median_hours": med_w,
                "losers_median_hours": med_l,
            },
        },
    }
