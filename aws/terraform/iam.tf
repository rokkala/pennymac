data "aws_iam_policy_document" "app_access" {
  statement {
    sid       = "S3Zones"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket", "s3:HeadObject", "s3:DeleteObject"]
    resources = flatten([for k in ["raw", "processed", "athena"] : [aws_s3_bucket.zone[k].arn, "${aws_s3_bucket.zone[k].arn}/*"]])
  }
  statement {
    sid       = "Kms"
    actions   = ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey*", "kms:DescribeKey"]
    resources = [aws_kms_key.data.arn]
  }
  statement {
    sid       = "Dynamo"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query", "dynamodb:Scan"]
    resources = [aws_dynamodb_table.rules.arn, "${aws_dynamodb_table.rules.arn}/index/*", aws_dynamodb_table.policy.arn]
  }
  statement {
    sid       = "Secrets"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [local.db_secret_arn]
  }
  statement {
    sid       = "Bedrock"
    actions   = ["bedrock:InvokeModel", "bedrock:Converse"]
    resources = ["arn:aws:bedrock:${var.region}::foundation-model/*", "arn:aws:bedrock:${var.region}:${local.account_id}:inference-profile/*"]
  }
  statement {
    sid       = "AppSettings"
    actions   = ["ssm:GetParametersByPath"]
    resources = ["arn:aws:ssm:${var.region}:${local.account_id}:parameter/${local.name}/app/*", "arn:aws:ssm:${var.region}:${local.account_id}:parameter/${local.name}/app"]
  }
  statement {
    sid       = "Comprehend"
    actions   = ["comprehend:DetectPiiEntities", "comprehend:ContainsPiiEntities"]
    resources = ["*"]
  }
  statement {
    sid       = "Aoss"
    actions   = ["aoss:APIAccessAll"]
    resources = [aws_opensearchserverless_collection.precedents.arn]
  }
  statement {
    sid       = "Metrics"
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "cloudwatch:namespace"
      values   = ["LBP/Pipeline"]
    }
  }
  statement {
    sid       = "QuickSightEmbed"
    actions   = ["quicksight:GenerateEmbedUrlForRegisteredUser", "quicksight:GenerateEmbedUrlForAnonymousUser"]
    resources = ["arn:aws:quicksight:${var.region}:${local.account_id}:*"]
  }
  statement {
    sid       = "StartPipeline"
    actions   = ["states:StartExecution", "states:ListExecutions"]
    resources = ["arn:aws:states:${var.region}:${local.account_id}:stateMachine:${local.name}-boarding"]
  }
  statement {
    sid       = "ReadPipeline"
    actions   = ["states:DescribeExecution", "states:GetExecutionHistory"]
    resources = ["arn:aws:states:${var.region}:${local.account_id}:execution:${local.name}-boarding:*"]
  }
  statement {
    sid       = "ConfigSigning"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.config_signing.arn]
  }
  statement {
    sid       = "GlueRuns"
    actions   = ["glue:StartJobRun", "glue:GetJobRun", "glue:GetJobRuns"]
    resources = ["arn:aws:glue:${var.region}:${local.account_id}:job/${local.name}-*"]
  }
  statement {
    sid       = "VendorPullCredentials"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = ["arn:aws:secretsmanager:${var.region}:${local.account_id}:secret:${local.name}/vendors/*"]
  }
  statement {
    sid       = "Alerts"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alerts.arn]
  }
  statement {
    sid       = "AsyncDlq"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.dlq.arn]
  }
  dynamic "statement" {
    for_each = length(var.vendor_pull_buckets) > 0 ? [1] : []
    content {
      sid       = "VendorPullBuckets"
      actions   = ["s3:GetObject", "s3:ListBucket"]
      resources = flatten([for b in var.vendor_pull_buckets : ["arn:aws:s3:::${b}", "arn:aws:s3:::${b}/*"]])
    }
  }
  dynamic "statement" {
    for_each = length(var.vendor_pull_role_arns) > 0 ? [1] : []
    content {
      sid       = "VendorPullRoles"
      actions   = ["sts:AssumeRole"]
      resources = var.vendor_pull_role_arns
    }
  }
  statement {
    sid = "CognitoPersonaAdmin"
    actions = [
      "cognito-idp:AdminCreateUser",
      "cognito-idp:AdminDisableUser",
      "cognito-idp:AdminEnableUser",
      "cognito-idp:AdminAddUserToGroup",
      "cognito-idp:AdminRemoveUserFromGroup",
      "cognito-idp:AdminListGroupsForUser",
      "cognito-idp:AdminSetUserPassword",
      "cognito-idp:ListUsers",
      "cognito-idp:AdminGetUser",
    ]
    resources = [aws_cognito_user_pool.main.arn]
  }
}

# Lambda role (control plane)
resource "aws_iam_role" "lambda" {
  name = "${local.name}-lambda"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_vpc" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_iam_role_policy" "lambda" {
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.app_access.json
}

# Step Functions role
resource "aws_iam_role" "sfn" {
  name = "${local.name}-sfn"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "states.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy" "sfn" {
  role = aws_iam_role.sfn.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["lambda:InvokeFunction"], Resource = [for f in aws_lambda_function.fn : f.arn] },
      { Effect = "Allow", Action = ["glue:StartJobRun", "glue:GetJobRun", "glue:GetJobRuns", "glue:BatchStopJobRun"],
      Resource = [aws_glue_job.feed.arn, aws_glue_job.feed_spark.arn, aws_glue_job.feed_load.arn] },
      { Effect = "Allow", Action = ["sns:Publish"], Resource = aws_sns_topic.alerts.arn },
      { Effect = "Allow", Action = ["kms:GenerateDataKey*", "kms:Decrypt"], Resource = aws_kms_key.data.arn },
      { Effect = "Allow", Action = ["logs:CreateLogDelivery", "logs:GetLogDelivery", "logs:UpdateLogDelivery", "logs:DeleteLogDelivery",
      "logs:ListLogDeliveries", "logs:PutResourcePolicy", "logs:DescribeResourcePolicies", "logs:DescribeLogGroups"], Resource = "*" },
      { Effect = "Allow", Action = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"], Resource = "*" }
    ]
  })
}

# Glue role
resource "aws_iam_role" "glue" {
  name = "${local.name}-glue"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "glue.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy_attachment" "glue_service" {
  role       = aws_iam_role.glue.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

resource "aws_iam_role_policy" "glue" {
  role   = aws_iam_role.glue.id
  policy = data.aws_iam_policy_document.app_access.json
}

# Security configuration encrypts Glue CloudWatch logs with the data key. The service role can write
# logs, but only AssociateKmsKey lets Glue attach that key to the job log group.
resource "aws_iam_role_policy" "glue_logs" {
  role = aws_iam_role.glue.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "EncryptJobLogs"
      Effect   = "Allow"
      Action   = ["logs:AssociateKmsKey"]
      Resource = "arn:aws:logs:${var.region}:${local.account_id}:log-group:/aws-glue/*"
    }]
  })
}
