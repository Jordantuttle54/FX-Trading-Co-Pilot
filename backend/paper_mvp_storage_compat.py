from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from fastapi import Depends, HTTPException
from psycopg2.extras import Json
from pydantic import BaseModel, Field

from . import paper_mvp_persistent as base
from .paper_mvp_trade_status_fix import app

PAPER_TABLE = "paper_trades_agent"
AUDIT_TABLE = "agent_audit_agent"


class AgentExecuteCompatRequest(BaseModel):
    pair: str
    account_balance: float = base.START_BALANCE
    candidate: Optional[Dict[str, Any]] = Field(default=None)


def _remove_routes(path: str, methods: Optional[set[str]] = None) -> None:
    kept = []
    for route in app.router.routes:
        route_path = getattr(route, "path", None)
        route_methods = getattr(route, "methods", set()) or set()
        if route_path == path and (methods is None or route_methods.intersection(methods)):
            continue
        kept.append(route)
    app.router.routes = kept


def _ensure_tables() -> bool:
    if not base.DATABASE_URL:
        return False
    try:
        with base.db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {PAPER_TABLE} (
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
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {AUDIT_TABLE} (
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
                cur.execute("SELECT to_regclass('public.paper_trades')")
                if cur.fetchone()[0]:
                    cur.execute(
                        f"""
                        WITH legacy AS (
                            SELECT
                                COALESCE(NULLIF(payload->>'id',''), id::text) AS legacy_id,
                                user_name,
                                CASE
                                    WHEN COALESCE(status, payload->>'status', 'open') = 'trade_candidate' THEN 'open'
                                    ELSE COALESCE(status, payload->>'status', 'open')
                                END AS compat_status,
                                COALESCE(pair, payload->>'pair') AS compat_pair,
                                COALESCE(created_at, payload->>'created_at') AS compat_created_at,
                                COALESCE(updated_at, payload->>'updated_at', created_at, payload->>'created_at') AS compat_updated_at,
                                jsonb_set(
                                    COALESCE(payload, '{{}}'::jsonb),
                                    '{{status}}',
                                    to_jsonb(CASE
                                        WHEN COALESCE(status, payload->>'status', 'open') = 'trade_candidate' THEN 'open'
                                        ELSE COALESCE(status, payload->>'status', 'open')
                                    END),
                                    true
                                ) AS compat_payload
                            FROM paper_trades
                            WHERE payload IS NOT NULL
                        )
                        INSERT INTO {PAPER_TABLE} (id,user_name,status,pair,created_at,updated_at,payload)
                        SELECT legacy_id,user_name,compat_status,compat_pair,compat_created_at,compat_updated_at,compat_payload
                        FROM legacy
                        WHERE legacy_id IS NOT NULL AND user_name IS NOT NULL
                        ON CONFLICT (id) DO NOTHING
                        """
                    )
                cur.execute("SELECT to_regclass('public.agent_audit')")
                if cur.fetchone()[0]:
                    cur.execute(
                        f"""
                        WITH legacy AS (
                            SELECT
                                COALESCE(NULLIF(payload->>'id',''), id::text) AS legacy_id,
                                user_name,
                                COALESCE(created_at, payload->>'created_at') AS compat_created_at,
                                COALESCE(event_type, payload->>'event_type') AS compat_event_type,
                                COALESCE(pair, payload->>'pair') AS compat_pair,
                                COALESCE(trade_id, payload->>'trade_id') AS compat_trade_id,
                                COALESCE(decision, payload->>'decision') AS compat_decision,
                                COALESCE(reason, payload->>'reason') AS compat_reason,
                                COALESCE(payload, '{{}}'::jsonb) AS compat_payload
                            FROM agent_audit
                            WHERE payload IS NOT NULL
                        )
                        INSERT INTO {AUDIT_TABLE} (id,user_name,created_at,event_type,pair,trade_id,decision,reason,payload)
                        SELECT legacy_id,user_name,compat_created_at,compat_event_type,compat_pair,compat_trade_id,compat_decision,compat_reason,compat_payload
                        FROM legacy
                        WHERE legacy_id IS NOT NULL AND user_name IS NOT NULL
                        ON CONFLICT (id) DO NOTHING
                        """
                    )
        base._DB_OK = True
        return True
    except Exception:
        base._DB_OK = False
        return False


def compat_storage_mode() -> str:
    return "postgres" if _ensure_tables() else "memory"


def normalise_payload(value: Any) -> Dict[str, Any]:
    return base.normalise_payload(value)


def compat_upsert_trade(item: Dict[str, Any]) -> None:
    if not _ensure_tables():
        for i, old in enumerate(base.TRADES):
            if str(old.get("id")) == str(item.get("id")):
                base.TRADES[i] = item
                return
        base.TRADES.append(item)
        return
    trade_id = str(item["id"])
    payload = dict(item)
    payload["id"] = trade_id
    payload["status"] = item.get("status", "open")
    with base.db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {PAPER_TABLE} (id,user_name,status,pair,created_at,updated_at,payload)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (id) DO UPDATE SET
                    status=EXCLUDED.status,
                    pair=EXCLUDED.pair,
                    updated_at=EXCLUDED.updated_at,
                    payload=EXCLUDED.payload
                """,
                (
                    trade_id,
                    payload.get("user_name"),
                    payload.get("status", "open"),
                    payload.get("pair"),
                    payload.get("created_at"),
                    payload.get("updated_at", base.now()),
                    Json(payload),
                ),
            )


def compat_list_trades(user: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
    if not _ensure_tables():
        rows = [t for t in base.TRADES if t.get("user_name") == user]
    else:
        with base.db_conn() as conn:
            with conn.cursor() as cur:
                if status:
                    cur.execute(
                        f"SELECT payload FROM {PAPER_TABLE} WHERE user_name=%s AND status=%s ORDER BY created_at DESC",
                        (user, status),
                    )
                else:
                    cur.execute(f"SELECT payload FROM {PAPER_TABLE} WHERE user_name=%s ORDER BY created_at DESC", (user,))
                rows = [normalise_payload(r[0]) for r in cur.fetchall()]
    normalised = []
    for row in rows:
        item = dict(row)
        if str(item.get("status", "")).lower() == "trade_candidate":
            item["candidate_status"] = "trade_candidate"
            item["status"] = "open"
        if status is None or str(item.get("status", "")).lower() == status.lower():
            normalised.append(item)
    return sorted(normalised, key=lambda x: x.get("created_at", ""), reverse=True)


def compat_get_trade(user: str, trade_id: str) -> Dict[str, Any]:
    if not _ensure_tables():
        for t in base.TRADES:
            if str(t.get("id")) == str(trade_id) and t.get("user_name") == user:
                return t
    else:
        with base.db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT payload FROM {PAPER_TABLE} WHERE user_name=%s AND id=%s", (user, str(trade_id)))
                row = cur.fetchone()
                if row:
                    item = normalise_payload(row[0])
                    if str(item.get("status", "")).lower() == "trade_candidate":
                        item["candidate_status"] = "trade_candidate"
                        item["status"] = "open"
                    return item
    raise HTTPException(status_code=404, detail="Trade not found")


def compat_update_trade(item: Dict[str, Any]) -> None:
    item["updated_at"] = base.now()
    compat_upsert_trade(item)


def compat_save_trade(user: str, candidate: Dict[str, Any]) -> Dict[str, Any]:
    trade_id = str(uuid.uuid4())
    payload = dict(candidate)
    original_status = payload.get("status")
    if original_status:
        payload["candidate_status"] = original_status
    payload["status"] = "open"
    item = {
        **payload,
        "id": trade_id,
        "user_name": user,
        "created_at": base.now(),
        "updated_at": base.now(),
        "status": "open",
        "broker_mode": "paper",
        "order_id": f"PAPER-{trade_id[:8]}",
    }
    item["entry_price"] = item.get("entry_price", item.get("entry"))
    item["entry"] = item["entry_price"]
    item["take_profit"] = item.get("take_profit", item.get("target"))
    item["target"] = item["take_profit"]
    item["filled_at"] = item["created_at"]
    compat_upsert_trade(item)
    return item


def compat_add_audit(user: str, event_type: str, decision: str, reason: str = "", pair: str = "", trade_id: str | None = None):
    item = {
        "id": str(uuid.uuid4()),
        "created_at": base.now(),
        "user_name": user,
        "event_type": event_type,
        "pair": pair,
        "trade_id": trade_id,
        "decision": decision,
        "reason": reason,
    }
    if not _ensure_tables():
        base.AUDIT.insert(0, item)
        return
    with base.db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {AUDIT_TABLE} (id,user_name,created_at,event_type,pair,trade_id,decision,reason,payload)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (id) DO NOTHING
                """,
                (item["id"], user, item["created_at"], event_type, pair, trade_id, decision, reason, Json(item)),
            )


def compat_list_audit(user: str) -> List[Dict[str, Any]]:
    if not _ensure_tables():
        return [a for a in base.AUDIT if a.get("user_name") == user][:200]
    with base.db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT payload FROM {AUDIT_TABLE} WHERE user_name=%s ORDER BY created_at DESC LIMIT 200", (user,))
            return [normalise_payload(r[0]) for r in cur.fetchall()]


# Monkeypatch the base module so existing management/review functions use the safe table.
_ensure_tables()
base.db_upsert_trade = compat_upsert_trade
base.list_trades = compat_list_trades
base.get_trade = compat_get_trade
base.update_trade = compat_update_trade
base.save_trade = compat_save_trade
base.add_audit = compat_add_audit
base.list_audit = compat_list_audit
base.storage_mode = compat_storage_mode


def _candidate_from_request(req: AgentExecuteCompatRequest) -> Dict[str, Any]:
    candidate = dict(req.candidate) if req.candidate and req.candidate.get("pair") == req.pair else base.score_candidate(req.pair, req.account_balance)
    if candidate.get("status") != "trade_candidate":
        raise HTTPException(status_code=422, detail={"message": "Paper trade blocked by current setup rules.", "candidate": candidate})
    return candidate


def _paper_stats(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    closed = [r for r in rows if str(r.get("status", "")).lower() == "closed"]
    vals = [float(r.get("result_r") or 0) for r in closed]
    wins = [v for v in vals if v > 0]
    total = sum(vals)
    return {
        "trades": len(rows),
        "open": len([r for r in rows if str(r.get("status", "")).lower() == "open"]),
        "closed": len(closed),
        "win_rate_pct": round((len(wins) / len(closed) * 100) if closed else 0, 1),
        "total_r": round(total, 2),
        "avg_r": round((total / len(closed)) if closed else 0, 2),
        "estimated_pnl": round(sum(float(r.get("result_money") or 0) for r in closed), 2),
    }


for path, methods in [
    ("/api/agent/execute", {"POST"}),
    ("/api/agent/trades/open", {"GET"}),
    ("/api/agent/trades", {"GET"}),
    ("/api/agent/trades/closed", {"GET"}),
    ("/api/agent/manage", {"POST"}),
    ("/api/agent/audit", {"GET"}),
    ("/api/paper/stats", {"GET"}),
    ("/api/paper-trades", {"GET", "POST"}),
]:
    _remove_routes(path, methods)


@app.post("/api/agent/execute")
async def agent_execute_storage_compat(req: AgentExecuteCompatRequest, user: str = Depends(base.current_user)):
    if base.KILL_SWITCH["active"]:
        raise HTTPException(status_code=403, detail=base.KILL_SWITCH["reason"] or "Kill switch active")
    candidate = _candidate_from_request(req)
    trade = compat_save_trade(user, candidate)
    try:
        compat_add_audit(user, "paper_execute", "opened", "Paper trade opened. No real order was sent.", req.pair, str(trade["id"]))
    except Exception:
        pass
    return {"trade_id": trade["id"], "execution": {"mode": "paper", "status": "filled", "order_id": trade.get("order_id"), "live_money": False}, "candidate": candidate, "trade": trade, "storage_mode": compat_storage_mode()}


@app.get("/api/agent/trades/open")
async def agent_open_trades_storage_compat(user: str = Depends(base.current_user)):
    return {"open_trades": compat_list_trades(user, "open"), "trading_allowed": {"allowed": not base.KILL_SWITCH["active"], "daily_loss_pct": 0.0, "weekly_loss_pct": 0.0, "daily_limit": base.DAILY_LIMIT, "weekly_limit": base.WEEKLY_LIMIT}, "kill_switch": base.KILL_SWITCH["active"], "storage_mode": compat_storage_mode()}


@app.get("/api/agent/trades")
async def agent_all_trades_storage_compat(user: str = Depends(base.current_user)):
    return compat_list_trades(user)


@app.get("/api/agent/trades/closed")
async def agent_closed_trades_storage_compat(user: str = Depends(base.current_user)):
    return compat_list_trades(user, "closed")


@app.post("/api/agent/manage")
async def agent_manage_storage_compat(req: base.ManageTradesRequest, user: str = Depends(base.current_user)):
    actions = base.manage_trades(user, req.current_prices or None)
    return {"actions_taken": actions, "open_trades": compat_list_trades(user, "open"), "snapshot": base.snapshot(), "storage_mode": compat_storage_mode()}


@app.get("/api/agent/audit")
async def agent_audit_storage_compat(user: str = Depends(base.current_user)):
    return compat_list_audit(user)


@app.get("/api/paper/stats")
async def paper_stats_storage_compat(user: str = Depends(base.current_user)):
    rows = compat_list_trades(user)
    return _paper_stats(rows)


@app.get("/api/paper-trades")
async def legacy_paper_trades_storage_compat(user: str = Depends(base.current_user)):
    rows = compat_list_trades(user)
    return {"rows": rows, "stats": _paper_stats(rows), "storage_mode": compat_storage_mode()}
