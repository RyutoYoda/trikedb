# Default: own VPC and two public subnets. No existing endpoints or routing change.
# Fargate has public egress, but task ingress is restricted to the HTTPS ALB SG.
data "aws_availability_zones" "available" { state = "available" }
locals {
  create_vpc       = var.vpc_id == ""
  vpc_id           = local.create_vpc ? aws_vpc.dedicated[0].id : var.vpc_id
  task_subnet_ids  = local.create_vpc ? aws_subnet.public[*].id : var.task_subnet_ids
  alb_subnet_ids   = local.create_vpc ? aws_subnet.public[*].id : var.alb_subnet_ids
  assign_public_ip = local.create_vpc || var.assign_public_ip
}
resource "aws_vpc" "dedicated" {
  count                = local.create_vpc ? 1 : 0
  cidr_block           = "10.240.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = local.name }
}
resource "aws_internet_gateway" "dedicated" {
  count  = local.create_vpc ? 1 : 0
  vpc_id = aws_vpc.dedicated[0].id
}
resource "aws_subnet" "public" {
  count                   = local.create_vpc ? 2 : 0
  vpc_id                  = aws_vpc.dedicated[0].id
  cidr_block              = cidrsubnet(aws_vpc.dedicated[0].cidr_block, 8, count.index)
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = true
}
resource "aws_route_table" "public" {
  count  = local.create_vpc ? 1 : 0
  vpc_id = aws_vpc.dedicated[0].id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.dedicated[0].id
  }
}
resource "aws_route_table_association" "public" {
  count          = local.create_vpc ? 2 : 0
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public[0].id
}
