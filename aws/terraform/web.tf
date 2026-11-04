# ---------------- React app: S3 + CloudFront (OAC), /api/* routed to API Gateway
resource "aws_s3_bucket" "web" {
  #checkov:skip=CKV_AWS_145:Static web assets only (no data); SSE-S3 keeps CloudFront OAC simple
  #checkov:skip=CKV_AWS_144:Rebuilt from CI on demand; no replication needed
  #checkov:skip=CKV_AWS_18:Static assets; requests are logged at WAF/CloudFront
  #checkov:skip=CKV2_AWS_62:No event processing for static assets
  bucket        = "${local.name}-web-${local.account_id}"
  force_destroy = true
}

resource "aws_s3_bucket_lifecycle_configuration" "web" {
  bucket = aws_s3_bucket.web.id
  rule {
    id     = "old-builds"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration { noncurrent_days = 30 }
    abort_incomplete_multipart_upload { days_after_initiation = 1 }
  }
}

resource "aws_s3_bucket_versioning" "web" {
  bucket = aws_s3_bucket.web.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_public_access_block" "web" {
  bucket                  = aws_s3_bucket.web.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_cloudfront_origin_access_control" "web" {
  name                              = "${local.name}-web"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_response_headers_policy" "security" {
  name = "${local.name}-security"
  security_headers_config {
    strict_transport_security {
      access_control_max_age_sec = 63072000
      include_subdomains         = true
      preload                    = true
      override                   = true
    }
    content_type_options { override = true }
    frame_options {
      frame_option = "SAMEORIGIN"
      override     = true
    }
    referrer_policy {
      referrer_policy = "strict-origin-when-cross-origin"
      override        = true
    }
  }
}

resource "aws_cloudfront_distribution" "web" {
  #checkov:skip=CKV_AWS_310:Single-region deployment; DR is a separate stack (see docs/PRODUCTION_READINESS.md)
  #checkov:skip=CKV_AWS_86:Standard logging needs ACL-enabled buckets; WAF logs + API Gateway access logs cover requests
  #checkov:skip=CKV2_AWS_42:Custom certificate via var.web_certificate_arn; enforced for prod by the precondition below
  #checkov:skip=CKV_AWS_174:TLSv1.2_2021 applies when the custom certificate is set (required for prod)
  #checkov:skip=CKV2_AWS_47:The attached web ACL includes AWSManagedRulesKnownBadInputsRuleSet (Log4j)
  enabled             = true
  aliases             = var.web_domain == "" ? [] : [var.web_domain]
  default_root_object = "index.html"
  price_class         = "PriceClass_100"
  web_acl_id          = aws_wafv2_web_acl.web.arn

  origin {
    origin_id                = "web"
    domain_name              = aws_s3_bucket.web.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.web.id
  }

  origin {
    origin_id   = "api"
    domain_name = replace(aws_apigatewayv2_api.main.api_endpoint, "https://", "")
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  default_cache_behavior {
    target_origin_id           = "web"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD", "OPTIONS"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = "658327ea-f89d-4fab-a63d-7e88639e58f6" # Managed-CachingOptimized
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id
    compress                   = true
  }

  ordered_cache_behavior {
    path_pattern             = "/api/*"
    target_origin_id         = "api"
    viewer_protocol_policy   = "https-only"
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    cache_policy_id          = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" # Managed-CachingDisabled
    origin_request_policy_id = "b689b0a8-53d0-40ab-baf2-68738e2966ac" # Managed-AllViewerExceptHostHeader
  }

  custom_error_response {
    error_code         = 403
    response_code      = 200
    response_page_path = "/index.html"
  }

  restrictions {
    geo_restriction {
      restriction_type = "whitelist"
      locations        = var.allowed_countries
    }
  }

  lifecycle {
    precondition {
      condition     = var.env != "prod" || var.web_certificate_arn != ""
      error_message = "prod requires web_certificate_arn (custom domain, TLS 1.2+)."
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = var.web_certificate_arn == ""
    acm_certificate_arn            = var.web_certificate_arn == "" ? null : var.web_certificate_arn
    ssl_support_method             = var.web_certificate_arn == "" ? null : "sni-only"
    minimum_protocol_version       = var.web_certificate_arn == "" ? "TLSv1" : "TLSv1.2_2021"
  }
}

resource "aws_s3_bucket_policy" "web" {
  bucket = aws_s3_bucket.web.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "cloudfront.amazonaws.com" }
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.web.arn}/*"
      Condition = { StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.web.arn } }
    }]
  })
}
