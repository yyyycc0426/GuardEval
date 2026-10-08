# Security Red-Team Audit Report

This report presents a local security audit of the LLM Security Evaluation Platform. It identifies key vulnerabilities, demonstrates execution evidence using automated tests, lists applied patches, and outlines remaining risks.

---

## 1. Threat Model Table

| Attack Surface | Risk Level | Possible Impact | Files Involved | Suggested Test |
| :--- | :--- | :--- | :--- | :--- |
| **Multi-Tenant Schema Isolation** | **Critical** | SQL Injection via malicious `tenant_id` and database credentials leakage. | [production_store.py](file:///d:/AI_Projects/proj4/llm_security_platform/app/production_store.py) | `test_sql_injection_tenant_id` |
| **Tenant Connection Leakage** | **Critical** | Tenant crosstalk. A tenant inherits another tenant's schema path. | [production_store.py](file:///d:/AI_Projects/proj4/llm_security_platform/app/production_store.py) | `test_tenant_crosstalk_prevention` |
| **API Authentication & RBAC** | **High** | Unauthenticated leakage of operational/token metrics via public endpoints. | [api.py](file:///d:/AI_Projects/proj4/llm_security_platform/app/api.py) | `test_metrics_endpoint_authorization` |
| **Semantic Cache Isolation** | **High** | Cache poisoning and defense bypass across models/policies. | [semantic_cache.py](file:///d:/AI_Projects/proj4/llm_security_platform/app/semantic_cache.py), [case_execution.py](file:///d:/AI_Projects/proj4/llm_security_platform/app/case_execution.py) | `test_semantic_cache_isolation` |
| **Celery Retry Abuse** | **Medium** | Denos of Service (DoS) through infinite worker task retries. | [api.py](file:///d:/AI_Projects/proj4/llm_security_platform/app/api.py) | `test_unbounded_retries_prevention` |
| **Idempotency Lock Leak** | **Medium** | Indefinite lockout (5 min) of a tenant's parameters if dispatch fails. | [api.py](file:///d:/AI_Projects/proj4/llm_security_platform/app/api.py) | `test_redis_lock_release_on_dispatch_failure` |
| **Unbounded Evaluation Size** | **Medium** | Memory/thread exhaustion through submission of thousands of case IDs. | [api.py](file:///d:/AI_Projects/proj4/llm_security_platform/app/api.py) | `test_unbounded_cases_prevention` |
| **RAG Indirect Injection** | **Medium** | Bypass of injection scanning using base64 obfuscation or character spacing. | [rag_defense.py](file:///d:/AI_Projects/proj4/llm_security_platform/policies/rag_defense.py) | `test_rag_base64_injection_detection` |
| **Multimodal Scanning DoS** | **Low** | Out-of-memory crashes on decompression bombs or massive image uploads. | [multimodal.py](file:///d:/AI_Projects/proj4/llm_security_platform/app/multimodal.py) | `test_multimodal_image_limits_and_watermark_threshold` |
| **Hardcoded Security Secrets** | **Low** | Vulnerable fallback secrets permitting token forging and DB key exposure. | [security.py](file:///d:/AI_Projects/proj4/llm_security_platform/app/security.py) | Warnings triggered during initialization. |

---

## 2. Top 10 Prioritized Risks & Pytest Mapping

For each identified risk, a test case has been created in [test_security_audit.py](file:///d:/AI_Projects/proj4/llm_security_platform/tests/test_security_audit.py):

### 1. PostgreSQL Schema SQL Injection (Critical)
- **Vulnerability**: F-string SQL query formatting inside `session_scope` routing allowed schema names containing spaces, semicolons, and SQL commands (e.g. `tenant_a; DROP TABLE...`) to execute raw SQL.
- **Test Case**: `SecurityAuditTests.test_sql_injection_tenant_id`
- **Fix**: Replaced the weak `isalnum()` check with a strict regular expression verification: `re.match(r"^[a-zA-Z0-9_]+$", tenant_id)`.

### 2. Connection Pool search_path Crosstalk (Critical)
- **Vulnerability**: Modifying `search_path` on pooled PostgreSQL connections meant subsequent tenants reusing the connection executed queries inside the previous tenant's schema.
- **Test Case**: `SecurityAuditTests.test_tenant_crosstalk_prevention`
- **Fix**: Wrapped database context in a `try...finally` block, explicitly reverting the `search_path` back to `public` before returning the connection to the pool.

### 3. Public Metrics Endpoint Information Disclosure (High)
- **Vulnerability**: The `/metrics` endpoint exposed global operational and token stats to unauthenticated visitors.
- **Test Case**: `SecurityAuditTests.test_metrics_endpoint_authorization`
- **Fix**: Protected `/metrics` behind the standard `require_permission("audit:read")` decorator.

### 4. Cache Pollution across Models & Defense Policies (High)
- **Vulnerability**: The `SemanticCache` keys only incorporated `tenant_id` and the prompt hash, leading to mock model responses bleeding into custom models, and cache hits bypassing defense policies.
- **Test Case**: `SecurityAuditTests.test_semantic_cache_isolation`
- **Fix**: Integrated `provider`, `model`, and active `defense_policy` configurations directly into the Redis caching keys.

### 5. Infinite Retries Task Abuse (Medium)
- **Vulnerability**: Tenants could trigger unlimited retries of failed runs via `/async-runs/{run_id}/retry`, flooding Celery worker queues.
- **Test Case**: `SecurityAuditTests.test_unbounded_retries_prevention`
- **Fix**: Enforced a retry count guard check (`retry_count >= 3`) before starting retries.

### 6. Redis Idempotency Lock Leak on Dispatch Failure (Medium)
- **Vulnerability**: If job dispatch failed (e.g., Celery queue unavailable), the Redis lock key was held for 300 seconds, locking the tenant out from executing runs with the same parameters.
- **Test Case**: `SecurityAuditTests.test_redis_lock_release_on_dispatch_failure`
- **Fix**: Added cleanup inside the exception block of `/async-runs` to delete the lock key if queue submission fails.

### 7. Unbounded Sync/Async Runs (Medium)
- **Vulnerability**: Requests could contain thousands of `case_ids`, leading to memory exhaustion and database lock contention.
- **Test Case**: `SecurityAuditTests.test_unbounded_cases_prevention`
- **Fix**: Added validation rejecting runs containing more than 100 cases.

### 8. Obfuscated RAG Document Commands Bypass (Medium)
- **Vulnerability**: Attackers could bypass injection scanning in retrieved documents using base64 representation or character spacing (e.g. `i g n o r e`).
- **Test Case**: `SecurityAuditTests.test_rag_base64_injection_detection`
- **Fix**: Added text normalization (whitespace extraction) and base64 parsing to retrieved RAG documents before checking injection regex patterns.

### 9. Multimodal Decompression Bombs & Watermark False Positives (Low)
- **Vulnerability**: Large image uploads caused high resource usage or OOM crashes, and small red shapes triggered visual watermark blocks (false positives).
- **Test Case**: `SecurityAuditTests.test_multimodal_image_limits_and_watermark_threshold`
- **Fix**: Added validation for image size (10MB) and dimensions (4096px), and raised the watermark red pixel ratio threshold to `0.05` (5%).

### 10. Default Hardcoded Credentials & Secrets (Low)
- **Vulnerability**: Fallback secrets (e.g., `security-jwt-secret-key-9417` and `LLM_SECURITY_ENCRYPTION_KEY`) allowed local attackers to forge tokens or decrypt tenant configuration parameters.
- **Fix**: Implemented validation to check for defaults and print warnings to standard loggers during initialization.

---

## 3. Verification & Test Suite Summary

All 9 validation test cases completed successfully:

```
llm_security_platform\tests\test_security_audit.py .........             [100%]
======================== 9 passed, 2 warnings in 6.01s ========================
```

---

## 4. Remaining Risks

1. **Local Encryption Key Security**: The system relies on the `LLM_SECURITY_ENCRYPTION_KEY` environment variable. If the host machine is compromised, this key can be extracted from process memory, exposing dynamic API keys stored in SQLite/PostgreSQL. Operators must ensure environment variable permissions are locked down.
2. **Third-Party Model Provider Failures**: Since third-party model providers are external, sudden API definition changes or connection failures can degrade the accuracy of LLM Judges. Wrapper circuit breakers help maintain availability but do not evaluate semantic validity.
