from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Set

from fastapi import Depends, HTTPException, Query, Request
from pydantic import BaseModel

from . import paper_mvp_trade_names as names

app = names.app
base = names.base
compat = names.compat
chart = names.chart
quick = names.quick


class AutoCloseRequest(BaseModel):
    pair: Optional[str] = None


def _as_float(value: Any, fallback: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return fallback
        return float(value)
    except Exception:
        return fallback


def _pair(value: Any) -> str:
    return str(value or "").upper().replace("_", "/")


def _direction(value: Any) -> str:
    return str(value or "").strip().lower()


def _target(trade: Dict[str, Any]) -> float:
    return _as_float(trade.get("take_profit", trade.get("target")))


def _sl(trade: Dict[str, Any]) -> float:
    return _as_float(trade.get("stop_loss"))


def _quote_for_pair(pair: str) -> Dict[str, Any]:
    return quick._latest_quote(pair)


def _close_side_price(trade: Dict[str, Any], quote: Dict[str, Any]) -> float:
    return quick._market_price_for_close(trade, quote)


def _hit_reason(trade: Dict[str, Any], quote: Dict[str, Any]) -> Optional[str]:
    direction = _direction(trade.get("direction"))
    stop_loss = _sl(trade)
    take_profit = _target(trade)
    close_price = _close_side_price(trade, quote)
    if not stop_loss or not take_profit or not close_price:
        return None

    if direction == "buy":
        if close_price <= stop_loss:
            return "stop_loss_hit"
        if close_price >= take_profit:
            return "take_profit_hit"
    elif direction == "sell":
        if close_price >= stop_loss:
            return "stop_loss_hit"
        if close_price <= take_profit:
            return "take_profit_hit"
    return None


def _close_trade_at_market(user: str, trade: Dict[str, Any], quote: Dict[str, Any], reason: str) -> Dict[str, Any]:
    pair = _pair(trade.get("pair"))
    # Fill at the level that was actually breached, not the live quote. The
    # auto-close check only runs once a day (Vercel cron) or when the user
    # has that pair's chart open, so price can gap well past the stop/target
    # between checks - filling at the raw current price would then produce
    # wildly inflated R-multiples (and £ P&L) instead of a realistic ~1R stop.
    trigger_price = _sl(trade) if reason == "stop_loss_hit" else _target(trade)
    close_price = trigger_price if trigger_price else _close_side_price(trade, quote)
    result_r = quick._result_r(trade, close_price)
    result_money = quick._result_money(trade, result_r)
    now = base.now()

    trade["status"] = "closed"
    trade["updated_at"] = now
    trade["closed_at"] = now
    trade["exit_price"] = close_price
    trade["close_price"] = close_price
    trade["close_reason"] = reason
    trade["result_r"] = result_r
    trade["result_money"] = result_money
    trade["quality_tag"] = "take_profit" if reason == "take_profit_hit" else "stop_loss"
    trade["auto_closed"] = True
    trade["auto_close_quote"] = quote
    trade["close_quote"] = quote
    trade["live_trading_locked"] = True

    compat.compat_update_trade(trade)
    try:
        label = "TP hit" if reason == "take_profit_hit" else "SL hit"
        compat.compat_add_audit(
            user,
            "auto_close",
            "closed",
            f"{label}: paper trade closed at {close_price} ({result_r:+.2f}R / {result_money:+.2f}).",
            pair,
            trade.get("id"),
        )
    except Exception:
        pass

    named = names.name_trade(user, trade)
    return {
        "trade_id": trade.get("id"),
        "display_name": named.get("display_name"),
        "pair": pair,
        "direction": trade.get("direction"),
        "reason": reason,
        "close_price": close_price,
        "result_r": result_r,
        "result_money": result_money,
        "closed_trade": named,
    }


def auto_close_open_trades(user: str, pair: Optional[str] = None) -> List[Dict[str, Any]]:
    pair_filter = _pair(pair) if pair else None
    actions: List[Dict[str, Any]] = []
    open_trades = compat.compat_list_trades(user, "open")

    quotes: Dict[str, Dict[str, Any]] = {}
    for trade in open_trades:
        trade_pair = _pair(trade.get("pair"))
        if not trade_pair:
            continue
        if pair_filter and trade_pair != pair_filter:
            continue
        if trade_pair not in quotes:
            quotes[trade_pair] = _quote_for_pair(trade_pair)
        quote = quotes[trade_pair]
        reason = _hit_reason(trade, quote)
        if not reason:
            continue
        actions.append(_close_trade_at_market(user, trade, quote, reason))
    return actions


def _configured_cron_users() -> Set[str]:
    users: Set[str] = set()
    for value in os.getenv("PAPER_CRON_USERS", "").split(","):
        user = value.strip()
        if user:
            users.add(user)
    return users


def _open_trade_users() -> List[str]:
    users: Set[str] = _configured_cron_users()

    if compat.compat_storage_mode() == "postgres":
        try:
            with base.db_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(f"SELECT DISTINCT user_name FROM {compat.PAPER_TABLE} WHERE status=%s", ("open",))
                    for row in cur.fetchall() or []:
                        if row and row[0]:
                            users.add(str(row[0]))
        except Exception:
            pass
    else:
        try:
            for trade in getattr(base, "TRADES", []):
                if str(trade.get("status", "")).lower() == "open":
                    user_name = trade.get("user_name") or trade.get("user") or trade.get("username")
                    if user_name:
                        users.add(str(user_name))
        except Exception:
            pass

    if not users:
        try:
            auth_users = getattr(base, "USERS", {}) or {}
            users.update(str(u) for u in auth_users.keys() if u)
        except Exception:
            pass

    return sorted(users)


def _verify_cron_request(request: Request) -> Dict[str, Any]:
    secret = os.getenv("CRON_SECRET", "").strip()
    if not secret:
        raise HTTPException(status_code=503, detail="CRON_SECRET is not configured on this Vercel project.")
    auth_header = (request.headers.get("authorization") or "").strip()
    if auth_header != f"Bearer {secret}":
        raise HTTPException(status_code=401, detail="Unauthorized cron request")
    return {
        "authorized": True,
        "user_agent": request.headers.get("user-agent", ""),
        "vercel_cron": "vercel-cron" in (request.headers.get("user-agent", "").lower()),
    }


for path, methods in [
    ("/api/agent/chart/tick", {"GET"}),
    ("/api/agent/chart/candles", {"GET"}),
    ("/api/agent/trades/auto-close-check", {"GET", "POST"}),
    ("/api/agent/trades/{trade_id}", {"GET"}),
    ("/api/agent/cron/auto-close", {"GET"}),
]:
    compat._remove_routes(path, methods)


@app.get("/api/agent/chart/tick")
async def agent_chart_tick_auto_close(
    pair: str = Query("GBP/USD"),
    user: str = Depends(base.current_user),
):
    chart_pair = chart._pair(pair)
    auto_close_actions = auto_close_open_trades(user, chart_pair)
    payload = await chart.agent_chart_tick(chart_pair, user)
    payload["auto_close_actions"] = auto_close_actions
    payload["auto_closed_count"] = len(auto_close_actions)
    payload["paper_auto_close_enabled"] = True
    return payload


@app.get("/api/agent/chart/candles")
async def agent_chart_candles_auto_close(
    pair: str = Query("GBP/USD"),
    timeframe: str = Query("H1"),
    count: int = Query(160, ge=20, le=500),
    trade_id: Optional[str] = Query(None),
    user: str = Depends(base.current_user),
):
    chart_pair = chart._pair(pair)
    auto_close_actions = auto_close_open_trades(user, chart_pair)
    payload = await chart.agent_chart_candles(chart_pair, timeframe, count, trade_id, user)
    payload["auto_close_actions"] = auto_close_actions
    payload["auto_closed_count"] = len(auto_close_actions)
    payload["paper_auto_close_enabled"] = True
    return payload


@app.get("/api/agent/trades/auto-close-check")
async def auto_close_check_get(
    pair: Optional[str] = Query(None),
    user: str = Depends(base.current_user),
):
    actions = auto_close_open_trades(user, pair)
    return {
        "checked_pair": _pair(pair) if pair else "ALL",
        "closed_count": len(actions),
        "actions": actions,
        "open_trades": names.name_trades(user, compat.compat_list_trades(user, "open")),
        "storage_mode": compat.compat_storage_mode(),
        "paper_auto_close_enabled": True,
        "live_trading_locked": True,
    }


@app.post("/api/agent/trades/auto-close-check")
async def auto_close_check_post(req: AutoCloseRequest, user: str = Depends(base.current_user)):
    return await auto_close_check_get(req.pair, user)


@app.get("/api/agent/cron/auto-close")
async def cron_auto_close_all_open_trades(request: Request):
    auth = _verify_cron_request(request)
    users = _open_trade_users()
    actions: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []

    for user in users:
        try:
            user_actions = auto_close_open_trades(user)
            for action in user_actions:
                action["user"] = user
            actions.extend(user_actions)
        except Exception as exc:
            errors.append({"user": user, "error": str(exc)})

    return {
        "ok": len(errors) == 0,
        "cron": True,
        "auth": auth,
        "checked_users": users,
        "users_checked_count": len(users),
        "closed_count": len(actions),
        "actions": actions,
        "errors": errors,
        "storage_mode": compat.compat_storage_mode(),
        "paper_auto_close_enabled": True,
        "live_trading_locked": True,
        "generated_at": base.now(),
    }


@app.get("/api/agent/trades/{trade_id}")
async def agent_get_trade_after_auto_close(trade_id: str, user: str = Depends(base.current_user)):
    return names.name_trade(user, compat.compat_get_trade(user, trade_id))
