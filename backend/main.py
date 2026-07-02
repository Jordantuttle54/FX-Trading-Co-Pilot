from pathlib import Path
from typing import Dict, Any, Optional, List
import traceback
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
from .scanner import scan_all_pairs, scan_pair, WATCHLIST as AGENT_WATCHLIST
from .execution import place_demo_trade, get_open_positions_oanda
from .trade_manager import (
    manage_open_trades,
    trading_allowed,
    activate_kill_switch,
    deactivate_kill_switch,
    kill_switch_active,
    can_open_new_trade,
)
from .agent_db import (
    save_agent_trade,
    get_open_agent_trades,
    get_all_agent_trades,
    get_closed_agent_trades,
    get_agent_trade,
    get_recent_scan_results,
    save_scan_result,
    get_audit_log,
    get_strategy_versions,
    record_loss,
)
from .review_engine import review_closed_trade, review_pending_trades
from .learning_engine import generate_performance_report, generate_optimisation_proposals, save_proposal_as_version

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


# ---------------------------------------------------------------------------
# Request models for new agent endpoints
# ---------------------------------------------------------------------------

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

class TradeReviewRequest(BaseModel):
        trade_id: int

class OptimisationRequest(BaseModel):
        save_as_version: bool = False
        description: str = ""


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

@app.on_event("startup")
def startup():
        init_db()
        init_agent_db()
        prepare_user_columns()


# ---------------------------------------------------------------------------
# Static frontend
# ---------------------------------------------------------------------------

@app.get("/")
async def index():
        return FileResponse(FRONTEND / "index.html")

@app.get("/fx-agent")
@app.get("/fx-agent/{path:path}")
async def agent_frontend(path: str = ""):
        agent_html = FRONTEND / "agent.html"
        if agent_html.exists():
                    return FileResponse(agent_html)
                return FileResponse(FRONTEND / "index.html")


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@app.post("/api/auth/login")
async def auth_login(req: LoginRequest):
        return make_session(req.username, req.passcode)

@app.get("/api/auth/me")
async def auth_me(user: str = Depends(current_user)):
        return {"authenticated": True, "user": user}


# ---------------------------------------------------------------------------
# Health & config
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health():
        return {
                    "status": "ok",
                    "version": APP_VERSION,
                    "live_trading_enabled": False,
                    "kill_switch_active": kill_switch_active(),
                    "selected_provider": choose_provider(),
                    "message": "Live trading controls are locked. Demo/paper mode only.",
                    "demo_mode": True,
                    "confidence_gate": {
                                    "min_confidence_score": settings.min_confidence_score,
                                    "mode": settings.confidence_gate_mode,
                                    "autonomous_execution_enabled": settings.autonomous_execution_enabled,
                    },
                    "trading_window": "07:00-11:00 UTC (London)",
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
                                    "trading_window": "07:00-11:00 UTC (London)",
                                    "live_trading_locked": True,
                                    "min_confidence_score": settings.min_confidence_score,
                    },
        }


# ---------------------------------------------------------------------------
# Existing market data endpoints (preserved)
# ---------------------------------------------------------------------------

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
                    result = score_setup(analysis, req.dict(), cal.get("events", []))
                    return result
except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

@app.post("/api/risk")
async def risk(req: RiskRequest, user: str = Depends(current_user)):
        return calculate_risk(req.dict())

@app.get("/api/briefing")
async def briefing(user: str = Depends(current_user)):
        try:
                    snap = await market_snapshot()
                    cal  = await economic_calendar()
                    return generate_briefing(snap, cal)
except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

@app.post("/api/automation/readiness")
async def check_readiness(req: AutomationReadinessIn, user: str = Depends(current_user)):
        return automation_readiness(req.dict())


# ---------------------------------------------------------------------------
# User journal & paper trades (preserved)
# ---------------------------------------------------------------------------

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


# ===========================================================================
# NEW AUTONOMOUS AGENT ENDPOINTS
# ===========================================================================

# ---------------------------------------------------------------------------
# Agent scanner
# ---------------------------------------------------------------------------

@app.post("/api/agent/scan")
async def agent_scan(req: AgentScanRequest, background_tasks: BackgroundTasks, user: str = Depends(current_user)):
        """
            Run the autonomous scanner across all approved pairs.
                Returns structured setup candidates and saves scan results to the audit DB.
                    """
        try:
                    cal_data = await economic_calendar()
                    events   = cal_data.get("events", [])

            candles_by_pair: Dict[str, list] = {}
        for pair in AGENT_WATCHLIST:
                        try:
                                            candles_by_pair[pair] = await get_candles(pair, "1H")
