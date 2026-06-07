"""Workflow evaluation test script."""
import json, time, urllib.parse, sys
from pathlib import Path
import httpx

BASE = "http://82.156.132.43:8080"
TOKEN = None
TIMEOUT = httpx.Timeout(30.0)

# 本地合同文件
BENCHMARK_FILE = Path(r"C:\Users\ASUS\Desktop\01_智能设备采购合同_基准版.docx")
REVISED_FILE   = Path(r"C:\Users\ASUS\Desktop\01_智能设备采购合同_修订版.docx")
PROBLEM_FILE   = Path(r"C:\Users\ASUS\Desktop\02_采购合同_智能仓储设备采购合同_偏问题.docx")

client = httpx.Client(timeout=TIMEOUT)


def api_get(path):
    resp = client.get(f"{BASE}{path}", headers={"Authorization": f"Bearer {TOKEN}"})
    return resp.json()


def api_post(path, data=None):
    resp = client.post(f"{BASE}{path}", json=data, headers={"Authorization": f"Bearer {TOKEN}"})
    return resp.json()


# === Health Check ===
print("=== HEALTH CHECK ===")
try:
    resp = client.get(f"{BASE}/health")
    print(f"  OK: {resp.json()}")
except Exception as e:
    print(f"  FAILED: {e}")
    sys.exit(1)

# === Login ===
print("\n=== LOGIN ===")
try:
    resp = api_post("/api/v1/auth/login", {"account": "1121799294@qq.com", "password": "123456"})
    TOKEN = resp.get("access_token", "")
    print(f"  {'OK' if TOKEN else 'FAILED'}")
    if not TOKEN:
        sys.exit(1)
except Exception as e:
    print(f"  FAILED: {e}")
    sys.exit(1)


def upload_and_wait(endpoint, file_map: dict, extra_fields: dict = None, label: str = "task"):
    """Upload files and poll until task completes."""
    opened = {}
    try:
        for key, filepath in file_map.items():
            opened[key] = open(filepath, "rb")

        resp = client.post(
            f"{BASE}{endpoint}",
            data=extra_fields or {},
            files=opened,
            headers={"Authorization": f"Bearer {TOKEN}"},
            timeout=60.0,
        )
        result = resp.json()
    except Exception as e:
        print(f"  FAILED to create: {e}")
        return
    finally:
        for f in opened.values():
            f.close()

    tid = result.get("task_id") or result.get("id", "")
    status = result.get("status", "?")
    print(f"  Created: {tid} status={status}")

    if not tid:
        return

    for i in range(20):
        time.sleep(15)
        try:
            resp = client.get(f"{BASE}{endpoint}/{tid}", headers={"Authorization": f"Bearer {TOKEN}"})
            raw = resp.json()
        except Exception:
            continue
        # review/comparison endpoints nest data under "task", reverse-rule is flat
        info = raw.get("task", raw)
        s = info.get("status", "?")
        p = info.get("progress", 0)
        print(f"  [{i+1}] status={s}" + (f" progress={p}" if p else ""))

        if s in ("completed", "pending_confirm"):
            if label == "review":
                try:
                    r2 = client.get(f"{BASE}{endpoint}/{tid}/risks", headers={"Authorization": f"Bearer {TOKEN}"})
                    print(f"  DONE: {r2.json().get('total', '?')} risks found")
                except Exception:
                    print(f"  DONE")
            elif label == "reverse-rule":
                try:
                    r2 = client.get(f"{BASE}{endpoint}/{tid}/candidates", headers={"Authorization": f"Bearer {TOKEN}"})
                    cc = len(r2.json().get("candidates", []))
                    print(f"  DONE: {cc} candidates extracted")
                except Exception:
                    print(f"  DONE")
            else:
                print(f"  DONE")
            break
        elif s == "failed":
            print(f"  FAILED: {info.get('error_message', '')[:120]}")
            break


# === Test 1: Contract Review ===
print("\n=== TEST 1: Contract Review ===")
upload_and_wait(
    endpoint=f"/api/v1/reviews?contract_type={urllib.parse.quote('采购合同')}",
    file_map={"file": BENCHMARK_FILE},
    label="review",
)

# === Test 2: Contract Comparison ===
print("\n=== TEST 2: Contract Comparison ===")
upload_and_wait(
    endpoint=f"/api/v1/comparisons?contract_type={urllib.parse.quote('采购合同')}",
    file_map={"old_file": BENCHMARK_FILE, "new_file": REVISED_FILE},
    label="comparison",
)

# === Test 3: Reverse Rule Extraction ===
print("\n=== TEST 3: Reverse Rule Extraction ===")
try:
    f1 = open(BENCHMARK_FILE, "rb")
    f2 = open(REVISED_FILE, "rb")
    resp = client.post(
        f"{BASE}/api/v1/reverse-rule-tasks",
        data={
            "task_name": "集成测试-规则提取",
            "contract_type": "采购合同",
            "review_role": "乙方",
            "pairs[0][pair_name]": "基准vs修订",
        },
        files={
            "pairs[0][before_file]": f1,
            "pairs[0][after_file]": f2,
        },
        headers={"Authorization": f"Bearer {TOKEN}"},
        timeout=60.0,
    )
    f1.close()
    f2.close()
    result = resp.json()
    tid = result.get("id", "")
    print(f"  Created: {tid} status={result.get('status', '?')}")

    if tid:
        for i in range(20):
            time.sleep(20)
            info = client.get(f"{BASE}/api/v1/reverse-rule-tasks/{tid}", headers={"Authorization": f"Bearer {TOKEN}"}).json()
            s = info.get("status", "?")
            p = info.get("progress", 0)
            print(f"  [{i+1}] status={s} progress={p}")
            if s == "pending_confirm":
                cands = client.get(f"{BASE}/api/v1/reverse-rule-tasks/{tid}/candidates", headers={"Authorization": f"Bearer {TOKEN}"}).json()
                cc = len(cands.get("candidates", []))
                print(f"  DONE: {cc} candidates extracted")
                break
            elif s == "failed":
                print(f"  FAILED: {info.get('error_message', '')[:120]}")
                break
except Exception as e:
    print(f"  FAILED: {e}")

# === Summary ===
print("\n" + "=" * 60)
print("ALL TESTS COMPLETE")
print("=" * 60)
client.close()
