from __future__ import annotations

import os
import csv
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import httpx

from .config import settings
from .strategy import WATCHLIST, analyse_candles, pip_size

OANDA_PRACTICE = "https://api-fxpractice.oanda.com"
OANDA_LIVE = "https://api-fxtrade.oanda.com"
TWELVE_BASE = "https://api.twelvedata.com"
FRANKFURTER_BASE = "https://api.frankfurter.dev/v2"
FMP_BASE = "https://financialmodelingprep.com/stable/economic-calendar"
FINNHUB_CALENDAR_BASE = "https://finnhub.io/api/v1/calendar/economic"

GRANULARITY_MAP = {
    "1m": "M1", "5m": "M5", "15m": "M15", "30m": "M30",
    "1h": "H1", "4h": "H4", "1d": "D"
}

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def oanda_instrument(pair: str) -> str:
    return pair.replace("/", "_").replace("XAU_USD", "XAU_USD")

def choose_provider() -> str:
    requested = settings.data_provider
    if requested != "auto":
        return requested
    if settings.oanda_access_token and settings.oanda_account_id:
        return "oanda"
    if settings.twelve_data_api_key:
        return "twelvedata"
    return "frankfurter"

async def get_json(url: str, params: Optional[dict] = None, headers: Optional[dict] = None) -> Any:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, params=params, headers=headers)
        resp.raise_for_status()
        return resp.json()

async def oanda_snapshot() -> Dict[str, Any]:
    base = OANDA_LIVE if settings.oanda_env == "live" else OANDA_PRACTICE
    instruments = ",".join(oanda_instrument(p) for p in WATCHLIST)
    url = f"{base}/v3/accounts/{settings.oanda_account_id}/pricing"
    headers = {"Authorization": f"Bearer {settings.oanda_access_token}"}
    data = await get_json(url, params={"instruments": instruments}, headers=headers)

    by_instrument = {p["instrument"]: p for p in data.get("prices", [])}
    quotes = []
    for pair in WATCHLIST:
        inst = oanda_instrument(pair)
        p = by_instrument.get(inst)
        if not p:
            continue
        bid = float(p["closeoutBid"])
        ask = float(p["closeoutAsk"])
        mid = (bid + ask) / 2
        spread_pips = abs(ask - bid) / pip_size(pair)
        quotes.append({
            "pair": pair,
            "price": mid,
            "bid": bid,
            "ask": ask,
            "spread_pips": spread_pips,
            "timestamp": p.get("time", now_iso()),
            "source": "oanda",
        })
    return {"provider": "oanda", "generated_at": now_iso(), "quotes": quotes, "warnings": []}

async def twelvedata_snapshot() -> Dict[str, Any]:
    quotes = []
    warnings = []
    for pair in WATCHLIST:
        if pair == "XAU/USD":
            symbol = "XAU/USD"
        else:
            symbol = pair
        try:
            data = await get_json(
                f"{TWELVE_BASE}/quote",
                params={"symbol": symbol, "apikey": settings.twelve_data_api_key},
            )
            if data.get("status") == "error":
                raise RuntimeError(data.get("message", "Twelve Data error"))
            price = float(data.get("close") or data.get("price") or data.get("previous_close"))
            quotes.append({
                "pair": pair,
                "price": price,
                "bid": None,
                "ask": None,
                "spread_pips": None,
                "timestamp": data.get("datetime") or now_iso(),
                "source": "twelvedata",
                "change_pct": data.get("percent_change"),
            })
        except Exception as exc:
            warnings.append(f"{pair}: {exc}")
    return {"provider": "twelvedata", "generated_at": now_iso(), "quotes": quotes, "warnings": warnings}

async def frankfurter_rate(pair: str) -> Optional[float]:
    if pair == "XAU/USD":
        return None
    base, quote = pair.split("/")
    data = await get_json(f"{FRANKFURTER_BASE}/rate/{base}/{quote}")
    if "rate" in data:
        return float(data["rate"])
    if "rates" in data and quote in data["rates"]:
        return float(data["rates"][quote])
    return None

async def frankfurter_snapshot() -> Dict[str, Any]:
    quotes = []
    warnings = ["Frankfurter fallback uses daily reference rates, not intraday tradable quotes."]
    for pair in WATCHLIST:
        try:
            price = await frankfurter_rate(pair)
            if price is None:
                raise RuntimeError("Not supported by Frankfurter fallback")
            quotes.append({
                "pair": pair,
                "price": price,
                "bid": None,
                "ask": None,
                "spread_pips": None,
                "timestamp": now_iso(),
                "source": "frankfurter-daily-reference",
            })
        except Exception:
            price = synthetic_base_price(pair)
            quotes.append({
                "pair": pair,
                "price": price,
                "bid": None,
                "ask": None,
                "spread_pips": None,
                "timestamp": now_iso(),
                "source": "synthetic-fallback",
            })
            warnings.append(f"{pair} is using synthetic fallback data.")
    return {"provider": "frankfurter", "generated_at": now_iso(), "quotes": quotes, "warnings": warnings}

