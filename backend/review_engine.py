"""
review_engine.py – Post-trade review engine for the AI FX Trading Agent.

After each trade closes, this engine:
  1. Analyses the trade against a structured set of review questions (spec §10)
    2. Assigns a quality tag from the approved tag set
      3. Writes a plain-English post-trade review note
        4. Persists the review back into agent_trades

        Spec §10 quality tags:
          good_setup_normal_loss      Rules followed, loss is acceptable.
            good_setup_good_execution   Trade matched plan and was executed well.
              good_setup_poor_execution   Idea was valid but entry/stop/timing was poor.
                poor_setup_lucky_win        Trade won but should not be repeated blindly.
                  chased_entry                Entered after price had already moved too far.
                    against_trend               Setup conflicted with higher-timeframe direction.
                      too_close_to_news           News risk was underestimated.
                        stop_too_tight              Stop did not allow normal market movement.
                          target_too_ambitious        Take-profit target was unrealistic.
                          """

from __future__ import annotations

from typing import Any, Dict

from .agent_db import update_agent_trade_review, log_audit

# ---------------------------------------------------------------------------
# Quality tag set (spec §10)
# ---------------------------------------------------------------------------

QUALITY_TAGS = {
      "good_setup_normal_loss":    "Good setup / normal loss",
      "good_setup_good_execution": "Good setup / good execution",
      "good_setup_poor_execution": "Good setup / poor execution",
      "poor_setup_lucky_win":      "Poor setup / lucky win",
      "chased_entry":              "Chased entry",
      "against_trend":             "Against trend",
      "too_close_to_news":         "Too close to news",
      "stop_too_tight":            "Stop too tight",
      "target_too_ambitious":      "Target too ambitious",
}


# ---------------------------------------------------------------------------
# Tag assignment logic
# ---------------------------------------------------------------------------

def _assign_tag(trade: Dict[str, Any]) -> str:
      """
          Assign a quality tag based on trade outcome and setup metadata.
              Uses heuristics; can be improved as the learning engine matures.
                  """
      result_r    = float(trade.get("result_r") or 0)
      confidence  = int(trade.get("confidence") or 0)
      rr_estimate = float(trade.get("rr_estimate") or 0)
      close_reason = trade.get("close_reason", "")
      setup_type  = trade.get("setup_type", "")
      stop_pips   = float(trade.get("stop_pips") or 20)

    # Winning trades
      if result_r > 0:
                if confidence < 85:
                              return "poor_setup_lucky_win"
                          if rr_estimate >= 2.5 and result_r >= rr_estimate * 0.9:
                                        return "good_setup_good_execution"
                                    if rr_estimate < 2.0:
                                                  return "target_too_ambitious"
                                              return "good_setup_good_execution"

    # Losing trades
      if result_r <= -1.0:
                # Full stop hit
                if stop_pips < 15:
                              return "stop_too_tight"
                          if confidence >= 85 and setup_type != "reversal_at_key_level":
                                        return "good_setup_normal_loss"
                                    if setup_type == "reversal_at_key_level":
                                                  return "against_trend"
                                              return "good_setup_poor_execution"

    # Partial loss (less than 1R)
      if confidence >= 85:
                return "good_setup_normal_loss"

      return "good_setup_poor_execution"


# ---------------------------------------------------------------------------
# Review note generation
# ---------------------------------------------------------------------------

def _generate_review(trade: Dict[str, Any], tag: str) -> str:
      """
          Generate a structured plain-English post-trade review note.
              Answers the spec §10 review questions systematically.
                  """
      pair        = trade.get("pair", "?")
      direction   = trade.get("direction", "?")
      setup_label = trade.get("setup_label", trade.get("setup_type", "?"))
      entry       = trade.get("entry_price", "?")
      stop        = trade.get("stop_loss", "?")
      target      = trade.get("take_profit", "?")
      close_price = trade.get("close_price", "?")
      result_r    = trade.get("result_r", 0) or 0
      confidence  = trade.get("confidence", 0) or 0
      rr_estimate = trade.get("rr_estimate", 0) or 0
      close_reason = trade.get("close_reason", "unknown")
      session     = trade.get("session", "unknown")
      setup_type  = trade.get("setup_type", "")

    tag_label = QUALITY_TAGS.get(tag, tag)
    outcome   = "win" if result_r > 0 else "loss" if result_r < 0 else "breakeven"

    lines = [
              f"POST-TRADE REVIEW — {pair} {direction.upper()} | {setup_label}",
              f"Result: {result_r:+.2f}R ({outcome}) | Closed at {close_price} via {close_reason} | Session: {session}",
              f"Quality tag: {tag_label}",
              "",
              "SETUP VALIDITY:",
    ]

    # Was the setup valid?
    if confidence >= 85:
              lines.append(f"  Setup was valid. Confidence score was {confidence}/100, above the 85% threshold.")