except Exception:
                candles_by_pair[pair] = []

        results = scan_all_pairs(candles_by_pair, events, req.account_balance)

        # Save scan results in background
        def _save_scans():
                        for r in results:
                                            save_scan_result(r)
                                            log_audit(
                                                event_type = "scan",
                                                decision   = r["status"],
                                                reason     = r.get("rejection_reason") or r.get("entry_reason", ""),
                                                pair       = r["pair"],
                                                details    = {"confidence": r["confidence"], "setup": r["setup_type"]},
                                            )
                                    background_tasks.add_task(_save_scans)

        candidates = [r for r in results if r["status"] == "trade_candidate"]
        rejected   = [r for r in results if r["status"] == "rejected"]
        no_setup   = [r for r in results if r["status"] == "no_setup"]

        return {
                        "scanned_at":       datetime.now(timezone.utc).isoformat(),
                        "total_pairs":      len(results),
                        "candidates":       candidates,
                        "rejected":         rejected,
                        "no_setup":         no_setup,
                        "trading_allowed":  trading_allowed(req.account_balance),
                        "kill_switch":      kill_switch_active(),
        }
except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/agent/scan/history")
async def agent_scan_history(user: str = Depends(current_user)):
        """Return recent scan results from the database."""
    return get_recent_scan_results(limit=100)


# ---------------------------------------------------------------------------
# Agent execution
# ---------------------------------------------------------------------------

@app.post("/api/agent/execute")
async def agent_execute(req: AgentExecuteRequest, background_tasks: BackgroundTasks, user: str = Depends(current_user)):
        """
            Execute a demo trade for a specific pair after running all rule checks.
                The scanner must have produced a trade_candidate for this pair first.
                    """
    # Safety: check trading is allowed
    allowed = trading_allowed(req.account_balance)
    if not allowed["allowed"]:
                raise HTTPException(status_code=403, detail=allowed["reason"])

    # Safety: check open trade limits
    can_open = can_open_new_trade()
    if not can_open["allowed"]:
                raise HTTPException(status_code=403, detail=can_open["reason"])

    # Run a fresh scan for this specific pair
    try:
                cal_data = await economic_calendar()
        events   = cal_data.get("events", [])
        candles  = await get_candles(req.pair, "1H")
except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Data fetch failed: {exc}")

    from .scanner import scan_pair as _scan_pair
    candidate = _scan_pair(req.pair, candles, events, req.account_balance)

    if candidate["status"] != "trade_candidate":
                log_audit(
                                event_type = "execution",
                                decision   = "rejected",
                                reason     = candidate.get("rejection_reason") or "No valid setup found.",
                                pair       = req.pair,
                                details    = candidate,
                )
        raise HTTPException(
                        status_code=422,
                        detail={
                                            "message": "Setup does not meet all rule requirements for execution.",
                                            "rejection_reason": candidate.get("rejection_reason"),
                                            "status": candidate["status"],
                                            "candidate": candidate,
                        }
        )

    # Place the demo trade
    execution_result = place_demo_trade(candidate)

    if execution_result.get("status") == "error":
                log_audit(
                                event_type = "execution",
                                decision   = "error",
                                reason     = execution_result.get("error", "Unknown error"),
                                pair       = req.pair,
                )
        raise HTTPException(status_code=502, detail=execution_result)

    # Merge candidate + execution into trade record
    trade_record = {**candidate, **execution_result}
    trade_id = save_agent_trade(trade_record)

    log_audit(
                event_type = "execution",
                decision   = "executed",
                reason     = f"Demo trade placed. Mode: {execution_result.get('mode')}. Order: {execution_result.get('order_id')}",
                pair       = req.pair,
                trade_id   = trade_id,
                details    = {"setup_type": candidate["setup_type"], "confidence": candidate["confidence"]},
    )

    return {
                "trade_id":        trade_id,
                "execution":       execution_result,
                "candidate":       candidate,
                "message":         f"Demo trade placed successfully. Trade ID: {trade_id}",
    }


# ---------------------------------------------------------------------------
# Trade management
# ---------------------------------------------------------------------------

@app.post("/api/agent/manage")
async def agent_manage(req: ManageTradesRequest, background_tasks: BackgroundTasks, user: str = Depends(current_user)):
        """
            Check all open trades against current prices and apply management rules.
                Called periodically (e.g. every 5-15 minutes) or manually.
                    """
    actions = manage_open_trades(req.current_prices, req.account_balance)

    # For any closed trades, trigger post-trade review
    def _run_reviews():
                review_pending_trades()
    background_tasks.add_task(_run_reviews)

    return {
                "actions_taken": actions,
                "open_trades":   get_open_agent_trades(),
                "reviewed":      True,
    }


