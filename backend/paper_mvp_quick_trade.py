from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from . import paper_mvp_chart as chart

app = chart.app
base = chart.base
compat = chart.compat


class QuickOpenRequest(BaseModel):
    pair: str
    direction: str
    account_balance: float = Field(default_factory=lambda: getattr(base, "START_BALANCE", 10000.0))
    risk_pct: float = Field(default_factory=lambda: getattr(base, "MAX_RISK", 0.5))
    rr: float = 2.0
    stop_pips: Optional[float] = None
    manual_sl: Optional[float] = None
    manual_tp: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    force_duplicate: bool = False
    fixed_units: Optional[float] = None


class AiQuickOpenRequest(BaseModel):
    pair: str
    account_balance: float = Field(default_factory=lambda: getattr(base, "START_BALANCE", 10000.0))
    force_duplicate: bool = False
    fixed_units: Optional[float] = None


class QuickCloseRequest(BaseModel):
    reason: str = "Quick close at market from dashboard"


def _as_float(value: Any, fallback: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return fallback
        return float(value)
    except Exception:
        return fallback


def _optional_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        parsed = float(value)
        return parsed if parsed > 0 else None
    except Exception:
        return None


def _pair(value: str) -> str:
    pair = str(value or "GBP/USD").upper().replace("_", "/")
    if pair not in base.WATCHLIST:
        raise HTTPException(status_code=400, detail=f"Unsupported pair: {pair}")
    return pair


def _direction(value: str) -> str:
    direction = str(value or "").strip().lower()
    if direction not in ("buy", "sell"):
        raise HTTPException(status_code=400, detail="Direction must be buy or sell")
    return direction


def _latest_quote(pair: str) -> Dict[str, Any]:
    quote = chart._current_quote(pair)
    if quote:
        return quote
    price = base.rprice(pair, base.base_price(pair))
    pip = base.pip_size(pair)
    return {
        "pair": pair,
        "price": price,
        "bid": base.rprice(pair, price - pip),
        "ask": base.rprice(pair, price + pip),
        "spread_pips": 2,
        "timestamp": base.now(),
        "source": "synthetic-fallback",
    }


def _market_price_for_open(pair: str, direction: str, quote: Dict[str, Any]) -> float:
    if direction == "buy":
        return base.rprice(pair, _as_float(quote.get("ask"), _as_float(quote.get("price"))))
    return base.rprice(pair, _as_float(quote.get("bid"), _as_float(quote.get("price"))))


def _market_price_for_close(trade: Dict[str, Any], quote: Dict[str, Any]) -> float:
    pair = _pair(str(trade.get("pair")))
    direction = _direction(str(trade.get("direction")))
    # Closing a buy uses the bid. Closing a sell uses the ask.
    if direction == "buy":
        return base.rprice(pair, _as_float(quote.get("bid"), _as_float(quote.get("price"))))
    return base.rprice(pair, _as_float(quote.get("ask"), _as_float(quote.get("price"))))


def _duplicate_open_trade(user: str, pair: str, direction: str) -> Optional[Dict[str, Any]]:
    for trade in compat.compat_list_trades(user, "open"):
        if str(trade.get("pair", "")).upper() == pair and str(trade.get("direction", "")).lower() == direction:
            return trade
    return None


def _result_r(trade: Dict[str, Any], close_price: float) -> float:
    pair = _pair(str(trade.get("pair")))
    direction = _direction(str(trade.get("direction")))
    entry = _as_float(trade.get("entry_price", trade.get("entry")))
    stop = _as_float(trade.get("stop_loss"))
    risk_per_unit = abs(entry - stop)
    if risk_per_unit <= 0:
        return 0.0
    if direction == "sell":
        return round((entry - close_price) / risk_per_unit, 4)
    return round((close_price - entry) / risk_per_unit, 4)


def _result_money(trade: Dict[str, Any], result_r: float) -> float:
    risk_amount = _as_float(trade.get("risk_amount"), 0.0)
    if risk_amount <= 0:
        balance = _as_float(trade.get("account_balance"), getattr(base, "START_BALANCE", 10000.0))
        risk_pct = _as_float(trade.get("risk_pct"), getattr(base, "MAX_RISK", 0.5))
        risk_amount = balance * (risk_pct / 100.0)
    return round(risk_amount * result_r, 2)


def _manual_levels(req: QuickOpenRequest) -> tuple[Optional[float], Optional[float]]:
    manual_sl = _optional_float(req.manual_sl)
    if manual_sl is None:
        manual_sl = _optional_float(req.stop_loss)
    manual_tp = _optional_float(req.manual_tp)
    if manual_tp is None:
        manual_tp = _optional_float(req.take_profit)
    return manual_sl, manual_tp


def _validate_manual_levels(pair: str, direction: str, entry: float, manual_sl: Optional[float], manual_tp: Optional[float]) -> None:
    if manual_sl is not None:
        if direction == "buy" and manual_sl >= entry:
            raise HTTPException(status_code=400, detail="For a BUY trade, SL must be below the entry price.")
        if direction == "sell" and manual_sl <= entry:
            raise HTTPException(status_code=400, detail="For a SELL trade, SL must be above the entry price.")
    if manual_tp is not None:
        if direction == "buy" and manual_tp <= entry:
            raise HTTPException(status_code=400, detail="For a BUY trade, TP must be above the entry price.")
        if direction == "sell" and manual_tp >= entry:
            raise HTTPException(status_code=400, detail="For a SELL trade, TP must be below the entry price.")


def _save_personal_trade(user: str, req: QuickOpenRequest) -> Dict[str, Any]:
    pair = _pair(req.pair)
    direction = _direction(req.direction)
    duplicate = _duplicate_open_trade(user, pair, direction)
    if duplicate and not req.force_duplicate:
        raise HTTPException(
            status_code=409,
            detail={
                "message": f"You already have an open {direction.upper()} paper trade on {pair}.",
                "duplicate_trade_id": duplicate.get("id"),
                "pair": pair,
                "direction": direction,
            },
        )

    quote = _latest_quote(pair)
    entry = _market_price_for_open(pair, direction, quote)
    pip = base.pip_size(pair)
    stop_pips = _as_float(req.stop_pips, 25.0 if pair == "XAU/USD" else 20.0)
    rr = max(0.5, _as_float(req.rr, 2.0))
    risk_pct = max(0.01, min(_as_float(req.risk_pct, getattr(base, "MAX_RISK", 0.5)), 5.0))
    balance = max(1.0, _as_float(req.account_balance, getattr(base, "START_BALANCE", 10000.0)))

    if direction == "buy":
        stop_loss = entry - (stop_pips * pip)
        take_profit = entry + (stop_pips * rr * pip)
    else:
        stop_loss = entry + (stop_pips * pip)
        take_profit = entry - (stop_pips * rr * pip)

    manual_sl, manual_tp = _manual_levels(req)
    _validate_manual_levels(pair, direction, entry, manual_sl, manual_tp)
    if manual_sl is not None:
        stop_loss = manual_sl
        stop_pips = abs(entry - stop_loss) / pip
    if manual_tp is not None:
        take_profit = manual_tp

    stop_distance = abs(entry - stop_loss)
    if stop_distance <= 0:
        raise HTTPException(status_code=400, detail="SL creates an invalid risk distance.")
    rr = max(0.01, abs(take_profit - entry) / stop_distance)

    fixed_units = _as_float(req.fixed_units, 0.0)
    if fixed_units > 0:
        position_units = round(fixed_units, 2)
        risk_amount = round(position_units * stop_distance, 2)
    else:
        risk_amount = round(balance * (risk_pct / 100.0), 2)
        position_units = round(risk_amount / stop_distance, 2) if stop_distance > 0 else 0
    trade = {
        "pair": pair,
        "direction": direction,
        "status": "open",
        "source": quote.get("source", "market"),
        "trade_origin": "personal_quick_open",
        "setup_type": "personal_quick_paper_trade",
        "setup_label": "Personal quick paper trade",
        "confidence": 0,
        "rr_estimate": rr,
        "session": base.session_label(),
        "in_window": base.london_window(),
        "entry_reason": "Personal quick paper trade opened from the chart.",
        "entry": base.rprice(pair, entry),
        "entry_price": base.rprice(pair, entry),
        "stop_loss": base.rprice(pair, stop_loss),
        "take_profit": base.rprice(pair, take_profit),
        "target": base.rprice(pair, take_profit),
        "stop_pips": round(stop_pips, 3),
        "risk_pct": risk_pct,
        "risk_amount": risk_amount,
        "account_balance": balance,
        "position_units": position_units,
        "quote": quote,
        "manual_sl_used": manual_sl is not None,
        "manual_tp_used": manual_tp is not None,
        "live_trading_locked": True,
    }
    saved = compat.compat_save_trade(user, trade)
    try:
        compat.compat_add_audit(user, "personal_quick_open", "opened", f"Personal quick {direction.upper()} paper trade opened on {pair}.", pair, saved.get("id"))
    except Exception:
        pass
    return saved


@app.post("/api/agent/trades/quick-open")
async def quick_open_personal_trade(req: QuickOpenRequest, user: str = Depends(base.current_user)):
    saved = _save_personal_trade(user, req)
    return {
        "trade": saved,
        "trade_id": saved.get("id"),
        "mode": "paper",
        "trade_origin": "personal_quick_open",
        "live_trading_locked": True,
        "storage_mode": compat.compat_storage_mode(),
    }


@app.post("/api/agent/trades/quick-open-ai")
async def quick_open_ai_trade(req: AiQuickOpenRequest, user: str = Depends(base.current_user)):
    pair = _pair(req.pair)
    candidate = base.score_candidate(pair, req.account_balance, req.fixed_units)
    if candidate.get("status") != "trade_candidate":
        raise HTTPException(status_code=409, detail={"message": "AI did not return an executable paper-trade candidate.", "candidate": candidate})
    direction = _direction(candidate.get("direction"))
    duplicate = _duplicate_open_trade(user, pair, direction)
    if duplicate and not req.force_duplicate:
        raise HTTPException(
            status_code=409,
            detail={
                "message": f"You already have an open {direction.upper()} paper trade on {pair}.",
                "duplicate_trade_id": duplicate.get("id"),
                "candidate": candidate,
            },
        )
    candidate["trade_origin"] = "ai_quick_open"
    candidate["setup_label"] = candidate.get("setup_label") or "AI quick paper trade"
    candidate["entry_reason"] = candidate.get("entry_reason") or "AI quick paper trade opened from the chart."
    saved = compat.compat_save_trade(user, candidate)
    try:
        compat.compat_add_audit(user, "ai_quick_open", "opened", f"AI quick paper trade opened on {pair}.", pair, saved.get("id"))
    except Exception:
        pass
    return {
        "trade": saved,
        "trade_id": saved.get("id"),
        "candidate": candidate,
        "mode": "paper",
        "trade_origin": "ai_quick_open",
        "live_trading_locked": True,
        "storage_mode": compat.compat_storage_mode(),
    }


@app.post("/api/agent/trades/{trade_id}/quick-close")
async def quick_close_trade(trade_id: str, req: QuickCloseRequest, user: str = Depends(base.current_user)):
    trade = compat.compat_get_trade(user, trade_id)
    if str(trade.get("status", "")).lower() != "open":
        raise HTTPException(status_code=409, detail="Trade is not open")
    pair = _pair(str(trade.get("pair")))
    quote = _latest_quote(pair)
    close_price = _market_price_for_close(trade, quote)
    result_r = _result_r(trade, close_price)
    result_money = _result_money(trade, result_r)

    trade["status"] = "closed"
    trade["updated_at"] = base.now()
    trade["closed_at"] = base.now()
    trade["exit_price"] = close_price
    trade["close_price"] = close_price
    trade["close_reason"] = req.reason or "Quick close at market from dashboard"
    trade["result_r"] = result_r
    trade["result_money"] = result_money
    trade["quality_tag"] = "quick_close"
    trade["close_quote"] = quote

    compat.compat_update_trade(trade)
    try:
        compat.compat_add_audit(user, "quick_close", "closed", f"Quick close at market: {result_r:+.2f}R / {result_money:+.2f}.", pair, trade_id)
    except Exception:
        pass
    return {
        "closed_trade": trade,
        "close_price": close_price,
        "quote": quote,
        "result_r": result_r,
        "result_money": result_money,
        "mode": "paper",
        "live_trading_locked": True,
        "storage_mode": compat.compat_storage_mode(),
    }
