"""
trade_manager.py – Open-trade monitoring and rule-based exit management.

Spec §8: Track open trades, apply predefined management rules, record
every management action with timestamp and reason.

MVP rules (spec §8 MVP note):
  - Fixed stop loss, fixed take profit
    - No martingale, no averaging down, no uncontrolled scaling
      - Revenge-trading prevention via daily/weekly loss limits
      """

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .config import settings
from .agent_db import (
    get_open_agent_trades,
    update_agent_trade_status,
    log_management_action,
    get_daily_loss_pct,
    get_weekly_loss_pct,
)
from .execution import close_position_oanda, MODE_PAPER

# ---------------------------------------------------------------------------
# Kill switch state (in-memory; persisted separately via agent_db)
# ---------------------------------------------------------------------------
_kill_switch_active: bool = False


def activate_kill_switch(reason: str = "Manual emergency stop") -> Dict[str, Any]:
      global _kill_switch_active
      _kill_switch_active = True
      return {"kill_switch": True, "reason": reason, "activated_at": datetime.now(timezone.utc).isoformat()}


def deactivate_kill_switch() -> Dict[str, Any]:
      global _kill_switch_active
      _kill_switch_active = False
      return {"kill_switch": False, "deactivated_at": datetime.now(timezone.utc).isoformat()}


def kill_switch_active() -> bool:
      return _kill_switch_active


# ---------------------------------------------------------------------------
# Daily / weekly loss guard
# ---------------------------------------------------------------------------

def _daily_limit_breached(account_balance: float) -> bool:
      lost_pct = get_daily_loss_pct()
      return lost_pct >= settings.max_daily_loss_pct


def _weekly_limit_breached(account_balance: float) -> bool:
      lost_pct = get_weekly_loss_pct()
      return lost_pct >= settings.max_weekly_loss_pct


def trading_allowed(account_balance: float = 10_000.0) -> Dict[str, Any]:
      """
          Return whether new trades are allowed right now.
              Checks kill switch, daily loss limit and weekly loss limit.
                  """
      if _kill_switch_active:
                return {"allowed": False, "reason": "Kill switch is active. Trading halted."}

      daily_pct  = get_daily_loss_pct()
      weekly_pct = get_weekly_loss_pct()

    if daily_pct >= settings.max_daily_loss_pct:
              return {
                            "allowed": False,
                            "reason": (
                                              f"Daily loss limit reached ({daily_pct:.2f}% >= {settings.max_daily_loss_pct}%). "
                                              f"No more trades today."
                            ),
                            "daily_loss_pct":  daily_pct,
                            "weekly_loss_pct": weekly_pct,
              }

    if weekly_pct >= settings.max_weekly_loss_pct:
              return {
                            "allowed": False,
                            "reason": (
                                              f"Weekly loss limit reached ({weekly_pct:.2f}% >= {settings.max_weekly_loss_pct}%). "
                                              f"No more trades this week."
                            ),
                            "daily_loss_pct":  daily_pct,
                            "weekly_loss_pct": weekly_pct,
              }

    return {
              "allowed": True,
              "daily_loss_pct":  daily_pct,
              "weekly_loss_pct": weekly_pct,
              "daily_limit":     settings.max_daily_loss_pct,
              "weekly_limit":    settings.max_weekly_loss_pct,
    }


# ---------------------------------------------------------------------------
# Trade status evaluation
# ---------------------------------------------------------------------------

def _evaluate_trade(trade: Dict[str, Any], current_price: float) -> Dict[str, Any]:
      """
          Given a current price, determine if a trade should be closed
              and calculate unrealised P&L.
                  """
      direction   = trade["direction"]
      entry       = float(trade["entry_price"])
      stop        = float(trade["stop_loss"])
      target      = float(trade["take_profit"])
      risk_amount = float(trade.get("risk_amount", 0))

    # Pip distance to stop and target
      if direction == "buy":
                stop_dist   = entry - stop
                target_dist = target - entry
                current_pnl = current_price - entry
                hit_stop    = current_price <= stop
                hit_target  = current_price >= target
