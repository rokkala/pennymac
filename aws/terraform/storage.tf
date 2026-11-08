locals {
  zones = {
    raw       = "Landing zone for source files"
    processed = "Chunks processed Parquet and analytics extracts"
    athena    = "Athena query results"
    audit     = "CloudTrail and access logs"
  }
}

resource "aws_s3_bucket" "zone" {
  #checkov:skip=CKV2_AWS_6:Public access block applied per bucket by aws_s3_bucket_public_access_block.zone (for_each)
  #checkov:skip=CKV_AWS_21:Versioning enabled per bucket by aws_s3_bucket_versioning.zone (for_each)
  #checkov:skip=CKV_AWS_18:Access logging by aws_s3_bucket_logging.zone (for_each); the audit bucket is the log target itself
  #checkov:skip=CKV_AWS_145:Data zones use SSE-KMS (for_each config); the audit bucket must use SSE-S3 because ELB and S3 access-log delivery do not support KMS
  #checkov:skip=CKV_AWS_144:Cross-region replication belongs to the DR stack (docs/PRODUCTION_READINESS.md)
  #checkov:skip=CKV2_AWS_62:Only the raw zone triggers processing (EventBridge notifications enabled there)
  for_each      = local.zones
  bucket        = "${local.name}-${each.key}-${local.account_id}"
  force_destroy = var.env != "prod"
  tags          = { Zone = each.key, Purpose = each.value }
}

