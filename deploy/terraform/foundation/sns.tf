# deploy/terraform/foundation/sns.tf
# Lifecycle events for the demo pipeline (M4 spec §5). One topic carries
# everything (demo-ready, run-summary, teardown-failed), each publish tagged
# with a `severity` message attribute. The email subscription filters
# severity=alert — the inbox gets failures only; widen the filter to
# ["alert","info"] to also receive demo-ready/run-summary events.
# Volume is a few messages/month: comfortably $0 (SNS free tier).
resource "aws_sns_topic" "alerts" {
  name = "annotated-maps-alerts"
}

resource "aws_sns_topic_subscription" "email_alerts" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = "dcltdw@protonmail.com"
  # Requires a one-time "Confirm subscription" click in the inbox.
  filter_policy = jsonencode({
    severity = ["alert"]
  })
}
