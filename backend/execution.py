"""
execution.py - Demo/paper execution engine for the AI FX Trading Agent.

This module provides a broker abstraction layer so the rest of the platform
can work with paper trading, OANDA demo, or future providers without rewriting
the application.

SAFETY RULE (spec Sec4 and Sec7):
    ENABLE_LIVE_TRADING must be False in production.
    No real-money execution path is available in the MVP.
    All live-trading code paths are locked and clearly labelled.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List

import httpx

from .config import settings

# ---------------------------------------------------------------------------
# Broker mode constants
# ---------------------------------------------------------------------------

MODE_PAPER = "paper"
MODE_DEMO = "oanda_demo"
MODE_LIVE = "oanda_live"  # LOCKED - must not be reachable in MVP

OANDA_PRACTICE_URL = "https://api-fxpractice.oanda.com"


def _active_mode() -> str:
    """Return the current execution mode. Live mode is hard-blocked."""
    if settings.enable_live_trading:
        # Extra safety guard - even if the flag were flipped, MVP refuses live mode.
        raise RuntimeError(
            "LIVE TRADING IS LOCKED IN THE MVP. Set ENABLE_LIVE_TRADING=false or remove the flag."
        )
    if settings.oanda_access_token and settings.oanda_account_id:
        return MODE_DEMO  # OANDA credentials present -> use demo account
    return MODE_PAPER  # No credentials -> pure paper mode


# ---------------------------------------------------------------------------
# Paper execution (default / safe path)
# ---------------------------------------------------------------------------

def _place_paper_trade(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """
    Simulate trade placement without any broker connection.
    Returns a response that mirrors the shape of a real broker response
    so the rest of the platform can treat both identically.
    """
    now = datetime.now(timezone.utc).isoformat()
    order_id = f"PAPER-{now.replace(':', '').replace('.', '')[:20]}"

    return {
        "mode": MODE_PAPER,
        "order_id": order_id,
        "status": "filled",
        "pair": candidate["pair"],
        "direction": candidate["direction"],
        "entry": candidate["entry"],
        "stop_loss": candidate["stop_loss"],
        "take_profit": candidate["take_profit"],
        "position_units": candidate["position_units"],
        "risk_pct": candidate["risk_pct"],
        "risk_amount": candidate["risk_amount"],
        "filled_at": now,
        "spread_cost": None,  # Not available in paper mode
        "slippage": None,
        "broker_raw": None,
        "note": "Paper trade - no real money involved.",
    }


# ---------------------------------------------------------------------------
# OANDA demo execution
# ---------------------------------------------------------------------------

def _price_precision(pair: str) -> int:
    if pair == "XAU/USD":
        return 2
    if "JPY" in pair:
        return 3
    return 5


def _place_oanda_demo_trade(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """
    Place a trade on the OANDA practice (demo) environment.
    Uses the OANDA v20 REST API. Never touches real money - the practice
    environment is a free, separate sandbox account from OANDA.
    """
    try:
        headers = {
            "Authorization": f"Bearer {settings.oanda_access_token}",
            "Content-Type": "application/json",
        }

        # OANDA instrument format: GBP_USD not GBP/USD
        instrument = candidate["pair"].replace("/", "_")
        # position_units from score_candidate() is already raw currency units
        # (risk_amount / stop_distance), not lots - this used to multiply by
        # 10000 on top of that, turning a reasonable ~25,000-unit position
        # into a ~250,000,000-unit order that OANDA rejects outright.
        units = candidate["position_units"]
        if candidate["direction"] == "sell":
            units = -abs(units)

        # candidate['entry']/'stop_loss'/'take_profit' come from this app's own
        # market analysis, which can be running on synthetic fallback data with
        # no relation to OANDA's real price for this instrument. Sending those
        # absolute levels straight to OANDA as a bracket order can put the
        # stop/target on the wrong side of the real fill price - OANDA then
        # either rejects the order outright or triggers the bracket instantly.
        # Re-anchor the stop/target distance to OANDA's actual current price
        # instead of trusting the (possibly synthetic) absolute levels.
        pricing_url = f"{OANDA_PRACTICE_URL}/v3/accounts/{settings.oanda_account_id}/pricing"
        with httpx.Client(timeout=12) as client:
            price_resp = client.get(pricing_url, params={"instruments": instrument}, headers=headers)
            price_resp.raise_for_status()
            live_prices = price_resp.json().get("prices", [])
        if not live_prices:
            raise RuntimeError(f"OANDA returned no live price for {instrument}.")
        live = live_prices[0]
        reference_price = float(live["closeoutAsk"]) if candidate["direction"] == "buy" else float(live["closeoutBid"])

        stop_distance = abs(candidate["entry"] - candidate["stop_loss"])
        target_distance = abs(candidate["take_profit"] - candidate["entry"])
        if candidate["direction"] == "buy":
            stop_loss = reference_price - stop_distance
            take_profit = reference_price + target_distance
        else:
            stop_loss = reference_price + stop_distance
            take_profit = reference_price - target_distance

        precision = _price_precision(candidate["pair"])
        payload = {
            "order": {
                "type": "MARKET",
                "instrument": instrument,
                "units": str(int(units)),
                "timeInForce": "FOK",
                "positionFill": "DEFAULT",
                "stopLossOnFill": {"price": f"{stop_loss:.{precision}f}"},
                "takeProfitOnFill": {"price": f"{take_profit:.{precision}f}"},
            }
        }

        url = f"{OANDA_PRACTICE_URL}/v3/accounts/{settings.oanda_account_id}/orders"
        with httpx.Client(timeout=12) as client:
            resp = client.post(url, headers=headers, json=payload)
            try:
                data = resp.json()
            except Exception:
                data = {}
            if resp.status_code >= 400:
                # A 4xx means OANDA rejected the request itself (bad units,
                # bad price format, etc.) - raise_for_status() alone would
                # only surface the generic "400 Bad Request" status line, not
                # OANDA's actual error message in the response body.
                detail = data.get("errorMessage") or data.get("rejectReason") or resp.text
                raise RuntimeError(f"OANDA rejected the order ({resp.status_code}): {detail}")

        fill = data.get("orderFillTransaction", {})
        if not fill:
            reject = data.get("orderRejectTransaction", {})
            raise RuntimeError(reject.get("rejectReason") or "OANDA did not return a fill for this order.")

        now = datetime.now(timezone.utc).isoformat()

        return {
            "mode": MODE_DEMO,
            "order_id": fill.get("id", "unknown"),
            "status": "filled",
            "pair": candidate["pair"],
            "direction": candidate["direction"],
            "entry": float(fill.get("price", candidate["entry"])),
            "stop_loss": round(stop_loss, precision),
            "take_profit": round(take_profit, precision),
            "position_units": candidate["position_units"],
            "risk_pct": candidate["risk_pct"],
            "risk_amount": candidate["risk_amount"],
            "filled_at": fill.get("time", now),
            "spread_cost": float(fill.get("halfSpreadCost", 0)) * 2,
            "slippage": round(abs(float(fill.get("price", candidate["entry"])) - candidate["entry"]), 5),
            "broker_raw": json.dumps(data),
            "note": "OANDA practice demo trade.",
        }

    except Exception as exc:
        return {
            "mode": MODE_DEMO,
            "order_id": None,
            "status": "error",
            "pair": candidate["pair"],
            "direction": candidate["direction"],
            "entry": candidate["entry"],
            "stop_loss": candidate["stop_loss"],
            "take_profit": candidate["take_profit"],
            "position_units": candidate["position_units"],
            "risk_pct": candidate["risk_pct"],
            "risk_amount": candidate["risk_amount"],
            "filled_at": datetime.now(timezone.utc).isoformat(),
            "spread_cost": None,
            "slippage": None,
            "broker_raw": None,
            "error": str(exc),
            "note": "OANDA demo order failed - see error field.",
        }


# ---------------------------------------------------------------------------
# Public execution interface
# ---------------------------------------------------------------------------

def place_demo_trade(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """
    Primary entry point for the execution engine.

    Accepts a validated SetupCandidate dict (status == 'trade_candidate')
    and routes to the appropriate execution path based on configuration.

    This function NEVER routes to live trading in the MVP.
    """
    # Final safety check - abort if live trading somehow enabled.
    if settings.enable_live_trading:
        raise RuntimeError("Live trading is locked in the MVP. Aborting execution.")

    mode = _active_mode()

    if mode == MODE_DEMO:
        return _place_oanda_demo_trade(candidate)

    return _place_paper_trade(candidate)


def get_open_positions_oanda() -> List[Dict[str, Any]]:
    """Fetch open positions from the OANDA demo account. Returns [] on any error."""
    if not (settings.oanda_access_token and settings.oanda_account_id):
        return []
    try:
        headers = {"Authorization": f"Bearer {settings.oanda_access_token}"}
        url = f"{OANDA_PRACTICE_URL}/v3/accounts/{settings.oanda_account_id}/openPositions"
        with httpx.Client(timeout=12) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.json().get("positions", [])
    except Exception:
        return []


def close_position_oanda(instrument: str) -> Dict[str, Any]:
    """Close an open position on the OANDA demo account. Returns a result dict."""
    if settings.enable_live_trading:
        raise RuntimeError("Live trading is locked.")
    try:
        headers = {
            "Authorization": f"Bearer {settings.oanda_access_token}",
            "Content-Type": "application/json",
        }
        url = f"{OANDA_PRACTICE_URL}/v3/accounts/{settings.oanda_account_id}/positions/{instrument}/close"
        payload = {"longUnits": "ALL", "shortUnits": "ALL"}
        with httpx.Client(timeout=12) as client:
            resp = client.put(url, headers=headers, json=payload)
            resp.raise_for_status()
            return {"status": "closed", "instrument": instrument, "raw": resp.json()}
    except Exception as exc:
        return {"status": "error", "instrument": instrument, "error": str(exc)}
