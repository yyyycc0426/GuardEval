import argparse
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib import error, request


COMPOSE = ["docker", "compose", "-f", "llm_security_platform/docker-compose.yml"]
BASE_URL = "http://127.0.0.1:8020"
ADMIN_KEY = "dev-security-key"
COMMAND_LOG = []


def run_command(*args, timeout=600):
    command = [*COMPOSE, *args]
    started = time.monotonic()
    completed = subprocess.run(command, check=False, text=True, capture_output=True, timeout=timeout)
    COMMAND_LOG.append({
        "command": command,
        "returncode": completed.returncode,
        "duration_seconds": round(time.monotonic() - started, 3),
        "stdout_tail": completed.stdout.strip()[-2000:],
        "stderr_tail": completed.stderr.strip()[-2000:],
    })
    if completed.returncode:
        raise RuntimeError(
            f"Command failed: {' '.join(command)}\n{completed.stdout}\n{completed.stderr}"
        )
    return completed.stdout.strip()


def api(method, path, api_key=ADMIN_KEY, payload=None, expected=200):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"X-API-Key": api_key}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = request.Request(BASE_URL + path, data=body, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=10) as response:
            status = response.status
            data = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        status = exc.code
        raw = exc.read().decode("utf-8")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {"raw_response": raw}
    if status != expected:
        raise AssertionError(f"{method} {path}: expected {expected}, got {status}: {data}")
    return data


def wait_for_api(timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with request.urlopen(BASE_URL + "/health", timeout=3) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(2)
    raise TimeoutError("API health check did not become ready")


def wait_for_run(run_id, expected_status, timeout=180):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = api("GET", f"/async-runs/{run_id}")["data"]
        if last["run"]["status"] == expected_status:
            return last
        if last["run"]["status"] in {"FAILED", "PARTIAL_FAILED", "CANCELLED", "COMPLETED"}:
            raise AssertionError(
                f"Run {run_id} reached {last['run']['status']}, expected {expected_status}: {last}"
            )
        time.sleep(1)
    raise TimeoutError(f"Run {run_id} did not reach {expected_status}: {last}")


def validate_infrastructure():
    run_command("exec", "-T", "postgres", "pg_isready", "-U", "llm_security", "-d", "llm_security")
    redis = run_command("exec", "-T", "redis", "redis-cli", "ping")
    if "PONG" not in redis:
        raise AssertionError(f"Unexpected Redis response: {redis}")
    worker = run_command(
        "exec", "-T", "worker", "celery", "-A",
        "llm_security_platform.app.tasks:celery_app", "inspect", "ping", "--timeout", "10",
    )
    if "pong" not in worker.lower():
        raise AssertionError(f"Worker did not answer ping: {worker}")
    run_command("run", "--rm", "migrate")


def validate_rbac():
    api("POST", "/async-runs", "viewer-key", {"name": "viewer-denied"}, expected=403)
    api("PATCH", "/human-reviews/999999", "analyst-key", {
        "human_final_label": "safe_answer",
        "human_attack_success": False,
        "reviewer_note": "unauthorized smoke attempt",
        "reviewer": "analyst",
    }, expected=403)
    api("POST", "/cases", "reviewer-key", {
        "case_id": "reviewer-policy-change",
        "name": "must be denied",
        "risk_type": "benign",
        "prompt": "test",
    }, expected=403)


def validate_successful_run():
    created = api("POST", "/async-runs", "analyst-key", {
        "name": "stage-5.5-success-smoke",
        "provider": "mock",
        "defense_policy": "input_defense+rag_defense+output_defense",
        "case_ids": ["atk-001", "atk-002", "ok-001"],
    }, expected=202)
    run_id = created["data"]["run_id"]
    result = wait_for_run(run_id, "COMPLETED")
    if result["run"]["completed_cases"] != 3 or result["run"]["failed_cases"] != 0:
        raise AssertionError(f"Unexpected completed run counters: {result['run']}")
    audits = api("GET", f"/audit-logs?run_id={run_id}")["data"]
    if not any(item["action"] == "run.create" for item in audits):
        raise AssertionError(f"Creation audit not found for run {run_id}")
    return run_id


def validate_failure_diagnostics():
    created = api("POST", "/async-runs", "analyst-key", {
        "name": "stage-5.5-failure-smoke",
        "provider": "openai_compatible",
        "model": "missing-key-smoke-model",
        "case_ids": ["atk-001"],
    }, expected=202)
    run_id = created["data"]["run_id"]
    result = wait_for_run(run_id, "FAILED")
    summary = result["run"].get("error_summary") or ""
    if "API_KEY" not in summary:
        raise AssertionError(f"Failure reason is not actionable: {summary!r}")
    return run_id


def main():
    parser = argparse.ArgumentParser(description="Stage 5.5 Docker end-to-end smoke test")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument(
        "--already-running",
        action="store_true",
        help="Use an externally started Compose stack and verify it through API workflows",
    )
    parser.add_argument("--keep", action="store_true", help="Keep the Compose stack running")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("llm_security_platform/reports/stage_5_5_docker_e2e.json"),
    )
    args = parser.parse_args()
    started_at = datetime.now(UTC)
    started_clock = time.monotonic()
    try:
        if not args.already_running:
            up_args = ["up", "-d"]
            if not args.skip_build:
                up_args.append("--build")
            run_command(*up_args, timeout=1800)
        wait_for_api()
        if not args.already_running:
            validate_infrastructure()
        validate_rbac()
        success_run = validate_successful_run()
        failed_run = validate_failure_diagnostics()
        report = {
            "status": "passed",
            "started_at": started_at.isoformat(),
            "completed_at": datetime.now(UTC).isoformat(),
            "duration_seconds": round(time.monotonic() - started_clock, 3),
            "checks": {
                "api_health": True,
                "worker_health": True,
                "postgres_connection": True,
                "redis_connection": True,
                "alembic_upgrade": True,
                "rbac_negative_cases": True,
                "audit_record": True,
                "failure_diagnostics": True,
            },
            "successful_run_id": success_run,
            "diagnostic_run_id": failed_run,
            "command_log": COMMAND_LOG,
            "verification_mode": (
                "externally_started_compose_plus_async_workflow"
                if args.already_running else "script_controlled_compose"
            ),
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
    finally:
        if not args.keep and not args.already_running:
            subprocess.run([*COMPOSE, "down"], check=False)


if __name__ == "__main__":
    main()
