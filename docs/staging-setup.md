# Staging preparation: Docker, PostgreSQL and Terraform

This milestone prepares deployment files and local acceptance evidence. It does
not deploy TraceWorth or connect MyHandyAI. AWS is the destination for TraceWorth;
the SDK remains independent of where the caller runs.

## The pieces in plain language

| Piece | Why TraceWorth needs it | Where data goes |
| --- | --- | --- |
| Docker image | Packages Python, FastAPI and the backend into one runnable release | Application code, never account data or credentials |
| PostgreSQL / RDS | Keeps account ownership, sessions, hashed keys and recorded events after a container restarts | Encrypted private RDS storage; local Docker volume for rehearsal |
| ECS Fargate | Runs the backend container without managing a server | Stateless compute |
| ECR | Stores versioned container images | Built images pinned by digest |
| Internal ALB | Sends CloudFront API requests to healthy containers | Request traffic only |
| S3 + CloudFront | Serves the React dashboard and routes `/api/*` to the backend | Static frontend files in private S3 |
| Secrets Manager | Supplies database credentials when a task starts | Runtime login, admin login, temporary owner-bootstrap password |
| CloudWatch + SNS | Keeps logs and sends operational alarms | Fourteen-day application logs and alarm metrics |
| VPC, subnets and NAT | Keep the database/API private while permitting required outbound AWS connections | Network infrastructure |
| WAF | Restricts this pilot to approved public IPs and limits bursts | Access policy, not the application database |

The marketing website remains a separate React application. The first cloud
pilot deploys the dashboard; a separate website bucket/distribution can follow.
The generated `https://…cloudfront.net` address works without buying a domain.

## Rehearse locally first

Docker Desktop must be running Linux containers. From the repository root in
PowerShell, generate a fresh password for this disposable local stack only:

```powershell
$env:TRACEWORTH_COMPOSE_DB_PASSWORD = [Guid]::NewGuid().ToString('N') + [Guid]::NewGuid().ToString('N')
docker compose up -d postgres
docker compose build
docker compose run --rm migrate
docker compose up -d api
Invoke-RestMethod http://127.0.0.1:18000/api/health/ready
```

Stop if a command fails. An uninitialized database is deliberately not ready;
run the migration command before starting the API. Keep the same generated
password in this shell when restarting this stack: an existing PostgreSQL
volume does not adopt a new `POSTGRES_PASSWORD`. If you want to keep this local
stack across shell sessions, save the generated value in an ignored root `.env`
as `TRACEWORTH_COMPOSE_DB_PASSWORD=…`. Do not reuse real credentials.

Start the React dashboard in another terminal, pointing its development proxy
at this container instead of the legacy SQLite API:

```powershell
$env:TRACEWORTH_DEV_API_TARGET = 'http://127.0.0.1:18000'
npm run dev:dashboard
```

Open `http://127.0.0.1:18767`. This local rehearsal permits registration and
explicit synthetic demo seeding. It uses plaintext PostgreSQL only on the local
Docker network and maps ports only to loopback; it is not the cloud TLS test.
`docker compose restart api` preserves data in the named PostgreSQL volume.
`docker compose down` stops this stack and retains the volume. Avoid `down -v`
unless you intentionally want to erase this rehearsal database. Existing
`local-data/traceworth.db` is untouched.

If a port is occupied, set `TRACEWORTH_COMPOSE_API_PORT` or
`TRACEWORTH_COMPOSE_DB_PORT` before starting Compose, and update the frontend
proxy target to match. The default API port is 18000, database port 15432.

Run backend acceptance with `pip install -e '.[backend,postgres,test]'` in the
repository virtual environment. PostgreSQL-specific tests require a disposable
server with permission to create test databases; see `tests/test_postgres.py`.

## Terraform: the commands you will use

Terraform configuration (`.tf` files) describes the resources you want. State
records which real AWS resources correspond to those definitions. Treat state
as sensitive even when passwords are absent: it includes infrastructure details.

1. `terraform init` installs the AWS provider and configures state storage.
2. `terraform fmt` formats files; `terraform validate` checks their structure.
3. `terraform plan -out=staging.tfplan` reads AWS and saves the proposed changes.
4. `terraform show staging.tfplan` lets us review those exact changes.
5. `terraform apply staging.tfplan` creates/changes the reviewed resources and
   starts billing for billable resources. We will review the plan together first.

Never use `apply -auto-approve` as a shortcut during this first deployment.
Do not run `destroy` on the database or state bucket as routine cleanup.

## Prepare state first, after review

Use the dedicated non-root AWS identity/profile already configured:

```powershell
$env:AWS_PROFILE = 'traceworth-staging'
aws sts get-caller-identity
Copy-Item infra/bootstrap/terraform.tfvars.example infra/bootstrap/terraform.tfvars
```

Edit the copied file with the intended account ID and a globally unique state
bucket name. Do not paste credentials into Terraform. Both AWS providers reject
an account other than `expected_account_id`.

```powershell
terraform -chdir=infra/bootstrap init
terraform -chdir=infra/bootstrap plan -out=bootstrap.tfplan
terraform -chdir=infra/bootstrap show bootstrap.tfplan
```

Stop to review the bucket, encryption, public-access block, versioning and
deletion protection. After approval, apply the saved bootstrap plan. Keep the
bootstrap directory's ignored local state securely backed up: it manages the
state bucket itself. The staging stack uses the newly created S3 bucket with
native S3 lockfiles (`use_lockfile = true`); it needs no DynamoDB locking table.

## Prepare the staging plan

```powershell
Copy-Item infra/staging/backend.hcl.example infra/staging/backend.hcl
Copy-Item infra/staging/terraform.tfvars.example infra/staging/terraform.tfvars
```

