variable "aws_region" {
  description = "AWS region to deploy the solution"
  type        = string
  default     = "us-east-1"
}

variable "scan_regions" {
  description = "List of AWS regions to scan"
  type        = list(string)
  default     = ["us-east-1", "us-west-2"]
}

variable "audit_accounts" {
  description = "List of audit/security tooling account IDs"
  type        = list(string)
}

variable "log_archive_accounts" {
  description = "List of log archive account IDs"
  type        = list(string)
}

variable "sra_member_role_name" {
  description = "Name of the IAM role deployed to member accounts"
  type        = string
  default     = "SRAMemberRole"
}

variable "lambda_timeout" {
  description = "Lambda timeout in seconds (max 900)"
  type        = number
  default     = 900
}

variable "lambda_memory" {
  description = "Lambda memory in MB"
  type        = number
  default     = 512
}
