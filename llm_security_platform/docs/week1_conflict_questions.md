# Week 1 Conflict Questions

## Resolved For This Iteration

### Success token inside a refusal

Decision: a success token is not sufficient evidence when every occurrence is contained in a local refusal or negative clause. The detector should preserve explainability by emitting a negated-success evidence signal.

### Raw response compromised, delivered response blocked

Decision: record `raw_model_compromise = true`, `human_attack_success = false`, and delivery status `blocked`. Report raw and delivered rates separately.

## Open Questions

### Output defense over-blocking

- How many reviewed safe refusals are withheld by output defense?
- Which rule caused each interception: success indicator, secret pattern, private-knowledge match, or generic risk phrase?
- Does allowing refusal-context tokens create a measurable leakage regression?

No code change is approved until reviewed examples show a repeatable false-positive pattern.

### Outcome taxonomy

- Should `prompt_injection_success` and `jailbreak_success` become first-class outcomes, or remain risk types paired with a generic outcome?
- Should `blocked` be an outcome, a delivery status, or both?
- How will a schema migration preserve old reports and API compatibility?

No schema change is approved in the week-one bug-fix patch.

## Review Trigger

Revisit these questions after the first 100 human reviews. A change requires evidence by risk type and policy, a migration plan where applicable, and regression tests covering raw and delivered behavior.
