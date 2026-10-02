variable "aws_account_id" {
  type        = string
  description = "Expected account. The provider refuses credentials for another account."
  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "Supply your own 12-digit AWS account ID."
  }
}
variable "region" {
  type = string
}
variable "vpc_id" {
  type        = string
  default     = ""
  description = "Optional existing VPC. Empty creates a dedicated isolated VPC."
}
variable "task_subnet_ids" {
  type        = list(string)
  default     = []
  description = "Required for an existing VPC; otherwise dedicated public subnets are created."
}
variable "alb_subnet_ids" {
  type        = list(string)
  default     = []
  description = "At least two public subnets in distinct AZs when create_service is true."
}
variable "assign_public_ip" {
  type    = bool
  default = false
}
variable "create_service" {
  type        = bool
  default     = false
  description = "Bootstrap resources/image first; enable after pushing the image and configuring HTTPS/auth."
}
variable "certificate_arn" {
  type    = string
  default = ""
}
variable "public_url" {
  type    = string
  default = ""
}
variable "bearer_secret_arn" {
  type        = string
  default     = ""
  description = "Existing Secrets Manager secret containing only the bearer token, never the token value."
}
variable "oauth_issuer" {
  type    = string
  default = ""
}
variable "kms_key_arns" {
  type        = list(string)
  default     = []
  description = "Optional customer-managed keys needed to decrypt your Secrets Manager secret."
}
variable "image_tag" {
  type    = string
  default = "0.36.0"
}
variable "cpu_architecture" {
  type    = string
  default = "ARM64"
  validation {
    condition     = contains(["ARM64", "X86_64"], var.cpu_architecture)
    error_message = "Use ARM64 or X86_64 and build the matching Docker platform."
  }
}
variable "allow_destroy_graph" {
  type        = bool
  default     = false
  description = "Dangerous: permit terraform destroy to delete all graph objects/versions. Enable only for disposable tests."
}
variable "allowed_cidrs" {
  type        = list(string)
  default     = ["0.0.0.0/0"]
  description = "HTTPS ingress to the authenticated ALB. Restrict to your team's network where possible."
}
