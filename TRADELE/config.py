"""App configuration from config/database.yaml + environment."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote_plus

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[1]
DATABASE_CONFIG_PATH = ROOT_DIR / "config" / "database.yaml"


def _load_database_yaml() -> dict[str, Any]:
    """Load non-secret DB defaults from config/database.yaml."""
    if not DATABASE_CONFIG_PATH.exists():
        return {}
    try:
        import yaml  # type: ignore
    except ImportError:
        return {}
    try:
        data = yaml.safe_load(DATABASE_CONFIG_PATH.read_text(encoding="utf-8")) or {}
        return data.get("database") or {}
    except Exception:
        return {}


_db_file = _load_database_yaml()


class Settings(BaseSettings):
    """Application settings loaded from env, with local DB defaults from config/database.yaml."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Zerodha
    kite_api_key: str = ""
    kite_api_secret: str = ""
    kite_access_token: str = ""

    # Groww
    groww_api_key: str = ""
    groww_api_secret: str = ""
    groww_access_token: str = ""

    # Database — local defaults match pgAdmin: postgres DB, Tradele schema
    db_host: str = Field(default=_db_file.get("host", "localhost"), validation_alias="DB_HOST")
    db_port: int = Field(default=int(_db_file.get("port", 5432)), validation_alias="DB_PORT")
    db_name: str = Field(default=_db_file.get("name", "postgres"), validation_alias="DB_NAME")
    db_user: str = Field(default=_db_file.get("user", "postgres"), validation_alias="DB_USER")
    db_password: str = Field(default=str(_db_file.get("password") or ""), validation_alias="DB_PASSWORD")
    db_schema: str = Field(default=_db_file.get("schema", "Tradele"), validation_alias="DB_SCHEMA")
    db_auto_create_tables: bool = Field(
        default=bool(_db_file.get("auto_create_tables", False)),
        validation_alias="DB_AUTO_CREATE_TABLES",
    )
    # Optional full URL override (if set, wins over individual fields)
    database_url: Optional[str] = Field(default=None, validation_alias="DATABASE_URL")

    # Telegram
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None

    # Email
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    alert_email_to: str = ""

    # LLM (optional)
    # Primary provider: claude_cli | gemini | openai
    llm_provider: str = Field(default="claude_cli", validation_alias="LLM_PROVIDER")
    # Comma-separated fallbacks after primary fails (default: remaining providers)
    llm_fallback: str = Field(default="gemini,openai", validation_alias="LLM_FALLBACK")
    openai_api_key: Optional[str] = None
    llm_base_url: Optional[str] = None
    openai_model: str = Field(default="gpt-4o-mini", validation_alias="OPENAI_MODEL")

    # Claude Code CLI (uses local `claude auth login` / Pro subscription)
    claude_cli_path: str = Field(default="", validation_alias="CLAUDE_CLI_PATH")
    claude_cli_model: str = Field(default="sonnet", validation_alias="CLAUDE_CLI_MODEL")
    claude_cli_timeout: int = Field(default=300, validation_alias="CLAUDE_CLI_TIMEOUT")
    # If true, scrub ANTHROPIC_API_KEY from child env so Pro subscription is used
    claude_cli_use_subscription: bool = Field(
        default=True, validation_alias="CLAUDE_CLI_USE_SUBSCRIPTION"
    )

    # Gemini
    gemini_api_key: Optional[str] = None
    gemini_model: str = "gemini-flash-latest"

    # Apify / Screener.in (optional)
    apify_api_token: Optional[str] = None

    # App
    tz: str = "Asia/Kolkata"
    log_level: str = "INFO"
    # Public UI origin — used for broker OAuth return redirects
    public_app_url: str = Field(default="http://localhost:5173", validation_alias="PUBLIC_APP_URL")
    # Comma-separated extra CORS origins for production frontends
    cors_origins: str = Field(
        default="https://tradele.pro,https://www.tradele.pro",
        validation_alias="CORS_ORIGINS",
    )

    # Filters
    min_avg_volume: int = 100_000
    min_price: float = 20.0
    max_price: float = 50_000.0
    exclude_small_cap: bool = True
    nifty_500_only: bool = True

    # Dashboard / quick scans
    dashboard_max_symbols: int = 30
    momentum_max_symbols: int = 50

    # Groww MyTrade — auto-sync after market close (Mon–Fri IST)
    groww_eod_sync_enabled: bool = Field(default=True, validation_alias="GROWW_EOD_SYNC_ENABLED")
    groww_eod_sync_hour: int = Field(default=16, validation_alias="GROWW_EOD_SYNC_HOUR")
    groww_eod_sync_minute: int = Field(default=0, validation_alias="GROWW_EOD_SYNC_MINUTE")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sqlalchemy_url(self) -> str:
        """Connection URL for SQLAlchemy. DATABASE_URL overrides individual fields."""
        if self.database_url:
            return self.database_url
        user = quote_plus(self.db_user)
        password = quote_plus(self.db_password) if self.db_password else ""
        auth = f"{user}:{password}@" if self.db_password else f"{user}@"
        return f"postgresql://{auth}{self.db_host}:{self.db_port}/{self.db_name}"


settings = Settings()
