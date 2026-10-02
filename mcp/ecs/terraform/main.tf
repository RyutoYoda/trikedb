terraform {
  required_version = ">= 1.5"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 6.0" }
    random = { source = "hashicorp/random", version = "~> 3.7" }
  }
}
provider "aws" {
  region              = var.region
  allowed_account_ids = [var.aws_account_id]
  default_tags { tags = { Application = "trikedb", ManagedBy = "terraform" } }
}
resource "random_id" "suffix" { byte_length = 4 }
locals {
  name  = "trikedb-${random_id.suffix.hex}"
  graph = "graphs/team.yaml"
  trust = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "ecs-tasks.amazonaws.com" }, Condition = { StringEquals = { "aws:SourceAccount" = var.aws_account_id } } }] })
}
resource "aws_s3_bucket" "graph" {
  bucket_prefix = "${local.name}-"
  force_destroy = var.allow_destroy_graph
}
resource "aws_s3_bucket_public_access_block" "graph" {
  bucket                  = aws_s3_bucket.graph.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_versioning" "graph" {
  bucket = aws_s3_bucket.graph.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_server_side_encryption_configuration" "graph" {
  bucket = aws_s3_bucket.graph.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}
resource "aws_ecr_repository" "image" {
  name         = local.name
  force_delete = var.allow_destroy_graph
}
resource "aws_cloudwatch_log_group" "server" {
  name              = "/ecs/${local.name}"
  retention_in_days = 7
}
resource "aws_iam_role" "execution" {
  name               = "${local.name}-execution"
  assume_role_policy = local.trust
}
resource "aws_iam_role_policy" "execution" {
  role = aws_iam_role.execution.id
  policy = jsonencode({ Version = "2012-10-17", Statement = concat([
    { Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*" },
    { Effect = "Allow", Action = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability"], Resource = aws_ecr_repository.image.arn },
    { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.server.arn}:*" }
    ], var.bearer_secret_arn == "" ? [] : [
    { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = var.bearer_secret_arn }
    ], length(var.kms_key_arns) == 0 ? [] : [
    { Effect = "Allow", Action = ["kms:Decrypt"], Resource = var.kms_key_arns }
  ]) })
}
resource "aws_iam_role" "task" {
  name               = "${local.name}-task"
  assume_role_policy = local.trust
}
resource "aws_iam_role_policy" "task" {
  role = aws_iam_role.task.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["s3:ListBucket"], Resource = aws_s3_bucket.graph.arn, Condition = { StringLike = { "s3:prefix" = ["graphs", "graphs/*"] } } },
    { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject"], Resource = "${aws_s3_bucket.graph.arn}/${local.graph}" }
  ] })
}
resource "aws_security_group" "alb" {
  name   = "${local.name}-alb"
  vpc_id = local.vpc_id
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = var.allowed_cidrs
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
resource "aws_security_group" "task" {
  name   = "${local.name}-task"
  vpc_id = local.vpc_id
  ingress {
    from_port       = 8080
    to_port         = 8080
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
resource "aws_ecs_cluster" "server" { name = local.name }
resource "aws_ecs_task_definition" "server" {
  family                   = local.name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn
  runtime_platform {
    cpu_architecture        = var.cpu_architecture
    operating_system_family = "LINUX"
  }
  container_definitions = jsonencode([{
    name         = "trikedb", image = "${aws_ecr_repository.image.repository_url}:${var.image_tag}", essential = true,
    portMappings = [{ containerPort = 8080, protocol = "tcp" }],
    environment = concat([{ name = "TRIKEDB_GRAPH_URL", value = "s3://${aws_s3_bucket.graph.id}/${local.graph}" }],
      var.public_url == "" ? [] : [{ name = "TRIKEDB_PUBLIC_URL", value = var.public_url }],
    var.oauth_issuer == "" ? [] : [{ name = "TRIKEDB_OAUTH_ISSUER", value = var.oauth_issuer }]),
    secrets = var.bearer_secret_arn == "" ? [] : [{ name = "TRIKEDB_TOKEN", valueFrom = var.bearer_secret_arn }],
    logConfiguration = { logDriver = "awslogs", options = {
      awslogs-group = aws_cloudwatch_log_group.server.name, awslogs-region = var.region, awslogs-stream-prefix = "server"
    } }
  }])
}
resource "aws_lb" "server" {
  count              = var.create_service ? 1 : 0
  name               = local.name
  load_balancer_type = "application"
  internal           = false
  security_groups    = [aws_security_group.alb.id]
  subnets            = local.alb_subnet_ids
  idle_timeout       = 300
  lifecycle {
    precondition {
      condition     = length(local.alb_subnet_ids) >= 2 && var.certificate_arn != "" && startswith(var.public_url, "https://") && (var.bearer_secret_arn != "" || var.oauth_issuer != "")
      error_message = "Service requires two ALB subnets, ACM certificate, public HTTPS URL and bearer secret ARN or OAuth issuer."
    }
  }
}
resource "aws_lb_target_group" "server" {
  count       = var.create_service ? 1 : 0
  name        = local.name
  port        = 8080
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = local.vpc_id
  health_check {
    path    = "/"
    matcher = "401"
  }
}
resource "aws_lb_listener" "https" {
  count             = var.create_service ? 1 : 0
  load_balancer_arn = aws_lb.server[0].arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.server[0].arn
  }
}
resource "aws_ecs_service" "server" {
  count           = var.create_service ? 1 : 0
  name            = local.name
  cluster         = aws_ecs_cluster.server.id
  task_definition = aws_ecs_task_definition.server.arn
  launch_type     = "FARGATE"
  desired_count   = 1
  depends_on      = [aws_lb_listener.https, aws_iam_role_policy.execution, aws_iam_role_policy.task]
  network_configuration {
    subnets          = local.task_subnet_ids
    security_groups  = [aws_security_group.task.id]
    assign_public_ip = local.assign_public_ip
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.server[0].arn
    container_name   = "trikedb"
    container_port   = 8080
  }
}
