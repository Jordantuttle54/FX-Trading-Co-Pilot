import os, sys, pathlib
from datetime import datetime, timezone
os.environ["TEMP_PASSWORDLESS_LOGIN"] = "true"
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
from api.index import app
from backend import paper_mvp_persistent as base
from backend import paper_mvp_agent_runner as agent

USER = "Jake"
ok = True
def check(name, cond):
    global ok
    print(("PASS  " if cond else "FAIL  ") + name)
    ok = ok and cond

client = TestClient(app)
token = client.post("/api/auth/login", json={"username": USER, "passcode": ""}).json()["access_token"]
H = {"Authorization": f"Bearer {token}"}

def reset(**cfg):
    base.TRADES.clear()
    base.AUDIT.clear()
    agent._MEM_CONFIG.clear()
    agent._MEM_RUNS.clear()
    base.KILL_SWITCH["active"] = False
    base.KILL_SWITCH["reason"] = ""
    agent.save_agent_config(USER, {"enabled": True, "respect_window": False, **cfg})

# A strong uptrend so the scanner reliably finds a buy on every pair.
def trending(pair):
    b = {"GBP/USD": 1.30, "EUR/USD": 1.08, "USD/JPY": 156.0,
         "EUR/GBP": 0.855, "GBP/JPY": 198.0, "XAU/USD": 4500.0}[pair]
    step = b * 0.0006
    return [{"time": f"t{i}", "open": b + i * step, "high": b + i * step * 1.001,
             "low": b + i * step * 0.999, "close": b + i * step, "volume": 100} for i in range(120)]

base.MIN_CONF = 0          # testing the agent's gates, not the strategy's
base.get_candles = trending
# Real OANDA quotes always carry the broker's own tick time and a tradeable
# flag; the agent refuses any quote it cannot age, so the stub must too.
def live_snapshot():
    ts = datetime.now(timezone.utc).isoformat()
    return {"provider": "oanda", "quotes": [
        {"pair": p, "price": trending(p)[-1]["close"], "bid": trending(p)[-1]["close"],
         "ask": trending(p)[-1]["close"], "timestamp": ts, "tradeable": True,
         "source": "oanda-practice"} for p in base.WATCHLIST]}

base.snapshot = live_snapshot

# ---- defaults are safe -----------------------------------------------------
agent._MEM_CONFIG.clear()
check("agent is OFF by default", agent.get_agent_config(USER)["enabled"] is False)
off = agent.run_agent_once(USER, "test")
check("a disabled agent opens nothing", off["halted"] and off["opened"] == [])
check("and says why", "switched off" in off["halt_reason"])

# ---- it actually opens trades ---------------------------------------------
reset(max_open_trades=3, max_trades_per_day=6, min_confidence=0)
run = agent.run_agent_once(USER, "test")
check("agent opened trades", len(run["opened"]) > 0)
check("it respects max_open_trades", len(run["opened"]) <= 3)
check("opened trades are tagged as the agent's", all(
    t.get("trade_origin") == "agent_auto" for t in base.TRADES))
check("trades are stored as open", all(t["status"] == "open" for t in base.TRADES))
check("each opened trade has a stop and target", all(
    t.get("stop_loss") and t.get("take_profit") for t in base.TRADES))
check("the run was recorded", len(agent.list_runs(USER)) >= 1)
check("an audit entry was written", any(a.get("event_type") == "agent_auto_open" for a in base.AUDIT))

# ---- it won't exceed the open-position cap on a second run ----------------
run2 = agent.run_agent_once(USER, "test")
check("second run is blocked by the position cap",
      run2["halted"] and "maximum" in run2["halt_reason"])

# ---- daily trade cap -------------------------------------------------------
reset(max_open_trades=10, max_trades_per_day=2, min_confidence=0)
agent.run_agent_once(USER, "test")
opened_total = len([t for t in base.TRADES if t.get("trade_origin") == "agent_auto"])
check(f"daily cap honoured ({opened_total} opened, cap 2)", opened_total <= 2)

# ---- kill switch -----------------------------------------------------------
reset(min_confidence=0)
base.KILL_SWITCH["active"] = True
base.KILL_SWITCH["reason"] = "Manual stop"
killed = agent.run_agent_once(USER, "test")
check("kill switch halts the agent", killed["halted"] and killed["opened"] == [])
check("kill switch reason is reported", "Manual stop" in killed["halt_reason"])
base.KILL_SWITCH["active"] = False

