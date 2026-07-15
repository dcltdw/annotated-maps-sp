# deploy/terraform/foundation/outputs.tf
output "state_bucket" {
  value = aws_s3_bucket.tf_state.bucket
}

output "ci_role_arn" {
  value = aws_iam_role.ci.arn
}

output "alerts_topic_arn" {
  value = aws_sns_topic.alerts.arn
}

output "deployer_role_arn" {
  value = aws_iam_role.deployer.arn
}
