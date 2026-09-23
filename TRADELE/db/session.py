"""Database session and engine (sync for Kite/cron use)."""
from __future__ import annotations

import logging

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from TRADELE.config import settings
from TRADELE.db.models import (
    Base,
    CandleCache,
    ExploreAnalysisCache,
    GrowwOrder,
    GrowwSyncRun,
    GrowwToken,
    GrowwTrade,
    GrowwTradingDay,
    IntradayMomentumCandidate,
    IntradayMomentumScanRun,
    JournalFill,
    MarketBrief,
    NewsWatchFeed,
    NewsWatchItem,
    SwingScanResult,
    SwingScanRun,
    TraderDnaReport,
    WatchlistAnalysis,
    WatchlistFactCache,
    WatchlistGraphEdge,
    WatchlistItem,
    WatchlistKnowledgeChunk,
    ZerodhaToken,
)

logger = logging.getLogger(__name__)

# Quote schema for Postgres case-sensitivity (e.g. "Tradele")
_schema = settings.db_schema
_search_path = f'-csearch_path="{_schema}",public'

engine = create_engine(
    settings.sqlalchemy_url,
    pool_pre_ping=True,
    echo=settings.log_level.upper() == "DEBUG",
    connect_args={"options": _search_path},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base.metadata.schema = _schema


def ensure_schema() -> None:
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{_schema}"'))


def _ensure_swing_result_extra_column() -> None:
    """Add extra JSON column to existing swing_scan_results tables."""
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    f'ALTER TABLE "{_schema}".swing_scan_results '
                    "ADD COLUMN IF NOT EXISTS extra JSON"
                )
            )
    except Exception as e:
        logger.debug("extra column migration skipped: %s", e)


def _ensure_groww_token_text_columns() -> None:
    """Groww API keys are JWTs (~900+ chars); widen from varchar(256)."""
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    f'ALTER TABLE "{_schema}".groww_tokens '
                    "ALTER COLUMN api_key TYPE TEXT"
                )
            )
            conn.execute(
                text(
                    f'ALTER TABLE "{_schema}".groww_tokens '
                    "ALTER COLUMN api_secret TYPE TEXT"
                )
            )
    except Exception as e:
        logger.debug("groww_tokens column widen skipped: %s", e)


def _ensure_watchlist_outcome_columns() -> None:
    """RL outcome fields on watchlist_analyses (added after initial deploy)."""
    cols = (
        ("outcome_return_pct", "DOUBLE PRECISION"),
        ("outcome_hit", "BOOLEAN"),
        ("outcome_label", "VARCHAR(64)"),
        ("outcome_labeled_at", "TIMESTAMP"),
    )
    try:
        with engine.begin() as conn:
            for name, typ in cols:
                conn.execute(
                    text(
                        f'ALTER TABLE "{_schema}".watchlist_analyses '
                        f"ADD COLUMN IF NOT EXISTS {name} {typ}"
                    )
                )
    except Exception as e:
        logger.debug("watchlist outcome columns migration skipped: %s", e)


def _ensure_pgvector() -> bool:
    """Enable pgvector extension + optional vector column on knowledge chunks."""
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.execute(
                text(
                    f'ALTER TABLE "{_schema}".watchlist_knowledge_chunks '
                    "ADD COLUMN IF NOT EXISTS embedding_vec vector(768)"
                )
            )
            conn.execute(
                text(
                    f'CREATE INDEX IF NOT EXISTS ix_wl_chunks_embedding_hnsw '
                    f'ON "{_schema}".watchlist_knowledge_chunks '
                    "USING hnsw (embedding_vec vector_cosine_ops)"
                )
            )
        return True
    except Exception as e:
        logger.info("pgvector not available — using JSON embedding fallback: %s", e)
        return False


def init_db() -> None:
    """Ensure schema exists and create required tables (zerodha_tokens always)."""
    ensure_schema()
    # Always create core tables; other tables only when auto_create_tables is on
    for table_cls in (
        ZerodhaToken,
        GrowwToken,
        GrowwTradingDay,
        GrowwOrder,
        GrowwTrade,
        GrowwSyncRun,
        CandleCache,
        ExploreAnalysisCache,
        SwingScanRun,
        SwingScanResult,
        IntradayMomentumScanRun,
        IntradayMomentumCandidate,
        WatchlistItem,
        WatchlistAnalysis,
        WatchlistKnowledgeChunk,
        WatchlistGraphEdge,
        WatchlistFactCache,
        NewsWatchItem,
        NewsWatchFeed,
        JournalFill,
        TraderDnaReport,
        MarketBrief,
    ):
        table_cls.__table__.create(bind=engine, checkfirst=True)
    _ensure_swing_result_extra_column()
    _ensure_groww_token_text_columns()
    _ensure_watchlist_outcome_columns()
    _ensure_pgvector()
    if settings.db_auto_create_tables:
        Base.metadata.create_all(bind=engine)
        logger.info("DB tables created in schema %s", settings.db_schema)
    else:
        logger.info(
            "DB ready (schema=%s, core tables ready): %s",
            settings.db_schema,
            settings.sqlalchemy_url.split("@")[-1] if "@" in settings.sqlalchemy_url else settings.sqlalchemy_url,
        )

    # Seed token from .env once if DB empty and env has a token
    _seed_token_from_env()
    _seed_groww_token_from_env()


def _seed_groww_token_from_env() -> None:
    token = (settings.groww_access_token or "").strip()
    if not token:
        return
    db = SessionLocal()
    try:
        from TRADELE.services.groww_token_store import get_token_row, save_access_token

        if get_token_row(db, "leninstark") is None:
            save_access_token(db, "leninstark", token)
            logger.info("Seeded Groww access token from .env into DB")
    except Exception as e:
        logger.warning("Could not seed Groww token: %s", e)
        db.rollback()
    finally:
        db.close()


def _seed_token_from_env() -> None:
    token = (settings.kite_access_token or "").strip()
    if not token:
        return
    db = SessionLocal()
    try:
        from TRADELE.services.zerodha_token_store import get_token_row, save_access_token

        if get_token_row(db, "leninstark") is None:
            save_access_token(db, "leninstark", token)
            logger.info("Seeded Zerodha access token from .env into DB")
    except Exception as e:
        logger.warning("Could not seed Zerodha token: %s", e)
        db.rollback()
    finally:
        db.close()


def check_db() -> dict:
    """Ping Postgres and report config."""
    with engine.connect() as conn:
        version = conn.execute(text("SHOW server_version")).scalar()
        schema = conn.execute(text("SHOW search_path")).scalar()
    return {
        "ok": True,
        "database": settings.db_name if not settings.database_url else "(from DATABASE_URL)",
        "schema": settings.db_schema,
        "search_path": schema,
        "server_version": version,
        "auto_create_tables": settings.db_auto_create_tables,
    }


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
