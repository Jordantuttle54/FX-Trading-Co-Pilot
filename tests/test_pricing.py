"""Entry fills and dealing costs: the price must be one you could have traded at."""
import os, sys, pathlib
os.environ["TEMP_PASSWORDLESS_LOGIN"] = "true"; os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from backend import paper_mvp_persistent as base
from backend import backtest

ok = True
def check(n, c):
    global ok; print(("PASS  " if c else "FAIL  ") + n); ok = ok and c

# ---- executable entry ------------------------------------------------------
QUOTE = {"pair": "GBP/JPY", "bid": 208.940, "ask": 209.010, "price": 208.975}
CLOSE = 208.973   # last completed H1 candle, mid

buy, basis = base.executable_entry("GBP/JPY", "buy", CLOSE, QUOTE)
check("a buy is filled at the ask", buy == 209.010)
check("and is reported as an executable fill", basis == "executable-quote")

sell, _ = base.executable_entry("GBP/JPY", "sell", CLOSE, QUOTE)
check("a sell is filled at the bid", sell == 208.940)

check("a buy never fills better than the mid", buy >= QUOTE["price"])
check("a sell never fills better than the mid", sell <= QUOTE["price"])

# Without a live book there is nothing to lift - the backtester replays history.
hist, basis = base.executable_entry("GBP/JPY", "buy", CLOSE, None)
check("no quote falls back to the candle close", hist == CLOSE and basis == "candle-close")

for bad in ({"bid": None, "ask": None}, {"bid": 0, "ask": 0}, {}, {"ask": "n/a"}):
    got, b = base.executable_entry("GBP/JPY", "buy", CLOSE, bad)
    check(f"an unusable quote {bad} falls back rather than crashing",
          got == CLOSE and b == "candle-close")

check("a directionless scan is left alone",
      base.executable_entry("GBP/JPY", "none", CLOSE, QUOTE)[0] == CLOSE)

# ---- the stop distance must survive the entry moving -----------------------
# Shifting the entry to the executable price is only safe if the stop and
# target move with it, or the trade silently takes on more risk than sized for.
candles = [{"open": 1.30 + i * 0.0004, "high": 1.3005 + i * 0.0004,
            "low": 1.2995 + i * 0.0004, "close": 1.30 + i * 0.0004,
            "volume": 100} for i in range(120)]
gq = {"pair": "GBP/USD", "bid": 1.34000, "ask": 1.34020, "price": 1.34010}
a = base.score_candidate("GBP/USD", 10000.0, None, candles=candles)
b = base.score_candidate("GBP/USD", 10000.0, None, candles=candles, quote=gq)
if a["direction"] in ("buy", "sell"):
    da = abs(a["entry"] - a["stop_loss"]); db = abs(b["entry"] - b["stop_loss"])
    check(f"stop distance unchanged by the entry moving ({da:.5f} vs {db:.5f})",
          abs(da - db) < 1e-9)
    check("the entry itself did move", a["entry"] != b["entry"])
    check("R:R is unchanged", abs(a["rr_estimate"] - b["rr_estimate"]) < 1e-9)
    check("the fill basis is reported", b["entry_basis"] == "executable-quote")
else:
    check("scanner produced a directional setup to test against", False)

# ---- the backtest pays a spread -------------------------------------------
check("every watchlist pair has a spread", all(p in backtest.SPREAD_PIPS for p in base.WATCHLIST))
check("spread cost is a positive price distance", backtest.spread_cost("GBP/USD") > 0)
check("GBP/JPY costs more than EUR/USD",
      backtest.spread_cost("GBP/JPY") > backtest.spread_cost("EUR/USD"))
check("an unknown pair still gets charged", backtest.spread_cost("XXX/YYY") > 0)

# A stop-out must now cost slightly MORE than 1R, as it does on a real account.
sim = backtest._simulate_pair_trades("GBP/USD", candles * 3, 120)
if sim:
    stops = [t for t in sim if t["exit_reason"] == "stop_loss"]
    wins = [t for t in sim if t["exit_reason"] == "take_profit"]
    check("net result is always worse than gross",
          all(t["result_r"] < t["gross_result_r"] for t in sim))
    if stops:
        check(f"a stop-out costs more than 1R ({stops[0]['result_r']}R)", stops[0]["result_r"] < -1.0)
    if wins:
        check(f"a winner books less than its target ({wins[0]['result_r']}R)",
              wins[0]["result_r"] < wins[0]["gross_result_r"])
else:
    print("note: no simulated trades on this synthetic series - spread maths unexercised")

print(); print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
