from pydantic import BaseModel
from dotenv import load_dotenv
import os

load_dotenv(override=True)

class Settings(BaseModel):
        # Data provider
        data_provider: str = os.getenv("DATA_PROVIDER", "auto").lower()

    # Safety: live trading MUST stay false in the MVP
        enable_live_trading: bool = os.getenv("ENABLE_LIVE_TRADING", "false").lower() == "true"

    # OANDA integration
        oanda_env: str = os.getenv("OANDA_ENV", "practice").lower()
        oanda_access_token: str = os.getenv("OANDA_ACCESS_TOKEN", "")
        oanda_account_id: str = os.getenv("OANDA_ACCOUNT_ID", "")

    # Market data providers
        twelve_data_api_key: str = os.getenv("TWELVE_DATA_API_KEY", "")
        fmp_api_key: str = os.getenv("FMP_API_KEY", "")
        finnhub_api_key: str = os.getenv("FINNHUB_API_KEY", "")
        calendar_provider: str = os.getenv("CALENDAR_PROVIDER", "auto").lower()
        manual_calendar_file: str = os.getenv("MANUAL_CALENDAR_FILE", "data/economic_calendar.csv")

    # Account settings
        account_currency: str = os.getenv("ACCOUNT_CURRENCY", "GBP")

    # Risk rules (spec §4 hard safety rules)
        max_risk_per_trade_pct: float = float(os.getenv("MAX_RISK_PER_TRADE_PCT", "0.5"))
        max_daily_loss_pct: float = float(os.getenv("MAX_DAILY_LOSS_PCT", "1.5"))
        max_weekly_loss_pct: float = float(os.getenv("MAX_WEEKLY_LOSS_PCT", "4.0"))
        min_risk_reward: float = float(os.getenv("MIN_RISK_REWARD", "2.0"))
        news_guard_minutes: int = int(os.getenv("NEWS_GUARD_MINUTES", "30"))
        trading_window: str = os.getenv("TRADING_WINDOW", "07:00-11:00 UTC (London)")
        min_confidence_score: int = int(os.getenv("MIN_CONFIDENCE_SCORE", "85"))
        confidence_gate_mode: str = os.getenv("CONFIDENCE_GATE_MODE", "strict").lower()
        session_filter_mode: str = os.getenv("SESSION_FILTER_MODE", "london_only").lower()

    # Agent execution controls
        autonomous_execution_enabled: bool = os.getenv("AUTONOMOUS_EXECUTION_ENABLED", "false").lower() == "true"
        max_open_trades: int = int(os.getenv("MAX_OPEN_TRADES", "3"))
        max_trades_per_day: int = int(os.getenv("MAX_TRADES_PER_DAY", "3"))

    # Auth
        auth_allowed_users: str = os.getenv("AUTH_ALLOWED_USERS", "Jake,Jordan")
        auth_passcode: str = os.getenv("AUTH_PASSCODE", "")
        auth_token_secret: str = os.getenv("AUTH_TOKEN_SECRET", "change-me-in-production")
        auth_token_ttl_seconds: int = int(os.getenv("AUTH_TOKEN_TTL_SECONDS", "86400"))

settings = Settings()
