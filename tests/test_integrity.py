"""Guards that must hold before real money: no invented prices, honest provenance."""
import os, sys, pathlib
os.environ["TEMP_PASSWORDLESS_LOGIN"] = "true"; os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from fastapi.testclient import TestClient
from api.index import app
from backend import paper_mvp_persistent as base
from backend import paper_mvp_trade_names as names

USER = "Jake"; ok = True
def check(n, c):
    global ok; print(("PASS  " if c else "FAIL  ") + n); ok = ok and c

client = TestClient(app)
token = client.post("/api/auth/login", json={"username": USER, "passcode": ""}).json()["access_token"]
H = {"Authorization": f"Bearer {token}"}

# ---- no live data means no new positions, on every path -------------------
# This is the deployment-without-credentials case: it still reaches the same
# database, so without these guards it can write trades priced off nothing.
base.TRADES.clear()
base.oanda_configured = lambda: False

ok_live, reason = base.market_data_is_live()
check("a deployment with no provider is not live", ok_live is False)
check("and says why in plain words", "invented" in reason)

paths = [
    ("/api/agent/trades/quick-open",
     {"pair": "GBP/USD", "direction": "buy", "entry": 1.30, "stop_loss": 1.29, "take_profit": 1.32}),
    ("/api/agent/trades/quick-open-ai", {"pair": "GBP/USD"}),
    ("/api/agent/execute", {"pair": "GBP/USD"}),
]
for path, body in paths:
    r = client.post(path, json=body, headers=H)
    check(f"{path} refuses to open on invented data ({r.status_code})", r.status_code == 503)
check("nothing was written", len(base.TRADES) == 0)

# ---- a synthetic-flagged snapshot is refused even with a provider set -----
base.oanda_configured = lambda: True
base.snapshot = lambda: {"provider": "oanda-failed-fallback", "quotes": [], "warnings": ["OANDA failed: timeout"]}
ok_live, reason = base.market_data_is_live()
check("a failed provider call is not live data", ok_live is False)
check("and the failure reason is carried through", "timeout" in reason)
r = client.post("/api/agent/execute", json={"pair": "GBP/USD"}, headers=H)
check(f"execute refuses while the feed is down ({r.status_code})", r.status_code == 503)

# ---- the client cannot dictate the trade ----------------------------------
# /api/agent/execute used to write whatever candidate the browser posted.
base.snapshot = lambda: {"provider": "oanda", "quotes": [
    {"pair": "GBP/USD", "price": 1.30, "bid": 1.2999, "ask": 1.3001,
     "timestamp": base.now(), "tradeable": True, "source": "oanda-practice"}]}
forged = {
    "pair": "GBP/USD", "direction": "buy", "status": "trade_candidate",
    "entry": 0.0001, "entry_price": 0.0001, "stop_loss": 0.00005,
    "take_profit": 99999.0, "risk_amount": 999999.0, "confidence": 100,
}
r = client.post("/api/agent/execute", json={"pair": "GBP/USD", "candidate": forged}, headers=H)
check(f"a forged candidate is not written as posted ({r.status_code})", r.status_code != 200)
if r.status_code == 200:
    t = r.json()["trade"]
    check("entry was re-priced by the server", float(t["entry_price"]) != 0.0001)
    check("risk was re-computed by the server", float(t["risk_amount"]) != 999999.0)
check("no forged trade reached the store",
      not any(float(t.get("risk_amount") or 0) == 999999.0 for t in base.TRADES))

# ---- provenance ------------------------------------------------------------
def label(**t): return names._origin_label(t)
check("the agent's own trades read AGENT TRADE", label(trade_origin="agent_auto") == "AGENT TRADE")
check("a scanner setup you executed reads Manual-Scanner",
      label(trade_origin="scanner_manual_execute") == "Manual-Scanner")
check("an AI-found setup opened from the chart is also Manual-Scanner",
      label(trade_origin="ai_quick_open") == "Manual-Scanner")
check("levels you drew yourself are Personal", label(trade_origin="personal_quick_open") == "Personal")

# Older rows recorded no origin. The agent did not exist then, so they were all
# placed by a person - setup_type says whether the scanner found the setup.
check("a legacy trend-continuation row is Manual-Scanner, not Unknown",
      label(setup_type="live_data_trend_continuation") == "Manual-Scanner")
check("a legacy mean-reversion row is Manual-Scanner",
      label(setup_type="live_data_mean_reversion") == "Manual-Scanner")
check("a legacy personal row is Personal",
      label(setup_type="personal_quick_paper_trade") == "Personal")
