from __future__ import annotations

import math
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .auth import current_user, make_session

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
APP_VERSION = "0.6.1-vercel-safe"
WATCHLIST = ["GBP/USD", "EUR/USD", "USD/JPY", "EUR/GBP", "GBP/JPY", "XAU/USD"]

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


class ScanRequest(BaseModel):
    pair: str
    timeframe: str = "1h"
    direction: str = "Long"
    risk_reward: float = 2.0
    checklist: Dict[str, Any] = {}


class RiskRequest(BaseModel):
    account_balance: float
    risk_pct: float
    pair: str
    entry: float
    stop_loss: float
    target: float
    pip_value_per_standard_lot: float = 10.0


class JournalEntryIn(BaseModel):
    date: str
    pair: str
    direction: str
    result_r: float
    reason: str = ""
    lesson: str = ""


class PaperTradeIn(BaseModel):
    pair: str
    direction: str
    entry: float
    stop_loss: float
    target: float
    risk_pct: float
    risk_amount: float
    position_units: float
    notes: str = ""


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


class AutomationReadinessIn(BaseModel):
    backtested_trades: int = 0
    forward_trades: int = 0
    avg_r: float = 0
    max_drawdown_pct: float = 100
    max_daily_loss_pct: float = 100
    win_rate_pct: float = 0


JOURNAL: List[Dict[str, Any]] = []
PAPER_TRADES: List[Dict[str, Any]] = []
AGENT_TRADES: List[Dict[str, Any]] = []
SCAN_HISTORY: List[Dict[str, Any]] = []
AUDIT_LOG: List[Dict[str, Any]] = []
KILL_SWITCH = {"active": False, "reason": None}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _frontend_file(name: str = "index.html"):
    path = FRONTEND / name
    if path.exists():
        return FileResponse(path)
    return JSONResponse({"status": "ok", "message": "AI FX Trading Agent backend is running.", "version": APP_VERSION})


def _pip_size(pair: str) -> float:
    return 0.01 if "JPY" in pair else 0.0001


def _base_price(pair: str) -> float:
    prices = {
        "GBP/USD": 1.2700,
        "EUR/USD": 1.0850,
        "USD/JPY": 156.20,
        "EUR/GBP": 0.8550,
        "GBP/JPY": 198.50,
        "XAU/USD": 2350.0,
    }
    random.seed(abs(hash(pair)) % 100000 + int(datetime.utcnow().strftime("%Y%m%d%H")))
    return prices.get(pair, 1.0) * (1 + random.uniform(-0.002, 0.002))


def _snapshot() -> Dict[str, Any]:
    quotes = []
    for pair in WATCHLIST:
        price = _base_price(pair)
        pip = _pip_size(pair)
        quotes.append({
            "pair": pair,
            "price": round(price, 3 if "JPY" in pair or pair == "XAU/USD" else 5),
            "bid": round(price - pip, 5),
            "ask": round(price + pip, 5),
            "spread_pips": 2,
            "timestamp": _now(),
            "source": "vercel-safe-fallback",
        })
    return {
        "provider": "vercel-safe-fallback",
        "generated_at": _now(),
        "quotes": quotes,
        "warnings": ["Fallback data only. Configure OANDA/Twelve Data for live demo-market data."],
    }


def _analysis_for_pair(pair: str) -> Dict[str, Any]:
    price = _base_price(pair)
    random.seed(abs(hash(pair + "analysis")) % 100000)
    bias = random.choice(["Bullish", "Bearish", "Neutral"])
    volatility = random.choice(["Low", "Medium", "High"])
    pip = _pip_size(pair)
    support = price - (40 * pip)
    resistance = price + (40 * pip)
    return {
        "pair": pair,
        "bias": bias,
        "trend": "Fallback technical scan generated safely on Vercel.",
        "zone": f"{support:.5f} support / {resistance:.5f} resistance",
        "volatility": volatility,
        "note": "Use only for demo/testing until live data providers are configured.",
        "price": price,
        "indicators": {"recent_high": resistance, "recent_low": support, "avg_range_pips": 40},
    }


def _calendar() -> Dict[str, Any]:
    today = datetime.utcnow().date().isoformat()
    return {
        "provider": "fallback",
        "generated_at": _now(),
        "events": [
            {"date": today, "time": "09:30 London", "currency": "GBP", "event": "UK high-impact data placeholder", "impact": "High", "source": "fallback"},
            {"date": today, "time": "13:30 London", "currency": "USD", "event": "US high-impact data placeholder", "impact": "High", "source": "fallback"},
            {"date": today, "time": "15:00 London", "currency": "USD", "event": "US medium-impact data placeholder", "impact": "Medium", "source": "fallback"},
        ],
        "warnings": ["Fallback economic calendar. Add an economic calendar provider before relying on the news guard."],
    }


