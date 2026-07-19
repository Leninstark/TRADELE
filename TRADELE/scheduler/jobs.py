"""Scheduled jobs: EOD scan 4:00 PM IST, morning alert 9:25 AM IST."""
from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from TRADELE.config import settings
from TRADELE.db.session import SessionLocal, init_db
from TRADELE.services.data_fetcher import apply_liquidity_filters, fetch_eod_batch
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


def start_scheduler() -> BackgroundScheduler:
    init_db()
    scheduler = BackgroundScheduler(timezone=IST)
    # EOD: 4:00 PM IST
    scheduler.add_job(run_eod_scan, CronTrigger(hour=16, minute=0, timezone=IST), id="eod_scan")
    # Morning: 9:25 AM IST
    scheduler.add_job(run_morning_alert, CronTrigger(hour=9, minute=25, timezone=IST), id="morning_alert")
    scheduler.start()
    logger.info("Scheduler started: EOD 4:00 PM, Morning 9:25 AM IST")
    return scheduler
