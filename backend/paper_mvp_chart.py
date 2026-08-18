from __future__ import annotations

import math
import os
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import Depends, HTTPException, Query

from . import paper_mvp_phase1_safe as phase1

app = phase1.app
base = phase1.base
compat = phase1.compat

TIMEFRAMES: Dict[str, Dict[str, Any]] = {
    "M1": {"granularity": "M1", "seconds": 60, "default_count": 180},
    "M5": {"granularity": "M5", "seconds": 300, "default_count": 180},
    "M15": {"granularity": "M15", "seconds": 900, "default_count": 160},
    "H1": {"granularity": "H1", "seconds": 3600, "default_count": 140},
    "H4": {"granularity": "H4", "seconds": 14400, "default_count": 120},
    "D": {"granularity": "D", "seconds": 86400, "default_count": 120},
}


def _tf(value: str) -> str:
    key = str(value or "H1").upper().replace("1H", "H1").replace("4H", "H4")
    return key if key in TIMEFRAMES else "H1"


def _pair(value: str) -> str:
    pair = str(value or "GBP/USD").upper().replace("_", "/")
    if pair not in base.WATCHLIST:
        raise HTTPException(status_code=400, detail=f"Unsupported chart pair: {pair}")
    return pair


def _r(pair: str, value: float) -> float:
    return base.rprice(pair, float(value))


def _current_quote(pair: str) -> Optional[Dict[str, Any]]:
    try:
        snap = base.snapshot()
        for quote in snap.get("quotes", []):
            if quote.get("pair") == pair:
                return quote
    except Exception:
        return None
    return None


def _oanda_candles(pair: str, timeframe: str, count: int) -> List[Dict[str, Any]]:
    url = f"{base.oanda_base()}/v3/instruments/{pair.replace('/', '_')}/candles"
    params = {"count": max(20, min(int(count), 500)), "granularity": TIMEFRAMES[timeframe]["granularity"], "price": "M"}
    with httpx.Client(timeout=12) as client:
        res = client.get(
            url,
            params=params,
            headers={"Authorization": f"Bearer {os.getenv('OANDA_ACCESS_TOKEN')}"},
        )
        res.raise_for_status()
        payload = res.json()
    candles = []
    for c in payload.get("candles", []):
        m = c.get("mid") or {}
        if not m:
            continue
        candles.append(
            {
                "time": c.get("time"),
                "open": _r(pair, float(m["o"])),
                "high": _r(pair, float(m["h"])),
                "low": _r(pair, float(m["l"])),
                "close": _r(pair, float(m["c"])),
                "complete": bool(c.get("complete", True)),
                "source": "oanda-practice",
            }
        )
    return candles


def _synthetic_candles(pair: str, timeframe: str, count: int) -> List[Dict[str, Any]]:
    cfg = TIMEFRAMES[timeframe]
    count = max(20, min(int(count), 500))
    seed_key = f"{pair}-{timeframe}-{datetime.now(timezone.utc).strftime('%Y%m%d%H')}"
    random.seed(base._stable_seed(seed_key) % 1000000)
    quote = _current_quote(pair)
    price = float((quote or {}).get("price") or base.base_price(pair))
    pip = base.pip_size(pair)
    vol = (14 * pip) if pair != "XAU/USD" else 2.6
    if timeframe in ("M1", "M5"):
        vol *= 0.35
    elif timeframe == "M15":
        vol *= 0.65
    elif timeframe == "H4":
        vol *= 1.8
    elif timeframe == "D":
        vol *= 3.2

    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = now - timedelta(seconds=cfg["seconds"] * (count - 1))
    candles: List[Dict[str, Any]] = []
    running = price
    drift_phase = random.uniform(0, math.pi)
    for i in range(count):
        t = start + timedelta(seconds=cfg["seconds"] * i)
        op = running
        drift = math.sin((i / 11.0) + drift_phase) * vol * 0.35
        close = max(pip, op + random.uniform(-vol, vol) + drift)
        high = max(op, close) + abs(random.uniform(0, vol * 0.75))
        low = min(op, close) - abs(random.uniform(0, vol * 0.75))
        candles.append(
            {
                "time": t.isoformat(),
                "open": _r(pair, op),
                "high": _r(pair, high),
                "low": _r(pair, low),
                "close": _r(pair, close),
                "complete": True,
                "source": "synthetic-fallback",
            }
        )
        running = close
    return candles


