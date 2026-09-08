"""The news blackout: no new position into a high-impact release."""
import os, sys, pathlib
os.environ["TEMP_PASSWORDLESS_LOGIN"] = "true"; os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from datetime import datetime, timedelta, timezone
from backend import news_guard as ng

ok = True
def check(n, c):
    global ok; print(("PASS  " if c else "FAIL  ") + n); ok = ok and c

NOW = datetime(2026, 9, 7, 13, 0, 0, tzinfo=timezone.utc)
def at(minutes): return (NOW + timedelta(minutes=minutes)).isoformat()

EVENTS = [
    {"time": at(10),   "currency": "USD", "event": "Non-Farm Payrolls",   "impact": "high"},
    {"time": at(200),  "currency": "GBP", "event": "BoE Rate Decision",   "impact": "high"},
    {"time": at(5),    "currency": "EUR", "event": "Retail Sales",        "impact": "medium"},
    {"time": at(-12),  "currency": "JPY", "event": "BoJ Press Conference","impact": "high"},
]

# ---- which currencies a pair is exposed to --------------------------------
check("a major maps to both its legs", ng.currencies_for_pair("GBP/JPY") == {"GBP", "JPY"})
check("underscores are accepted too", ng.currencies_for_pair("EUR_USD") == {"EUR", "USD"})
# Gold has no central bank, but it is priced in dollars and trades on US data.
check("gold is exposed to USD news", ng.currencies_for_pair("XAU/USD") == {"USD"})

# ---- the window ------------------------------------------------------------
hits = ng.blocking_events("EUR/USD", NOW, EVENTS)
check("a high-impact release 10 min out blocks the pair", len(hits) == 1)
check("and it is named", hits and hits[0]["event"] == "Non-Farm Payrolls")
check("with how far away it is", hits and hits[0]["minutes_away"] == 10.0)

# GBP/CHF, not GBP/USD - the latter is legitimately blocked by the USD NFP
# above, which is the guard working rather than a far-off BoE print.
check("a release 200 min out does not block", ng.blocking_events("GBP/CHF", NOW, EVENTS) == [])
check("but a pair exposed to a near release is blocked on either leg",
      len(ng.blocking_events("GBP/USD", NOW, EVENTS)) == 1)
check("a medium-impact release does not block by default",
      ng.blocking_events("EUR/GBP", NOW, EVENTS) == [])
# The window is symmetric: price whips around after a print as much as before.
check("a release 12 min ago still blocks", len(ng.blocking_events("GBP/JPY", NOW, EVENTS)) == 1)
check("an unrelated pair is untouched", ng.blocking_events("AUD/NZD", NOW, EVENTS) == [])
# NFP is USD, so it must catch gold as well as the dollar majors.
check("gold is blocked by USD news", len(ng.blocking_events("XAU/USD", NOW, EVENTS)) == 1)

# ---- boundaries ------------------------------------------------------------
edge = [{"time": at(30), "currency": "USD", "event": "CPI", "impact": "high"}]
check("exactly at the window edge still blocks", len(ng.blocking_events("EUR/USD", NOW, edge)) == 1)
past = [{"time": at(31), "currency": "USD", "event": "CPI", "impact": "high"}]
check("one minute beyond it does not", ng.blocking_events("EUR/USD", NOW, past) == [])

# ---- provider rows are normalised -----------------------------------------
row = ng.normalise_event({"time": "2026-09-07 13:30:00", "country": "US",
                          "event": "Core CPI", "impact": "high"})
check("a provider row with a country code maps to a currency", row and row["currency"] == "USD")
check("and its timestamp parses", row and row["time"].startswith("2026-09-07T13:30:00"))
check("a row with no usable time is dropped", ng.normalise_event({"country": "US"}) is None)
check("a row with no identifiable currency is dropped",
      ng.normalise_event({"time": at(5), "country": "ZZ"}) is None)

# Free ForexFactory-style feeds put the currency itself in "country" and the
# event in "title", with a capitalised impact. Accepting that shape is what
# keeps a paid provider from being the only option.
ff = ng.normalise_event({"title": "Non-Farm Employment Change", "country": "USD",
                         "date": "2026-09-04T13:30:00-04:00", "impact": "High"})