@app.get("/api/agent/trades/open")
async def agent_open_trades(user: str = Depends(current_user)):
        """Return all currently open agent trades."""
    return {
                "open_trades":      get_open_agent_trades(),
                "trading_allowed":  trading_allowed(),
                "kill_switch":      kill_switch_active(),
    }


@app.get("/api/agent/trades")
async def agent_all_trades(user: str = Depends(current_user)):
        """Return all agent trades (open and closed)."""
    return get_all_agent_trades(limit=500)


@app.get("/api/agent/trades/closed")
async def agent_closed_trades(user: str = Depends(current_user)):
        """Return closed agent trades."""
    return get_closed_agent_trades(limit=500)


@app.get("/api/agent/trades/{trade_id}")
async def agent_get_trade(trade_id: int, user: str = Depends(current_user)):
        """Return a single agent trade by ID."""
    trade = get_agent_trade(trade_id)
    if not trade:
                raise HTTPException(status_code=404, detail="Trade not found.")
    return trade


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------

@app.post("/api/agent/kill-switch/activate")
async def kill_switch_on(req: KillSwitchRequest, user: str = Depends(current_user)):
        """Activate the emergency kill switch. Halts all new trading immediately."""
    result = activate_kill_switch(req.reason)
    log_audit(
                event_type = "kill_switch",
                decision   = "activated",
                reason     = req.reason,
                details    = {"activated_by": user},
    )
    return result


@app.post("/api/agent/kill-switch/deactivate")
async def kill_switch_off(user: str = Depends(current_user)):
        """Deactivate the kill switch. Restores normal trading."""
    result = deactivate_kill_switch()
    log_audit(
                event_type = "kill_switch",
                decision   = "deactivated",
                reason     = f"Kill switch deactivated by {user}",
    )
    return result


@app.get("/api/agent/kill-switch/status")
async def kill_switch_status():
        return {
                    "active": kill_switch_active(),
                    "trading_allowed": not kill_switch_active(),
        }


# ---------------------------------------------------------------------------
# Post-trade review
# ---------------------------------------------------------------------------

@app.post("/api/agent/review/{trade_id}")
async def agent_review_trade(trade_id: int, user: str = Depends(current_user)):
        """Generate and save a post-trade review for a specific closed trade."""
    trade = get_agent_trade(trade_id)
    if not trade:
                raise HTTPException(status_code=404, detail="Trade not found.")
    if trade.get("status") != "closed":
                raise HTTPException(status_code=422, detail="Trade is not yet closed.")
    return review_closed_trade(trade)


@app.post("/api/agent/review/pending/all")
async def agent_review_all_pending(user: str = Depends(current_user)):
        """Review all closed trades that have not yet received a review."""
    reviewed = review_pending_trades()
    return {"reviewed_count": len(reviewed), "reviews": reviewed}


# ---------------------------------------------------------------------------
# Performance and learning
# ---------------------------------------------------------------------------

@app.get("/api/agent/performance")
async def agent_performance(user: str = Depends(current_user)):
        """
            Full performance report broken down by pair, setup, session, confidence.
                """
    return generate_performance_report()


@app.post("/api/agent/optimise")
async def agent_optimise(req: OptimisationRequest, user: str = Depends(current_user)):
        """
            Generate rule-improvement proposals based on closed trade evidence.
                Optionally save them as a strategy version for review.
                    """
    report    = generate_performance_report()
    proposals = generate_optimisation_proposals(report)

    version_id = None
    if req.save_as_version and proposals:
                version_id = save_proposal_as_version(proposals, description=req.description)

    return {
                "report":     report,
                "proposals":  proposals,
                "version_id": version_id,
    }


@app.get("/api/agent/strategy/versions")
async def agent_strategy_versions(user: str = Depends(current_user)):
        """Return all strategy version records (proposal history)."""
    return get_strategy_versions()


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

@app.get("/api/agent/audit")
async def agent_audit_log(user: str = Depends(current_user)):
        """Return recent audit log entries (decisions, scans, executions, reviews)."""
    return get_audit_log(limit=200)


# ---------------------------------------------------------------------------
# System status (combined dashboard state)
# ---------------------------------------------------------------------------

@app.get("/api/agent/status")
async def agent_status():
        """Combined system status for the agent dashboard."""
    trade_check = trading_allowed()
    open_trades = get_open_agent_trades()

    return {
                "version":             APP_VERSION,
                "mode":                "demo",
                "live_trading_locked": True,
                "kill_switch_active":  kill_switch_active(),
                "trading_allowed":     trade_check,
                "open_trade_count":    len(open_trades),
                "open_trades":         open_trades,
                "london_window_now":   _in_london_window_now(),
                "timestamp":           datetime.now(timezone.utc).isoformat(),
    }


def _in_london_window_now() -> bool:
        from .scanner import _in_london_window
    return _in_london_window()
