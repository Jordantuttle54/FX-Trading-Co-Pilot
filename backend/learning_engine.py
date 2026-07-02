"""
learning_engine.py – Learning and optimisation engine for the AI FX Trading Agent.

Spec §11: Analyses trade history in evidence batches, identifies patterns,
and produces controlled rule-improvement proposals.

Key principles (spec §11):
  - Do NOT optimise after one or two trades
    - Start analysing after at least 50 trades
      - Group performance by pair, setup type, session, confidence and news context
        - Propose controlled rule changes — do not apply them automatically
          - Keep full version history of strategy rules
            - Optimise for expectancy, R multiple, profit factor and drawdown
                NOT just win rate
                """

from __future__ import annotations

import statistics
from typing import Any, Dict, List, Optional

from .agent_db import get_closed_agent_trades, save_strategy_version, get_strategy_versions

# ---------------------------------------------------------------------------
# Minimum sample size before any analysis is run (spec §11)
# ---------------------------------------------------------------------------
MIN_SAMPLE_SIZE = 50


# ---------------------------------------------------------------------------
# Performance breakdown helpers
# ---------------------------------------------------------------------------

def _r_stats(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
      """Compute core performance stats for a list of trades."""
      r_values = [float(t.get("result_r") or 0) for t in trades]
      if not r_values:
                return {
                              "count":         0,
                              "win_rate":      0.0,
                              "avg_r":         0.0,
                              "expectancy":    0.0,
                              "profit_factor": 0.0,
                              "total_r":       0.0,
                              "max_loss_r":    0.0,
                }

      wins   = [r for r in r_values if r > 0]
      losses = [r for r in r_values if r <= 0]

    win_rate      = len(wins) / len(r_values) if r_values else 0
    avg_win       = statistics.mean(wins)   if wins   else 0
    avg_loss      = statistics.mean(losses) if losses else 0
    expectancy    = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)
    gross_profit  = sum(wins)
    gross_loss    = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    return {
              "count":         len(r_values),
              "win_rate":      round(win_rate * 100, 1),
              "avg_r":         round(statistics.mean(r_values), 3),
              "expectancy":    round(expectancy, 3),
              "profit_factor": round(profit_factor, 2),
              "total_r":       round(sum(r_values), 2),
              "max_loss_r":    round(min(r_values), 3) if r_values else 0,
              "avg_win_r":     round(avg_win, 3),
              "avg_loss_r":    round(avg_loss, 3),
    }


def _group_by(trades: List[Dict[str, Any]], field: str) -> Dict[str, List[Dict[str, Any]]]:
      groups: Dict[str, List] = {}
      for t in trades:
                key = str(t.get(field, "unknown") or "unknown")
                groups.setdefault(key, []).append(t)
            return groups


def _confidence_band(confidence: int) -> str:
      if confidence >= 95:
                return "95-100"
            if confidence >= 90:
                      return "90-94"
                  if confidence >= 87:
                            return "87-89"
                        return "85-86"


# ---------------------------------------------------------------------------
# Main performance report
# ---------------------------------------------------------------------------