resource "aws_s3_bucket_public_access_block" "zone" {
  for_each                = aws_s3_bucket.zone
  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "zone" {
  for_each = aws_s3_bucket.zone
  bucket   = each.value.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "zone" {
  for_each = { for k, v in aws_s3_bucket.zone : k => v if k != "audit" }
  bucket   = each.value.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.data.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "processed" {
  bucket = aws_s3_bucket.zone["processed"].id
  rule {
    id     = "expire-chunks"
    status = "Enabled"
    filter { prefix = "chunks/" }
    expiration { days = 14 }
    abort_incomplete_multipart_upload { days_after_initiation = 2 }
  }
  rule {
    id     = "expire-bulk-load"
    status = "Enabled"
    filter { prefix = "bulk-load/" }
    expiration { days = 14 }
    abort_incomplete_multipart_upload { days_after_initiation = 2 }
  }
  rule {
    id     = "tier-processed"
    status = "Enabled"
    filter { prefix = "processed/" }
    transition {
      days          = 90
      storage_class = "STANDARD_IA"
    }
    abort_incomplete_multipart_upload { days_after_initiation = 2 }
  }
  rule {
    id     = "abort-incomplete-uploads"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload { days_after_initiation = 2 }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "raw" {
  bucket = aws_s3_bucket.zone["raw"].id
  rule {
    id     = "retain-raw-7y"
    status = "Enabled"
    filter {}
    transition {
      days          = 30
      storage_class = "GLACIER_IR"
    }
    expiration { days = 2555 }
    abort_incomplete_multipart_upload { days_after_initiation = 2 }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "athena" {
  bucket = aws_s3_bucket.zone["athena"].id
  rule {
    id     = "expire-query-results"
    status = "Enabled"
    filter {}
    expiration { days = 30 }
    abort_incomplete_multipart_upload { days_after_initiation = 1 }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "audit" {
  bucket = aws_s3_bucket.zone["audit"].id
  rule {
    id     = "retain-7y"
    status = "Enabled"
    filter {}
    transition {
      days          = 90
      storage_class = "GLACIER"
    }
    expiration { days = 2555 }
    abort_incomplete_multipart_upload { days_after_initiation = 1 }
  }
}

# Object Lock on the audit zone would make logs WORM; it must be set at bucket creation.
# Server access logs for the data zones land in the audit bucket.
resource "aws_s3_bucket_logging" "zone" {
  for_each      = { for k, v in aws_s3_bucket.zone : k => v if k != "audit" }
  bucket        = each.value.id
  target_bucket = aws_s3_bucket.zone["audit"].id
  target_prefix = "s3-access/${each.key}/"
}

resource "aws_s3_bucket_cors_configuration" "raw" {
  bucket = aws_s3_bucket.zone["raw"].id
  cors_rule {
    allowed_methods = ["PUT"]
    allowed_origins = ["https://${aws_cloudfront_distribution.web.domain_name}"]
    allowed_headers = ["*"]
    max_age_seconds = 3000
  }
}

resource "aws_s3_bucket_notification" "raw" {
  bucket      = aws_s3_bucket.zone["raw"].id
  eventbridge = true
}

resource "aws_s3_bucket_policy" "audit" {
  bucket = aws_s3_bucket.zone["audit"].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "CloudTrailAclCheck"
        Effect    = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action    = "s3:GetBucketAcl"
        Resource  = aws_s3_bucket.zone["audit"].arn
      },
      {
        Sid       = "S3ServerAccessLogs"
        Effect    = "Allow"
        Principal = { Service = "logging.s3.amazonaws.com" }
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.zone["audit"].arn}/s3-access/*"
        Condition = { StringEquals = { "aws:SourceAccount" = local.account_id } }
      },
      {
        Sid       = "AlbAccessLogs"
        Effect    = "Allow"
        Principal = { Service = "logdelivery.elasticloadbalancing.amazonaws.com" }
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.zone["audit"].arn}/alb/*"
      },
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource  = [aws_s3_bucket.zone["audit"].arn, "${aws_s3_bucket.zone["audit"].arn}/*"]
        Condition = { Bool = { "aws:SecureTransport" = "false" } }
      },
      {
        Sid       = "CloudTrailWrite"
        Effect    = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.zone["audit"].arn}/AWSLogs/${local.account_id}/*"
        Condition = { StringEquals = { "s3:x-amz-acl" = "bucket-owner-full-control" } }
      }
    ]
  })
}

# ---------------- DynamoDB: Rule Registry + Policy Store
resource "aws_dynamodb_table" "rules" {
  name         = "${local.name}-rule-registry"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "rule_id"
  range_key    = "version"

  attribute {
    name = "rule_id"
    type = "S"
  }
  attribute {
    name = "version"
    type = "N"
  }
  attribute {
    name = "status"
    type = "S"
  }

  global_secondary_index {
    name            = "status-index"
    hash_key        = "status"
    range_key       = "rule_id"
    projection_type = "ALL"
  }

  point_in_time_recovery { enabled = true }
  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.data.arn
  }
  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"
}

resource "aws_dynamodb_table" "policy" {
  name         = "${local.name}-policy-store"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "key"

  attribute {
    name = "key"
    type = "S"
  }

  point_in_time_recovery { enabled = true }
  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.data.arn
  }
}

# ---------------- RDS: platform tables + SSE staging
resource "aws_db_instance" "main" {
  identifier                      = local.name
  engine                          = var.db_engine
  engine_version                  = var.db_engine_version != "" ? var.db_engine_version : null
  license_model                   = local.db_sqlserver ? "license-included" : null
  instance_class                  = var.db_instance_class
  allocated_storage               = var.db_allocated_storage
  max_allocated_storage           = var.db_max_allocated_storage
  storage_type                    = "gp3"
  storage_encrypted               = true
  kms_key_id                      = aws_kms_key.data.arn
  username                        = "lbpadmin"
  port                            = local.db_port
  manage_master_user_password     = true
  master_user_secret_kms_key_id   = aws_kms_key.data.arn
  db_subnet_group_name            = module.vpc.database_subnet_group_name
  vpc_security_group_ids          = [aws_security_group.db.id]
  multi_az                        = var.env == "prod"
  backup_retention_period         = 14
  deletion_protection             = var.env == "prod"
  skip_final_snapshot             = var.env != "prod"
  performance_insights_enabled    = true
  performance_insights_kms_key_id = aws_kms_key.data.arn
  copy_tags_to_snapshot           = true
  enabled_cloudwatch_logs_exports = local.db_sqlserver ? ["error", "agent"] : ["postgresql", "upgrade"]
  monitoring_interval             = 60
  monitoring_role_arn             = aws_iam_role.rds_monitoring.arn
  auto_minor_version_upgrade      = true
}

resource "aws_iam_role" "rds_monitoring" {
  name = "${local.name}-rds-monitoring"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "monitoring.rds.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy_attachment" "rds_monitoring" {
  role       = aws_iam_role.rds_monitoring.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
}

# RDS aws_s3.table_import_from_s3 — DB pulls CSV/text from processed bucket
resource "aws_iam_role" "rds_s3_import" {
  name = "${local.name}-rds-s3-import"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "rds.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "rds_s3_import" {
  name = "s3-import"
  role = aws_iam_role.rds_s3_import.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:ListBucket"]
        Resource = [aws_s3_bucket.zone["processed"].arn, "${aws_s3_bucket.zone["processed"].arn}/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt", "kms:DescribeKey"]
        Resource = [aws_kms_key.data.arn]
      },
    ]
  })
}

resource "aws_db_instance_role_association" "s3_import" {
  db_instance_identifier = aws_db_instance.main.identifier
  feature_name           = "s3Import"
  role_arn               = aws_iam_role.rds_s3_import.arn
}

# ---------------- OpenSearch Serverless: k-NN precedent index (exception RAG)
resource "aws_opensearchserverless_security_policy" "enc" {
  name = "${local.name}-prec-enc"
  type = "encryption"
  policy = jsonencode({
    Rules       = [{ ResourceType = "collection", Resource = ["collection/${local.name}-precedents"] }]
    AWSOwnedKey = false
    KmsARN      = aws_kms_key.data.arn
  })
}

resource "aws_opensearchserverless_security_policy" "net" {
  name = "${local.name}-prec-net"
  type = "network"
  policy = jsonencode([{
    Rules           = [{ ResourceType = "collection", Resource = ["collection/${local.name}-precedents"] }]
    AllowFromPublic = false
    SourceVPCEs     = [aws_opensearchserverless_vpc_endpoint.main.id]
  }])
}

resource "aws_opensearchserverless_vpc_endpoint" "main" {
  name               = "${local.name}-aoss"
  vpc_id             = module.vpc.vpc_id
  subnet_ids         = module.vpc.private_subnets
  security_group_ids = [aws_security_group.app.id]
}

resource "aws_opensearchserverless_collection" "precedents" {
  name       = "${local.name}-precedents"
  type       = "VECTORSEARCH"
  depends_on = [aws_opensearchserverless_security_policy.enc, aws_opensearchserverless_security_policy.net]
}

resource "aws_opensearchserverless_access_policy" "precedents" {
  name = "${local.name}-prec-access"
  type = "data"
  policy = jsonencode([{
    Rules = [
      { ResourceType = "index", Resource = ["index/${local.name}-precedents/*"], Permission = ["aoss:*"] },
      { ResourceType = "collection", Resource = ["collection/${local.name}-precedents"], Permission = ["aoss:*"] }
    ]
    Principal = [aws_iam_role.glue.arn, aws_iam_role.lambda.arn]
  }])
}

resource "aws_s3_bucket_policy" "tls_only" {
  for_each = { for k, v in aws_s3_bucket.zone : k => v if k != "audit" }
  bucket   = each.value.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [each.value.arn, "${each.value.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}