def _score_candidate(pair: str, account_balance: float = 10000.0) -> Dict[str, Any]:
    analysis = _analysis_for_pair(pair)
    direction = "buy" if analysis["bias"] == "Bullish" else "sell" if analysis["bias"] == "Bearish" else "none"
    confidence = 88 if direction != "none" else 0
    rr = 2.2 if direction != "none" else 0
    price = float(analysis["price"])
    pip = _pip_size(pair)
    stop_pips = 20.0
    if direction == "buy":
        stop = price - stop_pips * pip
        target = price + stop_pips * rr * pip
    elif direction == "sell":
        stop = price + stop_pips * pip
        target = price - stop_pips * rr * pip
    else:
        stop = price
        target = price
    risk_amount = account_balance * 0.005
    candidate = {
        "pair": pair,
        "direction": direction,
        "setup_type": "fallback_demo_scan" if direction != "none" else "no_trade",
        "setup_label": "Fallback demo scan" if direction != "none" else "No trade",
        "confidence": confidence,
        "rr_estimate": rr,
        "session": "Fallback",
        "in_window": True,
        "scanned_at": _now(),
        "entry_reason": "Fallback Vercel-safe scan. Replace with live scanner once data providers are configured.",
        "entry": round(price, 5),
        "stop_loss": round(stop, 5),
        "take_profit": round(target, 5),
        "stop_pips": stop_pips,
        "risk_amount": round(risk_amount, 2),
        "position_units": round(risk_amount / (stop_pips * 10), 4),
        "risk_pct": 0.5,
        "analysis": analysis,
        "blocked_events": [],
    }
    if direction == "none" or KILL_SWITCH["active"]:
        candidate["status"] = "no_setup" if direction == "none" else "rejected"
        candidate["rejection_reason"] = "No clear bias." if direction == "none" else KILL_SWITCH["reason"]
    else:
        candidate["status"] = "trade_candidate"
        candidate["rejection_reason"] = None
    return candidate


@app.get("/")
async def index():
    return _frontend_file("index.html")


@app.get("/fx-agent")
async def agent_dashboard():
    return _frontend_file("agent.html")


@app.get("/fx-agent/{path:path}")
async def agent_frontend(path: str):
    return _frontend_file("agent.html")


@app.post("/api/auth/login")
async def auth_login(req: LoginRequest):
    return make_session(req.username, req.passcode)


@app.get("/api/auth/me")
async def auth_me(user: str = Depends(current_user)):
    return {"authenticated": True, "user": user}


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": APP_VERSION, "live_trading_enabled": False, "demo_mode": True, "kill_switch_active": KILL_SWITCH["active"]}


@app.get("/api/config")
async def config():
    return {
        "watchlist": WATCHLIST,
        "selected_provider": "vercel-safe-fallback",
        "account_currency": "GBP",
        "rules": {"max_risk_per_trade_pct": 0.5, "max_daily_loss_pct": 1.5, "max_weekly_loss_pct": 4.0, "min_risk_reward": 2.0, "news_guard_minutes": 30, "live_trading_locked": True, "min_confidence_score": 85},
        "configured": {"oanda": False, "twelvedata": False, "fmp_calendar": False},
    }


@app.get("/api/market/snapshot")
async def market_snap():
    return _snapshot()


@app.get("/api/market/analysis")
async def market_analysis():
    return {"generated_at": _now(), "pairs": [_analysis_for_pair(p) for p in WATCHLIST], "warnings": ["Fallback analysis only."]}


@app.get("/api/calendar")
async def calendar():
    return _calendar()


@app.post("/api/scan")
async def scan(req: ScanRequest, user: str = Depends(current_user)):
    analysis = _analysis_for_pair(req.pair)
    rr = float(req.risk_reward or 0)
    confidence = 25 + (25 if req.checklist.get("trend_alignment") else 0) + (15 if rr >= 2 else 0) + (15 if req.checklist.get("planned_zone") else 0) + (15 if req.checklist.get("stop_defined") else 0) + (10 if req.checklist.get("no_news_risk") else 0)
    blockers = []
    if rr < 2:
        blockers.append("Risk/reward below minimum 2R.")
    if not req.checklist.get("stop_defined"):
        blockers.append("No defined stop-loss.")
    verdict = "BLOCKED_BY_HARD_RULES" if blockers else "HIGH_CONFIDENCE_MANUAL_REVIEW" if confidence >= 85 else "WAIT_FOR_MORE_CONFIRMATION"
    return {"score": min(confidence, 100), "confidence_score": min(confidence, 100), "min_confidence_score": 85, "verdict": verdict, "tone": "red" if blockers else "green" if confidence >= 85 else "amber", "message": verdict, "hard_blockers": blockers, "analysis": analysis, "live_trading_locked": True, "mode": "demo/fallback"}


