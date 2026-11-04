resource "aws_ecr_repository" "lbp" {
  name                 = local.name
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration { scan_on_push = true }
  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.data.arn
  }
}

locals {
  lambdas = {
    # control plane only: no Lambda transforms or loads loan data (that is Glue's job)
    on-file-arrival = { handler = "handlers.on_file_arrival", timeout = 120, memory = 1024, concurrency = 10 }
    route           = { handler = "handlers.route_batch", timeout = 30, memory = 512, concurrency = 20 }
    finalize        = { handler = "handlers.finalize_batch", timeout = 60, memory = 512, concurrency = 20 }
    mark-failed     = { handler = "handlers.mark_failed", timeout = 60, memory = 512, concurrency = 10 }
    migrate         = { handler = "handlers.migrate", timeout = 900, memory = 1024, concurrency = 1 }
    # one tick at a time (the tick also takes a database leader lease)
    scheduler-tick = { handler = "handlers.scheduler_tick", timeout = 600, memory = 1024, concurrency = 1 }
    api            = { handler = "handlers.api", timeout = 29, memory = 2048, concurrency = 50 }
  }
}

# ---------------- Lambda (one container image, different handlers)
resource "aws_lambda_function" "fn" {
  #checkov:skip=CKV_AWS_272:Container-image functions; integrity via immutable ECR tags + image scanning (code signing applies to zip packages)
  for_each                       = local.lambdas
  reserved_concurrent_executions = each.value.concurrency
  function_name                  = "${local.name}-${each.key}"
  role                           = aws_iam_role.lambda.arn
  package_type                   = "Image"
  image_uri                      = "${aws_ecr_repository.lbp.repository_url}:lambda-${var.image_tag}"
  timeout                        = each.value.timeout
  memory_size                    = each.value.memory
  kms_key_arn                    = aws_kms_key.data.arn

  image_config { command = [each.value.handler] }

  vpc_config {
    subnet_ids         = module.vpc.private_subnets
    security_group_ids = [aws_security_group.app.id]
  }

  environment {
    variables = merge(local.common_env, {
      LBP_GLUE_THRESHOLD_ROWS = tostring(var.glue_threshold_rows)
      LBP_GLUE_SPARK_JOB      = "${local.name}-feed-spark"
      LBP_WORKERS             = "1"
    })
  }

  tracing_config { mode = "Active" }

  # async (EventBridge) failures land here; Step Functions handles retries for the synchronous steps
  dead_letter_config { target_arn = aws_sqs_queue.dlq.arn }
}

resource "aws_cloudwatch_log_group" "lambda" {
  for_each          = local.lambdas
  name              = "/aws/lambda/${local.name}-${each.key}"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.data.arn
}
