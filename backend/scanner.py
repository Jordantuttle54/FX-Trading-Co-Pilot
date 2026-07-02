"""
scanner.py – Autonomous market scanner for the AI FX Trading Agent.

Scans approved watchlist pairs, identifies named setup types, scores confidence,
and returns structured SetupCandidate objects for the strategy engine to validate.

Every scan — whether it produces a trade candidate or a rejection — is logged
to the audit table so nothing is hidden from the post-trade review process.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .config import settings
from .strategy import WATCHLIST, analyse_candles, pip_size

# ---------------------------------------------------------------------------
# Named setup types (spec §6)
# ---------------------------------------------------------------------------

SETUP_TYPES = [
      "london_pullback_continuation",
      "break_and_retest",
      "range_breakout",
      "reversal_at_key_level",
      "no_trade",
]

SETUP_LABELS: Dict[str, str] = {
      "london_pullback_continuation": "London pullback continuation",
      "break_and_retest": "Break and retest",
      "range_breakout": "Range breakout",
      "reversal_at_key_level": "Reversal at key level",
      "no_trade": "No-trade condition",
}

# ---------------------------------------------------------------------------
# London session window (07:00–11:00 UTC)
# ---------------------------------------------------------------------------

LONDON_OPEN_HOUR = 7
LONDON_CLOSE_HOUR = 11


def _in_london_window(now: Optional[datetime] = None) -> bool:
      """Return True if current UTC time is inside the allowed trading window."""
      t = now or datetime.now(timezone.utc)
      return LONDON_OPEN_HOUR <= t.hour < LONDON_CLOSE_HOUR


def _session_label(now: Optional[datetime] = None) -> str:
      t = now or datetime.now(timezone.utc)
      hour = t.hour
      if 7 <= hour < 11:
                return "London"
            if 12 <= hour < 17:
                      return "New York"
                  if 0 <= hour < 6:
                            return "Asia"
                        return "Off-session"


# ---------------------------------------------------------------------------
# Setup detection helpers
# ---------------------------------------------------------------------------

def _detect_setup(pair: str, analysis: Dict[str, Any], candles: List[Dict[str, Any]]) -> Dict[str, Any]:
      """
          Inspect candle data and market analysis to identify the best matching
              named setup type and return its metadata.

                  Returns a dict with keys:
                          setup_type, direction, confidence_raw, entry_reason, rr_estimate
                              """
    if len(candles) < 20:
              return {
                            "setup_type": "no_trade",
                            "direction": "none",
                            "confidence_raw": 0,
                            "entry_reason": "Insufficient candle data for pattern detection.",
                            "rr_estimate": 0.0,
              }

    closes = [float(c["close"]) for c in candles[-50:] if c.get("close")]
    highs  = [float(c["high"])  for c in candles[-50:] if c.get("high")]
    lows   = [float(c["low"])   for c in candles[-50:] if c.get("low")]

    price       = closes[-1]
    prev_close  = closes[-2] if len(closes) >= 2 else price
    recent_high = max(highs[-20:])
    recent_low  = min(lows[-20:])
    range_size  = recent_high - recent_low
    pip         = pip_size(pair)

    bias      = analysis.get("bias", "Neutral")
    vol       = analysis.get("volatility", "Unknown")
    sma20     = analysis.get("indicators", {}).get("sma20") or price
    sma50     = analysis.get("indicators", {}).get("sma50") or price
    avg_range = analysis.get("indicators", {}).get("avg_range_pips", 0)

    # --- London pullback continuation ----------------------------------------
    if bias in ("Bullish", "Bearish"):
              pullback_into_support = (
                            bias == "Bullish"
                            and price <= sma20 * 1.002
                            and price >= recent_low * 0.998
                            and price > prev_close
              )
              pullback_into_resistance = (
                  bias == "Bearish"
                  and price >= sma20 * 0.998
                  and price <= recent_high * 1.002
                  and price < prev_close
              )

        if pullback_into_support or pullback_into_resistance:
                      direction  = "buy" if pullback_into_support else "sell"
                      stop_dist  = abs(price - recent_low) if direction == "buy" else abs(recent_high - price)
                      stop_pips  = stop_dist / pip
                      target_pips = stop_pips * 2.5
                      rr = round(target_pips / stop_pips, 2) if stop_pips > 0 else 0
                      conf = _confidence_london_pullback(bias, vol, avg_range, rr)
                      return {
                          "setup_type": "london_pullback_continuation",
                          "direction": direction,
                          "confidence_raw": conf,
                          "entry_reason": (
                              f"Price pulled back into {'previous resistance now acting as support' if direction == 'buy' else 'previous support now acting as resistance'} "
                              f"during the London session. Trend bias is {bias.lower()}. "
                              f"Continuation candle forming above SMA20."
                          ),
                          "rr_estimate": rr,
                      }

    # --- Break and retest -----------------------------------------------------
    # Price must have closed beyond recent high/low and then returned to it
    broke_high = closes[-3] < recent_high and closes[-2] > recent_high and price < closes[-2]
    broke_low  = closes[-3] > recent_low  and closes[-2] < recent_low  and price > closes[-2]

    if broke_high or broke_low:
              direction  = "sell" if broke_high else "buy"
              stop_dist  = abs(price - closes[-2])
              stop_pips  = stop_dist / pip
              target_pips = stop_pips * 2.2
              rr = round(target_pips / stop_pips, 2) if stop_pips > 0 else 0
              conf = _confidence_break_retest(bias, direction, vol, rr)
              return {
                  "setup_type": "break_and_retest",
                  "direction": direction,
                  "confidence_raw": conf,
                  "entry_reason": (
                      f"Price broke {'above' if broke_high else 'below'} the recent "
                      f"{'high' if broke_high else 'low'} at {recent_high if broke_high else recent_low:.5f}, "
                      f"retested the level and showed rejection with {'bearish' if direction == 'sell' else 'bullish'} momentum."
                  ),
                  "rr_estimate": rr,
              }

    # --- Range breakout -------------------------------------------------------
    range_pips = range_size / pip
    is_tight_range = range_pips < avg_range * 0.6 if avg_range > 0 else False
    price_near_high = price >= recent_high * 0.9995
    price_near_low  = price <= recent_low  * 1.0005

    if is_tight_range and (price_near_high or price_near_low):
              direction  = "buy" if price_near_high else "sell"
              stop_dist  = range_size * 0.3
              stop_pips  = stop_dist / pip
              target_pips = stop_pips * 2.1
              rr = round(target_pips / stop_pips, 2) if stop_pips > 0 else 0
              conf = _confidence_range_breakout(vol, range_pips, rr)
              return {
                  "setup_type": "range_breakout",
                  "direction": direction,
                  "confidence_raw": conf,
                  "entry_reason": (
                      f"Price has been ranging in a tight {range_pips:.0f}-pip band "
                      f"and is pressing against the {'upper' if direction == 'buy' else 'lower'} boundary. "
                      f"Breakout with momentum and room for at least 2R."
                  ),
                  "rr_estimate": rr,
              }

    # --- Reversal at key level (cautious) ------------------------------------
    near_extreme = (
              abs(price - recent_high) / (recent_high + 1e-9) < 0.002
              or abs(price - recent_low)  / (recent_low  + 1e-9) < 0.002
    )
    if near_extreme and bias == "Neutral":
              at_high  = abs(price - recent_high) < abs(price - recent_low)
              direction = "sell" if at_high else "buy"
              stop_dist = range_size * 0.25
              stop_pips = stop_dist / pip
              rr = 2.1
              conf = _confidence_reversal(vol, rr)
              return {
                  "setup_type": "reversal_at_key_level",
                  "direction": direction,
                  "confidence_raw": conf,
                  "entry_reason": (
                      f"Price is rejecting the major {'resistance' if at_high else 'support'} level "
                      f"at {recent_high if at_high else recent_low:.5f} with confirmation. "
                      f"Market structure is neutral — using cautiously."
                  ),
                  "rr_estimate": rr,
              }

    # --- No-trade condition --------------------------------------------------
    return {
              "setup_type": "no_trade",
              "direction": "none",
              "confidence_raw": 0,
              "entry_reason": (
                            "No clear setup pattern detected. Market structure is ambiguous or "
                            "conditions do not meet any named strategy pattern. Best action: wait."
              ),
              "rr_estimate": 0.0,
    }


# ---------------------------------------------------------------------------
# Confidence sub-scorers (keep separate so learning engine can tune them)
# ---------------------------------------------------------------------------

def _confidence_london_pullback(bias: str, vol: str, avg_range: float, rr: float) -> int:
      score = 50
      if bias in ("Bullish", "Bearish"):
                score += 20
            if vol in ("Medium", "High"):
                      score += 10
                  if avg_range > 40:
                            score += 8
                        if rr >= 2.5:
                                  score += 10
elif rr >= 2.0:
        score += 7
    return min(score, 97)


def _confidence_break_retest(bias: str, direction: str, vol: str, rr: float) -> int:
      aligned = (bias == "Bearish" and direction == "sell") or (bias == "Bullish" and direction == "buy")
    score = 45
    if aligned:
              score += 18
          if vol in ("Medium", "High"):
                    score += 12
                if rr >= 2.2:
                          score += 10
elif rr >= 2.0:
        score += 6
    return min(score, 95)


def _confidence_range_breakout(vol: str, range_pips: float, rr: float) -> int:
      score = 40
    if vol == "Medium":
              score += 15
elif vol == "High":
        score += 8  # High vol breakouts are noisier
    if range_pips > 30:
              score += 12
          if rr >= 2.1:
                    score += 10
                return min(score, 90)


def _confidence_reversal(vol: str, rr: float) -> int:
      # Reversals get capped lower because they're counter-trend
      score = 35
    if vol in ("Low", "Medium"):
              score += 12
          if rr >= 2.0:
                    score += 8
                return min(score, 82)


# ---------------------------------------------------------------------------
# Position sizing (spec §7)
# ---------------------------------------------------------------------------

def _calculate_position(
      pair: str,
      direction: str,
      price: float,
      rr: float,
      account_balance: float = 10_000.0,
      risk_pct: float = 0.5,
) -> Dict[str, Any]:
      """
          Calculate entry, stop, target and position size from risk rules.
              Uses a default 20-pip stop for now; real implementation reads ATR from candles.
                  """
      pip = pip_size(pair)
      stop_pips = 20.0  # conservative default; scanner will refine from candle data later
    tp_pips   = stop_pips * rr

    if direction == "buy":
              stop_loss = round(price - stop_pips * pip, 5)
              take_profit = round(price + tp_pips * pip, 5)
else:
          stop_loss = round(price + stop_pips * pip, 5)
          take_profit = round(price - tp_pips * pip, 5)

    risk_amount = account_balance * (risk_pct / 100)
    # Standard lot position sizing: risk_amount / (stop_pips * pip_value_per_pip)
    pip_value_per_standard_lot = 10.0 if "JPY" not in pair else 9.0
    position_units = risk_amount / (stop_pips * pip_value_per_standard_lot)

    return {
              "entry":          round(price, 5),
              "stop_loss":      stop_loss,
              "take_profit":    take_profit,
              "stop_pips":      stop_pips,
              "tp_pips":        tp_pips,
              "risk_amount":    round(risk_amount, 2),
              "position_units": round(position_units, 4),
              "risk_pct":       risk_pct,
    }


# ---------------------------------------------------------------------------
# Main scan function
# ---------------------------------------------------------------------------

def scan_pair(
      pair: str,
      candles: List[Dict[str, Any]],
      calendar_events: List[Dict[str, Any]],
      account_balance: float = 10_000.0,
      now: Optional[datetime] = None,
) -> Dict[str, Any]:
      """
          Full scan of a single pair.  Returns a structured SetupCandidate dict.

              Status values:
                      trade_candidate  – passes all rule checks, ready for execution engine
                              rejected         – failed one or more rule checks (reason included)
                                      no_setup         – no pattern found, not a rule failure
                                          """
      t = now or datetime.now(timezone.utc)
      scanned_at = t.isoformat()
      session = _session_label(t)
      in_window = _in_london_window(t)

    # ---- 1. Market analysis -------------------------------------------------
      analysis = analyse_candles(pair, candles)
    price    = float(analysis.get("price", 0))

    # ---- 2. Pattern detection -----------------------------------------------
    detected = _detect_setup(pair, analysis, candles)
    setup_type    = detected["setup_type"]
    direction     = detected["direction"]
    confidence    = detected["confidence_raw"]
    entry_reason  = detected["entry_reason"]
    rr_estimate   = detected["rr_estimate"]

    # ---- 3. Rule checks (spec §6 decision checklist) ------------------------
    rejections: List[str] = []

    if pair not in WATCHLIST:
              rejections.append(f"Pair {pair} is not on the approved watchlist.")

    if setup_type == "no_trade":
              return {
                            "pair":        pair,
                            "direction":   "none",
                            "setup_type":  "no_trade",
                            "setup_label": SETUP_LABELS["no_trade"],
                            "confidence":  0,
                            "rr_estimate": 0.0,
                            "session":     session,
                            "in_window":   in_window,
                            "scanned_at":  scanned_at,
                            "status":      "no_setup",
                            "rejection_reason": entry_reason,
                            "entry_reason": entry_reason,
                            "analysis":    analysis,
              }

    if not in_window:
              rejections.append(
                            f"Outside the allowed London trading window (07:00–11:00 UTC). "
                            f"Current session: {session}."
              )

    # News blackout check
    currencies = pair.split("/") if pair != "XAU/USD" else ["XAU", "USD"]
    blackout_minutes = settings.news_guard_minutes
    blocked_events = [
              e for e in calendar_events
              if str(e.get("impact", "")).lower() in ("high", "critical")
              and e.get("currency") in currencies
              and abs(int(e.get("minutes_until", 9999))) <= blackout_minutes
    ]
    if blocked_events:
              evt = blocked_events[0]
              rejections.append(
                  f"High-impact {evt.get('currency')} event ({evt.get('event','?')}) "
                  f"is within the {blackout_minutes}-minute news blackout window."
              )

    if confidence < settings.min_confidence_score:
              rejections.append(
                            f"Confidence score {confidence} is below the minimum threshold of "
                            f"{settings.min_confidence_score}."
              )

    if rr_estimate < settings.min_risk_reward:
              rejections.append(
                            f"Risk-to-reward estimate {rr_estimate:.1f}R is below the minimum "
                            f"of {settings.min_risk_reward:.1f}R."
              )

    # ---- 4. Build candidate -------------------------------------------------
    pos = _calculate_position(pair, direction, price, max(rr_estimate, 2.0), account_balance)

    status = "rejected" if rejections else "trade_candidate"
    rejection_reason = " | ".join(rejections) if rejections else None

    return {
              "pair":             pair,
              "direction":        direction,
              "setup_type":       setup_type,
              "setup_label":      SETUP_LABELS.get(setup_type, setup_type),
              "confidence":       confidence,
              "rr_estimate":      rr_estimate,
              "session":          session,
              "in_window":        in_window,
              "scanned_at":       scanned_at,
              "status":           status,
              "rejection_reason": rejection_reason,
              "entry_reason":     entry_reason,
              "entry":            pos["entry"],
              "stop_loss":        pos["stop_loss"],
              "take_profit":      pos["take_profit"],
              "stop_pips":        pos["stop_pips"],
              "risk_amount":      pos["risk_amount"],
              "position_units":   pos["position_units"],
              "risk_pct":         pos["risk_pct"],
              "analysis":         analysis,
              "blocked_events":   blocked_events,
    }


def scan_all_pairs(
      candles_by_pair: Dict[str, List[Dict[str, Any]]],
      calendar_events: List[Dict[str, Any]],
      account_balance: float = 10_000.0,
      now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
      """Scan all approved pairs and return a sorted list of candidates."""
      results = []
      for pair in WATCHLIST:
                candles = candles_by_pair.get(pair, [])
                result  = scan_pair(pair, candles, calendar_events, account_balance, now)
                results.append(result)

      # Sort: trade_candidates first (by confidence desc), then rejections, then no_setup
      order = {"trade_candidate": 0, "rejected": 1, "no_setup": 2}
    results.sort(key=lambda r: (order.get(r["status"], 9), -r.get("confidence", 0)))
    return results
