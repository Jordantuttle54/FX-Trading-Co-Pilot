"""Lets the agent scan and open paper trades on a schedule, with no browser open.

Until now nothing opened a trade unless somebody pressed "Run Full Scan" in the
UI, so an unattended agent closed positions but never took any. This adds the
missing half: a scheduled run that scans the watchlist, applies every safety
gate, and opens the trades that pass.

Two principles run through it. Every gate is checked per run rather than
trusted from configuration, because an agent nobody is watching has to be
defensive about its own state. And every run records what it decided, including
the boring "looked, found nothing" case - silence from a scheduled job is
otherwise indistinguishable from it having quietly died.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import Depends, HTTPException, Query, Request
from psycopg2.extras import Json
from pydantic import BaseModel

from . import notify as notifier
from . import paper_mvp_persistent as base
from . import paper_mvp_storage_compat as compat
from . import paper_mvp_quick_trade as quick
from . import paper_mvp_auto_close as autoclose
from . import paper_mvp_trade_repair as chain

app = chain.app

CONFIG_TABLE = "agent_config_agent"
RUNS_TABLE = "agent_runs_agent"

# Kept off until switched on deliberately. An agent that starts trading the
# moment it is deployed is not a feature.
DEFAULT_CONFIG: Dict[str, Any] = {
    "enabled": False,
    "pairs": [],                 # empty means the whole watchlist
    "strategies": [],            # empty means each pair's own configured strategies
    "max_open_trades": 3,
    "max_trades_per_day": 6,
    "min_confidence": base.MIN_CONF,
    "respect_window": True,
    "fixed_units": None,         # None means risk-based sizing
    "notify_webhook": "",        # ntfy.sh / Discord / Slack URL, empty = no alerts
}

# How long without a run before the agent is presumed broken rather than quiet.
# Comfortably longer than a daily cron so a normal schedule never trips it.
STALE_RUN_HOURS = float(os.getenv("AGENT_STALE_RUN_HOURS", "30"))

# Its own guard rather than ensure_db(): that flag can be cached True from
# before these tables existed, in a warm process that then never creates them.
# That exact bug already cost us the strategy_versions table in production.
_AGENT_TABLES_OK = False


class AgentConfigRequest(BaseModel):
    enabled: Optional[bool] = None
    pairs: Optional[List[str]] = None
    strategies: Optional[List[str]] = None
    max_open_trades: Optional[int] = None
    max_trades_per_day: Optional[int] = None
    min_confidence: Optional[int] = None
    respect_window: Optional[bool] = None
    fixed_units: Optional[float] = None
    notify_webhook: Optional[str] = None


class AgentRunRequest(BaseModel):
    dry_run: bool = False


def ensure_agent_tables() -> bool:
    global _AGENT_TABLES_OK
    if _AGENT_TABLES_OK:
        return True
    if not base.DATABASE_URL:
        return False
    try:
        with base.db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {CONFIG_TABLE} (
                        user_name TEXT PRIMARY KEY,
                        updated_at TEXT NOT NULL,
                        payload JSONB NOT NULL
                    )
                    """
                )
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {RUNS_TABLE} (
                        id TEXT PRIMARY KEY,
                        user_name TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        payload JSONB NOT NULL
                    )
                    """
                )
        _AGENT_TABLES_OK = True
        return True
    except Exception:
        return False


# In-memory fallback so everything still works without a database.
_MEM_CONFIG: Dict[str, Dict[str, Any]] = {}
_MEM_RUNS: List[Dict[str, Any]] = []


def get_agent_config(user: str) -> Dict[str, Any]:
    stored: Dict[str, Any] = {}
    if ensure_agent_tables():
        try:
            with base.db_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(f"SELECT payload FROM {CONFIG_TABLE} WHERE user_name=%s", (user,))
                    row = cur.fetchone()
                    if row and row[0]:
                        stored = base.normalise_payload(row[0])
        except Exception:
            stored = {}
    else:
        stored = _MEM_CONFIG.get(user, {})
    return {**DEFAULT_CONFIG, **stored}


def save_agent_config(user: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    config = {**get_agent_config(user), **{k: v for k, v in updates.items() if v is not None}}
    config["max_open_trades"] = max(0, min(int(config["max_open_trades"]), 20))
    config["max_trades_per_day"] = max(0, min(int(config["max_trades_per_day"]), 50))
    config["min_confidence"] = max(0, min(int(config["min_confidence"]), 100))
    config["pairs"] = [p for p in (config.get("pairs") or []) if p in base.WATCHLIST]
    config["strategies"] = [s for s in (config.get("strategies") or []) if s in base.STRATEGIES]

    # Only https, so trade details can't go out in the clear. An empty string
    # is how you turn alerts off, so it has to survive the None-filtering above.
    hook = str(updates.get("notify_webhook", config.get("notify_webhook") or "")).strip()
    config["notify_webhook"] = hook if hook.lower().startswith("https://") else ""

    if ensure_agent_tables():
        with base.db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {CONFIG_TABLE} (user_name, updated_at, payload)
                    VALUES (%s,%s,%s)
                    ON CONFLICT (user_name) DO UPDATE SET
                        updated_at=EXCLUDED.updated_at, payload=EXCLUDED.payload
                    """,
                    (user, base.now(), Json(config)),
                )
    else:
        _MEM_CONFIG[user] = config
    return config


