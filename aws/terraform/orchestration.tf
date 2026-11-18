# ---------------- Step Functions: boarding pipeline
resource "aws_cloudwatch_log_group" "sfn" {
  name              = "/aws/vendedlogs/states/${local.name}-boarding"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.data.arn
}

resource "aws_sfn_state_machine" "boarding" {
  #checkov:skip=CKV_AWS_285:Full execution history is logged (level ALL) but without execution data: payloads would contain NPI
  name     = "${local.name}-boarding"
  role_arn = aws_iam_role.sfn.arn
  definition = templatefile("${path.module}/../stepfunctions/boarding.asl.json", {
    route_fn_arn    = aws_lambda_function.fn["route"].arn
    finalize_fn_arn = aws_lambda_function.fn["finalize"].arn
    failed_fn_arn   = aws_lambda_function.fn["mark-failed"].arn
    feed_job        = aws_glue_job.feed.name
    spark_job       = aws_glue_job.feed_spark.name
    load_job        = aws_glue_job.feed_load.name
    sns_topic_arn   = aws_sns_topic.alerts.arn
  })
  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn.arn}:*"
    include_execution_data = false # never log loan payloads
    level                  = "ALL"
  }
  tracing_configuration { enabled = true }
}

# ---------------- EventBridge: new file in raw/incoming -> start pipeline
resource "aws_cloudwatch_event_rule" "file_arrival" {
  name = "${local.name}-file-arrival"
  event_pattern = jsonencode({
    source      = ["aws.s3"]
    detail-type = ["Object Created"]
    detail = {
      bucket = { name = [aws_s3_bucket.zone["raw"].bucket] }
      object = { key = [{ prefix = "incoming/" }] }
    }
  })
}

resource "aws_cloudwatch_event_target" "file_arrival" {
  rule = aws_cloudwatch_event_rule.file_arrival.name
  arn  = aws_lambda_function.fn["on-file-arrival"].arn
  retry_policy {
    maximum_retry_attempts       = 4
    maximum_event_age_in_seconds = 3600
  }
  dead_letter_config { arn = aws_sqs_queue.dlq.arn }
}

resource "aws_lambda_permission" "file_arrival" {
  statement_id  = "AllowEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fn["on-file-arrival"].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.file_arrival.arn
}

resource "aws_sqs_queue" "dlq" {
  name                      = "${local.name}-events-dlq"
  kms_master_key_id         = aws_kms_key.data.arn
  message_retention_seconds = 1209600
}

# Rule deployments (DynamoDB stream on the rule registry -> audit/notify via EventBridge Pipes)
resource "aws_cloudwatch_event_bus" "rules" {
  name = "${local.name}-rules"
}

resource "aws_cloudwatch_event_rule" "rule_activated" {
  name           = "${local.name}-rule-activated"
  event_bus_name = aws_cloudwatch_event_bus.rules.name
  event_pattern  = jsonencode({ source = ["lbp.rules"], detail-type = ["RuleStatusChanged"], detail = { to = ["active", "canary"] } })
}

resource "aws_cloudwatch_event_target" "rule_activated_sns" {
  rule           = aws_cloudwatch_event_rule.rule_activated.name
  event_bus_name = aws_cloudwatch_event_bus.rules.name
  arn            = aws_sns_topic.alerts.arn
}

# ---------------- Glue catalog and data quality
resource "aws_glue_catalog_database" "lbp" {
  name = replace("${local.name}_catalog", "-", "_")
}

# ---------------- Glue data plane: every byte of loan data is processed here
# The lbp wheel (built by CI, uploaded to glue/wheels/) is installed into each job, so Glue runs exactly the
# same mapping / rule / triage / load code as the tests. Jobs read only signed, published feed configurations.
locals {
  glue_scripts = {
    feed        = "feed_job.py"
    feed-spark  = "feed_spark_job.py"
    feed-load   = "feed_load_job.py"
    vendor-pull = "vendor_pull_job.py"
  }
  processed = aws_s3_bucket.zone["processed"].bucket
  glue_common_args = {
    "--additional-python-modules"        = "s3://${local.processed}/${var.lbp_wheel_key},${local.db_sqlserver ? "pyodbc==5.2.0" : "psycopg[binary]==3.3.6"}"
    "--python-modules-installer-option"  = "--no-cache-dir"
    "--enable-metrics"                   = "true"
    "--enable-observability-metrics"     = "true"
    "--enable-continuous-cloudwatch-log" = "true"
    "--job-bookmark-option"              = "job-bookmark-disable"
    "--TempDir"                          = "s3://${local.processed}/glue/tmp/"
  }
  # the same settings the Lambdas get, passed to Glue as job arguments (aws/glue/*_job.py exports them)
  glue_env_args = { for k, v in local.common_env : "--${k}" => v }
}

