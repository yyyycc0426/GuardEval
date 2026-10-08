import os
import json
import logging
from abc import ABC, abstractmethod
from llm_security_platform.app.production_store import set_task_id

logger = logging.getLogger("llm_security_platform.task_queue")

class BaseTaskQueue(ABC):
    @abstractmethod
    def enqueue(self, run_id: str, tenant_id: str = "default", trace_id: str | None = None) -> str:
        """
        Dispatches the evaluation run to the task queue.
        Returns the unique task ID or task name path.
        """
        pass

class CeleryTaskQueue(BaseTaskQueue):
    def enqueue(self, run_id: str, tenant_id: str = "default", trace_id: str | None = None) -> str:
        from llm_security_platform.app.tasks import execute_evaluation_run
        result = execute_evaluation_run.delay(run_id, tenant_id=tenant_id, trace_id=trace_id)
        set_task_id(run_id, result.id)
        logger.info(f"Dispatched run {run_id} to Celery Task Queue. Task ID: {result.id}")
        return result.id

class CloudTasksTaskQueue(BaseTaskQueue):
    def enqueue(self, run_id: str, tenant_id: str = "default", trace_id: str | None = None) -> str:
        import os
        from google.cloud import tasks_v2
        from google.api_core import exceptions
        
        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
        queue = os.environ.get("LLM_SECURITY_CLOUD_TASKS_QUEUE", "evaluation-run-queue")
        service_url = os.environ.get("LLM_SECURITY_WORKER_SERVICE_URL")
        
        if not project or not service_url:
            raise ValueError(
                "GOOGLE_CLOUD_PROJECT and LLM_SECURITY_WORKER_SERVICE_URL environment variables "
                "are required for Cloud Tasks execution."
            )
            
        client = tasks_v2.CloudTasksClient()
        parent = client.queue_path(project, location, queue)
        
        url = f"{service_url.rstrip('/')}/tasks/execute-run"
        payload = {
            "run_id": run_id,
            "tenant_id": tenant_id,
            "trace_id": trace_id
        }
        
        task = {
            "http_request": {
                "http_method": "POST",
                "url": url,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps(payload).encode("utf-8")
            }
        }
        
        # Attach OIDC token for invoking authenticated Cloud Run service
        tasks_service_account = os.environ.get("LLM_SECURITY_TASKS_SERVICE_ACCOUNT")
        if tasks_service_account:
            task["http_request"]["oidc_token"] = {
                "service_account_email": tasks_service_account,
                "audience": service_url
            }
            
        # Guarantee Task Dispatch Idempotency
        # Cloud Tasks task name format: projects/PROJECT/locations/LOCATION/queues/QUEUE/tasks/TASK_ID
        # Using run_id as the task ID handles deduplication natively.
        task_name = f"{parent}/tasks/{run_id}"
        task["name"] = task_name
        
        try:
            response = client.create_task(request={"parent": parent, "task": task})
            task_id = response.name
            set_task_id(run_id, task_id)
            logger.info(f"Dispatched run {run_id} to Cloud Tasks. Task Name: {task_id}")
            return task_id
        except exceptions.AlreadyExists:
            logger.warning(f"Task already exists in queue (Idempotent Dispatch Bypass): {task_name}")
            set_task_id(run_id, task_name)
            return task_name
        except Exception as exc:
            logger.error(f"Cloud Tasks dispatch failed: {exc}")
            raise exc

# Queue Factory
queue_mode = os.environ.get("LLM_SECURITY_QUEUE_MODE", "local").lower()
if queue_mode == "cloud":
    task_queue = CloudTasksTaskQueue()
else:
    task_queue = CeleryTaskQueue()
