locals {
  s3_site_origin_id = "s3-site"
  s3_data_origin_id = "s3-data"
  gate_origin_id    = "gate-lambda"
  api_origin_id     = "items-api-lambda"

  # AWS managed policies (stable IDs).
  cache_policy_optimized    = "658327ea-f89d-4fab-a63d-7e88639e58f6" # CachingOptimized
  cache_policy_disabled     = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" # CachingDisabled
  origin_request_policy_all = "b689b0a8-53d0-40ab-baf2-68738e2966ac" # AllViewerExceptHostHeader
}

resource "aws_cloudfront_distribution" "site" {
  enabled             = true
  is_ipv6_enabled     = true
  default_root_object = "index.html"
  aliases             = [var.domain_name]
  price_class         = "PriceClass_100"

  origin {
    domain_name              = aws_s3_bucket.site.bucket_regional_domain_name
    origin_id                = local.s3_site_origin_id
    origin_path              = "/site"
    origin_access_control_id = aws_cloudfront_origin_access_control.site.id
  }

  origin {
    domain_name              = aws_s3_bucket.site.bucket_regional_domain_name
    origin_id                = local.s3_data_origin_id
    origin_access_control_id = aws_cloudfront_origin_access_control.site.id
  }

  origin {
    domain_name = trimsuffix(trimprefix(aws_lambda_function_url.gate.function_url, "https://"), "/")
    origin_id   = local.gate_origin_id
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
    custom_header {
      name  = "X-Origin-Verify"
      value = random_password.origin_verify.result
    }
  }

  origin {
    domain_name = trimsuffix(trimprefix(aws_lambda_function_url.items_api.function_url, "https://"), "/")
    origin_id   = local.api_origin_id
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
    custom_header {
      name  = "X-Origin-Verify"
      value = random_password.origin_verify.result
    }
  }

  # Everything not matched below needs the signed cookies the gate issues.
  default_cache_behavior {
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = local.s3_site_origin_id
    viewer_protocol_policy = "redirect-to-https"
    cache_policy_id        = local.cache_policy_optimized
    compress               = true
    trusted_key_groups     = [aws_cloudfront_key_group.cookie_signing.id]
  }

  # The two public assets: the password page itself, and the stylesheet it
  # uses. A viewer with no cookies is bounced here by custom_error_response,
  # so this behaviour must NOT require them.
  ordered_cache_behavior {
    path_pattern           = "/login.html"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = local.s3_site_origin_id
    viewer_protocol_policy = "redirect-to-https"
    cache_policy_id        = local.cache_policy_optimized
    compress               = true
  }

  ordered_cache_behavior {
    path_pattern           = "/style.css"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = local.s3_site_origin_id
    viewer_protocol_policy = "redirect-to-https"
    cache_policy_id        = local.cache_policy_optimized
    compress               = true
  }

  ordered_cache_behavior {
    path_pattern           = "/images/*"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = local.s3_data_origin_id
    viewer_protocol_policy = "redirect-to-https"
    cache_policy_id        = local.cache_policy_optimized
    compress               = true
    trusted_key_groups     = [aws_cloudfront_key_group.cookie_signing.id]
  }

  ordered_cache_behavior {
    path_pattern           = "/data/*"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = local.s3_data_origin_id
    viewer_protocol_policy = "redirect-to-https"
    cache_policy_id        = local.cache_policy_disabled
    trusted_key_groups     = [aws_cloudfront_key_group.cookie_signing.id]
  }

  ordered_cache_behavior {
    path_pattern             = "/auth/*"
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    target_origin_id         = local.gate_origin_id
    viewer_protocol_policy   = "https-only"
    cache_policy_id          = local.cache_policy_disabled
    origin_request_policy_id = local.origin_request_policy_all
  }

  # Item routes. Every request is a distinct action, so nothing is cached, and
  # the AllViewer origin request policy forwards the Cookie header that
  # items-api checks.
  ordered_cache_behavior {
    path_pattern             = "/api/*"
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    target_origin_id         = local.api_origin_id
    viewer_protocol_policy   = "https-only"
    cache_policy_id          = local.cache_policy_disabled
    origin_request_policy_id = local.origin_request_policy_all
  }

  # A viewer with no valid signed cookies gets a 403; serve the password page
  # instead of a raw AWS error.
  custom_error_response {
    error_code            = 403
    response_code         = 403
    response_page_path    = "/login.html"
    error_caching_min_ttl = 0
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate_validation.site.certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }

  tags = { Project = var.project_name }
}