def synthetic_base_price(pair: str) -> float:
    bases = {
        "GBP/USD": 1.2700,
        "EUR/USD": 1.0850,
        "USD/JPY": 156.20,
        "EUR/GBP": 0.8550,
        "GBP/JPY": 198.50,
        "XAU/USD": 2350.0,
    }
    base = bases.get(pair, 1.0)
    # Deterministic gentle daily variation so the interface does not look frozen.
    seed = int(datetime.utcnow().strftime("%Y%m%d")) + abs(hash(pair)) % 1000
    random.seed(seed)
    return base * (1 + random.uniform(-0.003, 0.003))

async def mock_snapshot() -> Dict[str, Any]:
    quotes = []
    for pair in WATCHLIST:
        price = synthetic_base_price(pair)
        quotes.append({
            "pair": pair,
            "price": price,
            "bid": price - pip_size(pair),
            "ask": price + pip_size(pair),
            "spread_pips": 2,
            "timestamp": now_iso(),
            "source": "mock",
        })
    return {"provider": "mock", "generated_at": now_iso(), "quotes": quotes, "warnings": ["Mock data only."]}

async def market_snapshot() -> Dict[str, Any]:
    provider = choose_provider()
    try:
        if provider == "oanda":
            return await oanda_snapshot()
        if provider == "twelvedata":
            return await twelvedata_snapshot()
        if provider == "frankfurter":
            return await frankfurter_snapshot()
        if provider == "mock":
            return await mock_snapshot()
    except Exception as exc:
        fallback = await frankfurter_snapshot()
        fallback["provider"] = f"{provider}-failed-frankfurter-fallback"
        fallback["warnings"].append(f"{provider} failed: {exc}")
        return fallback
    return await frankfurter_snapshot()

def synthetic_candles(pair: str, count: int = 120, interval: str = "1h", base_price: Optional[float] = None) -> List[Dict[str, Any]]:
    price = base_price or synthetic_base_price(pair)
    candles = []
    step_minutes = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}.get(interval, 60)
    t = datetime.now(timezone.utc) - timedelta(minutes=step_minutes * count)
    random.seed(abs(hash(pair + interval)) % 100000 + int(datetime.utcnow().strftime("%Y%m%d")))
    vol = 0.0008 if "JPY" not in pair and pair != "XAU/USD" else 0.08
    if pair == "XAU/USD":
        vol = 2.5
    for i in range(count):
        drift = math.sin(i / 13) * vol * 0.25
        open_ = price
        close = max(0.0001, open_ + random.uniform(-vol, vol) + drift)
        high = max(open_, close) + abs(random.uniform(0, vol * 0.6))
        low = min(open_, close) - abs(random.uniform(0, vol * 0.6))
        t = t + timedelta(minutes=step_minutes)
        candles.append({
            "time": t.isoformat(),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "source": "synthetic-fallback",
        })
        price = close
    return candles

async def oanda_candles(pair: str, interval: str, count: int) -> List[Dict[str, Any]]:
    base = OANDA_LIVE if settings.oanda_env == "live" else OANDA_PRACTICE
    url = f"{base}/v3/instruments/{oanda_instrument(pair)}/candles"
    headers = {"Authorization": f"Bearer {settings.oanda_access_token}"}
    data = await get_json(
        url,
        params={
            "count": min(count, 500),
            "granularity": GRANULARITY_MAP.get(interval, "H1"),
            "price": "M",
        },
        headers=headers,
    )
    candles = []
    for c in data.get("candles", []):
        if not c.get("complete", True):
            continue
        mid = c["mid"]
        candles.append({
            "time": c["time"],
            "open": float(mid["o"]),
            "high": float(mid["h"]),
            "low": float(mid["l"]),
            "close": float(mid["c"]),
            "source": "oanda",
        })
    return candles

async def twelvedata_candles(pair: str, interval: str, count: int) -> List[Dict[str, Any]]:
    td_interval = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h", "4h": "4h", "1d": "1day"}.get(interval, "1h")
    data = await get_json(
        f"{TWELVE_BASE}/time_series",
        params={
            "symbol": pair,
            "interval": td_interval,
            "outputsize": min(count, 5000),
            "apikey": settings.twelve_data_api_key,
        },
    )
    if data.get("status") == "error":
        raise RuntimeError(data.get("message", "Twelve Data error"))
    values = list(reversed(data.get("values", [])))
    return [{
        "time": v.get("datetime"),
        "open": float(v["open"]),
        "high": float(v["high"]),
        "low": float(v["low"]),
        "close": float(v["close"]),
        "source": "twelvedata",
    } for v in values]

