# deploy/terraform/demo/variables.tf
variable "region" {
  description = "AWS region for the demo environment."
  type        = string
  default     = "us-east-1"
}

variable "cluster_name" {
  description = "EKS cluster name (also used in resource names and tags)."
  type        = string
  default     = "annotated-maps-demo"
}