else:
          lines.append(f"  Setup validity is questionable. Confidence score was only {confidence}/100 (below 85 threshold). This should not have been taken.")

    # Entry quality
      lines.append("")
    lines.append("ENTRY QUALITY:")
    if tag in ("chased_entry", "good_setup_poor_execution"):
              lines.append(f"  Entry quality was poor. Entry at {entry} may have been late or too far from the ideal zone.")
else:
          lines.append(f"  Entry at {entry} appears well-timed relative to the setup plan.")

    # Stop loss quality
      lines.append("")
    lines.append("STOP LOSS REVIEW:")
    if tag == "stop_too_tight":
              lines.append(f"  Stop at {stop} was too tight and did not allow normal market movement. Consider widening future stops.")
else:
          lines.append(f"  Stop at {stop} appears logical for this setup type.")

    # Target quality
      lines.append("")
    lines.append("TARGET REVIEW:")
    if tag == "target_too_ambitious":
              lines.append(f"  Target at {target} ({rr_estimate:.1f}R) was ambitious. Price did not reach it.")
else:
          lines.append(f"  Target at {target} ({rr_estimate:.1f}R) was realistic for the setup.")

    # Market condition
      lines.append("")
    lines.append("MARKET CONDITION:")
    if setup_type == "london_pullback_continuation":
              lines.append("  Trade was taken with the trend — the highest-probability setup type in the system.")
elif setup_type == "break_and_retest":
          lines.append("  Break-and-retest setup — validity depends on clean level and strong rejection.")
elif setup_type == "range_breakout":
          lines.append("  Range breakout — higher risk of false breakouts. Monitor this pattern carefully.")
elif setup_type == "reversal_at_key_level":
          lines.append("  Counter-trend reversal — highest risk category. Use only at major levels with strong confirmation.")

    # Confidence accuracy
      lines.append("")
    lines.append("CONFIDENCE ACCURACY:")
    if confidence >= 90 and result_r > 0:
              lines.append(f"  High confidence ({confidence}) matched a positive outcome. Good signal quality.")
elif confidence >= 90 and result_r < 0:
          lines.append(f"  High confidence ({confidence}) did not match the outcome. Monitor this setup type for false signals.")
elif confidence < 88 and result_r > 0:
          lines.append(f"  Lower confidence ({confidence}) still produced a win — possibly lucky or edge case.")
else:
          lines.append(f"  Confidence score {confidence} was consistent with the outcome.")

    # Should this setup be repeated?
      lines.append("")
    lines.append("REPEAT ASSESSMENT:")
    if tag in ("good_setup_normal_loss", "good_setup_good_execution"):
              lines.append("  YES — this setup type should be continued. The loss is within expected variance.")
elif tag == "poor_setup_lucky_win":
          lines.append("  CAUTION — do not repeat blindly. The win was fortunate given the setup quality.")
elif tag in ("chased_entry", "stop_too_tight", "target_too_ambitious"):
          lines.append("  IMPROVE — the setup idea was valid but execution had a specific flaw. Note the improvement.")
elif tag == "against_trend":
          lines.append("  RESTRICT — this setup conflicted with the higher-timeframe trend. Avoid counter-trend setups.")
else:
          lines.append("  REVIEW — more data needed before drawing conclusions about this pattern.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main review function
# ---------------------------------------------------------------------------

def review_closed_trade(trade: Dict[str, Any]) -> Dict[str, Any]:
      """
          Generate and persist a post-trade review for a closed trade.

              Args:
                      trade: A full agent_trade row dict (from get_agent_trade())

                          Returns:
                                  A dict containing the quality_tag and review text.
                                      """
      trade_id = trade.get("id")

    tag    = _assign_tag(trade)
    review = _generate_review(trade, tag)

    if trade_id:
              update_agent_trade_review(trade_id, review, tag)
              log_audit(
                  event_type = "review",
                  decision   = "completed",
                  reason     = f"Post-trade review generated. Tag: {QUALITY_TAGS.get(tag, tag)}",
                  pair       = trade.get("pair", ""),
                  trade_id   = trade_id,
                  details    = {"tag": tag, "result_r": trade.get("result_r")},
              )

    return {
              "trade_id":     trade_id,
              "quality_tag":  tag,
              "tag_label":    QUALITY_TAGS.get(tag, tag),
              "review":       review,
    }


def review_pending_trades() -> list:
      """
          Find all closed trades that have not yet received a review and review them.
              Called periodically by the agent loop.
                  """
      from .agent_db import get_closed_agent_trades

    closed = get_closed_agent_trades(limit=200)
    reviewed = []

    for trade in closed:
              if not trade.get("post_trade_review"):
                            result = review_closed_trade(trade)
                            reviewed.append(result)

          return reviewed
