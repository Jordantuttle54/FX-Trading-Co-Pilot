from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from . import paper_mvp_persistent as base
from .paper_mvp_persistent_execfix import app
from .paper_mvp_persistent import (
    START_BALANCE,
    current_user,
    save_trade,
    list_trades,
    storage_mode,
    now,
)


class LegacyJournalEntryIn(BaseModel):
    date: str
    pair: str
    direction: str
    result_r: float
    reason: str = ""
    lesson: str = ""


class LegacyPaperTradeIn(BaseModel):
    pair: str
    direction: str
    entry: float
    stop_loss: float
    target: float
    risk_pct: float = 0.5
    risk_amount: float = 0.0
    position_units: float = 0.0
    notes: str = ""


class AutomationReadinessLegacyIn(BaseModel):
    backtested_trades: int = 0
    forward_trades: int = 0
    avg_r: float = 0
    max_drawdown_pct: float = 100
    max_daily_loss_pct: float = 100
    win_rate_pct: float = 0


def _run_schema_migrations() -> None:
    """Make existing Postgres tables match the current paper-trading code.

    Early MVP deployments created paper_trades without updated_at. CREATE TABLE IF NOT
    EXISTS does not add missing columns, so paper execution failed after the first
    persistent-storage rollout. These ALTER statements are safe to rerun.
    """
    if not base.DATABASE_URL:
        return
    try:
        with base.db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS paper_trades (
                        id TEXT PRIMARY KEY,
                        user_name TEXT NOT NULL,
                        status TEXT NOT NULL,
                        pair TEXT,
                        created_at TEXT,
                        updated_at TEXT,
                        payload JSONB NOT NULL
                    )
                    """
                )
                cur.execute("ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS user_name TEXT")
                cur.execute("ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS status TEXT")
                cur.execute("ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS pair TEXT")
                cur.execute("ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS created_at TEXT")
                cur.execute("ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS updated_at TEXT")
                cur.execute("ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS payload JSONB")
                cur.execute("UPDATE paper_trades SET updated_at = COALESCE(updated_at, created_at)")
                cur.execute("UPDATE paper_trades SET status = COALESCE(status, payload->>'status', 'open')")
                cur.execute("UPDATE paper_trades SET pair = COALESCE(pair, payload->>'pair')")

                cur.execute(
                    """
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
                    """
                )
                cur.execute("ALTER TABLE agent_audit ADD COLUMN IF NOT EXISTS user_name TEXT")
                cur.execute("ALTER TABLE agent_audit ADD COLUMN IF NOT EXISTS created_at TEXT")
                cur.execute("ALTER TABLE agent_audit ADD COLUMN IF NOT EXISTS event_type TEXT")
                cur.execute("ALTER TABLE agent_audit ADD COLUMN IF NOT EXISTS pair TEXT")
                cur.execute("ALTER TABLE agent_audit ADD COLUMN IF NOT EXISTS trade_id TEXT")
                cur.execute("ALTER TABLE agent_audit ADD COLUMN IF NOT EXISTS decision TEXT")
                cur.execute("ALTER TABLE agent_audit ADD COLUMN IF NOT EXISTS reason TEXT")
                cur.execute("ALTER TABLE agent_audit ADD COLUMN IF NOT EXISTS payload JSONB")
        base._DB_OK = True
    except Exception:
        base._DB_OK = False


_run_schema_migrations()


def _remove_routes(path: str, methods: Optional[set[str]] = None) -> None:
    kept = []
    for route in app.router.routes:
        route_path = getattr(route, "path", None)
        route_methods = getattr(route, "methods", set()) or set()
        if route_path == path and (methods is None or route_methods.intersection(methods)):
            continue
        kept.append(route)
    app.router.routes = kept


def _journal_rows(user: str) -> List[Dict[str, Any]]:
    return [j for j in base.JOURNAL if j.get("user_name") == user]


def _journal_stats(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    vals = [float(r.get("result_r") or 0) for r in rows]
    wins = [v for v in vals if v > 0]
    total = sum(vals)
    return {
        "trades": len(rows),
        "win_rate_pct": round((len(wins) / len(rows) * 100) if rows else 0, 1),
        "total_r": round(total, 2),
        "avg_r": round((total / len(rows)) if rows else 0, 2),
    }


def _trade_rows(user: str) -> List[Dict[str, Any]]:
    rows = []
    for t in list_trades(user):
        rows.append(
            {
                "id": t.get("id"),
                "status": str(t.get("status", "open")).upper(),
                "pair": t.get("pair"),
                "direction": t.get("direction"),
                "entry": t.get("entry", t.get("entry_price")),
                "entry_price": t.get("entry_price", t.get("entry")),
                "stop_loss": t.get("stop_loss"),
                "target": t.get("target", t.get("take_profit")),
                "take_profit": t.get("take_profit", t.get("target")),
                "risk_pct": t.get("risk_pct", 0.5),
                "risk_amount": t.get("risk_amount", 0),
                "position_units": t.get("position_units", 0),
                "result_r": t.get("result_r"),
                "result_money": t.get("result_money"),
                "created_at": t.get("created_at"),
                "notes": t.get("notes", ""),
            }
        )
    return rows


def _paper_stats(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    closed = [r for r in rows if r.get("status") == "CLOSED"]
    open_rows = [r for r in rows if r.get("status") == "OPEN"]
    vals = [float(r.get("result_r") or 0) for r in closed]
    wins = [v for v in vals if v > 0]
    total_r = sum(vals)
    return {
        "trades": len(rows),
        "open": len(open_rows),
        "closed": len(closed),
        "win_rate_pct": round((len(wins) / len(closed) * 100) if closed else 0, 1),
        "total_r": round(total_r, 2),
        "avg_r": round((total_r / len(closed)) if closed else 0, 2),
        "estimated_pnl": round(sum(float(r.get("result_money") or 0) for r in closed), 2),
    }


# Replace old journal routes with the response shape expected by the embedded Co-Pilot page.
_remove_routes("/api/journal", {"GET", "POST", "DELETE"})
_remove_routes("/api/paper-trades", {"GET", "POST", "DELETE"})
_remove_routes("/api/automation-readiness", {"POST"})


@app.get("/api/journal")
async def legacy_journal_list(user: str = Depends(current_user)):
    rows = _journal_rows(user)
    return {"rows": rows, "stats": _journal_stats(rows)}


@app.post("/api/journal")
async def legacy_journal_add(entry: LegacyJournalEntryIn, user: str = Depends(current_user)):
    item = {"id": f"J-{len(base.JOURNAL) + 1}", "created_at": now(), "user_name": user, **entry.dict()}
    base.JOURNAL.append(item)
    rows = _journal_rows(user)
    return {"row": item, "rows": rows, "stats": _journal_stats(rows)}


@app.delete("/api/journal")
async def legacy_journal_clear(user: str = Depends(current_user)):
    base.JOURNAL[:] = [j for j in base.JOURNAL if j.get("user_name") != user]
    return {"cleared": True, "rows": [], "stats": _journal_stats([])}


@app.get("/api/paper-trades")
async def legacy_paper_trades(user: str = Depends(current_user)):
    rows = _trade_rows(user)
    return {"rows": rows, "stats": _paper_stats(rows), "storage_mode": storage_mode()}


@app.post("/api/paper-trades")
async def legacy_paper_trade_add(req: LegacyPaperTradeIn, user: str = Depends(current_user)):
    target = req.target
    trade = save_trade(
        user,
        {
            "pair": req.pair,
            "direction": req.direction.lower(),
            "setup_type": "manual_copilot_paper_trade",
            "setup_label": "Manual Co-Pilot paper trade",
            "confidence": 0,
            "rr_estimate": 0,
            "entry": req.entry,
            "entry_price": req.entry,
            "stop_loss": req.stop_loss,
            "target": target,
            "take_profit": target,
            "risk_pct": req.risk_pct,
            "risk_amount": req.risk_amount,
            "position_units": req.position_units,
            "account_balance": START_BALANCE,
            "entry_reason": req.notes or "Manual paper trade opened from Co-Pilot page.",
            "notes": req.notes,
            "source": "manual-copilot",
        },
    )
    rows = _trade_rows(user)
    return {"row": trade, "rows": rows, "stats": _paper_stats(rows), "storage_mode": storage_mode()}


@app.post("/api/automation-readiness")
async def legacy_automation_readiness(req: AutomationReadinessLegacyIn, user: str = Depends(current_user)):
    gates = [
        {"name": "At least 200 backtested trades", "pass": req.backtested_trades >= 200},
        {"name": "At least 50 forward paper trades", "pass": req.forward_trades >= 50},
        {"name": "Positive average R", "pass": req.avg_r > 0},
        {"name": "Max drawdown below 8%", "pass": req.max_drawdown_pct <= 8},
        {"name": "Daily loss below limit", "pass": req.max_daily_loss_pct <= 1.5},
        {"name": "Win rate is not relied on alone", "pass": True},
    ]
    passed = sum(1 for g in gates if g["pass"])
    ready = passed == len(gates)
    return {
        "ready_for_demo_automation": ready,
        "live_trading_locked": True,
        "passed": passed,
        "total": len(gates),
        "gates": gates,
        "message": "Demo automation readiness check complete. Live trading remains locked.",
    }
