import os, sys, pathlib
os.environ["TEMP_PASSWORDLESS_LOGIN"] = "true"
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend import paper_mvp_persistent as base

ok = True
def check(name, cond):
    global ok
    print(("PASS  " if cond else "FAIL  ") + name)
    ok = ok and cond

BAL = 10000.0
cap_pct = base.MAX_GOLD_RISK_PCT
cap_money = BAL * cap_pct / 100.0
print(f"cap = {cap_pct}% of £{BAL:,.0f} = £{cap_money:,.2f}\n")

# ---- the real trade from the journal: XAU/USD Buy #027 --------------------
# entry 4531.430, stop 4530.430 -> $1.00 stop, 1000 fixed units = £1,000 risk
units, risk, note = base.cap_gold_risk("XAU/USD", 1000.0, 1000.0, 1.00, BAL)
check("the real gold trade gets capped", note is not None)
check(f"risk cut from £1,000 to £{risk:,.2f}", risk == round(cap_money, 2))
check(f"units cut from 1000 to {units}", units == round(cap_money / 1.00, 2))
check("the original request is recorded", note["requested_risk_amount"] == 1000.0 and note["requested_units"] == 1000.0)

# ---- the default gold stop is even worse: 25 pips = $2.50 ----------------
units2, risk2, note2 = base.cap_gold_risk("XAU/USD", 1000.0, 2500.0, 2.50, BAL)
check("default-stop gold trade capped too", note2 is not None)
check(f"£2,500 risk cut to £{risk2:,.2f}", risk2 == round(cap_money, 2))
check("capped units still give the capped risk", round(units2 * 2.50, 2) == risk2)

# ---- a gold trade already inside the cap is untouched ---------------------
small = base.cap_gold_risk("XAU/USD", 10.0, 25.0, 2.50, BAL)
check("small gold trade left alone", small == (10.0, 25.0, None))

# ---- exactly at the cap is not capped ------------------------------------
exact = base.cap_gold_risk("XAU/USD", 20.0, cap_money, 2.50, BAL)
check("gold trade exactly at the cap is untouched", exact[2] is None)

# ---- other pairs are NOT affected ----------------------------------------
for pair, units_in, risk_in, dist in [
    ("GBP/USD", 1000.0, 2.0, 0.0020),
    ("EUR/USD", 100000.0, 200.0, 0.0020),   # deliberately large
    ("USD/JPY", 1000.0, 20.0, 0.020),
    ("GBP/JPY", 1000.0, 20.0, 0.020),
    ("EUR/GBP", 1000.0, 2.0, 0.0020),
]:
    res = base.cap_gold_risk(pair, units_in, risk_in, dist, BAL)
    check(f"{pair} untouched by the gold cap", res == (units_in, risk_in, None))

# ---- degenerate inputs are safe ------------------------------------------
check("zero stop distance is safe", base.cap_gold_risk("XAU/USD", 1000.0, 1000.0, 0.0, BAL)[2] is None)
check("zero risk is safe", base.cap_gold_risk("XAU/USD", 0.0, 0.0, 2.5, BAL)[2] is None)
check("zero balance is safe", base.cap_gold_risk("XAU/USD", 1000.0, 1000.0, 2.5, 0.0)[2] is None)

# ---- end to end through the real personal-trade path ---------------------
from backend import paper_mvp_quick_trade as quick

quick._latest_quote = lambda pair: {
    "pair": pair, "price": 4500.0, "bid": 4499.9, "ask": 4500.1,
    "spread_pips": 2, "source": "oanda-practice",
}
saved = {}
quick.compat.compat_save_trade = lambda user, t: (saved.update(t), t)[1]
quick.compat.compat_add_audit = lambda *a, **k: None
quick._duplicate_open_trade = lambda u, p, d: None

req = quick.QuickOpenRequest(pair="XAU/USD", direction="buy", account_balance=BAL,
                             stop_pips=25.0, fixed_units=1000.0)
trade = quick._save_personal_trade("Jake", req)
check("personal gold trade is capped end to end", trade["risk_cap"] is not None)
check(f"personal gold risk is £{trade['risk_amount']:,.2f}", trade["risk_amount"] == round(cap_money, 2))
check("a stop-out would now lose the cap, not £2,500",
      round(trade["risk_amount"] * 1.0, 2) == round(cap_money, 2))

req_fx = quick.QuickOpenRequest(pair="GBP/USD", direction="buy", account_balance=BAL,
                                stop_pips=20.0, fixed_units=1000.0)
quick._latest_quote = lambda pair: {
    "pair": pair, "price": 1.3550, "bid": 1.3549, "ask": 1.3551,
    "spread_pips": 2, "source": "oanda-practice",
}
trade_fx = quick._save_personal_trade("Jake", req_fx)
check("personal GBP/USD trade is not capped", trade_fx["risk_cap"] is None)
check("GBP/USD keeps its 1000 units", trade_fx["position_units"] == 1000.0)

print()
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
