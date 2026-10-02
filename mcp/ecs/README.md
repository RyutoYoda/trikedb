# Shared remote MCP on ECS + S3

This optional deployment is for teams that want a shared remote MCP endpoint.
A local Python/CLI user only needs `pip install trikedb`. These deployment files
are distributed on GitHub, not inside the PyPI wheel or source distribution.

The server stores the graph as YAML in a **private S3 object**, using the ECS task
role. No YAML or AWS credentials are baked into the image. `/mcp` provides
Streamable HTTP, `/sparql` provides REST, and `/` provides the graph UI. A bearer
token or external OAuth issuer is mandatory in this container entrypoint.
The shared browser-connector example below uses OAuth.

## Build

Run from this directory after installing Docker:

```bash
docker build --platform linux/arm64 -t trikedb:0.36.0 .
```

Use `linux/amd64` and `X86_64` in the task definition for x86 Fargate. The image
runs as UID 10001 and installs `trikedb[serve,remote,oauth]==0.36.0` from PyPI.
The optional `wheel` target is for maintainers testing an unreleased wheel;
normal users do not need a `dist/` directory.

## Deploy

For a reproducible deployment, use the [Terraform module](terraform/README.md).
It creates dedicated ECS/S3/ECR/IAM resources in your selected account, with an
optional HTTPS ALB, and defaults to a dedicated VPC. The steps below describe
the equivalent manual setup. 構成を先に把握したい場合は、[サンプルアーキテクチャ](ARCHITECTURE.md)を参照してください。

1. Choose your own AWS account and region. Create a private S3 bucket with Block
   Public Access enabled. Use a unique object key such as `graphs/team.yaml`.
   The object is created on the first write; optionally upload an initial graph:

   ```bash
   aws s3 cp team.yaml s3://YOUR_PRIVATE_BUCKET/graphs/team.yaml
   ```

2. Create an ECR repository and push the image. These placeholders deliberately
   contain no organization-specific settings:

   ```bash
   aws ecr create-repository --repository-name trikedb --region YOUR_REGION
   aws ecr get-login-password --region YOUR_REGION | docker login --username AWS --password-stdin YOUR_ACCOUNT_ID.dkr.ecr.YOUR_REGION.amazonaws.com
   docker tag trikedb:0.36.0 YOUR_ACCOUNT_ID.dkr.ecr.YOUR_REGION.amazonaws.com/trikedb:0.36.0
   docker push YOUR_ACCOUNT_ID.dkr.ecr.YOUR_REGION.amazonaws.com/trikedb:0.36.0
   ```

3. Create an ECS task role trusting `ecs-tasks.amazonaws.com`, and substitute your
   bucket in `task-role-policy.json`. Attach that policy to the **task role**.
   The separate **execution role** needs ECR pull and CloudWatch Logs permissions
   (`AmazonECSTaskExecutionRolePolicy`). For a customer-managed S3 KMS key,
   add narrowly scoped `kms:Decrypt` and `kms:GenerateDataKey` as required.

4. Configure an OAuth issuer you operate (for example, Keycloak, Auth0 or Entra).
   It must expose discovery metadata and JWKS and issue signed JWT access tokens
   whose audience is your exact MCP URL, such as `https://kg.example.com/mcp`.
   Register the client using the callback URL shown by ChatGPT or Claude, enable
   authorization code flow with PKCE, and supply its client ID in the connector.
   TrikeDB verifies tokens; it does not provide a login service or OAuth clients.
   Create the CloudWatch log group `/ecs/trikedb`. Fill in
   `task-definition.json` (image, roles, region, bucket, HTTPS URL and OAuth issuer):

   ```bash
   aws ecs register-task-definition --cli-input-json file://task-definition.json --region YOUR_REGION
   ```

5. Create a Fargate service with **desired count 1**, an ALB target group of type
   **IP**, and container port 8080. Use private subnets with NAT or the necessary
   ECR/S3/Logs/Secrets endpoints. Task ingress should allow only the ALB security
   group. Attach an HTTPS listener using your own ACM certificate; point your DNS
   name at that ALB and match it to `TRIKEDB_PUBLIC_URL`. Allow outbound access to
   S3 and the required AWS endpoints. Use `/` as the target-group health check
   with matcher **401**: the load balancer does not send the bearer token. This
   checks liveness, not authenticated graph readiness; verify readiness below.

