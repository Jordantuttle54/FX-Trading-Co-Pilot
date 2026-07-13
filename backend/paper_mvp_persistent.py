from __future__ import annotations

import json
import math
import os
import random
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import httpx
import psycopg2
from psycopg2.extras import Json
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .auth import current_user, make_session

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
APP_VERSION = "0.7.1-persistent-paper-trades"
WATCHLIST = ["GBP/USD", "EUR/USD", "USD/JPY", "EUR/GBP", "GBP/JPY", "XAU/USD"]
OANDA_PRACTICE = "https://api-fxpractice.oanda.com"
OANDA_LIVE = "https://api-fxtrade.oanda.com"

START_BALANCE = float(os.getenv("PAPER_STARTING_BALANCE", "10000"))
MAX_RISK = float(os.getenv("MAX_RISK_PER_TRADE_PCT", "0.5"))
DAILY_LIMIT = float(os.getenv("MAX_DAILY_LOSS_PCT", "1.5"))
WEEKLY_LIMIT = float(os.getenv("MAX_WEEKLY_LOSS_PCT", "4.0"))
MIN_RR = float(os.getenv("MIN_RISK_REWARD", "2.0"))
MIN_CONF = int(os.getenv("MIN_CONFIDENCE_SCORE", "85"))
ENFORCE_WINDOW = os.getenv("PAPER_TRADING_ENFORCE_WINDOW", "false").lower() == "true"
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

app = FastAPI(title="AI FX Persistent Paper Trading MVP", version=APP_VERSION)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
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
    checklist: Dict[str, Any] = Field(default_factory=dict)

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

class AgentScanRequest(BaseModel):
    account_balance: float = START_BALANCE

class AgentExecuteRequest(BaseModel):
    pair: str
    account_balance: float = START_BALANCE

class ManageTradesRequest(BaseModel):
    current_prices: Dict[str, float] = Field(default_factory=dict)
    account_balance: float = START_BALANCE

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
TRADES: List[Dict[str, Any]] = []
SCAN_HISTORY: List[Dict[str, Any]] = []
AUDIT: List[Dict[str, Any]] = []
KILL_SWITCH = {"active": False, "reason": None}
_DB_OK: Optional[bool] = None


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def pip_size(pair: str) -> float:
    return 0.1 if pair == "XAU/USD" else 0.01 if "JPY" in pair else 0.0001


def precision(pair: str) -> int:
    return 2 if pair == "XAU/USD" else 3 if "JPY" in pair else 5


def rprice(pair: str, price: float) -> float:
    return round(float(price), precision(pair))


def london_window() -> bool:
    h = datetime.now(ZoneInfo("Europe/London")).hour
    return 7 <= h < 11


def session_label() -> str:
    h = datetime.now(ZoneInfo("Europe/London")).hour
    if 7 <= h < 11:
        return "London"
    if 12 <= h < 17:
        return "New York"
    if 0 <= h < 6:
        return "Asia"
    return "Off-session"


def oanda_configured() -> bool:
    return bool(os.getenv("OANDA_ACCESS_TOKEN") and os.getenv("OANDA_ACCOUNT_ID"))


def oanda_base() -> str:
    return OANDA_LIVE if os.getenv("OANDA_ENV", "practice").lower() == "live" else OANDA_PRACTICE


def db_url() -> str:
    if DATABASE_URL and DATABASE_URL.startswith("postgres") and "sslmode=" not in DATABASE_URL:
        return DATABASE_URL + ("&" if "?" in DATABASE_URL else "?") + "sslmode=require"
    return DATABASE_URL


def db_conn():
    return psycopg2.connect(db_url())


