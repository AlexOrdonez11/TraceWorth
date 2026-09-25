variable "aws_region" {
  type    = string
  default = "us-east-2"
}
variable "expected_account_id" {
  type = string
  validation {
    condition     = can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "Specify the intended 12-digit AWS account ID."
  }
}
variable "vpc_cidr" {
  type    = string
  default = "10.42.0.0/16"
}
variable "pilot_ipv4_cidrs" {
  description = "Public egress IPv4 CIDRs for pilot team and instrumented applications. No worldwide access."
  type        = list(string)
  validation {
    condition     = length(var.pilot_ipv4_cidrs) > 0 && alltrue([for c in var.pilot_ipv4_cidrs : can(cidrnetmask(c)) && c != "0.0.0.0/0"])
    error_message = "Supply explicit pilot IPv4 CIDRs; 0.0.0.0/0 is prohibited."
  }
}
variable "alert_email" {
  type = string
  validation {
    condition     = can(regex("^[^@ ]+@[^@ ]+\\.[^@ ]+$", var.alert_email))
    error_message = "Provide a monitored alert email."
  }
}
variable "container_image" {
  description = "ECR URI pinned by sha256 digest; null until a tested image has been pushed."
  type        = string
  default     = null
  nullable    = true
  validation {
    condition     = var.container_image == null ? true : can(regex("^[0-9]{12}\\.dkr\\.ecr\\.[a-z0-9-]+\\.amazonaws\\.com/[^@]+@sha256:[a-f0-9]{64}$", var.container_image))
    error_message = "Use an ECR image pinned by sha256 digest."
  }
}
variable "api_desired_count" {
  type    = number
  default = 0
  validation {
    condition     = contains([0, 1], var.api_desired_count)
    error_message = "This pilot supports zero or one API task."
  }
  validation {
    condition     = var.api_desired_count == 0 || var.container_image != null
    error_message = "Starting an API task requires a tested digest-pinned image."
  }
}
variable "database_instance_class" {
  type    = string
  default = "db.t4g.micro"
}
variable "database_engine_version" {
  type    = string
  default = "17"
}
variable "edge_requests_per_five_minutes" {
  type    = number
  default = 1000
  validation {
    condition     = var.edge_requests_per_five_minutes >= 100 && var.edge_requests_per_five_minutes <= 100000
    error_message = "Choose a bounded pilot rate between 100 and 100000 requests per five minutes per IP."
  }
}
