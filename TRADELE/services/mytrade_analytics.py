"""MyTrade performance KPIs split by Equity Intraday (MIS) vs Swing (CNC) vs F&O."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any, Literal, Optional

from TRADELE.db.models import GrowwOrder, GrowwTrade, GrowwTradingDay

Style = Literal["intraday", "swing", "fno"]
CalendarStyle = Style

INTRADAY_PRODUCTS = {"MIS"}
SWING_PRODUCTS = {"CNC", "NRML"}
FNO_SEGMENTS = {"FNO", "F&O", "FO", "DERIVATIVE", "DERIVATIVES"}
EQUITY_SEGMENTS = {"CASH", "NSE", "BSE", "EQ", ""}


def normalize_segment(segment: Optional[str]) -> str:
    s = (segment or "").strip().upper().replace(" ", "")
    if s in FNO_SEGMENTS or s.replace("&", "") in {"FNO", "FO"}:
        return "FNO"
    return "CASH"


def matches_calendar_style(
    *,
    product: Optional[str],
    segment: Optional[str],
    style: str,
) -> bool:
    """Separate books: Equity Intraday (MIS), Equity Swing (CNC/NRML cash), F&O (segment)."""
    p = (product or "").strip().upper()
    seg = normalize_segment(segment)
    key = (style or "intraday").strip().lower()
    if key == "fno":
        return seg == "FNO"
    if key == "intraday":
        return p == "MIS" and seg != "FNO"
    if key == "swing":
        return seg != "FNO" and p in SWING_PRODUCTS
    return False


def products_for_calendar_style(style: str) -> Optional[set[str]]:
    """Product set for position P&L merge (None = any product on filtered rows)."""
    key = (style or "intraday").strip().lower()
    if key == "fno":
        return None
    if key == "intraday":
        return set(INTRADAY_PRODUCTS)
    if key == "swing":
        return set(SWING_PRODUCTS)
    return set(INTRADAY_PRODUCTS)


def filter_trades_for_style(trades: list[GrowwTrade], style: str) -> list[GrowwTrade]:
    return [
        t
        for t in trades
        if matches_calendar_style(product=t.product, segment=t.segment, style=style)
    ]


def filter_orders_for_style(orders: list[GrowwOrder], style: str) -> list[GrowwOrder]:
    return [
        o
        for o in orders
        if matches_calendar_style(product=o.product, segment=o.segment, style=style)
    ]


def filter_positions_for_style(positions: list[dict[str, Any]], style: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for pos in dedupe_positions(positions):
        seg = pos.get("segment") or pos.get("segment_name") or pos.get("exchange_segment")
        if matches_calendar_style(product=pos.get("product"), segment=seg, style=style):
            out.append(pos)
    return out


def classify_style(product: Optional[str], segment: Optional[str] = None) -> Optional[Style]:
    """Classify a fill/order into calendar books (segment-aware)."""
    if matches_calendar_style(product=product, segment=segment, style="fno"):
        return "fno"
    if matches_calendar_style(product=product, segment=segment, style="intraday"):
        return "intraday"
    if matches_calendar_style(product=product, segment=segment, style="swing"):
        return "swing"
    return None


def dedupe_positions(positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Groww often returns the same MIS book twice (NSE + BSE) with identical realised_pnl.
    Deduplicate by trading_symbol + product so P&L is not double-counted.
    """
    best: dict[tuple[str, str], dict[str, Any]] = {}
    for pos in positions:
        if not isinstance(pos, dict):
            continue
        symbol = str(pos.get("trading_symbol") or "").strip().upper()
        product = str(pos.get("product") or "").strip().upper()
        if not symbol:
            continue
        key = (symbol, product)
        try:
            pnl = float(pos.get("realised_pnl") or 0)
        except (TypeError, ValueError):
            pnl = 0.0
        qty = 0
        try:
            qty = abs(int(pos.get("quantity") or 0))
        except (TypeError, ValueError):
            qty = 0

        existing = best.get(key)
        if existing is None:
            best[key] = {**pos, "realised_pnl": pnl, "trading_symbol": symbol, "product": product}
            continue

        # Same symbol/product on another exchange — keep one row (prefer closed qty=0, else larger |pnl|)
        try:
            ex_pnl = float(existing.get("realised_pnl") or 0)
            ex_qty = abs(int(existing.get("quantity") or 0))
        except (TypeError, ValueError):
            ex_pnl, ex_qty = 0.0, 0

        if abs(pnl - ex_pnl) < 0.01:
            # Identical P&L — keep closed row if available
            if qty == 0 and ex_qty != 0:
                best[key] = {**pos, "realised_pnl": pnl, "trading_symbol": symbol, "product": product}
            continue
        if abs(pnl) > abs(ex_pnl):
            best[key] = {**pos, "realised_pnl": pnl, "trading_symbol": symbol, "product": product}

    return list(best.values())


