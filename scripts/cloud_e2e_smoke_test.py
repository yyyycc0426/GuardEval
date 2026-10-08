import os
import sys
import time
import json
import urllib.request
import urllib.error

API_URL = os.environ.get("LLM_SECURITY_API_URL", "http://127.0.0.1:8020").rstrip("/")
API_KEY = os.environ.get("LLM_SECURITY_API_KEY", "dev-security-key")

def make_request(path, method="GET", payload=None):
    url = f"{API_URL}{path}"
    headers = {
        "X-API-Key": API_KEY,
        "Content-Type": "application/json"
    }
    google_id_token = os.environ.get("GOOGLE_ID_TOKEN")
    if google_id_token:
        headers["Authorization"] = f"Bearer {google_id_token}"
    req_data = json.dumps(payload).encode("utf-8") if payload else None
    req = urllib.request.Request(url, data=req_data, headers=headers, method=method)
    
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            body = res.read().decode("utf-8")
            return res.status, json.loads(body)
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(err_body)
        except Exception:
            return exc.code, {"error": err_body}
    except Exception as exc:
        return 0, {"error": str(exc)}

def main():
    print(f"=== LLM Security Platform E2E Smoke Test ===")
    print(f"Target API Endpoint: {API_URL}")

    # 1. Verify Health Check
    print("\n[Step 1/6] Running API Health Check...")
    status, res = make_request("/health")
    if status != 200 or not res.get("success"):
        print(f"❌ API Health Check failed (Status: {status}, Response: {res})")
        sys.exit(1)
    print(f"✅ Health Check Passed! Status: {res.get('data')}")

    # 2. Seed Attack Cases
    print("\n[Step 2/6] Seeding default attack cases...")
    status, res = make_request("/cases/seed", method="POST")
    if status not in (200, 201):
        print(f"❌ Failed to seed attack cases (Status: {status}, Response: {res})")
        sys.exit(1)
    print(f"✅ Seeded successfully: {res.get('message')}")

    # 3. Retrieve Attack Cases
    print("\n[Step 3/6] Fetching seeded attack cases...")
    status, res = make_request("/cases")
    if status != 200 or not res.get("success") or not res.get("data"):
        print(f"❌ Failed to retrieve attack cases (Status: {status})")
        sys.exit(1)
    
    cases = res["data"]
    print(f"✅ Retrieved {len(cases)} attack cases.")
    selected_case = cases[0]
    case_id = selected_case["case_id"]
    print(f"Selected case for evaluation: {case_id} ({selected_case['risk_type']})")

    # 4. Submit Evaluation Run
    print("\n[Step 4/6] Submitting Evaluation Run...")
    run_payload = {
        "name": "Cloud E2E Smoke Run",
        "provider": "mock",
        "model": "mock-vulnerable-model",
        "defense_policy": "none",
        "judge_provider": "mock",
        "concurrency": 1,
        "case_ids": [case_id]
    }
    
    status, res = make_request("/async-runs", method="POST", payload=run_payload)
    if status != 202 or not res.get("success"):
        print(f"❌ Failed to submit evaluation run (Status: {status}, Response: {res})")
        sys.exit(1)
        
    run_id = res["data"]["run_id"]
    print(f"✅ Run submitted successfully! Run ID: {run_id}")

    # 5. Poll Run Execution Status
    print("\n[Step 5/6] Polling execution status...")
    max_retries = 30
    retry_interval = 2.0
    completed = False
    
    for attempt in range(max_retries):
        status, res = make_request(f"/async-runs/{run_id}")
        if status != 200:
            print(f"❌ Failed to fetch run detail (Status: {status})")
            sys.exit(1)
            
        run_data = res["data"]["run"]
        run_status = run_data["status"]
        progress = run_data["progress"]
        print(f"Attempt {attempt+1}/{max_retries} | Status: {run_status} | Progress: {progress*100:.1f}%")
        
        if run_status in ("COMPLETED", "FAILED", "PARTIAL_FAILED", "CANCELLED"):
            completed = True
            break
        time.sleep(retry_interval)

    if not completed:
        print("❌ Timeout reached waiting for evaluation run to complete.")
        sys.exit(1)
        
    print(f"✅ Run finished executing with final status: {run_status}")

    # 6. Verify GCS / Fallback report archiving
    print("\n[Step 6/6] Verifying report archiving...")
    gcs_bucket = os.environ.get("LLM_SECURITY_GCS_BUCKET")
    if gcs_bucket:
        try:
            from google.cloud import storage
            storage_client = storage.Client()
            bucket = storage_client.bucket(gcs_bucket)
            blob = bucket.blob(f"reports/default/{run_id}_report.json")
            if blob.exists():
                print(f"✅ Report successfully archived in GCS: gs://{gcs_bucket}/reports/default/{run_id}_report.json")
            else:
                print("❌ GCS report blob not found in bucket.")
                sys.exit(1)
        except Exception as exc:
            print(f"⚠️ Failed to verify storage via GCS SDK ({exc}). Falling back to local storage check...")
            # fallback check
            fallback_check(run_id)
    else:
        fallback_check(run_id)

    print("\n🎉 ALL SMOKE TESTS COMPLETED SUCCESSFULLY!")

def fallback_check(run_id):
    local_path = os.path.join("reports/gcs_fallback/reports/default", f"{run_id}_report.json")
    if os.path.exists(local_path):
        print(f"✅ Report successfully archived in local fallback storage: {local_path}")
    else:
        print(f"❌ Report not found in GCS or local fallback path: {local_path}")
        sys.exit(1)

if __name__ == "__main__":
    main()
