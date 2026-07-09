# deploy/terraform/demo/ecr.tf
resource "aws_ecr_repository" "api" {
  name = "annotated-maps-api"
  # Ephemeral env: repos holding images must never block terraform destroy.
  force_delete = true
  image_scanning_configuration { scan_on_push = true }
}

resource "aws_ecr_repository" "web" {
  name         = "annotated-maps-web"
  force_delete = true
  image_scanning_configuration { scan_on_push = true }
}
