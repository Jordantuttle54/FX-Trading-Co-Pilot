from __future__ import annotations

from typing import Any, Dict

from fastapi import Depends, HTTPException

from . import paper_mvp_phase1_controls as phase1

app = phase1.app
base = phase1.base
compat = phase1.compat


def _as_float(value: Any, fallback: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return fallback
        return float(value)
    except Exception:
        return fallback


def _direction(value: Any) -> str:
    return str(value or "").strip().lower()


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
        balance = _as_float(trade.get("account_balance"), getattr(base, "START_BALANCE", 10000))
        risk_pct = _as_float(trade.get("risk_pct"), getattr(base, "RISK_PER_TRADE", 0.5))
        risk_amount = balance * (risk_pct / 100.0)
    return round(risk_amount * result_r, 2)


# Replace the previous manual close route with a safe version that does not assume optional constants exist.
compat._remove_routes("/api/agent/trades/{trade_id}/close", {"POST"})


@app.post("/api/agent/trades/{trade_id}/close")
async def agent_manual_close_trade_phase1_safe(
    trade_id: str,
    req: phase1.ManualCloseRequest,
    user: str = Depends(base.current_user),
):
    trade = compat.compat_get_trade(user, trade_id)
    if str(trade.get("status", "")).lower() != "open":
        raise HTTPException(status_code=409, detail="Trade is not open")

    close_price = _as_float(req.close_price, _as_float(trade.get("entry_price", trade.get("entry"))))
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

    compat.compat_update_trade(trade)
    try:
        compat.compat_add_audit(user, "manual_close", "closed", trade["close_reason"], str(trade.get("pair", "")), trade_id)
    except Exception:
        pass

    return {"closed_trade": trade, "storage_mode": compat.compat_storage_mode()}
