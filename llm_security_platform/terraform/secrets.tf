resource "google_secret_manager_secret" "jwt_secret" {
  secret_id = "llm-security-jwt-secret"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret" "api_key" {
  secret_id = "llm-security-api-key"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret" "encryption_key" {
  secret_id = "llm-security-encryption-key"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret" "db_url_secret" {
  secret_id = "llm-security-database-url"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "db_url_version" {
  secret      = google_secret_manager_secret.db_url_secret.id
  secret_data = "postgresql+psycopg://llm_security:${var.db_password}@/llm_security?host=/cloudsql/${google_sql_database_instance.postgres.connection_name}"
}

resource "google_secret_manager_secret_version" "jwt_secret_version" {
  secret      = google_secret_manager_secret.jwt_secret.id
  secret_data = var.jwt_secret_value
}

resource "google_secret_manager_secret_version" "api_key_version" {
  secret      = google_secret_manager_secret.api_key.id
  secret_data = var.api_key_value
}

resource "google_secret_manager_secret_version" "encryption_key_version" {
  secret      = google_secret_manager_secret.encryption_key.id
  secret_data = var.encryption_key_value
}
