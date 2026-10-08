resource "google_cloud_tasks_queue" "evaluation_queue" {
  name     = "evaluation-run-queue"
  location = var.region

  rate_limits {
    max_concurrent_dispatches = 10
    max_dispatches_per_second = 5
  }

  retry_config {
    max_attempts       = 3
    max_backoff        = "3600s"
    min_backoff        = "5s"
    max_doublings      = 4
  }
}
