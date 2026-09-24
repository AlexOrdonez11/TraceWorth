resource "aws_lb" "api" {
  name                       = local.name
  internal                   = true
  load_balancer_type         = "application"
  subnets                    = aws_subnet.private[*].id
  security_groups            = [aws_security_group.alb.id]
  drop_invalid_header_fields = true
}
resource "aws_lb_target_group" "api" {
  name                 = local.name
  port                 = 8000
  protocol             = "HTTP"
  target_type          = "ip"
  vpc_id               = aws_vpc.main.id
  deregistration_delay = 30
  health_check {
    path                = "/api/health/ready"
    matcher             = "200"
    interval            = 30
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}
resource "aws_lb_listener" "api" {
  load_balancer_arn = aws_lb.api.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}
resource "aws_cloudfront_vpc_origin" "api" {
  vpc_origin_endpoint_config {
    name                   = local.name
    arn                    = aws_lb.api.arn
    http_port              = 80
    https_port             = 443
    origin_protocol_policy = "http-only"
    origin_ssl_protocols {
      items    = ["TLSv1.2"]
      quantity = 1
    }
  }
  depends_on = [aws_internet_gateway.main, aws_lb_listener.api]
}
data "aws_security_group" "cloudfront" {
  filter {
    name   = "group-name"
    values = ["CloudFront-VPCOrigins-Service-SG*"]
  }
  filter {
    name   = "vpc-id"
    values = [aws_vpc.main.id]
  }
  depends_on = [aws_cloudfront_vpc_origin.api]
}
resource "aws_vpc_security_group_ingress_rule" "cloudfront_alb" {
  security_group_id            = aws_security_group.alb.id
  referenced_security_group_id = data.aws_security_group.cloudfront.id
  ip_protocol                  = "tcp"
  from_port                    = 80
  to_port                      = 80
}
resource "aws_s3_bucket" "dashboard" {
  bucket_prefix = "${local.name}-dashboard-"
  force_destroy = false
}
resource "aws_s3_bucket_public_access_block" "dashboard" {
  bucket                  = aws_s3_bucket.dashboard.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_server_side_encryption_configuration" "dashboard" {
  bucket = aws_s3_bucket.dashboard.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}
resource "aws_s3_bucket_versioning" "dashboard" {
  bucket = aws_s3_bucket.dashboard.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_cloudfront_origin_access_control" "dashboard" {
  name                              = "${local.name}-dashboard"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}
resource "aws_cloudfront_function" "spa" {
  name    = "${local.name}-spa"
  runtime = "cloudfront-js-2.0"
  publish = true
  code    = file("${path.module}/spa.js")
}
data "aws_cloudfront_cache_policy" "static" { name = "Managed-CachingOptimized" }
data "aws_cloudfront_cache_policy" "api" { name = "Managed-CachingDisabled" }
data "aws_cloudfront_origin_request_policy" "api" { name = "Managed-AllViewerExceptHostHeader" }
resource "aws_cloudfront_distribution" "dashboard" {
  enabled             = true
  default_root_object = "index.html"
  comment             = "TraceWorth private staging pilot"
  price_class         = "PriceClass_100"
  is_ipv6_enabled     = false
  web_acl_id          = aws_wafv2_web_acl.pilot.arn
  origin {
    origin_id                = "dashboard"
    domain_name              = aws_s3_bucket.dashboard.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.dashboard.id
  }
  origin {
    origin_id   = "api"
    domain_name = aws_lb.api.dns_name
    vpc_origin_config { vpc_origin_id = aws_cloudfront_vpc_origin.api.id }
  }
  default_cache_behavior {
    target_origin_id       = "dashboard"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    cache_policy_id        = data.aws_cloudfront_cache_policy.static.id
    compress               = true
    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.spa.arn
    }
  }
  dynamic "ordered_cache_behavior" {
    for_each = ["/api/*", "/api"]
    content {
      path_pattern             = ordered_cache_behavior.value
      target_origin_id         = "api"
      viewer_protocol_policy   = "https-only"
      allowed_methods          = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
      cached_methods           = ["GET", "HEAD"]
      cache_policy_id          = data.aws_cloudfront_cache_policy.api.id
      origin_request_policy_id = data.aws_cloudfront_origin_request_policy.api.id
      compress                 = true
    }
  }
  restrictions {
    geo_restriction { restriction_type = "none" }
  }
  viewer_certificate { cloudfront_default_certificate = true }
  depends_on = [aws_vpc_security_group_ingress_rule.cloudfront_alb]
}
resource "aws_s3_bucket_policy" "dashboard" {
  bucket = aws_s3_bucket.dashboard.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow", Principal = { Service = "cloudfront.amazonaws.com" },
        Action    = "s3:GetObject", Resource = "${aws_s3_bucket.dashboard.arn}/*",
        Condition = { StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.dashboard.arn } }
      },
      {
        Effect    = "Deny", Principal = "*", Action = "s3:*",
        Resource  = [aws_s3_bucket.dashboard.arn, "${aws_s3_bucket.dashboard.arn}/*"],
        Condition = { Bool = { "aws:SecureTransport" = "false" } }
      }
    ]
  })
}
resource "aws_wafv2_ip_set" "pilot" {
  provider           = aws.edge
  name               = "${local.name}-pilot"
  scope              = "CLOUDFRONT"
  ip_address_version = "IPV4"
  addresses          = var.pilot_ipv4_cidrs
}
resource "aws_wafv2_web_acl" "pilot" {
  provider = aws.edge
  name     = local.name
  scope    = "CLOUDFRONT"
  default_action {
    block {}
  }
  rule {
    name     = "PilotRateLimit"
    priority = 0
    action {
      block {}
    }
    statement {
      rate_based_statement {
        limit                 = var.edge_requests_per_five_minutes
        aggregate_key_type    = "IP"
        evaluation_window_sec = 300
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "PilotRateLimit"
      sampled_requests_enabled   = false
    }
  }
  rule {
    name     = "AllowedPilotAddresses"
    priority = 1
    action {
      allow {}
    }
    statement {
      ip_set_reference_statement { arn = aws_wafv2_ip_set.pilot.arn }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "AllowedPilotAddresses"
      sampled_requests_enabled   = false
    }
  }
  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = local.name
    sampled_requests_enabled   = false
  }
}
