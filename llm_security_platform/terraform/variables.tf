variable "project_id" {
  type        = string
  description = "The Google Cloud Project ID where resources will be provisioned."
}

variable "region" {
  type        = string
  default     = "us-central1"
  description = "The primary GCP region for serverless compute and database resources."
}

variable "environment" {
  type        = string
  default     = "production"
  description = "Target deployment environment (development, staging, production)."
}

variable "db_password" {
  type        = string
  sensitive   = true
  description = "The master password for the Cloud SQL PostgreSQL instance."
}

variable "gcs_bucket_name" {
  type        = string
  description = "Name of the Google Cloud Storage bucket for saving reports, datasets, and evidence."
}

variable "jwt_secret_value" {
  type        = string
  sensitive   = true
  description = "Value for the LLM Security JWT signing secret. Must be supplied via TF_VAR_jwt_secret_value in CI — never hardcoded."
}

variable "api_key_value" {
  type        = string
  sensitive   = true
  description = "Value for the LLM Security API key. Must be supplied via TF_VAR_api_key_value in CI — never hardcoded."
}

variable "encryption_key_value" {
  type        = string
  sensitive   = true
  description = "Fernet encryption key for at-rest data. Must be supplied via TF_VAR_encryption_key_value in CI — never hardcoded."
}