def record_run(user: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    item = {"id": str(uuid.uuid4()), "user_name": user, "created_at": base.now(), **payload}
    if ensure_agent_tables():
        try:
            with base.db_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"INSERT INTO {RUNS_TABLE} (id,user_name,created_at,payload) VALUES (%s,%s,%s,%s)",
                        (item["id"], user, item["created_at"], Json(item)),
                    )
        except Exception:
            pass
    else:
        _MEM_RUNS.insert(0, item)
        del _MEM_RUNS[50:]
    return item


def list_runs(user: str, limit: int = 20) -> List[Dict[str, Any]]:
    if not ensure_agent_tables():
        return [r for r in _MEM_RUNS if r.get("user_name") == user][:limit]
    try:
        with base.db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT payload FROM {RUNS_TABLE} WHERE user_name=%s ORDER BY created_at DESC LIMIT %s",
                    (user, limit),
                )
                return [base.normalise_payload(r[0]) for r in cur.fetchall()]
    except Exception:
        return []


def _closed_since(user: str, since: datetime) -> List[Dict[str, Any]]:
    out = []
    for t in compat.compat_list_trades(user, "closed"):
        raw = t.get("closed_at") or t.get("updated_at") or t.get("created_at") or ""
        try:
            when = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except Exception:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if when >= since:
            out.append(t)
    return out


def loss_limit_state(user: str, balance: float) -> Dict[str, Any]:
    """Realised loss today and this week, against the configured limits.

    The status endpoint has always reported these as 0.0. That is harmless
    while a human is deciding every trade and fatal once nothing is watching,
    so the agent computes them for real before it opens anything.
    """
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = day_start - timedelta(days=day_start.weekday())
    balance = max(1.0, balance)

    daily_pnl = round(sum(float(t.get("result_money") or 0) for t in _closed_since(user, day_start)), 2)
    weekly_pnl = round(sum(float(t.get("result_money") or 0) for t in _closed_since(user, week_start)), 2)
    daily_loss_pct = round(max(0.0, -daily_pnl) / balance * 100, 3)
    weekly_loss_pct = round(max(0.0, -weekly_pnl) / balance * 100, 3)

    return {
        "daily_pnl": daily_pnl,
        "weekly_pnl": weekly_pnl,
        "daily_loss_pct": daily_loss_pct,
        "weekly_loss_pct": weekly_loss_pct,
        "daily_limit": base.DAILY_LIMIT,
        "weekly_limit": base.WEEKLY_LIMIT,
        "daily_breached": daily_loss_pct >= base.DAILY_LIMIT,
        "weekly_breached": weekly_loss_pct >= base.WEEKLY_LIMIT,
    }


# A quote this old means the market is shut, not that it stopped moving. Live
# FX quotes refresh constantly, so nothing legitimate is this stale.
MAX_QUOTE_AGE_MINUTES = float(os.getenv("AGENT_MAX_QUOTE_AGE_MINUTES", "15"))


