# Stage Five: Production Engineering

Stage five adds a production control plane without removing the stage two-to-four SQLite workflow.

## Architecture

- FastAPI validates RBAC and creates an asynchronous run.
- PostgreSQL or SQLite stores run state, immutable case snapshots, results, and audit logs.
- Redis carries Celery tasks.
- A Celery worker performs model calls, detection, and defense evaluation.
- A unique `(run_id, case_id)` constraint makes retries idempotent.

Run states are `PENDING`, `RUNNING`, `PARTIAL_FAILED`, `FAILED`, `COMPLETED`, and `CANCELLED`.

## Local Development

Set `LLM_SECURITY_DATABASE_URL` to a SQLite URL and run Celery in eager mode when no Redis service is needed:

```powershell
$env:LLM_SECURITY_CELERY_EAGER="true"
python -m uvicorn llm_security_platform.app.api:app --port 8020
```

## Docker Deployment

```powershell
docker compose -f llm_security_platform/docker-compose.yml up --build
```

The stack starts PostgreSQL, Redis, an Alembic migration job, FastAPI, and a Celery worker.

Run the automated Docker end-to-end verification before stage six:

```powershell
python llm_security_platform/scripts/stage_five_e2e_smoke.py
```

See `docs/stage_five_e2e_smoke.md` for its infrastructure, RBAC, complete-run, failure-diagnostic, and audit assertions.

## API Flow

1. `POST /async-runs` returns a `run_id` with HTTP 202.
2. `GET /async-runs/{run_id}` returns status, progress, failures, and case results.
3. `POST /async-runs/{run_id}/cancel` requests cancellation at the next case boundary.
4. `POST /async-runs/{run_id}/retry` retries only failed or unfinished cases.
5. `GET /audit-logs?run_id=...` returns operation audit records.

Default development keys are `viewer-key`, `analyst-key`, `reviewer-key`, and the configured admin key. Production deployments should replace all defaults through environment configuration.
