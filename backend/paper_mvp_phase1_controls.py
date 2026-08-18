from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from . import execution
from . import paper_mvp_storage_compat as compat

app = compat.app
base = compat.base


class AgentExecutePhase1Request(BaseModel):
    pair: str
    account_balance: float = base.START_BALANCE
    candidate: Optional[Dict[str, Any]] = Field(default=None)
    force_duplicate: bool = False


class ManualCloseRequest(BaseModel):
    close_price: Optional[float] = None
    reason: str = "Manual close from dashboard"


class ResetTradesRequest(BaseModel):
    confirm: bool = False
    include_closed: bool = True


def _as_float(value: Any, fallback: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return fallback
        return float(value)
    except Exception:
        return fallback


def _direction(value: Any) -> str:
    return str(value or "").strip().lower()


def _pair(value: Any) -> str:
    return str(value or "").strip().upper()


def _duplicate_open_trade(user: str, pair: str, direction: str) -> Optional[Dict[str, Any]]:
    for trade in compat.compat_list_trades(user, "open"):
        if _pair(trade.get("pair")) == _pair(pair) and _direction(trade.get("direction")) == _direction(direction):
            return trade
    return None


def _calc_result_r(trade: Dict[str, Any], close_price: float) -> float:
    direction = _direction(trade.get("direction"))
    entry = _as_float(trade.get("entry_price", trade.get("entry")))
    stop = _as_float(trade.get("stop_loss"))
    risk_per_unit = abs(entry - stop)
    if risk_per_unit <= 0:
        return 0.0
    if direction == "sell":
        return round((entry - close_price) / risk_per_unit, 4)
    return round((close_price - entry) / risk_per_unit, 4)


def _calc_result_money(trade: Dict[str, Any], result_r: float) -> float:
    risk_amount = _as_float(trade.get("risk_amount"), 0.0)
    if risk_amount <= 0:
        balance = _as_float(trade.get("account_balance"), base.START_BALANCE)
        risk_pct = _as_float(trade.get("risk_pct"), base.RISK_PER_TRADE)
        risk_amount = balance * (risk_pct / 100.0)
    return round(risk_amount * result_r, 2)


# Replace routes that need phase-one behaviour. This also prevents old route order issues returning.
for path, methods in [
    ("/api/agent/status", {"GET"}),
    ("/api/agent/execute", {"POST"}),
    ("/api/agent/trades/open", {"GET"}),
    ("/api/agent/trades", {"GET"}),
    ("/api/agent/trades/closed", {"GET"}),
    ("/api/agent/trades/{trade_id}", {"GET"}),
    ("/api/agent/manage", {"POST"}),
]:
    compat._remove_routes(path, methods)


@app.get("/api/agent/status")
async def agent_status_phase1(user: str = Depends(base.current_user)):
    open_trades = compat.compat_list_trades(user, "open")
    return {
        "version": "0.7.5-phase1-paper-controls",
        "user": user,
        "storage_mode": compat.compat_storage_mode(),
        "live_trading_enabled": False,
        "live_trading_locked": True,
        "paper_trading": True,
        "kill_switch_active": base.KILL_SWITCH["active"],
        "kill_switch_reason": base.KILL_SWITCH["reason"],
        "london_window_now": base.london_window(),
        "session": base.session_label(),
        "open_trade_count": len(open_trades),
        "open_trades": open_trades,
        "trading_allowed": {
            "allowed": not base.KILL_SWITCH["active"],
            "reason": base.KILL_SWITCH["reason"] if base.KILL_SWITCH["active"] else None,
            "daily_loss_pct": 0.0,
            "weekly_loss_pct": 0.0,
            "daily_limit": base.DAILY_LIMIT,
            "weekly_limit": base.WEEKLY_LIMIT,
        },
    }


@app.post("/api/agent/execute")
async def agent_execute_phase1(req: AgentExecutePhase1Request, user: str = Depends(base.current_user)):
    if base.KILL_SWITCH["active"]:
        raise HTTPException(status_code=403, detail=base.KILL_SWITCH["reason"] or "Kill switch active")

    candidate = dict(req.candidate) if req.candidate and req.candidate.get("pair") == req.pair else compat._candidate_from_request(req)  # type: ignore[arg-type]
    if candidate.get("status") != "trade_candidate":
        raise HTTPException(status_code=422, detail={"message": "Paper trade blocked by current setup rules.", "candidate": candidate})

    duplicate = _duplicate_open_trade(user, req.pair, str(candidate.get("direction", "")))
    if duplicate and not req.force_duplicate:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Duplicate open paper trade found for this pair and direction.",
                "duplicate_trade_id": duplicate.get("id"),
                "pair": duplicate.get("pair"),
                "direction": duplicate.get("direction"),
                "opened_at": duplicate.get("filled_at") or duplicate.get("created_at"),
            },
        )

    execution_result = execution.place_demo_trade(candidate)
    if execution_result.get("status") != "filled":
        raise HTTPException(
            status_code=502,
            detail={
                "message": f"{execution_result.get('mode', 'broker')} order was not filled.",
                "error": execution_result.get("error"),
                "candidate": candidate,
            },
        )

    candidate = {
        **candidate,
        "entry": execution_result["entry"],
        "entry_price": execution_result["entry"],
        "broker_mode": execution_result["mode"],
        "order_id": execution_result["order_id"],
        "filled_at": execution_result["filled_at"],
        "spread_cost": execution_result.get("spread_cost"),
        "slippage": execution_result.get("slippage"),
        "broker_raw": execution_result.get("broker_raw"),
    }

    trade = compat.compat_save_trade(user, candidate)
    try:
        audit_note = (
            "Paper trade opened. No real order was sent."
            if execution_result["mode"] == execution.MODE_PAPER
            else f"OANDA demo order opened at {execution_result['entry']}. Practice account only, no real money involved."
        )
        compat.compat_add_audit(
            user,
            "paper_execute",
            "opened",
            audit_note,
            req.pair,
            str(trade["id"]),
        )
    except Exception:
        pass

    return {
        "trade_id": trade["id"],
        "execution": {**execution_result, "live_money": False},
        "candidate": candidate,
        "trade": trade,
        "duplicate_warning": bool(duplicate),
        "storage_mode": compat.compat_storage_mode(),
    }


