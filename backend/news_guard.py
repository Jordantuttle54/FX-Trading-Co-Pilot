"""news_guard.py - refuse to open a position into a high-impact release.

The app claimed to do this for a long time before it did: the Calendar tab
said "High-impact events within 30 minutes of a trade trigger a news blackout"
while `blocked_events` was a hardcoded empty list. This is that guard.

Why it matters more than most gates: every other risk control here assumes the
stop works. Around NFP, a rate decision or CPI, price gaps - it jumps straight
through the stop level and fills well beyond it. A position sized to lose 1R
loses three or five. No amount of position sizing protects against that; only
not being in the trade does.

Design notes
------------
The guard is OFF until a calendar provider is configured, and says so rather
than implying coverage it does not have. Once configured it fails CLOSED: if
the calendar cannot be fetched, we do not know whether NFP is in five minutes,
and "I don't know" is not a reason to trade. Set NEWS_GUARD_FAIL_OPEN=true to
invert that if an outage silencing the agent is worse for you than trading
blind through a release.

Choosing a provider
-------------------
Two shapes are supported and neither is privileged:

  ECONOMIC_CALENDAR_PROVIDER=finnhub + ECONOMIC_CALENDAR_API_KEY
  ECONOMIC_CALENDAR_URL=<any endpoint returning JSON>

The custom route takes any feed that returns a list of events, or an object
containing one. normalise_event() accepts both field conventions in the wild:
a country code with the event under "event" (Finnhub), or the currency itself
under "country" with the event under "title", which is how the widely-copied
ForexFactory weekly JSON is shaped. So a free feed needs no code change.

Whatever you pick, check what it costs before relying on it - a provider that
starts refusing requests will stop the agent trading, by design.
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

import httpx

log = logging.getLogger("fx.news")

# Minutes either side of a release during which no new position is opened.
# Symmetric on purpose: the spread widens and liquidity thins before the print
# as much as price whips around after it.
BLACKOUT_MINUTES = float(os.getenv("NEWS_BLACKOUT_MINUTES", "30"))

# Which impact levels count. Medium releases move price but rarely gap it.
BLOCK_IMPACTS = {
    s.strip().lower()
    for s in os.getenv("NEWS_BLACKOUT_IMPACTS", "high").split(",")
    if s.strip()
}

FAIL_OPEN = os.getenv("NEWS_GUARD_FAIL_OPEN", "false").lower() in ("1", "true", "yes", "on")
CACHE_MINUTES = float(os.getenv("NEWS_CACHE_MINUTES", "15"))

PROVIDER = os.getenv("ECONOMIC_CALENDAR_PROVIDER", "").strip().lower()
API_KEY = os.getenv("ECONOMIC_CALENDAR_API_KEY", "").strip()
CUSTOM_URL = os.getenv("ECONOMIC_CALENDAR_URL", "").strip()

# Country/region codes to the currency whose price they move.
COUNTRY_CURRENCY = {
    "US": "USD", "USA": "USD",
    "GB": "GBP", "UK": "GBP",
    "EU": "EUR", "EA": "EUR", "DE": "EUR", "FR": "EUR", "IT": "EUR", "ES": "EUR",
    "JP": "JPY",
    "CH": "CHF", "CA": "CAD", "AU": "AUD", "NZ": "NZD", "CN": "CNY",
}


def currencies_for_pair(pair: str) -> Set[str]:
    """The currencies whose news moves this instrument.

    Gold is quoted in dollars and trades on US data - rate expectations,
    inflation prints - so XAU/USD is exposed to USD releases even though
    "XAU" is not a currency with a central bank.
    """
    parts = [p.strip().upper() for p in str(pair or "").replace("_", "/").split("/")]
    out = {p for p in parts if p and p not in ("XAU", "XAG")}
    if any(p in ("XAU", "XAG") for p in parts):
        out.add("USD")
    return out


def _parse_when(raw: Any) -> Optional[datetime]:
    text = str(raw or "").strip()
    if not text:
        return None
    for candidate in (text.replace("Z", "+00:00"), text.replace(" ", "T") + "+00:00", text.replace(" ", "T")):
        try:
            when = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        return when if when.tzinfo else when.replace(tzinfo=timezone.utc)
    return None


def normalise_event(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """One provider's row into the shape the guard works in."""
    when = _parse_when(raw.get("time") or raw.get("date") or raw.get("datetime"))
    if not when:
        return None
    currency = str(raw.get("currency") or "").strip().upper()
    if not currency:
        country = str(raw.get("country") or raw.get("region") or "").strip().upper()
        # Feeds disagree about this field. Finnhub puts a country code in it
        # ("US"); the ForexFactory-style weekly JSON that most free calendars
        # copy puts the currency itself in it ("USD"). Accept either, so a free
        # feed works without needing its own adapter.
        currency = COUNTRY_CURRENCY.get(country, country if len(country) == 3 else "")
    if not currency:
        return None
    return {
        "time": when.isoformat(),
        "currency": currency,
        "event": str(raw.get("event") or raw.get("title") or "Economic release").strip(),
        "impact": str(raw.get("impact") or raw.get("importance") or "").strip().lower() or "unknown",
    }


def _fetch_finnhub() -> List[Dict[str, Any]]:
    # Finnhub gates several endpoints behind its paid plans; check
    # finnhub.io/pricing before assuming this one is on the free tier. A
    # PremiumRequired reply surfaces as a fetch failure, which - because the
    # guard fails closed - stops trading rather than silently trading blind.
    url = "https://finnhub.io/api/v1/calendar/economic"
    with httpx.Client(timeout=12) as client:
        res = client.get(url, params={"token": API_KEY})
        res.raise_for_status()
        data = res.json()
    return list(data.get("economicCalendar") or [])