def ensure_db() -> bool:
    global _DB_OK
    if _DB_OK is not None:
        return _DB_OK
    if not DATABASE_URL:
        _DB_OK = False
        return False
    try:
        with db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS paper_trades (
                        id TEXT PRIMARY KEY,
                        user_name TEXT NOT NULL,
                        status TEXT NOT NULL,
                        pair TEXT,
                        created_at TEXT,
                        updated_at TEXT,
                        payload JSONB NOT NULL
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS agent_audit (
                        id TEXT PRIMARY KEY,
                        user_name TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        event_type TEXT,
                        pair TEXT,
                        trade_id TEXT,
                        decision TEXT,
                        reason TEXT,
                        payload JSONB NOT NULL
                    )
                """)
        _DB_OK = True
    except Exception:
        _DB_OK = False
    return _DB_OK


def normalise_payload(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return json.loads(value)
    return dict(value)


def storage_mode() -> str:
    return "postgres" if ensure_db() else "memory"


def add_audit(user: str, event_type: str, decision: str, reason: str = "", pair: str = "", trade_id: str | None = None):
    item = {"id": str(uuid.uuid4()), "created_at": now(), "user_name": user, "event_type": event_type, "pair": pair, "trade_id": trade_id, "decision": decision, "reason": reason}
    if ensure_db():
        with db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO agent_audit (id,user_name,created_at,event_type,pair,trade_id,decision,reason,payload) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (item["id"], user, item["created_at"], event_type, pair, trade_id, decision, reason, Json(item)),
                )
    else:
        AUDIT.insert(0, item)


def list_audit(user: str) -> List[Dict[str, Any]]:
    if ensure_db():
        with db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT payload FROM agent_audit WHERE user_name=%s ORDER BY created_at DESC LIMIT 200", (user,))
                return [normalise_payload(r[0]) for r in cur.fetchall()]
    return [a for a in AUDIT if a.get("user_name") == user][:200]


def db_upsert_trade(item: Dict[str, Any]) -> None:
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO paper_trades (id,user_name,status,pair,created_at,updated_at,payload)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (id) DO UPDATE SET
                    status=EXCLUDED.status,
                    pair=EXCLUDED.pair,
                    updated_at=EXCLUDED.updated_at,
                    payload=EXCLUDED.payload
                """,
                (str(item["id"]), item.get("user_name"), item.get("status"), item.get("pair"), item.get("created_at"), item.get("updated_at", now()), Json(item)),
            )


