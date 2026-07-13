from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import Depends

from . import paper_mvp_persistent as base
from .paper_mvp_finalfix import app
from .paper_mvp_persistent import (
    DAILY_LIMIT,
    WEEKLY_LIMIT,
    KILL_SWITCH,
    current_user,
    list_trades,
    manage_trades,
    snapshot,
    storage_mode,
)


def _remove_routes(path: str, methods: Optional[set[str]] = None) -> None:
    kept = []
    for route in app.router.routes:
        route_path = getattr(route, "path", None)
        route_methods = getattr(route, "methods", set()) or set()
        if route_path == path and (methods is None or route_methods.intersection(methods)):
            continue
        kept.append(route)
    app.router.routes = kept


def _migrate_trade_candidate_status() -> None:
    """Convert successfully executed legacy paper trades from trade_candidate to open.

    The scanner uses status=trade_candidate. An earlier execution version saved the
    candidate payload as-is, which meant the trade existed in the journal but did
    not appear in Open Paper Trades and was not picked up by management rules.
    """
    if not base.DATABASE_URL:
        return
    try:
        with base.db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE paper_trades
                    SET
                        status = 'open',
                        updated_at = COALESCE(updated_at, created_at),
                        payload = jsonb_set(
                            COALESCE(payload, '{}'::jsonb),
                            '{status}',
                            '"open"'::jsonb,
                            true
                        )
                    WHERE status = 'trade_candidate'
                       OR payload->>'status' = 'trade_candidate'
                    """
                )
        base._DB_OK = True
    except Exception:
        # Do not crash the app if migration cannot run; health/config will still
        # show whether Postgres is available.
        base._DB_OK = False


def _normalise_open_trade(t: Dict[str, Any]) -> Dict[str, Any]:
    item = dict(t)
    if str(item.get("status", "")).lower() == "trade_candidate":
        item["candidate_status"] = "trade_candidate"
        item["status"] = "open"
    return item


def _open_trades_for_user(user: str) -> List[Dict[str, Any]]:
    rows = list_trades(user)
    return [
        _normalise_open_trade(t)
        for t in rows
        if str(t.get("status", "open")).lower() in ("open", "trade_candidate")
    ]


_migrate_trade_candidate_status()

# Replace routes that rely on the old strict status=open query.
_remove_routes("/api/agent/trades/open", {"GET"})
_remove_routes("/api/agent/manage", {"POST"})


@app.get("/api/agent/trades/open")
async def agent_open_trades_status_fixed(user: str = Depends(current_user)):
    return {
        "open_trades": _open_trades_for_user(user),
        "trading_allowed": {
            "allowed": not KILL_SWITCH["active"],
            "daily_loss_pct": 0.0,
            "weekly_loss_pct": 0.0,
            "daily_limit": DAILY_LIMIT,
            "weekly_limit": WEEKLY_LIMIT,
        },
        "kill_switch": KILL_SWITCH["active"],
        "storage_mode": storage_mode(),
    }


@app.post("/api/agent/manage")
async def agent_manage_status_fixed(req: base.ManageTradesRequest, user: str = Depends(current_user)):
    # The import-time migration converts legacy trade_candidate rows to open so
    # the existing management engine can close them when SL/TP is reached.
    actions = manage_trades(user, req.current_prices or None)
    return {
        "actions_taken": actions,
        "open_trades": _open_trades_for_user(user),
        "snapshot": snapshot(),
        "storage_mode": storage_mode(),
    }
