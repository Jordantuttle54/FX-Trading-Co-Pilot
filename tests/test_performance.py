"""Performance reporting: the numbers must describe the trades that happened."""
import os, sys, pathlib
os.environ["TEMP_PASSWORDLESS_LOGIN"] = "true"; os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from fastapi.testclient import TestClient
from api.index import app
from backend import paper_mvp_persistent as base

USER = "Jake"; ok = True
def check(n, c):
    global ok; print(("PASS  " if c else "FAIL  ") + n); ok = ok and c

client = TestClient(app)
token = client.post("/api/auth/login", json={"username": USER, "passcode": ""}).json()["access_token"]
H = {"Authorization": f"Bearer {token}"}

def trade(i, r, pair="GBP/USD", origin="agent_auto", conf=90):
    return {"id": f"p{i}", "user_name": USER, "status": "closed", "pair": pair,
            "direction": "buy", "result_r": r, "result_money": r * 50.0,
            "risk_amount": 50.0, "trade_origin": origin, "confidence": conf,
            "setup_label": "Live-data trend continuation", "session": "London",
            "quality_tag": "take_profit" if r > 0 else "stop_loss",
            "created_at": f"2026-09-0{i}T10:00:00", "closed_at": f"2026-09-0{i}T12:00:00"}

# A run that goes +2, then -1, -1, -1 (a 3R drawdown), then +2.
base.TRADES.clear()
base.TRADES.extend([trade(1, 2.0), trade(2, -1.0), trade(3, -1.0),
                    trade(4, -1.0), trade(5, 2.0)])

check("drawdown is computed, not hardcoded", base.max_drawdown_r(base.TRADES) == 3.0)
check("a run with no losses has no drawdown",
      base.max_drawdown_r([trade(1, 1.0), trade(2, 1.0)]) == 0.0)
check("drawdown ignores open trades",
      base.max_drawdown_r([trade(1, -5.0), {"id": "x", "status": "open"}]) == 5.0)

r = client.get("/api/agent/performance", headers=H).json()
check(f"report is produced ({r.get('status')})", r["status"] == "ok")
check(f"reported drawdown is real ({r['max_drawdown_r']}R)", r["max_drawdown_r"] == 3.0)
check("total R is right", r["overall"]["total_r"] == 1.0)

# --- the breakdowns must actually break things down ------------------------
for field in ("by_pair", "by_origin", "by_setup", "by_session", "by_confidence", "by_tag"):
    check(f"{field} is populated", bool(r[field]))

check("by_pair keys on the pair", "GBP/USD" in r["by_pair"])
check("by_pair counts every trade", r["by_pair"]["GBP/USD"]["count"] == 5)

# --- AI versus manual, which is what origin was recorded for ---------------
base.TRADES.clear()
base.TRADES.extend([
    trade(1, 2.0, origin="agent_auto"), trade(2, 1.0, origin="agent_auto"),
    trade(3, 2.0, origin="agent_auto"),
    trade(4, -1.0, origin="personal_quick_open"),
    trade(5, -1.0, origin="personal_quick_open"),
    trade(6, -1.0, origin="personal_quick_open"),
])
r = client.get("/api/agent/performance", headers=H).json()
by_origin = r["by_origin"]
# Grouped by the label you actually read on screen, so the split matches the
# journal rather than needing a lookup table to interpret.
check("the agent's trades are reported separately", "AGENT TRADE" in by_origin)
check("hand-placed trades are reported separately", "Personal" in by_origin)
check(f"the agent's total R is its own ({by_origin['AGENT TRADE']['total_r']})",
      by_origin["AGENT TRADE"]["total_r"] == 5.0)
check(f"manual total R is its own ({by_origin['Personal']['total_r']})",
      by_origin["Personal"]["total_r"] == -3.0)
check("win rates differ between the two",
      by_origin["AGENT TRADE"]["win_rate"] != by_origin["Personal"]["win_rate"])
check("each group carries its own drawdown",
      by_origin["Personal"]["max_drawdown_r"] == 3.0)

# --- too little data is still reported honestly ----------------------------
base.TRADES.clear()
base.TRADES.extend([trade(1, 1.0), trade(2, 1.0)])
r = client.get("/api/agent/performance", headers=H).json()
check("a thin sample is refused rather than dressed up", r["status"] == "insufficient_data")

print(); print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
