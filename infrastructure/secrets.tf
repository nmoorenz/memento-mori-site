# Key pair CloudFront uses to check the signed cookies the gate Lambda issues.
resource "tls_private_key" "cookie_signing" {
  algorithm = "RSA"
  rsa_bits  = 2048
}

resource "aws_cloudfront_public_key" "cookie_signing" {
  name        = "${var.project_name}-cookie-key"
  comment     = "Verifies signed cookies issued by the gate Lambda"
  encoded_key = tls_private_key.cookie_signing.public_key_pem
}

resource "aws_cloudfront_key_group" "cookie_signing" {
  name    = "${var.project_name}-cookie-key-group"
  comment = "Trusted key group for the gated part of the site"
  items   = [aws_cloudfront_public_key.cookie_signing.id]
}

# Shared secret between CloudFront and the two functions, so the function URLs
# are not usable by anyone who finds them directly.
resource "random_password" "origin_verify" {
  length  = 32
  special = false
}

# Signs the short session cookie items-api checks on every write.
resource "random_password" "session_secret" {
  length  = 48
  special = false
}

resource "aws_ssm_parameter" "cookie_signing_private_key" {
  name  = "/${var.project_name}/cloudfront-private-key"
  type  = "SecureString"
  value = tls_private_key.cookie_signing.private_key_pem
  tags  = { Project = var.project_name }
}

# The shared password itself. Change it by changing var.site_password and
# re-applying -- no redeploy of the Lambda is needed, it reads this at call
# time (cached for the life of the execution environment).
resource "aws_ssm_parameter" "site_password" {
  name  = "/${var.project_name}/site-password"
  type  = "SecureString"
  value = var.site_password
  tags  = { Project = var.project_name }
}

resource "aws_ssm_parameter" "session_secret" {
  name  = "/${var.project_name}/session-secret"
  type  = "SecureString"
  value = random_password.session_secret.result
  tags  = { Project = var.project_name }
}