resource "aws_s3_object" "glue_script" {
  for_each = local.glue_scripts
  bucket   = aws_s3_bucket.zone["processed"].id
  key      = "glue/scripts/${each.value}"
  source   = "${path.module}/../glue/${each.value}"
  etag     = filemd5("${path.module}/../glue/${each.value}")
}

# Glue reaches RDS (SSE) and the VPC endpoints through the private subnets
resource "aws_glue_connection" "vpc" {
  name            = "${local.name}-vpc"
  connection_type = "NETWORK"
  physical_connection_requirements {
    availability_zone      = data.aws_subnet.glue.availability_zone
    subnet_id              = data.aws_subnet.glue.id
    security_group_id_list = [aws_security_group.app.id]
  }
}

data "aws_subnet" "glue" {
  id = module.vpc.private_subnets[0]
}

# Standard engine: one batch end to end on the driver (gate, pre-flight, map, validate, triage T1-T5,
# micro-batched load with checkpoints, reconcile). Also runs held-loan replays (--mode replay).
resource "aws_glue_job" "feed" {
  name              = "${local.name}-feed"
  description       = "Board one feed file (or replay held loans) using the feed's published configuration"
  role_arn          = aws_iam_role.glue.arn
  glue_version      = "5.0"
  worker_type       = "G.1X"
  number_of_workers = 2
  timeout           = 240
  max_retries       = 0 # Step Functions owns retries; the job resumes from its checkpoint
  connections       = [aws_glue_connection.vpc.name]
  execution_property { max_concurrent_runs = var.glue_feed_concurrency }
  command {
    name            = "glueetl"
    script_location = "s3://${local.processed}/${aws_s3_object.glue_script["feed"].key}"
    python_version  = "3"
  }
  default_arguments      = merge(local.glue_common_args, local.glue_env_args, { "--mode" = "batch" })
  security_configuration = aws_glue_security_configuration.main.name
}

# Spark engine: very large full tapes. Partitions run the same code; the driver persists in bounded
# micro-batches so SSE sees a fixed number of connections regardless of worker count.
resource "aws_glue_job" "feed_spark" {
  name              = "${local.name}-feed-spark"
  description       = "Board a very large full tape with Spark partitions and bounded SSE writes"
  role_arn          = aws_iam_role.glue.arn
  glue_version      = "5.0"
  worker_type       = "G.1X"
  number_of_workers = var.glue_spark_max_workers
  timeout           = 480
  max_retries       = 0
  connections       = [aws_glue_connection.vpc.name]
  execution_property { max_concurrent_runs = 2 }
  command {
    name            = "glueetl"
    script_location = "s3://${local.processed}/${aws_s3_object.glue_script["feed-spark"].key}"
    python_version  = "3"
  }
  default_arguments = merge(local.glue_common_args, local.glue_env_args, {
    "--enable-auto-scaling" = "true"
    "--processed_bucket"    = local.processed
    "--LBP_SPARK_DB_FREE"   = "1"
    "--LBP_BULK_FILE_LOAD"  = "1"
    "--LBP_S3_IMPORT"       = "1"
  })
  security_configuration = aws_glue_security_configuration.main.name
}

# Load engine: COPY clean+dirty S3 parts after Spark DB-free materialize (no Spark cluster).
resource "aws_glue_job" "feed_load" {
  name              = "${local.name}-feed-load"
  description       = "COPY staged bulk-load parts into SSE after Spark materialize"
  role_arn          = aws_iam_role.glue.arn
  glue_version      = "5.0"
  worker_type       = "G.1X"
  number_of_workers = 2
  timeout           = 480
  max_retries       = 0
  connections       = [aws_glue_connection.vpc.name]
  execution_property { max_concurrent_runs = var.glue_feed_concurrency }
  command {
    name            = "glueetl"
    script_location = "s3://${local.processed}/${aws_s3_object.glue_script["feed-load"].key}"
    python_version  = "3"
  }
  default_arguments = merge(local.glue_common_args, local.glue_env_args, {
    "--processed_bucket"   = local.processed
    "--LBP_BULK_FILE_LOAD" = "1"
    "--LBP_S3_IMPORT"      = "1"
  })
  security_configuration = aws_glue_security_configuration.main.name
}

