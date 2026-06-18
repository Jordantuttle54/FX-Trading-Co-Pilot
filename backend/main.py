from pathlib import Path
from typing import Dict, Any
import traceback

from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .config import settings
from .database import init_db
from .models import ScanRequest, RiskRequest, JournalEntryIn, PaperTradeIn, AutomationReadinessIn
from .data_providers import market_snapshot, get_candles, all_pair_analysis, economic_calendar, choose_provider
from .strategy import WATCHLIST, score_setup, calculate_risk, automation_readiness
from .ai_briefing import generate_briefing
from .auth import make_session, current_user
from .user_records import (
    prepare_user_columns,
    add_user_journal,
    list_user_journal,
    clear_user_journal,
    add_user_paper_trade,
    list_user_paper_trades,
    close_user_paper_trade,
    paper_stats,
)

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"

APP_VERSION = "0.5.0-user-accounts"

app = FastAPI(title="AI FX Co-Pilot", version=APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")


class LoginRequest(BaseModel):
    username: str
    passcode: str


@app.on_event("startup")
def startup():
    init_db()
    prepare_user_columns()


@app.get("/")
async def index():
    return FileResponse(FRONTEND / "index.html")


@app.post("/api/auth/login")
async def auth_login(req: LoginRequest):
    return make_session(req.username, req.passcode)


@app.get("/api/auth/me")
async def auth_me(user: str = Depends(current_user)):
    return {"authenticated": True, "user": user}


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "version": APP_VERSION,
        "live_trading_enabled": False,
        "selected_provider": choose_provider(),
        "message": "Live trading controls are locked. Paper/manual review only.",
        "confidence_gate": {
            "min_confidence_score": settings.min_confidence_score,
            "mode": settings.confidence_gate_mode,
            "session_filter_mode": settings.session_filter_mode,
            "autonomous_execution_enabled": False,
        },
    }


@app.get("/api/config")
async def config():
    return {
        "watchlist": WATCHLIST,
        "selected_provider": choose_provider(),
        "account_currency": settings.account_currency,
        "rules": {
            "max_risk_per_trade_pct": settings.max_risk_per_trade_pct,
            "max_daily_loss_pct": settings.max_daily_loss_pct,
            "max_weekly_loss_pct": settings.max_weekly_loss_pct,
            "min_risk_reward": settings.min_risk_reward,
            "news_guard_minutes": settings.news_guard_minutes,
            "trading_window": settings.trading_window,
            "live_trading_locked": True,
            "min_confidence_score": settings.min_confidence_score,
            "confidence_gate_mode": settings.confidence_gate_mode,
        },
        "configured": {
            "oanda": bool(settings.oanda_access_token and settings.oanda_account_id),
            "twelvedata": bool(settings.twelve_data_api_key),
            "fmp_calendar": bool(settings.fmp_api_key),
            "finnhub_calendar": bool(settings.finnhub_api_key),
            "calendar_provider": settings.calendar_provider,
            "manual_calendar": (ROOT / settings.manual_calendar_file).exists(),
            "manual_calendar_file": settings.manual_calendar_file,
        },
    }


@app.get("/api/market/snapshot")
async def api_market_snapshot():
    return await market_snapshot()


@app.get("/api/market/candles")
async def api_candles(pair: str = "GBP/USD", interval: str = "1h", count: int = 120):
    return await get_candles(pair, interval=interval, count=count)


@app.get("/api/market/analysis")
async def api_analysis(interval: str = "1h"):
    return await all_pair_analysis(interval=interval)


@app.get("/api/calendar")
async def api_calendar():
    return await economic_calendar()


@app.get("/api/briefing")
async def api_briefing():
    snapshot = await market_snapshot()
    analysis = await all_pair_analysis(interval="1h")
    calendar = await economic_calendar()
    return generate_briefing(analysis, calendar, snapshot)


@app.post("/api/scan")
async def api_scan(req: ScanRequest):
    analysis = await get_candles(req.pair, interval=req.timeframe.lower(), count=120)
    calendar = await economic_calendar()
    return score_setup(analysis["analysis"], req.model_dump(), calendar["events"])


@app.post("/api/risk")
async def api_risk(req: RiskRequest):
    try:
        return calculate_risk(req.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/journal")
async def api_list_journal(user: str = Depends(current_user)):
    rows = list_user_journal(user)
    wins = len([r for r in rows if r["result_r"] > 0])
    total_r = sum(float(r["result_r"]) for r in rows)
    return {
        "user": user,
        "rows": rows,
        "stats": {
            "trades": len(rows),
            "win_rate_pct": round((wins / len(rows)) * 100, 1) if rows else 0,
            "total_r": round(total_r, 2),
            "avg_r": round(total_r / len(rows), 2) if rows else 0,
        },
    }


@app.post("/api/journal")
async def api_add_journal(entry: JournalEntryIn, user: str = Depends(current_user)):
    return add_user_journal(entry.model_dump(), user)


@app.delete("/api/journal")
async def api_clear_journal(user: str = Depends(current_user)):
    clear_user_journal(user)
    return {"status": "cleared", "user": user}


@app.get("/api/paper-trades")
async def api_list_paper_trades(user: str = Depends(current_user)):
    rows = list_user_paper_trades(user)
    return {"user": user, "rows": rows, "stats": paper_stats(rows)}


@app.post("/api/paper-trades")
async def api_add_paper_trade(trade: PaperTradeIn, user: str = Depends(current_user)):
    return add_user_paper_trade(trade.model_dump(), user)


@app.post("/api/paper-trades/{trade_id}/close")
async def api_close_paper_trade(trade_id: int, close_price: float, result_r: float, user: str = Depends(current_user)):
    result = close_user_paper_trade(trade_id, close_price, result_r, user)
    if not result:
        raise HTTPException(status_code=404, detail="Record not found for this user")
    return result


@app.post("/api/automation-readiness")
async def api_automation_readiness(req: AutomationReadinessIn):
    return automation_readiness(req.model_dump())
