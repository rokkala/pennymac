module "vpc" {
  # pinned to a tag via git so builds do not depend on the public module registry
  source = "git::https://github.com/terraform-aws-modules/terraform-aws-vpc.git?ref=e226cc15a7b8f62fd0e108792fea66fa85bcb4b9" # v5.13.0

  name                 = local.name
  cidr                 = var.vpc_cidr
  azs                  = local.azs
  private_subnets      = [for i, _ in local.azs : cidrsubnet(var.vpc_cidr, 4, i)]
  public_subnets       = [for i, _ in local.azs : cidrsubnet(var.vpc_cidr, 8, 200 + i)]
  database_subnets     = [for i, _ in local.azs : cidrsubnet(var.vpc_cidr, 8, 210 + i)]
  enable_nat_gateway   = true
  single_nat_gateway   = var.env != "prod"
  enable_dns_hostnames = true

  enable_flow_log                      = true
  create_flow_log_cloudwatch_log_group = true
  create_flow_log_cloudwatch_iam_role  = true
}

# Gateway endpoints keep S3/DynamoDB traffic off the NAT
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = module.vpc.vpc_id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = module.vpc.private_route_table_ids
}

resource "aws_vpc_endpoint" "dynamodb" {
  vpc_id            = module.vpc.vpc_id
  service_name      = "com.amazonaws.${var.region}.dynamodb"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = module.vpc.private_route_table_ids
}

resource "aws_security_group" "app" {
  name        = "${local.name}-app"
  description = "Glue jobs and VPC Lambdas"
  vpc_id      = module.vpc.vpc_id
}

# Standalone rules only. Inline rules on the group get revoked whenever the group is updated,
# which previously dropped the database egress and left Lambdas unable to reach RDS.
resource "aws_security_group_rule" "app_https_egress" {
  description       = "HTTPS to AWS APIs (S3, DynamoDB, Bedrock, Secrets Manager) via endpoints/NAT"
  type              = "egress"
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  security_group_id = aws_security_group.app.id
  cidr_blocks       = ["0.0.0.0/0"]
}

resource "aws_security_group_rule" "app_to_vendor_sftp" {
  count             = length(var.vendor_sftp_cidrs) > 0 ? 1 : 0
  description       = "SFTP to approved vendor servers only (delivery pull connector)"
  type              = "egress"
  from_port         = 22
  to_port           = 22
  protocol          = "tcp"
  security_group_id = aws_security_group.app.id
  cidr_blocks       = var.vendor_sftp_cidrs
}

resource "aws_security_group_rule" "app_to_db" {
  description              = "RDS from Glue jobs and Lambdas"
  type                     = "egress"
  from_port                = local.db_port
  to_port                  = local.db_port
  protocol                 = "tcp"
  security_group_id        = aws_security_group.app.id
  source_security_group_id = aws_security_group.db.id
}

resource "aws_security_group_rule" "app_to_redshift" {
  description              = "Redshift Serverless (analytics loads)"
  type                     = "egress"
  from_port                = 5439
  to_port                  = 5439
  protocol                 = "tcp"
  security_group_id        = aws_security_group.app.id
  source_security_group_id = aws_security_group.app.id
}

# Glue jobs run in the VPC through a NETWORK connection; Glue requires a self-referencing rule on its SG
resource "aws_security_group_rule" "app_self_ingress" {
  description              = "Glue workers talk to each other (required by Glue VPC connections)"
  type                     = "ingress"
  from_port                = 0
  to_port                  = 65535
  protocol                 = "tcp"
  security_group_id        = aws_security_group.app.id
  source_security_group_id = aws_security_group.app.id
}

resource "aws_security_group_rule" "app_self_egress" {
  description              = "Glue workers talk to each other (required by Glue VPC connections)"
  type                     = "egress"
  from_port                = 0
  to_port                  = 65535
  protocol                 = "tcp"
  security_group_id        = aws_security_group.app.id
  source_security_group_id = aws_security_group.app.id
}

resource "aws_security_group" "db" {
  name        = "${local.name}-db"
  description = "RDS"
  vpc_id      = module.vpc.vpc_id

  ingress {
    description     = "RDS from Glue jobs and Lambdas"
    from_port       = local.db_port
    to_port         = local.db_port
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
  }

  # aws_s3.table_import_from_s3 runs inside RDS and must reach S3 + KMS
  egress {
    description = "RDS aws_s3 import to S3/KMS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
