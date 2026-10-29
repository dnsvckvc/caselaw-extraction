# One dashboard (requests, errors, latency, healthy targets, task CPU and memory, database CPU,
# connections and free storage) and eight alarms on an SNS topic. Service metrics come from
# the load balancer, ECS and RDS at no extra charge; the alarms cost ten cents each per month.

resource "aws_sns_topic" "alarms" {
  name = "${local.name}-alarms"
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alarm_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

locals {
  alb_dim = { LoadBalancer = aws_lb.api.arn_suffix, TargetGroup = aws_lb_target_group.api.arn_suffix }
  lb_only = { LoadBalancer = aws_lb.api.arn_suffix }
  ecs_dim = { ClusterName = aws_ecs_cluster.main.name, ServiceName = aws_ecs_service.api.name }
  rds_dim = { DBInstanceIdentifier = aws_db_instance.db.identifier }
  actions = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "api_5xx" {
  alarm_name          = "${local.name}-api-5xx"
  alarm_description   = "5 or more 5xx responses from the API in 5 minutes"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_Target_5XX_Count"
  dimensions          = local.alb_dim
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 5
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.actions
  ok_actions          = local.actions
}

resource "aws_cloudwatch_metric_alarm" "api_latency" {
  alarm_name          = "${local.name}-api-latency-p95"
  alarm_description   = "p95 response time above 1 s in 2 of 3 five-minute windows"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "TargetResponseTime"
  dimensions          = local.alb_dim
  extended_statistic  = "p95"
  period              = 300
  evaluation_periods  = 3
  datapoints_to_alarm = 2
  threshold           = 1
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.actions
  ok_actions          = local.actions
}

resource "aws_cloudwatch_metric_alarm" "api_unhealthy" {
  alarm_name          = "${local.name}-api-unhealthy-target"
  alarm_description   = "a target failed the /health check for 3 minutes"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "UnHealthyHostCount"
  dimensions          = local.alb_dim
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 3
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.actions
  ok_actions          = local.actions
}

resource "aws_cloudwatch_metric_alarm" "api_no_healthy" {
  alarm_name          = "${local.name}-api-no-healthy-target"
  alarm_description   = "no healthy API task behind the load balancer"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HealthyHostCount"
  dimensions          = local.alb_dim
  statistic           = "Minimum"
  period              = 60
  evaluation_periods  = 3
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = local.actions
  ok_actions          = local.actions
}

resource "aws_cloudwatch_metric_alarm" "ecs_cpu" {
  alarm_name          = "${local.name}-api-cpu"
  alarm_description   = "API tasks above 80 percent CPU for 15 minutes"
  namespace           = "AWS/ECS"
  metric_name         = "CPUUtilization"
  dimensions          = local.ecs_dim
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 3
  threshold           = 80
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.actions
  ok_actions          = local.actions
}

resource "aws_cloudwatch_metric_alarm" "ecs_memory" {
  alarm_name          = "${local.name}-api-memory"
  alarm_description   = "API tasks above 80 percent memory for 15 minutes"
  namespace           = "AWS/ECS"
  metric_name         = "MemoryUtilization"
  dimensions          = local.ecs_dim
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 3
  threshold           = 80
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.actions
  ok_actions          = local.actions
}

resource "aws_cloudwatch_metric_alarm" "rds_cpu" {
  alarm_name          = "${local.name}-db-cpu"
  alarm_description   = "database above 80 percent CPU for 15 minutes"
  namespace           = "AWS/RDS"
  metric_name         = "CPUUtilization"
  dimensions          = local.rds_dim
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 3
  threshold           = 80
  comparison_operator = "GreaterThanThreshold"
  alarm_actions       = local.actions
  ok_actions          = local.actions
}

resource "aws_cloudwatch_metric_alarm" "rds_storage" {
  alarm_name          = "${local.name}-db-free-storage"
  alarm_description   = "database below 2 GB of free storage"
  namespace           = "AWS/RDS"
  metric_name         = "FreeStorageSpace"
  dimensions          = local.rds_dim
  statistic           = "Minimum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 2000000000
  comparison_operator = "LessThanThreshold"
  alarm_actions       = local.actions
  ok_actions          = local.actions
}

locals {
  w = 8
  h = 6
  dashboard_widgets = [
    {
      type       = "text", x = 0, y = 0, width = 24, height = 2,
      properties = { markdown = "## ${local.name} API\nRequests, errors and latency from the load balancer; task CPU and memory from ECS; the database from RDS. Alarms: ${join(", ", [aws_cloudwatch_metric_alarm.api_5xx.alarm_name, aws_cloudwatch_metric_alarm.api_latency.alarm_name, aws_cloudwatch_metric_alarm.api_no_healthy.alarm_name])}." }
    },
    {
      type = "metric", x = 0, y = 2, width = local.w, height = local.h,
      properties = {
        title   = "Requests per minute", region = var.region, stat = "Sum", period = 60, view = "timeSeries",
        metrics = [["AWS/ApplicationELB", "RequestCount", "LoadBalancer", aws_lb.api.arn_suffix]]
      }
    },
    {
      type = "metric", x = local.w, y = 2, width = local.w, height = local.h,
      properties = {
        title = "Responses by class (5 min)", region = var.region, stat = "Sum", period = 300, view = "timeSeries",
        metrics = [
          ["AWS/ApplicationELB", "HTTPCode_Target_2XX_Count", "LoadBalancer", aws_lb.api.arn_suffix, { label = "2xx" }],
          [".", "HTTPCode_Target_4XX_Count", ".", ".", { label = "4xx" }],
          [".", "HTTPCode_Target_5XX_Count", ".", ".", { label = "5xx target", color = "#d62728" }],
          [".", "HTTPCode_ELB_5XX_Count", ".", ".", { label = "5xx load balancer", color = "#ff7f0e" }],
        ]
      }
    },
    {
      type = "metric", x = 2 * local.w, y = 2, width = local.w, height = local.h,
      properties = {
        title = "Target response time (s)", region = var.region, period = 60, view = "timeSeries",
        metrics = [
          ["AWS/ApplicationELB", "TargetResponseTime", "LoadBalancer", aws_lb.api.arn_suffix, { stat = "p50", label = "p50" }],
          ["...", { stat = "p95", label = "p95" }],
          ["...", { stat = "p99", label = "p99" }],
        ],
        annotations = { horizontal = [{ label = "p95 alarm", value = 1 }] }
      }
    },
    {
      type = "metric", x = 0, y = 2 + local.h, width = local.w, height = local.h,
      properties = {
        title = "Healthy / unhealthy targets", region = var.region, period = 60, view = "timeSeries",
        metrics = [
          ["AWS/ApplicationELB", "HealthyHostCount", "TargetGroup", aws_lb_target_group.api.arn_suffix, "LoadBalancer", aws_lb.api.arn_suffix, { stat = "Minimum" }],
          [".", "UnHealthyHostCount", ".", ".", ".", ".", { stat = "Maximum", color = "#d62728" }],
        ]
      }
    },
    {
      type = "metric", x = local.w, y = 2 + local.h, width = local.w, height = local.h,
      properties = {
        title = "API task CPU and memory (%)", region = var.region, stat = "Average", period = 60, view = "timeSeries",
        metrics = [
          ["AWS/ECS", "CPUUtilization", "ClusterName", aws_ecs_cluster.main.name, "ServiceName", aws_ecs_service.api.name],
          [".", "MemoryUtilization", ".", ".", ".", "."],
        ],
        yAxis = { left = { min = 0, max = 100 } }
      }
    },
    {
      type = "metric", x = 2 * local.w, y = 2 + local.h, width = local.w, height = local.h,
      properties = {
        title = "Database CPU (%) and connections", region = var.region, stat = "Average", period = 60, view = "timeSeries",
        metrics = [
          ["AWS/RDS", "CPUUtilization", "DBInstanceIdentifier", aws_db_instance.db.identifier],
          [".", "DatabaseConnections", ".", ".", { yAxis = "right" }],
        ]
      }
    },
    {
      type = "metric", x = 0, y = 2 + 2 * local.h, width = local.w, height = local.h,
      properties = {
        title       = "Database free storage (bytes)", region = var.region, stat = "Minimum", period = 300, view = "timeSeries",
        metrics     = [["AWS/RDS", "FreeStorageSpace", "DBInstanceIdentifier", aws_db_instance.db.identifier]],
        annotations = { horizontal = [{ label = "alarm", value = 2000000000 }] }
      }
    },
    {
      type = "metric", x = local.w, y = 2 + 2 * local.h, width = local.w, height = local.h,
      properties = {
        title = "Database read / write latency (s)", region = var.region, stat = "Average", period = 60, view = "timeSeries",
        metrics = [
          ["AWS/RDS", "ReadLatency", "DBInstanceIdentifier", aws_db_instance.db.identifier],
          [".", "WriteLatency", ".", "."],
        ]
      }
    },
    {
      type = "log", x = 2 * local.w, y = 2 + 2 * local.h, width = local.w, height = local.h,
      properties = {
        title = "Last API log lines", region = var.region, view = "table",
        query = "SOURCE '${aws_cloudwatch_log_group.api.name}' | fields @timestamp, @message | sort @timestamp desc | limit 20"
      }
    },
  ]
}

resource "aws_cloudwatch_dashboard" "api" {
  dashboard_name = "${local.name}-api"
  dashboard_body = jsonencode({ widgets = local.dashboard_widgets })
}
