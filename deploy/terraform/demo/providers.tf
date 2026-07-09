# deploy/terraform/demo/providers.tf
provider "aws" {
  region = var.region
  default_tags {
    tags = {
      project    = "annotated-maps"
      env        = "demo"
      ephemeral  = "true"
      managed-by = "terraform"
    }
  }
}
