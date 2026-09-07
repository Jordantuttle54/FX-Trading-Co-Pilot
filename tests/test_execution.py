"""The broker order path: risk must be exactly what the position was sized for."""
import os, sys, pathlib, json
os.environ["TEMP_PASSWORDLESS_LOGIN"] = "true"; os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import httpx
from backend import execution

ok = True
def check(n, c):
    global ok; print(("PASS  " if c else "FAIL  ") + n); ok = ok and c

CANDIDATE = {
    "pair": "GBP/USD", "direction": "buy",
    "entry": 1.30000, "stop_loss": 1.29800, "take_profit": 1.30400,
    "position_units": 25000.0, "risk_pct": 0.5, "risk_amount": 50.0,
}
STOP_DIST, TARGET_DIST = 0.00200, 0.00400
SLIPPED_FILL = 1.30035   # filled 3.5 pips away from the quote we sized against

sent = {}

class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload, self.status_code, self.text = payload, status, json.dumps(payload)
    def json(self): return self._payload
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError(self.text)

class FakeClient:
    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def get(self, url, params=None, headers=None):
        return FakeResponse({"prices": [{"closeoutAsk": "1.30010", "closeoutBid": "1.29990"}]})
    def post(self, url, headers=None, json=None):
        sent.clear(); sent.update(json)
        return FakeResponse({"orderFillTransaction": {
            "id": "12345", "price": str(SLIPPED_FILL), "time": "2026-09-07T10:00:00Z",
            "halfSpreadCost": "0.35"}})

execution.httpx.Client = FakeClient
execution.settings.oanda_access_token = "test-token"
execution.settings.oanda_account_id = "test-account"
execution.settings.enable_live_trading = False

result = execution._place_oanda_demo_trade(dict(CANDIDATE))
check(f"the order fills ({result.get('status')})", result["status"] == "filled")

# --- the bracket must ride the fill, not a pre-fill guess ------------------
order = sent.get("order", {})
check("stop is sent as a distance, not an absolute price",
      "distance" in order.get("stopLossOnFill", {}) and "price" not in order.get("stopLossOnFill", {}))
check("target is sent as a distance too",
      "distance" in order.get("takeProfitOnFill", {}))
check(f"the stop distance is the one sized for ({order.get('stopLossOnFill', {}).get('distance')})",
      float(order["stopLossOnFill"]["distance"]) == round(STOP_DIST, 5))
check(f"the target distance is the one sized for ({order.get('takeProfitOnFill', {}).get('distance')})",
      float(order["takeProfitOnFill"]["distance"]) == round(TARGET_DIST, 5))

# --- what we record must match what the broker is actually holding ---------
check(f"entry recorded as the real fill ({result['entry']})", result["entry"] == SLIPPED_FILL)
risk = round(abs(result["entry"] - result["stop_loss"]), 5)
reward = round(abs(result["take_profit"] - result["entry"]), 5)
check(f"risk from the fill is exactly as sized ({risk})", risk == STOP_DIST)
check(f"reward from the fill is exactly as sized ({reward})", reward == TARGET_DIST)
# Before this, stop_loss was computed from the pre-fill quote (1.30010), so a
# 2.5-pip slip left the recorded risk at 0.00175 instead of 0.00200 - a trade
# meant to lose 1R would have lost about 1.14R.
check("the stop is not left anchored to the pre-fill quote", result["stop_loss"] != round(1.30010 - STOP_DIST, 5))
check(f"slippage is reported ({result['slippage']})", result["slippage"] > 0)

# --- a sell mirrors it ------------------------------------------------------
sell = dict(CANDIDATE, direction="sell", stop_loss=1.30200, take_profit=1.29600)
res_sell = execution._place_oanda_demo_trade(sell)
check("a sell fills", res_sell["status"] == "filled")
check("a sell's stop sits above its fill", res_sell["stop_loss"] > res_sell["entry"])
check("a sell's target sits below its fill", res_sell["take_profit"] < res_sell["entry"])
check("a sell is sent as negative units", int(sent["order"]["units"]) < 0)
check(f"a sell's risk is as sized ({round(abs(res_sell['stop_loss'] - res_sell['entry']), 5)})",
      round(abs(res_sell["stop_loss"] - res_sell["entry"]), 5) == STOP_DIST)

# --- live trading stays locked ---------------------------------------------
execution.settings.enable_live_trading = True
try:
    execution._active_mode()
    check("live trading is refused", False)
except RuntimeError as exc:
    check("live trading is refused outright", "LOCKED" in str(exc))
execution.settings.enable_live_trading = False

print(); print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
