# Alert Policy for Cloud Run 5xx Server Error Rate
resource "google_monitoring_alert_policy" "api_error_rate" {
  display_name = "LLM Security API 5xx Error Alert"
  combinator   = "OR"

  conditions {
    display_name = "Cloud Run HTTP 5xx Error Rate Threshold"

    condition_threshold {
      filter          = "resource.type = \"cloud_run_revision\" AND resource.labels.service_name = \"llm-security-api\" AND metric.type = \"run.googleapis.com/request_count\" AND metric.labels.response_code_class = \"5xx\""
      duration        = "60s"
      comparison      = "COMPARISON_GT"
      threshold_value = 5.0 # More than 5 errors in a minute triggers alert

      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_RATE"
        cross_series_reducer = "REDUCE_SUM"
      }
    }
  }

  notification_channels = [] # Define Notification Channels (e.g. email/pagerduty) if needed
}

# Billing budget alert (informational block, standard setup)
# Requires billing account metadata mapping.
