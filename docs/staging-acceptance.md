# Staging preparation acceptance

This record distinguishes local checks from AWS deployment. No AWS resources were
created or changed during this milestone. Local fixtures use generated credentials,
disposable PostgreSQL databases/containers, and synthetic SDK operations. Existing
SQLite account data and telemetry are preserved.

## Reproduction

Install `.[backend,postgres,test]` in the repository virtual environment. Run:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
npm ci
npm run typecheck
npm run build
```

PostgreSQL acceptance is opt-in. Set `TRACEWORTH_TEST_POSTGRES_DSN` to a disposable
PostgreSQL server whose login may create databases, then run:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_postgres.py -v
```

Each test creates a uniquely named `tw_acceptance_*` database and drops only that
database. The database supplied in the URL is not emptied. The runtime-role test
also creates and removes its uniquely named role. Without the environment variable,
these integration cases are explicitly skipped; a skipped PostgreSQL run is not
acceptance evidence.

Build and exercise the actual runtime image:

```powershell
docker build --tag traceworth:staging-acceptance .
.\.venv\Scripts\python.exe tests/container_smoke.py --image traceworth:staging-acceptance
```

The smoke script creates and cleans up its own Docker network and containers. It
runs explicit migrations twice, provisions a restricted database role, bootstraps
an owner, checks non-root/read-only API execution, records a synthetic operation
through `HttpExporter`, verifies persistence after API restart, and revokes the key.
It deliberately uses local mode and unencrypted communication on the isolated
Docker network; this does not demonstrate cloud TLS or an AWS integration.

Terraform checks use only mock providers:

```powershell
terraform -chdir=infra/bootstrap init -backend=false
terraform -chdir=infra/bootstrap validate
terraform -chdir=infra/bootstrap test
terraform -chdir=infra/staging init -backend=false
terraform -chdir=infra/staging validate
terraform -chdir=infra/staging test
```

The mock tests assert private database/load balancer/tasks, disabled API caching,
scoped network access, non-root container settings, runtime-only secret access,
protected state storage, safe stopped defaults, and rejected mutable images or
worldwide pilot access. They cannot establish AWS regional service availability,
real IAM access, TLS handshakes, network routing, or deployment readiness.

## Current independent evidence

- PostgreSQL 16 local Docker: the combined 120-case Python suite passed without
  skips, including inherited account/CSRF/key/atomic-ingestion cases, the 64 KiB
  individual-event and bounded-report regressions, and real HTTP SDK ingestion.
- Four settings and legacy SQLite migration tests passed.
- PostgreSQL tests cover concurrent identical ingestion, concurrent conflicting
  events, repeated migrations, restricted runtime role, explicit owner bootstrap,
  disabled cloud registration/demo, Secure cookies, readiness, and capped metrics.
- Test clients were corrected to close their transports without independently
  shutting down the shared ASGI application while other clients still use it.
- Terraform formatting and validation passed for both stacks. All five offline
  mock tests passed (one bootstrap and four staging).
- `npm ci`, both React typechecks, and both production builds passed.
- Actionlint passed the updated GitHub workflow. The container smoke job now
  installs its host-side Python dependencies before executing the smoke script.
- Wheel build and fresh virtual-environment installation with `--no-deps` passed
  outside the repository: SDK imports, CLI help/demo/assessment, three cohorts,
  zero invalid events, and packaged static/backend files.
- A new PostgreSQL non-superuser database-owner regression passes repeated runtime
  role provisioning/password rotation and restricted table access. This models
  PostgreSQL permissions; it does not establish actual RDS behavior. Existing
  replication-privileged roles are also explicitly rejected. SQLite and PostgreSQL
  reject boolean-to-number replay conflicts, including nested additive fields,
  and roll back the entire batch.
- The final Docker image passed independent runtime smoke against PostgreSQL 16:
  non-root/read-only operation, repeat migrations, restricted runtime credentials,
  owner bootstrap, real HTTP SDK ingestion, metrics persistence after API restart,
  and revoked-key rejection. The harness was corrected to rediscover Docker's
  ephemeral host port after restart. Its disposable containers/network were removed.
- The repaired smoke harness passed again on September 24 against the cached
  `traceworth:staging-acceptance` image (`903fe68fa3a3`) and `postgres:16-alpine`.
  The restart check uses the newly published port and the existing authenticated
  client, then confirms persisted metrics and revoked-key rejection.
- PostgreSQL 17 acceptance passed in [GitHub run 36044809499](https://github.com/AlexOrdonez11/TraceWorth/actions/runs/36044809499)
  for commit `525d82b25c05c15ab3c774f2d05e5ef6d9c58000`. That run also passed all
  three Python versions, React checks, and the isolated wheel smoke.
- The repaired container smoke passed on Linux in [GitHub run 36046591880](https://github.com/AlexOrdonez11/TraceWorth/actions/runs/36046591880)
  for commit `4b41c8389d4678bd94e4f3c7c5bd5b1d8ff4bfee`. All seven non-Terraform
  jobs passed, including PostgreSQL 17 acceptance again.
- Both provider lockfiles now include Terraform-generated Linux and Windows
  package hashes. Independent diff review confirmed the expected Linux hash was
  added without changing the AWS provider version or existing checksums. After
  this change, Terraform formatting, both validations, and all five mock tests
  passed again locally.
- All eight hosted jobs passed in [GitHub run 36047121331](https://github.com/AlexOrdonez11/TraceWorth/actions/runs/36047121331)
  for implementation commit `ebee3c73949ff3541a8c87082fa3fa0d6b0dde5e`:
  Python 3.10/3.12/3.14, React typechecks/builds, isolated wheel installation,
  PostgreSQL 17 acceptance, Linux container runtime smoke, and Terraform offline
  checks. This accepts the local staging foundation; AWS deployment and the
  real-cloud gates in `staging-setup.md` remain untested.

See `staging-usability-review.md` for separately scoped onboarding/browser evidence.