check("a ForexFactory-style row is accepted", ff is not None)
check("its currency is read straight from country", ff and ff["currency"] == "USD")
check("its title becomes the event name", ff and ff["event"] == "Non-Farm Employment Change")
check("its impact is normalised to lower case", ff and ff["impact"] == "high")
check("its offset timestamp parses", ff and ff["time"].startswith("2026-09-04T13:30:00"))
check("a two-letter country still maps through the table",
      (ng.normalise_event({"time": at(5), "country": "GB", "event": "x"}) or {}).get("currency") == "GBP")

# ---- off until configured, and honest about it ----------------------------
ng.PROVIDER = ""; ng.API_KEY = ""; ng.CUSTOM_URL = ""
check("the guard is off with no provider", ng.configured() is False)
off = ng.check("EUR/USD", NOW)
check("nothing is blocked while it is off", off["blocked"] is False)
check("and it does not claim to be active", off["active"] is False)
check("and says so in words", "no news blackout" in off["note"].lower())

# ---- configured but unreachable: refuse, do not guess ---------------------
ng.PROVIDER = "finnhub"; ng.API_KEY = "test-key"
ng._CACHE.update({"events": None, "fetched_at": None, "error": ""})
ng._fetch_finnhub = lambda: (_ for _ in ()).throw(RuntimeError("503 upstream"))

blocked = ng.check("EUR/USD", NOW)
check("an unreachable calendar blocks new trades", blocked["blocked"] is True)
check("and explains that releases are unknown", "unknown" in blocked["reason"].lower())

ng.FAIL_OPEN = True
ng._CACHE.update({"events": None, "fetched_at": None, "error": ""})
opened = ng.check("EUR/USD", NOW)
check("NEWS_GUARD_FAIL_OPEN inverts that deliberately", opened["blocked"] is False)
check("and the note records that it did", "FAIL_OPEN" in opened["note"])
ng.FAIL_OPEN = False

# ---- a working provider ---------------------------------------------------
ng._fetch_finnhub = lambda: [
    {"time": at(8), "country": "US", "event": "Non-Farm Payrolls", "impact": "high"},
]
ng._CACHE.update({"events": None, "fetched_at": None, "error": ""})
live = ng.check("EUR/USD", NOW)
check("a real release blocks the pair", live["blocked"] is True)
check("the reason names the event", "Non-Farm Payrolls" in live["reason"])
check("the reason says how far away it is", "8 min" in live["reason"])
check("an unaffected pair still trades", ng.check("AUD/NZD", NOW)["blocked"] is False)

st = ng.status()
check("status reports the guard as active", st["active"] is True)
check("status reports the window", st["blackout_minutes"] == ng.BLACKOUT_MINUTES)
check("status carries the events", len(st["events"]) == 1)

check("status counts what arrived", st["raw_count"] == 1)
check("status counts what it could read", st["parsed_count"] == 1)

# ---- a feed that answers cleanly but cannot be read ------------------------
# The case that looks like good news and is not: 200 OK, rows present, none of
# them in a shape normalise_event understands. Events come back empty with no
# error, which is indistinguishable from a quiet week unless the counts are
# kept separately.
ng._fetch_finnhub = lambda: [
    {"when": "next tuesday", "ccy": "USD", "name": "Non-Farm Payrolls", "importance": "high"},
    {"when": "later", "ccy": "GBP", "name": "CPI", "importance": "high"},
]
ng._CACHE.update({"events": None, "fetched_at": None, "error": ""})
unreadable = ng.status(force=True)
check("an unreadable feed reports no error", unreadable["error"] == "")
check("and no events", len(unreadable["events"]) == 0)
check("but records that rows did arrive", unreadable["raw_count"] == 2)
check("and that none of them could be read", unreadable["parsed_count"] == 0)

# ---- force skips the cache ------------------------------------------------
ng._fetch_finnhub = lambda: [{"time": at(8), "country": "US", "event": "CPI", "impact": "high"}]
cached = ng.status()
check("without force the cached empty result stands", cached["parsed_count"] == 0)
refreshed = ng.status(force=True)
check("force=True refetches instead of serving the cache", refreshed["parsed_count"] == 1)

print(); print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
