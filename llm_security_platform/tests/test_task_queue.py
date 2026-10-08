import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Dynamic mock injection for Google Cloud modules when they are not installed in the local environment
try:
    import google.cloud.tasks_v2
    from google.api_core import exceptions
except ModuleNotFoundError:
    from types import ModuleType
    
    if "google" in sys.modules:
        google = sys.modules["google"]
    else:
        google = ModuleType("google")
        google.__path__ = []
        sys.modules["google"] = google
        
    if hasattr(google, "cloud"):
        cloud = google.cloud
    elif "google.cloud" in sys.modules:
        cloud = sys.modules["google.cloud"]
        google.cloud = cloud
    else:
        cloud = ModuleType("google.cloud")
        cloud.__path__ = []
        sys.modules["google.cloud"] = cloud
        google.cloud = cloud
        
    if hasattr(google, "api_core"):
        api_core = google.api_core
    elif "google.api_core" in sys.modules:
        api_core = sys.modules["google.api_core"]
        google.api_core = api_core
    else:
        api_core = ModuleType("google.api_core")
        api_core.__path__ = []
        sys.modules["google.api_core"] = api_core
        google.api_core = api_core
        
    google.cloud.tasks_v2 = ModuleType("google.cloud.tasks_v2")
    google.api_core.exceptions = ModuleType("google.api_core.exceptions")
    
    class MockAlreadyExistsException(Exception):
        pass
        
    class MockCloudTasksClient(MagicMock):
        pass
        
    google.cloud.tasks_v2.CloudTasksClient = MockCloudTasksClient
    google.api_core.exceptions.AlreadyExists = MockAlreadyExistsException
    
    sys.modules["google.cloud.tasks_v2"] = google.cloud.tasks_v2
    sys.modules["google.api_core.exceptions"] = google.api_core.exceptions



class TaskQueueTests(unittest.TestCase):
    @patch.dict(os.environ, {"LLM_SECURITY_QUEUE_MODE": "local"})
    def test_local_queue_resolution(self):
        # Reloading task_queue to trigger mode re-evaluation
        import importlib
        import llm_security_platform.app.task_queue as tq
        importlib.reload(tq)
        
        self.assertIsInstance(tq.task_queue, tq.CeleryTaskQueue)

    @patch.dict(os.environ, {"LLM_SECURITY_QUEUE_MODE": "cloud"})
    def test_cloud_queue_resolution(self):
        import importlib
        import llm_security_platform.app.task_queue as tq
        importlib.reload(tq)
        
        self.assertIsInstance(tq.task_queue, tq.CloudTasksTaskQueue)

    @patch.dict(os.environ, {
        "LLM_SECURITY_QUEUE_MODE": "cloud",
        "GOOGLE_CLOUD_PROJECT": "test-project",
        "GOOGLE_CLOUD_LOCATION": "us-central1",
        "LLM_SECURITY_WORKER_SERVICE_URL": "https://service-url.run.app",
        "LLM_SECURITY_TASKS_SERVICE_ACCOUNT": "tasks-sa@test-project.iam.gserviceaccount.com"
    })
    @patch("google.cloud.tasks_v2.CloudTasksClient")
    @patch("llm_security_platform.app.production_store.set_task_id")
    def test_cloud_tasks_enqueue_payload_and_idempotency(self, mock_set_task_id, mock_tasks_client_class):
        import importlib
        import llm_security_platform.app.task_queue as tq
        importlib.reload(tq)
        
        mock_client = MagicMock()
        mock_tasks_client_class.return_value = mock_client
        mock_client.queue_path.return_value = "projects/test-project/locations/us-central1/queues/evaluation-run-queue"
        mock_response = MagicMock()
        mock_response.name = "projects/test-project/locations/us-central1/queues/evaluation-run-queue/tasks/run123"
        mock_client.create_task.return_value = mock_response
        
        task_id = tq.task_queue.enqueue("run123", "tenant123", "trace123")
        
        # Verify Cloud Tasks client is invoked
        mock_client.create_task.assert_called_once()
        create_task_kwargs = mock_client.create_task.call_args[1]
        task = create_task_kwargs["request"]["task"]
        
        # Verify correct OIDC token integration and HTTP configuration
        self.assertEqual(task["name"], "projects/test-project/locations/us-central1/queues/evaluation-run-queue/tasks/run123")
        self.assertEqual(task["http_request"]["url"], "https://service-url.run.app/tasks/execute-run")
        self.assertEqual(task["http_request"]["oidc_token"]["service_account_email"], "tasks-sa@test-project.iam.gserviceaccount.com")
        self.assertEqual(task["http_request"]["oidc_token"]["audience"], "https://service-url.run.app")
        
        # Verify database task tracking hook was called
        mock_set_task_id.assert_called_once_with("run123", mock_response.name)
        self.assertEqual(task_id, mock_response.name)

    @patch.dict(os.environ, {
        "LLM_SECURITY_QUEUE_MODE": "cloud",
        "GOOGLE_CLOUD_PROJECT": "test-project",
        "GOOGLE_CLOUD_LOCATION": "us-central1",
        "LLM_SECURITY_WORKER_SERVICE_URL": "https://service-url.run.app"
    })
    @patch("google.cloud.tasks_v2.CloudTasksClient")
    @patch("llm_security_platform.app.production_store.set_task_id")
    def test_cloud_tasks_idempotent_duplicate_handling(self, mock_set_task_id, mock_tasks_client_class):
        import importlib
        import llm_security_platform.app.task_queue as tq
        importlib.reload(tq)
        
        mock_client = MagicMock()
        mock_tasks_client_class.return_value = mock_client
        mock_client.queue_path.return_value = "projects/test-project/locations/us-central1/queues/evaluation-run-queue"
        
        from google.api_core import exceptions
        # Simulate Google Cloud tasks ALREADY_EXISTS exception
        mock_client.create_task.side_effect = exceptions.AlreadyExists("Task already exists")
        
        task_id = tq.task_queue.enqueue("run123", "tenant123")
        
        # Verify it gracefully handles the ALREADY_EXISTS exception without throwing,
        # and registers/returns the expected idempotent task name path
        expected_task_name = "projects/test-project/locations/us-central1/queues/evaluation-run-queue/tasks/run123"
        self.assertEqual(task_id, expected_task_name)
        mock_set_task_id.assert_called_once_with("run123", expected_task_name)
