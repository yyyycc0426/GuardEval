import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from llm_security_platform.scripts.stage_five_e2e_smoke import (
    api,
    run_command,
    wait_for_api,
    wait_for_run,
)


def create_run(name, case_ids, model_config=None):
    payload = {
        "name": name,
        "provider": "mock",
        "defense_policy": "none",
        "case_ids": case_ids,
        "model_config": model_config or {},
    }
    return api("POST", "/async-runs", "analyst-key", payload, expected=202)["data"]["run_id"]


def worker_interruption():
    run_command("stop", "worker")
    run_id = create_run("fault-worker-interruption", ["atk-001", "ok-001"])
    time.sleep(2)
    pending = api("GET", f"/async-runs/{run_id}")["data"]["run"]
    if pending["status"] != "PENDING":
        raise AssertionError(f"run should remain PENDING without worker: {pending}")
    run_command("start", "worker")
    result = wait_for_run(run_id, "COMPLETED", timeout=180)
    return {"run_id": run_id, "recovered_status": result["run"]["status"]}


def redis_restart():
    run_command("restart", "redis")
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            if "PONG" in run_command("exec", "-T", "redis", "redis-cli", "ping"):
                wait_for_api(30)
                return {"redis": "PONG", "api": "healthy"}
        except Exception:
            time.sleep(2)
    raise TimeoutError("Redis/API did not recover after restart")


def timeout_drill():
    run_id = create_run(
        "fault-timeout", ["atk-001"],
        {"inject_delay_ms": 200, "timeout_seconds": 0.05},
    )
    result = wait_for_run(run_id, "FAILED")
    error_text = json.dumps(result, ensure_ascii=False)
    if "timed out" not in error_text:
        raise AssertionError(f"timeout reason missing: {result}")
    return {"run_id": run_id, "status": "FAILED", "diagnostic": "timed out"}


def single_case_failure():
    run_id = create_run(
        "fault-single-case", ["atk-001", "ok-001"],
        {"fail_on_text": "INJECTION_SUCCEEDED"},
    )
    result = wait_for_run(run_id, "PARTIAL_FAILED")
    return {
        "run_id": run_id,
        "status": result["run"]["status"],
        "success_cases": result["run"]["success_cases"],
        "failed_cases": result["run"]["failed_cases"],
    }


def duplicate_delivery():
    run_id = create_run("fault-duplicate-delivery", ["ok-001"])
    first = wait_for_run(run_id, "COMPLETED")
    attempts_before = first["cases"][0]["attempts"]
    for _ in range(2):
        run_command(
            "exec", "-T", "worker", "celery", "-A",
            "llm_security_platform.app.tasks:celery_app", "call",
            "security.execute_evaluation_run", f"--args=[\"{run_id}\"]",
        )
    time.sleep(3)
    after = api("GET", f"/async-runs/{run_id}")["data"]
    attempts_after = after["cases"][0]["attempts"]
    if attempts_after != attempts_before:
        raise AssertionError("duplicate delivery re-executed a completed case")
    return {"run_id": run_id, "attempts_before": attempts_before, "attempts_after": attempts_after}


def cancellation():
    run_command("stop", "worker")
    run_id = create_run("fault-cancel", ["atk-001", "atk-002", "ok-001"])
    api("POST", f"/async-runs/{run_id}/cancel", "analyst-key")
    run_command("start", "worker")
    result = wait_for_run(run_id, "CANCELLED")
    return {"run_id": run_id, "status": result["run"]["status"]}


def main():
    parser = argparse.ArgumentParser(description="Run Stage 5.6 Docker fault drills")
    parser.add_argument("--output", type=Path, default=Path("llm_security_platform/reports/stage_5_6_fault_drill.json"))
    parser.add_argument("--skip-up", action="store_true")
    args = parser.parse_args()
    started = time.monotonic()
    if not args.skip_up:
        run_command("up", "-d", "--build", timeout=1800)
    wait_for_api()
    checks = {
        "worker_interruption": worker_interruption(),
        "redis_restart": redis_restart(),
        "model_timeout": timeout_drill(),
        "duplicate_delivery": duplicate_delivery(),
        "single_case_failure": single_case_failure(),
        "task_cancellation": cancellation(),
    }
    report = {
        "status": "passed",
        "executed_at": datetime.now(UTC).isoformat(),
        "duration_seconds": round(time.monotonic() - started, 3),
        "checks": checks,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