def quote_freshness() -> Dict[str, Dict[str, Any]]:
    """How old each pair's last quote is, in minutes.

    This is what makes running the agent outside the London window safe. The
    window used to be doing double duty - a strategy preference AND an
    accidental guard against trading a closed market. Drop the window and only
    this stands between the agent and Saturday's stale Friday-close prices.
    """
    out: Dict[str, Dict[str, Any]] = {}
    try:
        snap = base.snapshot()
    except Exception:
        return out

    now = datetime.now(timezone.utc)
    for q in snap.get("quotes", []):
        pair = q.get("pair")
        if not pair:
            continue
        age = None
        raw_ts = str(q.get("timestamp") or "")
        try:
            when = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            age = round((now - when).total_seconds() / 60.0, 1)
        except Exception:
            age = None
        synthetic = "synthetic" in str(q.get("source", "")).lower()
        out[pair] = {
            "age_minutes": age,
            # Synthetic quotes are stamped with our own clock, so their age is
            # meaningless but parseable. Only a real quote can vouch for itself.
            "age_known": age is not None and not synthetic,
            "synthetic": synthetic,
            # Absent on synthetic quotes, so default to True and let the
            # synthetic check above be the thing that rejects those.
            "tradeable": bool(q.get("tradeable", True)),
            "market_status": str(q.get("market_status") or ""),
            # Kept so the scanner can price the entry off the same quote we
            # just vetted, rather than fetching the book a second time.
            "quote": q,
        }
    return out


def _opened_today(user: str) -> int:
    day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    count = 0
    for t in compat.compat_list_trades(user):
        if str(t.get("trade_origin") or "") != "agent_auto":
            continue
        raw = t.get("created_at") or ""
        try:
            when = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except Exception:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if when >= day_start:
            count += 1
    return count


def _account_balance(user: str) -> float:
    try:
        from . import paper_mvp_wallet as wallet
        return float(wallet.wallet_summary(user).get("balance") or base.START_BALANCE)
    except Exception:
        return float(base.START_BALANCE)


