# Holdout and Human-Review Protocol

## Frozen Holdout

`data/holdout_inputs_v1.json` contains 128 unlabeled inputs: 96 attacks and 32
benign hard negatives. Development code may read this file, but it must not read
the private label artifact.

`data/private_holdout_labels.json` is intentionally excluded from version
control. The evaluator custodian keeps it outside the development workflow.
`data/holdout_manifest_v1.json` stores SHA-256 hashes for both artifacts so any
post-freeze modification is detectable.

Build and freeze:

```powershell
python -m llm_security_platform.scripts.build_holdout_dataset
```

After freezing, move the private label file to evaluator-controlled storage.
Do not tune rules, prompts, classifiers, or policies against unsealed results.

## Human Review

The review packet includes:

- every delivered attack success;
- every output-defense interception;
- a seeded 10% sample of otherwise safe results.

```powershell
python -m llm_security_platform.scripts.build_real_model_review_packet
```

A Reviewer fills `human_final_label`, `human_attack_success`,
`raw_model_compromise`, `reviewer_note`, and `reviewer`.
`human_attack_success` evaluates the delivered response, while
`raw_model_compromise` evaluates the pre-output-defense response. Automated
Judge output is context only and must not be copied without independent
inspection.

AI-assisted labels must use a distinct reviewer identity and remain provisional
until a person spot-checks all conflicts, all high-risk successes, and a random
sample of agreements. They must not be reported as independent human gold
labels.

Calculate agreement only after review:

```powershell
python -m llm_security_platform.scripts.finalize_real_model_review
```

The report compares the raw-response Judge with `raw_model_compromise`, and the
delivered-response detector with `human_attack_success`. Comparing a raw Judge
directly with a delivered label is invalid because output defense may change the
result. An incomplete packet deliberately produces null agreement metrics
rather than pretending that an automated judgment is a human label.
