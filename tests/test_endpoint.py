import os, sys, json, pathlib
os.environ["TEMP_PASSWORDLESS_LOGIN"] = "true"
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
from api.index import app
from backend import paper_mvp_persistent as base

USER = "Jake"

def seed():
    base.TRADES.clear()
    base.TRADES.extend([
        # The reported bug: gold stop-out filled 50 dollars past the stop.
        {"id": "g1", "user_name": USER, "status": "closed", "pair": "XAU/USD",
         "direction": "buy", "entry_price": 2350.0, "entry": 2350.0,
         "stop_loss": 2347.5, "take_profit": 2355.0, "target": 2355.0,
         "risk_amount": 50.0, "close_reason": "stop_loss_hit", "close_price": 2300.0,
         "result_r": -20.0, "result_money": -1000.0, "created_at": "2026-08-18T10:00:00",
         "setup_label": "Personal quick paper trade"},
        # A correctly-recorded stop-out - must be left alone.
        {"id": "g2", "user_name": USER, "status": "closed", "pair": "EUR/GBP",
         "direction": "sell", "entry_price": 0.8550, "entry": 0.8550,
         "stop_loss": 0.8570, "take_profit": 0.8510, "target": 0.8510,
         "risk_amount": 50.0, "close_reason": "stop_loss_hit", "close_price": 0.8570,
         "result_r": -1.0, "result_money": -50.0, "created_at": "2026-08-18T11:00:00",
         "setup_label": "Personal quick paper trade"},
        # A manual close at market - must be left alone even though it looks big.
        {"id": "g3", "user_name": USER, "status": "closed", "pair": "GBP/USD",
         "direction": "buy", "entry_price": 1.2700, "entry": 1.2700,
         "stop_loss": 1.2680, "take_profit": 1.2740, "target": 1.2740,
         "risk_amount": 50.0, "close_reason": "Quick close at market from dashboard",
         "close_price": 1.2500, "result_r": -10.0, "result_money": -500.0,
         "created_at": "2026-08-18T12:00:00", "setup_label": "Personal quick paper trade"},
        # An open trade - must be left alone.
        {"id": "g4", "user_name": USER, "status": "open", "pair": "USD/JPY",
         "direction": "buy", "entry_price": 156.20, "entry": 156.20,
         "stop_loss": 156.00, "take_profit": 156.60, "target": 156.60,
         "risk_amount": 50.0, "created_at": "2026-08-18T13:00:00"},
    ])

def check(name, cond):
    print(("PASS  " if cond else "FAIL  ") + name)
    return cond

client = TestClient(app)
token = client.post("/api/auth/login", json={"username": USER, "passcode": ""}).json()["access_token"]
H = {"Authorization": f"Bearer {token}"}
ok = True

# --- auth is enforced -------------------------------------------------------
ok &= check("endpoint rejects unauthenticated calls",
            client.post("/api/agent/trades/repair-trigger-fills", json={"apply": False}).status_code == 401)

# --- dry run ----------------------------------------------------------------
seed()
preview = client.post("/api/agent/trades/repair-trigger-fills", json={"apply": False}, headers=H).json()
ok &= check("preview reports applied=False", preview["applied"] is False)
ok &= check("preview finds exactly 1 affected trade", preview["affected_count"] == 1)
ok &= check("preview checks only closed trades (3)", preview["closed_trades_checked"] == 3)
ok &= check("preview targets the gold trade", preview["repairs"][0]["trade_id"] == "g1")
ok &= check("preview credits +950.00", preview["money_delta"] == 950.0)
ok &= check("DRY RUN did not mutate stored trade",
            [t for t in base.TRADES if t["id"] == "g1"][0]["result_money"] == -1000.0)

# --- apply ------------------------------------------------------------------
applied = client.post("/api/agent/trades/repair-trigger-fills", json={"apply": True}, headers=H).json()
ok &= check("apply reports applied=True", applied["applied"] is True)
ok &= check("apply repaired 1 trade", applied["affected_count"] == 1)

g1 = [t for t in base.TRADES if t["id"] == "g1"][0]
ok &= check("stored result_r is now -1R", g1["result_r"] == -1.0)
ok &= check("stored result_money is now -50.00", g1["result_money"] == -50.0)
ok &= check("stored close_price is the stop level", g1["close_price"] == 2347.5)
ok &= check("original values preserved for audit",
            g1["result_repair"]["original_result_money"] == -1000.0)

# untouched rows really are untouched
g2 = [t for t in base.TRADES if t["id"] == "g2"][0]
g3 = [t for t in base.TRADES if t["id"] == "g3"][0]
g4 = [t for t in base.TRADES if t["id"] == "g4"][0]
ok &= check("correct trade untouched", g2["result_money"] == -50.0 and "result_repair" not in g2)
ok &= check("manual close untouched", g3["result_money"] == -500.0 and "result_repair" not in g3)
ok &= check("open trade untouched", g4["status"] == "open" and "result_r" not in g4)

# --- idempotency ------------------------------------------------------------
again = client.post("/api/agent/trades/repair-trigger-fills", json={"apply": True}, headers=H).json()
ok &= check("re-running finds nothing left to repair", again["affected_count"] == 0)
ok &= check("re-running leaves the value at -50.00",
            [t for t in base.TRADES if t["id"] == "g1"][0]["result_money"] == -50.0)

# --- wallet reflects the repair --------------------------------------------
wallet = client.get("/api/agent/wallet", headers=H).json()
# -50 (gold, repaired) + -50 (eurgbp) + -500 (manual) = -600 realised
expected = round(base.START_BALANCE - 600.0, 2)
ok &= check(f"wallet balance recomputed to {expected}", wallet["balance"] == expected)
ok &= check("wallet realised P&L is -600.00", wallet["realised_pnl"] == -600.0)

# save the real preview payload for the UI test to use as a fixture
seed()
fixture = client.post("/api/agent/trades/repair-trigger-fills", json={"apply": False}, headers=H).json()

print()
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