def run_agent_once(user: str, trigger: str = "cron", dry_run: bool = False) -> Dict[str, Any]:
    """One full scan-and-open pass. Always returns a record of what it decided."""
    config = get_agent_config(user)
    balance = _account_balance(user)
    limits = loss_limit_state(user, balance)
    opened: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    considered: List[Dict[str, Any]] = []

    def finish(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Record the run, then alert on it if it's worth interrupting someone."""
        run = record_run(user, payload)
        alert = notifier.summarise_run(run)
        if alert:
            run["notified"] = notifier.send(
                alert["title"], alert["message"], config, alert["event"],
            )
        return run

    def stop(reason: str) -> Dict[str, Any]:
        return finish({
            "trigger": trigger, "dry_run": dry_run, "halted": True, "halt_reason": reason,
            "opened": [], "skipped": [], "considered": [], "limits": limits, "balance": balance,
        })

    # --- account-level gates, checked before any market data is fetched -----
    if not config["enabled"]:
        return stop("Agent is switched off.")
    if base.KILL_SWITCH["active"]:
        return stop(base.KILL_SWITCH["reason"] or "Kill switch is active.")
    if limits["daily_breached"]:
        return stop(f"Daily loss limit reached ({limits['daily_loss_pct']}% of {limits['daily_limit']}%).")
    if limits["weekly_breached"]:
        return stop(f"Weekly loss limit reached ({limits['weekly_loss_pct']}% of {limits['weekly_limit']}%).")
    if config["respect_window"] and not base.london_window():
        return stop("Outside the London trading window.")

    open_trades = compat.compat_list_trades(user, "open")
    room = config["max_open_trades"] - len(open_trades)
    if room <= 0:
        return stop(f"Already holding {len(open_trades)} of a maximum {config['max_open_trades']} open trades.")

    opened_today = _opened_today(user)
    day_room = config["max_trades_per_day"] - opened_today
    if day_room <= 0:
        return stop(f"Already opened {opened_today} of a maximum {config['max_trades_per_day']} trades today.")

    room = min(room, day_room)
    pairs = config["pairs"] or list(base.WATCHLIST)
    overrides = {"strategies": config["strategies"]} if config["strategies"] else None
    freshness = quote_freshness()

    for pair in pairs:
        if room <= 0:
            skipped.append({"pair": pair, "reason": "Position limit reached earlier in this run."})
            continue
        try:
            # Passing the live quote makes the entry the price we could have
            # actually traded at - ask for a buy, bid for a sell - instead of
            # the last completed hourly candle's mid close.
            candidates = base.score_candidates(
                pair, balance, config["fixed_units"], None, overrides,
                quote=(freshness.get(pair) or {}).get("quote"),
            )
        except Exception as exc:
            skipped.append({"pair": pair, "reason": f"Scan failed: {exc}"})
            continue

        best = candidates[0] if candidates else None
        if best is None:
            skipped.append({"pair": pair, "reason": "No strategy returned a view."})
            continue

        considered.append({
            "pair": pair, "strategy": best.get("strategy"), "status": best.get("status"),
            "direction": best.get("direction"), "confidence": best.get("confidence"),
            "reason": best.get("rejection_reason"),
        })

        # Never trade on invented prices. snapshot() substitutes synthetic
        # values when the OANDA call fails, and they are far enough from the
        # real market to produce nonsense entries as well as nonsense exits.
        if "synthetic" in str(best.get("source", "")).lower():
            skipped.append({"pair": pair, "reason": "Market data unavailable - refusing to trade on fallback prices."})
            continue

        # A stale quote means the market is closed. Without this the agent
        # would happily trade Friday's closing price all weekend.
        #
        # This gate fails CLOSED. It used to skip itself whenever the age
        # couldn't be worked out, which is backwards: not knowing how old a
        # price is, is not a reason to trust it. That mattered little while the
        # London window was on, because the window kept the agent away from the
        # weekend anyway. With the window off this is the only thing left.
        fresh = freshness.get(pair) or {}
        if not fresh.get("tradeable", True):
            status = fresh.get("market_status") or "not tradeable"
            skipped.append({"pair": pair, "reason": f"{pair} is closed for trading right now ({status})."})
            continue
        if not fresh.get("age_known"):
            skipped.append({"pair": pair, "reason": f"Could not tell how old the {pair} price is - not trading on it."})
            continue
        age = fresh.get("age_minutes")
        if age > MAX_QUOTE_AGE_MINUTES:
            skipped.append({"pair": pair, "reason": f"Market looks closed - last {pair} quote is {age:.0f} min old."})
            continue

        if best.get("status") != "trade_candidate":
            skipped.append({"pair": pair, "reason": best.get("rejection_reason") or "No setup."})
            continue
        if int(best.get("confidence") or 0) < config["min_confidence"]:
            skipped.append({"pair": pair, "reason": f"Confidence {best.get('confidence')}% below the agent's {config['min_confidence']}% floor."})
            continue
        if quick._duplicate_open_trade(user, pair, str(best.get("direction"))):
            skipped.append({"pair": pair, "reason": f"Already holding an open {str(best.get('direction')).upper()} on {pair}."})
            continue

        if dry_run:
            opened.append({"pair": pair, "strategy": best.get("strategy"), "direction": best.get("direction"),
                           "confidence": best.get("confidence"), "dry_run": True})
            room -= 1
            continue

        candidate = dict(best)
        candidate["trade_origin"] = "agent_auto"
        candidate["opened_by"] = f"agent:{trigger}"
        try:
            saved = compat.compat_save_trade(user, candidate)
        except Exception as exc:
            skipped.append({"pair": pair, "reason": f"Could not save the trade: {exc}"})
            continue

        opened.append({
            "trade_id": saved.get("id"), "pair": pair, "strategy": best.get("strategy"),
            "direction": best.get("direction"), "confidence": best.get("confidence"),
            "entry": saved.get("entry_price"), "stop_loss": saved.get("stop_loss"),
            "take_profit": saved.get("take_profit"), "risk_amount": saved.get("risk_amount"),
        })
        room -= 1
        try:
            compat.compat_add_audit(
                user, "agent_auto_open", "executed",
                f"Agent opened a {str(best.get('direction')).upper()} on {pair} "
                f"({best.get('setup_label')}, {best.get('confidence')}% confidence).",
                pair, saved.get("id"),
            )
        except Exception:
            pass

    return finish({
        "trigger": trigger, "dry_run": dry_run, "halted": False, "halt_reason": None,
        "opened": opened, "skipped": skipped, "considered": considered,
        "limits": limits, "balance": balance,
        "pairs_scanned": len(pairs), "opened_count": len(opened),
    })


def run_health(user: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """Whether the agent has run recently enough to be believed.

    A scheduled job that has silently stopped looks exactly like a quiet
    market from the outside, so the gap since the last run is worth surfacing
    rather than leaving you to infer it.
    """
    runs = list_runs(user, 1)
    last = runs[0] if runs else None
    last_at = last.get("created_at") if last else None
    hours = None
    if last_at:
        try:
            when = datetime.fromisoformat(str(last_at).replace("Z", "+00:00"))
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            hours = round((datetime.now(timezone.utc) - when).total_seconds() / 3600.0, 1)
        except Exception:
            hours = None
    # Only meaningful while the agent is supposed to be running.
    stale = bool(config.get("enabled")) and (last_at is None or (hours is not None and hours > STALE_RUN_HOURS))
    return {
        "last_run_at": last_at,
        "hours_since_last_run": hours,
        "stale": stale,
        "stale_after_hours": STALE_RUN_HOURS,
        "message": (
            "The agent is switched on but has not run recently - check the scheduler."
            if stale else None
        ),
    }


@app.post("/api/agent/agent-test-alert")
async def send_test_alert(user: str = Depends(base.current_user)):
    """Prove the webhook works before relying on it."""
    config = get_agent_config(user)
    result = notifier.send(
        "FX Co-Pilot test alert",
        "If you can read this, the agent can reach you.",
        config, "test",
    )
    return {"result": result, "configured": bool(notifier.webhook_url(config))}


@app.get("/api/agent/agent-config")
async def read_agent_config(user: str = Depends(base.current_user)):
    config = get_agent_config(user)
    balance = _account_balance(user)
    return {
        "config": config,
        "health": run_health(user, config),
        "alerts_configured": bool(notifier.webhook_url(config)),
        "available_strategies": [
            {"id": "trend_continuation", "label": "Trend continuation"},
            {"id": "mean_reversion", "label": "Mean reversion"},
        ],
        "watchlist": base.WATCHLIST,
        "limits": loss_limit_state(user, balance),
        "open_trades": len(compat.compat_list_trades(user, "open")),
        "opened_today": _opened_today(user),
        "in_window": base.london_window(),
        "kill_switch": base.KILL_SWITCH["active"],
        "storage_mode": compat.compat_storage_mode(),
    }


@app.post("/api/agent/agent-config")
async def write_agent_config(req: AgentConfigRequest, user: str = Depends(base.current_user)):
    config = save_agent_config(user, req.model_dump(exclude_unset=True))
    try:
        compat.compat_add_audit(
            user, "agent_config", "updated",
            f"Agent {'enabled' if config['enabled'] else 'disabled'}; "
            f"max {config['max_open_trades']} open, {config['max_trades_per_day']}/day.",
            "", None,
        )
    except Exception:
        pass
    return {"config": config, "saved": True}


@app.get("/api/agent/agent-runs")
async def read_agent_runs(limit: int = Query(20, ge=1, le=100), user: str = Depends(base.current_user)):
    runs = list_runs(user, limit)
    last = runs[0] if runs else None
    return {
        "runs": runs,
        "last_run_at": last.get("created_at") if last else None,
        "last_opened_count": last.get("opened_count", 0) if last else 0,
        "enabled": get_agent_config(user)["enabled"],
    }


@app.post("/api/agent/agent-run")
async def trigger_agent_run(req: AgentRunRequest, user: str = Depends(base.current_user)):
    """Run the agent now, from the UI. Useful for testing without waiting."""
    return run_agent_once(user, trigger="manual", dry_run=bool(req.dry_run))


@app.get("/api/agent/cron/scan-open")
async def cron_scan_and_open(request: Request):
    auth = autoclose._verify_cron_request(request)
    users = autoclose._open_trade_users() or sorted(getattr(base, "USERS", {}) or {})
    runs: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []

    for user in users:
        try:
            runs.append(run_agent_once(user, trigger="cron"))
        except Exception as exc:
            errors.append({"user": user, "error": str(exc)})

    return {
        "ok": not errors,
        "cron": True,
        "auth": auth,
        "checked_users": users,
        "opened_count": sum(len(r.get("opened", [])) for r in runs),
        "runs": runs,
        "errors": errors,
        "generated_at": base.now(),
    }
