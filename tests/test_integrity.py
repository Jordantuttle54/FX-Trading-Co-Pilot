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
check("the agent's own trades are AI", label(trade_origin="agent_auto") == "AI")
check("a hand-placed quick trade is Personal", label(trade_origin="personal_quick_open") == "Personal")
check("executing a scanner setup yourself is Personal",
      label(trade_origin="scanner_manual_execute") == "Personal")
check("an AI-sourced setup you opened is still yours",
      label(trade_origin="ai_quick_open") == "Personal")
check("a trade with no recorded origin is Unknown, not AI", label(setup_label="Whatever") == "Unknown")
# The old substring test matched the letters "ai" anywhere in the setup text.
check("a setup containing the letters 'ai' is not mislabelled AI",
      label(setup_label="Waiting for available retest") == "Unknown")

print(); print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