def _fetch_custom() -> List[Dict[str, Any]]:
    """Any endpoint returning a JSON list, or an object with one list in it."""
    headers = {"Authorization": f"Bearer {API_KEY}"} if API_KEY else {}
    with httpx.Client(timeout=12) as client:
        res = client.get(CUSTOM_URL, headers=headers)
        res.raise_for_status()
        data = res.json()
    if isinstance(data, list):
        return data
    for value in (data or {}).values():
        if isinstance(value, list):
            return value
    return []


def configured() -> bool:
    if PROVIDER == "finnhub":
        return bool(API_KEY)
    if PROVIDER == "custom" or CUSTOM_URL:
        return bool(CUSTOM_URL)
    return False


def provider_name() -> str:
    if not configured():
        return "none"
    return PROVIDER or "custom"


_CACHE: Dict[str, Any] = {"events": None, "fetched_at": None, "error": ""}
_LOCK = threading.Lock()


def upcoming_events(force: bool = False) -> Dict[str, Any]:
    """Cached calendar. {events, error, fetched_at, provider}.

    `error` non-empty means we could not establish what is coming - which is
    a different thing from "nothing is coming", and the callers below treat it
    that way.
    """
    if not configured():
        return {"events": [], "error": "", "fetched_at": None, "provider": "none", "configured": False}

    with _LOCK:
        fetched_at = _CACHE.get("fetched_at")
        fresh = (
            not force
            and _CACHE.get("events") is not None
            and fetched_at is not None
            and (datetime.now(timezone.utc) - fetched_at) < timedelta(minutes=CACHE_MINUTES)
        )
        if fresh:
            return {
                "events": _CACHE["events"], "error": _CACHE.get("error", ""),
                "fetched_at": fetched_at.isoformat(), "provider": provider_name(), "configured": True,
            }

        try:
            raw = _fetch_finnhub() if PROVIDER == "finnhub" else _fetch_custom()
            events = [e for e in (normalise_event(r) for r in raw) if e]
            events.sort(key=lambda e: e["time"])
            _CACHE.update({"events": events, "fetched_at": datetime.now(timezone.utc), "error": ""})
            return {
                "events": events, "error": "", "fetched_at": _CACHE["fetched_at"].isoformat(),
                "provider": provider_name(), "configured": True,
            }
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            log.error("Economic calendar fetch failed: %s", message)
            _CACHE["error"] = message
            # Deliberately keep any previously cached events. A stale calendar
            # still knows about this afternoon's releases, and is far better
            # than nothing while the provider is down.
            return {
                "events": _CACHE.get("events") or [], "error": message,
                "fetched_at": fetched_at.isoformat() if fetched_at else None,
                "provider": provider_name(), "configured": True,
            }


def blocking_events(pair: str, now: Optional[datetime] = None, events: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """High-impact releases inside the blackout window for this pair."""
    now = now or datetime.now(timezone.utc)
    if events is None:
        events = upcoming_events().get("events") or []
    wanted = currencies_for_pair(pair)
    window = timedelta(minutes=BLACKOUT_MINUTES)
    hits = []
    for event in events:
        if event.get("currency") not in wanted:
            continue
        if event.get("impact") not in BLOCK_IMPACTS:
            continue
        when = _parse_when(event.get("time"))
        if not when:
            continue
        delta = when - now
        if -window <= delta <= window:
            hits.append({**event, "minutes_away": round(delta.total_seconds() / 60.0, 1)})
    return hits


def check(pair: str, now: Optional[datetime] = None) -> Dict[str, Any]:
    """{blocked, reason, events, active} - the single answer for one pair."""
    if not configured():
        return {
            "blocked": False, "reason": None, "events": [], "active": False,
            "provider": "none",
            "note": "No economic calendar provider configured, so no news blackout is in force.",
        }

    state = upcoming_events()
    if state.get("error") and not state.get("events"):
        # We cannot tell what is coming. Trading through an unknown calendar is
        # exactly the risk this guard exists to remove, so refuse by default.
        if FAIL_OPEN:
            return {
                "blocked": False, "reason": None, "events": [], "active": True,
                "provider": provider_name(),
                "note": f"Economic calendar unavailable ({state['error']}) - trading anyway because NEWS_GUARD_FAIL_OPEN is set.",
            }
        return {
            "blocked": True,
            "reason": f"Economic calendar unavailable, so upcoming releases are unknown ({state['error']}).",
            "events": [], "active": True, "provider": provider_name(),
        }

    hits = blocking_events(pair, now, state.get("events") or [])
    if not hits:
        return {"blocked": False, "reason": None, "events": [], "active": True, "provider": provider_name()}

    soonest = min(hits, key=lambda e: abs(e["minutes_away"]))
    minutes = soonest["minutes_away"]
    timing = f"in {abs(minutes):.0f} min" if minutes >= 0 else f"{abs(minutes):.0f} min ago"
    return {
        "blocked": True,
        "reason": f"{soonest['currency']} {soonest['event']} {timing} - inside the {BLACKOUT_MINUTES:.0f} minute news blackout.",
        "events": hits,
        "active": True,
        "provider": provider_name(),
    }


def status() -> Dict[str, Any]:
    """What the Calendar tab needs to describe the guard honestly."""
    state = upcoming_events()
    return {
        "configured": configured(),
        "provider": provider_name(),
        "active": configured(),
        "blackout_minutes": BLACKOUT_MINUTES,
        "impacts": sorted(BLOCK_IMPACTS),
        "fail_open": FAIL_OPEN,
        "events": state.get("events") or [],
        "error": state.get("error") or "",
        "fetched_at": state.get("fetched_at"),
    }
