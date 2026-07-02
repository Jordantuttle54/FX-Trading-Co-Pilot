"""
execution.py – Demo/paper execution engine for the AI FX Trading Agent.

This module provides a broker abstraction layer so the rest of the platform
can work with paper trading, OANDA demo, or future providers without rewriting
the application.

SAFETY RULE (spec §4 and §7):
    ENABLE_LIVE_TRADING must be False in production.
        No real-money execution path is available in the MVP.
            All live-trading code paths are locked and clearly labelled.
            """

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .config import settings

# ---------------------------------------------------------------------------
# Broker mode constants
# ---------------------------------------------------------------------------

MODE_PAPER  = "paper"
MODE_DEMO   = "oanda_demo"
MODE_LIVE   = "oanda_live"   # LOCKED – must not be reachable in MVP


def _active_mode() -> str:
      """Return the current execution mode. Live mode is hard-blocked."""
      if settings.enable_live_trading:
                # Extra safety guard – even if the flag were flipped, MVP refuses live mode.
                raise RuntimeError(
                              "LIVE TRADING IS LOCKED IN THE MVP.  "
                              "Set ENABLE_LIVE_TRADING=false or remove the flag."
                )
            if settings.oanda_access_token and settings.oanda_account_id:
                      return MODE_DEMO   # OANDA credentials present → use demo account
    return MODE_PAPER      # No credentials → pure paper mode


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
              "mode":           MODE_PAPER,
              "order_id":       order_id,
              "status":         "filled",
              "pair":           candidate["pair"],
              "direction":      candidate["direction"],
              "entry":          candidate["entry"],
              "stop_loss":      candidate["stop_loss"],
              "take_profit":    candidate["take_profit"],
              "position_units": candidate["position_units"],
              "risk_pct":       candidate["risk_pct"],
              "risk_amount":    candidate["risk_amount"],
              "filled_at":      now,
              "spread_cost":    None,   # Not available in paper mode
              "slippage":       None,
              "broker_raw":     None,
              "note":           "Paper trade – no real money involved.",
    }


# ---------------------------------------------------------------------------
# OANDA demo execution
# ---------------------------------------------------------------------------

def _place_oanda_demo_trade(candidate: Dict[str, Any]) -> Dict[str, Any]:
      """
          Place a trade on the OANDA practice (demo) environment.
              Uses the OANDA v20 REST API.
                  """
    try:
              import requests  # lazy import so paper mode works without requests installed

        base_url = "https://api-fxpractice.oanda.com"
        headers = {
                      "Authorization": f"Bearer {settings.oanda_access_token}",
                      "Content-Type": "application/json",
        }

        # OANDA instrument format: GBP_USD not GBP/USD
        instrument = candidate["pair"].replace("/", "_")
        units = candidate["position_units"] * 10000   # convert lots to units (approx)
        if candidate["direction"] == "sell":
                      units = -abs(units)

        payload = {
                      "order": {
                                        "type":            "MARKET",
                                        "instrument":      instrument,
                                        "units":           str(int(units)),
                                        "timeInForce":     "FOK",
                                        "positionFill":    "DEFAULT",
                                        "stopLossOnFill":  {"price": f"{candidate['stop_loss']:.5f}"},
                                        "takeProfitOnFill": {"price": f"{candidate['take_profit']:.5f}"},
                      }
        }

        url = f"{base_url}/v3/accounts/{settings.oanda_account_id}/orders"
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        fill = data.get("orderFillTransaction", {})
        now  = datetime.now(timezone.utc).isoformat()

        return {
                      "mode":           MODE_DEMO,
                      "order_id":       fill.get("id", "unknown"),
                      "status":         "filled",
                      "pair":           candidate["pair"],
                      "direction":      candidate["direction"],
                      "entry":          float(fill.get("price", candidate["entry"])),
                      "stop_loss":      candidate["stop_loss"],
                      "take_profit":    candidate["take_profit"],
                      "position_units": candidate["position_units"],
                      "risk_pct":       candidate["risk_pct"],
                      "risk_amount":    candidate["risk_amount"],
                      "filled_at":      fill.get("time", now),
                      "spread_cost":    float(fill.get("halfSpreadCost", 0)) * 2,
                      "slippage":       round(abs(float(fill.get("price", candidate["entry"])) - candidate["entry"]), 5),
                      "broker_raw":     json.dumps(data),
                      "note":           "OANDA practice demo trade.",
        }

except Exception as exc:
        return {
                      "mode":           MODE_DEMO,
                      "order_id":       None,
                      "status":         "error",
                      "pair":           candidate["pair"],
                      "direction":      candidate["direction"],
                      "entry":          candidate["entry"],
                      "stop_loss":      candidate["stop_loss"],
                      "take_profit":    candidate["take_profit"],
                      "position_units": candidate["position_units"],
                      "risk_pct":       candidate["risk_pct"],
                      "risk_amount":    candidate["risk_amount"],
                      "filled_at":      datetime.now(timezone.utc).isoformat(),
                      "spread_cost":    None,
                      "slippage":       None,
                      "broker_raw":     None,
                      "error":          str(exc),
                      "note":           "OANDA demo order failed – see error field.",
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
      # Final safety check – abort if live trading somehow enabled
      if settings.enable_live_trading:
                raise RuntimeError("Live trading is locked in the MVP.  Aborting execution.")

    mode = _active_mode()

    if mode == MODE_DEMO:
              return _place_oanda_demo_trade(candidate)

    return _place_paper_trade(candidate)


def get_open_positions_oanda() -> list:
      """Fetch open positions from OANDA demo account. Returns [] on any error."""
      if not (settings.oanda_access_token and settings.oanda_account_id):
                return []
            try:
                      import requests
                      base_url = "https://api-fxpractice.oanda.com"
                      headers  = {"Authorization": f"Bearer {settings.oanda_access_token}"}
                      url = f"{base_url}/v3/accounts/{settings.oanda_account_id}/openPositions"
                      resp = requests.get(url, headers=headers, timeout=10)
                      resp.raise_for_status()
                      return resp.json().get("positions", [])
except Exception:
        return []


def close_position_oanda(instrument: str) -> Dict[str, Any]:
      """Close an open position on OANDA demo. Returns result dict."""
    if settings.enable_live_trading:
              raise RuntimeError("Live trading is locked.")
          try:
                    import requests
                    base_url = "https://api-fxpractice.oanda.com"
                    headers  = {
                        "Authorization": f"Bearer {settings.oanda_access_token}",
                        "Content-Type": "application/json",
                    }
                    url = f"{base_url}/v3/accounts/{settings.oanda_account_id}/positions/{instrument}/close"
                    payload = {"longUnits": "ALL", "shortUnits": "ALL"}
                    resp = requests.put(url, headers=headers, json=payload, timeout=10)
                    resp.raise_for_status()
                    return {"status": "closed", "instrument": instrument, "raw": resp.json()}
except Exception as exc:
        return {"status": "error", "instrument": instrument, "error": str(exc)}