async def get_candles(pair: str, interval: str = "1h", count: int = 120) -> Dict[str, Any]:
    provider = choose_provider()
    try:
        if provider == "oanda" and settings.oanda_access_token and settings.oanda_account_id:
            candles = await oanda_candles(pair, interval, count)
            return {"pair": pair, "provider": "oanda", "candles": candles, "analysis": analyse_candles(pair, candles)}
        if provider == "twelvedata" and settings.twelve_data_api_key:
            candles = await twelvedata_candles(pair, interval, count)
            return {"pair": pair, "provider": "twelvedata", "candles": candles, "analysis": analyse_candles(pair, candles)}
    except Exception as exc:
        base = synthetic_base_price(pair)
        candles = synthetic_candles(pair, count=count, interval=interval, base_price=base)
        return {
            "pair": pair,
            "provider": f"{provider}-failed-synthetic-fallback",
            "candles": candles,
            "analysis": analyse_candles(pair, candles),
            "warning": str(exc),
        }

    snapshot = await market_snapshot()
    match = next((q for q in snapshot["quotes"] if q["pair"] == pair), None)
    base = match["price"] if match else synthetic_base_price(pair)
    candles = synthetic_candles(pair, count=count, interval=interval, base_price=base)
    return {
        "pair": pair,
        "provider": "synthetic-candles-from-current-rate",
        "candles": candles,
        "analysis": analyse_candles(pair, candles),
        "warning": "Candles are synthetic unless OANDA or Twelve Data is configured.",
    }

async def all_pair_analysis(interval: str = "1h") -> Dict[str, Any]:
    analyses = []
    warnings = []
    for pair in WATCHLIST:
        data = await get_candles(pair, interval=interval, count=120)
        analyses.append(data["analysis"])
        if data.get("warning"):
            warnings.append(f"{pair}: {data['warning']}")
    return {"generated_at": now_iso(), "pairs": analyses, "warnings": warnings}

async def economic_calendar() -> Dict[str, Any]:
    provider = settings.calendar_provider
    if provider == "auto":
        manual_path = Path(__file__).resolve().parents[1] / settings.manual_calendar_file
        if manual_path.exists():
            provider = "manual"
        elif getattr(settings, "finnhub_api_key", ""):
            provider = "finnhub"
        elif settings.fmp_api_key:
            provider = "fmp"
        else:
            provider = "fallback"

    if provider in {"manual", "csv"}:
        return manual_csv_calendar()

    if provider == "finnhub":
        return await finnhub_calendar()

    if provider == "fmp":
        return await fmp_calendar()

    return fallback_calendar(["Fallback sample calendar. Add a manual CSV calendar or API key for live economic calendar data."])

def manual_csv_calendar() -> Dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    csv_path = root / settings.manual_calendar_file

    if not csv_path.exists():
        return fallback_calendar([f"Manual calendar file not found: {settings.manual_calendar_file}"])

    events = []
    warnings = []
    try:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            required = {"date", "time", "currency", "event", "impact"}
            missing = required - set(reader.fieldnames or [])
            if missing:
                return fallback_calendar([f"Manual calendar CSV is missing columns: {', '.join(sorted(missing))}"])

            today = datetime.utcnow().date()
            for row in reader:
                date_text = (row.get("date") or "").strip()
                try:
                    event_date = datetime.strptime(date_text, "%Y-%m-%d").date()
                except Exception:
                    warnings.append(f"Skipped row with invalid date: {date_text}")
                    continue

                if event_date < today - timedelta(days=1):
                    continue

                events.append({
                    "date": date_text,
                    "time": (row.get("time") or "").strip(),
                    "currency": (row.get("currency") or "").strip().upper(),
                    "event": (row.get("event") or "").strip(),
                    "impact": normalize_impact(row.get("impact")),
                    "actual": (row.get("actual") or "").strip(),
                    "forecast": (row.get("forecast") or "").strip(),
                    "previous": (row.get("previous") or "").strip(),
                    "source": "manual_csv",
                })

        events = sorted(events, key=lambda e: (e["date"], e["time"]))[:200]
        if not events:
            return fallback_calendar([f"Manual calendar file loaded but no current/future events were found: {settings.manual_calendar_file}"])

        return {
            "provider": "manual_csv",
            "generated_at": now_iso(),
            "events": events,
            "warnings": warnings,
        }

    except Exception as exc:
        return fallback_calendar([f"Manual calendar failed: {exc}"])

