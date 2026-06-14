# Stage Six: Security Operations Console

The stage six MVP is served by FastAPI at `/console/` and contains four focused pages.

1. Dataset management: filtering, details, JSON import, and dataset-version visibility.
2. Run creation: model, dataset, defense, Judge, concurrency, timeout, and experiment name.
3. Results overview: ASR, false-positive rate, normal-task success, failures, latency, tokens, cost, distribution, and cross-run comparison.
4. Case evidence chain: original input, detectors, defense actions, effective prompt, raw response, Judge, human review, final outcome, and audit records.

## Local Demo

```powershell
$env:LLM_SECURITY_CELERY_EAGER="true"
python -m uvicorn llm_security_platform.app.api:app --port 8020
```

Open `http://127.0.0.1:8020/console/` and use the configured admin or analyst API key.

## Docker Demo

```powershell
docker compose -f llm_security_platform/docker-compose.yml up -d --build
```

The console uses the same API, PostgreSQL, Redis, Worker, RBAC, audit, and Alembic deployment validated in stage 5.5.

## Current Boundary

The semantic detector and human-review sections are shown explicitly when no result exists. They are not fabricated. A configured stage-three semantic artifact or completed human-review record can populate those sections in a later increment.
