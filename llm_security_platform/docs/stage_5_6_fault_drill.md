# Stage 5.6 Fault Drill

The fault drill was executed against the rebuilt Docker Compose stack on
2026-06-13. The machine-readable evidence is stored in
`reports/stage_5_6_fault_drill.json`.

## Results

1. Worker interruption: a queued run remained `PENDING`; after Worker restart
   it completed both cases without loss.
2. Redis restart: Redis returned `PONG` and the API remained healthy after
   recovery.
3. Model timeout: the run reached `FAILED` and retained the case-level timeout
   message.
4. Duplicate delivery: two repeated task executions returned `ignored`; case
   attempts remained one.
5. Single-case failure: one failed and one successful case produced
   `PARTIAL_FAILED`, proving failure isolation.
6. Cancellation: a queued three-case run reached `CANCELLED` without executing
   its cases.

Mock-only fault controls (`inject_delay_ms` and `fail_on_text`) are accepted
through run model configuration and are used only to produce deterministic
failure scenarios. They do not change real-model provider behavior.
