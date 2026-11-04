resource "aws_sns_topic" "alerts" {
  name              = "${local.name}-alerts"
  kms_master_key_id = aws_kms_key.data.id
}

resource "aws_sns_topic_policy" "alerts" {
  arn = aws_sns_topic.alerts.arn
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "EventBridgePublish", Effect = "Allow", Principal = { Service = "events.amazonaws.com" },
      Action    = "sns:Publish", Resource = aws_sns_topic.alerts.arn
      Condition = { StringEquals = { "aws:SourceAccount" = local.account_id } }
    }]
  })
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alert_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_cloudwatch_metric_alarm" "sfn_failed" {
  alarm_name          = "${local.name}-boarding-failed"
  namespace           = "AWS/States"
  metric_name         = "ExecutionsFailed"
  dimensions          = { StateMachineArn = aws_sfn_state_machine.boarding.arn }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

# Any Glue run of the data plane that fails or times out pages (the batch itself is marked failed by Step Functions)
resource "aws_cloudwatch_event_rule" "glue_failed" {
  name = "${local.name}-glue-failed"
  event_pattern = jsonencode({
    source = ["aws.glue"], "detail-type" = ["Glue Job State Change"],
    detail = { jobName = [aws_glue_job.feed.name, aws_glue_job.feed_spark.name, aws_glue_job.vendor_pull.name], state = ["FAILED", "TIMEOUT", "ERROR"] }
  })
}

resource "aws_cloudwatch_event_target" "glue_failed" {
  rule = aws_cloudwatch_event_rule.glue_failed.name
  arn  = aws_sns_topic.alerts.arn
}

resource "aws_cloudwatch_metric_alarm" "rds_cpu" {
  alarm_name          = "${local.name}-sse-db-cpu"
  namespace           = "AWS/RDS"
  metric_name         = "CPUUtilization"
  dimensions          = { DBInstanceIdentifier = aws_db_instance.main.identifier }
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 3
  threshold           = 80
  comparison_operator = "GreaterThanThreshold"
  alarm_description   = "SSE database under pressure: lower glue_feed_concurrency or raise throttling"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "failure_rate" {
  alarm_name          = "${local.name}-first-pass-failure-rate"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  threshold           = 15
  alarm_description   = "More than 15% of loans failing first pass - likely a mapping or source format change"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  metric_query {
    id          = "rate"
    expression  = "100 * failed / MAX([processed, 1])"
    label       = "Failure %"
    return_data = true
  }
  metric_query {
    id = "failed"
    metric {
      namespace   = "LBP/Pipeline"
      metric_name = "LoansFailed"
      period      = 900
      stat        = "Sum"
    }
  }
  metric_query {
    id = "processed"
    metric {
      namespace   = "LBP/Pipeline"
      metric_name = "LoansProcessed"
      period      = 900
      stat        = "Sum"
    }
  }
}

resource "aws_cloudwatch_dashboard" "pipeline" {
  dashboard_name = "${local.name}-pipeline"
  dashboard_body = jsonencode({
    widgets = [
      { type = "metric", x = 0, y = 0, width = 12, height = 6, properties = {
        title = "Loans processed vs failed (per 5 min)", region = var.region, stat = "Sum", period = 300,
      metrics = [["LBP/Pipeline", "LoansProcessed"], [".", "LoansFailed"]] } },
      { type = "metric", x = 12, y = 0, width = 12, height = 6, properties = {
        title = "Batch duration on Glue (s)", region = var.region, period = 300,
      metrics = [["LBP/Pipeline", "BatchSeconds", { stat = "p50" }], ["...", { stat = "p95" }]] } },
      { type = "metric", x = 0, y = 6, width = 12, height = 6, properties = {
        title = "Step Functions executions", region = var.region, stat = "Sum", period = 300,
      metrics = [["AWS/States", "ExecutionsSucceeded", "StateMachineArn", aws_sfn_state_machine.boarding.arn], [".", "ExecutionsFailed", ".", "."]] } },
      { type = "metric", x = 12, y = 6, width = 12, height = 6, properties = {
        title = "SSE database CPU / connections", region = var.region, period = 300,
      metrics = [["AWS/RDS", "CPUUtilization", "DBInstanceIdentifier", aws_db_instance.main.identifier], [".", "DatabaseConnections", ".", "."]] } }
    ]
  })
}

# The scheduler is what notices a vendor file that never came. If it stops, nothing alerts, so
# watch it like a dead man's switch: no successful tick in 15 minutes, or ticks failing, pages.
resource "aws_cloudwatch_metric_alarm" "scheduler_silent" {
  alarm_name          = "${local.name}-delivery-scheduler-silent"
  namespace           = "AWS/Lambda"
  metric_name         = "Invocations"
  dimensions          = { FunctionName = aws_lambda_function.fn["scheduler-tick"].function_name }
  statistic           = "Sum"
  period              = 900
  evaluation_periods  = 1
  comparison_operator = "LessThanThreshold"
  threshold           = 1
  treat_missing_data  = "breaching"
  alarm_description   = "Delivery scheduler has not run for 15 minutes: late/missed vendor files would go unnoticed"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "scheduler_errors" {
  alarm_name          = "${local.name}-delivery-scheduler-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.fn["scheduler-tick"].function_name }
  statistic           = "Sum"
  period              = 900
  evaluation_periods  = 2
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = 2
  treat_missing_data  = "notBreaching"
  alarm_description   = "Delivery scheduler ticks are failing"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}
