output "api_service_url" {
  value       = google_cloud_run_v2_service.api.uri
  description = "The public URL of the deployed FastAPI Security Evaluation Service."
}

output "db_connection_name" {
  value       = google_sql_database_instance.postgres.connection_name
  description = "The connection string name of the Google Cloud SQL PostgreSQL instance."
}

output "storage_bucket_url" {
  value       = google_storage_bucket.storage.url
  description = "The URL of the GCS bucket for files and reports."
}
