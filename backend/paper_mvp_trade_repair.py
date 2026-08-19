"""Repairs paper trades whose recorded result came from the wrong fill price.

Both automatic exit paths (the auto-close checker and manage_trades) used to
close a trade at whatever the market price happened to be when the check ran,
rather than at the stop-loss/take-profit level that was actually breached.
Because those checks are periodic, price could be well past the trigger by the
time a breach was noticed, so the recorded result_r/result_money could be many
times larger than the trade ever risked. XAU/USD was worst affected - its stop
distance is small in absolute dollar terms next to how far gold moves.

The code paths are fixed; this module repairs the rows they already wrote.
Recomputing is safe because every input needed is stored on the trade itself
(entry, stop, target, risk_amount), so the corrected result is derived from
the trade's own terms rather than from any live market data.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from fastapi import Depends
from pydantic import BaseModel

from . import paper_mvp_persistent as base
from . import paper_mvp_storage_compat as compat
from . import strategy_calibration as chain

app = chain.app

# close_reason values written by the two automatic exit paths, mapped to the
# field holding the price the trade should have filled at. Manual and quick
# closes are deliberately absent - those genuinely did fill at market, so their
# recorded result is correct and must be left alone.
TRIGGER_CLOSE_REASONS: Dict[str, str] = {
    "stop_loss_hit": "stop_loss",
    "stop": "stop_loss",
    "take_profit_hit": "take_profit",
    "target": "take_profit",
}

# Differences smaller than these are rounding noise rather than the bug, and
# repairing them would churn rows without changing what the user sees.
MATERIAL_R_DELTA = 0.005
MATERIAL_MONEY_DELTA = 0.01


class TradeRepairRequest(BaseModel):
    apply: bool = False


def _as_float(value: Any, fallback: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return fallback
        return float(value)
    except Exception:
        return fallback


def _trigger_price(trade: Dict[str, Any]) -> Optional[float]:
    """The price this trade should have filled at, or None if not trigger-closed."""
    field = TRIGGER_CLOSE_REASONS.get(str(trade.get("close_reason") or "").strip().lower())
    if not field:
        return None
    if field == "stop_loss":
        level = _as_float(trade.get("stop_loss"))
    else:
        level = _as_float(trade.get("take_profit", trade.get("target")))
    return level or None


def _recompute(trade: Dict[str, Any], close_price: float) -> Optional[Tuple[float, float]]:
    entry = _as_float(trade.get("entry_price", trade.get("entry")))
    stop = _as_float(trade.get("stop_loss"))
    risk_per_unit = abs(entry - stop)
    if risk_per_unit <= 0:
        return None

    direction = str(trade.get("direction") or "").strip().lower()
    if direction == "buy":
        result_r = (close_price - entry) / risk_per_unit
    elif direction == "sell":
        result_r = (entry - close_price) / risk_per_unit
    else:
        return None
    result_r = round(result_r, 4)

    risk_amount = _as_float(trade.get("risk_amount"))
    if risk_amount <= 0:
        balance = _as_float(trade.get("account_balance"), getattr(base, "START_BALANCE", 10000.0))
        risk_pct = _as_float(trade.get("risk_pct"), getattr(base, "MAX_RISK", 0.5))
        risk_amount = balance * (risk_pct / 100.0)
    return result_r, round(risk_amount * result_r, 2)


def analyse_trade(trade: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Returns what this trade's result should be, or None if it needs no repair."""
    if str(trade.get("status") or "").strip().lower() != "closed":
        return None
    trigger = _trigger_price(trade)
    if trigger is None:
        return None
    recomputed = _recompute(trade, trigger)
    if recomputed is None:
        return None

    new_r, new_money = recomputed
    old_r = _as_float(trade.get("result_r"))
    old_money = _as_float(trade.get("result_money"))
    if abs(new_r - old_r) < MATERIAL_R_DELTA and abs(new_money - old_money) < MATERIAL_MONEY_DELTA:
        return None

    return {
        "trade_id": trade.get("id"),
        "pair": trade.get("pair"),
        "direction": trade.get("direction"),
        "setup_label": trade.get("setup_label") or trade.get("setup_type") or "",
        "closed_at": trade.get("closed_at"),
        "close_reason": trade.get("close_reason"),
        "old_close_price": _as_float(trade.get("close_price", trade.get("exit_price"))),
        "new_close_price": trigger,
        "old_result_r": round(old_r, 4),
        "new_result_r": new_r,
        "old_result_money": round(old_money, 2),
        "new_result_money": new_money,
        "money_delta": round(new_money - old_money, 2),
    }


def _apply_repair(trade: Dict[str, Any], repair: Dict[str, Any]) -> None:
    # Keep the first-seen originals so a repaired row stays auditable and the
    # change can be traced back even after several passes.
    history = trade.get("result_repair") or {}
    trade["result_repair"] = {
        "repaired_at": base.now(),
        "reason": "refilled_at_trigger_level",
        "original_close_price": history.get("original_close_price", repair["old_close_price"]),
        "original_result_r": history.get("original_result_r", repair["old_result_r"]),
        "original_result_money": history.get("original_result_money", repair["old_result_money"]),
    }
    trade["close_price"] = repair["new_close_price"]
    trade["exit_price"] = repair["new_close_price"]
    trade["result_r"] = repair["new_result_r"]
    trade["result_money"] = repair["new_result_money"]
    compat.compat_update_trade(trade)


def repair_user_trades(user: str, apply: bool = False) -> Dict[str, Any]:
    trades = compat.compat_list_trades(user, "closed")
    repairs: List[Dict[str, Any]] = []

    for trade in trades:
        repair = analyse_trade(trade)
        if not repair:
            continue
        if apply:
            _apply_repair(trade, repair)
        repairs.append(repair)

    money_delta = round(sum(r["money_delta"] for r in repairs), 2)
    if apply and repairs:
        try:
            compat.compat_add_audit(
                user,
                "trade_repair",
                "repaired",
                f"Refilled {len(repairs)} trigger-closed trade(s) at their stop/target level "
                f"(balance change {money_delta:+.2f}).",
                "",
                None,
            )
        except Exception:
            pass

    return {
        "applied": apply,
        "closed_trades_checked": len(trades),
        "affected_count": len(repairs),
        "money_delta": money_delta,
        "repairs": repairs,
        "storage_mode": compat.compat_storage_mode(),
    }


@app.post("/api/agent/trades/repair-trigger-fills")
async def repair_trigger_fills(req: TradeRepairRequest, user: str = Depends(base.current_user)):
    return repair_user_trades(user, apply=bool(req.apply))
