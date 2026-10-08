resource "google_cloud_run_v2_service" "api" {
  name     = "llm-security-api"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    scaling {
      max_instance_count = 10
      min_instance_count = 0
    }

    containers {
      image = "gcr.io/${var.project_id}/llm-security-api:latest" # Image repository URL

      ports {
        container_port = 8020
      }

      env {
        name = "LLM_SECURITY_DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.db_url_secret.secret_id
            version = "latest"
          }
        }
      }

      env {
        name  = "LLM_SECURITY_GCS_BUCKET"
        value = google_storage_bucket.storage.name
      }

      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }

      env {
        name  = "GOOGLE_CLOUD_LOCATION"
        value = var.region
      }

      env {
        name  = "LLM_SECURITY_ENV"
        value = "production"
      }

      env {
        name  = "LLM_SECURITY_QUEUE_MODE"
        value = "cloud"
      }

      env {
        name  = "LLM_SECURITY_CLOUD_TASKS_QUEUE"
        value = google_cloud_tasks_queue.evaluation_queue.name
      }

      env {
        name  = "LLM_SECURITY_TASKS_SERVICE_ACCOUNT"
        value = google_service_account.tasks_sa.email
      }

      env {
        name = "LLM_SECURITY_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.api_key.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "LLM_SECURITY_JWT_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.jwt_secret.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "LLM_SECURITY_ENCRYPTION_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.encryption_key.secret_id
            version = "latest"
          }
        }
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "2Gi"
        }
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.postgres.connection_name]
      }
    }

    service_account = google_service_account.api_sa.email
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  depends_on = [
    google_sql_database_instance.postgres,
    google_storage_bucket.storage,
    google_project_service.apis,
    google_secret_manager_secret_version.db_url_version,
    google_secret_manager_secret_version.jwt_secret_version,
    google_secret_manager_secret_version.api_key_version,
    google_secret_manager_secret_version.encryption_key_version
  ]
}

# Only allow invocation from Tasks and API Gateway service accounts
resource "google_cloud_run_service_iam_member" "tasks_invoker" {
  location = google_cloud_run_v2_service.api.location
  project  = google_cloud_run_v2_service.api.project
  service  = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.tasks_sa.email}"
}

resource "google_cloud_run_service_iam_member" "gateway_invoker" {
  location = google_cloud_run_v2_service.api.location
  project  = google_cloud_run_v2_service.api.project
  service  = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.gateway_sa.email}"
}
