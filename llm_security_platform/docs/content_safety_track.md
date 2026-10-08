# Content-Safety Evaluation Track (HateXplain)

## Why this track exists

The platform's primary pipeline measures **attack success rate (ASR)** against
self-authored prompt-injection / jailbreak / RAG-leakage cases. A fair reviewer
critique is: *those cases are hand-written and self-judged — what externally
validates the detector/judge?*

This track answers that by calibrating classification against a **public,
human-labeled** safety benchmark. It does **not** replace or merge into the ASR
pipeline; it is a separate evaluation paradigm:

| | Attack/defense (ASR) pipeline | Content-safety track |
|---|---|---|
| Input | adversarial attack prompt | a social-media post |
| Process | model generates → defenses → detect breach | classify the post |
| Ground truth | self-authored success indicators | external human labels |
| Metric | ASR, false-positive rate | accuracy, macro-F1, confusion matrix |

## Dataset

[HateXplain](https://github.com/hate-alert/HateXplain) — 20,148 posts (Twitter +
Gab), each labeled by 3 annotators.

- **Gold label** = majority vote of the 3 annotator labels. Posts with no
  majority (all three disagree) are excluded — this matches the official
  `post_id_divisions.json` 8:1:1 split, which already drops them.
- **Classes (3):** `normal`, `offensive`, `hatespeech`.
- **Binary view (2):** `toxic` (= hatespeech ∨ offensive) vs `non-toxic`.
- **Splits:** train 15,383 / val 1,922 / test 1,924.
- **Rationales:** 11,415 posts carry per-annotator token-level rationale masks.
  These are loaded into `ContentSafetyRecord.rationale_mask` (union of
  annotators) but **not yet scored** — they are the hook for a future
  explainability-eval layer (token IoU/F1 of cited evidence vs human rationale),
  which is the standout reason HateXplain was chosen over Davidson.

Provenance is pinned in `data/hatexplain/manifest.json` (source URL, license,
sha256, label distribution).

## Components

| File | Role |
|---|---|
| `app/content_safety/hatexplain_loader.py` | load → majority vote → unified `ContentSafetyRecord`, split-tagged |
| `app/content_safety/classifiers.py` | classifiers under test (majority / tfidf / llm) |
| `app/content_safety/metrics.py` | sklearn metric blocks (3-class + binary toxic) |
| `run_content_safety_benchmark.py` | CLI → JSON report in `reports/content_safety_hatexplain.json` |
| `content_safety_gate.py` | quality gate (baseline must beat majority floor + clear an absolute macro-F1 floor) |
| `tests/test_content_safety.py` | unit tests (loader, metrics, classifiers, gate) |

## Classifiers under test

- **`tfidf`** (default): TF-IDF + LogisticRegression trained on the train split.
  Deterministic, offline, zero API cost. A weak reference model that establishes
  the pipeline floor — **not** a state-of-the-art claim.
- **`majority`**: predicts the most frequent training label. Sanity floor.
- **`llm`**: routes each post through a provider (`mock` / `ollama` /
  `openai_compatible`) with a toxicity-classification prompt. Use `--limit` to
  sample — the full test split is 1,924 calls. This is how the same public
  ground truth can externally calibrate the platform's LLM judging.

## Current offline-baseline result (test = 1,924)

| Classifier | 3-class accuracy | 3-class macro-F1 |
|---|---|---|
| majority floor | 0.41 | 0.19 |
| tfidf baseline | 0.67 | 0.66 |

`offensive` is the hardest class (F1 ≈ 0.52) — the offensive/hate boundary is
genuinely blurred, exactly the problem this dataset is built to study. For
reference, HateXplain's published BERT models reach ~0.68 macro-F1, so the
TF-IDF reference is honest and reasonable.

## Real-model runs: local + cloud LLM judges vs offline baseline

Stratified balanced sample, seed 20260628. Reports:
`reports/content_safety_hatexplain_tfidf_sample.json`,
`reports/content_safety_hatexplain_qwen3_8b.json`,
`reports/content_safety_hatexplain_gemini25.json`.

| Metric | TF-IDF baseline | qwen3:8b (local) | gemini-2.5-flash (Vertex) |
|---|---|---|---|
| clean samples | 300 | 300 | 90¹ |
| 3-class accuracy | 0.61 | 0.53 | 0.57 |
| 3-class macro-F1 | 0.609 | 0.495 | 0.554 |
| binary toxic accuracy | 0.75 | 0.76 | 0.81 |
| toxic recall | — | 0.99 | 0.98 |
| non-toxic recall | — | 0.30 | 0.47 |

¹ Gemini ran on 90 (30/class) at 5s pacing because the new GCP project has a low
per-minute Gemini quota (429 RESOURCE_EXHAUSTED); failed calls are excluded from
metrics, not counted as predictions (`error_count` in the report). The local
models ran on the full 300.

**Finding (the point of the track):** both LLM judges — local **qwen3:8b** and
cloud **gemini-2.5-flash** — show the same **over-moderation bias**. They catch
almost all unsafe content (toxic recall 0.99 / 0.98) but over-flag benign posts
(non-toxic recall 0.30 / 0.47 — i.e. 53–70% of normal posts misclassified as
offensive/hate). The classic TF-IDF model trained on the data is the most
*balanced* (macro-F1 0.609). This is a classic over-refusal safety/usability
trade-off, consistent across a local and a cloud model, and it directly echoes
the **benign false-positive rate** this platform already measures in the
attack/defense pipeline. A public, human-labeled benchmark makes the trade-off
externally measurable rather than asserted.

