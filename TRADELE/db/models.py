"""SQLAlchemy models for alerts, scans, and audit."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
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
    access_token: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True)


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