async def finnhub_calendar() -> Dict[str, Any]:
    today = datetime.utcnow().date()
    future = today + timedelta(days=7)

    if not getattr(settings, "finnhub_api_key", ""):
        return fallback_calendar(["Finnhub calendar selected, but FINNHUB_API_KEY is empty."])

    try:
        data = await get_json(
            FINNHUB_CALENDAR_BASE,
            params={
                "from": str(today),
                "to": str(future),
                "token": settings.finnhub_api_key,
            },
        )

        raw_events = data.get("economicCalendar", []) if isinstance(data, dict) else []
        events = []
        for e in raw_events[:120]:
            raw_time = e.get("time") or e.get("date") or ""
            date_part = ""
            time_part = ""
            if isinstance(raw_time, str):
                parts = raw_time.replace("T", " ").split(" ")
                date_part = parts[0] if parts else str(today)
                time_part = parts[1][:5] if len(parts) > 1 else ""

            country = e.get("country") or ""
            currency = country_to_currency(country)

            events.append({
                "date": date_part or str(today),
                "time": time_part,
                "currency": currency,
                "country": country,
                "event": e.get("event") or e.get("name") or "Economic event",
                "impact": normalize_impact(e.get("impact")),
                "actual": e.get("actual"),
                "forecast": e.get("estimate") or e.get("forecast"),
                "previous": e.get("prev") or e.get("previous"),
                "source": "finnhub",
            })

        if not events:
            return fallback_calendar(["Finnhub returned no events for the selected date range."])

        return {"provider": "finnhub", "generated_at": now_iso(), "events": events, "warnings": []}

    except Exception as exc:
        return fallback_calendar([f"Finnhub calendar failed: {exc}"])

async def fmp_calendar() -> Dict[str, Any]:
    today = datetime.utcnow().date()
    future = today + timedelta(days=3)

    if settings.fmp_api_key:
        try:
            data = await get_json(
                FMP_BASE,
                params={"from": str(today), "to": str(future), "apikey": settings.fmp_api_key},
            )
            events = []
            for e in data[:80] if isinstance(data, list) else []:
                events.append({
                    "date": e.get("date"),
                    "time": e.get("time") or "",
                    "currency": e.get("country") or e.get("currency") or "",
                    "event": e.get("event") or e.get("name") or "Economic event",
                    "impact": e.get("impact") or "Medium",
                    "actual": e.get("actual"),
                    "forecast": e.get("estimate") or e.get("forecast"),
                    "previous": e.get("previous"),
                    "source": "fmp",
                })
            return {"provider": "fmp", "generated_at": now_iso(), "events": events, "warnings": []}
        except Exception as exc:
            return fallback_calendar([f"FMP calendar failed: {exc}"])

    return fallback_calendar(["Fallback sample calendar. Add FMP_API_KEY for live economic calendar data."])

def normalize_impact(value: Any) -> str:
    if value is None:
        return "Medium"
    text = str(value).strip()
    lower = text.lower()
    if lower in {"high", "3", "important"}:
        return "High"
    if lower in {"low", "1"}:
        return "Low"
    if lower in {"medium", "2"}:
        return "Medium"
    return text.title()

def country_to_currency(country: str) -> str:
    mapping = {
        "US": "USD", "USA": "USD", "United States": "USD",
        "GB": "GBP", "UK": "GBP", "United Kingdom": "GBP",
        "EU": "EUR", "EA": "EUR", "Euro Area": "EUR", "Eurozone": "EUR",
        "DE": "EUR", "FR": "EUR", "IT": "EUR", "ES": "EUR",
        "JP": "JPY", "Japan": "JPY",
        "CA": "CAD", "Canada": "CAD",
        "AU": "AUD", "Australia": "AUD",
        "NZ": "NZD", "New Zealand": "NZD",
        "CH": "CHF", "Switzerland": "CHF",
    }
    return mapping.get(country, country)

def fallback_calendar(warnings: List[str]) -> Dict[str, Any]:
    today = datetime.utcnow().date().isoformat()
    events = [
        {"date": today, "time": "09:30 London", "currency": "GBP", "event": "UK PMI / inflation / labour data placeholder", "impact": "High", "source": "fallback"},
        {"date": today, "time": "13:30 London", "currency": "USD", "event": "US jobs / CPI / retail sales placeholder", "impact": "High", "source": "fallback"},
        {"date": today, "time": "15:00 London", "currency": "USD", "event": "US ISM / consumer sentiment placeholder", "impact": "Medium", "source": "fallback"},
        {"date": today, "time": "18:00 London", "currency": "EUR", "event": "ECB speaker placeholder", "impact": "Medium", "source": "fallback"},
    ]
    return {"provider": "fallback", "generated_at": now_iso(), "events": events, "warnings": warnings}
