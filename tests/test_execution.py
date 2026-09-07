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

# --- the spread guard -------------------------------------------------------
# The real failure this came from: GBP/USD at the 17:00 New York rollover
# quoted a 19.5 pip spread against a 12 pip stop. Nothing in this file
# stopped it; only the broker declining the fill did.
#
# _place_oanda_demo_trade catches its own failures and reports them as
# {"status": "error", "error": ...} rather than raising - the endpoint turns
# that into a 502 - so these read the returned dict.
class WideSpreadClient(FakeClient):
    def get(self, url, params=None, headers=None):
        # 19.5 pips wide, against CANDIDATE's 20 pip stop.
        return FakeResponse({"prices": [{"closeoutAsk": "1.30105", "closeoutBid": "1.29910"}]})

execution.httpx.Client = WideSpreadClient
wide = execution._place_oanda_demo_trade(CANDIDATE)
check("a spread wider than the guard does not open", wide["status"] != "filled")
check("the refusal explains itself", "Refusing to open" in (wide["error"] or ""))
check(f"and says how wide, in pips ({wide['error'].split(' against')[0]})",
      "19.5 pips" in wide["error"])

class NormalSpreadClient(FakeClient):
    def get(self, url, params=None, headers=None):
        # 2 pips against a 20 pip stop - 10% of the risk, well inside the cap.
        return FakeResponse({"prices": [{"closeoutAsk": "1.30010", "closeoutBid": "1.29990"}]})

execution.httpx.Client = NormalSpreadClient
check("a normal spread still trades", execution._place_oanda_demo_trade(CANDIDATE)["status"] == "filled")

# A JPY pair prices to 3 decimals; the guard must read pips in that scale
# rather than reporting a 20 pip spread as 2000.
jpy = {**CANDIDATE, "pair": "GBP/JPY", "entry": 195.000, "stop_loss": 194.800, "take_profit": 195.400}
class JpyWideClient(FakeClient):
    def get(self, url, params=None, headers=None):
        return FakeResponse({"prices": [{"closeoutAsk": "195.150", "closeoutBid": "194.950"}]})

execution.httpx.Client = JpyWideClient
jpy_result = execution._place_oanda_demo_trade(jpy)
check("a wide JPY spread does not open", jpy_result["status"] != "filled")
check(f"JPY pips are read at 0.01 ({jpy_result['error'].split(' against')[0]})",
      "20.0 pips" in jpy_result["error"])

# --- a cancelled order says why ---------------------------------------------
# OANDA cancels rather than rejects when it cannot fill, and only the reject
# shape was being read - so a halted market surfaced as "did not return a
# fill", which says nothing about what to do next.
class HaltedClient(NormalSpreadClient):
    def post(self, url, headers=None, json=None):
        return FakeResponse({"orderCancelTransaction": {"reason": "MARKET_HALTED"}})

execution.httpx.Client = HaltedClient
halted = execution._place_oanda_demo_trade(CANDIDATE)
check("a cancelled order does not open", halted["status"] != "filled")
check("a cancelled order explains itself", "market was halted" in halted["error"])
check("and keeps OANDA's own code", "MARKET_HALTED" in halted["error"])
check("and is not the old blank message", "did not return a fill" not in halted["error"])

class UnknownCancelClient(NormalSpreadClient):
    def post(self, url, headers=None, json=None):
        return FakeResponse({"orderCancelTransaction": {"reason": "SOMETHING_NEW"}})

execution.httpx.Client = UnknownCancelClient
check("an unmapped reason still reaches the user",
      "SOMETHING_NEW" in execution._place_oanda_demo_trade(CANDIDATE)["error"])

execution.httpx.Client = FakeClient

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
