# Deployment-specific values have NO default: an incomplete config fails
# before anything is created. They come from .env via scripts/tf.py, which
# exports them as TF_VAR_*.
#
# Non-identifying values keep their defaults here. There is no
# terraform.tfvars -- terraform would load it automatically and it would
# override what tf.py passes from .env, so tf.py refuses to run while one
# exists.

# ---------------------------------------------------------------- required

variable "bucket_name" {
  description = "S3 bucket to create. Globally unique across all of AWS. .env: S3_BUCKET"
  type        = string
}

variable "domain_name" {
  description = "Domain the site is served on, e.g. mementos.example.com. .env: DOMAIN_NAME"
  type        = string
}

variable "aws_profile" {
  description = "AWS CLI profile to deploy with. .env: AWS_PROFILE"
  type        = string
}

variable "site_password" {
  description = "The shared password for the gate. .env: SITE_PASSWORD"
  type        = string
  sensitive   = true
}

# ---------------------------------------------------------------- defaulted

variable "aws_region" {
  description = "Region for S3 and the Lambdas. Must support Lambda function URLs -- ap-southeast-6 does not. .env: AWS_REGION"
  type        = string
  default     = "ap-southeast-2"
}

variable "project_name" {
  description = "Prefix for the resources this creates, and the Project tag. .env: PROJECT_NAME"
  type        = string
  default     = "mementos"
}

variable "session_hours" {
  description = "How long a login lasts before the gate asks again. .env: SESSION_HOURS"
  type        = number
  default     = 720 # 30 days
}
