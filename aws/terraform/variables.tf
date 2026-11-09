variable "env" {
  type    = string
  default = "poc"
}

variable "region" {
  type    = string
  default = "us-west-2"
}

variable "vpc_cidr" {
  type    = string
  default = "10.42.0.0/16"
}

variable "image_tag" {
  description = "Tag of the lbp container image in ECR (API, worker and Lambda share one image)."
  type        = string
  default     = "latest"
}

variable "ai_provider" {
  description = "heuristic | bedrock"
  type        = string
  default     = "bedrock"
}

variable "bedrock_model_id" {
  type    = string
  default = "anthropic.claude-sonnet-4-5-20250929-v1:0"
}

variable "micro_batch_size" {
  type    = number
  default = 10000
}

variable "glue_feed_concurrency" {
  description = "Max concurrent lbp-feed Glue runs (batches loading SSE at once). Primary SSE protection knob."
  type        = number
  default     = 10
}

variable "sse_throttle_rps" {
  description = "Per-worker row/sec cap on SSE writes (0 = unthrottled)."
  type        = number
  default     = 0
}

variable "glue_threshold_rows" {
  description = "Full tapes above this many rows run on the Spark job (lbp-feed-spark); everything else on lbp-feed. Raise above the tape size (e.g. 2e6) for a 1M-row standard-path A/B."
  type        = number
  default     = 500000
}

variable "glue_spark_max_workers" {
  description = "Upper bound for lbp-feed-spark auto-scaling (G.1X workers)"
  type        = number
  default     = 10
}

variable "lbp_wheel_key" {
  description = "Key (in the processed bucket) of the lbp wheel built by CI and installed into every Glue job"
  type        = string
  default     = "glue/wheels/lbp-1.0.0-py3-none-any.whl"
}

variable "db_instance_class" {
  type    = string
  default = "db.m6i.xlarge"
}

variable "db_allocated_storage" {
  description = "RDS gp3 storage in GB. 20 is the minimum."
  type        = number
  default     = 200
}

variable "db_max_allocated_storage" {
  description = "RDS storage autoscaling cap in GB."
  type        = number
  default     = 2000
}

variable "db_engine" {
  description = "RDS engine for platform + SSE staging tables. sqlserver-se matches the SSE estate. postgres is the tested engine for a small poc."
  type        = string
  default     = "sqlserver-se"
}

variable "db_engine_version" {
  description = "RDS engine version. Empty lets AWS pick the default."
  type        = string
  default     = ""
}

variable "alert_email" {
  type    = string
  default = ""
}

variable "saml_metadata_url" {
  description = "Optional corporate IdP (Okta / Entra ID) SAML metadata URL for SSO."
  type        = string
  default     = ""
}

variable "web_domain" {
  description = "Optional custom domain for the web app (leave empty to use the CloudFront domain)."
  type        = string
  default     = ""
}

variable "log_retention_days" {
  description = "CloudWatch log retention (BFSI: at least one year online)."
  type        = number
  default     = 400
}

variable "web_certificate_arn" {
  description = "ACM certificate (us-east-1) for the CloudFront custom domain. Required for prod (TLS 1.2+)."
  type        = string
  default     = ""
}

variable "allowed_countries" {
  description = "Viewer countries allowed at CloudFront (geo restriction)."
  type        = list(string)
  default     = ["US", "IN"]
}

# ---------------- vendor deliveries
variable "scheduler_rate" {
  description = "How often the delivery scheduler runs (late/missed detection resolution, pull polling floor)"
  type        = string
  default     = "rate(5 minutes)"
}

variable "vendor_sftp_hosts" {
  description = "Vendor SFTP hostnames the pull connector may connect to (anything else is refused in code)"
  type        = list(string)
  default     = []
}

variable "vendor_sftp_cidrs" {
  description = "CIDR blocks of vendor SFTP servers; opens egress tcp/22 only to these (empty = no SFTP egress)"
  type        = list(string)
  default     = []
}

variable "vendor_pull_buckets" {
  description = "Vendor-owned S3 buckets shared with PennyMac that the pull connector may list/read"
  type        = list(string)
  default     = []
}

variable "vendor_pull_role_arns" {
  description = "Cross-account roles the pull connector may assume to read vendor buckets"
  type        = list(string)
  default     = []
}
