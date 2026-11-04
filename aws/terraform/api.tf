# ---------------- Cognito: RBAC + SSO
resource "aws_cognito_user_pool" "main" {
  name                     = local.name
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]
  mfa_configuration        = "ON"
  software_token_mfa_configuration { enabled = true }
  password_policy {
    minimum_length    = 14
    require_lowercase = true
    require_uppercase = true
    require_numbers   = true
    require_symbols   = true
  }
  admin_create_user_config { allow_admin_create_user_only = true }
  user_pool_add_ons { advanced_security_mode = "ENFORCED" }
}

resource "aws_cognito_user_group" "roles" {
  for_each = {
    analyst    = "Data analyst: onboards sources, prepares mappings"
    sme        = "Subject-matter expert: approves mappings, authors rules"
    ops        = "Loan boarding operations: uploads files, monitors batches"
    reviewer   = "Exception reviewer (T2/T3, T4 maker)"
    checker    = "Exception checker (T4 second pair of eyes)"
    compliance = "Compliance: T5 blocks, regulatory rule and policy approvals, PII view"
    admin      = "Platform administrator"
  }
  name         = each.key
  description  = each.value
  user_pool_id = aws_cognito_user_pool.main.id
}

resource "aws_cognito_identity_provider" "saml" {
  count         = var.saml_metadata_url == "" ? 0 : 1
  user_pool_id  = aws_cognito_user_pool.main.id
  provider_name = "CorporateSSO"
  provider_type = "SAML"
  provider_details = {
    MetadataURL = var.saml_metadata_url
  }
  attribute_mapping = {
    email = "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress"
  }
}

resource "aws_cognito_user_pool_domain" "main" {
  domain       = "${local.name}-${local.account_id}"
  user_pool_id = aws_cognito_user_pool.main.id
}

resource "aws_cognito_user_pool_client" "web" {
  name                                 = "${local.name}-web"
  user_pool_id                         = aws_cognito_user_pool.main.id
  generate_secret                      = false
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  callback_urls                        = ["https://${aws_cloudfront_distribution.web.domain_name}/auth/callback"]
  logout_urls                          = ["https://${aws_cloudfront_distribution.web.domain_name}/"]
  supported_identity_providers         = concat(["COGNITO"], var.saml_metadata_url == "" ? [] : ["CorporateSSO"])
  access_token_validity                = 60
  id_token_validity                    = 60
  refresh_token_validity               = 8
  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "hours"
  }
  prevent_user_existence_errors = "ENABLED"
}

# ---------------- API Gateway (HTTP API) + JWT authorizer
# No CORS: the browser reaches the API same-origin through CloudFront (/api/*)
resource "aws_apigatewayv2_api" "main" {
  name          = local.name
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_authorizer" "cognito" {
  api_id           = aws_apigatewayv2_api.main.id
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]
  name             = "cognito"
  jwt_configuration {
    audience = [aws_cognito_user_pool_client.web.id]
    issuer   = "https://cognito-idp.${var.region}.amazonaws.com/${aws_cognito_user_pool.main.id}"
  }
}

# The whole control-plane API runs on Lambda (FastAPI via Mangum). Loan data never flows through it.
resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.fn["api"].invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "api" {
  api_id             = aws_apigatewayv2_api.main.id
  route_key          = "ANY /api/{proxy+}"
  target             = "integrations/${aws_apigatewayv2_integration.lambda.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito.id
}

# Needed before sign-in (the web app reads its Cognito settings here) and by health checks; no data
resource "aws_apigatewayv2_route" "public" {
  #checkov:skip=CKV_AWS_309:Intentionally public, read-only endpoints with no data (web sign-in settings, liveness)
  for_each  = toset(["GET /api/config", "GET /api/health", "GET /api/ready"])
  api_id    = aws_apigatewayv2_api.main.id
  route_key = each.value
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/apigateway/${local.name}"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.data.arn
}

resource "aws_apigatewayv2_stage" "main" {
  api_id      = aws_apigatewayv2_api.main.id
  name        = "$default"
  auto_deploy = true
  default_route_settings {
    throttling_burst_limit = 500
    throttling_rate_limit  = 200
  }
  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api.arn
    format = jsonencode({
      requestId = "$context.requestId", user = "$context.authorizer.claims.email", route = "$context.routeKey",
      status    = "$context.status", latency = "$context.integrationLatency", ip = "$context.identity.sourceIp"
    })
  }
}

resource "aws_lambda_permission" "apigw" {
  statement_id  = "AllowApiGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fn["api"].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}

resource "aws_wafv2_web_acl" "web" {
  provider = aws.us_east_1
  name     = "${local.name}-web"
  scope    = "CLOUDFRONT"
  default_action {
    allow {}
  }
  rule {
    name     = "known-bad-inputs" # includes Log4j (CVE-2021-44228) signatures
    priority = 0
    override_action {
      none {}
    }
    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
        vendor_name = "AWS"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "bad-inputs"
      sampled_requests_enabled   = true
    }
  }
  rule {
    name     = "ip-reputation"
    priority = 2
    override_action {
      none {}
    }
    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesAmazonIpReputationList"
        vendor_name = "AWS"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "ip-reputation"
      sampled_requests_enabled   = true
    }
  }
  rule {
    name     = "rate-limit"
    priority = 3
    action {
      block {}
    }
    statement {
      rate_based_statement {
        limit              = 2000
        aggregate_key_type = "IP"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "rate-limit"
      sampled_requests_enabled   = true
    }
  }
  rule {
    name     = "aws-common"
    priority = 1
    override_action {
      none {}
    }
    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "common"
      sampled_requests_enabled   = true
    }
  }
  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${local.name}-web"
    sampled_requests_enabled   = true
  }
}

provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
}

resource "aws_kms_key" "waf_logs" {
  provider                = aws.us_east_1
  description             = "${local.name} WAF log encryption (us-east-1)"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Sid = "Root", Effect = "Allow", Principal = { AWS = "arn:aws:iam::${local.account_id}:root" }, Action = "kms:*", Resource = "*" },
      { Sid = "Logs", Effect = "Allow", Principal = { Service = "logs.us-east-1.amazonaws.com" },
      Action = ["kms:Encrypt*", "kms:Decrypt*", "kms:GenerateDataKey*", "kms:Describe*"], Resource = "*" }
    ]
  })
}

resource "aws_cloudwatch_log_group" "waf" {
  provider          = aws.us_east_1
  name              = "aws-waf-logs-${local.name}"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.waf_logs.arn
}

resource "aws_wafv2_web_acl_logging_configuration" "web" {
  provider                = aws.us_east_1
  log_destination_configs = [aws_cloudwatch_log_group.waf.arn]
  resource_arn            = aws_wafv2_web_acl.web.arn
  redacted_fields {
    single_header { name = "authorization" }
  }
}

# Settings the API reads at start-up (avoids a Lambda <-> CloudFront <-> Cognito dependency cycle)
resource "aws_ssm_parameter" "cognito_client_id" {
  #checkov:skip=CKV2_AWS_34:Public OAuth client id (no secret); SecureString adds nothing
  name  = "/${local.name}/app/cognito_client_id"
  type  = "String"
  value = aws_cognito_user_pool_client.web.id
}

resource "aws_ssm_parameter" "cognito_domain" {
  #checkov:skip=CKV2_AWS_34:Public hostname (no secret)
  name  = "/${local.name}/app/cognito_domain"
  type  = "String"
  value = "${aws_cognito_user_pool_domain.main.domain}.auth.${var.region}.amazoncognito.com"
}