def sum_realised_pnl(positions: list[dict[str, Any]], *, products: Optional[set[str]] = None) -> float:
    total = 0.0
    for pos in dedupe_positions(positions):
        product = str(pos.get("product") or "").upper()
        if products is not None and product not in products:
            continue
        try:
            total += float(pos.get("realised_pnl") or 0)
        except (TypeError, ValueError):
            pass
    return round(total, 2)


def _filter_trades(trades: list[GrowwTrade], style: Style) -> list[GrowwTrade]:
    products = INTRADAY_PRODUCTS if style == "intraday" else SWING_PRODUCTS
    return [t for t in trades if (t.product or "").upper() in products]


def _filter_orders(orders: list[GrowwOrder], style: Style) -> list[GrowwOrder]:
    products = INTRADAY_PRODUCTS if style == "intraday" else SWING_PRODUCTS
    return [o for o in orders if (o.product or "").upper() in products]


def _style_positions(day: GrowwTradingDay, style: Style) -> list[dict[str, Any]]:
    summary = day.summary or {}
    positions = summary.get("positions") if isinstance(summary, dict) else None
    if not isinstance(positions, list):
        return []
    products = INTRADAY_PRODUCTS if style == "intraday" else SWING_PRODUCTS
    return [
        p
        for p in dedupe_positions(positions)
        if str(p.get("product") or "").upper() in products
    ]


def _style_positions_pnl(day: GrowwTradingDay, style: Style) -> float:
    return round(sum(float(p.get("realised_pnl") or 0) for p in _style_positions(day, style)), 2)


def _symbol_pnl_from_positions(days: list[GrowwTradingDay], style: Style) -> dict[str, float]:
    """Latest known realised P&L per symbol from Groww positions (authoritative for the day)."""
    by_symbol: dict[str, float] = {}
    for day in sorted(days, key=lambda d: d.trade_date):
        for p in _style_positions(day, style):
            symbol = str(p.get("trading_symbol") or "")
            if not symbol:
                continue
            by_symbol[symbol] = round(float(p.get("realised_pnl") or 0), 2)
    return by_symbol


def _symbol_day_pnl_from_trades(trades: list[GrowwTrade]) -> list[dict[str, Any]]:
    """
    Net P&L per symbol per day from fills (sell value - buy value) when qty is flat.
    Used as fallback when positions snapshot is missing.
    """
    buckets: dict[tuple[date, str], dict[str, float]] = defaultdict(
        lambda: {"buy_qty": 0.0, "sell_qty": 0.0, "buy_val": 0.0, "sell_val": 0.0}
    )
    for t in trades:
        key = (t.trade_date, t.trading_symbol)
        side = (t.transaction_type or "").upper()
        qty = float(t.quantity or 0)
        val = qty * float(t.price or 0)
        if side == "BUY":
            buckets[key]["buy_qty"] += qty
            buckets[key]["buy_val"] += val
        elif side == "SELL":
            buckets[key]["sell_qty"] += qty
            buckets[key]["sell_val"] += val

    closed: list[dict[str, Any]] = []
    for (trade_date, symbol), b in buckets.items():
        matched = min(b["buy_qty"], b["sell_qty"])
        if matched <= 0:
            continue
        # Pro-rate if uneven (shouldn't happen for closed MIS)
        buy_px = b["buy_val"] / b["buy_qty"] if b["buy_qty"] else 0
        sell_px = b["sell_val"] / b["sell_qty"] if b["sell_qty"] else 0
        pnl = round(matched * (sell_px - buy_px), 2)
        closed.append(
            {
                "trade_date": trade_date,
                "trading_symbol": symbol,
                "pnl": pnl,
                "quantity": matched,
            }
        )
    return closed


