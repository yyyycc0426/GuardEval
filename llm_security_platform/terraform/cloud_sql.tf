resource "google_sql_database_instance" "postgres" {
  name             = "llm-security-db-${var.environment}"
  database_version = "POSTGRES_16"
  region           = var.region

  settings {
    tier = "db-f1-micro" # Lightweight cost-friendly serverless tier

    database_flags {
      name  = "max_connections"
      value = "100"
    }

    backup_configuration {
      enabled    = true
      start_time = "02:00"
    }

    ip_configuration {
      ipv4_enabled = true # Enabling public IP for Cloud SQL Auth Proxy connection
      # For enterprise security, VPC private service access would restrict this further.
    }
  }

  deletion_protection = false # Set true for active production
}

resource "google_sql_database" "database" {
  name     = "llm_security"
  instance = google_sql_database_instance.postgres.name
}

resource "google_sql_user" "db_user" {
  name     = "llm_security"
  instance = google_sql_database_instance.postgres.name
  password = var.db_password
}
