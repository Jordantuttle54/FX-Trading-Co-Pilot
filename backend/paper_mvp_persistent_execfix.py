from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from .paper_mvp_persistent import (
    app,
    KILL_SWITCH,
    START_BALANCE,
    current_user,
    score_candidate,
    save_trade,
    add_audit,
    storage_mode,
)


class AgentExecuteRequestFixed(BaseModel):
    pair: str
    account_balance: float = START_BALANCE
    candidate: Optional[Dict[str, Any]] = Field(default=None)


def _remove_existing_execute_route() -> None:
    """Remove the original execute route so this safer one handles the request."""
    kept = []
    for route in app.router.routes:
        methods = getattr(route, "methods", set()) or set()
        if getattr(route, "path", None) == "/api/agent/execute" and "POST" in methods:
            continue
        kept.append(route)
    app.router.routes = kept


def _candidate_from_request(req: AgentExecuteRequestFixed) -> Dict[str, Any]:
    if req.candidate and req.candidate.get("pair") == req.pair:
        candidate = dict(req.candidate)
    else:
        candidate = score_candidate(req.pair, req.account_balance)

    if candidate.get("status") != "trade_candidate":
        reason = candidate.get("rejection_reason") or candidate.get("entry_reason") or "The latest scan no longer marks this as a trade candidate."
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Paper trade blocked by current setup rules.",
                "pair": req.pair,
                "status": candidate.get("status"),
                "reason": reason,
                "candidate": candidate,
            },
        )

    required = ["pair", "direction", "entry_price", "stop_loss", "take_profit"]
    missing = [k for k in required if candidate.get(k) in (None, "")]
    if missing:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Paper trade candidate is missing required price fields.",
                "missing": missing,
                "candidate": candidate,
            },
        )

    if str(candidate.get("direction", "")).lower() not in ("buy", "sell"):
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Paper trade candidate does not have a valid buy/sell direction.",
                "candidate": candidate,
            },
        )

    return candidate


def _trade_payload_from_candidate(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """Convert scanner candidate fields into an actually-open paper trade.

    Scanner rows use status=trade_candidate. If that value is saved directly, the
    open-trades panel and management engine cannot see it. Preserve the scanner
    status separately and force the paper-trade lifecycle status to open.
    """
    payload = dict(candidate)
    payload["candidate_status"] = candidate.get("status")
    payload["status"] = "open"
    return payload


_remove_existing_execute_route()


@app.post("/api/agent/execute")
async def agent_execute_fixed(req: AgentExecuteRequestFixed, user: str = Depends(current_user)):
    if KILL_SWITCH["active"]:
        raise HTTPException(status_code=403, detail=KILL_SWITCH["reason"] or "Kill switch active")

    try:
        candidate = _candidate_from_request(req)
        trade = save_trade(user, _trade_payload_from_candidate(candidate))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Paper trade could not be saved to storage.",
                "error": str(exc),
                "storage_mode": storage_mode(),
            },
        ) from exc

    audit_warning = None
    try:
        add_audit(user, "paper_execute", "opened", "Paper trade opened. No real order was sent.", req.pair, str(trade["id"]))
    except Exception as exc:
        audit_warning = f"Trade saved, but audit log failed: {exc}"

    return {
        "trade_id": trade["id"],
        "execution": {
            "mode": "paper",
            "status": "filled",
            "order_id": trade.get("order_id"),
            "live_money": False,
        },
        "candidate": candidate,
        "trade": trade,
        "storage_mode": storage_mode(),
        "warning": audit_warning,
    }
