# GuardEval — LLM Security Evaluation & Defense Platform

An internal LLM/RAG security evaluation and defense platform for AI platform, security, or R&D teams. It provides a reproducible, auditable, and measurable evaluation pipeline for prompt injection, jailbreak, and RAG leakage risks, with defense strategy comparison and human review — plus a **content-safety track** that calibrates classifiers against public, human-labeled benchmarks.

> Built end-to-end as a single-author project. Highlights: a two-metric security model (raw vs delivered ASR), pluggable input/RAG/output defenses with ablation, async evaluation with RBAC/multi-tenancy/audit, and external calibration on public safety data.

> 📚 Lost in the docs? Start at **[docs/INDEX.md](docs/INDEX.md)** — a one-page "which file should I read" map.

### Operations console & evidence chain

| Console overview | Case-level evidence chain |
|---|---|
| ![Console overview](llm_security_platform/reports/stage_6_overview.png) | ![Evidence chain](llm_security_platform/reports/stage_6_evidence_chain.png) |

_The console (runs, metrics, comparisons) and the per-case evidence chain — original prompt → defenses → raw response → detectors/judge → final outcome → audit records._

## ⚡ Quickstart (no services, ~30s)

The content-safety benchmark runs fully offline (no Docker/Redis/API):

```powershell
python -m llm_security_platform.run_content_safety_benchmark   # TF-IDF baseline vs HateXplain
python -m llm_security_platform.run_rationale_benchmark        # explainability: cited vs human rationale tokens
python -m llm_security_platform.content_safety_gate            # quality gate
```

## 🏗️ Architecture

```text
+-----------------------+      +---------------------------+
|   Attack Case Store   | ---> |  Defense Policy Engine    |
| (Prompt & RAG Leak)   |      | (Unicode, LlamaGuard, etc)|
+-----------------------+      +---------------------------+
                                             |
                                             v
+-----------------------+      +---------------------------+
|  LLM Response Evaluator| <--- |   Target Model Adaptors   |
| (Ollama, OpenAI, Mock) |      | (Ollama, OpenAI, Mock)    |
+-----------------------+      +---------------------------+
           |
           v
+-----------------------+      +---------------------------+
|   Control Plane DB    | ---> |     Operations Console    |
| (PostgreSQL / SQLite) |      |   (Runs, Audits, Review)  |
+-----------------------+      +---------------------------+
```

## 🚀 Three-Step Start

### 1. Launch Services
Ensure Docker and Compose are installed, then spin up the local database, redis queue, celery workers, and API service:
```powershell
docker compose -f llm_security_platform/docker-compose.yml up --build
```

### 2. Run Automated Verification Suite
Run unit and integration tests to verify the multi-tenancy, rate limiting, and core evaluation pipeline logic:
```powershell
.\.venv\Scripts\python.exe -m pytest llm_security_platform/tests -q
```

### 3. Load Testing Execution
Install development dependencies and run Locust headless load testing:
```powershell
pip install -r requirements-dev.txt
locust -f locustfile.py --headless -u 2 -r 1 -t 5s --only-summary --host http://localhost:8020
```

## 🔬 Real-Model Ablation Experiments
The platform evaluates security metrics across two distinct dimensions:
* **Raw Model Compromise Rate (ASR)**: Whether the upstream model was successfully subverted.
* **Delivered Attack Success Rate (ASR)**: Whether unsafe responses slipped past the defense layers and reached the end-user.

In repeated ablation experiments on `qwen3:8b` and `qwen3.6:latest` (under 128-case holdout datasets), the full defense configuration reduced the **Delivered ASR** to **0%**, demonstrating effective egress inspection and input redacting, even while raw compromise rates remained at 31.25% and 12.50% respectively.

## 🧪 Public-Benchmark Calibration (Content-Safety Track)

Beyond hand-authored attack cases, the platform calibrates classifiers/judges against the public, human-labeled **HateXplain** dataset (20,148 posts; normal / offensive / hatespeech). This is a separate *classification* track (accuracy / macro-F1 / confusion matrix), not the attack/defense ASR pipeline — it gives the platform's judgments external validity. See [`docs/content_safety_track.md`](llm_security_platform/docs/content_safety_track.md).

Balanced sample, fixed seed; failed model calls are excluded from metrics (never counted as a label):

| Classifier | 3-class macro-F1 | toxic recall | non-toxic recall |
|---|---|---|---|
| TF-IDF baseline (offline) | 0.609 | — | — |
| qwen3:8b (local, via Ollama) | 0.495 | 0.99 | 0.30 |
| gemini-2.5-flash (Vertex AI + ADC) | 0.554 | 0.98 | 0.47 |

**Finding:** both LLM judges — local *and* cloud — show a consistent **over-moderation bias** (catch ~98–99% of toxic content but over-flag 53–70% of benign posts as toxic). A classic safety/usability trade-off, measured on real data — exactly what this platform exists to quantify.

**Explainability:** the track also scores *rationale alignment* — when the model flags a post toxic, do its important tokens match the human-highlighted rationale? (TF-IDF baseline: token recall 0.71 / IoU 0.32 over 911 posts.)

## 🚧 Known Boundaries & Limitations
1. **Not a Real-time Firewall**: This is a reproducible security evaluation platform designed to run async evaluation datasets. It should not be used as an inline production firewall or reverse proxy gateway.
2. **Fail-Closed on Outages**: Write endpoints (`POST`, `PUT`, `PATCH`, `DELETE`) are designed to fail-closed with `503 Service Unavailable` during Redis rate-limiter outages to prevent cost runaways and backend resource abuse. Read endpoints degrade gracefully to local process limits.
3. **Internal Deployment Profile**: Direct Cloud Run URLs are private. Network ports for local Compose services bind to `127.0.0.1` by default to prevent unauthorized external network exposure. Anonymous access to Prometheus metrics and Grafana is disabled.
