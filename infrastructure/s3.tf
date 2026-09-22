resource "aws_s3_bucket" "site" {
  bucket = var.bucket_name
  tags   = { Project = var.project_name }
}

resource "aws_s3_bucket_public_access_block" "site" {
  bucket                  = aws_s3_bucket.site.id
  block_public_acls       = true
  block_public_policy     = false # the bucket policy below grants CloudFront, not the public
  ignore_public_acls      = true
  restrict_public_buckets = false
}

resource "aws_s3_bucket_versioning" "site" {
  bucket = aws_s3_bucket.site.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_cloudfront_origin_access_control" "site" {
  name                              = "${var.project_name}-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# Bucket contents are readable only through CloudFront. Everything except the
# handful of public login assets is further restricted at the CloudFront
# behaviour level by signed cookies. "data/items/*" has no CloudFront
# behaviour at all -- only items-api touches it.
resource "aws_s3_bucket_policy" "site" {
  bucket = aws_s3_bucket.site.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowCloudFrontServicePrincipal"
      Effect    = "Allow"
      Principal = { Service = "cloudfront.amazonaws.com" }
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.site.arn}/*"
      Condition = {
        StringEquals = {
          "AWS:SourceArn" = aws_cloudfront_distribution.site.arn
        }
      }
    }]
  })
}

# The browser uploads resized JPEGs straight to S3 with presigned PUT URLs, so
# S3 itself has to accept a cross-origin PUT from the site.
resource "aws_s3_bucket_cors_configuration" "site" {
  bucket = aws_s3_bucket.site.id

  cors_rule {
    allowed_methods = ["PUT"]
    allowed_origins = ["https://${var.domain_name}"]
    allowed_headers = ["*"]
    expose_headers  = ["ETag"]
    max_age_seconds = 3000
  }
}

# Created only if absent; item_sync.py and items-api own the contents from
# then on.
resource "aws_s3_object" "manifest_bootstrap" {
  bucket = aws_s3_bucket.site.id
  key    = "data/manifest.json"
  content = jsonencode({
    generated = "1970-01-01T00:00:00Z"
    items     = []
  })
  content_type  = "application/json"
  cache_control = "no-cache"

  lifecycle {
    ignore_changes = [content, content_type, cache_control, etag]
  }
}