Caveats: this reflects one prompt, one sample, one decoding setting; the numbers
move with prompt design and are not a verdict on any model's overall quality.
The Gemini provider supports both Vertex AI (ADC, no key) and the Developer API
(AIza key) modes — see `GeminiProvider` and the `gemini` branch of
`build_provider`.

## Rationale / explainability eval

HateXplain's token-level human rationales (which words make a post toxic) are not
just loaded — they are scored. `run_rationale_benchmark.py` asks: when the
classifier flags a post as toxic, does it look at the same tokens a human
highlighted? It compares the model's token-importance mask against the human
rationale mask (token-level precision / recall / F1 / IoU), on toxic posts that
carry a rationale and that the model also predicts toxic.

The offline TF-IDF baseline uses its linear coefficients as a directly
interpretable attribution (`TfidfLogRegBaseline.explain_tokens`). Result
(`reports/content_safety_rationale.json`): on 911 such posts,
macro recall 0.71 / precision 0.43 / F1 0.45 / IoU 0.32 — it covers ~71% of the
human-highlighted tokens but over-marks (diffuse attribution typical of linear
models). This extends the platform's "evidence-citing judge" idea into
content-safety and is the standout signal HateXplain offers over label-only
datasets. (Metrics: `app/content_safety/rationale.py`.)

## Follow-up: LoRA fine-tuned judge and quantized inference

The over-moderation finding raises an obvious question: does a *small* model
fine-tuned on the labels beat a large zero-shot judge? `run_lora_safety_judge.py`
fine-tunes **Qwen3-1.7B** as a 3-class sequence classifier with LoRA
(r=16, alpha=32, q/k/v/o projections; 6.43M trainable params = 0.37% of 1.73B)
on the HateXplain train split (15,383 posts, 2 epochs, lr 2e-4, batch 16,
seed 20260628). The epoch is selected on the **val** split only (best: epoch 2,
val macro-F1 0.693); the test split is never used for selection. Training took
~15 minutes on one RTX 5070 Ti Laptop GPU (12 GB).

Evaluation reuses the exact same seeded stratified sample as the judge reports
(`stratified_100_per_class_seed_20260628`, 300 posts), plus the full test split.
Report: `reports/content_safety_hatexplain_lora_qwen3_1.7b.json`.

| Metric (300-post sample) | TF-IDF | qwen3:8b zero-shot | LoRA Qwen3-1.7B (bf16) |
|---|---:|---:|---:|
| 3-class accuracy | 0.61 | 0.53 | 0.69 |
| 3-class macro-F1 | 0.609 | 0.495 | 0.685 |
| binary macro-F1 | 0.723 | 0.650 | 0.802 |
| toxic recall | — | 0.99 | 0.815 |
| non-toxic recall | 0.66 | 0.30 | 0.82 |

On the full 1,924-post test split the LoRA model reaches macro-F1 0.686 vs
0.656 for TF-IDF. On the 90-post subset used for Gemini 2.5 it scores macro-F1
0.566 (Gemini 0.554) with non-toxic recall 0.80 (Gemini 0.47).

**Finding:** fine-tuning shifts the operating point rather than giving a free
win. Benign posts wrongly flagged drop from 70% (qwen3:8b) to 18%, and macro-F1
rises from 0.495 to 0.685, but toxic recall falls from 0.99 to 0.815. Which point
is right depends on the cost of a missed harmful post versus a wrongly blocked
benign one; a deployment would tune the decision threshold for that trade-off
rather than take argmax.

**Quantized inference** (same adapter, bitsandbytes NF4 base weights):

| | bf16 | NF4 4-bit |
|---|---:|---:|
| full-test macro-F1 (1,924) | 0.686 | 0.688 |
| peak GPU memory | 3,790 MB | 1,858 MB (-51%) |
| batch-1 latency mean / P95 | 80 / 99 ms | 92 / 108 ms |
| batch-32 throughput | 198 posts/s | 196 posts/s |

NF4 halves memory at no measurable quality cost on the full test split, but it
is ~9-14% slower per request because weights are dequantized on the fly; it
buys memory headroom, not speed. (On the 300-post sample NF4 even scores 0.724
vs 0.685; that gap disappears on the full split, so it is sampling noise and
not evidence that quantization helps.)

Reproduce (needs a CUDA torch environment with `transformers`, `peft`,
`accelerate`, `bitsandbytes`; see `requirements-ft.txt`):

```bash
python -m llm_security_platform.run_lora_safety_judge
```

## Honest boundaries

- These numbers describe a specific baseline on a specific dataset. They are not
  a claim about any production model's safety.
- The track measures *classification quality* and rationale alignment, not
  real-time moderation latency or adversarial robustness.
- The LLM-judge variant of rationale scoring (have the model emit evidence spans)
  is a documented extension; the current rationale number is the deterministic
  offline baseline (no API/quota dependency).