# Vendor pull: fetch due files over SFTP / S3 into raw/incoming/, where arrival starts lbp-feed
resource "aws_glue_job" "vendor_pull" {
  name              = "${local.name}-vendor-pull"
  description       = "Pull a vendor's files (SFTP with pinned host keys, or S3) into the raw zone"
  role_arn          = aws_iam_role.glue.arn
  glue_version      = "5.0"
  worker_type       = "G.1X"
  number_of_workers = 2
  timeout           = 60
  max_retries       = 0
  connections       = [aws_glue_connection.vpc.name]
  execution_property { max_concurrent_runs = 5 }
  command {
    name            = "glueetl"
    script_location = "s3://${local.processed}/${aws_s3_object.glue_script["vendor-pull"].key}"
    python_version  = "3"
  }
  default_arguments      = merge(local.glue_common_args, local.glue_env_args)
  security_configuration = aws_glue_security_configuration.main.name
}

resource "aws_glue_security_configuration" "main" {
  name = "${local.name}-glue-sec"
  encryption_configuration {
    cloudwatch_encryption {
      cloudwatch_encryption_mode = "SSE-KMS"
      kms_key_arn                = aws_kms_key.data.arn
    }
    job_bookmarks_encryption {
      job_bookmarks_encryption_mode = "CSE-KMS"
      kms_key_arn                   = aws_kms_key.data.arn
    }
    s3_encryption {
      s3_encryption_mode = "SSE-KMS"
      kms_key_arn        = aws_kms_key.data.arn
    }
  }
}

resource "aws_glue_crawler" "processed" {
  name          = "${local.name}-processed"
  role          = aws_iam_role.glue.arn
  database_name = aws_glue_catalog_database.lbp.name
  schedule      = "cron(15 * * * ? *)"
  s3_target { path = "s3://${aws_s3_bucket.zone["processed"].bucket}/processed/" }
  s3_target { path = "s3://${aws_s3_bucket.zone["processed"].bucket}/analytics/" }
  security_configuration = aws_glue_security_configuration.main.name
}

# Glue Data Quality ruleset (DQDL) mirrors the format/range checks for the processed zone
resource "aws_glue_data_quality_ruleset" "sse_core" {
  name        = "${local.name}-sse-core"
  description = "Processed-zone guardrails mirroring core SSE rules"
  ruleset     = <<-DQDL
    Rules = [
      IsComplete "loan_number",
      IsUnique "loan_number",
      ColumnValues "interest_rate" between 0.5 and 15,
      ColumnValues "original_term_months" between 60 and 480,
      ColumnLength "property_state" = 2,
      ColumnValues "borrower_fico" between 300 and 850 with threshold > 0.98,
      Completeness "borrower_ssn" > 0.99
    ]
  DQDL
}

# ---------------- vendor delivery scheduler
# One schedule drives the tick; vendor timetables live in the application (maker-checker, per-vendor
# timezone and business calendar), so onboarding a vendor never needs an infrastructure change.
resource "aws_iam_role" "scheduler" {
  name = "${local.name}-scheduler"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow", Principal = { Service = "scheduler.amazonaws.com" }, Action = "sts:AssumeRole"
      Condition = { StringEquals = { "aws:SourceAccount" = local.account_id } }
    }]
  })
}

resource "aws_iam_role_policy" "scheduler" {
  role = aws_iam_role.scheduler.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["lambda:InvokeFunction"], Resource = aws_lambda_function.fn["scheduler-tick"].arn },
      { Effect = "Allow", Action = ["sqs:SendMessage"], Resource = aws_sqs_queue.dlq.arn },
      { Effect = "Allow", Action = ["kms:GenerateDataKey*", "kms:Decrypt"], Resource = aws_kms_key.data.arn }
    ]
  })
}

resource "aws_scheduler_schedule" "delivery_tick" {
  name                         = "${local.name}-delivery-tick"
  schedule_expression          = var.scheduler_rate
  schedule_expression_timezone = "UTC"
  kms_key_arn                  = aws_kms_key.data.arn
  flexible_time_window { mode = "OFF" }
  target {
    arn      = aws_lambda_function.fn["scheduler-tick"].arn
    role_arn = aws_iam_role.scheduler.arn
    retry_policy {
      maximum_retry_attempts       = 0 # the next tick is minutes away and catches up; never stack ticks
      maximum_event_age_in_seconds = 300
    }
    dead_letter_config { arn = aws_sqs_queue.dlq.arn }
  }
}
