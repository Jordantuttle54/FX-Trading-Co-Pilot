from typing import Dict, Any
from .config import settings

WATCHLIST = ["GBP/USD", "EUR/USD", "USD/JPY", "EUR/GBP", "GBP/JPY", "XAU/USD"]


def affected_pairs_for_currency(currency: str):
    currency = (currency or "").upper()
    return [p for p in WATCHLIST if currency in p.split("/") or (currency == "USD" and p == "XAU/USD")]


def generate_briefing(analysis: Dict[str, Any], calendar: Dict[str, Any], snapshot: Dict[str, Any]) -> Dict[str, Any]:
    pairs = analysis.get("pairs", [])
    events = calendar.get("events", [])

    bullish = [p["pair"] for p in pairs if p.get("bias") == "Bullish"]
    bearish = [p["pair"] for p in pairs if p.get("bias") == "Bearish"]
    neutral = [p["pair"] for p in pairs if p.get("bias") == "Neutral"]

    high_events = [e for e in events if str(e.get("impact", "")).lower() == "high"]
    provider = snapshot.get("provider", "unknown")
    calendar_provider = calendar.get("provider", "unknown")

    blocked = []
    for e in high_events:
        for p in affected_pairs_for_currency(e.get("currency", "")):
            if p not in blocked:
                blocked.append(p)

    cleaner_focus = []
    for p in pairs:
        pair_name = p.get("pair")
        if pair_name not in blocked and p.get("bias") in ("Bullish", "Bearish") and p.get("volatility") != "Very High":
            cleaner_focus.append(pair_name)

    risk_level = "High" if len(high_events) >= 2 else "Medium" if high_events else "Normal"

    lines = []
    lines.append(f"Market feed: {provider}. Calendar source: {calendar_provider}.")
    lines.append(f"Today’s risk level: {risk_level}.")
    lines.append(f"Trading window: {settings.trading_window}. Max risk per trade: {settings.max_risk_per_trade_pct}%.")

    if high_events:
        event_text = "; ".join(f"{e.get('time', '')} {e.get('currency', '')} {e.get('event', '')}" for e in high_events[:5])
        lines.append(f"High-impact news to respect: {event_text}.")
        lines.append("News-affected pairs: " + (", ".join(blocked) if blocked else "none matched to watchlist") + ".")
    else:
        lines.append("No high-impact events loaded in the manual calendar.")

    if cleaner_focus:
        lines.append("Cleaner focus list: " + ", ".join(cleaner_focus[:4]) + ".")
    else:
        lines.append("Cleaner focus list: patience. Most active pairs are either mixed or news-affected.")

    if bullish:
        lines.append("Bullish technical bias: " + ", ".join(bullish) + ".")
    if bearish:
        lines.append("Bearish technical bias: " + ", ".join(bearish) + ".")
    if neutral:
        lines.append("Neutral / waitlist: " + ", ".join(neutral) + ".")

    lines.append("Rule for today: no trade without a defined stop, minimum risk/reward, planned level, and clear news guard.")
    lines.append("If price is between levels, do nothing.")

    return {
        "title": "AI FX Morning Briefing",
        "summary": "\n\n".join(lines),
        "risk_level": risk_level,
        "blocked_pairs": blocked,
        "cleaner_focus": cleaner_focus[:4],
        "high_impact_events": high_events[:10],
        "generated_from": {
            "market_provider": snapshot.get("provider"),
            "calendar_provider": calendar.get("provider"),
        },
    }
