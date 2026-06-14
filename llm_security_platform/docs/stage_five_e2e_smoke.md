# Stage 5.5: Docker E2E Smoke Test

This validation proves that the production topology works as a system, rather than only parsing as Docker Compose configuration.

## Run

```powershell
python llm_security_platform/scripts/stage_five_e2e_smoke.py
```

Use `--skip-build` to reuse existing images or `--keep` to leave the stack running for manual inspection.

## Assertions

The script verifies:

1. Docker Compose starts PostgreSQL, Redis, API, migration, and Worker services.
2. The API health endpoint responds successfully.
3. PostgreSQL accepts connections and Redis responds with `PONG`.
4. The Celery Worker responds to an inspect ping.
5. `alembic upgrade head` succeeds against PostgreSQL.
6. A three-case asynchronous Mock run reaches `COMPLETED` with zero execution failures.
7. The creation audit record is queryable by `run_id`.
8. A deliberately misconfigured remote-model run reaches `FAILED` with an actionable `error_summary`.
9. Viewer, Analyst, and Reviewer privilege-escalation attempts return HTTP 403.

After this smoke test, stage two, three, and four quality gates should be run again to prove that production engineering did not change benchmark behavior.
