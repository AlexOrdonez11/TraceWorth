resource "aws_ecr_repository" "api" {
  name                 = local.name
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration { scan_on_push = true }
}
resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${local.name}"
  retention_in_days = 14
}
resource "aws_ecs_cluster" "main" { name = local.name }
locals {
  ecs_assume_role = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
  common_environment = [
    { name = "TRACEWORTH_MODE", value = "cloud" },
    { name = "TRACEWORTH_DB_HOST", value = aws_db_instance.main.address },
    { name = "TRACEWORTH_DB_NAME", value = aws_db_instance.main.db_name },
    { name = "TRACEWORTH_DB_SSLROOTCERT", value = "/etc/ssl/certs/rds-global-bundle.pem" },
    { name = "TRACEWORTH_ALLOWED_ORIGINS", value = jsonencode(["https://${aws_cloudfront_distribution.dashboard.domain_name}"]) },
    { name = "TRACEWORTH_PORT", value = "8000" },
    { name = "TRACEWORTH_DB_POOL_MAX", value = "5" },
    { name = "TRACEWORTH_METRICS_MAX_EVENTS", value = "10000" }
  ]
  logs = {
    logDriver = "awslogs"
    options = {
      awslogs-group         = aws_cloudwatch_log_group.api.name
      awslogs-region        = var.aws_region
      awslogs-stream-prefix = "api"
    }
  }
}
resource "aws_iam_role" "execution" {
  for_each           = toset(["api", "admin"])
  name               = "${local.name}-${each.key}-execution"
  assume_role_policy = local.ecs_assume_role
}
resource "aws_iam_role_policy" "execution" {
  for_each = aws_iam_role.execution
  name     = "image-logs-secrets"
  role     = each.value.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*" },
      { Effect = "Allow", Action = ["ecr:BatchCheckLayerAvailability", "ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage"], Resource = aws_ecr_repository.api.arn },
      { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.api.arn}:*" },
      {
        Effect = "Allow", Action = ["secretsmanager:GetSecretValue"],
        Resource = each.key == "api" ? [aws_secretsmanager_secret.runtime_database.arn] : [
          aws_db_instance.main.master_user_secret[0].secret_arn,
          aws_secretsmanager_secret.runtime_database.arn,
          aws_secretsmanager_secret.bootstrap.arn
        ]
      }
    ]
  })
}
# Application code needs no AWS API permissions.
resource "aws_iam_role" "task" {
  name               = "${local.name}-task"
  assume_role_policy = local.ecs_assume_role
}
resource "aws_ecs_task_definition" "api" {
  count                    = var.container_image == null ? 0 : 1
  family                   = "${local.name}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.execution["api"].arn
  task_role_arn            = aws_iam_role.task.arn
  container_definitions = jsonencode([{
    name         = "api", image = var.container_image, essential = true,
    user         = "10001:10001", readonlyRootFilesystem = true,
    portMappings = [{ containerPort = 8000, protocol = "tcp" }],
    environment  = local.common_environment,
    secrets = [
      { name = "TRACEWORTH_DB_USER", valueFrom = "${aws_secretsmanager_secret.runtime_database.arn}:username::" },
      { name = "TRACEWORTH_DB_PASSWORD", valueFrom = "${aws_secretsmanager_secret.runtime_database.arn}:password::" }
    ],
    logConfiguration = local.logs,
    stopTimeout      = 60,
    healthCheck = {
      command  = ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health/live', timeout=3)"],
      interval = 30, timeout = 5, retries = 3, startPeriod = 30
    }
  }])
}
resource "aws_ecs_task_definition" "admin" {
  count                    = var.container_image == null ? 0 : 1
  family                   = "${local.name}-admin"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.execution["admin"].arn
  task_role_arn            = aws_iam_role.task.arn
  container_definitions = jsonencode([{
    name        = "admin", image = var.container_image, essential = true,
    user        = "10001:10001", readonlyRootFilesystem = true,
    command     = ["migrate"],
    environment = local.common_environment,
    secrets = [
      { name = "TRACEWORTH_DB_USER", valueFrom = "${aws_db_instance.main.master_user_secret[0].secret_arn}:username::" },
      { name = "TRACEWORTH_DB_PASSWORD", valueFrom = "${aws_db_instance.main.master_user_secret[0].secret_arn}:password::" },
      { name = "TRACEWORTH_RUNTIME_DB_USER", valueFrom = "${aws_secretsmanager_secret.runtime_database.arn}:username::" },
      { name = "TRACEWORTH_RUNTIME_DB_PASSWORD", valueFrom = "${aws_secretsmanager_secret.runtime_database.arn}:password::" },
      { name = "TRACEWORTH_BOOTSTRAP_PASSWORD", valueFrom = "${aws_secretsmanager_secret.bootstrap.arn}:password::" }
    ],
    logConfiguration = local.logs
  }])
}
resource "aws_ecs_service" "api" {
  count                              = var.container_image == null ? 0 : 1
  name                               = local.name
  cluster                            = aws_ecs_cluster.main.id
  task_definition                    = aws_ecs_task_definition.api[0].arn
  desired_count                      = var.api_desired_count
  launch_type                        = "FARGATE"
  platform_version                   = "1.4.0"
  health_check_grace_period_seconds  = 60
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.api.id]
    assign_public_ip = false
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }
  depends_on = [aws_lb_listener.api, aws_iam_role_policy.execution]
}