@app.post("/api/risk")
async def risk(req: RiskRequest, user: str = Depends(current_user)):
    stop_pips = abs(req.entry - req.stop_loss) / _pip_size(req.pair)
    reward_pips = abs(req.target - req.entry) / _pip_size(req.pair)
    if stop_pips <= 0:
        raise HTTPException(status_code=422, detail="Stop distance must be greater than zero.")
    risk_amount = req.account_balance * (req.risk_pct / 100)
    lots = risk_amount / (stop_pips * req.pip_value_per_standard_lot)
    rr = reward_pips / stop_pips
    return {"risk_amount": risk_amount, "stop_pips": stop_pips, "reward_pips": reward_pips, "risk_reward": rr, "standard_lots": lots, "position_units": lots * 100000, "verdict": "OK_FOR_REVIEW" if req.risk_pct <= 0.5 and rr >= 2 else "CHECK_RULES", "tone": "green" if req.risk_pct <= 0.5 and rr >= 2 else "amber"}


@app.get("/api/briefing")
async def briefing(user: str = Depends(current_user)):
    return {"generated_at": _now(), "summary": "Demo-safe fallback briefing. Serverless function is running correctly.", "market": _snapshot(), "calendar": _calendar()}


@app.post("/api/automation/readiness")
async def check_readiness(req: AutomationReadinessIn, user: str = Depends(current_user)):
    gates = [req.backtested_trades >= 100, req.forward_trades >= 50, req.avg_r > 0, req.max_drawdown_pct <= 10, req.max_daily_loss_pct <= 2, req.win_rate_pct >= 40 and req.avg_r > 0]
    return {"ready_for_demo_automation": all(gates), "live_trading_locked": True, "passed": sum(gates), "total": len(gates)}


@app.post("/api/journal")
async def journal_add(entry: JournalEntryIn, user: str = Depends(current_user)):
    item = {"id": len(JOURNAL) + 1, "created_at": _now(), "user_name": user, **entry.dict()}
    JOURNAL.append(item)
    return item


@app.get("/api/journal")
async def journal_list(user: str = Depends(current_user)):
    return [j for j in JOURNAL if j.get("user_name") == user]


@app.delete("/api/journal")
async def journal_clear(user: str = Depends(current_user)):
    JOURNAL[:] = [j for j in JOURNAL if j.get("user_name") != user]
    return {"cleared": True}


@app.post("/api/paper")
async def paper_add(trade: PaperTradeIn, user: str = Depends(current_user)):
    item = {"id": len(PAPER_TRADES) + 1, "created_at": _now(), "status": "OPEN", "user_name": user, **trade.dict()}
    PAPER_TRADES.append(item)
    return item


@app.get("/api/paper")
async def paper_list(user: str = Depends(current_user)):
    return [t for t in PAPER_TRADES if t.get("user_name") == user]


@app.post("/api/paper/{trade_id}/close")
async def paper_close(trade_id: int, close_price: Optional[float] = None, user: str = Depends(current_user)):
    for t in PAPER_TRADES:
        if t["id"] == trade_id and t.get("user_name") == user:
            t.update({"status": "CLOSED", "closed_at": _now(), "close_price": close_price})
            return t
    raise HTTPException(status_code=404, detail="Trade not found")


@app.get("/api/paper/stats")
async def paper_statistics(user: str = Depends(current_user)):
    rows = [t for t in PAPER_TRADES if t.get("user_name") == user]
    closed = [r for r in rows if r.get("status") == "CLOSED"]
    return {"trades": len(rows), "open": len(rows) - len(closed), "closed": len(closed)}


@app.post("/api/agent/scan")
async def agent_scan(req: AgentScanRequest, user: str = Depends(current_user)):
    results = [_score_candidate(p, req.account_balance) for p in WATCHLIST]
    SCAN_HISTORY[:0] = results
    return {"scanned_at": _now(), "total_pairs": len(results), "candidates": [r for r in results if r["status"] == "trade_candidate"], "rejected": [r for r in results if r["status"] == "rejected"], "no_setup": [r for r in results if r["status"] == "no_setup"], "trading_allowed": {"allowed": not KILL_SWITCH["active"]}, "kill_switch": KILL_SWITCH["active"]}


@app.get("/api/agent/scan/history")
async def agent_scan_history(user: str = Depends(current_user)):
    return SCAN_HISTORY[:100]


