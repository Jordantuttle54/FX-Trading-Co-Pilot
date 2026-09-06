import os, sys, json, pathlib
from datetime import datetime, timedelta, timezone
os.environ["TEMP_PASSWORDLESS_LOGIN"]="true"; os.environ.pop("DATABASE_URL",None)
os.environ.pop("NOTIFY_WEBHOOK_URL", None)
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from fastapi.testclient import TestClient
from api.index import app
from backend import paper_mvp_persistent as base
from backend import paper_mvp_agent_runner as agent
from backend import notify as notifier

USER="Jake"; ok=True
def check(n,c):
    global ok; print(("PASS  " if c else "FAIL  ")+n); ok = ok and c

client=TestClient(app)
tok=client.post("/api/auth/login",json={"username":USER,"passcode":""}).json()["access_token"]
H={"Authorization":f"Bearer {tok}"}

# ---- what gets alerted on, and what stays quiet ---------------------------
opened_run={"dry_run":False,"halted":False,"opened":[{"pair":"GBP/USD","direction":"buy","entry":1.35,
    "stop_loss":1.348,"take_profit":1.356,"strategy":"trend_continuation","confidence":88}],"skipped":[]}
a=notifier.summarise_run(opened_run)
check("opening a trade alerts", a and a["event"]=="agent_opened")
check("the alert names the pair and direction", "GBP/USD" in a["message"] and "BUY" in a["message"])

check("a routine window halt stays quiet",
      notifier.summarise_run({"halted":True,"halt_reason":"Outside the London trading window.","opened":[],"skipped":[]}) is None)
check("agent-off stays quiet",
      notifier.summarise_run({"halted":True,"halt_reason":"Agent is switched off.","opened":[],"skipped":[]}) is None)
risk=notifier.summarise_run({"halted":True,"halt_reason":"Daily loss limit reached (2.1% of 1.5%).","opened":[],"skipped":[]})
check("a loss-limit halt DOES alert", risk and risk["event"]=="agent_risk_halt")
check("a dry run never alerts", notifier.summarise_run({**opened_run,"dry_run":True}) is None)
check("a quiet scan with no setups stays quiet",
      notifier.summarise_run({"halted":False,"opened":[],"skipped":[{"pair":"GBP/USD","reason":"No setup."}]}) is None)
stale=notifier.summarise_run({"halted":False,"opened":[],
    "skipped":[{"pair":p,"reason":"Market looks closed - last quote is 900 min old."} for p in ["GBP/USD","EUR/USD"]]})
check("a fully blocked run alerts about market data", stale and stale["event"]=="agent_stale_data")

# ---- sending ---------------------------------------------------------------
check("no webhook configured = not sent, with a reason",
      notifier.send("t","m",{},"test") == {"sent":False,"reason":"No notification webhook configured."})
check("http:// is refused",
      notifier.send("t","m",{"notify_webhook":"http://x.test/hook"},"test")["sent"] is False)
check("an unknown event is refused", notifier.send("t","m",{"notify_webhook":"https://x/y"},"nope")["sent"] is False)

sent={}
class FakeResp:
    status_code=200
class FakeClient:
    def __init__(self,*a,**k): pass
    def __enter__(self): return self
    def __exit__(self,*a): return False
    def post(self,url,content=None,headers=None):
        sent.update(url=url,content=content,headers=headers); return FakeResp()
notifier.httpx.Client=FakeClient
r=notifier.send("Title","Body",{"notify_webhook":"https://ntfy.sh/mytopic"},"test")
check("ntfy send reports success", r["sent"] is True)
check("ntfy gets a plain-text body", sent["content"]==b"Body")
check("ntfy gets the title as a header", sent["headers"]["Title"]=="Title")

sent.clear()
notifier.send("Title","Body",{"notify_webhook":"https://discord.com/api/webhooks/x"},"test")
body=json.loads(sent["content"].decode())
check("discord/slack get JSON with content and text", "content" in body and "text" in body)

# ---- a broken webhook must not break trading -------------------------------
class ExplodingClient(FakeClient):
    def post(self,*a,**k): raise RuntimeError("connection refused")
notifier.httpx.Client=ExplodingClient
check("a dead webhook returns not-sent instead of raising",
      notifier.send("t","m",{"notify_webhook":"https://dead.test/x"},"test")["sent"] is False)

def trending(pair):
    b={"GBP/USD":1.30,"EUR/USD":1.08,"USD/JPY":156.0,"EUR/GBP":0.855,"GBP/JPY":198.0,"XAU/USD":4500.0}[pair]
    s=b*0.0006
    return [{"time":f"t{i}","open":b+i*s,"high":b+i*s*1.001,"low":b+i*s*0.999,"close":b+i*s,"volume":100} for i in range(120)]
base.MIN_CONF=0; base.get_candles=trending; base.london_window=lambda: True
ts=datetime.now(timezone.utc).isoformat()
base.snapshot=lambda: {"provider":"oanda","quotes":[{"pair":p,"price":trending(p)[-1]["close"],
    "bid":trending(p)[-1]["close"],"ask":trending(p)[-1]["close"],"timestamp":ts,"source":"oanda-practice"} for p in base.WATCHLIST]}
base.TRADES.clear(); agent._MEM_CONFIG.clear(); agent._MEM_RUNS.clear()
agent.save_agent_config(USER,{"enabled":True,"respect_window":False,"min_confidence":0,
                              "notify_webhook":"https://dead.test/x"})
run=agent.run_agent_once(USER,"test")
check("the agent still opened trades despite the dead webhook", len(run["opened"])>0)
check("and recorded that the alert failed", run.get("notified",{}).get("sent") is False)

# ---- the watchdog ----------------------------------------------------------
cfg=agent.get_agent_config(USER)
health=agent.run_health(USER,cfg)
check("a fresh run is not flagged stale", health["stale"] is False)
old=(datetime.now(timezone.utc)-timedelta(hours=48)).isoformat()
agent._MEM_RUNS.clear(); agent._MEM_RUNS.append({"user_name":USER,"created_at":old,"opened":[]})
stale_health=agent.run_health(USER,cfg)
check(f"a 48h-old run IS flagged stale ({stale_health['hours_since_last_run']}h)", stale_health["stale"] is True)
check("and explains what to check", "scheduler" in (stale_health["message"] or ""))
agent.save_agent_config(USER,{"enabled":False})
check("a switched-off agent is never flagged stale",
      agent.run_health(USER,agent.get_agent_config(USER))["stale"] is False)

# ---- HTTP surface ----------------------------------------------------------
check("test-alert needs auth", client.post("/api/agent/agent-test-alert").status_code==401)
cfgr=client.get("/api/agent/agent-config",headers=H).json()
check("config exposes health", "health" in cfgr and "stale" in cfgr["health"])
check("config says whether alerts are on", "alerts_configured" in cfgr)
saved=client.post("/api/agent/agent-config",json={"notify_webhook":"http://insecure.test/x"},headers=H).json()
check("an http webhook is rejected on save", saved["config"]["notify_webhook"]=="")
saved=client.post("/api/agent/agent-config",json={"notify_webhook":"https://ntfy.sh/ok"},headers=H).json()
check("an https webhook is kept", saved["config"]["notify_webhook"]=="https://ntfy.sh/ok")
saved=client.post("/api/agent/agent-config",json={"notify_webhook":""},headers=H).json()
check("clearing the webhook turns alerts off", saved["config"]["notify_webhook"]=="")

print(); print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
