from typing import List, Dict, Any
import statistics
from .config import settings

WATCHLIST = ["GBP/USD", "EUR/USD", "USD/JPY", "EUR/GBP", "GBP/JPY", "XAU/USD"]

def pip_size(pair: str) -> float:
    return 0.01 if "JPY" in pair else 0.0001

def sma(values: List[float], period: int):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period

def analyse_candles(pair: str, candles: List[Dict[str, Any]]) -> Dict[str, Any]:
    closes = [float(c["close"]) for c in candles if c.get("close") is not None]
    highs = [float(c["high"]) for c in candles if c.get("high") is not None]
    lows = [float(c["low"]) for c in candles if c.get("low") is not None]

    if len(closes) < 10:
        return {
            "pair": pair,
            "bias": "Neutral",
            "trend": "Insufficient data",
            "zone": "N/A",
            "volatility": "Unknown",
            "note": "Need more candles for analysis.",
            "indicators": {},
        }

    s20 = sma(closes, min(20, len(closes)))
    s50 = sma(closes, min(50, len(closes)))
    price = closes[-1]

    recent_high = max(highs[-20:]) if highs else price
    recent_low = min(lows[-20:]) if lows else price

    ranges = [abs(h - l) for h, l in zip(highs[-20:], lows[-20:])]
    avg_range = statistics.mean(ranges) if ranges else 0
    avg_range_pips = avg_range / pip_size(pair)

    if s20 and s50 and price > s20 > s50:
        bias = "Bullish"
        trend = "Price above 20/50 SMA"
        note = "Trend-following long setups may be higher quality after pullbacks."
    elif s20 and s50 and price < s20 < s50:
        bias = "Bearish"
        trend = "Price below 20/50 SMA"
        note = "Trend-following short setups may be higher quality after pullbacks."
    else:
        bias = "Neutral"
        trend = "Mixed or ranging"
        note = "Wait for clearer structure or defined range edges."

    if avg_range_pips > 120:
        vol = "Very High"
    elif avg_range_pips > 70:
        vol = "High"
    elif avg_range_pips > 35:
        vol = "Medium"
    else:
        vol = "Low"

    precision = 3 if "JPY" in pair else 5
    return {
        "pair": pair,
        "bias": bias,
        "trend": trend,
        "zone": f"{recent_low:.{precision}f} support / {recent_high:.{precision}f} resistance",
        "volatility": vol,
        "note": note,
        "price": price,
        "indicators": {
            "sma20": s20,
            "sma50": s50,
            "recent_high": recent_high,
            "recent_low": recent_low,
            "avg_range_pips": avg_range_pips,
        },
    }

