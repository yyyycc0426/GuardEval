# Three-Minute Demo Script

## 0:00-0:30 Dataset Management

Open `/console/`. Show the dataset version, attack/benign counts, and filters. Filter by `rag_data_leakage` and `critical`. Explain that imported JSON is validated by the backend and versioned before persistence.

## 0:30-1:10 Async Run

Open Create Run. Select the frozen 64-case dataset, Mock baseline model, full defense, Rule-backed Judge, concurrency, and timeout. Submit the run and point out the returned `run_id`, progress, success count, and failure count.

## 1:10-1:50 Results

Open Results Overview. Explain ASR, false-positive rate, normal-task success, P50/P95, tokens, cost, risk distribution, configuration versions, and model/defense comparison.

## 1:50-2:50 Evidence Chain

Open `atk-013`. Walk through the original prompt, input risk evidence, sanitization decision, hardened effective prompt, safe model response, rule detector, Judge result, final refusal outcome, and audit record.

## 2:50-3:00 Engineering Close

State that FastAPI and Worker are separated, PostgreSQL and Redis were Docker E2E tested, retries are idempotent, permissions are enforced by the backend, and stage two-to-four gates still pass.
