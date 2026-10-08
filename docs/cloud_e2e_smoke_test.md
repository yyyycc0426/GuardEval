# Cloud End-to-End Smoke Test Guide

This document describes how to execute, interpret, and troubleshoot the **Cloud End-to-End Smoke Test** for the LLM Security Evaluation & Defense Platform (`proj4`).

---

## 1. Execution Steps

The smoke test script can be run against a local FastAPI instance or a remote staging service hosted on GCP Cloud Run.

### A. Testing Against Local Instance (Local Verification)
1. Boot the FastAPI API server:
   ```bash
   python -m uvicorn llm_security_platform.app.api:app --host 127.0.0.1 --port 8020
   ```
2. Start the Celery worker in a separate terminal:
   ```bash
   celery -A llm_security_platform.app.tasks:celery_app worker --loglevel=INFO --pool=solo
   ```
3. Execute the smoke test script:
   ```bash
   python scripts/cloud_e2e_smoke_test.py
   ```

### B. Testing Against Deployed GCP Cloud Run (Remote Verification)
1. Retrieve the deployed Cloud Run service URL (e.g. from Terraform output or GCP console).
2. Configure environment variables and run the test:
   ```bash
   # Linux/macOS
   export LLM_SECURITY_API_URL="https://llm-security-api-xxxx.a.run.app"
   export LLM_SECURITY_API_KEY="dev-security-key"
   export LLM_SECURITY_GCS_BUCKET="your-gcs-bucket-name"
   python scripts/cloud_e2e_smoke_test.py
   
   # Windows PowerShell
   $env:LLM_SECURITY_API_URL="https://llm-security-api-xxxx.a.run.app"
   $env:LLM_SECURITY_API_KEY="dev-security-key"
   $env:LLM_SECURITY_GCS_BUCKET="your-gcs-bucket-name"
   python scripts/cloud_e2e_smoke_test.py
   ```

---

## 2. Expected Outputs

A successful execution will output logs resembling the following:

```text
=== LLM Security Platform E2E Smoke Test ===
Target API Endpoint: http://127.0.0.1:8020

[Step 1/6] Running API Health Check...
✅ Health Check Passed! Status: {'status': 'healthy'}

[Step 2/6] Seeding default attack cases...
✅ Seeded successfully: Attack cases seeded successfully

[Step 3/6] Fetching seeded attack cases...
✅ Retrieved 96 attack cases.
Selected case for evaluation: case_001 (jailbreak)

[Step 4/6] Submitting Evaluation Run...
✅ Run submitted successfully! Run ID: a98165b4-cd78-4ef2-9217-becc78912345

[Step 5/6] Polling execution status...
Attempt 1/30 | Status: PENDING | Progress: 0.0%
Attempt 2/30 | Status: RUNNING | Progress: 50.0%
Attempt 3/30 | Status: COMPLETED | Progress: 100.0%
✅ Run finished executing with final status: COMPLETED

[Step 6/6] Verifying report archiving...
✅ Report successfully archived in local fallback storage: reports/gcs_fallback/reports/default/a98165b4-cd78-4ef2-9217-becc78912345_report.json

🎉 ALL SMOKE TESTS COMPLETED SUCCESSFULLY!
```

---

## 3. Failure Troubleshooting Guide

If the smoke test fails at any step, use the following guide to resolve it:

### Step 1: Health Check Fails (`X-API-Key` / Connection Refused)
- **Symptom**: `❌ API Health Check failed (Status: 401)` or `0, {"error": "Connection refused"}`
- **Reason**: The API is not running at the target URL, or the configured `LLM_SECURITY_API_KEY` does not match the server's configuration.
- **Action**: Check if the server process is alive. Verify the `.env` settings for the server and make sure the client's `LLM_SECURITY_API_KEY` matches.

### Step 2/3: Seeding or Fetching Fails
- **Symptom**: `❌ Failed to seed attack cases`
- **Reason**: Database connection failed, database was locked (SQLite write lock), or permissions are invalid.
- **Action**: Check server logs. If using Postgres, ensure Postgres is running and accessible. If using SQLite, check if the filesystem directory is writable.

### Step 4/5: Run Stalls in `PENDING`
- **Symptom**: Polling loops continuously showing `Status: PENDING` until max retries is reached.
- **Reason**: The asynchronous task worker (Celery worker or Cloud Tasks subscriber) is not running or cannot process tasks.
- **Action**:
  - **Local**: Verify that the Celery worker process is active and connected to Redis (`redis-cli ping` returns `PONG`).
  - **Cloud**: Verify Cloud Tasks configuration and check Google Cloud Logging to see if the HTTP push requests to `/tasks/execute-run` failed (e.g. returning 401/403/500).

### Step 6: Archival Report is Missing
- **Symptom**: `❌ Report not found in GCS or local fallback path`
- **Reason**: GCS bucket was not created, IAM permissions on the service account do not permit writes to the bucket, or local fallback folder has write permission blocks.
- **Action**:
  - Verify if `LLM_SECURITY_GCS_BUCKET` is set correctly.
  - Review GCS IAM bindings for the Cloud Run Service Account (`roles/storage.objectUser`).
  - If running locally, check if `reports/gcs_fallback` directory exists.
