"""SQLAlchemy models for alerts, scans, and audit."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ScanRun(Base):
    """One EOD or pre-market scan run."""

    __tablename__ = "scan_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_type: Mapped[str] = mapped_column(String(32))  # eod, pre_market
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="running")  # running, success, failed
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSON, nullable=True)


class Alert(Base):
    """Stored alert (top 10 buy / top 10 short) with reasons and sources."""

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_run_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    exchange: Mapped[str] = mapped_column(String(16), default="NSE")
    direction: Mapped[str] = mapped_column(String(16))  # long, short
    rank: Mapped[int] = mapped_column(Integer)  # 1-10
    score: Mapped[float] = mapped_column(Float)
    reasons: Mapped[dict] = mapped_column(JSON)  # list of {reason, source, value}
    key_levels: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # support, resistance, etc.
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    delivered_telegram: Mapped[bool] = mapped_column(Boolean, default=False)
    delivered_email: Mapped[bool] = mapped_column(Boolean, default=False)


class CandleCache(Base):
    """Cached OHLCV for a symbol/interval to respect Kite rate limits."""

    __tablename__ = "candle_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    exchange: Mapped[str] = mapped_column(String(16))
    interval: Mapped[str] = mapped_column(String(16))  # day, 5minute, etc.
    from_date: Mapped[str] = mapped_column(String(10))
    to_date: Mapped[str] = mapped_column(String(10))
    data: Mapped[dict] = mapped_column(JSON)  # list of ohlcv rows
    cached_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ZerodhaToken(Base):
    """Kite Connect access token per TRADELE user (expires ~6 AM IST daily)."""

    __tablename__ = "zerodha_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), index=True, unique=True)
    access_token: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True)


class GrowwToken(Base):
    """Groww access token per TRADELE user (expires ~6 AM IST daily)."""

    __tablename__ = "groww_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), index=True, unique=True)
    access_token: Mapped[str] = mapped_column(Text)
    api_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    api_secret: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True)


class GrowwTradingDay(Base):
    """Daily Groww trading snapshot (one row per user per trade date)."""

    __tablename__ = "groww_trading_days"
    __table_args__ = (UniqueConstraint("username", "trade_date", name="uq_groww_trading_day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    realised_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    order_count: Mapped[int] = mapped_column(Integer, default=0)
    trade_count: Mapped[int] = mapped_column(Integer, default=0)
    buy_value: Mapped[float] = mapped_column(Float, default=0.0)
    sell_value: Mapped[float] = mapped_column(Float, default=0.0)
    holdings_count: Mapped[int] = mapped_column(Integer, default=0)
    positions_count: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class GrowwOrder(Base):
    """Groww order stored by trade date (upserted on each sync)."""

    __tablename__ = "groww_orders"
    __table_args__ = (UniqueConstraint("username", "groww_order_id", name="uq_groww_order"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    groww_order_id: Mapped[str] = mapped_column(String(64), index=True)
    order_reference_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    trading_symbol: Mapped[str] = mapped_column(String(64), index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    filled_quantity: Mapped[int] = mapped_column(Integer, default=0)
    price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    average_fill_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    order_status: Mapped[str] = mapped_column(String(32))
    transaction_type: Mapped[str] = mapped_column(String(8))
    order_type: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    segment: Mapped[str] = mapped_column(String(8), default="CASH")
    exchange: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    product: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    raw: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class GrowwTrade(Base):
    """Individual Groww trade fill linked to an order."""

    __tablename__ = "groww_trades"
    __table_args__ = (UniqueConstraint("username", "groww_trade_id", name="uq_groww_trade"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    groww_trade_id: Mapped[str] = mapped_column(String(64), index=True)
    groww_order_id: Mapped[str] = mapped_column(String(64), index=True)
    trading_symbol: Mapped[str] = mapped_column(String(64), index=True)
    transaction_type: Mapped[str] = mapped_column(String(8))
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    price: Mapped[float] = mapped_column(Float, default=0.0)
    segment: Mapped[str] = mapped_column(String(8), default="CASH")
    exchange: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    product: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    raw: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class GrowwSyncRun(Base):
    """Audit log for Groww → MyTrade sync jobs."""

    __tablename__ = "groww_sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="running")
    dates_synced: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    orders_added: Mapped[int] = mapped_column(Integer, default=0)
    trades_added: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class SwingScanRun(Base):
    """Latest swing tab scan run (one active run per tab; replaced on each scan)."""

    __tablename__ = "swing_scan_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tab: Mapped[str] = mapped_column(String(32), index=True)  # universe, price_momentum, ...
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="running")  # running, success, failed
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSON, nullable=True)
    results: Mapped[list["SwingScanResult"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class SwingScanResult(Base):
    """One stock row from a swing tab scan."""

    __tablename__ = "swing_scan_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("swing_scan_runs.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    market_cap_cr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    avg_daily_volume: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    delivery_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_circuit: Mapped[bool] = mapped_column(Boolean, default=False)
    extra: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    run: Mapped["SwingScanRun"] = relationship(back_populates="results")


class ExploreAnalysisCache(Base):
    """Deep Agent stock report cache — one row per symbol; refresh when the calendar day changes."""

    __tablename__ = "explore_analysis_cache"
    __table_args__ = (UniqueConstraint("symbol", name="uq_explore_analysis_symbol"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    company: Mapped[str] = mapped_column(String(256), default="")
    analysis_date: Mapped[date] = mapped_column(Date, index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    accessed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class IntradayMomentumScanRun(Base):
    """One tomorrow-momentum scan — kept for RL / conviction audit."""

    __tablename__ = "intraday_momentum_scan_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), index=True, default="leninstark")
    as_of: Mapped[date] = mapped_column(Date, index=True)  # session scored
    target_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)  # next session
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="success")  # success, partial, failed
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scanned: Mapped[int] = mapped_column(Integer, default=0)
    prefiltered: Mapped[int] = mapped_column(Integer, default=0)
    rate_limited: Mapped[bool] = mapped_column(Boolean, default=False)
    sources: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    pattern: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # full API response snapshot
    candidates: Mapped[list["IntradayMomentumCandidate"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class IntradayMomentumCandidate(Base):
    """One scored Long/Short candidate from a momentum scan (top picks + near-misses)."""

    __tablename__ = "intraday_momentum_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("intraday_momentum_scan_runs.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    direction: Mapped[str] = mapped_column(String(16), index=True)  # long, short
    rank: Mapped[int] = mapped_column(Integer, default=0)  # 1 = top pick in direction
    is_top_pick: Mapped[bool] = mapped_column(Boolean, default=False)
    conviction: Mapped[int] = mapped_column(Integer, default=0)
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    can_trade_tomorrow: Mapped[bool] = mapped_column(Boolean, default=False)
    checks_passed: Mapped[int] = mapped_column(Integer, default=0)
    checks_total: Mapped[int] = mapped_column(Integer, default=0)
    close: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    data_source: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # Full conviction blob: checks, metrics, news, nse, yahoo, narrative, plan, verdict
    conviction_payload: Mapped[dict] = mapped_column(JSON)
    # Filled later for RL / post-mortem
    outcome_return_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    outcome_mfe_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # max favorable
    outcome_mae_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # max adverse
    outcome_hit: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    outcome_label: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # win/loss/scratch
    outcome_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    outcome_labeled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    run: Mapped["IntradayMomentumScanRun"] = relationship(back_populates="candidates")


class WatchlistItem(Base):
    """User watchlist — unlimited symbols per user."""

    __tablename__ = "watchlist_items"
    __table_args__ = (UniqueConstraint("username", "symbol", name="uq_watchlist_user_symbol"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    company: Mapped[str] = mapped_column(String(256), default="")
    sector: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class WatchlistAnalysis(Base):
    """Persisted analyst output — chat turns, deep reports, daily snapshots (JSON)."""

    __tablename__ = "watchlist_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[Optional[str]] = mapped_column(String(32), index=True, nullable=True)
    analysis_type: Mapped[str] = mapped_column(String(32), index=True)  # chat, deep, daily
    question: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON)
    sources: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    outcome_return_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    outcome_hit: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    outcome_label: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    outcome_labeled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class WatchlistKnowledgeChunk(Base):
    """RAG chunks — text + optional embedding vector (JSON array) for similarity search."""

    __tablename__ = "watchlist_knowledge_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    source: Mapped[str] = mapped_column(String(64), index=True)  # nse, news, technical, db, web
    chunk_key: Mapped[str] = mapped_column(String(128), index=True)  # dedupe id
    content: Mapped[str] = mapped_column(Text)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSON, nullable=True)
    embedding: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)  # float[]; pgvector later
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WatchlistGraphEdge(Base):
    """Symbol relationship graph — sector peers, supply chain (extensible)."""

    __tablename__ = "watchlist_graph_edges"
    __table_args__ = (UniqueConstraint("from_symbol", "to_symbol", "relation", name="uq_watchlist_graph_edge"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    from_symbol: Mapped[str] = mapped_column(String(32), index=True)
    to_symbol: Mapped[str] = mapped_column(String(32), index=True)
    relation: Mapped[str] = mapped_column(String(32), index=True)  # same_sector, peer, index_member
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSON, nullable=True)


class WatchlistFactCache(Base):
    """Same-day deterministic fact bundle per symbol (collector outputs)."""

    __tablename__ = "watchlist_fact_cache"
    __table_args__ = (UniqueConstraint("symbol", "cache_date", name="uq_watchlist_fact_day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    cache_date: Mapped[date] = mapped_column(Date, index=True)
    facts: Mapped[dict] = mapped_column(JSON)
    sources: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class NewsWatchItem(Base):
    """User-tracked symbols for Market News live feed."""

    __tablename__ = "news_watch_items"
    __table_args__ = (UniqueConstraint("username", "symbol", name="uq_news_watch_user_symbol"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    company: Mapped[str] = mapped_column(String(256), default="")
    sector: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class NewsWatchFeed(Base):
    """Cached news + AI impact summary per tracked symbol."""

    __tablename__ = "news_watch_feeds"
    __table_args__ = (UniqueConstraint("username", "symbol", name="uq_news_feed_user_symbol"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    seen_links: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class JournalFill(Base):
    """Canonical trade fill for Journal / Trader DNA (Groww sync + Excel upload)."""

    __tablename__ = "journal_fills"
    __table_args__ = (UniqueConstraint("username", "dedupe_key", name="uq_journal_fill_dedupe"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(16), index=True)  # groww | upload
    trade_datetime: Mapped[datetime] = mapped_column(DateTime, index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    side: Mapped[str] = mapped_column(String(8))  # BUY | SELL
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    price: Mapped[float] = mapped_column(Float, default=0.0)
    product: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    segment: Mapped[str] = mapped_column(String(16), default="CASH")
    exchange: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    instrument: Mapped[str] = mapped_column(String(16), default="equity")  # equity | fno
    order_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    trade_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String(64), index=True)
    raw: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TraderDnaReport(Base):
    """Cached Trader DNA audit (stats + LLM narrative)."""

    __tablename__ = "trader_dna_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    fills_through: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    fill_count: Mapped[int] = mapped_column(Integer, default=0)
    stats: Mapped[dict] = mapped_column(JSON)
    narrative: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    llm_provider: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    llm_used: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(32), default="success")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class MarketBrief(Base):
    """Overnight / morning market risk brief (global news → India index/sector verdict)."""

    __tablename__ = "market_briefs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    brief_type: Mapped[str] = mapped_column(String(16), index=True)  # night | morning | manual
    as_of: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    stance: Mapped[str] = mapped_column(String(16), default="neutral")  # risk_on|neutral|risk_off|crisis
    confidence: Mapped[int] = mapped_column(Integer, default=50)
    payload: Mapped[dict] = mapped_column(JSON)
    headline_count: Mapped[int] = mapped_column(Integer, default=0)
    llm_provider: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    llm_used: Mapped[bool] = mapped_column(Boolean, default=False)
    alerted: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(32), default="success")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
