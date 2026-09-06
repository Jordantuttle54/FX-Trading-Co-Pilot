import os, sys, pathlib
os.environ["TEMP_PASSWORDLESS_LOGIN"] = "true"
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend import paper_mvp_auto_close as ac
from backend import paper_mvp_persistent as base

ok = True
def check(name, cond):
    global ok
    print(("PASS  " if cond else "FAIL  ") + name)
    ok = ok and cond

# A real GBP/USD buy: entry 1.3540, stop 1.3520, target 1.3580
buy = {"id": "t1", "user_name": "Jake", "status": "open", "pair": "GBP/USD",
       "direction": "buy", "entry_price": 1.3540, "entry": 1.3540,
       "stop_loss": 1.3520, "take_profit": 1.3580, "target": 1.3580,
       "risk_amount": 50.0}
sell = dict(buy, id="t2", direction="sell", stop_loss=1.3560, take_profit=1.3500, target=1.3500)

def q(bid, ask, source="oanda-practice"):
    return {"pair": "GBP/USD", "price": (bid + ask) / 2, "bid": bid, "ask": ask, "source": source}

# ---- the reported bug: a synthetic price must never close anything ---------
synthetic = q(1.26834, 1.26854, source="synthetic-fallback")
check("synthetic price does NOT stop out a buy", ac._hit_reason(buy, synthetic) is None)
check("synthetic price does NOT stop out a sell", ac._hit_reason(sell, synthetic) is None)
check("synthetic quote is detected", ac._is_synthetic(synthetic))
check("real quote is not flagged synthetic", not ac._is_synthetic(q(1.3530, 1.3532)))

# ---- genuine stop-outs still fire on real prices ---------------------------
# closing a buy uses the bid
check("buy stops out when bid is below the stop", ac._hit_reason(buy, q(1.3515, 1.3517)) == "stop_loss_hit")
check("buy hits target when bid is above it", ac._hit_reason(buy, q(1.3585, 1.3587)) == "take_profit_hit")
check("buy left open between the levels", ac._hit_reason(buy, q(1.3550, 1.3552)) is None)

# closing a sell uses the ask
check("sell stops out when ask is above the stop", ac._hit_reason(sell, q(1.3563, 1.3565)) == "stop_loss_hit")
check("sell hits target when ask is below it", ac._hit_reason(sell, q(1.3495, 1.3497)) == "take_profit_hit")
check("sell left open between the levels", ac._hit_reason(sell, q(1.3530, 1.3532)) is None)

# ---- exactly at the level counts as hit ------------------------------------
check("buy stops out exactly at the stop", ac._hit_reason(buy, q(1.3520, 1.3522)) == "stop_loss_hit")

# ---- the fill price is the level, not the gapped price ---------------------
gapped = q(1.3400, 1.3402)   # real price, far through the stop
res = ac._close_trade_at_market("Jake", dict(buy), gapped, "stop_loss_hit")
check("gapped stop-out fills AT the stop level", res["close_price"] == 1.3520)
check("gapped stop-out is exactly -1R", res["result_r"] == -1.0)
check("gapped stop-out loses exactly the risk", res["result_money"] == -50.0)

tp = ac._close_trade_at_market("Jake", dict(buy), q(1.3700, 1.3702), "take_profit_hit")
check("take profit fills AT the target", tp["close_price"] == 1.3580)
check("take profit pays the intended 2R", tp["result_r"] == 2.0)

# ---- manage_trades must also ignore synthetic prices -----------------------
real_snap = {"quotes": [{"pair": "GBP/USD", "price": 1.3530, "source": "oanda-practice"}]}
syn_snap = {"quotes": [{"pair": "GBP/USD", "price": 1.2700, "source": "synthetic-fallback"}]}

base.snapshot = lambda: syn_snap
base.list_trades = lambda u, s=None: [dict(buy)]
check("manage_trades closes nothing on synthetic prices", base.manage_trades("Jake") == [])

base.snapshot = lambda: real_snap
check("manage_trades closes nothing when price is between levels", base.manage_trades("Jake") == [])

print()
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