def list_trades(user: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
    if ensure_db():
        with db_conn() as conn:
            with conn.cursor() as cur:
                if status:
                    cur.execute("SELECT payload FROM paper_trades WHERE user_name=%s AND status=%s ORDER BY created_at DESC", (user, status))
                else:
                    cur.execute("SELECT payload FROM paper_trades WHERE user_name=%s ORDER BY created_at DESC", (user,))
                return [normalise_payload(r[0]) for r in cur.fetchall()]
    rows = [t for t in TRADES if t.get("user_name") == user and (status is None or t.get("status") == status)]
    return sorted(rows, key=lambda x: x.get("created_at", ""), reverse=True)


def get_trade(user: str, trade_id: str) -> Dict[str, Any]:
    if ensure_db():
        with db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT payload FROM paper_trades WHERE user_name=%s AND id=%s", (user, str(trade_id)))
                row = cur.fetchone()
                if row:
                    return normalise_payload(row[0])
    else:
        for t in TRADES:
            if str(t.get("id")) == str(trade_id) and t.get("user_name") == user:
                return t
    raise HTTPException(status_code=404, detail="Trade not found")


def save_trade(user: str, t: Dict[str, Any]) -> Dict[str, Any]:
    tid = str(uuid.uuid4())
    item = {"id": tid, "user_name": user, "created_at": now(), "updated_at": now(), "status": "open", "broker_mode": "paper", "order_id": f"PAPER-{tid[:8]}", **t}
    item["entry_price"] = item.get("entry_price", item.get("entry"))
    item["entry"] = item["entry_price"]
    item["take_profit"] = item.get("take_profit", item.get("target"))
    item["target"] = item["take_profit"]
    item["filled_at"] = item["created_at"]
    if ensure_db():
        db_upsert_trade(item)
    else:
        TRADES.append(item)
    return item


def update_trade(item: Dict[str, Any]) -> None:
    item["updated_at"] = now()
    if ensure_db():
        db_upsert_trade(item)
    else:
        for i, t in enumerate(TRADES):
            if str(t.get("id")) == str(item.get("id")):
                TRADES[i] = item
                break


def base_price(pair: str) -> float:
    bases = {"GBP/USD": 1.2700, "EUR/USD": 1.0850, "USD/JPY": 156.20, "EUR/GBP": 0.8550, "GBP/JPY": 198.50, "XAU/USD": 2350.0}
    random.seed(abs(hash(pair)) % 100000 + int(datetime.utcnow().strftime("%Y%m%d%H")))
    return bases.get(pair, 1.0) * (1 + random.uniform(-0.002, 0.002))


def synthetic_snapshot() -> Dict[str, Any]:
    quotes = []
    for pair in WATCHLIST:
        price = base_price(pair)
        pip = pip_size(pair)
        quotes.append({"pair": pair, "price": rprice(pair, price), "bid": rprice(pair, price - pip), "ask": rprice(pair, price + pip), "spread_pips": 2, "timestamp": now(), "source": "synthetic-fallback"})
    return {"provider": "synthetic-fallback", "generated_at": now(), "quotes": quotes, "warnings": ["Fallback data only. Add OANDA practice credentials for live market data."]}


def oanda_snapshot() -> Dict[str, Any]:
    instruments = ",".join(p.replace("/", "_") for p in WATCHLIST)
    url = f"{oanda_base()}/v3/accounts/{os.getenv('OANDA_ACCOUNT_ID')}/pricing"
    with httpx.Client(timeout=12) as client:
        res = client.get(url, params={"instruments": instruments}, headers={"Authorization": f"Bearer {os.getenv('OANDA_ACCESS_TOKEN')}"})
        res.raise_for_status()
        data = res.json()
    by_inst = {p["instrument"]: p for p in data.get("prices", [])}
    quotes = []
    for pair in WATCHLIST:
        raw = by_inst.get(pair.replace("/", "_"))
        if not raw:
            continue
        bid = float(raw["closeoutBid"])
        ask = float(raw["closeoutAsk"])
        mid = (bid + ask) / 2
        quotes.append({"pair": pair, "price": rprice(pair, mid), "bid": rprice(pair, bid), "ask": rprice(pair, ask), "spread_pips": round(abs(ask - bid) / pip_size(pair), 2), "timestamp": raw.get("time", now()), "source": "oanda-practice"})
    return {"provider": "oanda", "generated_at": now(), "quotes": quotes, "warnings": []}


def snapshot() -> Dict[str, Any]:
    if oanda_configured() and os.getenv("DATA_PROVIDER", "auto").lower() in ("auto", "oanda"):
        try:
            live = oanda_snapshot()
            if live["quotes"]:
                return live
        except Exception as exc:
            fb = synthetic_snapshot()
            fb["provider"] = "oanda-failed-fallback"
            fb["warnings"].insert(0, f"OANDA failed: {exc}")
            return fb
    return synthetic_snapshot()


def synthetic_candles(pair: str) -> List[Dict[str, Any]]:
    price = base_price(pair)
    pip = pip_size(pair)
    vol = 12 * pip if pair != "XAU/USD" else 2.0
    out = []
    random.seed(abs(hash(pair + "candles")) % 100000 + int(datetime.utcnow().strftime("%Y%m%d")))
    for i in range(120):
        drift = math.sin(i / 12) * vol * 0.35
        op = price
        close = max(pip, op + random.uniform(-vol, vol) + drift)
        high = max(op, close) + abs(random.uniform(0, vol * 0.7))
        low = min(op, close) - abs(random.uniform(0, vol * 0.7))
        out.append({"open": op, "high": high, "low": low, "close": close})
        price = close
    return out


def oanda_candles(pair: str) -> List[Dict[str, Any]]:
    url = f"{oanda_base()}/v3/instruments/{pair.replace('/', '_')}/candles"
    with httpx.Client(timeout=12) as client:
        res = client.get(url, params={"count": 120, "granularity": "H1", "price": "M"}, headers={"Authorization": f"Bearer {os.getenv('OANDA_ACCESS_TOKEN')}"})
        res.raise_for_status()
        data = res.json()
    out = []
    for c in data.get("candles", []):
        if not c.get("complete", True):
            continue
        m = c["mid"]
        out.append({"open": float(m["o"]), "high": float(m["h"]), "low": float(m["l"]), "close": float(m["c"])})
    return out


def get_candles(pair: str) -> List[Dict[str, Any]]:
    if oanda_configured():
        try:
            live = oanda_candles(pair)
            if len(live) >= 20:
                return live
        except Exception:
            pass
    return synthetic_candles(pair)


def sma(vals: List[float], n: int) -> Optional[float]:
    return sum(vals[-n:]) / n if len(vals) >= n else None


def analyse(pair: str) -> Dict[str, Any]:
    cs = get_candles(pair)
    closes = [float(c["close"]) for c in cs]
    highs = [float(c["high"]) for c in cs]
    lows = [float(c["low"]) for c in cs]
    price = closes[-1] if closes else base_price(pair)
    if len(closes) < 20:
        return {"pair": pair, "bias": "Neutral", "trend": "Insufficient data", "zone": "N/A", "volatility": "Unknown", "note": "Need more candles.", "price": rprice(pair, price), "indicators": {}}
    s20 = sma(closes, 20) or price
    s50 = sma(closes, min(50, len(closes))) or s20
    recent_high = max(highs[-20:])
    recent_low = min(lows[-20:])
    avg_pips = (sum(abs(h - l) for h, l in zip(highs[-20:], lows[-20:])) / 20) / pip_size(pair)
    if price > s20 > s50:
        bias, trend, note = "Bullish", "Price is above the 20 and 50 period moving averages.", "Buy setups may be higher quality after pullbacks."
    elif price < s20 < s50:
        bias, trend, note = "Bearish", "Price is below the 20 and 50 period moving averages.", "Sell setups may be higher quality after pullbacks."
    else:
        bias, trend, note = "Neutral", "Mixed or ranging structure.", "Wait for cleaner structure."
    vol = "Very High" if avg_pips > 120 else "High" if avg_pips > 70 else "Medium" if avg_pips > 35 else "Low"
    p = precision(pair)
    return {"pair": pair, "bias": bias, "trend": trend, "zone": f"{recent_low:.{p}f} support / {recent_high:.{p}f} resistance", "volatility": vol, "note": note, "price": rprice(pair, price), "indicators": {"sma20": rprice(pair, s20), "sma50": rprice(pair, s50), "recent_high": rprice(pair, recent_high), "recent_low": rprice(pair, recent_low), "avg_range_pips": round(avg_pips, 1)}}


def score_candidate(pair: str, account_balance: float = START_BALANCE) -> Dict[str, Any]:
    a = analyse(pair)
    direction = "buy" if a["bias"] == "Bullish" else "sell" if a["bias"] == "Bearish" else "none"
    rr = 2.2 if direction != "none" else 0.0
    conf = 88 if direction != "none" else 0
    if a.get("volatility") == "Medium":
        conf += 3
    elif a.get("volatility") == "Very High":
        conf -= 8
    conf = max(0, min(96, conf))
    entry = float(a["price"])
    pip = pip_size(pair)
    stop_pips = 25.0 if pair == "XAU/USD" else 20.0
    if direction == "buy":
        sl, tp = entry - stop_pips * pip, entry + stop_pips * rr * pip
    elif direction == "sell":
        sl, tp = entry + stop_pips * pip, entry - stop_pips * rr * pip
    else:
        sl = tp = entry
    risk_amount = round(account_balance * (MAX_RISK / 100), 2)
    stop_dist = abs(entry - sl)
    rejects = []
    if direction == "none":
        rejects.append("No clean directional bias.")
    if ENFORCE_WINDOW and not london_window():
        rejects.append("Outside the configured London paper-trading window.")
    if direction != "none" and conf < MIN_CONF:
        rejects.append(f"Confidence {conf}% is below {MIN_CONF}%.")
    if KILL_SWITCH["active"]:
        rejects.append(KILL_SWITCH["reason"] or "Kill switch active.")
    status = "trade_candidate" if not rejects else ("no_setup" if direction == "none" else "rejected")
    return {"pair": pair, "direction": direction, "setup_type": "live_data_trend_continuation" if direction != "none" else "no_trade", "setup_label": "Live-data trend continuation" if direction != "none" else "No trade", "confidence": conf, "rr_estimate": rr, "session": session_label(), "in_window": london_window(), "scanned_at": now(), "status": status, "rejection_reason": " | ".join(rejects) if rejects else None, "entry_reason": f"{pair} {direction} paper-trade candidate based on live/demo candle trend structure." if direction != "none" else "No clear setup detected.", "entry": rprice(pair, entry), "entry_price": rprice(pair, entry), "stop_loss": rprice(pair, sl), "take_profit": rprice(pair, tp), "target": rprice(pair, tp), "stop_pips": stop_pips, "risk_amount": risk_amount, "position_units": round(risk_amount / stop_dist, 2) if stop_dist > 0 else 0, "risk_pct": MAX_RISK, "account_balance": account_balance, "analysis": a, "blocked_events": [], "source": "oanda" if oanda_configured() else "synthetic-fallback"}


def calc_r(t: Dict[str, Any], close_price: float) -> float:
    entry = float(t.get("entry_price", t.get("entry")))
    sl = float(t["stop_loss"])
    dist = abs(entry - sl)
    if dist <= 0:
        return 0.0
    return (close_price - entry) / dist if t["direction"] == "buy" else (entry - close_price) / dist


def tag_trade(t: Dict[str, Any]) -> str:
    r = float(t.get("result_r") or 0)
    if r > 0:
        return "good_setup_good_execution"
    if r <= -1:
        return "good_setup_normal_loss"
    return "good_setup_poor_execution"


def review(t: Dict[str, Any]) -> str:
    r = float(t.get("result_r") or 0)
    outcome = "win" if r > 0 else "loss" if r < 0 else "breakeven"
    return f"POST-TRADE REVIEW - {t.get('pair')} {str(t.get('direction','')).upper()}\nOutcome: {outcome} ({r:+.2f}R).\nQuality tag: {t.get('quality_tag')}.\nLearning note: collect at least 50 closed paper trades before changing rules."


def close_trade(user: str, trade_id: str, close_price: float, reason: str) -> Dict[str, Any]:
    t = get_trade(user, trade_id)
    if t.get("status") == "closed":
        return t
    r = round(calc_r(t, close_price), 3)
    money = round(float(t.get("risk_amount") or 0) * r, 2)
    t.update({"status": "closed", "updated_at": now(), "closed_at": now(), "close_price": rprice(t["pair"], close_price), "close_reason": reason, "result_r": r, "result_money": money})
    t["quality_tag"] = tag_trade(t)
    t["post_trade_review"] = review(t)
    update_trade(t)
    add_audit(user, "paper_close", "closed", f"Closed by {reason}: {r:+.2f}R / {money:+.2f}.", t["pair"], trade_id)
    return t


def manage_trades(user: str, prices: Optional[Dict[str, float]] = None) -> List[Dict[str, Any]]:
    if not prices:
        prices = {q["pair"]: float(q["price"]) for q in snapshot().get("quotes", [])}
    actions = []
    for t in list_trades(user, "open"):
        price = prices.get(t["pair"])
        if price is None:
            continue
        if t["direction"] == "buy":
            hit_stop, hit_target = price <= float(t["stop_loss"]), price >= float(t["take_profit"])
        else:
            hit_stop, hit_target = price >= float(t["stop_loss"]), price <= float(t["take_profit"])
        if hit_stop or hit_target:
            reason = "stop" if hit_stop else "target"
            c = close_trade(user, str(t["id"]), float(price), reason)
            actions.append({"trade_id": c["id"], "pair": t["pair"], "action": f"close_{reason}", "reason": f"{t['pair']} hit {reason}.", "close_price": c.get("close_price"), "result_r": c.get("result_r"), "result_money": c.get("result_money")})
    return actions


def perf(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    closed = [t for t in rows if t.get("status") == "closed" and t.get("result_r") is not None]
    vals = [float(t["result_r"]) for t in closed]
    wins = [v for v in vals if v > 0]
    losses = [v for v in vals if v <= 0]
    total = sum(vals)
    gp, gl = sum(wins), abs(sum(losses))
    return {"count": len(closed), "win_rate": round((len(wins) / len(closed) * 100) if closed else 0, 1), "avg_r": round((total / len(closed)) if closed else 0, 3), "expectancy": round((total / len(closed)) if closed else 0, 3), "profit_factor": round((gp / gl) if gl else (999 if gp else 0), 2), "total_r": round(total, 2), "max_loss_r": round(min(vals), 3) if vals else 0, "estimated_pnl": round(sum(float(t.get("result_money") or 0) for t in closed), 2)}


@app.get("/")
async def index():
    return FileResponse(FRONTEND / "index.html") if (FRONTEND / "index.html").exists() else JSONResponse({"status": "ok", "version": APP_VERSION})

@app.get("/fx-agent")
async def agent_dashboard():
    return FileResponse(FRONTEND / "agent.html") if (FRONTEND / "agent.html").exists() else await index()

@app.get("/fx-agent/{path:path}")
async def agent_frontend(path: str):
    return await agent_dashboard()

@app.post("/api/auth/login")
async def auth_login(req: LoginRequest):
    return make_session(req.username, req.passcode)

@app.get("/api/auth/me")
async def auth_me(user: str = Depends(current_user)):
    return {"authenticated": True, "user": user}

@app.get("/api/health")
async def health():
    return {"status": "ok", "version": APP_VERSION, "paper_trading": True, "live_trading_enabled": False, "live_trading_locked": True, "data_provider": "oanda" if oanda_configured() else "synthetic-fallback", "storage_mode": storage_mode()}

@app.get("/api/config")
async def config():
    return {"watchlist": WATCHLIST, "selected_provider": "oanda" if oanda_configured() else "synthetic-fallback", "account_currency": "GBP", "paper_trading": {"starting_balance": START_BALANCE, "enforce_london_window": ENFORCE_WINDOW, "live_trading_locked": True, "storage_mode": storage_mode()}, "rules": {"max_risk_per_trade_pct": MAX_RISK, "max_daily_loss_pct": DAILY_LIMIT, "max_weekly_loss_pct": WEEKLY_LIMIT, "min_risk_reward": MIN_RR, "live_trading_locked": True, "min_confidence_score": MIN_CONF}, "configured": {"oanda": oanda_configured(), "auth_passcode": bool(os.getenv("AUTH_PASSCODE")), "auth_token_secret": bool(os.getenv("AUTH_TOKEN_SECRET")), "database": storage_mode() == "postgres"}}

@app.get("/api/status")
async def legacy_status():
    return await config()

@app.get("/api/market/snapshot")
async def market_snap():
    return snapshot()

@app.get("/api/market/analysis")
async def market_analysis():
    return {"generated_at": now(), "pairs": [analyse(p) for p in WATCHLIST], "warnings": [] if oanda_configured() else ["Synthetic fallback analysis. Add OANDA practice credentials for live candle data."]}

@app.get("/api/market/candles")
async def market_candles(pair: str = "GBP/USD", interval: str = "1h", count: int = 120):
    return {"pair": pair, "provider": "oanda" if oanda_configured() else "synthetic-fallback", "candles": get_candles(pair), "warning": "" if oanda_configured() else "Synthetic fallback data. Add OANDA practice credentials for live candle data."}

@app.get("/api/calendar")
async def calendar():
    today = datetime.utcnow().date().isoformat()
    return {"provider": "fallback", "generated_at": now(), "events": [{"date": today, "time": "09:30 London", "currency": "GBP", "event": "UK high-impact data placeholder", "impact": "High", "source": "fallback"}, {"date": today, "time": "13:30 London", "currency": "USD", "event": "US high-impact data placeholder", "impact": "High", "source": "fallback"}], "warnings": ["Fallback calendar only."]}

@app.post("/api/scan")
async def scan(req: ScanRequest, user: str = Depends(current_user)):
    return {"score": 85, "confidence_score": 85, "min_confidence_score": MIN_CONF, "verdict": "HIGH_CONFIDENCE_MANUAL_REVIEW", "tone": "green", "message": "Manual scan endpoint active.", "hard_blockers": [], "analysis": analyse(req.pair), "live_trading_locked": True, "mode": "paper"}

@app.post("/api/agent/scan")
async def agent_scan(req: AgentScanRequest, user: str = Depends(current_user)):
    results = [score_candidate(p, req.account_balance) for p in WATCHLIST]
    SCAN_HISTORY[:0] = results
    for r in results:
        add_audit(user, "scan", r["status"], r.get("rejection_reason") or r.get("entry_reason", ""), r["pair"])
    return {"scanned_at": now(), "total_pairs": len(results), "candidates": [r for r in results if r["status"] == "trade_candidate"], "rejected": [r for r in results if r["status"] == "rejected"], "no_setup": [r for r in results if r["status"] == "no_setup"], "trading_allowed": {"allowed": not KILL_SWITCH["active"], "daily_limit": DAILY_LIMIT, "weekly_limit": WEEKLY_LIMIT}, "kill_switch": KILL_SWITCH["active"], "provider": "oanda" if oanda_configured() else "synthetic-fallback"}

@app.get("/api/agent/scan/history")
async def agent_scan_history(user: str = Depends(current_user)):
    return SCAN_HISTORY[:100]

@app.post("/api/risk")
async def risk(req: RiskRequest, user: str = Depends(current_user)):
    stop_pips = abs(req.entry - req.stop_loss) / pip_size(req.pair)
    reward_pips = abs(req.target - req.entry) / pip_size(req.pair)
    if stop_pips <= 0:
        raise HTTPException(status_code=422, detail="Stop distance must be greater than zero.")
    risk_amount = req.account_balance * (req.risk_pct / 100)
    lots = risk_amount / (stop_pips * req.pip_value_per_standard_lot)
    rr = reward_pips / stop_pips
    return {"risk_amount": round(risk_amount, 2), "stop_pips": round(stop_pips, 2), "reward_pips": round(reward_pips, 2), "risk_reward": round(rr, 2), "standard_lots": round(lots, 4), "position_units": round(lots * 100000, 0), "verdict": "OK_FOR_REVIEW" if req.risk_pct <= MAX_RISK and rr >= MIN_RR else "CHECK_RULES", "tone": "green" if req.risk_pct <= MAX_RISK and rr >= MIN_RR else "amber"}

@app.get("/api/briefing")
async def briefing(user: str = Depends(current_user)):
    return {"generated_at": now(), "summary": "Paper trading mode is active. Live trading remains locked.", "market": snapshot()}

@app.post("/api/automation/readiness")
async def check_readiness(req: AutomationReadinessIn, user: str = Depends(current_user)):
    return {"ready_for_demo_automation": False, "live_trading_locked": True, "passed": 0, "total": 6}

@app.post("/api/journal")
async def journal_add(entry: JournalEntryIn, user: str = Depends(current_user)):
    item = {"id": str(uuid.uuid4()), "created_at": now(), "user_name": user, **entry.dict()}
    JOURNAL.append(item)
    return item

@app.get("/api/journal")
async def journal_list(user: str = Depends(current_user)):
    return [j for j in JOURNAL if j.get("user_name") == user]

@app.delete("/api/journal")
async def journal_clear(user: str = Depends(current_user)):
    JOURNAL[:] = [j for j in JOURNAL if j.get("user_name") != user]
    return {"cleared": True}

@app.post("/api/agent/execute")
async def agent_execute(req: AgentExecuteRequest, user: str = Depends(current_user)):
    if KILL_SWITCH["active"]:
        raise HTTPException(status_code=403, detail=KILL_SWITCH["reason"] or "Kill switch active")
    c = score_candidate(req.pair, req.account_balance)
    if c["status"] != "trade_candidate":
        raise HTTPException(status_code=422, detail=c)
    t = save_trade(user, c)
    add_audit(user, "paper_execute", "opened", "Paper trade opened. No real order was sent.", req.pair, str(t["id"]))
    return {"trade_id": t["id"], "execution": {"mode": "paper", "status": "filled", "order_id": t["order_id"], "live_money": False}, "candidate": c, "trade": t, "storage_mode": storage_mode()}

@app.post("/api/agent/manage")
async def agent_manage(req: ManageTradesRequest, user: str = Depends(current_user)):
    actions = manage_trades(user, req.current_prices or None)
    return {"actions_taken": actions, "open_trades": list_trades(user, "open"), "snapshot": snapshot(), "storage_mode": storage_mode()}

@app.get("/api/agent/trades/open")
async def agent_open_trades(user: str = Depends(current_user)):
    return {"open_trades": list_trades(user, "open"), "trading_allowed": {"allowed": not KILL_SWITCH["active"], "daily_loss_pct": 0.0, "weekly_loss_pct": 0.0, "daily_limit": DAILY_LIMIT, "weekly_limit": WEEKLY_LIMIT}, "kill_switch": KILL_SWITCH["active"], "storage_mode": storage_mode()}

@app.get("/api/agent/trades")
async def agent_all_trades(user: str = Depends(current_user)):
    return list_trades(user)

@app.get("/api/agent/trades/closed")
async def agent_closed_trades(user: str = Depends(current_user)):
    return list_trades(user, "closed")

@app.get("/api/agent/trades/{trade_id}")
async def agent_get_trade(trade_id: str, user: str = Depends(current_user)):
    return get_trade(user, trade_id)

@app.post("/api/paper/{trade_id}/close")
async def paper_close(trade_id: str, close_price: Optional[float] = None, user: str = Depends(current_user)):
    t = get_trade(user, trade_id)
    if close_price is None:
        close_price = {q["pair"]: float(q["price"]) for q in snapshot().get("quotes", [])}.get(t["pair"])
    if close_price is None:
        raise HTTPException(status_code=422, detail="No current price available.")
    return close_trade(user, trade_id, float(close_price), "manual")

@app.get("/api/paper/stats")
async def paper_statistics(user: str = Depends(current_user)):
    rows = list_trades(user)
    p = perf(rows)
    return {"trades": len(rows), "open": len([r for r in rows if r.get("status") == "open"]), "closed": p["count"], **p}

@app.post("/api/agent/review/{trade_id}")
async def agent_review_trade(trade_id: str, user: str = Depends(current_user)):
    t = get_trade(user, trade_id)
    if t.get("status") != "closed":
        raise HTTPException(status_code=422, detail="Trade is not closed yet.")
    t["quality_tag"] = tag_trade(t)
    t["post_trade_review"] = review(t)
    update_trade(t)
    return {"trade_id": trade_id, "quality_tag": t["quality_tag"], "tag_label": t["quality_tag"].replace("_", " "), "review": t["post_trade_review"], "trade": t}

@app.post("/api/agent/review/pending/all")
async def agent_review_pending(user: str = Depends(current_user)):
    reviewed = []
    for t in list_trades(user, "closed"):
        if not t.get("post_trade_review"):
            reviewed.append(await agent_review_trade(str(t["id"]), user))
    return {"reviewed_count": len(reviewed), "reviews": reviewed}

@app.get("/api/agent/performance")
async def agent_performance(user: str = Depends(current_user)):
    rows = list_trades(user)
    closed = [t for t in rows if t.get("status") == "closed"]
    if len(closed) < 5:
        return {"status": "insufficient_data", "message": f"{len(closed)} closed paper trades available. Need at least 5 for a basic report and 50 before optimisation.", "count": len(closed)}
    overall = perf(rows)
    return {"status": "ok", "count": len(closed), "overall": overall, "max_drawdown_r": 0, "by_pair": {}, "by_setup": {}, "by_session": {}, "by_confidence": {}, "by_tag": {}, "ready_for_optimisation": len(closed) >= 50}

@app.post("/api/agent/optimise")
async def agent_optimise(req: OptimisationRequest, user: str = Depends(current_user)):
    return {"report": await agent_performance(user), "proposals": [{"type": "info", "message": "Collect at least 50 closed paper trades before optimisation proposals."}], "version_id": None}

@app.get("/api/agent/strategy/versions")
async def agent_versions(user: str = Depends(current_user)):
    return []

@app.get("/api/agent/audit")
async def agent_audit(user: str = Depends(current_user)):
    return list_audit(user)

@app.post("/api/agent/kill-switch/activate")
async def kill_switch_on(req: KillSwitchRequest, user: str = Depends(current_user)):
    KILL_SWITCH.update({"active": True, "reason": req.reason})
    return {"kill_switch": True, "reason": req.reason, "activated_at": now()}

@app.post("/api/agent/kill-switch/deactivate")
async def kill_switch_off(user: str = Depends(current_user)):
    KILL_SWITCH.update({"active": False, "reason": None})
    return {"kill_switch": False, "deactivated_at": now()}

@app.get("/api/agent/kill-switch/status")
async def kill_switch_status():
    return {"active": KILL_SWITCH["active"], "trading_allowed": not KILL_SWITCH["active"]}

@app.get("/api/agent/status")
async def agent_status(user: str = Depends(current_user)):
    actions = manage_trades(user)
    open_trades = list_trades(user, "open")
    return {"version": APP_VERSION, "user": user, "storage_mode": storage_mode(), "live_trading_enabled": False, "live_trading_locked": True, "paper_trading": True, "kill_switch_active": KILL_SWITCH["active"], "kill_switch_reason": KILL_SWITCH["reason"], "london_window_now": london_window(), "session": session_label(), "trading_allowed": {"allowed": not KILL_SWITCH["active"], "reason": KILL_SWITCH["reason"], "daily_loss_pct": 0.0, "weekly_loss_pct": 0.0, "daily_limit": DAILY_LIMIT, "weekly_limit": WEEKLY_LIMIT}, "open_trade_count": len(open_trades), "open_trades": open_trades, "management_actions": actions}
