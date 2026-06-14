# Stage 4.5 Real-Model Defense Ablation Report

## Scope

Stage four uses a deterministic vulnerable Mock model to establish the full
nine-group causal ablation. Stage 4.5 is a separate trend-validation experiment:
two local Qwen models were evaluated on the frozen 64-case benchmark using a
cost-controlled subset of defense combinations.

- Dataset: `attackset_v2_frozen_64` (48 attacks, 16 benign requests)
- Models: `qwen3:8b`, `qwen3.6:latest`
- Generation: temperature 0, top-p 1, seed 42, max output 32 tokens
- Core strategies: none, baseline, full defense
- Single strategies on `qwen3:8b`: input, RAG, and output defense

All valid runs completed 64 cases with zero failed cases. Model, dataset,
policy, experiment, code commit, and run configuration hashes are retained in
the machine-readable report.

## Three-Run Validation Results

| Model | Strategy | Raw compromise | Delivered ASR | RAG ASR | Normal success | Review | Mean P95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| qwen3:8b | none | 44.44% | 44.44% | 16.67% | 93.75% | 0% | 2808 ms |
| qwen3:8b | RAG defense | 35.42% | 35.42% | 0% | 93.75% | 0% | 2666 ms |
| qwen3:8b | full defense | 31.25% | 0% | 0% | 93.75% | 23.44% | 2626 ms |
| qwen3.6:latest | none | 18.75% | 18.75% | 16.67% | 100% | 0% | 4012 ms |
| qwen3.6:latest | RAG defense | 12.50% | 12.50% | 0% | 100% | 0% | 3845 ms |
| qwen3.6:latest | full defense | 12.50% | 0% | 0% | 100% | 9.38% | 3855 ms |

Each row above aggregates three valid runs. The earlier Qwen3.6 baseline P95
outlier of 100941 ms belongs to the one-run baseline experiment and is not part
of the repeated key-strategy matrix. Repeated `none`, RAG, and full-defense P95
values remained between roughly 3.8 and 4.0 seconds, so the old spike is best
treated as transient resource contention rather than normal model latency.

## Single-Defense Results on qwen3:8b

| Strategy | ASR | RAG ASR | Prompt Injection ASR | Jailbreak ASR | Normal success | Review |
|---|---:|---:|---:|---:|---:|---:|
| input defense | 43.75% | 16.67% | 50.00% | 41.67% | 93.75% | 0% |
| RAG defense | 37.50% | 0% | 40.00% | 50.00% | 93.75% | 0% |
| output defense | 0% | 0% | 0% | 0% | 93.75% | 35.94% |

## Findings

1. Full defense reduced delivered ASR to zero on both real models without using
   blanket blocking. It did not reduce raw compromise to zero: the raw rates
   were 31.25% for Qwen3:8b and 12.50% for Qwen3.6.
2. Baseline protection was insufficient. It slightly reduced overall ASR but
   increased measured RAG leakage ASR from 16.67% to 33.33% on both models.
3. RAG defense had an independent effect on `qwen3:8b`: RAG leakage ASR fell
   from 16.67% to zero, while overall ASR only fell from 43.75% to 37.50%.
4. Input defense alone did not improve overall ASR. This confirms that lexical
   normalization and prompt constraints cannot cover response-side leakage.
5. Output defense was the dominant safeguard in this benchmark, but it is a
   post-generation control. Its 35.94% review rate means zero delivered ASR is
   achieved partly by redaction and review, not by preventing model compromise.
6. An earlier `qwen3.6:latest` full-defense attempt failed 61 of 64 cases. The
   invalid run remains in the report for diagnosis and is excluded from metric
   aggregation; the stable retry completed all 64 cases.

## Interpretation

The Mock experiment proves policy wiring and causal contribution under a
controlled vulnerable model. This real-model experiment only validates the
observed trend on two local models. It does not prove universal robustness or
that the underlying model was never attacked; the output layer can prevent an
unsafe response from being delivered after generation.

## Limitations

- The three key groups have three valid runs; single-defense and baseline groups
  remain smaller supporting experiments.
- ASR uses the platform's saved detector outcome and should be cross-checked
  with expanded human review or an independently calibrated Judge.
- The benchmark uses short 32-token outputs and local Ollama inference.
- Local models have zero estimated API cost; token and latency trade-offs are
  still recorded.
- The `qwen3.6:latest` baseline latency anomaly requires a repeat run before
  production capacity conclusions are drawn.

## Reproduction

```powershell
python -m llm_security_platform.scripts.run_real_model_defense_ablation
python -m llm_security_platform.stage_4_5_gate
```

Machine-readable results are stored in
`reports/stage_4_5_real_model_ablation.json`.
