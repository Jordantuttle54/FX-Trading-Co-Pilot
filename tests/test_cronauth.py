import os, sys, pathlib
os.environ["TEMP_PASSWORDLESS_LOGIN"]="true"; os.environ.pop("DATABASE_URL",None)
os.environ["CRON_SECRET"]="4zU7c0YiRvc3e8533kqwKRas4pyf_KtvCwK4mxJ2Zmc"
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from fastapi.testclient import TestClient
from api.index import app
ok=True
def check(n,c):
    global ok; print(("PASS  " if c else "FAIL  ")+n); ok=ok and c

c=TestClient(app)
SEC=os.environ["CRON_SECRET"]
URL="/api/agent/cron/auto-close"

r=c.get(URL)
check("no header -> 401 that says the header is missing", r.status_code==401 and "No Authorization header" in r.json()["detail"])
check("and tells you the expected length", "43 characters" in r.json()["detail"])

r=c.get(URL, headers={"Authorization": SEC})
check("missing 'Bearer ' prefix is named", r.status_code==401 and "must start with 'Bearer '" in r.json()["detail"])

r=c.get(URL, headers={"Authorization": f"Bearer {SEC[:-8]}"})
check("a truncated paste is identified as a length mismatch", r.status_code==401 and "characters but this deployment expects" in r.json()["detail"])
check("and reports both lengths", "35 characters" in r.json()["detail"] and "43" in r.json()["detail"])

wrong = "x"*len(SEC)
r=c.get(URL, headers={"Authorization": f"Bearer {wrong}"})
check("right length but wrong value is distinguished", r.status_code==401 and "does not match this deployment" in r.json()["detail"])

r=c.get(URL, headers={"Authorization": f"Bearer {SEC}"})
check("the correct secret is accepted", r.status_code==200)
check("and the run actually executes", "checked_users" in r.json())

r=c.get(URL, headers={"Authorization": f"  Bearer {SEC}  "})
check("surrounding whitespace is tolerated", r.status_code==200)

r=c.get(URL, headers={"Authorization": f"bearer {SEC}"})
check("lowercase 'bearer' is tolerated", r.status_code==200)

for d in [c.get(URL).json()["detail"], c.get(URL, headers={"Authorization":f"Bearer {wrong}"}).json()["detail"]]:
    check("no part of the real secret leaks in the message", SEC[:12] not in d)

print(); print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