Edit the bucket name, account ID, monitored alarm email, and pilot public IP
allowlist. The documentation address `192.0.2.1/32` is only a placeholder and
will not let you in. Confirm the VPC CIDR and MyHandyAI networking. Do not widen
the allowlist to the whole internet to bypass an integration problem.

```powershell
terraform -chdir=infra/staging init -backend-config=backend.hcl
terraform -chdir=infra/staging plan -out=staging.tfplan
terraform -chdir=infra/staging show staging.tfplan
```

Before apply, review the resource count, target account/region, network ranges,
RDS engine/class availability, service quotas and a regional cost estimate.
`api_desired_count = 0` still leaves ALB, NAT and RDS billable after apply. The
planned size is a starting point, not a measured capacity or price guarantee.
Keep the existing AWS budget alerts; this stack does not duplicate them.

## Release order after the infrastructure plan is approved

1. Apply the reviewed infrastructure with no running API initially.
2. Push the tested Linux/amd64 image to the output ECR repository using a unique
   release tag. Obtain its sha256 digest; set `container_image` to the full ECR
   URI plus digest. Keep `api_desired_count = 0` and review/apply that update.
3. Populate the runtime database secret with JSON `username` and `password`,
   and the temporary bootstrap secret with JSON `password`, using Secrets
   Manager. Generate different strong passwords. No values belong in Git,
   Terraform variables, command arguments or build logs.
4. Run the admin task to migrate, provision the limited database login, and
   bootstrap the owner. Require exit code zero after every task; do not start
   the API after a failed migration. The service never migrates on startup.
5. Set `api_desired_count = 1`, review/apply the service update, and wait for
   database readiness and ALB health. Master credentials are not injected into
   the API task. Restart consumers when credentials rotate.
6. Build the React dashboard and upload its build output to the private bucket.
   Do not upload environment files or source credentials. Invalidate the
   CloudFront entry document after releases. Leave API responses uncached.
7. Open the output HTTPS dashboard address from an allowed network. Sign in,
   create the pilot application and its ingestion key, then store the key in
   MyHandyAI staging's Secrets Manager under its own execution permissions.
8. Verify two-account isolation, ingestion, key revocation, task-replacement
   persistence, RDS backup restore, alarm emails and HTTPS behavior. Schedule
   retention and confirm its first successful run before sustained telemetry.

### Exact admin task commands

After secret values exist and the digest-pinned admin definition has been
applied, use the wrapper below from the repository root. These commands change
the staging database; they are **not** part of offline validation. The wrapper
reads infrastructure outputs, starts one private Fargate task, waits for it to
stop, and requires exit code zero. Its temporary JSON contains no passwords.

```powershell
./scripts/run-staging-admin.ps1 -Command migrate
./scripts/run-staging-admin.ps1 -Command provision-runtime-role
./scripts/run-staging-admin.ps1 -Command bootstrap-owner -Email 'YOUR_OWNER_EMAIL' -AccountName 'TraceWorth pilot'
```

The wrapper defaults to profile `traceworth-staging` and region `us-east-2`.
If either changes, pass matching `-Profile` and `-Region` arguments each time.

Use a unique runtime username such as `traceworth_runtime` with a 20–256 character
password. The owner password accepts 12–256 characters. The bootstrap task reads
`TRACEWORTH_BOOTSTRAP_PASSWORD` from the bootstrap secret; it never resets an
existing account. Migration and role provisioning are repeatable; duplicate
owner bootstrap fails rather than changing a password.

Underlying container commands are `migrate`, `provision-runtime-role`,
`bootstrap-owner --email … --account-name … --password-env`, and
`retain --days 30 --batch-size 1000`. Retention deletes **one** bounded batch:
inspect `more_may_remain` and schedule repeat runs until the backlog is cleared.
Do not claim a 30-day retention guarantee until that schedule is running and
verified. Bootstrap secret access remains only on the admin task; remove its
injection when replacing the bootstrap task with a narrower maintenance role.

### Dashboard build

```powershell
npm ci
npm run build --workspace @traceworth/dashboard
```

The production build uses relative `/api` calls and the current browser origin
in the Python snippet. With no separately hosted marketing site it links back
to workspace home. Once that site is deployed, set `VITE_WEBSITE_URL` to its
HTTPS address **before** the dashboard build; this is public configuration,
never a place for keys. Upload `apps/dashboard/dist/` only. Keep S3 object
metadata for `index.html` at `Cache-Control: no-cache` and invalidate it after
updates. Hashed assets may use long-lived caching.

The admin task has greater access than the API task. Limit `ecs:RunTask` and
`iam:PassRole` for it to staging operators; do not use it as an application
service. The app task role itself has no AWS API permissions.

## Deployment gates still requiring real AWS evidence

Offline Terraform validation is not an AWS plan/apply test. Private origin
connectivity, HTTPS/Secure cookie behavior through CloudFront, WAF allowlisting,
service IAM, RDS TLS and restore, quotas, alarm delivery, and Lambda egress must
be verified on the deployed stack. A single NAT and Single-AZ database can cause
staging outages. The private HTTP origin hops are not end-to-end TLS.

The SDK is still best effort, without retries or a durable spool. Lambda needs
an invocation-aware flush strategy before it can be used for trustworthy pilot
measurements. No public signup, recovery, invitations or email verification is
claimed. Report windows and event limits mean assessments are not an all-time
or complete accounting record.

Current report defaults are a 30-day received-event window, at most 10,000
events, and at most 16 MiB of stored event input. Each incoming event is limited
to 64 KiB; an oversized event rejects its entire batch. These bounds reduce
memory exposure but do not prove latency or throughput at pilot volume.
