mock_provider "aws" {
  override_during = plan
  mock_data "aws_availability_zones" { defaults = { names = ["us-east-2a", "us-east-2b"] } }
  mock_data "aws_cloudfront_cache_policy" { defaults = { id = "11111111-1111-1111-1111-111111111111" } }
  mock_resource "aws_cloudfront_distribution" { defaults = { domain_name = "d123example.cloudfront.net" } }
  mock_resource "aws_cloudwatch_log_group" { defaults = { arn = "arn:aws:logs:us-east-2:123456789012:log-group:traceworth-staging" } }
  mock_resource "aws_ecr_repository" { defaults = { arn = "arn:aws:ecr:us-east-2:123456789012:repository/traceworth-staging" } }
  mock_resource "aws_iam_role" { defaults = { arn = "arn:aws:iam::123456789012:role/mock-role" } }
  mock_resource "aws_secretsmanager_secret" { defaults = { arn = "arn:aws:secretsmanager:us-east-2:123456789012:secret:mock-AbCdEf" } }
  mock_resource "aws_db_instance" {
    defaults = {
      address            = "mock.database.example"
      master_user_secret = [{ secret_arn = "arn:aws:secretsmanager:us-east-2:123456789012:secret:admin-AbCdEf", secret_status = "active", kms_key_id = "arn:aws:kms:us-east-2:123456789012:key/mock" }]
    }
  }
}
mock_provider "aws" {
  alias           = "edge"
  override_during = plan
}
override_resource {
  target          = aws_security_group.api
  values          = { id = "sg-11111111111111111" }
  override_during = plan
}
override_resource {
  target          = aws_security_group.alb
  values          = { id = "sg-22222222222222222" }
  override_during = plan
}
override_resource {
  target          = aws_security_group.database
  values          = { id = "sg-33333333333333333" }
  override_during = plan
}
variables {
  expected_account_id = "123456789012"
  pilot_ipv4_cidrs    = ["192.0.2.1/32"]
  alert_email         = "staging-alerts@example.test"
}
run "safe_defaults" {
  command = plan
  assert {
    condition     = length(aws_ecs_service.api) == 0 && length(aws_ecs_task_definition.api) == 0
    error_message = "Default infrastructure must not launch an unconfigured application image."
  }
  assert {
    condition     = aws_lb.api.internal && !aws_db_instance.main.publicly_accessible && aws_db_instance.main.storage_encrypted && aws_db_instance.main.manage_master_user_password
    error_message = "ALB and database must stay private; database must use encryption and managed credentials."
  }
  assert {
    condition     = aws_db_instance.main.deletion_protection && !aws_db_instance.main.skip_final_snapshot && aws_db_instance.main.backup_retention_period >= 7
    error_message = "Database recovery protections must remain enabled."
  }
  assert {
    condition     = aws_vpc_security_group_ingress_rule.database.referenced_security_group_id == aws_security_group.api.id && aws_vpc_security_group_ingress_rule.database.from_port == 5432 && aws_vpc_security_group_ingress_rule.database.cidr_ipv4 == null
    error_message = "Database ingress must be scoped to application security group, never public CIDR."
  }
  assert {
    condition     = aws_vpc_security_group_ingress_rule.api.referenced_security_group_id == aws_security_group.alb.id && aws_vpc_security_group_ingress_rule.api.from_port == 8000 && aws_vpc_security_group_ingress_rule.api.cidr_ipv4 == null
    error_message = "API ingress must originate exclusively from the ALB security group."
  }
  assert {
    condition     = alltrue([for b in aws_cloudfront_distribution.dashboard.ordered_cache_behavior : b.cache_policy_id == data.aws_cloudfront_cache_policy.api.id && b.viewer_protocol_policy == "https-only" && toset(b.allowed_methods) == toset(["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"])]) && data.aws_cloudfront_cache_policy.api.name == "Managed-CachingDisabled"
    error_message = "Authenticated API behaviors must disable caching and permit all API methods over HTTPS."
  }
  assert {
    condition     = aws_s3_bucket_public_access_block.dashboard.block_public_acls && aws_s3_bucket_public_access_block.dashboard.block_public_policy && aws_s3_bucket_public_access_block.dashboard.ignore_public_acls && aws_s3_bucket_public_access_block.dashboard.restrict_public_buckets
    error_message = "Dashboard bucket must block all public access."
  }
}
run "configured_image_security" {
  command = plan
  variables { container_image = "123456789012.dkr.ecr.us-east-2.amazonaws.com/traceworth@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" }
  assert {
    condition     = !aws_ecs_service.api[0].network_configuration[0].assign_public_ip && aws_ecs_service.api[0].desired_count == 0
    error_message = "Configured service must remain private and stopped until explicit activation."
  }
  assert {
    condition     = jsondecode(aws_ecs_task_definition.api[0].container_definitions)[0].user == "10001:10001" && jsondecode(aws_ecs_task_definition.api[0].container_definitions)[0].readonlyRootFilesystem
    error_message = "API container must run non-root with a read-only root filesystem."
  }
  assert {
    condition     = toset([for s in jsondecode(aws_ecs_task_definition.api[0].container_definitions)[0].secrets : s.name]) == toset(["TRACEWORTH_DB_USER", "TRACEWORTH_DB_PASSWORD"]) && alltrue([for e in jsondecode(aws_ecs_task_definition.api[0].container_definitions)[0].environment : !strcontains(e.name, "PASSWORD")])
    error_message = "API receives only runtime DB secret references, never literal password environment values or admin credentials."
  }
  assert {
    condition     = jsondecode(aws_iam_role_policy.execution["api"].policy).Statement[3].Resource == [aws_secretsmanager_secret.runtime_database.arn]
    error_message = "API execution role must read only its runtime secret."
  }
}
run "reject_worldwide_pilot" {
  command = plan
  variables { pilot_ipv4_cidrs = ["0.0.0.0/0"] }
  expect_failures = [var.pilot_ipv4_cidrs]
}
run "reject_mutable_image" {
  command = plan
  variables { container_image = "123456789012.dkr.ecr.us-east-2.amazonaws.com/traceworth:latest" }
  expect_failures = [var.container_image]
}
