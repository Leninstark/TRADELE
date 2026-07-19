"""Notification delivery: Telegram + Email; audit trail in DB."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from TRADELE.config import settings
from TRADELE.db.models import Alert, ScanRun
from TRADELE.services.scoring_engine import StockScore, reasons_to_dict

logger = logging.getLogger(__name__)


def format_alert_message(
    top_longs: list[StockScore],
    top_shorts: list[StockScore],
    llm_summary: str = "",
    run_type: str = "eod",
) -> str:
    """Single message body for Telegram/email."""
    lines = [
        f"📊 Tradele Intraday Alerts ({run_type.upper()})",
        f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M IST')}",
        "",
        "🟢 TOP 10 LONG (Buy)",
    ]
    for i, s in enumerate(top_longs[:10], 1):
        lines.append(f"{i}. {s.symbol} (score: {s.score:.0f})")
        for r in s.reasons[:3]:
            lines.append(f"   • {r.reason}")
        if s.key_levels:
            lines.append(f"   Levels: {s.key_levels}")
        lines.append("")
    lines.append("🔴 TOP 10 SHORT (Avoid/Sell)")
    for i, s in enumerate(top_shorts[:10], 1):
        lines.append(f"{i}. {s.symbol} (score: {s.score:.0f})")
        for r in s.reasons[:3]:
            lines.append(f"   • {r.reason}")
        lines.append("")
    if llm_summary:
        lines.append("--- AI Summary ---")
        lines.append(llm_summary[:1500])
    lines.append("")
    lines.append(
        "⚠️ Disclaimer: Not investment advice. Past performance does not guarantee future results. Trade at your own risk."
    )
    return "\n".join(lines)


def send_telegram(text: str) -> bool:
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        logger.debug("Telegram not configured")
        return False
    try:
        import requests
        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
        # Telegram message limit 4096
        chunk = text[:4000]
        r = requests.post(
            url,
            json={"chat_id": settings.telegram_chat_id, "text": chunk, "disable_web_page_preview": True},
            timeout=10,
        )
        if r.ok:
            return True
        logger.warning("Telegram send failed: %s", r.text)
        return False
    except Exception as e:
        logger.exception("Telegram error: %s", e)
        return False


def send_email(subject: str, body: str) -> bool:
    if not settings.smtp_user or not settings.alert_email_to:
        logger.debug("Email not configured")
        return False
    try:
        import smtplib
        from email.mime.text import MIMEText

        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = settings.smtp_user
        msg["To"] = settings.alert_email_to
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as smtp:
            smtp.starttls()
            smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.sendmail(settings.smtp_user, settings.alert_email_to, msg.as_string())
        return True
    except Exception as e:
        logger.exception("Email send failed: %s", e)
        return False


def persist_alerts(
    db: Session,
    scan_run_id: Optional[int],
    top_longs: list[StockScore],
    top_shorts: list[StockScore],
) -> None:
    """Save alerts to DB for audit trail."""
    for rank, s in enumerate(top_longs[:10], 1):
        db.add(
            Alert(
                scan_run_id=scan_run_id,
                symbol=s.symbol,
                exchange="NSE",
                direction="long",
                rank=rank,
                score=s.score,
                reasons=reasons_to_dict(s.reasons),
                key_levels=s.key_levels,
            )
        )
    for rank, s in enumerate(top_shorts[:10], 1):
        db.add(
            Alert(
                scan_run_id=scan_run_id,
                symbol=s.symbol,
                exchange="NSE",
                direction="short",
                rank=rank,
                score=s.score,
                reasons=reasons_to_dict(s.reasons),
                key_levels=s.key_levels,
            )
        )
    db.commit()


def mark_alerts_delivered(db: Session, scan_run_id: int, channel: str) -> None:
    if channel == "telegram":
        db.query(Alert).filter(Alert.scan_run_id == scan_run_id).update({"delivered_telegram": True})
    elif channel == "email":
        db.query(Alert).filter(Alert.scan_run_id == scan_run_id).update({"delivered_email": True})
    db.commit()


def deliver_alerts(
    db: Session,
    scan_run_id: Optional[int],
    top_longs: list[StockScore],
    top_shorts: list[StockScore],
    llm_summary: str = "",
    run_type: str = "eod",
) -> None:
    """Persist, send Telegram + Email, update delivered flags."""
    persist_alerts(db, scan_run_id, top_longs, top_shorts)
    body = format_alert_message(top_longs, top_shorts, llm_summary, run_type)
    subject = f"Tradele Intraday Alerts ({run_type}) - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    if send_telegram(body):
        if scan_run_id:
            mark_alerts_delivered(db, scan_run_id, "telegram")
    if send_email(subject, body):
        if scan_run_id:
            mark_alerts_delivered(db, scan_run_id, "email")
