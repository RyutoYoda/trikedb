# Terraform deployment

This module creates dedicated S3 storage (private, encrypted, versioned), ECR,
ECS/Fargate, log group and narrowly scoped IAM roles. With `create_service=true`
it also creates an HTTPS ALB and a single-replica ECS service. By default it creates a dedicated VPC, internet gateway and two public subnets;
only the ALB can reach the task port. An existing VPC/subnets can be supplied
instead and are then **not managed or deleted**. ACM certificate and Secrets
Manager secret are supplied by the caller; DNS is configured separately.

1. Install Terraform >=1.5 and authenticate AWS outside the project (SSO or your
   normal credential chain). Copy `terraform.tfvars.example` to
   `terraform.tfvars`, replacing every placeholder. The provider refuses an
   account different from `aws_account_id`. Keep `create_service=false` first.
   For an existing VPC, supply task subnets with NAT or working AWS endpoints.
   Private-DNS endpoints (especially Secrets Manager) must allow connections
   from the new task security group; otherwise tasks fail before starting.
   The default dedicated VPC avoids dependencies on existing endpoints.
2. Initialize, inspect the plan, then provision the bootstrap resources:

   ```bash
   terraform init
   terraform plan -out=bootstrap.tfplan
   terraform apply bootstrap.tfplan
   terraform output -raw repository_url
   ```

3. Build the parent directory's Dockerfile and push `:0.36.0` to that repository
   using ECR login, as shown in the parent README. ARM64 is the default; match
   `cpu_architecture` to the image platform. The source bucket/key is available
   from `terraform output -raw graph_url`.
4. Set your external OAuth issuer, public HTTPS URL, and ACM
   certificate ARN. Supply two public ALB subnets in different AZs only when
   reusing an existing VPC. Change
   `create_service=true`, inspect another plan and apply it. Point your public
   hostname to `terraform output -raw alb_dns_name`. This module does not create
   plaintext public HTTP listeners.
5. Wait for the ECS service to stabilize, then perform the authenticated
   INSERT/ASK and restart/readback checks in the parent README. The ALB's
   unauthenticated `/` probe intentionally expects 401, so it checks liveness
   only. Verify authenticated readiness separately.

`terraform.tfvars`, state and saved plans are ignored by git. State contains
infrastructure identifiers, and can contain sensitive values in future changes;
keep it in private storage with suitable access controls. Do not commit test
account identifiers, token values, AWS credentials or state files. The bearer
secret is referenced by ARN; its value never enters this module or state.

For shared operations, configure a private remote Terraform backend with state
locking according to your organization's practices; no organization-specific
backend is provided here. No CI is created.

## Teardown

For a disposable test, explicitly set `allow_destroy_graph=true` before apply;
then `terraform destroy` can empty the graph bucket (including versions) and
remove the ECR repository even if it has images. For real data keep it false:
Terraform will refuse to delete nonempty S3/ECR resources. Archive data or
remove those resources from management deliberately before teardown; never
silently enable destructive deletion on a production graph.

Standalone tasks started with `aws ecs run-task` are outside Terraform's service
state. Stop them and wait for STOPPED before destroying. After destroy, verify
there are no running tasks, owned buckets/repositories, roles or security groups, and no dedicated VPC,
subnets, route table or internet gateway.
Deregistered task-definition and stopped-task history can remain visible in AWS.

## Verification boundary

The module's bootstrap resources, Docker entrypoint, real S3 YAML and real TCP
MCP/REST were exercised in a disposable Fargate task and removed afterward.
The dedicated VPC and HTTPS ALB service were also deployed and exercised from
an external MCP client, including Secrets Manager injection, S3 readback and
ECS task replacement. The client explicitly trusted the imported test
certificate and mapped its hostname to the ALB; public DNS and SaaS OAuth login
are separate checks. All test-owned AWS resources were removed and independently
checked through AWS APIs. Test your own certificate, DNS and OAuth provider
before inviting users.