check("a genuinely unattributable row is still Unknown", label(setup_label="Whatever") == "Unknown")
# The old substring test matched the letters "ai" anywhere in the setup text.
check("a setup containing the letters 'ai' is not mislabelled",
      label(setup_label="Waiting for available retest") == "Unknown")
check("nothing is credited to the agent by inference",
      all(label(setup_type=k) != "AGENT TRADE" for k in base.LEGACY_SETUP_ORIGINS))

# The performance split must bucket legacy rows the same way, or the
# AI-versus-manual comparison silently drops every trade placed before origins
# were recorded.
base.TRADES.clear()
base.TRADES.extend([
    {"id": "l1", "user_name": USER, "status": "closed", "pair": "EUR/GBP", "direction": "buy",
     "result_r": 1.0, "result_money": 50.0, "risk_amount": 50.0, "confidence": 88,
     "setup_type": "live_data_trend_continuation", "setup_label": "Live-data trend continuation",
     "created_at": "2026-09-01T10:00:00", "closed_at": "2026-09-01T12:00:00"},
    {"id": "l2", "user_name": USER, "status": "closed", "pair": "EUR/GBP", "direction": "buy",
     "result_r": -1.0, "result_money": -50.0, "risk_amount": 50.0, "confidence": 0,
     "trade_origin": "agent_auto", "setup_type": "live_data_trend_continuation",
     "created_at": "2026-09-02T10:00:00", "closed_at": "2026-09-02T12:00:00"},
])
buckets = base._group_perf(base.TRADES, base.origin_label)
check("legacy scanner rows land under Manual-Scanner", "Manual-Scanner" in buckets)
check("the agent's row lands under AGENT TRADE", "AGENT TRADE" in buckets)
check("they are not lumped together", buckets["Manual-Scanner"]["total_r"] != buckets["AGENT TRADE"]["total_r"])

# ---- the loss limits must stop a person, not just the agent ---------------
# These were reported as a hardcoded 0.0 by every status endpoint and enforced
# only inside the agent, so you could keep opening trades by hand well past the
# daily limit printed on your own Risk Rules card.
base.TRADES.clear()
base.snapshot = lambda: {"provider": "oanda", "quotes": [
    {"pair": "GBP/USD", "price": 1.30, "bid": 1.2999, "ask": 1.3001,
     "timestamp": base.now(), "tradeable": True, "source": "oanda-practice"}]}

clean = base.trading_allowed(USER)
check("with no losses, trading is allowed", clean["allowed"] is True)
check("and the daily loss reads zero honestly", clean["daily_loss_pct"] == 0.0)

# A loss big enough to breach the 1.5% daily limit on the starting balance.
breach = round(base.START_BALANCE * (base.DAILY_LIMIT / 100) * 1.2, 2)
base.TRADES.append({"id": "big", "user_name": USER, "status": "closed",
                    "pair": "GBP/USD", "direction": "buy", "result_r": -1.0,
                    "result_money": -breach, "risk_amount": 50.0,
                    "created_at": base.now(), "closed_at": base.now()})

state = base.trading_allowed(USER)
check(f"a real daily loss is measured ({state['daily_loss_pct']}%)", state["daily_loss_pct"] > 0)
check("it is no longer reported as zero", state["daily_loss_pct"] != 0.0)
check("the daily limit registers as breached", state["daily_breached"] is True)
check("trading is refused", state["allowed"] is False)
check("and the reason names the limit", "Daily loss limit" in (state["reason"] or ""))

for path, body in [
    ("/api/agent/trades/quick-open",
     {"pair": "GBP/USD", "direction": "buy", "entry": 1.30, "stop_loss": 1.29, "take_profit": 1.32}),
    ("/api/agent/trades/quick-open-ai", {"pair": "GBP/USD"}),
    ("/api/agent/execute", {"pair": "GBP/USD"}),
]:
    r = client.post(path, json=body, headers=H)
    check(f"{path} refuses past the daily limit ({r.status_code})", r.status_code == 403)

check("no trade was opened past the limit",
      not any(t.get("status") == "open" for t in base.TRADES))

# And the status endpoint must show the real figure, not 0.0
status = client.get("/api/agent/status", headers=H).json()
ta = status.get("trading_allowed", {})
check(f"status reports the real daily loss ({ta.get('daily_loss_pct')}%)", ta.get("daily_loss_pct", 0) > 0)
check("status reports trading as blocked", ta.get("allowed") is False)

print(); print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
