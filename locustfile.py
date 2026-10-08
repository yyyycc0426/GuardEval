import os
import random
from locust import HttpUser, task, between

# Read API Key from environment or fallback to default
API_KEY = os.environ.get("LLM_SECURITY_API_KEY", "dev-security-key")


class LLMSecurityUser(HttpUser):
    # Wait between 1 and 3 seconds between tasks to simulate human pace
    wait_time = between(1, 3)

    def on_start(self):
        self.headers = {
            "X-API-Key": API_KEY,
            "Content-Type": "application/json"
        }
        self.active_runs = []

    @task(4)
    def get_health(self):
        """Simulates public status checks"""
        self.client.get("/health")

    @task(3)
    def list_attack_cases(self):
        """Simulates security engineers loading or refreshing cases"""
        self.client.get("/cases", headers=self.headers)

    @task(1)
    def create_evaluation_run(self):
        """Simulates creating an asynchronous evaluation run"""
        # Select randomly between some case lists to avoid identical fingerprints
        case_id_sets = [
            ["atk-001"],
            ["atk-002"],
            ["ok-001"],
            ["atk-001", "ok-001"],
            ["atk-002", "ok-002"],
        ]
        
        payload = {
            "name": f"Locust Load Run {random.randint(1000, 9999)}",
            "provider": "mock",
            "model": "mock-vulnerable-model",
            "defense_policy": "none",
            "judge_provider": "mock",
            "concurrency": 1,
            "case_ids": random.choice(case_id_sets)
        }
        
        with self.client.post("/async-runs", json=payload, headers=self.headers, catch_response=True) as response:
            if response.status_code == 202:
                response.success()
                try:
                    data = response.json()
                    run_id = data["data"]["run_id"]
                    self.active_runs.append(run_id)
                except Exception:
                    pass
            elif response.status_code == 409:
                # 409 is expected when active run locks trigger during concurrent load
                response.success()
            else:
                response.failure(f"Unexpected status code: {response.status_code}")

    @task(2)
    def check_run_status(self):
        """Simulates checking status of evaluations in progress"""
        if not self.active_runs:
            return
            
        run_id = random.choice(self.active_runs)
        with self.client.get(f"/async-runs/{run_id}", headers=self.headers, catch_response=True) as response:
            if response.status_code == 200:
                response.success()
                try:
                    data = response.json()
                    status = data["data"]["run"]["status"]
                    # If run is in terminal state, we stop polling it
                    if status in ("COMPLETED", "FAILED", "PARTIAL_FAILED", "CANCELLED"):
                        self.active_runs.remove(run_id)
                except Exception:
                    pass
            elif response.status_code == 404:
                # Stale or missing run from other sessions
                response.success()
                self.active_runs.remove(run_id)
            else:
                response.failure(f"Unexpected status code: {response.status_code}")