# ---- trading window --------------------------------------------------------
reset(respect_window=True, min_confidence=0)
base.london_window = lambda: False
windowed = agent.run_agent_once(USER, "test")
check("outside the window the agent stands down", windowed["halted"] and "window" in windowed["halt_reason"])
base.london_window = lambda: True

# ---- confidence floor ------------------------------------------------------
reset(min_confidence=99)
lowconf = agent.run_agent_once(USER, "test")
check("confidence floor blocks weak setups", lowconf["opened"] == [])
check("and explains why per pair", any("below the agent" in s["reason"] for s in lowconf["skipped"]))

# ---- synthetic data is refused --------------------------------------------
reset(min_confidence=0)
# Simulate the OANDA candle fetch failing: get_candles falls back to synthetic
# candles, which carry the marker that makes the fallback detectable.
base.get_candles = lambda pair: [dict(c, synthetic=True) for c in trending(pair)]
syn = agent.run_agent_once(USER, "test")
check("agent refuses to trade on fallback prices", syn["opened"] == [])
check("and says the data was unavailable", any("fallback prices" in s["reason"] for s in syn["skipped"]))
base.get_candles = trending
base.snapshot = live_snapshot

# ---- loss limits -----------------------------------------------------------
reset(min_confidence=0)
base.TRADES.append({"id": "loss", "user_name": USER, "status": "closed", "pair": "GBP/USD",
                    "direction": "buy", "result_money": -900.0, "closed_at": base.now(),
                    "created_at": base.now()})
limits = agent.loss_limit_state(USER, 10000.0)
check(f"daily loss computed ({limits['daily_loss_pct']}%)", limits["daily_loss_pct"] > 0)
check("daily limit registers as breached", limits["daily_breached"])
blocked = agent.run_agent_once(USER, "test")
check("agent stops after breaching the daily limit",
      blocked["halted"] and "Daily loss limit" in blocked["halt_reason"])

# ---- dry run opens nothing -------------------------------------------------
reset(min_confidence=0)
dry = agent.run_agent_once(USER, "test", dry_run=True)
check("dry run reports what it would do", len(dry["opened"]) > 0)
check("dry run stores no trades", len([t for t in base.TRADES if t.get("trade_origin") == "agent_auto"]) == 0)

# ---- pair restriction ------------------------------------------------------
reset(pairs=["GBP/USD"], min_confidence=0)
only = agent.run_agent_once(USER, "test")
check("only the allowed pair is scanned", only["pairs_scanned"] == 1)
check("and only that pair is traded", all(o["pair"] == "GBP/USD" for o in only["opened"]))

# ---- HTTP surface ----------------------------------------------------------
check("config endpoint needs auth", client.get("/api/agent/agent-config").status_code == 401)
check("cron endpoint needs the secret", client.get("/api/agent/cron/scan-open").status_code in (401, 503))

cfg = client.get("/api/agent/agent-config", headers=H).json()
check("config endpoint returns the config", "config" in cfg and "enabled" in cfg["config"])
check("config lists both strategies", len(cfg["available_strategies"]) == 2)
check("config reports the real loss limits", "daily_loss_pct" in cfg["limits"])

saved = client.post("/api/agent/agent-config", json={"enabled": True, "max_open_trades": 2}, headers=H).json()
check("config saves", saved["config"]["enabled"] is True and saved["config"]["max_open_trades"] == 2)
bad = client.post("/api/agent/agent-config", json={"max_open_trades": 999, "pairs": ["FAKE/PAIR"]}, headers=H).json()
check("silly limits are clamped", bad["config"]["max_open_trades"] == 20)
check("unknown pairs are dropped", bad["config"]["pairs"] == [])

runs = client.get("/api/agent/agent-runs", headers=H).json()
check("run history is exposed", "runs" in runs and "last_run_at" in runs)

manual = client.post("/api/agent/agent-run", json={"dry_run": True}, headers=H).json()
check("manual dry run works from the UI", "opened" in manual and manual["dry_run"] is True)

print()
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