def score_setup(pair_analysis: Dict[str, Any], request: Dict[str, Any], calendar_events: List[Dict[str, Any]]) -> Dict[str, Any]:
    pair = request["pair"]
    direction = request["direction"]
    rr = float(request.get("risk_reward", 0))
    checklist = request.get("checklist", {})

    bias = pair_analysis.get("bias", "Neutral")
    volatility = pair_analysis.get("volatility", "Unknown")
    trend_ok = (direction == "Long" and bias == "Bullish") or (direction == "Short" and bias == "Bearish")

    currencies = pair.split("/")
    if pair == "XAU/USD":
        currencies = ["XAU", "USD"]

    linked_high_news = [
        e for e in calendar_events
        if str(e.get("impact", "")).lower() == "high"
        and (e.get("currency") in currencies or (pair == "XAU/USD" and e.get("currency") == "USD"))
    ]

    min_conf = int(settings.min_confidence_score)

    components = []
    def add_component(name: str, points: int, max_points: int, passed: bool, note: str):
        components.append({
            "name": name,
            "points": int(points),
            "max_points": int(max_points),
            "passed": bool(passed),
            "note": note,
        })

    # 100-point conservative confidence model.
    trend_points = 25 if trend_ok and checklist.get("trend_alignment", False) else 12 if trend_ok else 0
    add_component(
        "Trend alignment",
        trend_points,
        25,
        trend_points >= 25,
        "Direction agrees with technical bias and higher-timeframe trend box is ticked." if trend_points >= 25 else "Trend confirmation is not strong enough."
    )

    rr_points = 15 if rr >= settings.min_risk_reward else max(0, int((rr / settings.min_risk_reward) * 15)) if settings.min_risk_reward else 0
    add_component(
        "Minimum risk/reward",
        rr_points,
        15,
        rr >= settings.min_risk_reward,
        f"Risk/reward is {rr:.2f}; minimum is {settings.min_risk_reward:.2f}."
    )

    zone_points = 15 if checklist.get("planned_zone", False) else 0
    add_component("Planned level / zone", zone_points, 15, bool(zone_points), "Entry is at a planned level." if zone_points else "No planned level confirmed.")

    stop_points = 15 if checklist.get("stop_defined", False) else 0
    add_component("Stop-loss defined", stop_points, 15, bool(stop_points), "Stop-loss is defined before entry." if stop_points else "No defined stop-loss.")

    emotion_points = 10 if checklist.get("emotional_control", False) else 0
    add_component("Emotional control", emotion_points, 10, bool(emotion_points), "No revenge/FOMO trigger confirmed." if emotion_points else "Emotional control not confirmed.")

    news_clear = not linked_high_news and checklist.get("no_news_risk", False)
    news_points = 10 if news_clear else 0
    add_component("News guard clear", news_points, 10, news_clear, "No linked high-impact news risk loaded and news box ticked." if news_clear else "Linked high-impact news or news-clear box not confirmed.")

    vol_points = 10 if volatility in ("Low", "Medium") else 5 if volatility == "High" else 0
    add_component("Volatility quality", vol_points, 10, vol_points >= 10, f"Current volatility reading: {volatility}.")

    score = max(0, min(100, sum(c["points"] for c in components)))

    hard_blockers = []
    if not checklist.get("stop_defined", False):
        hard_blockers.append("No defined stop-loss.")
    if rr < settings.min_risk_reward:
        hard_blockers.append(f"Risk/reward below minimum {settings.min_risk_reward:.2f}.")
    if not checklist.get("planned_zone", False):
        hard_blockers.append("No planned entry zone.")
    if linked_high_news and not checklist.get("no_news_risk", False):
        hard_blockers.append("Linked high-impact news risk has not been cleared.")
    if volatility == "Very High":
        hard_blockers.append("Very high volatility reading.")

    if hard_blockers:
        verdict = "BLOCKED_BY_HARD_RULES"
        tone = "red"
        message = "Trade blocked. One or more hard safety rules failed."
    elif score >= min_conf:
        verdict = "HIGH_CONFIDENCE_MANUAL_REVIEW"
        tone = "green"
        message = f"Confidence score is {score}/100, meeting the {min_conf}+ gate. Still paper/manual review only."
    elif score >= max(70, min_conf - 15):
        verdict = "WAIT_FOR_MORE_CONFIRMATION"
        tone = "amber"
        message = f"Confidence score is {score}/100. Below the {min_conf}+ gate. Wait for a cleaner setup."
    else:
        verdict = "BLOCKED_LOW_CONFIDENCE"
        tone = "red"
        message = f"Confidence score is {score}/100. Too low for the current strict gate."

    return {
        "score": score,
        "confidence_score": score,
        "min_confidence_score": min_conf,
        "verdict": verdict,
        "tone": tone,
        "message": message,
        "trend_ok": trend_ok,
        "risk_reward_ok": rr >= settings.min_risk_reward,
        "linked_high_news": linked_high_news,
        "hard_blockers": hard_blockers,
        "components": components,
        "analysis": pair_analysis,
        "live_trading_locked": True,
        "mode": "24/7 monitoring, paper/manual review only",
    }

def calculate_risk(req: Dict[str, Any]) -> Dict[str, Any]:
    balance = float(req["account_balance"])
    risk_pct = float(req["risk_pct"])
    pair = req["pair"]
    entry = float(req["entry"])
    stop = float(req["stop_loss"])
    target = float(req["target"])
    pip_value = float(req.get("pip_value_per_standard_lot", 10.0))

    stop_pips = abs(entry - stop) / pip_size(pair)
    reward_pips = abs(target - entry) / pip_size(pair)

    if stop_pips <= 0:
        raise ValueError("Stop distance must be greater than zero.")

    risk_amount = balance * (risk_pct / 100)
    lots = risk_amount / (stop_pips * pip_value)
    units = lots * 100000
    rr = reward_pips / stop_pips if stop_pips else 0

    if risk_pct > settings.max_risk_per_trade_pct:
        verdict = "RISK_TOO_HIGH"
        tone = "red"
    elif rr < settings.min_risk_reward:
        verdict = "RR_TOO_LOW"
        tone = "amber"
    else:
        verdict = "OK_FOR_REVIEW"
        tone = "green"

    return {
        "risk_amount": risk_amount,
        "stop_pips": stop_pips,
        "reward_pips": reward_pips,
        "risk_reward": rr,
        "standard_lots": lots,
        "position_units": units,
        "verdict": verdict,
        "tone": tone,
        "notes": "Educational estimate. Confirm broker contract specs, spread and account-currency conversion before any real trade.",
    }

def automation_readiness(data: Dict[str, Any]) -> Dict[str, Any]:
    gates = [
        {"name": "At least 100 backtested trades", "pass": data["backtested_trades"] >= 100},
        {"name": "At least 50 demo/forward trades", "pass": data["forward_trades"] >= 50},
        {"name": "Positive average R", "pass": data["avg_r"] > 0},
        {"name": "Max drawdown below or equal 10%", "pass": data["max_drawdown_pct"] <= 10},
        {"name": "Daily loss cap below or equal 2%", "pass": data["max_daily_loss_pct"] <= 2},
        {"name": "Win rate above 40% with positive expectancy", "pass": data["win_rate_pct"] >= 40 and data["avg_r"] > 0},
    ]
    passed = sum(1 for g in gates if g["pass"])
    ready = passed == len(gates)
    return {
        "ready_for_demo_automation": ready,
        "live_trading_locked": True,
        "passed": passed,
        "total": len(gates),
        "gates": gates,
        "message": "Ready for demo automation only." if ready else "Not ready for automation. Continue testing manually/paper trading.",
    }
