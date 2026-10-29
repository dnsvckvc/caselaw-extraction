output "region" {
  value = var.region
}

output "api_url" {
  description = "Public, read-only. HTTP only: there is no domain, so no certificate."
  value       = "http://${aws_lb.api.dns_name}"
}

output "ecr_repository_url" {
  value = aws_ecr_repository.api.repository_url
}

output "runs_bucket" {
  value = aws_s3_bucket.runs.bucket
}

output "db_address" {
  value = aws_db_instance.db.address
}

output "dsn_parameter" {
  description = "SSM parameter that holds the connection string (SecureString)."
  value       = aws_ssm_parameter.dsn.name
}

output "cluster_name" {
  value = aws_ecs_cluster.main.name
}

output "service_name" {
  value = aws_ecs_service.api.name
}

output "load_task_family" {
  value = aws_ecs_task_definition.load.family
}

output "subnet_ids" {
  value = data.aws_subnets.default.ids
}

output "api_security_group_id" {
  value = aws_security_group.api.id
}

output "log_group" {
  value = aws_cloudwatch_log_group.api.name
}

output "dashboard_url" {
  value = "https://${var.region}.console.aws.amazon.com/cloudwatch/home?region=${var.region}#dashboards:name=${aws_cloudwatch_dashboard.api.dashboard_name}"
}

output "github_deploy_role_arn" {
  value = try(aws_iam_role.github_deploy[0].arn, null)
}
