resource "aws_sns_topic" "alerts" { name = "${local.name}-alerts" }
resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}
locals {
  alarms = {
    api_5xx = {
      namespace  = "AWS/ApplicationELB", metric = "HTTPCode_Target_5XX_Count",
      statistic  = "Sum", comparison = "GreaterThanThreshold", threshold = 5,
      dimensions = { LoadBalancer = aws_lb.api.arn_suffix }
    }
    unhealthy_targets = {
      namespace  = "AWS/ApplicationELB", metric = "UnHealthyHostCount",
      statistic  = "Maximum", comparison = "GreaterThanThreshold", threshold = 0,
      dimensions = { LoadBalancer = aws_lb.api.arn_suffix, TargetGroup = aws_lb_target_group.api.arn_suffix }
    }
    database_storage = {
      namespace  = "AWS/RDS", metric = "FreeStorageSpace",
      statistic  = "Minimum", comparison = "LessThanThreshold", threshold = 5 * 1024 * 1024 * 1024,
      dimensions = { DBInstanceIdentifier = aws_db_instance.main.identifier }
    }
    database_memory = {
      namespace  = "AWS/RDS", metric = "FreeableMemory",
      statistic  = "Minimum", comparison = "LessThanThreshold", threshold = 128 * 1024 * 1024,
      dimensions = { DBInstanceIdentifier = aws_db_instance.main.identifier }
    }
    api_cpu = {
      namespace  = "AWS/ECS", metric = "CPUUtilization",
      statistic  = "Average", comparison = "GreaterThanThreshold", threshold = 80,
      dimensions = { ClusterName = aws_ecs_cluster.main.name, ServiceName = local.name }
    }
  }
}
resource "aws_cloudwatch_metric_alarm" "pilot" {
  for_each            = local.alarms
  alarm_name          = "${local.name}-${each.key}"
  namespace           = each.value.namespace
  metric_name         = each.value.metric
  statistic           = each.value.statistic
  comparison_operator = each.value.comparison
  threshold           = each.value.threshold
  dimensions          = each.value.dimensions
  period              = 300
  evaluation_periods  = 2
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}