def _chart_candles(pair: str, timeframe: str, count: int) -> tuple[List[Dict[str, Any]], str, List[str]]:
    warnings: List[str] = []
    if base.oanda_configured() and os.getenv("DATA_PROVIDER", "auto").lower() in ("auto", "oanda"):
        try:
            candles = _oanda_candles(pair, timeframe, count)
            if len(candles) >= 20:
                return candles, "oanda", warnings
            warnings.append("OANDA returned too few candles; fallback candles used.")
        except Exception as exc:
            warnings.append(f"OANDA candle feed failed: {exc}")
    candles = _synthetic_candles(pair, timeframe, count)
    return candles, "synthetic-fallback", warnings


def _trade_lines(user: str, pair: str, trade_id: Optional[str] = None) -> List[Dict[str, Any]]:
    rows = compat.compat_list_trades(user, "open")
    lines = []
    for trade in rows:
        if trade_id and str(trade.get("id")) != str(trade_id):
            continue
        if str(trade.get("pair", "")).upper() != pair:
            continue
        lines.append(
            {
                "id": trade.get("id"),
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


def _trade_markers(user: str, pair: str) -> List[Dict[str, Any]]:
    markers = []
    for trade in compat.compat_list_trades(user):
        if str(trade.get("pair", "")).upper() != pair:
            continue
        direction = str(trade.get("direction", "")).lower()
        created = trade.get("filled_at") or trade.get("created_at")
        if created:
            markers.append({"time": created, "type": "entry", "direction": direction, "trade_id": trade.get("id"), "label": f"{direction.upper()} entry"})
        closed = trade.get("closed_at")
        if closed:
            markers.append({"time": closed, "type": "exit", "direction": direction, "trade_id": trade.get("id"), "label": "Exit"})
    return markers[-80:]


@app.get("/api/agent/chart/candles")
async def agent_chart_candles(
    pair: str = Query("GBP/USD"),
    timeframe: str = Query("H1"),
    count: int = Query(160, ge=20, le=500),
    trade_id: Optional[str] = Query(None),
    user: str = Depends(base.current_user),
):
    chart_pair = _pair(pair)
    chart_tf = _tf(timeframe)
    if count == 160:
        count = TIMEFRAMES[chart_tf]["default_count"]
    candles, provider, warnings = _chart_candles(chart_pair, chart_tf, count)
    quote = _current_quote(chart_pair)
    return {
        "pair": chart_pair,
        "timeframe": chart_tf,
        "provider": provider,
        "generated_at": base.now(),
        "candles": candles,
        "current_price": quote,
        "trade_lines": _trade_lines(user, chart_pair, trade_id),
        "trade_markers": _trade_markers(user, chart_pair),
        "warnings": warnings,
        "live_trading_locked": True,
        "paper_trading": True,
    }


@app.get("/api/agent/chart/tick")
async def agent_chart_tick(
    pair: str = Query("GBP/USD"),
    user: str = Depends(base.current_user),
):
    chart_pair = _pair(pair)
    quote = _current_quote(chart_pair)
    if not quote:
        price = base.rprice(chart_pair, base.base_price(chart_pair))
        pip = base.pip_size(chart_pair)
        quote = {
            "pair": chart_pair,
            "price": price,
            "bid": base.rprice(chart_pair, price - pip),
            "ask": base.rprice(chart_pair, price + pip),
            "spread_pips": 2,
            "timestamp": base.now(),
            "source": "synthetic-fallback",
        }
    return {
        "pair": chart_pair,
        "price": quote.get("price"),
        "bid": quote.get("bid"),
        "ask": quote.get("ask"),
        "spread_pips": quote.get("spread_pips"),
        "timestamp": quote.get("timestamp") or base.now(),
        "generated_at": base.now(),
        "provider": quote.get("source") or "snapshot",
        "trade_lines": _trade_lines(user, chart_pair),
        "live_trading_locked": True,
        "paper_trading": True,
        "suggested_poll_seconds": 5,
    }
