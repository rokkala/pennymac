env    = "poc"
region = "us-west-2"
image_tag = "app6"
# Small PostgreSQL for a poc. The suite is verified on PostgreSQL; SQL Server Standard cannot run this small.
db_engine                = "postgres"
db_engine_version        = "16"
db_instance_class        = "db.t4g.medium"
db_allocated_storage     = 200
db_max_allocated_storage = 200
ai_provider              = "bedrock"
glue_feed_concurrency    = 8
# Default 500k → Spark. For a 1M-row standard-path A/B (lbp-feed vs Spark), raise above the tape:
# glue_threshold_rows = 2000000
glue_threshold_rows      = 500000
alert_email              = "loan-boarding-alerts@example.com"
# Required: ACM certificate for CloudFront (us-east-1) and the custom domain
web_certificate_arn = ""
web_domain          = ""
# saml_metadata_url = "https://login.microsoftonline.com/<tenant>/federationmetadata/2007-06/federationmetadata.xml"

# vendor delivery pulls (fill in per vendor; empty = push-only vendors)
vendor_sftp_hosts   = []
vendor_sftp_cidrs   = []
vendor_pull_buckets = []
