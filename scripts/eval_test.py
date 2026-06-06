"""Workflow evaluation test script."""
import json, time, urllib.request, urllib.error, ssl, subprocess

BASE = "http://82.156.132.43"
TOKEN = None
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def api_get(path):
    headers = {"Authorization": f"Bearer {TOKEN}"}
    req = urllib.request.Request(f"{BASE}{path}", headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
        return json.loads(resp.read())

def api_post(path, data=None):
    headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(f"{BASE}{path}", data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
        return json.loads(resp.read())

# === Login ===
resp = api_post("/api/v1/auth/login", {"account":"1121799294@qq.com","password":"123456"})
TOKEN = resp.get("access_token", "")
print(f"LOGIN: {'OK' if TOKEN else 'FAILED'}")
if not TOKEN: exit(1)

test_file = "C:/Users/ASUS/Desktop/01_智能设备采购合同_基准版.docx"
rev_file = "C:/Users/ASUS/Desktop/01_智能设备采购合同_修订版.docx"

# === Test 1: Contract Review ===
print("\n=== TEST 1: Contract Review ===")
cmd = ["curl","-s","-m","15","-X","POST",f"{BASE}/api/v1/reviews?contract_type=采购合同","-H",f"Authorization: Bearer {TOKEN}","-F",f"file=@{test_file}"]
r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
review = json.loads(r.stdout)
RID = review.get("task_id","")
print(f"Create review task: {RID}")

if RID:
    for i in range(15):
        time.sleep(15)
        resp = api_get(f"/api/v1/reviews/{RID}")
        s = resp.get("status","?")
        print(f"  [{i+1}] status={s}")
        if s == "completed":
            resp2 = api_get(f"/api/v1/reviews/{RID}/risks")
            print(f"  DONE: {resp2.get('total','?')} risks found")
            break
        elif s == "failed":
            print(f"  FAILED: {resp.get('error_message','')[:80]}")
            break

# === Test 2: Reverse Rule ===
print("\n=== TEST 2: Reverse Rule Extraction ===")
cmd = ["curl","-s","-m","15","-X","POST",f"{BASE}/api/v1/reverse-rule-tasks",
       "-H",f"Authorization: Bearer {TOKEN}",
       "-F","task_name=测评用","-F","contract_type=采购合同","-F","review_role=乙方",
       "-F","pairs[0][pair_name]=测试合同组",
       "-F",f"pairs[0][before_file]=@{test_file}",
       "-F",f"pairs[0][after_file]=@{rev_file}"]
r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
rev = json.loads(r.stdout)
RVID = rev.get("id","")
print(f"Create reverse task: {RVID} status={rev.get('status','?')}")

if RVID:
    for i in range(20):
        time.sleep(20)
        resp = api_get(f"/api/v1/reverse-rule-tasks/{RVID}")
        s = resp.get("status","?")
        p = resp.get("progress",0)
        print(f"  [{i+1}] status={s} progress={p}")
        if s == "pending_confirm":
            cands = api_get(f"/api/v1/reverse-rule-tasks/{RVID}/candidates")
            cc = len(cands.get("candidates",[]))
            print(f"  DONE: {cc} candidates")
            break
        elif s == "failed":
            print(f"  FAILED: {resp.get('error_message','')[:80]}")
            break

# === Results ===
print("\n" + "="*60)
print("ALL TESTS COMPLETE")
print("="*60)