@app.get("/api/agent/trades/open")
async def agent_open_trades_phase1(user: str = Depends(base.current_user)):
    return {
        "open_trades": compat.compat_list_trades(user, "open"),
        "trading_allowed": {
            "allowed": not base.KILL_SWITCH["active"],
            "daily_loss_pct": 0.0,
            "weekly_loss_pct": 0.0,
            "daily_limit": base.DAILY_LIMIT,
            "weekly_limit": base.WEEKLY_LIMIT,
        },
        "kill_switch": base.KILL_SWITCH["active"],
        "storage_mode": compat.compat_storage_mode(),
    }


@app.get("/api/agent/trades")
async def agent_all_trades_phase1(user: str = Depends(base.current_user)):
    return compat.compat_list_trades(user)


@app.get("/api/agent/trades/closed")
async def agent_closed_trades_phase1(user: str = Depends(base.current_user)):
    return compat.compat_list_trades(user, "closed")


@app.get("/api/agent/trades/{trade_id}")
async def agent_get_trade_phase1(trade_id: str, user: str = Depends(base.current_user)):
    return compat.compat_get_trade(user, trade_id)


@app.post("/api/agent/trades/{trade_id}/close")
async def agent_manual_close_trade_phase1(trade_id: str, req: ManualCloseRequest, user: str = Depends(base.current_user)):
    trade = compat.compat_get_trade(user, trade_id)
    if str(trade.get("status", "")).lower() != "open":
        raise HTTPException(status_code=409, detail="Trade is not open")

    close_price = _as_float(req.close_price, _as_float(trade.get("entry_price", trade.get("entry"))))
    broker_close: Optional[Dict[str, Any]] = None

    if trade.get("broker_mode") == execution.MODE_DEMO:
        instrument = _pair(trade.get("pair")).replace("/", "_")
        broker_close = execution.close_position_oanda(instrument)
        if broker_close.get("status") == "closed" and req.close_price is None:
            raw = broker_close.get("raw") or {}
            fill = raw.get("longOrderFillTransaction") or raw.get("shortOrderFillTransaction") or {}
            if fill.get("price"):
                close_price = _as_float(fill.get("price"), close_price)
        # A broker-side error here usually just means OANDA's own stop-loss/take-profit
        # order already closed this position before the manual click landed - the app
        # still records the close locally using the best price it has.

    result_r = _calc_result_r(trade, close_price)
    result_money = _calc_result_money(trade, result_r)

    trade["status"] = "closed"
    trade["closed_at"] = base.now()
    trade["exit_price"] = close_price
    trade["close_price"] = close_price
    trade["close_reason"] = req.reason or "Manual close from dashboard"
    trade["result_r"] = result_r
    trade["result_money"] = result_money
    trade["quality_tag"] = "manual_close"
    if broker_close is not None:
        trade["broker_close"] = broker_close

    compat.compat_update_trade(trade)
    try:
        compat.compat_add_audit(user, "manual_close", "closed", trade["close_reason"], str(trade.get("pair", "")), trade_id)
    except Exception:
        pass

    return {"closed_trade": trade, "storage_mode": compat.compat_storage_mode()}


@app.post("/api/agent/manage")
async def agent_manage_phase1(req: base.ManageTradesRequest, user: str = Depends(base.current_user)):
    actions = base.manage_trades(user, req.current_prices or None)
    return {
        "actions_taken": actions,
        "open_trades": compat.compat_list_trades(user, "open"),
        "snapshot": base.snapshot(),
        "storage_mode": compat.compat_storage_mode(),
    }


@app.post("/api/agent/trades/reset")
async def agent_reset_trades_phase1(req: ResetTradesRequest, user: str = Depends(base.current_user)):
    if not req.confirm:
        raise HTTPException(status_code=400, detail="Reset requires confirm=true")

    rows_before = compat.compat_list_trades(user)
    if compat.compat_storage_mode() == "postgres":
        with base.db_conn() as conn:
            with conn.cursor() as cur:
                if req.include_closed:
                    cur.execute(f"DELETE FROM {compat.PAPER_TABLE} WHERE user_name=%s", (user,))
                else:
                    cur.execute(f"DELETE FROM {compat.PAPER_TABLE} WHERE user_name=%s AND status=%s", (user, "open"))
    else:
        if req.include_closed:
            base.TRADES[:] = [t for t in base.TRADES if t.get("user_name") != user]
        else:
            base.TRADES[:] = [t for t in base.TRADES if not (t.get("user_name") == user and str(t.get("status", "")).lower() == "open")]

    try:
        compat.compat_add_audit(user, "reset_test_data", "reset", f"Reset {len(rows_before)} paper trade row(s).", "", None)
    except Exception:
        pass

    return {
        "reset": True,
        "deleted_count": len(rows_before),
        "remaining_trades": compat.compat_list_trades(user),
        "storage_mode": compat.compat_storage_mode(),
    }