def fifo_realised_pnl_by_day(trades: list[GrowwTrade]) -> dict[date, float]:
    """Cross-day FIFO realised P&L from fills, keyed by sell/cover date."""
    by_sym = fifo_realised_pnl_by_day_symbol(trades)
    out: dict[date, float] = defaultdict(float)
    for d, syms in by_sym.items():
        out[d] += sum(syms.values())
    return {d: round(v, 2) for d, v in out.items()}


def fifo_realised_pnl_by_day_symbol(trades: list[GrowwTrade]) -> dict[date, dict[str, float]]:
    """
    Cross-day FIFO realised P&L from fills (CNC/NRML friendly).

    Buy lots are held until later sells; P&L is booked on the sell date.
    Short lots are covered by later buys; P&L is booked on the cover date.
    """
    by_symbol: dict[str, list[GrowwTrade]] = defaultdict(list)
    for t in trades:
        sym = (t.trading_symbol or "").strip().upper()
        if not sym:
            continue
        by_symbol[sym].append(t)

    by_day: dict[date, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for sym, fills in by_symbol.items():
        fills_sorted = sorted(
            fills,
            key=lambda x: (x.trade_date, x.id or 0),
        )
        long_lots: list[list[float]] = []
        short_lots: list[list[float]] = []
        for f in fills_sorted:
            side = (f.transaction_type or "").upper()
            qty = float(f.quantity or 0)
            px = float(f.price or 0)
            if qty <= 0:
                continue
            if side == "BUY":
                remaining = qty
                while remaining > 0 and short_lots:
                    lot_qty, lot_px = short_lots[0]
                    matched = min(remaining, lot_qty)
                    by_day[f.trade_date][sym] += matched * (lot_px - px)
                    lot_qty -= matched
                    remaining -= matched
                    if lot_qty <= 1e-9:
                        short_lots.pop(0)
                    else:
                        short_lots[0][0] = lot_qty
                if remaining > 0:
                    long_lots.append([remaining, px])
            elif side == "SELL":
                remaining = qty
                while remaining > 0 and long_lots:
                    lot_qty, lot_px = long_lots[0]
                    matched = min(remaining, lot_qty)
                    by_day[f.trade_date][sym] += matched * (px - lot_px)
                    lot_qty -= matched
                    remaining -= matched
                    if lot_qty <= 1e-9:
                        long_lots.pop(0)
                    else:
                        long_lots[0][0] = lot_qty
                if remaining > 0:
                    short_lots.append([remaining, px])

    return {
        d: {s: round(v, 2) for s, v in syms.items()}
        for d, syms in by_day.items()
    }


def position_pnl_by_symbol(positions: list[dict[str, Any]], *, products: Optional[set[str]] = None) -> dict[str, float]:
    out: dict[str, float] = {}
    for pos in dedupe_positions(positions):
        product = str(pos.get("product") or "").upper()
        if products is not None and product not in products:
            continue
        sym = str(pos.get("trading_symbol") or "").strip().upper()
        if not sym:
            continue
        try:
            out[sym] = round(float(pos.get("realised_pnl") or 0), 2)
        except (TypeError, ValueError):
            out[sym] = 0.0
    return out


def merge_day_style_pnl(
    *,
    positions: list[dict[str, Any]],
    products: set[str],
    fill_pnl_by_symbol: dict[str, float],
) -> float:
    """Prefer Groww position realised per symbol; fall back to FIFO fills when Groww reports 0."""
    pos_by_sym = position_pnl_by_symbol(positions, products=products)
    symbols = set(pos_by_sym) | set(fill_pnl_by_symbol)
    total = 0.0
    for sym in symbols:
        pos_pnl = float(pos_by_sym.get(sym, 0.0))
        if abs(pos_pnl) > 0.009:
            total += pos_pnl
        else:
            total += float(fill_pnl_by_symbol.get(sym, 0.0))
    return round(total, 2)


def _count_position_hits(trades: list[GrowwTrade]) -> dict[str, Any]:
    """
    Count position 'hits' = how many times you opened and flattened a book in a symbol.
    Partial fills of the same order do not count separately — only when net qty returns to 0.
    Remaining open qty at end of day counts as 1 hit.
    """
    by_key: dict[tuple[date, str], list[GrowwTrade]] = defaultdict(list)
    for t in trades:
        by_key[(t.trade_date, t.trading_symbol)].append(t)

    per_symbol_day: list[dict[str, Any]] = []
    hits_by_day: dict[date, int] = defaultdict(int)
    symbols_by_day: dict[date, set[str]] = defaultdict(set)

    for (trade_date, symbol), fills in by_key.items():
        fills_sorted = sorted(fills, key=lambda x: x.id)
        net = 0
        hits = 0
        for f in fills_sorted:
            qty = int(f.quantity or 0)
            side = (f.transaction_type or "").upper()
            if side == "BUY":
                net += qty
            elif side == "SELL":
                net -= qty
            if net == 0:
                hits += 1
        if net != 0:
            hits += 1  # still holding / open book
        if hits <= 0 and fills_sorted:
            hits = 1
        per_symbol_day.append(
            {
                "trade_date": trade_date.isoformat(),
                "symbol": symbol,
                "hits": hits,
                "fills": len(fills_sorted),
            }
        )
        hits_by_day[trade_date] += hits
        symbols_by_day[trade_date].add(symbol)

    return {
        "per_symbol_day": sorted(per_symbol_day, key=lambda r: (r["trade_date"], r["symbol"])),
        "hits_by_day": {d.isoformat(): n for d, n in hits_by_day.items()},
        "symbols_by_day": {d.isoformat(): len(s) for d, s in symbols_by_day.items()},
        "total_hits": sum(hits_by_day.values()),
        "total_symbol_days": sum(len(s) for s in symbols_by_day.values()),
    }


def _daily_pnl_from_symbol_days(rows: list[dict[str, Any]]) -> dict[date, float]:
    by_day: dict[date, float] = defaultdict(float)
    for row in rows:
        by_day[row["trade_date"]] += row["pnl"]
    return {d: round(v, 2) for d, v in by_day.items()}


def _merge_daily_pnl(
    days: list[GrowwTradingDay],
    style: Style,
    trade_day_pnl: dict[date, float],
) -> dict[date, float]:
    """Prefer Groww positions realised_pnl (deduped); fall back to trade nets."""
    merged: dict[date, float] = {}
    for d in days:
        pos_rows = _style_positions(d, style)
        if pos_rows:
            merged[d.trade_date] = round(sum(float(p.get("realised_pnl") or 0) for p in pos_rows), 2)
        elif d.trade_date in trade_day_pnl:
            merged[d.trade_date] = trade_day_pnl[d.trade_date]
    for td, pnl in trade_day_pnl.items():
        if td not in merged:
            merged[td] = pnl
    # Drop empty zero-activity days with no trades/positions for this style
    return {d: p for d, p in merged.items() if p != 0 or d in trade_day_pnl}


def _max_drawdown(daily_series: list[tuple[date, float]]) -> float:
    if not daily_series:
        return 0.0
    ordered = sorted(daily_series, key=lambda x: x[0])
    peak = 0.0
    cumulative = 0.0
    max_dd = 0.0
    for _, pnl in ordered:
        cumulative += pnl
        peak = max(peak, cumulative)
        max_dd = max(max_dd, peak - cumulative)
    return round(max_dd, 2)


def _profit_factor(values: list[float]) -> Optional[float]:
    gains = sum(v for v in values if v > 0)
    losses = abs(sum(v for v in values if v < 0))
    if losses == 0:
        return None
    return round(gains / losses, 2)


def compute_style_kpis(
    *,
    style: Style,
    trades: list[GrowwTrade],
    orders: list[GrowwOrder],
    days: list[GrowwTradingDay],
    today: date,
    month_start: date,
) -> dict[str, Any]:
    style_trades = _filter_trades(trades, style)
    style_orders = _filter_orders(orders, style)

    # Closed symbol-days from trades (fallback + quality metrics)
    symbol_days = _symbol_day_pnl_from_trades(style_trades)
    trade_day_pnl = _daily_pnl_from_symbol_days(symbol_days)

    # Prefer Groww positions for daily totals (matches Groww Positions UI)
    daily_pnl_map = _merge_daily_pnl(days, style, trade_day_pnl)

    # If we have a positions snapshot for today, rebuild today's map from that alone
    today_day = next((d for d in days if d.trade_date == today), None)
    if today_day and _style_positions(today_day, style):
        daily_pnl_map[today] = _style_positions_pnl(today_day, style)

    daily_series = sorted(daily_pnl_map.items(), key=lambda x: x[0], reverse=True)
    pnl_values = [v for _, v in daily_series]
    active_days = len(pnl_values)

    today_pnl = daily_pnl_map.get(today, 0.0)
    mtd_pnl = sum(v for d, v in daily_pnl_map.items() if month_start <= d <= today)
    total_pnl = sum(pnl_values)

    green_days = sum(1 for v in pnl_values if v > 0)
    red_days = sum(1 for v in pnl_values if v < 0)
    green_pct = round(100 * green_days / active_days, 1) if active_days else 0.0

    best_day = max(pnl_values) if pnl_values else 0.0
    worst_day = min(pnl_values) if pnl_values else 0.0
    avg_daily = round(total_pnl / active_days, 2) if active_days else 0.0
    max_dd = _max_drawdown(list(daily_pnl_map.items()))

    # Quality: one closed idea = one symbol P&L for the day (not every fill)
    # Prefer positions snapshot symbols for today; else trade nets
    pos_symbol_pnl = _symbol_pnl_from_positions(days, style)
    if pos_symbol_pnl:
        idea_pnls = list(pos_symbol_pnl.values())
        top_symbols = sorted(
            [{"symbol": s, "pnl": p} for s, p in pos_symbol_pnl.items()],
            key=lambda x: abs(x["pnl"]),
            reverse=True,
        )[:5]
    else:
        # Aggregate symbol_days across history
        agg: dict[str, float] = defaultdict(float)
        for row in symbol_days:
            agg[row["trading_symbol"]] += row["pnl"]
        idea_pnls = list(agg.values())
        top_symbols = sorted(
            [{"symbol": s, "pnl": round(p, 2)} for s, p in agg.items()],
            key=lambda x: abs(x["pnl"]),
            reverse=True,
        )[:5]

    wins = [p for p in idea_pnls if p > 0]
    losses = [p for p in idea_pnls if p < 0]
    win_rate = round(100 * len(wins) / len(idea_pnls), 1) if idea_pnls else 0.0
    avg_win = round(sum(wins) / len(wins), 2) if wins else 0.0
    avg_loss = round(sum(losses) / len(losses), 2) if losses else 0.0
    pf_trips = _profit_factor(idea_pnls)
    pf_days = _profit_factor(pnl_values)
    expectancy = 0.0
    if idea_pnls:
        wr = len(wins) / len(idea_pnls)
        expectancy = round(wr * avg_win + (1 - wr) * avg_loss, 2)

    hit_stats = _count_position_hits(style_trades)
    today_key = today.isoformat()
    symbols_today = int(hit_stats["symbols_by_day"].get(today_key, 0))
    hits_today = int(hit_stats["hits_by_day"].get(today_key, 0))
    total_hits = int(hit_stats["total_hits"])
    # Average hits across days that had at least one symbol
    hit_days = len(hit_stats["hits_by_day"]) or 0
    avg_hits_day = round(total_hits / hit_days, 1) if hit_days else 0.0
    fills_today = sum(1 for t in style_trades if t.trade_date == today)

    filled_qty = sum(o.filled_quantity or 0 for o in style_orders)
    ordered_qty = sum(o.quantity or 0 for o in style_orders)
    fill_rate = round(100 * filled_qty / ordered_qty, 1) if ordered_qty else 0.0

    top_concentration = 0.0
    if top_symbols and total_pnl:
        top_concentration = round(100 * top_symbols[0]["pnl"] / total_pnl, 1)

    chart_days = sorted(daily_pnl_map.items(), key=lambda x: x[0])[-30:]
    cumulative = 0.0
    daily_chart = []
    cumulative_chart = []
    for d, pnl in chart_days:
        daily_chart.append({"date": d.isoformat(), "pnl": pnl})
        cumulative += pnl
        cumulative_chart.append({"date": d.isoformat(), "pnl": round(cumulative, 2)})

    today_hit_breakdown = [
        r for r in hit_stats["per_symbol_day"] if r["trade_date"] == today_key
    ]

    return {
        "style": style,
        "pnl": {
            "today": today_pnl,
            "mtd": round(mtd_pnl, 2),
            "total": round(total_pnl, 2),
            "avg_daily": avg_daily,
            "best_day": round(best_day, 2),
            "worst_day": round(worst_day, 2),
            "green_days_pct": green_pct,
            "green_days": green_days,
            "red_days": red_days,
            "max_drawdown": max_dd,
            "profit_factor_days": pf_days,
        },
        "activity": {
            # New semantics: unique symbols + position hits (not exchange fills)
            "symbols_today": symbols_today,
            "hits_today": hits_today,
            "avg_hits_per_day": avg_hits_day,
            "total_hits": total_hits,
            "fills_today": fills_today,
            "total_fills": len(style_trades),
            "total_orders": len(style_orders),
            "fill_rate_pct": fill_rate,
            "active_trading_days": active_days,
            "hits_breakdown_today": today_hit_breakdown,
            # Back-compat aliases used by older clients
            "trades_today": hits_today,
            "trades_mtd": hits_today,
            "total_trades": total_hits,
            "avg_trades_per_day": avg_hits_day,
        },
        "quality": {
            "win_rate_pct": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_factor": pf_trips,
            "expectancy": expectancy,
            "round_trips": len(idea_pnls),
        },
        "risk": {
            "max_daily_loss": round(worst_day, 2),
            "max_drawdown": max_dd,
            "largest_daily_gain": round(best_day, 2),
        },
        "concentration": {
            "top_symbol_pct": top_concentration,
            "top_symbols": top_symbols,
        },
        "charts": {
            "daily_pnl": daily_chart,
            "cumulative_pnl": cumulative_chart,
        },
    }


def build_dashboard_payload(
    *,
    username: str,
    trades: list[GrowwTrade],
    orders: list[GrowwOrder],
    days: list[GrowwTradingDay],
    today: date,
) -> dict[str, Any]:
    month_start = today.replace(day=1)
    intraday = compute_style_kpis(
        style="intraday",
        trades=trades,
        orders=orders,
        days=days,
        today=today,
        month_start=month_start,
    )
    swing = compute_style_kpis(
        style="swing",
        trades=trades,
        orders=orders,
        days=days,
        today=today,
        month_start=month_start,
    )

    recent_orders = sorted(
        orders,
        key=lambda o: (
            (o.raw or {}).get("created_at")
            or (o.raw or {}).get("exchange_time")
            or (o.synced_at.isoformat() if o.synced_at else "")
            or o.trade_date.isoformat()
        ),
        reverse=True,
    )[:15]

    def _order_time(o: GrowwOrder) -> Optional[str]:
        raw = o.raw if isinstance(o.raw, dict) else {}
        for key in ("exchange_time", "created_at"):
            val = raw.get(key)
            if val:
                return str(val)
        return o.synced_at.isoformat() if o.synced_at else None

    return {
        "username": username,
        "today": today.isoformat(),
        "intraday": intraday,
        "swing": swing,
        "recent_orders": [
            {
                "groww_order_id": o.groww_order_id,
                "trade_date": o.trade_date.isoformat(),
                "order_time": _order_time(o),
                "trading_symbol": o.trading_symbol,
                "transaction_type": o.transaction_type,
                "quantity": o.quantity,
                "filled_quantity": o.filled_quantity,
                "order_status": o.order_status,
                "segment": o.segment,
                "product": o.product,
                "style": classify_style(o.product, o.segment),
            }
            for o in recent_orders
        ],
    }
