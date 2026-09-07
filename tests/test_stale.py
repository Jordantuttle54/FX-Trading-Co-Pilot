import os, sys, pathlib
from datetime import datetime, timedelta, timezone
os.environ["TEMP_PASSWORDLESS_LOGIN"] = "true"; os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from api.index import app  # noqa
from backend import paper_mvp_persistent as base
from backend import paper_mvp_agent_runner as agent

USER = "Jake"; ok = True
def check(n, c):
    global ok; print(("PASS  " if c else "FAIL  ") + n); ok = ok and c

def trending(pair):
    b = {"GBP/USD":1.30,"EUR/USD":1.08,"USD/JPY":156.0,"EUR/GBP":0.855,"GBP/JPY":198.0,"XAU/USD":4500.0}[pair]
    s = b*0.0006
    return [{"time":f"t{i}","open":b+i*s,"high":b+i*s*1.001,"low":b+i*s*0.999,"close":b+i*s,"volume":100} for i in range(120)]

base.MIN_CONF = 0
base.get_candles = trending
base.london_window = lambda: True

def snap_at(minutes_ago):
    ts = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()
    return lambda: {"provider":"oanda","quotes":[
        {"pair":p,"price":trending(p)[-1]["close"],"bid":trending(p)[-1]["close"],
         "ask":trending(p)[-1]["close"],"timestamp":ts,"source":"oanda-practice"} for p in base.WATCHLIST]}

def reset(**cfg):
    base.TRADES.clear(); base.AUDIT.clear()
    agent._MEM_CONFIG.clear(); agent._MEM_RUNS.clear()
    base.KILL_SWITCH["active"] = False
    agent.save_agent_config(USER, {"enabled":True,"respect_window":False,"min_confidence":0,**cfg})

# --- live market: fresh quotes, window OFF -> it trades 24/5 ----------------
reset(); base.snapshot = snap_at(0.2)
run = agent.run_agent_once(USER, "test")
check("with the window off and fresh quotes, the agent trades", len(run["opened"]) > 0)
fresh = agent.quote_freshness()["GBP/USD"]
check(f"fresh quote measured as {fresh['age_minutes']} min old", fresh["age_minutes"] < 5)

# --- market closed: stale quotes -------------------------------------------
reset(); base.snapshot = snap_at(60 * 40)   # Friday close, checked Sunday
stale = agent.run_agent_once(USER, "test")
check("stale quotes stop it opening anything", stale["opened"] == [])
check("and it says the market looks closed",
      any("Market looks closed" in s["reason"] for s in stale["skipped"]))
check("no trades were stored", len([t for t in base.TRADES if t.get("trade_origin")=="agent_auto"]) == 0)

# --- boundary ---------------------------------------------------------------
reset(); base.snapshot = snap_at(14)
inside = agent.run_agent_once(USER, "test")
check("14 min old is still tradeable (limit 15)", len(inside["opened"]) > 0)
reset(); base.snapshot = snap_at(16)
outside = agent.run_agent_once(USER, "test")
check("16 min old is refused", outside["opened"] == [])

# --- a quote whose age we cannot establish is refused -----------------------
# This assertion used to be the opposite ("a missing timestamp does not falsely
# block"). That was wrong: not knowing how old a price is, is not a reason to
# trust it. It went unnoticed because the London window kept the agent away
# from the closed market anyway - with the window off, this gate is all there is.
reset()
base.snapshot = lambda: {"provider":"oanda","quotes":[
    {"pair":p,"price":trending(p)[-1]["close"],"bid":1.0,"ask":1.0,"source":"oanda-practice"}
    for p in base.WATCHLIST]}
notime = agent.run_agent_once(USER, "test")
check("an unknown-age quote is refused, not trusted", notime["opened"] == [])
check("and it says it could not tell the price's age",
      any("how old" in s["reason"] for s in notime["skipped"]))

# --- the broker saying "closed" beats guessing from the timestamp -----------
# OANDA reports tradeable=false on a shut market. That is the market telling us
# directly, rather than us inferring it from how stale the price looks.
reset()
base.snapshot = lambda: {"provider":"oanda","quotes":[
    {"pair":p,"price":trending(p)[-1]["close"],"bid":1.0,"ask":1.0,
     "timestamp":datetime.now(timezone.utc).isoformat(),
     "tradeable":False,"market_status":"non-tradeable","source":"oanda-practice"}
    for p in base.WATCHLIST]}
shut = agent.run_agent_once(USER, "test")
check("a fresh quote on a shut market is still refused", shut["opened"] == [])
check("and it says the market is closed",
      any("closed for trading" in s["reason"] for s in shut["skipped"]))

# --- the window toggle still works when you want it -------------------------
reset(respect_window=True); base.snapshot = snap_at(0.2)
base.london_window = lambda: False
win = agent.run_agent_once(USER, "test")
check("window toggle still stands the agent down when ON", win["halted"] and "window" in win["halt_reason"])
base.london_window = lambda: True
reset(respect_window=False); base.snapshot = snap_at(0.2)
base.london_window = lambda: False
nowin = agent.run_agent_once(USER, "test")
check("window toggle OFF lets it trade outside London hours", len(nowin["opened"]) > 0)

print(); print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
