# AWS staging pilot: MyHandyAI + TraceWorth

Planning baseline updated September 24, 2026. Proposed infrastructure, not provisioned.
MyHandyAI uses Python on AWS Lambda, as confirmed by the owner. Its repository,
AWS region, networking, and traffic volume have not yet been inspected.
Use the same AWS region as its staging backend. The
recommended architecture assumes a small, team-only pilot, not public SaaS.

## Preparation checklist: generated CloudFront domain

This is the selected first deployment variant. It supersedes the custom-domain
examples below until a business domain is available.

Prepare now:

- AWS account with a monitored owner email, root MFA, billing contact and payment
  method. Use administrative role access for daily work, not root access keys.
  For Identity Center AWS-account permission sets, use an organization instance;
  an account instance does not provide AWS account access.
- Confirm MyHandyAI staging's AWS region, account, Python runtime, function names,
  deployment tool, VPC attachment and outbound HTTPS access. Record whether
  responses stream and whether work continues in separate functions/queues.
- Choose that region for TraceWorth, and tag resources Project=TraceWorth,
  Environment=staging, Owner=Alex. Confirm VPC CIDRs before creation.
- Set monthly actual-spend alerts at $100, $150 and $200, plus a forecast alert
  against a $300 pilot budget. Notifications do not cap AWS spending.
- Install AWS CLI v2, Docker and Terraform; configure temporary administrative
  credentials. Verify the target account with `aws sts get-caller-identity`.
  Never send root credentials or access keys through chat.

Provision with infrastructure as code after cloud compatibility is implemented:

- One VPC across two AZs; two public subnets for NAT placement and two private
  subnets for the internal ALB, API tasks and database subnet group. One NAT for
  this staging pilot accepts an AZ dependency; no public task/database IPs.
- One internal ALB as a CloudFront VPC origin, with IP targets for Fargate.
  CloudFront is the public entry; ALB accepts only CloudFront-origin traffic,
  task port 8000 only accepts the ALB security group, and database port 5432
  only accepts the API/migration security group. Follow AWS VPC-origin ENI,
  security-group, IPv4 and internet-gateway prerequisites.
- One Fargate service (initial profiling size 0.5 vCPU / 1 GiB), ECR repository,
  separate execution/task IAM roles, and controlled database migration job.
- RDS PostgreSQL Single-AZ, initial db.t4g.micro or small after memory checks,
  20 GiB gp3, encryption, TLS database connections, no public access, seven-day
  backups and deletion protection. Do not select Extended Support engines.
- Private dashboard S3 bucket with Block Public Access and CloudFront OAC.
  CloudFront default hostname/TLS certificate; `/api/*` goes to the VPC origin,
  caching disabled, forwarding required auth/cookies/CSRF/origin/query values.
  No Route 53 hosted zone, domain registration or viewer ACM certificate needed.
- For this no-domain pilot, explicitly configure HTTP on the private
  CloudFront-to-ALB origin hop. Viewer/SDK connections use HTTPS; this is not
  end-to-end TLS. If policy requires TLS on that private hop, obtain a suitable
  origin hostname/certificate before deployment. CloudFront's default viewer
  certificate cannot be installed on the ALB.
- Secrets Manager entries for DB credentials and the application ingestion key;
  CloudWatch log group with 14-day retention and alarms for errors, unhealthy
  tasks, database capacity and failed/dropped telemetry. Separate website
  bucket/distribution can follow; it is not needed to test MyHandyAI ingestion.

Cloud code gates remain: PostgreSQL/migrations, container entrypoint, readiness,
secure-cookie configuration independent of the private HTTP origin hop, trusted
proxy handling, admin bootstrap/disabled public registration, bounded metrics,
retention, and Lambda invocation-aware delivery. Current local code does not
provide these deployment capabilities. Do not create idle billable compute,
ALB, NAT and database resources before the deployable build is ready.

