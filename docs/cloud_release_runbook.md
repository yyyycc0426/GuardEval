# Cloud Release Runbook

This guide covers the deployment, traffic control, rollback, and decommissioning operations for the **LLM Security Evaluation Platform** (`proj4`) on Google Cloud Platform (GCP).

---

## 1. Staging Release & Verification
Our CI/CD pipeline deploys each code check-in to Cloud Run staging:
1. Every commit to `main` builds a new Docker image and pushes it to Artifact Registry.
2. The staging service `llm-security-api-staging` is updated.
3. The E2E smoke test (`scripts/cloud_e2e_smoke_test.py`) is run automatically by GitHub Actions.
4. Review the staging logs in Cloud Logging if any stage fails.

---

## 2. Canary Traffic Split (Blue/Green Deploy)
Once Staging verification passes, we roll out the revision to the production service `llm-security-api` and split traffic.

### A. Deploy New Production Revision (No Traffic)
Deploy the container to production with `0%` traffic:
```bash
gcloud run deploy llm-security-api \
  --image=us-central1-docker.pkg.dev/YOUR_PROJECT_ID/llm-security-platform/llm-security-api:latest \
  --region=us-central1 \
  --no-traffic
```

### B. Route 10% Traffic to New Revision (Canary Stage)
1. Find the name of the new revision:
   ```bash
   gcloud run revisions list --service=llm-security-api --region=us-central1 --limit=5
   ```
2. Route 10% traffic to the canary revision (e.g. `llm-security-api-00002-xyz`):
   ```bash
   gcloud run services update-traffic llm-security-api \
     --region=us-central1 \
     --to-revisions=llm-security-api-00002-xyz=10
   ```

### C. Route 100% Traffic (Full Promotion)
If error rates remain at zero and performance latencies look normal, promote the revision to 100%:
```bash
gcloud run services update-traffic llm-security-api \
  --region=us-central1 \
  --to-latest
```

---

## 3. Rollback Operations
In case of critical failures (5xx rate spikes, memory leaks, security breaches):

1. List active revisions:
   ```bash
   gcloud run revisions list --service=llm-security-api --region=us-central1
   ```
2. Instantly route 100% traffic back to the last known-good revision (e.g. `llm-security-api-00001-abc`):
   ```bash
   gcloud run services update-traffic llm-security-api \
     --region=us-central1 \
     --to-revisions=llm-security-api-00001-abc=100
   ```
3. Pin the revision. Cloud Run will direct all incoming requests to the stable revision, letting you debug the broken revision offline.

---

## 4. Monitoring Checklist
Before confirming a successful release, check the following dashboards in Cloud Monitoring:

- [ ] **HTTP 5xx Rate**: Ensure there are no spikes on `run.googleapis.com/request_count` filtered by `response_code_class = 5xx`.
- [ ] **Vertex AI API Latency**: Ensure the latency on `aiplatform.googleapis.com/prediction/request_latencies` is under 4000ms.
- [ ] **Cloud Tasks Dispatch Failure**: Check `cloudtasks.googleapis.com/queue/error_count` to verify webhook push dispatches are not failing with 4xx or 5xx codes.
- [ ] **GCS Bucket Error Codes**: Verify that storage requests do not return 403 (Permission Denied).

---

## 5. Decommissioning & Cleanup (`terraform destroy`)
To decommission the environment and avoid recurring charges when the workspace or demo is no longer needed:

1. Log in to your GCP CLI context.
2. Initialize and destroy resources via Terraform:
   ```bash
   cd llm_security_platform/terraform
   terraform init
   terraform destroy -var-file="production.tfvars"
   ```
3. **Important Check**: Verify that the Cloud SQL instance is deleted. PostgreSQL databases on GCP incur constant hourly charges regardless of activity.
4. Empty and delete GCS buckets if Terraform fails to delete them because of existing objects:
   ```bash
   gsutil rm -r gs://your-gcs-bucket-name
   ```
