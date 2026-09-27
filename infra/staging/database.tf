resource "aws_db_subnet_group" "main" {
  name       = local.name
  subnet_ids = aws_subnet.private[*].id
}
resource "aws_db_parameter_group" "main" {
  name_prefix = "${local.name}-"
  family      = "postgres${split(".", var.database_engine_version)[0]}"
  parameter {
    name         = "rds.force_ssl"
    value        = "1"
    apply_method = "pending-reboot"
  }
  lifecycle { create_before_destroy = true }
}
resource "aws_cloudwatch_log_group" "database" {
  name              = "/aws/rds/instance/${local.name}/postgresql"
  retention_in_days = 14
}
resource "aws_db_instance" "main" {
  identifier                      = local.name
  engine                          = "postgres"
  engine_version                  = var.database_engine_version
  engine_lifecycle_support        = "open-source-rds-extended-support-disabled"
  instance_class                  = var.database_instance_class
  db_name                         = "traceworth"
  username                        = "traceworth_admin"
  manage_master_user_password     = true
  allocated_storage               = 20
  max_allocated_storage           = 50
  storage_type                    = "gp3"
  storage_encrypted               = true
  publicly_accessible             = false
  multi_az                        = false
  db_subnet_group_name            = aws_db_subnet_group.main.name
  vpc_security_group_ids          = [aws_security_group.database.id]
  parameter_group_name            = aws_db_parameter_group.main.name
  backup_retention_period         = 7
  backup_window                   = "07:00-08:00"
  maintenance_window              = "sun:08:00-sun:09:00"
  auto_minor_version_upgrade      = true
  deletion_protection             = true
  skip_final_snapshot             = false
  final_snapshot_identifier       = "${local.name}-final"
  copy_tags_to_snapshot           = true
  enabled_cloudwatch_logs_exports = ["postgresql"]
  lifecycle { prevent_destroy = true }
  depends_on = [aws_cloudwatch_log_group.database]
}
# Values are populated through Secrets Manager, never Terraform variables/state.
resource "aws_secretsmanager_secret" "runtime_database" {
  name                    = "${local.name}/runtime-database"
  recovery_window_in_days = 7
}
resource "aws_secretsmanager_secret" "bootstrap" {
  name                    = "${local.name}/bootstrap-owner"
  recovery_window_in_days = 7
}
