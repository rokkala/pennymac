env                   = "uat"
region                = "us-west-2"
ai_provider           = "bedrock"
glue_feed_concurrency = 8
alert_email           = "loan-boarding-alerts@example.com"
# Required: ACM certificate for CloudFront (us-east-1) and the custom domain
web_certificate_arn = "arn:aws:acm:us-east-1:ACCOUNT:certificate/REPLACE"
web_domain          = "loanboarding.uat.example.com"
# saml_metadata_url = "https://login.microsoftonline.com/<tenant>/federationmetadata/2007-06/federationmetadata.xml"

# vendor delivery pulls (fill in per vendor; empty = push-only vendors)
vendor_sftp_hosts   = []
vendor_sftp_cidrs   = []
vendor_pull_buckets = []
