resource "google_storage_bucket" "storage" {
  name                        = var.gcs_bucket_name
  location                    = var.region
  force_destroy               = false
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      age = 90
    }
    action {
      type = "Delete"
    }
  }

  labels = {
    environment = var.environment
    project     = "llm-security-platform"
  }
}
