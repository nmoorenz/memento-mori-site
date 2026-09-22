# DNS records are added by hand at the registrar. This creates and validates
# the certificate only; the validation CNAME and the domain's own CNAME are
# yours to add. See README for the two-step apply.
resource "aws_acm_certificate" "site" {
  provider          = aws.us_east_1
  domain_name       = var.domain_name
  validation_method = "DNS"
  tags              = { Project = var.project_name }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_acm_certificate_validation" "site" {
  provider                = aws.us_east_1
  certificate_arn         = aws_acm_certificate.site.arn
  validation_record_fqdns = [for r in aws_acm_certificate.site.domain_validation_options : r.resource_record_name]
}
