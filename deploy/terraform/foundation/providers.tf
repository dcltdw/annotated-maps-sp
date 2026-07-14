# deploy/terraform/foundation/providers.tf
provider "aws" {
  region = var.region
  default_tags {
    # This stack is the PERSISTENT layer (state bucket, CI role, budget) — it
    # outlives every demo. Tag it ephemeral=false so a future tag-based cleanup
    # keyed on ephemeral=true can never sweep it. (The demo/ stack is the
    # ephemeral one and tags itself ephemeral=true.)
    tags = {
      project    = "annotated-maps"
      env        = "foundation"
      ephemeral  = "false"
      managed-by = "terraform"
    }
  }
}
