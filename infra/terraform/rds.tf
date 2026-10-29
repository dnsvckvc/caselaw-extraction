# Postgres 16 on the smallest instance. The schema is created by the loader
# (`caselaw db-load` runs src/caselaw_extraction/sql/schema.sql); Terraform only provides the
# server. The connection string is stored once in SSM and injected into the tasks as a secret.
resource "random_password" "db" {
  length  = 24
  special = false
}

resource "aws_db_subnet_group" "db" {
  name       = "${local.name}-db"
  subnet_ids = data.aws_subnets.default.ids
}

resource "aws_security_group" "db" {
  name        = "${local.name}-db"
  description = "Postgres: API tasks and listed CIDRs only"
  vpc_id      = data.aws_vpc.default.id
}

resource "aws_vpc_security_group_ingress_rule" "db_from_api" {
  security_group_id            = aws_security_group.db.id
  referenced_security_group_id = aws_security_group.api.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_ingress_rule" "db_from_cidr" {
  for_each          = toset(var.db_allowed_cidrs)
  security_group_id = aws_security_group.db.id
  cidr_ipv4         = each.value
  from_port         = 5432
  to_port           = 5432
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "db_all" {
  security_group_id = aws_security_group.db.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

resource "aws_db_instance" "db" {
  identifier              = "${local.name}-db"
  engine                  = "postgres"
  engine_version          = "16"
  instance_class          = var.db_instance_class
  allocated_storage       = var.db_allocated_storage
  storage_type            = "gp3"
  db_name                 = "caselaw"
  username                = "caselaw"
  password                = random_password.db.result
  db_subnet_group_name    = aws_db_subnet_group.db.name
  vpc_security_group_ids  = [aws_security_group.db.id]
  publicly_accessible     = var.db_publicly_accessible
  backup_retention_period = 1
  skip_final_snapshot     = true
  deletion_protection     = false
  apply_immediately       = true
}

locals {
  dsn = "postgresql://caselaw:${random_password.db.result}@${aws_db_instance.db.address}:${aws_db_instance.db.port}/caselaw"
}

resource "aws_ssm_parameter" "dsn" {
  name  = "/${local.name}/dsn"
  type  = "SecureString"
  value = local.dsn
}
