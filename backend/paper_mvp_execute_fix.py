from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from .paper_mvp_persistent import (
    app,
    current_user,
    KILL_SWITCH,
    score_candidate,
    save_trade,
    add_audit,
    storage_mode,
    now,
    MAX_RISK,
    MIN_RR,
)


# Remove the original /api/agent/execute route from the imported persistent MVP.
# FastAPI matches routes in order, so the older route must be removed before the
# safer replacement is registered below.
app.router.routes = [
    route for route in app.router.routes
    if not (getattr(route, "path", None) == "/api/agent/execute" and "POST" in getattr(route, "methods", set()))
]


class AgentExecuteSafeRequest(BaseModel):
    pair: str
    account_balance: float = 10000
    candidate: Optional[Dict[str, Any]] = Field(default=None)


def _normalise_candidate(req: AgentExecuteSafeRequest) -> Dict[str, Any]:
    """Use the clicked scan candidate when supplied, otherwise re-score.

    The old endpoint re-scored the pair at execution time. That can cause a
    trade to fail even though the user clicked a visible candidate from the
    scan result. For paper trading, the clicked candidate is the auditable
    decision that should be saved.
    """
    candidate = req.candidate or {}
    if candidate.get("pair") == req.pair and candidate.get("direction") not in (None, "", "none"):
        candidate = dict(candidate)
    else:
        candidate = score_candidate(req.pair, req.account_balance)

    candidate["pair"] = req.pair
    candidate.setdefault("account_balance", req.account_balance)
    candidate.setdefault("risk_pct", MAX_RISK)
    candidate.setdefault("rr_estimate", MIN_RR)
    candidate.setdefault("status", "trade_candidate")
    candidate.setdefault("broker_mode", "paper")
    candidate.setdefault("source", "scanner_candidate")

    # Make sure the fields used by the trade journal exist.
    if candidate.get("entry_price") is None and candidate.get("entry") is not None:
        candidate["entry_price"] = candidate.get("entry")
    if candidate.get("entry") is None and candidate.get("entry_price") is not None:
        candidate["entry"] = candidate.get("entry_price")
    if candidate.get("take_profit") is None and candidate.get("target") is not None:
        candidate["take_profit"] = candidate.get("target")
    if candidate.get("target") is None and candidate.get("take_profit") is not None:
        candidate["target"] = candidate.get("take_profit")

    missing = [field for field in ("entry_price", "stop_loss", "take_profit", "direction") if candidate.get(field) in (None, "")]
    if missing:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Paper trade candidate is missing required fields.",
                "missing_fields": missing,
                "pair": req.pair,
                "candidate_status": candidate.get("status"),
                "rejection_reason": candidate.get("rejection_reason"),
            },
        )

    if candidate.get("status") not in ("trade_candidate", "manual_candidate", "paper_candidate"):
        raise HTTPException(
            status_code=422,
            detail={
                "message": "This setup is not currently a trade candidate.",
                "pair": req.pair,
                "candidate_status": candidate.get("status"),
                "rejection_reason": candidate.get("rejection_reason") or candidate.get("entry_reason"),
            },
        )

    return candidate


@app.post("/api/agent/execute")
async def agent_execute_safe(req: AgentExecuteSafeRequest, user: str = Depends(current_user)):
    if KILL_SWITCH["active"]:
        raise HTTPException(status_code=403, detail=KILL_SWITCH["reason"] or "Kill switch active")

    candidate = _normalise_candidate(req)

    try:
        trade = save_trade(user, candidate)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Paper trade could not be saved to storage.",
                "storage_mode": storage_mode(),
                "error": str(exc),
            },
        ) from exc

    audit_warning = None
    try:
        add_audit(user, "paper_execute", "opened", "Paper trade opened. No real order was sent.", req.pair, str(trade["id"]))
    except Exception as exc:
        # Audit failure should not make a successfully saved paper trade look
        # like it failed. Return the warning so the UI can surface it later.
        audit_warning = str(exc)

    return {
        "trade_id": trade["id"],
        "execution": {
            "mode": "paper",
            "status": "filled",
            "order_id": trade.get("order_id"),
            "live_money": False,
            "saved": True,
        },
        "candidate": candidate,
        "trade": trade,
        "storage_mode": storage_mode(),
        "audit_warning": audit_warning,
        "created_at": now(),
    }
