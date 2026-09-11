"""Why the agent is not trading - the question the status panel could not answer.

The gates the panel knew about are the ones that stop the agent looking:
switched off, kill switch, loss limit, window, position count. An agent that
looks at every pair and refuses every one trips none of them, so the panel
read "ON - TRADING" for days while nothing opened and nothing said why.
"""
import os, sys, pathlib
os.environ["TEMP_PASSWORDLESS_LOGIN"] = "true"; os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from backend import paper_mvp_agent_runner as agent

ok = True
def check(n, c):
    global ok; print(("PASS  " if c else "FAIL  ") + n); ok = ok and c


def skips(*reasons):
    return {"halted": False, "opened": [],
            "skipped": [{"pair": f"P{i}", "reason": r} for i, r in enumerate(reasons)]}


# ---- one run's verdict -----------------------------------------------------
v = agent.run_verdict(skips(
    "Confidence 73% is below 85%.",
    "Confidence 61% is below 85%.",
    "No setup.",
))
check("a run that opened nothing is not marked as traded", v["traded"] is False)
check("the headline counts the pairs refused", "3 pairs" in v["headline"])
check(f"and names the dominant reason ({v['headline']})", "confidence" in v["headline"])
check("the breakdown groups by reason, not by wording",
      [b["pairs"] for b in v["breakdown"]] == [2, 1])
check("the two differently-worded confidence rejections collapse into one",
      v["breakdown"][0]["reason"] == "confidence was below the threshold")

opened = agent.run_verdict({"halted": False, "skipped": [], "opened": [{"pair": "GBP/USD"}]})
check("a run that opened something says so", opened["traded"] is True)
check("and does not report a refusal breakdown", opened["breakdown"] == [])

halt = agent.run_verdict({"halted": True, "halt_reason": "Agent is switched off.", "opened": [], "skipped": []})
check("a halted run reports the halt itself", halt["headline"] == "Agent is switched off.")
check("and is not counted as trading", halt["traded"] is False)

# ---- the dry spell, across runs -------------------------------------------
# The case that prompted this: enabled, unblocked, scanning on schedule,
# refusing everything, panel showing ON - TRADING.
runs = [skips("Confidence 70% is below 85%.", "No setup.") for _ in range(12)]
for r in runs:
    r["verdict"] = agent.run_verdict(r)
spell = agent.dry_spell(runs)
check("the dry spell counts every run since the last trade", spell["runs_since_trade"] == 12)
check(f"and says so plainly ({spell['headline']})", "12 runs" in spell["headline"])
check("and totals the reasons across runs, not within one",
      spell["breakdown"][0]["pairs"] == 12)

# A trade in the middle stops the count there - it is a dry spell, not a total.
mixed = [skips("No setup.") for _ in range(4)]
for r in mixed:
    r["verdict"] = agent.run_verdict(r)
traded = {"halted": False, "skipped": [], "opened": [{"pair": "GBP/USD"}]}
traded["verdict"] = agent.run_verdict(traded)
spell2 = agent.dry_spell(mixed + [traded] + mixed)
check("the count stops at the last trade", spell2["runs_since_trade"] == 4)

recent = [dict(traded)]
check("no dry spell when the newest run traded", agent.dry_spell(recent)["runs_since_trade"] == 0)
check("and no headline to show", agent.dry_spell(recent)["headline"] == "")

# ---- a halt leads, because it means it never looked ------------------------
halted_runs = [{"halted": True, "halt_reason": "Outside the London trading window.",
                "opened": [], "skipped": []} for _ in range(6)]
for r in halted_runs:
    r["verdict"] = agent.run_verdict(r)
hs = agent.dry_spell(halted_runs)
check("a run of halts is reported as the halt reason",
      "Outside the London trading window." in hs["headline"])
check("and the halts are counted", hs["halts"][0]["runs"] == 6)

# ---- an old run with no stored verdict still answers -----------------------
# Runs recorded before this existed have no verdict key; the rollup must not
# skip them or the dry spell silently resets on deploy.
legacy = [{"halted": False, "opened": [], "skipped": [{"pair": "GBP/USD", "reason": "No setup."}]}]
check("a run stored before verdicts existed is still read",
      agent.dry_spell(legacy)["runs_since_trade"] == 1)

# ---- the calendar outage is its own class, not "other" ---------------------
cal = agent.run_verdict(skips(
    "Economic calendar unavailable, so upcoming releases are unknown (HTTPError: 401).",
    "Economic calendar unavailable, so upcoming releases are unknown (HTTPError: 401).",
))
check("a calendar outage is named as such",
      cal["breakdown"][0]["reason"] == "the economic calendar could not be reached")
news = agent.run_verdict(skips("USD Non-Farm Payrolls in 12 min - inside the 30 minute news blackout."))
check("and a real blackout is a different reason from an outage",
      news["breakdown"][0]["reason"] == "a high-impact release was inside the blackout window")

print(); print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
