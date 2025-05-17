variable "key_name" {
  description = "SSH key name to use for the instance"
  type        = string
  default     = "aws-key-pair"
}

variable "ssh_private_key_path" {
  description = "Path to your OpenSSH-format private key (PEM)"
  type        = string
  default     = "C:/Users/vijha/.ssh/aws-key-pair.pem"
}

variable "spot_price" {
  description = "Maximum spot price (in USD) you're willing to pay"
  type        = string
  default     = "0.252"
}


variable "repo_url" {
  description = "HTTPS URL (with or without embedded token) for the Git repo to deploy"
  type        = string
  sensitive   = true
}
