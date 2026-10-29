# Case-law extraction API on AWS (week 4): the run Parquet in S3, the records in RDS Postgres,
# the FastAPI image on ECS Fargate behind an application load balancer, logs, a dashboard and
# alarms in CloudWatch. The default VPC and its public subnets are used on purpose: a NAT
# gateway would cost more per month than everything else here together, and the API is public
# and read-only. The database is reachable from the API tasks only.

data "aws_caller_identity" "current" {}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
  filter {
    name   = "default-for-az"
    values = ["true"]
  }
}

locals {
  name       = var.project
  account_id = data.aws_caller_identity.current.account_id
  bucket     = "${var.project}-runs-${local.account_id}"
}
