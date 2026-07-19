"""News aggregation from free RSS/sources; can be extended for Groww-style sources."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote_plus
import feedparser
import requests

logger = logging.getLogger(__name__)

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_TAG_RE = re.compile(r"<[^>]+>")

# Free RSS / news endpoints (India markets)
SOURCES = [
    ("Moneycontrol", "https://www.moneycontrol.com/rss/latestnews.xml"),
    ("Economic Times", "https://economictimes.indiatimes.com/rssfeedstopstories.cms"),
    ("Business Standard", "https://www.business-standard.com/rss/home_page_top_stories.rss"),
    ("Livemint", "https://www.livemint.com/rss/companies"),
    ("NDTV Business", "https://feeds.feedburner.com/ndtvprofit-latest"),
]


@dataclass
class NewsItem:
    title: str
    link: str
    source: str
    published: Optional[datetime] = None
    summary: str = ""


def fetch_rss(url: str, source_name: str) -> list[NewsItem]:
    items = []
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "TradeleBot/1.0"})
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
        for e in feed.entries[:30]:
            pub = None
            if hasattr(e, "published_parsed") and e.published_parsed:
                try:
                    pub = datetime(*e.published_parsed[:6], tzinfo=timezone.utc)
                except Exception:
                    pass
            items.append(
                NewsItem(
                    title=(e.get("title") or "").strip(),
                    link=e.get("link") or "",
                    source=source_name,
                    published=pub,
                    summary=(e.get("summary") or "")[:500],
                )
            )
    except Exception as e:
        logger.warning("RSS fetch failed %s: %s", url, e)
    return items


def aggregate_news(symbols: Optional[list[str]] = None) -> list[NewsItem]:
    """Fetch from all configured RSS sources. Optionally filter by symbols (keyword match)."""
    all_items: list[NewsItem] = []
    for name, url in SOURCES:
        all_items.extend(fetch_rss(url, name))
    # Dedupe by title
    seen = set()
    unique = []
    for n in all_items:
        key = (n.title[:80], n.source)
        if key in seen:
            continue
        seen.add(key)
        unique.append(n)
    # Sort by published desc
    unique.sort(key=lambda x: x.published or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    if symbols:
        pattern = re.compile("|".join(re.escape(s) for s in symbols), re.I)
        unique = [n for n in unique if pattern.search(n.title) or pattern.search(n.summary)]
    return unique[:50]


def _strip_html(text: str) -> str:
    return _TAG_RE.sub("", text or "").strip()


def fetch_google_news(query: str, limit: int = 10) -> list[NewsItem]:
    """
    Query Google News RSS (India edition) by free text.
    Free, no API key. Great for per-company and per-industry news.
    """
    query = (query or "").strip()
    if not query:
        return []
    url = GOOGLE_NEWS_RSS.format(q=quote_plus(query))
    items: list[NewsItem] = []
    try:
        resp = requests.get(url, timeout=12, headers={"User-Agent": _USER_AGENT})
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
        for e in feed.entries[:limit]:
            pub = None
            if getattr(e, "published_parsed", None):
                try:
                    pub = datetime(*e.published_parsed[:6], tzinfo=timezone.utc)
                except Exception:
                    pass
            # Google News exposes the real publisher in entry.source.title
            source_name = "Google News"
            src = getattr(e, "source", None)
            if src is not None and getattr(src, "title", None):
                source_name = src.title
            elif isinstance(e.get("source"), dict) and e["source"].get("title"):
                source_name = e["source"]["title"]

            title = (e.get("title") or "").strip()
            # Titles are formatted "Headline - Publisher"; drop the suffix
            if source_name and title.endswith(f" - {source_name}"):
                title = title[: -(len(source_name) + 3)].strip()

            items.append(
                NewsItem(
                    title=title,
                    link=e.get("link") or "",
                    source=source_name,
                    published=pub,
                    summary=_strip_html(e.get("summary") or "")[:300],
                )
            )
    except Exception as ex:
        logger.warning("Google News fetch failed for '%s': %s", query, ex)
    return items


def news_for_symbol(symbol: str, items: Optional[list[NewsItem]] = None) -> list[NewsItem]:
    """Filter aggregated news to items mentioning symbol."""
    if items is None:
        items = aggregate_news()
    sym_upper = symbol.upper()
    return [n for n in items if sym_upper in n.title.upper() or sym_upper in n.summary.upper()]
