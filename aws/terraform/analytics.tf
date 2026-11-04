# ---------------- Pillar 2: Athena + Redshift Serverless (+ QuickSight, see docs/analytics.md)
resource "aws_athena_workgroup" "lbp" {
  name = local.name
  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true
    bytes_scanned_cutoff_per_query     = 10737418240
    result_configuration {
      output_location = "s3://${aws_s3_bucket.zone["athena"].bucket}/results/"
      encryption_configuration {
        encryption_option = "SSE_KMS"
        kms_key_arn       = aws_kms_key.data.arn
      }
    }
  }
}

resource "aws_athena_named_query" "exception_trend" {
  name      = "exception-trend-by-rule"
  workgroup = aws_athena_workgroup.lbp.id
  database  = aws_glue_catalog_database.lbp.name
  query     = <<-SQL
    SELECT date_trunc('day', created_at) AS day, rule_id, tier, count(*) AS exceptions
    FROM exceptions
    GROUP BY 1, 2, 3
    ORDER BY 1 DESC, 4 DESC
  SQL
}

resource "aws_redshiftserverless_namespace" "lbp" {
  namespace_name        = local.name
  db_name               = "lbp_analytics"
  kms_key_id            = aws_kms_key.data.arn
  manage_admin_password = true
  admin_username        = "lbpadmin"
  iam_roles             = [aws_iam_role.redshift.arn]
}

resource "aws_redshiftserverless_workgroup" "lbp" {
  namespace_name      = aws_redshiftserverless_namespace.lbp.namespace_name
  workgroup_name      = local.name
  base_capacity       = 8
  max_capacity        = 64
  publicly_accessible = false
  subnet_ids          = module.vpc.private_subnets
  security_group_ids  = [aws_security_group.app.id]
}

resource "aws_iam_role" "redshift" {
  name = "${local.name}-redshift"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "redshift.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy" "redshift" {
  role = aws_iam_role.redshift.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:GetObject", "s3:ListBucket"], Resource = [aws_s3_bucket.zone["processed"].arn, "${aws_s3_bucket.zone["processed"].arn}/*"] },
      { Effect = "Allow", Action = ["glue:GetDatabase", "glue:GetTable", "glue:GetTables", "glue:GetPartitions"], Resource = "*" },
      { Effect = "Allow", Action = ["kms:Decrypt"], Resource = aws_kms_key.data.arn }
    ]
  })
}
