# Stage 4.5 Real-Model Defense Ablation Plan

## Purpose

Stage four uses a deterministic vulnerable Mock model for complete nine-strategy causal ablation. Stage 4.5 does not replace that experiment. It validates whether the key defense trends also appear on real local models under a cost-controlled design.

## Models and Dataset

- `qwen3:8b`
- `qwen3.6:latest`
- Frozen `attack_cases_v2.json`: 48 attacks and 16 benign requests

## Strategies

- `none`
- `baseline`
- `input_defense`
- `rag_defense`
- `output_defense`
- `input_defense+rag_defense+output_defense`

Both models must complete none, baseline, and full defense. At least one model must complete all three single-defense runs. Mock remains responsible for the full nine-strategy causal matrix.

## Metrics

ASR, RAG leakage ASR, Prompt Injection ASR, Jailbreak ASR, false-positive rate, normal-task success, blocked ratio, review rate, P50/P95 latency, tokens, estimated cost, and failed cases.

Every valid run preserves model configuration, policy and dataset versions, code commit, run configuration hash, raw responses, DefenseDecision records, and detector results.

## Repetition

The default is one run per group. The runner supports repeated core groups and reports mean, minimum, and maximum. Invalid runs with failed cases are retained for diagnosis but excluded from metric aggregation.

## Commands

```powershell
python -m llm_security_platform.scripts.run_real_model_defense_ablation
python -m llm_security_platform.stage_4_5_gate
```
