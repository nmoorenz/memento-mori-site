# Zips what scripts/build_lambdas.py assembled -- handler plus its installed
# dependencies. Run that script before apply.

# ---------------------------------------------------------------------------
# gate -- the password page's backend. Checks the shared password and issues
# the CloudFront signed cookies that unlock the whole site.
# ---------------------------------------------------------------------------

data "archive_file" "gate" {
  type        = "zip"
  source_dir  = "${path.module}/build/gate"
  output_path = "${path.module}/dist/gate.zip"
}

resource "aws_iam_role" "gate" {
  name = "${var.project_name}-gate"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "gate_logs" {
  role       = aws_iam_role.gate.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "gate_ssm" {
  name = "${var.project_name}-gate-ssm"
  role = aws_iam_role.gate.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = "ssm:GetParameter"
      Resource = [
        aws_ssm_parameter.cookie_signing_private_key.arn,
        aws_ssm_parameter.site_password.arn,
        aws_ssm_parameter.session_secret.arn,
      ]
    }]
  })
}

resource "aws_lambda_function" "gate" {
  function_name    = "${var.project_name}-gate"
  role             = aws_iam_role.gate.arn
  handler          = "handler.handler"
  runtime          = "python3.12"
  timeout          = 10
  filename         = data.archive_file.gate.output_path
  source_code_hash = data.archive_file.gate.output_base64sha256

  environment {
    variables = {
      COOKIE_DOMAIN            = var.domain_name
      COOKIE_RESOURCE          = "https://${var.domain_name}/*"
      SESSION_HOURS            = tostring(var.session_hours)
      CLOUDFRONT_KEY_PAIR_ID   = aws_cloudfront_public_key.cookie_signing.id
      SSM_PRIVATE_KEY_PARAM    = aws_ssm_parameter.cookie_signing_private_key.name
      SSM_PASSWORD_PARAM       = aws_ssm_parameter.site_password.name
      SSM_SESSION_SECRET_PARAM = aws_ssm_parameter.session_secret.name
      ORIGIN_VERIFY_SECRET     = random_password.origin_verify.result
    }
  }

  tags = { Project = var.project_name }
}

resource "aws_lambda_function_url" "gate" {
  function_name      = aws_lambda_function.gate.function_name
  authorization_type = "NONE" # gated by the X-Origin-Verify check inside the function
}

# ---------------------------------------------------------------------------
# items-api -- the add/edit routes behind /api/*. Same CloudFront-only caller
# pattern as the gate, plus a per-request check of the session cookie the gate
# sets on login.
# ---------------------------------------------------------------------------

data "archive_file" "items_api" {
  type        = "zip"
  source_dir  = "${path.module}/build/items-api"
  output_path = "${path.module}/dist/items-api.zip"
}

resource "aws_iam_role" "items_api" {
  name = "${var.project_name}-items-api"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "items_api_logs" {
  role       = aws_iam_role.items_api.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "items_api" {
  name = "${var.project_name}-items-api"
  role = aws_iam_role.items_api.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = "${aws_s3_bucket.site.arn}/data/*"
      },
      {
        # Presigned PUT URLs are signed with this role's credentials, so the
        # role has to be allowed to do the PUT it is handing out.
        Effect   = "Allow"
        Action   = "s3:PutObject"
        Resource = "${aws_s3_bucket.site.arn}/images/*"
      },
      {
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = aws_s3_bucket.site.arn
        Condition = {
          StringLike = { "s3:prefix" = "data/*" }
        }
      },
      {
        Effect   = "Allow"
        Action   = "ssm:GetParameter"
        Resource = aws_ssm_parameter.session_secret.arn
      },
    ]
  })
}

resource "aws_lambda_function" "items_api" {
  function_name    = "${var.project_name}-items-api"
  role             = aws_iam_role.items_api.arn
  handler          = "handler.handler"
  runtime          = "python3.12"
  timeout          = 15
  filename         = data.archive_file.items_api.output_path
  source_code_hash = data.archive_file.items_api.output_base64sha256

  environment {
    variables = {
      BUCKET_NAME              = aws_s3_bucket.site.bucket
      SSM_SESSION_SECRET_PARAM = aws_ssm_parameter.session_secret.name
      ORIGIN_VERIFY_SECRET     = random_password.origin_verify.result
    }
  }

  tags = { Project = var.project_name }
}

resource "aws_lambda_function_url" "items_api" {
  function_name      = aws_lambda_function.items_api.function_name
  authorization_type = "NONE" # gated by the X-Origin-Verify check inside the function
}
