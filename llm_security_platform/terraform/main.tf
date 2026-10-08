terraform {
  required_version = ">= 1.5.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.10.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# Required Google APIs
locals {
  apis = [
    "run.googleapis.com",             # Cloud Run
    "sqladmin.googleapis.com",        # Cloud SQL Admin
    "storage.googleapis.com",         # Google Cloud Storage
    "secretmanager.googleapis.com",   # Secret Manager
    "cloudtasks.googleapis.com",      # Cloud Tasks
    "aiplatform.googleapis.com",      # Vertex AI (Gemini)
    "monitoring.googleapis.com",      # Cloud Monitoring
    "logging.googleapis.com",         # Cloud Logging
    "vpcaccess.googleapis.com"        # Serverless VPC Access (Optional, for SQL private IP)
  ]
}

resource "google_project_service" "apis" {
  for_each           = toset(local.apis)
  project            = var.project_id
  service            = each.key
  disable_on_destroy = false
}
