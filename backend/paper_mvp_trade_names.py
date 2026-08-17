from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import Depends

from . import paper_mvp_quick_trade as quick

app = quick.app
base = quick.base
compat = quick.compat
chart = quick.chart


def _safe_str(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text or fallback


def _direction_label(value: Any) -> str:
    direction = _safe_str(value).lower()
    if direction == "buy":
        return "Buy"
    if direction == "sell":
        return "Sell"
    return direction.title() if direction else "Trade"


def _origin_label(trade: Dict[str, Any]) -> str:
    origin = _safe_str(trade.get("trade_origin") or trade.get("origin") or trade.get("source")).lower()
    setup = _safe_str(trade.get("setup_label") or trade.get("setup_type") or trade.get("entry_reason")).lower()
    if "personal" in origin or "personal" in setup or "manual" in setup:
        return "Personal"
    if "ai" in origin or "ai" in setup or "scanner" in setup:
        return "AI"
    # Older scanner/executed trades did not store an explicit origin, so treat them as AI-generated.
    return "AI"


def _sort_key(trade: Dict[str, Any]) -> tuple[str, str]:
    created = _safe_str(trade.get("created_at") or trade.get("filled_at") or trade.get("opened_at"))
    return created, _safe_str(trade.get("id"))


def _name_for_trade(trade: Dict[str, Any], sequence: int) -> Dict[str, Any]:
    pair = _safe_str(trade.get("pair"), "Unknown")
    direction = _direction_label(trade.get("direction"))
    origin = _origin_label(trade)
    display_sequence = int(sequence)
    display_name = f"{origin} {pair} {direction} #{display_sequence:03d}"
    return {
        "display_sequence": display_sequence,
        "display_name": display_name,
        "friendly_name": display_name,
        "short_trade_id": _safe_str(trade.get("id"))[:8],
        "technical_id": _safe_str(trade.get("id")),
        "trade_origin_label": origin,
    }


def _name_map(user: str) -> Dict[str, Dict[str, Any]]:
    all_rows = compat.compat_list_trades(user)
    ordered = sorted(all_rows, key=_sort_key)
    names: Dict[str, Dict[str, Any]] = {}
    for index, trade in enumerate(ordered, start=1):
        trade_id = _safe_str(trade.get("id"))
        if trade_id:
            names[trade_id] = _name_for_trade(trade, index)
    return names


def name_trade(user: str, trade: Dict[str, Any], names: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    item = dict(trade)
    trade_id = _safe_str(item.get("id"))
    name_data = (names or _name_map(user)).get(trade_id)
    if not name_data:
        # Fallback for a just-created row not returned in the all-trades list yet.
        name_data = _name_for_trade(item, int(item.get("display_sequence") or 1))
    item.update(name_data)
    return item


def name_trades(user: str, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    names = _name_map(user)
    return [name_trade(user, row, names) for row in rows]


# Patch chart trade-line helper so chart overlays and trade chips also receive display names.
def _named_trade_lines(user: str, pair: str, trade_id: Optional[str] = None) -> List[Dict[str, Any]]:
    rows = name_trades(user, compat.compat_list_trades(user, "open"))
    lines = []
    for trade in rows:
        if trade_id and str(trade.get("id")) != str(trade_id):
            continue
        if str(trade.get("pair", "")).upper() != pair:
            continue
        lines.append(
            {
                "id": trade.get("id"),
                "display_name": trade.get("display_name"),
                "friendly_name": trade.get("friendly_name"),
                "short_trade_id": trade.get("short_trade_id"),
                "pair": trade.get("pair"),
                "direction": trade.get("direction"),
                "entry": trade.get("entry_price") or trade.get("entry"),
                "stop_loss": trade.get("stop_loss"),
                "take_profit": trade.get("take_profit") or trade.get("target"),
                "created_at": trade.get("filled_at") or trade.get("created_at"),
                "status": trade.get("status"),
                "setup_label": trade.get("setup_label") or trade.get("setup_type"),
            }
        )
    return lines


chart._trade_lines = _named_trade_lines


# Replace selected read endpoints so the frontend receives friendly names everywhere.
for path, methods in [
    ("/api/agent/status", {"GET"}),
    ("/api/agent/trades/open", {"GET"}),
    ("/api/agent/open-trades", {"GET"}),
    ("/api/agent/trades", {"GET"}),
    ("/api/agent/trades/closed", {"GET"}),
    ("/api/agent/trades/{trade_id}", {"GET"}),
    ("/api/agent/trades/quick-open", {"POST"}),
    ("/api/agent/trades/quick-open-ai", {"POST"}),
    ("/api/agent/trades/{trade_id}/quick-close", {"POST"}),
]:
    compat._remove_routes(path, methods)


@app.get("/api/agent/status")
async def agent_status_named(user: str = Depends(base.current_user)):
    open_trades = name_trades(user, compat.compat_list_trades(user, "open"))
    return {
        "version": "0.9.0-friendly-trade-names",
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


@app.get("/api/agent/trades/open")
async def agent_open_trades_named(user: str = Depends(base.current_user)):
    return {
        "open_trades": name_trades(user, compat.compat_list_trades(user, "open")),
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


@app.get("/api/agent/open-trades")
async def agent_open_trades_alias_named(user: str = Depends(base.current_user)):
    return await agent_open_trades_named(user)


@app.get("/api/agent/trades")
async def agent_all_trades_named(user: str = Depends(base.current_user)):
    return name_trades(user, compat.compat_list_trades(user))


@app.get("/api/agent/trades/closed")
async def agent_closed_trades_named(user: str = Depends(base.current_user)):
    return name_trades(user, compat.compat_list_trades(user, "closed"))


@app.get("/api/agent/trades/{trade_id}")
async def agent_get_trade_named(trade_id: str, user: str = Depends(base.current_user)):
    return name_trade(user, compat.compat_get_trade(user, trade_id))


@app.post("/api/agent/trades/quick-open")
async def quick_open_personal_trade_named(req: quick.QuickOpenRequest, user: str = Depends(base.current_user)):
    result = await quick.quick_open_personal_trade(req, user)
    if isinstance(result, dict) and isinstance(result.get("trade"), dict):
        result["trade"] = name_trade(user, result["trade"])
        result["display_name"] = result["trade"].get("display_name")
    return result


@app.post("/api/agent/trades/quick-open-ai")
async def quick_open_ai_trade_named(req: quick.AiQuickOpenRequest, user: str = Depends(base.current_user)):
    result = await quick.quick_open_ai_trade(req, user)
    if isinstance(result, dict) and isinstance(result.get("trade"), dict):
        result["trade"] = name_trade(user, result["trade"])
        result["display_name"] = result["trade"].get("display_name")
    return result


@app.post("/api/agent/trades/{trade_id}/quick-close")
async def quick_close_trade_named(trade_id: str, req: quick.QuickCloseRequest, user: str = Depends(base.current_user)):
    result = await quick.quick_close_trade(trade_id, req, user)
    if isinstance(result, dict) and isinstance(result.get("closed_trade"), dict):
        result["closed_trade"] = name_trade(user, result["closed_trade"])
        result["display_name"] = result["closed_trade"].get("display_name")
    return result
