from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .config import settings
from .database import init_db
from .agent_db import init_agent_db, log_audit
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
from .scanner import scan_all_pairs, scan_pair as _scanner_scan_pair, WATCHLIST as AGENT_WATCHLIST
from .execution import place_demo_trade
from .trade_manager import (
    manage_open_trades, trading_allowed,
    activate_kill_switch, deactivate_kill_switch,
    kill_switch_active, can_open_new_trade,
)
from .agent_db import (
    save_agent_trade, get_open_agent_trades, get_all_agent_trades,
    get_closed_agent_trades, get_agent_trade,
    get_recent_scan_results, save_scan_result,
    get_audit_log, get_strategy_versions,
)
from .review_engine import review_closed_trade, review_pending_trades
from .learning_engine import (
    generate_performance_report, generate_optimisation_proposals, save_proposal_as_version
)

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
APP_VERSION = "0.6.0-autonomous-agent"

app = FastAPI(title="AI FX Trading Agent", version=APP_VERSION)

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


class AgentScanRequest(BaseModel):
    account_balance: float = 10000.0


class AgentExecuteRequest(BaseModel):
    pair: str
    account_balance: float = 10000.0


class ManageTradesRequest(BaseModel):
    current_prices: Dict[str, float]
    account_balance: float = 10000.0


class KillSwitchRequest(BaseModel):
    reason: str = "Manual emergency stop"


class OptimisationRequest(BaseModel):
    save_as_version: bool = False
    description: str = ""


@app.on_event("startup")
def startup():
    init_db()
    init_agent_db()
    prepare_user_columns()


@app.get("/")
async def index():
    return FileResponse(FRONTEND / "index.html")


@app.get("/fx-agent")
async def agent_dashboard():
    html = FRONTEND / "agent.html"
    return FileResponse(html if html.exists() else FRONTEND / "index.html")


@app.get("/fx-agent/{path:path}")
async def agent_frontend(path: str):
    html = FRONTEND / "agent.html"
    return FileResponse(html if html.exists() else FRONTEND / "index.html")


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
        "kill_switch_active": kill_switch_active(),
        "selected_provider": choose_provider(),
        "message": "Live trading locked. Demo mode only.",
        "demo_mode": True,
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
            "trading_window": "07:00-11:00 UTC London",
            "live_trading_locked": True,
            "min_confidence_score": settings.min_confidence_score,
        },
        "configured": {
            "oanda": bool(settings.oanda_access_token and settings.oanda_account_id),
            "twelvedata": bool(settings.twelve_data_api_key),
            "fmp_calendar": bool(settings.fmp_api_key),
        },
    }


@app.get("/api/market/snapshot")
async def market_snap():
    try:
        return await market_snapshot()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/api/market/analysis")
async def market_analysis():
    try:
        return await all_pair_analysis()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/api/calendar")
async def calendar():
    try:
        return await economic_calendar()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.post("/api/scan")
async def scan(req: ScanRequest, user: str = Depends(current_user)):
    try:
        candles = await get_candles(req.pair, req.timeframe)
        cal = await economic_calendar()
        analysis = (await all_pair_analysis()).get(req.pair, {})
        return score_setup(analysis, req.dict(), cal.get("events", []))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/risk")
async def risk(req: RiskRequest, user: str = Depends(current_user)):
    return calculate_risk(req.dict())


@app.get("/api/briefing")
async def briefing(user: str = Depends(current_user)):
    try:
        snap = await market_snapshot()
        cal = await economic_calendar()
        return generate_briefing(snap, cal)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/automation/readiness")
async def check_readiness(req: AutomationReadinessIn, user: str = Depends(current_user)):
    return automation_readiness(req.dict())


@app.post("/api/journal")
async def journal_add(entry: JournalEntryIn, user: str = Depends(current_user)):
    return add_user_journal(entry.dict(), user)


@app.get("/api/journal")
async def journal_list(user: str = Depends(current_user)):
    return list_user_journal(user)


@app.delete("/api/journal")
async def journal_clear(user: str = Depends(current_user)):
    return clear_user_journal(user)


@app.post("/api/paper")
async def paper_add(trade: PaperTradeIn, user: str = Depends(current_user)):
    return add_user_paper_trade(trade.dict(), user)


@app.get("/api/paper")
async def paper_list(user: str = Depends(current_user)):
    return list_user_paper_trades(user)


@app.post("/api/paper/{trade_id}/close")
async def paper_close(trade_id: int, close_price: Optional[float] = None, user: str = Depends(current_user)):
    return close_user_paper_trade(trade_id, user, close_price)


@app.get("/api/paper/stats")
async def paper_statistics(user: str = Depends(current_user)):
    return paper_stats(user)


