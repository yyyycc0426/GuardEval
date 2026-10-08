resource "google_service_account" "api_sa" {
  account_id   = "llm-security-api-sa"
  display_name = "IAM Service Account for LLM Security API on Cloud Run"
}

# Grant GCS Object Access on Storage Bucket
resource "google_storage_bucket_iam_member" "gcs_role" {
  bucket = google_storage_bucket.storage.name
  role   = "roles/storage.objectUser"
  member = "serviceAccount:${google_service_account.api_sa.email}"
}

# Grant Cloud SQL Client access to connect to postgres database
resource "google_project_iam_member" "sql_client_role" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.api_sa.email}"
}

# Grant Vertex AI User role to call Gemini API
resource "google_project_iam_member" "vertex_ai_role" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.api_sa.email}"
}

# Grant Cloud Tasks Enqueuer role to enqueue async tasks
resource "google_project_iam_member" "tasks_enqueuer_role" {
  project = var.project_id
  role    = "roles/cloudtasks.enqueuer"
  member  = "serviceAccount:${google_service_account.api_sa.email}"
}

# Grant Secret Manager Accessor for API Keys
resource "google_project_iam_member" "secret_accessor_role" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.api_sa.email}"
}

resource "google_service_account" "tasks_sa" {
  account_id   = "llm-security-tasks-sa"
  display_name = "Cloud Tasks Runner Service Account"
}

resource "google_service_account" "gateway_sa" {
  account_id   = "llm-security-gateway-sa"
  display_name = "API Gateway Service Account"
}
