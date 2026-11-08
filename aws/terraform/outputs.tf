output "web_url" {
  value = "https://${aws_cloudfront_distribution.web.domain_name}"
}

output "api_endpoint" {
  value = aws_apigatewayv2_api.main.api_endpoint
}

output "raw_bucket" {
  value = aws_s3_bucket.zone["raw"].bucket
}

output "processed_bucket" {
  value = aws_s3_bucket.zone["processed"].bucket
}

output "web_bucket" {
  value = aws_s3_bucket.web.bucket
}

output "ecr_repository" {
  value = aws_ecr_repository.lbp.repository_url
}

output "state_machine_arn" {
  value = aws_sfn_state_machine.boarding.arn
}

output "cognito_user_pool_id" {
  value = aws_cognito_user_pool.main.id
}

output "cognito_client_id" {
  value = aws_cognito_user_pool_client.web.id
}

output "cognito_domain" {
  value = "https://${aws_cognito_user_pool_domain.main.domain}.auth.${var.region}.amazoncognito.com"
}

output "rules_table" {
  value = aws_dynamodb_table.rules.name
}

output "db_secret_arn" {
  value = local.db_secret_arn
}

output "glue_jobs" {
  value = { feed = aws_glue_job.feed.name, feed_spark = aws_glue_job.feed_spark.name, feed_load = aws_glue_job.feed_load.name, vendor_pull = aws_glue_job.vendor_pull.name }
}

output "config_signing_secret_arn" {
  value = aws_secretsmanager_secret.config_signing.arn
}

output "migrate_function" {
  value = aws_lambda_function.fn["migrate"].function_name
}

output "glue_wheel_key" {
  value = var.lbp_wheel_key
}
