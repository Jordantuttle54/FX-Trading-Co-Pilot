import os, sys, json, pathlib
os.environ["TEMP_PASSWORDLESS_LOGIN"] = "true"
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend import paper_mvp_persistent as base

ok = True
def check(name, cond):
    global ok
    print(("PASS  " if cond else "FAIL  ") + name)
    ok = ok and cond

def candles(prices):
    out = []
    for i, p in enumerate(prices):
        out.append({"time": f"t{i}", "open": p, "high": p * 1.001, "low": p * 0.999, "close": p, "volume": 100})
    return out

# A clean uptrend: steadily rising, averages separated.
uptrend = candles([1.30 + i * 0.0008 for i in range(120)])
# A flat chop: no separation, RSI mid.
chop = candles([1.30 + (0.0005 if i % 2 else -0.0005) for i in range(120)])
# A sharp spike up: RSI stretched high, but trend separation grows too.
spike = candles([1.30] * 90 + [1.30 + i * 0.004 for i in range(30)])

# ---- the default strategy is unchanged ------------------------------------
c = base.score_candidate("GBP/USD", 10000.0, None, uptrend)
check("default strategy is trend continuation", c["strategy"] == "trend_continuation")
check("setup_type unchanged for trend continuation", c["setup_type"] == "live_data_trend_continuation")
check("setup_label unchanged", c["setup_label"] == "Live-data trend continuation")
check("entry_reason still reads naturally",
      c["entry_reason"].endswith("based on live/demo candle trend structure."))
check("uptrend produces a buy", c["direction"] == "buy")

flat = base.score_candidate("GBP/USD", 10000.0, None, chop)
check("chop is rejected or no-setup", flat["status"] in ("rejected", "no_setup"))

# ---- explicitly asking for the old strategy matches the default -----------
explicit = base.score_candidate("GBP/USD", 10000.0, None, uptrend, None, "trend_continuation")
for field in ["direction", "confidence", "status", "entry_price", "stop_loss", "take_profit",
              "rr_estimate", "stop_pips", "position_units", "risk_amount", "rejection_reason"]:
    check(f"explicit call matches default on {field}", explicit[field] == c[field])

# ---- mean reversion is a real, different strategy -------------------------
mr = base.score_candidate("GBP/USD", 10000.0, None, spike, None, "mean_reversion")
check("mean reversion identifies itself", mr["strategy"] == "mean_reversion")
check("mean reversion has its own setup type", mr["setup_type"] in ("live_data_mean_reversion", "no_trade"))
tc = base.score_candidate("GBP/USD", 10000.0, None, spike, None, "trend_continuation")
rsi = tc["analysis"]["indicators"]["rsi"]
print(f"      (spike RSI = {rsi})")
if rsi is not None and rsi >= 78:
    check("on a stretched spike, mean reversion goes the opposite way to trend", mr["direction"] != tc["direction"])
    check("mean reversion uses its own tighter RR", mr["rr_estimate"] != tc["rr_estimate"] or mr["direction"] == "none")

# ---- registry and enabled list -------------------------------------------
check("both strategies registered", set(base.STRATEGIES) == {"trend_continuation", "mean_reversion"})
check("default enabled list is trend only", base.enabled_strategies({}) == ["trend_continuation"])
check("unknown names are ignored", base.enabled_strategies({"strategies": ["nope"]}) == ["trend_continuation"])
check("a string is accepted", base.enabled_strategies({"strategies": "mean_reversion"}) == ["mean_reversion"])
check("both can be enabled",
      base.enabled_strategies({"strategies": ["trend_continuation", "mean_reversion"]}) ==
      ["trend_continuation", "mean_reversion"])

# ---- score_candidates runs several and ranks them -------------------------
multi = base.score_candidates("GBP/USD", 10000.0, None, uptrend,
                              {"strategies": ["trend_continuation", "mean_reversion"]})
check("score_candidates returns one per strategy", len(multi) == 2)
check("results carry distinct strategies", {m["strategy"] for m in multi} == {"trend_continuation", "mean_reversion"})
statuses = [m["status"] == "trade_candidate" for m in multi]
check("executable candidates sort ahead of rejected ones", statuses == sorted(statuses, reverse=True))

single = base.score_candidates("GBP/USD", 10000.0, None, uptrend)
check("score_candidates defaults to just the one strategy", len(single) == 1)
check("and it is the trend strategy", single[0]["strategy"] == "trend_continuation")

# ---- gold config still applies across strategies --------------------------
gold = base.score_candidate("XAU/USD", 10000.0, 1000.0, candles([4500 + i * 0.9 for i in range(120)]))
check("gold risk cap still applies via the scanner", gold["risk_cap"] is not None or gold["risk_amount"] <= 50.01)

print()
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
