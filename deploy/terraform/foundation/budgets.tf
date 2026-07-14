# deploy/terraform/foundation/budgets.tf
# The guardrail. Applied FIRST, before any EKS spend exists — it must always
# guard the account, so it lives here in the persistent foundation stack, not
# in the ephemeral demo/ stack that gets torn down every run.
resource "aws_budgets_budget" "demo" {
  name         = "annotated-maps-demo"
  budget_type  = "COST"
  limit_amount = "10"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  dynamic "notification" {
    for_each = [50, 80, 100]
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = [var.budget_alert_email]
    }
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.budget_alert_email]
  }
}
