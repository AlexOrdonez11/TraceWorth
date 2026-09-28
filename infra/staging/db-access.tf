# A private Session Manager hop for occasional operator access to PostgreSQL.
# It has no inbound rules, public IP, database password, or permission to read secrets.
data "aws_ssm_parameter" "al2023_arm64" {
  count = var.db_access_enabled ? 1 : 0
  name  = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64"
}

resource "aws_iam_role" "db_access" {
  count = var.db_access_enabled ? 1 : 0
  name  = "${local.name}-db-access"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "ec2.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy_attachment" "db_access_ssm" {
  count      = var.db_access_enabled ? 1 : 0
  role       = aws_iam_role.db_access[0].name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "db_access" {
  count = var.db_access_enabled ? 1 : 0
  name  = "${local.name}-db-access"
  role  = aws_iam_role.db_access[0].name
}

resource "aws_security_group" "db_access" {
  count       = var.db_access_enabled ? 1 : 0
  name_prefix = "${local.name}-db-access-"
  vpc_id      = aws_vpc.main.id
  description = "Private SSM access node with no inbound connections"
}

resource "aws_vpc_security_group_egress_rule" "db_access_postgres" {
  count                        = var.db_access_enabled ? 1 : 0
  security_group_id            = aws_security_group.db_access[0].id
  referenced_security_group_id = aws_security_group.database.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

resource "aws_vpc_security_group_egress_rule" "db_access_ssm" {
  count             = var.db_access_enabled ? 1 : 0
  security_group_id = aws_security_group.db_access[0].id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  description       = "SSM over the existing private-subnet NAT route"
}

resource "aws_vpc_security_group_ingress_rule" "database_from_db_access" {
  count                        = var.db_access_enabled ? 1 : 0
  security_group_id            = aws_security_group.database.id
  referenced_security_group_id = aws_security_group.db_access[0].id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

resource "aws_instance" "db_access" {
  count                       = var.db_access_enabled ? 1 : 0
  ami                         = data.aws_ssm_parameter.al2023_arm64[0].value
  instance_type               = "t4g.micro"
  subnet_id                   = aws_subnet.private[0].id
  vpc_security_group_ids      = [aws_security_group.db_access[0].id]
  iam_instance_profile        = aws_iam_instance_profile.db_access[0].name
  associate_public_ip_address = false
  metadata_options {
    http_tokens = "required"
  }
  root_block_device {
    encrypted   = true
    volume_type = "gp3"
    volume_size = 8
  }
  tags = { Name = "${local.name}-db-access" }
  depends_on = [
    aws_iam_role_policy_attachment.db_access_ssm,
    aws_vpc_security_group_ingress_rule.database_from_db_access,
    aws_vpc_security_group_egress_rule.db_access_postgres,
    aws_vpc_security_group_egress_rule.db_access_ssm,
  ]
}