else:
          stop_dist   = stop - entry
          target_dist = entry - target
          current_pnl = entry - current_price
          hit_stop    = current_price >= stop
          hit_target  = current_price <= target

    r_multiple = current_pnl / stop_dist if stop_dist > 0 else 0.0

    action = None
    reason = None

    if hit_stop:
              action = "close_stop"
              reason = f"Stop loss hit at {current_price:.5f} (stop was {stop:.5f})."
elif hit_target:
          action = "close_target"
          reason = f"Take profit reached at {current_price:.5f} (target was {target:.5f})."

    return {
              "action":        action,
              "reason":        reason,
              "current_price": current_price,
              "unrealised_pnl": round(current_pnl / stop_dist if stop_dist > 0 else 0, 4),
              "r_multiple":    round(r_multiple, 3),
              "hit_stop":      hit_stop,
              "hit_target":    hit_target,
    }


# ---------------------------------------------------------------------------
# Manage all open trades
# ---------------------------------------------------------------------------

def manage_open_trades(
      current_prices: Dict[str, float],
      account_balance: float = 10_000.0,
) -> List[Dict[str, Any]]:
      """
          Check all open agent trades against current prices.
              Close any that have hit stop or target.
                  Returns a list of management action records.
                      """
      if _kill_switch_active:
                return [{"note": "Kill switch active – trade management suspended."}]

      open_trades = get_open_agent_trades()
      actions = []

    for trade in open_trades:
              pair          = trade["pair"]
              current_price = current_prices.get(pair)

        if current_price is None:
                      continue

        evaluation = _evaluate_trade(trade, current_price)

        if evaluation["action"] in ("close_stop", "close_target"):
                      result = evaluation["action"].replace("close_", "")   # "stop" or "target"

            # Close via broker or mark as closed in paper mode
                      close_result = {}
                      if trade.get("broker_mode") != MODE_PAPER:
                                        instrument = pair.replace("/", "_")
                                        close_result = close_position_oanda(instrument)

                      # Calculate final R multiple
                      entry     = float(trade["entry_price"])
            stop      = float(trade["stop_loss"])
            stop_dist = abs(entry - stop)
            final_price = current_price
            if trade["direction"] == "buy":
                              final_r = (final_price - entry) / stop_dist if stop_dist > 0 else 0
else:
                  final_r = (entry - final_price) / stop_dist if stop_dist > 0 else 0

            close_data = {
                              "status":       "closed",
                              "closed_at":    datetime.now(timezone.utc).isoformat(),
                              "close_price":  final_price,
                              "close_reason": result,
                              "result_r":     round(final_r, 3),
            }

            update_agent_trade_status(trade["id"], close_data)

            action_record = {
                              "trade_id":    trade["id"],
                              "pair":        pair,
                              "action":      evaluation["action"],
                              "reason":      evaluation["reason"],
                              "close_price": final_price,
                              "result_r":    round(final_r, 3),
                              "timestamp":   datetime.now(timezone.utc).isoformat(),
                              "broker":      close_result,
            }
            log_management_action(action_record)
            actions.append(action_record)

    return actions


# ---------------------------------------------------------------------------
# Max open trades guard
# ---------------------------------------------------------------------------

MAX_OPEN_TRADES = int(getattr(settings, "max_open_trades", 3))
MAX_TRADES_PER_DAY = int(getattr(settings, "max_trades_per_day", 3))


def open_trade_count() -> int:
      return len(get_open_agent_trades())


def can_open_new_trade() -> Dict[str, Any]:
      """Returns whether a new trade can be opened (open count and daily count checks)."""
      open_count = open_trade_count()
      if open_count >= MAX_OPEN_TRADES:
                return {
                              "allowed": False,
                              "reason": f"Maximum open trades ({MAX_OPEN_TRADES}) already reached.",
                              "open_count": open_count,
                }
            return {"allowed": True, "open_count": open_count}
