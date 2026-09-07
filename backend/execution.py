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
import os
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

# The spread has to be small next to the stop, or the trade starts underwater
# by a meaningful fraction of the risk it was sized for. At 0.33 a 12 pip stop
# refuses anything above 4 pips. This is not a theoretical limit: an attempt to
# open GBP/USD at the 17:00 New York rollover met a 19.5 pip spread against a
# 12 pip stop - wider than the entire stop - and would have opened roughly
# 1.6R down had the broker filled it. OANDA declined; nothing here did.
MAX_SPREAD_FRACTION_OF_STOP = float(os.getenv("MAX_SPREAD_FRACTION_OF_STOP", "0.33"))

# OANDA cancels an order it cannot fill rather than rejecting it, and puts the
# why in a machine code. Passing that code straight to the screen is barely
# better than saying nothing, so the ones that actually happen get sentences.
CANCEL_REASONS = {
    "MARKET_HALTED": (
        "the market was halted. This normally means the 17:00 New York "
        "rollover or the weekend close - spreads blow out and the broker "
        "stops filling for a few minutes either side."
    ),
    "INSUFFICIENT_LIQUIDITY": (
        "there was not enough liquidity to fill the whole order at once."
    ),
    "INSUFFICIENT_MARGIN": "the account did not have enough margin.",
    "FIFO_VIOLATION": "it would have broken the broker's FIFO rule.",
    "TIME_IN_FORCE_EXPIRED": "it could not be filled immediately and expired.",
    "BOUNDS_VIOLATION": "the price moved outside the bounds set on the order.",
    "STOP_LOSS_ON_FILL_LOSS": (
        "the stop would already have been hit at the fill price - the spread "
        "was wider than the stop distance."
    ),
}


def _explain_cancel(reason: str) -> str:
    """OANDA's cancel code as a sentence, with the code kept for the record."""
    text = CANCEL_REASONS.get(reason)
    return f"OANDA did not fill the order: {text} ({reason})" if text else (
        f"OANDA did not fill the order ({reason or 'no reason given'})."
    )


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

        # Refuse a spread that is large next to the stop. The position was
        # sized so that hitting the stop costs 1R; crossing a wide spread to
        # get in spends part of that R before the trade has done anything, and
        # a spread wider than the stop itself means the stop is already behind
        # price at the moment of the fill. There was no check here at all
        # before - the only thing that stopped a 19.5 pip spread going through
        # was the broker declining it.
        spread = abs(float(live["closeoutAsk"]) - float(live["closeoutBid"]))
        if stop_distance > 0 and spread > stop_distance * MAX_SPREAD_FRACTION_OF_STOP:
            pip = 0.01 if "JPY" in candidate["pair"].upper() else 0.0001
            raise RuntimeError(
                f"Spread is {spread / pip:.1f} pips against a {stop_distance / pip:.1f} pip stop "
                f"({spread / stop_distance:.0%} of the risk). Refusing to open - "
                "this is normal around the 17:00 New York rollover and the weekend close."
            )
        if candidate["direction"] == "buy":
            stop_loss = reference_price - stop_distance
            take_profit = reference_price + target_distance
        else:
            stop_loss = reference_price + stop_distance
            take_profit = reference_price - target_distance

        precision = _price_precision(candidate["pair"])
        # Attach the bracket as a DISTANCE from the fill, not an absolute price.
        # The prices above are computed from a quote fetched moments earlier, so
        # any slippage between that quote and the actual fill silently changes
        # how far the stop really sits - and the position was sized on the
        # intended distance. A trade meant to risk 1R would then risk more or
        # less than 1R, with nothing in the record showing it. OANDA anchors a
        # distance to the real fill price, so the risk is exactly what was sized.
        payload = {
            "order": {
                "type": "MARKET",
                "instrument": instrument,
                "units": str(int(units)),
                "timeInForce": "FOK",
                "positionFill": "DEFAULT",
                "stopLossOnFill": {"distance": f"{stop_distance:.{precision}f}"},
                "takeProfitOnFill": {"distance": f"{target_distance:.{precision}f}"},
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
            # Three different shapes come back for "no fill" and only one was
            # being read, so every other case surfaced as the generic "OANDA
            # did not return a fill for this order" - a message that tells you
            # nothing about whether the market was shut, the margin was short
            # or the price had moved.
            cancel = data.get("orderCancelTransaction") or {}
            reject = data.get("orderRejectTransaction") or {}
            if cancel:
                raise RuntimeError(_explain_cancel(str(cancel.get("reason", ""))))
            if reject:
                raise RuntimeError(_explain_cancel(str(reject.get("rejectReason", ""))))
            raise RuntimeError("OANDA did not return a fill for this order.")

        now = datetime.now(timezone.utc).isoformat()

        # Record the bracket relative to where it actually filled. Returning the
        # pre-fill estimates would leave our own stop/target checks comparing
        # against levels the broker is not holding.
        filled_at_price = float(fill.get("price", candidate["entry"]))
        if candidate["direction"] == "buy":
            stop_loss = filled_at_price - stop_distance
            take_profit = filled_at_price + target_distance
        else:
            stop_loss = filled_at_price + stop_distance
            take_profit = filled_at_price - target_distance

        return {
            "mode": MODE_DEMO,
            "order_id": fill.get("id", "unknown"),
            "status": "filled",
            "pair": candidate["pair"],
            "direction": candidate["direction"],
            "entry": filled_at_price,
            "stop_loss": round(stop_loss, precision),
            "take_profit": round(take_profit, precision),
            "position_units": candidate["position_units"],
            "risk_pct": candidate["risk_pct"],
            "risk_amount": candidate["risk_amount"],
            "filled_at": fill.get("time", now),
            "spread_cost": float(fill.get("halfSpreadCost", 0)) * 2,
            "slippage": round(abs(filled_at_price - candidate["entry"]), 5),
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