def generate_performance_report(trades: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
      """
          Generate a full performance report broken down by pair, setup type,
              session, confidence band, and quality tag.

                  Returns a structured report dict suitable for the dashboard and
                      learning engine proposals.
                          """
    if trades is None:
              trades = get_closed_agent_trades(limit=1000)

    closed = [t for t in trades if t.get("status") == "closed" and t.get("result_r") is not None]

    if len(closed) < 5:
              return {
                            "status":  "insufficient_data",
                            "message": f"Only {len(closed)} closed trades available. Need at least 5 for any analysis, {MIN_SAMPLE_SIZE} for optimisation.",
                            "count":   len(closed),
              }

    # Overall stats
    overall = _r_stats(closed)

    # By pair
    by_pair = {
              pair: _r_stats(group)
              for pair, group in _group_by(closed, "pair").items()
    }

    # By setup type
    by_setup = {
              setup: _r_stats(group)
              for setup, group in _group_by(closed, "setup_type").items()
    }

    # By session
    by_session = {
              session: _r_stats(group)
              for session, group in _group_by(closed, "session").items()
    }

    # By confidence band
    for t in closed:
              t["_conf_band"] = _confidence_band(int(t.get("confidence") or 0))
          by_confidence = {
                    band: _r_stats(group)
                    for band, group in _group_by(closed, "_conf_band").items()
          }

    # By quality tag
    by_tag = {
              tag: _r_stats(group)
              for tag, group in _group_by(closed, "quality_tag").items()
    }

    # Max drawdown (sequential R curve)
    r_curve = [float(t.get("result_r") or 0) for t in sorted(closed, key=lambda x: x.get("created_at", ""))]
    peak = 0.0
    trough = 0.0
    running = 0.0
    max_drawdown = 0.0
    for r in r_curve:
              running += r
              if running > peak:
                            peak = running
                        dd = peak - running
        if dd > max_drawdown:
                      max_drawdown = dd

    return {
              "status":         "ok",
              "count":          len(closed),
              "overall":        overall,
              "max_drawdown_r": round(max_drawdown, 2),
              "by_pair":        by_pair,
              "by_setup":       by_setup,
              "by_session":     by_session,
              "by_confidence":  by_confidence,
              "by_tag":         by_tag,
              "ready_for_optimisation": len(closed) >= MIN_SAMPLE_SIZE,
    }


# ---------------------------------------------------------------------------
# Rule improvement proposals
# ---------------------------------------------------------------------------

def generate_optimisation_proposals(report: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
      """
          Analyse the performance report and produce controlled rule-improvement
              proposals.  Does NOT apply changes automatically — proposals must be
                  reviewed and approved before activation.

                      Requires at least MIN_SAMPLE_SIZE closed trades (spec §11).
                          """
    if report is None:
              report = generate_performance_report()

    if report.get("status") != "ok":
              return [{"type": "info", "message": report.get("message", "Insufficient data.")}]

    if not report.get("ready_for_optimisation"):
              remaining = MIN_SAMPLE_SIZE - report["count"]
        return [{
                      "type":    "info",
                      "message": f"Need {remaining} more closed trades before optimisation proposals are generated. "
                                 f"Current sample: {report['count']} trades.",
        }]

    proposals = []

    # --- Pair-level proposals -----------------------------------------------
    for pair, stats in report["by_pair"].items():
              if stats["count"] < 10:
                            continue  # Too few trades for pair-level conclusions

        if stats["expectancy"] < -0.2 and stats["count"] >= 15:
                      proposals.append({
                                        "type":        "restrict_pair",
                                        "pair":        pair,
                                        "observation": f"{pair} has negative expectancy of {stats['expectancy']:.3f}R over {stats['count']} trades.",
                                        "suggestion":  f"Consider blocking {pair} setups temporarily or raising its confidence threshold by 3-5 points.",
                                        "evidence":    stats,
                                        "auto_apply":  False,
                      })

        if stats["expectancy"] > 0.3 and stats["win_rate"] > 55 and stats["count"] >= 15:
                      proposals.append({
                                        "type":        "prioritise_pair",
                                        "pair":        pair,
                                        "observation": f"{pair} has strong positive expectancy of {stats['expectancy']:.3f}R ({stats['win_rate']:.0f}% WR) over {stats['count']} trades.",
                                        "suggestion":  f"Prioritise {pair} setups during its strongest session.",
                                        "evidence":    stats,
                                        "auto_apply":  False,
                      })

    # --- Setup type proposals -----------------------------------------------
    for setup, stats in report["by_setup"].items():
              if stats["count"] < 10:
                            continue

        if stats["expectancy"] < -0.15 and stats["count"] >= 12:
                      proposals.append({
                                        "type":        "restrict_setup",
                                        "setup_type":  setup,
                                        "observation": f"Setup '{setup}' has negative expectancy of {stats['expectancy']:.3f}R over {stats['count']} trades.",
                                        "suggestion":  f"Restrict '{setup}' or increase its minimum confidence to 90%.",
                                        "evidence":    stats,
                                        "auto_apply":  False,
                      })

    # --- Confidence band proposals ------------------------------------------
    for band, stats in report["by_confidence"].items():
              if stats["count"] < 10:
                            continue
                        if stats["expectancy"] < 0 and band in ("85-86", "87-89"):
                                      proposals.append({
                                                        "type":        "raise_confidence_threshold",
                                                        "band":        band,
                                                        "observation": f"Trades with confidence {band}% have negative expectancy ({stats['expectancy']:.3f}R) over {stats['count']} trades.",
                                                        "suggestion":  f"Raise minimum confidence threshold from 85% to 90% and monitor results.",
                                                        "evidence":    stats,
                                                        "auto_apply":  False,
                                      })

    # --- News blackout proposals --------------------------------------------
    too_close = report["by_tag"].get("too_close_to_news", {})
    if too_close.get("count", 0) >= 5 and (too_close.get("expectancy", 0) or 0) < -0.1:
              proposals.append({
                  "type":        "extend_news_blackout",
                  "observation": f"{too_close['count']} trades tagged 'too_close_to_news' have negative expectancy ({too_close.get('expectancy', 0):.3f}R).",
                  "suggestion":  "Extend news blackout window from 30 to 60 minutes for high-impact events.",
                  "evidence":    too_close,
                  "auto_apply":  False,
    })

    # --- Overall expectancy warning -----------------------------------------
    overall = report["overall"]
    if overall["expectancy"] < 0 and report["count"] >= MIN_SAMPLE_SIZE:
              proposals.append({
                  "type":        "system_warning",
                  "observation": f"Overall system expectancy is negative ({overall['expectancy']:.3f}R) after {report['count']} trades.",
                  "suggestion":  "Pause new trades. Conduct full review of setup types, session timing, and entry quality before continuing.",
                  "evidence":    overall,
                  "auto_apply":  False,
                  "priority":    "HIGH",
    })

    if not proposals:
              proposals.append({
                  "type":    "info",
                  "message": f"No negative patterns identified in {report['count']} closed trades. System is performing within expected parameters. Continue collecting data.",
    })

    return proposals


# ---------------------------------------------------------------------------
# Save proposed rule changes as a strategy version
# ---------------------------------------------------------------------------

def save_proposal_as_version(
      proposals: List[Dict[str, Any]],
      version_tag: str = "auto",
      description: str = "",
) -> int:
      """
          Persist a set of optimisation proposals as a strategy_version record.
              The version is marked as NOT approved and NOT active by default.
                  A human must review and approve it via the dashboard.
                      """
    from datetime import date
    if version_tag == "auto":
              version_tag = f"v-proposal-{date.today().isoformat()}"

    rules = {
              "proposals": proposals,
              "generated_at": str(date.today()),
              "approved": False,
              "note": description or "Auto-generated optimisation proposal. Review required before activation.",
    }

    return save_strategy_version(
              version     = version_tag,
              description = description or f"Optimisation proposal ({len(proposals)} suggestions)",
              rules       = rules,
    )
