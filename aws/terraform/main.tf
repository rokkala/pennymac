terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.70"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
  # backend "s3" {
  #   bucket         = "pennymac-tfstate"
  #   key            = "loan-boarding/terraform.tfstate"
  #   region         = "us-west-2"
  #   dynamodb_table = "pennymac-tf-locks"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Application = "loan-boarding-platform"
      Environment = var.env
      Owner       = "loan-boarding"
      DataClass   = "confidential-npi"
      ManagedBy   = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}
data "aws_availability_zones" "available" {
  #checkov:skip=CKV_AWS_394:Only the first two AZs are used (slice in locals); new AZs do not change the result
  state = "available"
}

locals {
  name         = "lbp-${var.env}"
  account_id   = data.aws_caller_identity.current.account_id
  azs          = slice(data.aws_availability_zones.available.names, 0, 2)
  db_sqlserver = startswith(var.db_engine, "sqlserver")
  db_port      = local.db_sqlserver ? 1433 : 5432
  db_driver    = local.db_sqlserver ? "mssql+pyodbc" : "postgresql+psycopg"
  common_env = {
    LBP_ENV                  = "aws"
    LBP_AI_PROVIDER          = var.ai_provider
    LBP_BEDROCK_MODEL_ID     = var.bedrock_model_id
    LBP_RAW_BUCKET           = aws_s3_bucket.zone["raw"].bucket
    LBP_PROCESSED_BUCKET     = aws_s3_bucket.zone["processed"].bucket
    LBP_RULES_TABLE          = aws_dynamodb_table.rules.name
    LBP_POLICY_TABLE         = aws_dynamodb_table.policy.name
    LBP_MICRO_BATCH_SIZE     = tostring(var.micro_batch_size)
    LBP_SSE_THROTTLE_RPS     = tostring(var.sse_throttle_rps)
    LBP_DB_SECRET_ARN        = local.db_secret_arn
    LBP_DB_HOST              = aws_db_instance.main.address
    LBP_DB_NAME              = "lbp"
    LBP_DB_DRIVER            = local.db_driver
    LBP_AUTH_MODE            = "jwt"
    LBP_ENABLE_DEMO          = "false"
    LBP_AUTO_CREATE_SCHEMA   = "false"
    LBP_CORS_ORIGINS         = "" # same-origin via CloudFront; no CORS
    LBP_COGNITO_REGION       = var.region
    LBP_COGNITO_USER_POOL_ID = aws_cognito_user_pool.main.id
    LBP_SSM_PREFIX           = "/${local.name}/app/" # client id + domain (avoids a Lambda <-> CloudFront dependency cycle)
    # vendor delivery scheduler: EventBridge Scheduler drives the tick (not the workers)
    LBP_SCHEDULER_ENABLED    = "false"
    LBP_ALERT_TOPIC_ARN      = aws_sns_topic.alerts.arn
    LBP_PULL_ALLOWED_HOSTS   = join(",", concat(var.vendor_sftp_hosts, [for b in var.vendor_pull_buckets : "s3:${b}"]))
    LBP_VENDOR_SECRET_PREFIX = "${local.name}/vendors/"
  }
}