@app.post("/api/agent/scan")
async def agent_scan(req: AgentScanRequest, background_tasks: BackgroundTasks, user: str = Depends(current_user)):
    try:
        cal_data = await economic_calendar()
        events = cal_data.get("events", [])
        candles_by_pair = {}
        for pair in AGENT_WATCHLIST:
            try:
                candles_by_pair[pair] = await get_candles(pair, "1H")
            except Exception:
                candles_by_pair[pair] = []
        results = scan_all_pairs(candles_by_pair, events, req.account_balance)

        def _save():
            for r in results:
                save_scan_result(r)
                log_audit(
                    event_type="scan",
                    decision=r["status"],
                    reason=r.get("rejection_reason") or r.get("entry_reason", ""),
                    pair=r["pair"],
                )
        background_tasks.add_task(_save)
        return {
            "scanned_at": datetime.now(timezone.utc).isoformat(),
            "total_pairs": len(results),
            "candidates": [r for r in results if r["status"] == "trade_candidate"],
            "rejected": [r for r in results if r["status"] == "rejected"],
            "no_setup": [r for r in results if r["status"] == "no_setup"],
            "trading_allowed": trading_allowed(req.account_balance),
            "kill_switch": kill_switch_active(),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/agent/scan/history")
async def agent_scan_history(user: str = Depends(current_user)):
    return get_recent_scan_results(limit=100)


@app.post("/api/agent/execute")
async def agent_execute(req: AgentExecuteRequest, background_tasks: BackgroundTasks, user: str = Depends(current_user)):
    allowed = trading_allowed(req.account_balance)
    if not allowed["allowed"]:
        raise HTTPException(status_code=403, detail=allowed["reason"])
    can_open = can_open_new_trade()
    if not can_open["allowed"]:
        raise HTTPException(status_code=403, detail=can_open["reason"])
    try:
        cal_data = await economic_calendar()
        events = cal_data.get("events", [])
        candles = await get_candles(req.pair, "1H")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    candidate = _scanner_scan_pair(req.pair, candles, events, req.account_balance)
    if candidate["status"] != "trade_candidate":
        raise HTTPException(status_code=422, detail={
            "rejection_reason": candidate.get("rejection_reason"),
            "status": candidate["status"],
        })
    execution_result = place_demo_trade(candidate)
    if execution_result.get("status") == "error":
        raise HTTPException(status_code=502, detail=execution_result)
    trade_id = save_agent_trade({**candidate, **execution_result})
    log_audit(event_type="execution", decision="executed", reason="Demo trade placed.", pair=req.pair, trade_id=trade_id)
    return {"trade_id": trade_id, "execution": execution_result, "candidate": candidate}


@app.post("/api/agent/manage")
async def agent_manage(req: ManageTradesRequest, background_tasks: BackgroundTasks, user: str = Depends(current_user)):
    actions = manage_open_trades(req.current_prices, req.account_balance)
    background_tasks.add_task(review_pending_trades)
    return {"actions_taken": actions, "open_trades": get_open_agent_trades()}


@app.get("/api/agent/trades/open")
async def agent_open_trades(user: str = Depends(current_user)):
    return {
        "open_trades": get_open_agent_trades(),
        "trading_allowed": trading_allowed(),
        "kill_switch": kill_switch_active(),
    }


@app.get("/api/agent/trades")
async def agent_all_trades(user: str = Depends(current_user)):
    return get_all_agent_trades(limit=500)


@app.get("/api/agent/trades/closed")
async def agent_closed_trades(user: str = Depends(current_user)):
    return get_closed_agent_trades(limit=500)


@app.get("/api/agent/trades/{trade_id}")
async def agent_get_trade(trade_id: int, user: str = Depends(current_user)):
    trade = get_agent_trade(trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found.")
    return trade


@app.post("/api/agent/kill-switch/activate")
async def kill_switch_on(req: KillSwitchRequest, user: str = Depends(current_user)):
    result = activate_kill_switch(req.reason)
    log_audit(event_type="kill_switch", decision="activated", reason=req.reason)
    return result


@app.post("/api/agent/kill-switch/deactivate")
async def kill_switch_off(user: str = Depends(current_user)):
    return deactivate_kill_switch()


@app.get("/api/agent/kill-switch/status")
async def kill_switch_status():
    return {"active": kill_switch_active(), "trading_allowed": not kill_switch_active()}


@app.post("/api/agent/review/{trade_id}")
async def agent_review_trade(trade_id: int, user: str = Depends(current_user)):
    trade = get_agent_trade(trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found.")
    if trade.get("status") != "closed":
        raise HTTPException(status_code=422, detail="Trade not closed.")
    return review_closed_trade(trade)


@app.post("/api/agent/review/pending/all")
async def agent_review_pending(user: str = Depends(current_user)):
    reviewed = review_pending_trades()
    return {"reviewed_count": len(reviewed), "reviews": reviewed}


@app.get("/api/agent/performance")
async def agent_performance(user: str = Depends(current_user)):
    return generate_performance_report()


@app.post("/api/agent/optimise")
async def agent_optimise(req: OptimisationRequest, user: str = Depends(current_user)):
    report = generate_performance_report()
    proposals = generate_optimisation_proposals(report)
    version_id = save_proposal_as_version(proposals, description=req.description) if req.save_as_version else None
    return {"report": report, "proposals": proposals, "version_id": version_id}


@app.get("/api/agent/strategy/versions")
async def agent_versions(user: str = Depends(current_user)):
    return get_strategy_versions()


@app.get("/api/agent/audit")
async def agent_audit(user: str = Depends(current_user)):
    return get_audit_log(limit=200)


@app.get("/api/agent/status")
async def agent_status():
    from .scanner import _in_london_window
    open_trades = get_open_agent_trades()
    return {
        "version": APP_VERSION,
        "mode": "demo",
        "live_trading_locked": True,
        "kill_switch_active": kill_switch_active(),
        "trading_allowed": trading_allowed(),
        "open_trade_count": len(open_trades),
        "open_trades": open_trades,
        "london_window_now": _in_london_window(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
