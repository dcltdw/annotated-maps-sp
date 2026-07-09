# deploy/terraform/foundation/variables.tf
variable "region" {
  description = "AWS region for persistent foundation resources."
  type        = string
  default     = "us-east-1"
}

variable "budget_alert_email" {
  description = "Email for AWS Budgets alerts. No default on purpose: supplied at apply time, never committed."
  type        = string
}