References:
[CloudFront VPC origins](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-vpc-origins.html),
[Identity Center instance types](https://docs.aws.amazon.com/singlesignon/latest/userguide/identity-center-instances.html),
[Fargate networking](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fargate-tasks-services.html).

## Recommended resources

| Resource | Initial purpose/configuration |
| --- | --- |
| ECS Fargate | TraceWorth FastAPI service; initially one task, 0.5 vCPU / 1 GiB as a profiling starting point, not a capacity guarantee |
| ECR | Versioned container images pinned by digest for deploy/rollback |
| Application Load Balancer | HTTPS entry to API; IP target group, readiness health check; tasks accept traffic only from its security group |
| RDS PostgreSQL | Authoritative accounts, users, sessions, applications, hashed keys, event payloads; small general-purpose instance, encrypted gp3 storage, private subnets |
| S3 + CloudFront | Separate private buckets/builds for React dashboard and website; origin access control and Block Public Access |
| Secrets Manager | Database credentials and MyHandyAI's TraceWorth ingestion key; scoped IAM access |
| CloudWatch | Operational logs, ingestion/export counts, latency, errors, database/task alarms; explicit retention |
| Route 53 + ACM | Example app.stage.your-domain and www.stage.your-domain with HTTPS |
| VPC/security groups | Public ALB subnets and private task/database subnets spanning two AZs; controlled outbound connectivity |
| AWS Budgets | Pilot cost alerts; alerts do not enforce a spending cap |

Use an existing suitable staging VPC rather than automatically duplicating NAT
and network resources. Private tasks need a deliberate egress plan for ECR,
CloudWatch and Secrets Manager: existing NAT or appropriate VPC endpoints.
Compare their regional cost before provisioning. A new NAT gateway, ALB and RDS
can dominate the cost of a quiet staging pilot.

RDS Single-AZ is acceptable if the team accepts staging outages and restore time.
Use Multi-AZ if staging availability matters. A subnet group spanning two AZs does
not itself make a Single-AZ database highly available. Size compute/storage after
measuring actual event rates and report memory use.

## Request and storage paths

```text
MyHandyAI staging backend
  -> TraceWorth Python SDK (scoped ingestion key)
  -> HTTPS app.stage.your-domain/api/events
  -> CloudFront /api/* -> ALB -> FastAPI on Fargate
  -> RDS PostgreSQL

Team browser -> app.stage.your-domain
  /       -> CloudFront -> private dashboard S3 bucket
  /api/*  -> CloudFront -> ALB -> same FastAPI API

Website -> separate CloudFront distribution + private website S3 bucket
```

Keep dashboard and API on the same browser origin, preserving the frontend's
relative `/api` calls and cookie flow. `/api/*` must allow required HTTP methods,
disable caching entirely, and forward Authorization, cookies, CSRF/Origin headers
and query strings. Preserve the path. Do not apply an SPA fallback to API errors.
Only static routes should fall back to index.html. Protect the ALB from bypass
of the approved entry path; restrict staging access to team/test-runner and
MyHandyAI staging egress addresses using a deliberate edge/network policy.
If MyHandyAI already has private connectivity, evaluate an internal ingestion
path separately rather than making PostgreSQL public.

The database stores relational ownership columns plus the original validated
event body as JSONB, indexed by account, application, environment and time. Keep
the unique (account_id, application_id, event_id) replay constraint. Do not use
MyHandyAI's operational database for TraceWorth telemetry.

S3 stores frontend artifacts. An optional separate S3 bucket can later store
compressed immutable event exports for replay/archive. S3 is not the live metrics
query store in this design. There is no implemented archive exporter yet.
CloudWatch stores service diagnostics, not the sole copy of telemetry. RDS
automated backups restore the database; they are different from event exports.
Proposed pilot policy: 30 days of telemetry, 14 days of operational logs, 7 days
of database backups. Implement deletion and restore tests before claiming these
retention periods are enforced.

## Ordered rollout

1. **Inventory MyHandyAI staging.** Record region, deployment runtime, Python
   version/provider libraries, concurrency, expected workflows/day, outbound
   access and whether streaming/background jobs exist. Select one meaningful
   workflow and its acceptance signal. Do not instrument every method initially.

2. **Make TraceWorth deployable.** Add PostgreSQL persistence and migrations
   (e.g. SQLAlchemy/Alembic), connection pooling and TLS verification. Preserve
   SQLite for local use. Rerun ownership, atomic batch and replay tests against
   PostgreSQL. Add a non-root container, environment-based settings, cloud
   entrypoint bound to 0.0.0.0, separate liveness/readiness and graceful shutdown.
   The existing CLI deliberately binds loopback and is not that entrypoint.

3. **Close staging exposure gaps.** Disable public registration and synthetic
   seeding in cloud mode; provide an explicit admin bootstrap for the pilot
   owner. Restrict access to the pilot team and application. Configure Secure
   cookies, exact origins, CSRF and trusted proxy handling through CloudFront/ALB;
   don't blindly trust forwarded IP headers. Current authentication throttling
   is process-local and must not be represented as a shared distributed limit.
   Add ingestion quotas/rate limits. Public self-service access requires a
   separate identity lifecycle decision (Cognito is an option, not integrated).

4. **Bound stored-data processing.** The current metrics endpoint loads all
   account events into memory. Add server-side time windows, query limits and
   pagination before a sustained staging feed. Preserve complete workflow
   boundaries or explicitly mark truncated/incomplete data. Add retention jobs.

5. **Provision with infrastructure as code.** Define the VPC bindings, IAM,
   ECR/ECS/ALB, private RDS, buckets/distributions, secrets, DNS/TLS, alarms and
   budgets in Terraform or CDK. Use separate staging state/secrets. A CloudFront
   viewer certificate belongs in us-east-1; regional ALB certificates belong
   with the ALB. CI uses short-lived AWS credentials/OIDC and least privilege.

6. **Deploy TraceWorth first.** Build/test image and React artifacts, run DB
   migrations as a controlled job, deploy one API task, and verify HTTPS health,
   account auth, no cached private responses and database persistence across
   task replacement. Test backup restore to a separate database. Link the
   website to the deployed dashboard using its build-time configuration.

7. **Register the pilot.** Create a pilot account and application slug
   `myhandyai-stage`. Generate an ingestion-only key and store it in Secrets
   Manager, accessible only to MyHandyAI's staging execution identity. Never put
   the key in React, a repository, image layer, or logs. Keep production separate.

8. **Integrate one staging workflow.** Pin the TraceWorth package revision in
   MyHandyAI's deployment. Configure endpoint, application, environment=staging,
   configuration_id=release identifier and the secret key. Construct one SDK
   client per worker process after forking; flush/close on graceful shutdown.
   Decorate the selected workflow, add spans around provider/retrieval/tool
   calls, record usage from actual responses, and explicit retries/outcomes.
   For async/background workers, define lifecycle and cross-job correlation.
   Lambda needs a separate flush/lifecycle design; an unflushed background
   thread cannot be assumed to run after an invocation returns.

9. **Run controlled cases.** Execute known successful, failed, retried and
   cancelled requests; include unknown costs and missing acceptance. Compare
   counts and quantities against an independent staging execution log and
   provider response usage. Do not infer prices or capture prompts, arguments,
   customer addresses or outputs by default. Test a second account cannot read
   the pilot's data and revoke a throwaway ingestion key.

10. **Measure failure behavior and expand gradually.** Simulate API outage,
    throttling, task replacement and application shutdown; measure SDK queue
    drops/export_errors and application latency. Current HTTP export is best
    effort with no retries/spool: loss during those tests is expected and must
    be quantified. Add batching, backoff and a bounded durable spool before
    relying on completeness. Start with controlled test traffic, then a small
    staging cohort, then broader staging only after results are understood.

## Pilot acceptance

- Unchanged MyHandyAI return values, exceptions and cancellation semantics.
- Agreed overhead and telemetry-loss thresholds, measured before/after.
- Known test workflow/usage counts reconcile; absent prices remain unknown.
- Correct environment/release labels; real telemetry separated from synthetic.
- Account isolation, key revocation, HTTPS/proxy/cookie flow and task-replacement
  persistence pass against the deployed stack.
- Report time windows, retention, alarms and a database restore are exercised.
- Rollback: disable the MyHandyAI integration through application configuration,
  revoke its key if necessary and redeploy the pinned previous application image.

No Kubernetes, warehouse, Kafka, OpenSearch or Databricks is required for this
pilot. Add a queue/worker only once durable ingestion and measured volume justify
its delivery and processing semantics.

## AWS references checked

- [ECS Application Load Balancer integration](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/alb.html)
- [Private S3 origins with CloudFront OAC](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-restricting-access-to-s3.html)
- [CloudFront cache policies](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/using-managed-cache-policies.html)
- [Forwarding authorization](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/http-401-unauthorized.html)
- [RDS encryption](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Overview.Encryption.html)
- [RDS backup retention](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_WorkingWithAutomatedBackups.BackupRetention.html)
- [ECS Secrets Manager injection](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/secrets-envvar-secrets-manager.html)

Injected ECS secrets require task replacement to pick up a rotated value; plan
key rotation as create new key, deploy consumers, verify, revoke old key.
