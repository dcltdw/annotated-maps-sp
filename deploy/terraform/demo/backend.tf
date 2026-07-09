# deploy/terraform/demo/backend.tf
# S3 backend with Terraform >= 1.10 NATIVE lockfile — no DynamoDB table.
# The bucket doesn't exist until the persistent foundation/ stack is applied;
# static checks run `init -backend=false`, so this block is inert in CI.
terraform {
  backend "s3" {
    # bucket is account-specific: supplied at init time in PR-2 via
    #   terraform init -backend-config="bucket=annotated-maps-tf-state-<ACCOUNT_ID>"
    key          = "demo/terraform.tfstate"
    region       = "us-east-1"
    use_lockfile = true
  }
}
