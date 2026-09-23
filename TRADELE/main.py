"""FastAPI application entrypoint."""
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from TRADELE.api.routes import admin, agents, alerts, dashboard, explore, filters, fno, groww, indicators, intraday, jarvis, market, mytrade, news, scan, scanners, screener, swing, watchlist, zerodha
from TRADELE.scheduler.jobs import start_scheduler
from TRADELE.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler
    _scheduler = start_scheduler()
    yield
    if _scheduler:
        _scheduler.shutdown(wait=False)


app = FastAPI(
    title="Tradele AI Trading Intelligence Platform",
    description="AI-powered trading intelligence: intraday, swing, and positional scanners with rule engine.",
    version="0.2.0",
    lifespan=lifespan,
)

_default_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://tradele.vercel.app",
]
_extra = [o.strip() for o in (getattr(settings, "cors_origins", None) or "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_default_origins + _extra,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
app.include_router(agents.router, prefix="/api/agents", tags=["agents"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(scanners.router, prefix="/api/scanners", tags=["scanners"])
app.include_router(intraday.router, prefix="/api/intraday", tags=["intraday"])
app.include_router(indicators.router, prefix="/api/indicators", tags=["indicators"])
app.include_router(alerts.router, prefix="/api/alerts", tags=["alerts"])
app.include_router(news.router, prefix="/api/news", tags=["news"])
app.include_router(screener.router, prefix="/api/screener", tags=["screener"])
app.include_router(market.router, prefix="/api/market", tags=["market"])
app.include_router(scan.router, prefix="/api/scan", tags=["scan"])
app.include_router(zerodha.router, prefix="/api/zerodha", tags=["zerodha"])
app.include_router(groww.router, prefix="/api/groww", tags=["groww"])
app.include_router(mytrade.router, prefix="/api/mytrade", tags=["mytrade"])
app.include_router(filters.router, prefix="/api/filters", tags=["filters"])
app.include_router(swing.router, prefix="/api/swing", tags=["swing"])
app.include_router(explore.router, prefix="/api/explore", tags=["explore"])
app.include_router(watchlist.router, prefix="/api/watchlist", tags=["watchlist"])
app.include_router(jarvis.router, prefix="/api/jarvis", tags=["jarvis"])
app.include_router(fno.router, prefix="/api/fno", tags=["fno"])


@app.get("/")
async def root(
    request_token: str = Query(""),
    status: str = Query(""),
    action: str = Query(""),
    type: str = Query(""),
):
    """
    App root. Also handles Zerodha OAuth when Redirect URL is http://localhost:8000/
    (exchanges request_token → access_token, then sends user back to the UI login page).
    """
    if request_token and (not status or status == "success"):
        try:
            from TRADELE.db.session import SessionLocal
            from TRADELE.services.zerodha_client import make_kite
            from TRADELE.services.zerodha_token_store import save_access_token

            kite = make_kite()
            data = kite.generate_session(request_token, api_secret=settings.kite_api_secret)
            db = SessionLocal()
            try:
                save_access_token(db, "leninstark", data["access_token"])
            finally:
                db.close()
            return RedirectResponse(
                "http://localhost:5173/mytrade?zerodha=connected",
                status_code=302,
            )
        except Exception as e:
            logger.exception("Zerodha OAuth on / failed: %s", e)
            return RedirectResponse(
                "http://localhost:5173/mytrade?zerodha=error",
                status_code=302,
            )

    return {
        "message": "Tradele AI Trading Intelligence Platform",
        "docs": "/docs",
        "modules": [
            "market_data", "indicators", "scanners", "fundamentals",
            "news", "alerts", "recommendations", "portfolio",
        ],
    }


@app.get("/health")
async def health():
    return {"status": "ok"}
