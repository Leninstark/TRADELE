"""Scheduled jobs: EOD scan 4:00 PM IST, Groww sync 4:00 PM IST (Mon–Fri), morning alert 9:25 AM IST."""
from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from TRADELE.config import settings
from TRADELE.db.session import SessionLocal, init_db
from TRADELE.services.data_fetcher import apply_liquidity_filters, fetch_eod_batch
from TRADELE.services.groww_sync import sync_all_groww_users
from TRADELE.services.llm_agent import enrich_alerts_with_llm
from TRADELE.services.news_aggregator import aggregate_news
from TRADELE.services.notification_service import deliver_alerts
from TRADELE.services.scoring_engine import run_scoring
from TRADELE.services.zerodha_client import get_client

from TRADELE.db.models import ScanRun

logger = logging.getLogger(__name__)
IST = ZoneInfo(settings.tz)


def run_eod_scan() -> None:
    """Run after market close: fetch EOD, score, persist, send morning summary optional."""
    db = SessionLocal()
    run = ScanRun(run_type="eod", status="running")
    db.add(run)
    db.commit()
    db.refresh(run)
    try:
        client = get_client()
        symbol_data = fetch_eod_batch(client, db)
        symbol_data = apply_liquidity_filters(symbol_data)
        top_longs, top_shorts = run_scoring(symbol_data, top_n=10)
        news = aggregate_news()
        news_snippets = [{"title": n.title, "source": n.source, "link": n.link} for n in news[:20]]
        llm_summary = enrich_alerts_with_llm(top_longs, top_shorts, news_snippets)
        deliver_alerts(db, run.id, top_longs, top_shorts, llm_summary=llm_summary, run_type="eod")
        run.status = "success"
        run.finished_at = datetime.now(IST)
    except Exception as e:
        logger.exception("EOD scan failed: %s", e)
        run.status = "failed"
        run.error_message = str(e)
        run.finished_at = datetime.now(IST)
    finally:
        db.commit()
        db.close()


def run_morning_alert() -> None:
    """Run at 9:25 AM IST: use latest EOD scan + pre-market context, send alerts."""
    db = SessionLocal()
    run = ScanRun(run_type="pre_market", status="running")
    db.add(run)
    db.commit()
    db.refresh(run)
    try:
        client = get_client()
        symbol_data = fetch_eod_batch(client, db)
        symbol_data = apply_liquidity_filters(symbol_data)
        top_longs, top_shorts = run_scoring(symbol_data, top_n=10)
        news = aggregate_news()
        news_snippets = [{"title": n.title, "source": n.source} for n in news[:20]]
        llm_summary = enrich_alerts_with_llm(
            top_longs, top_shorts, news_snippets, market_context="Pre-market session 9:00-9:15; open at 9:15."
        )
        deliver_alerts(db, run.id, top_longs, top_shorts, llm_summary=llm_summary, run_type="pre_market")
        run.status = "success"
        run.finished_at = datetime.now(IST)
    except Exception as e:
        logger.exception("Morning alert failed: %s", e)
        run.status = "failed"
        run.error_message = str(e)
        run.finished_at = datetime.now(IST)
    finally:
        db.commit()
        db.close()


def run_watchlist_outcome_label() -> None:
    """Label watchlist analyst predictions vs next-session move (RL hook)."""
    db = SessionLocal()
    try:
        from TRADELE.services.watchlist_outcome import label_pending_analyses

        result = label_pending_analyses(db)
        logger.info("Watchlist outcome labeling: %s", result)
    except Exception as e:
        logger.exception("Watchlist outcome labeling failed: %s", e)
    finally:
        db.close()


def run_groww_eod_sync() -> None:
    """
    After market close: persist today's Groww orders, trades, and P&L for all connected users.
    Groww only exposes same-day orders via API, so this job must run daily to build history.
    """
    logger.info("Groww EOD sync starting")
    db = SessionLocal()
    try:
        result = sync_all_groww_users(db)
        logger.info(
            "Groww EOD sync finished: users=%s synced=%s skipped=%s date=%s",
            result.get("users"),
            result.get("synced"),
            result.get("skipped"),
            result.get("trade_date"),
        )
    except Exception as e:
        logger.exception("Groww EOD sync failed: %s", e)
    finally:
        db.close()


def run_market_brief_night() -> None:
    """~11:00 PM IST — US close / late global cues → India risk brief."""
    db = SessionLocal()
    try:
        from TRADELE.services.market_brief import build_and_save_market_brief

        result = build_and_save_market_brief(db, brief_type="night", send_alert=False)
        logger.info(
            "Night market brief: stance=%s conf=%s id=%s",
            result.get("stance"),
            result.get("confidence"),
            result.get("id"),
        )
    except Exception as e:
        logger.exception("Night market brief failed: %s", e)
    finally:
        db.close()


def run_market_brief_morning() -> None:
    """~8:15 AM IST — pre-open refresh of global+India risk brief."""
    db = SessionLocal()
    try:
        from TRADELE.services.market_brief import build_and_save_market_brief

        result = build_and_save_market_brief(db, brief_type="morning", send_alert=False)
        logger.info(
            "Morning market brief: stance=%s conf=%s id=%s",
            result.get("stance"),
            result.get("confidence"),
            result.get("id"),
        )
    except Exception as e:
        logger.exception("Morning market brief failed: %s", e)
    finally:
        db.close()


def start_scheduler() -> BackgroundScheduler:
    init_db()
    scheduler = BackgroundScheduler(timezone=IST)
    # EOD: 4:00 PM IST
    scheduler.add_job(run_eod_scan, CronTrigger(hour=16, minute=0, timezone=IST), id="eod_scan")
    # Watchlist RL outcome labeling: 4:35 PM IST Mon–Fri
    scheduler.add_job(
        run_watchlist_outcome_label,
        CronTrigger(hour=16, minute=35, day_of_week="mon-fri", timezone=IST),
        id="watchlist_outcome_label",
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
    )
    # Groww MyTrade: shortly after close, Mon–Fri (NSE closes 3:30 PM IST)
    if settings.groww_eod_sync_enabled:
        scheduler.add_job(
            run_groww_eod_sync,
            CronTrigger(
                hour=settings.groww_eod_sync_hour,
                minute=settings.groww_eod_sync_minute,
                day_of_week="mon-fri",
                timezone=IST,
            ),
            id="groww_eod_sync",
            replace_existing=True,
            misfire_grace_time=3600,
            coalesce=True,
        )
    # Morning: 9:25 AM IST
    scheduler.add_job(run_morning_alert, CronTrigger(hour=9, minute=25, timezone=IST), id="morning_alert")
    # Market Brief — night (US close cues) + morning pre-open
    # APScheduler ranges must be ascending (sun-thu is invalid)
    scheduler.add_job(
        run_market_brief_night,
        CronTrigger(hour=23, minute=0, day_of_week="sun,mon,tue,wed,thu", timezone=IST),
        id="market_brief_night",
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
    )
    scheduler.add_job(
        run_market_brief_morning,
        CronTrigger(hour=8, minute=15, day_of_week="mon-fri", timezone=IST),
        id="market_brief_morning",
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
    )
    scheduler.start()
    groww_time = (
        f"{settings.groww_eod_sync_hour:02d}:{settings.groww_eod_sync_minute:02d}"
        if settings.groww_eod_sync_enabled
        else "disabled"
    )
    logger.info(
        "Scheduler started: EOD 4:00 PM, Groww sync %s Mon-Fri, Morning 9:25 AM, "
        "Market Brief night 23:00 Sun-Thu + morning 08:15 Mon-Fri IST",
        groww_time,
    )
    return scheduler