## Verify and connect

1. In ChatGPT developer mode or Claude's custom connector settings, add
   `https://kg.example.com/mcp` with **OAuth**, then configure the OAuth client
   registered at your issuer. Availability depends on your workspace permissions.
   Complete the issuer's login/consent flow. Do not paste an access token into
   the URL or choose the static-token option for this OAuth setup.
2. Confirm the connector discovers the graph tools. Ask it to run
   `SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 5`, then authorize a synthetic write
   such as `INSERT DATA {t:example t:USES t:trikedb}` and verify it with
   `ASK {t:example t:USES t:trikedb}`.
3. Read the S3 YAML independently, replace the ECS task, and run the ASK again.
   Test an unauthenticated request too: `/mcp` must reject it with HTTP 401 and
   advertise the protected-resource metadata URL.

The issuer, its users/clients, DNS and ACM certificate are supplied separately;
Terraform does not create or remove those existing resources. For a disposable
OAuth test, create a separate issuer/client and remove it explicitly afterward.
OAuth authorization grants access to this graph as a whole; this example does
not implement per-user graph partitions or separate read/write roles.

For diagnostics, an OAuth **access token issued for this MCP resource** can be
used with REST; keep it out of source control, command arguments and logs:

```bash
curl -fsS https://kg.example.com/sparql \
  -H "Authorization: Bearer $ACCESS_TOKEN" -H 'Content-Type: application/json' \
  -d '{"query":"ASK {t:example t:USES t:trikedb}"}'
```

A static-token setup remains available for script clients via `TRIKEDB_TOKEN`
and `bearer_secret_arn`; it is separate from the OAuth browser setup above.

## Operations and limits

- Each process caches its graph. Keep one service replica for coherent reads.
  S3 conditional writes reject stale data; MCP retries by reload/reapply, but
  retries are bounded and not guaranteed to succeed under endless contention.
  REST does not automatically retry a conflicting update.
- An external S3 overwrite needs a server restart or explicit reload. Separate
  replicas can return stale reads even when write conflicts are protected.
- Do not expose bearer-token HTTP directly to the internet; terminate TLS at
  the ALB. The HTML UI loads JavaScript/WASM from public CDNs.
- S3 bucket versioning is an optional recovery layer, not a substitute for CAS.
  Grant each deployment only its own bucket/prefix. Token rotation requires an
  ECS task replacement so the environment receives the new secret value.

## Test evidence and teardown

The release candidate was exercised on Linux ARM64 ECS Fargate against a real
private S3 bucket: typed RDF save/reload, stale-write rejection, authenticated
MCP and REST, ten concurrent writes, two independent server processes, and
restart persistence. These checks used real TCP inside the isolated task.
A second test provisioned the dedicated VPC and HTTPS ALB service, injected a
bearer secret through Secrets Manager, and called MCP from an external client.
It verified TLS, unauthorized access rejection, tool calls, independent S3 YAML
readback, and persistence after ECS task replacement. That test used an imported
test certificate trusted explicitly by the client and a client-side DNS mapping;
it does not establish compatibility with public DNS or a SaaS OAuth login.
A separate browser login against a disposable Keycloak issuer completed the
authorization-code/PKCE flow and authenticated an independent MCP SDK client,
which listed 11 tools and ran a SPARQL query. This is not proof of a successful
ChatGPT or Claude connector registration; that UI check is still incomplete.
All test-created AWS resources were removed and their absence verified.

For your own temporary deployment: delete the ECS service and wait for tasks to
stop; remove its ALB/listeners/target group, task definitions, dedicated security
groups, ECR images/repository, log group, and dedicated IAM roles/policies.
Delete the secret according to your organization's recovery policy. Delete the
S3 graph/bucket only if it is disposable; with versioning enabled, remove old
versions and delete markers too. Never apply teardown to shared infrastructure.

No CI or automatic deployment pipeline is included.