@app.post("/api/agent/execute")
async def agent_execute(req: AgentExecuteRequest, user: str = Depends(current_user)):
    if KILL_SWITCH["active"]:
        raise HTTPException(status_code=403, detail=KILL_SWITCH["reason"] or "Kill switch active")
    candidate = _score_candidate(req.pair, req.account_balance)
    if candidate["status"] != "trade_candidate":
        raise HTTPException(status_code=422, detail=candidate)
    trade = {"id": len(AGENT_TRADES) + 1, "created_at": _now(), "status": "open", "broker_mode": "paper", "order_id": f"PAPER-{len(AGENT_TRADES)+1}", **candidate}
    AGENT_TRADES.append(trade)
    AUDIT_LOG.insert(0, {"id": len(AUDIT_LOG) + 1, "created_at": _now(), "event_type": "execution", "decision": "paper_executed", "pair": req.pair, "reason": "Fallback paper trade created."})
    return {"trade_id": trade["id"], "execution": {"mode": "paper", "status": "filled", "order_id": trade["order_id"]}, "candidate": candidate}


@app.post("/api/agent/manage")
async def agent_manage(req: ManageTradesRequest, user: str = Depends(current_user)):
    return {"actions_taken": [], "open_trades": [t for t in AGENT_TRADES if t.get("status") == "open"]}


@app.get("/api/agent/trades/open")
async def agent_open_trades(user: str = Depends(current_user)):
    return {"open_trades": [t for t in AGENT_TRADES if t.get("status") == "open"], "trading_allowed": {"allowed": not KILL_SWITCH["active"]}, "kill_switch": KILL_SWITCH["active"]}


@app.get("/api/agent/trades")
async def agent_all_trades(user: str = Depends(current_user)):
    return AGENT_TRADES[-500:]


@app.get("/api/agent/trades/closed")
async def agent_closed_trades(user: str = Depends(current_user)):
    return [t for t in AGENT_TRADES if t.get("status") == "closed"][-500:]


@app.get("/api/agent/trades/{trade_id}")
async def agent_get_trade(trade_id: int, user: str = Depends(current_user)):
    for t in AGENT_TRADES:
        if t["id"] == trade_id:
            return t
    raise HTTPException(status_code=404, detail="Trade not found")


@app.post("/api/agent/kill-switch/activate")
async def kill_switch_on(req: KillSwitchRequest, user: str = Depends(current_user)):
    KILL_SWITCH.update({"active": True, "reason": req.reason})
    return {"kill_switch": True, "reason": req.reason, "activated_at": _now()}


@app.post("/api/agent/kill-switch/deactivate")
async def kill_switch_off(user: str = Depends(current_user)):
    KILL_SWITCH.update({"active": False, "reason": None})
    return {"kill_switch": False, "deactivated_at": _now()}


@app.get("/api/agent/kill-switch/status")
async def kill_switch_status():
    return {"active": KILL_SWITCH["active"], "trading_allowed": not KILL_SWITCH["active"]}


@app.post("/api/agent/review/{trade_id}")
async def agent_review_trade(trade_id: int, user: str = Depends(current_user)):
    trade = next((t for t in AGENT_TRADES if t["id"] == trade_id), None)
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    review = "Fallback review generated. Full learning engine should be re-enabled after syntax cleanup."
    trade["post_trade_review"] = review
    return {"trade_id": trade_id, "quality_tag": "fallback_review", "review": review}


@app.post("/api/agent/review/pending/all")
async def agent_review_pending(user: str = Depends(current_user)):
    return {"reviewed_count": 0, "reviews": []}


@app.get("/api/agent/performance")
async def agent_performance(user: str = Depends(current_user)):
    closed = [t for t in AGENT_TRADES if t.get("status") == "closed"]
    return {"status": "insufficient_data", "message": f"{len(closed)} closed trades available.", "count": len(closed)}


@app.post("/api/agent/optimise")
async def agent_optimise(req: OptimisationRequest, user: str = Depends(current_user)):
    return {"report": {"status": "insufficient_data"}, "proposals": [{"type": "info", "message": "Collect more demo trades before optimisation."}], "version_id": None}


@app.get("/api/agent/strategy/versions")
async def agent_versions(user: str = Depends(current_user)):
    return []


@app.get("/api/agent/audit")
async def agent_audit(user: str = Depends(current_user)):
    return AUDIT_LOG[:200]


@app.get("/api/agent/status")
async def agent_status():
    return {"version": APP_VERSION, "mode": "demo", "live_trading_locked": True, "kill_switch_active": KILL_SWITCH["active"], "trading_allowed": {"allowed": not KILL_SWITCH["active"]}, "open_trade_count": len([t for t in AGENT_TRADES if t.get("status") == "open"]), "timestamp": _now()}
