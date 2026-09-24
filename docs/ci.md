# Continuous integration and the deployment sequence

CI means continuous integration: GitHub runs checks when code changes so we can
find regressions before deploying. CD is the later step that releases a tested
version to AWS. This first workflow performs CI only.

## What is checked

The workflow is `.github/workflows/ci.yml`. It runs on pushes, pull requests,
and a manual **Actions → CI → Run workflow** invocation once the workflow is on
the default branch. Job names in the workflow are the source of truth.

| Check | Purpose |
| --- | --- |
| Python tests on Ubuntu, Python 3.10/3.12/3.14 | SDK behavior, schema, accounting, local web server, FastAPI account isolation and HTTP delivery |
| React checks on Node.js 22 | Install from package-lock.json with npm ci, type-check and build both applications |
| Python distribution smoke check | Build a wheel and test installation and CLI/static resources outside the source checkout |

The workflow installs both backend and test extras. Its database tests currently
exercise **SQLite**, not PostgreSQL. Live ingestion tests use an ephemeral local
HTTP server with generated test accounts/keys; no AWS credentials are needed.
There are no Docker, PostgreSQL or Terraform checks yet because their deployment
files/support have not been implemented. Add these gates with those milestones.
CI does not replace browser acceptance of UI changes.

## Reading the result

1. Open the repository's **Actions** tab and select the run for your commit.
2. Open any failed job and its first failing command. Fix the cause locally.
3. Push the correction; GitHub runs the checks again. A newer run on the same
   branch supersedes the older run.
4. Before merging, check that every job for the intended commit passed.

Workflow permissions are read-only. Official actions are pinned by commit SHA;
review pins periodically to receive fixes. Python dependencies currently resolve
within pyproject.toml ranges; npm uses the committed lockfile. A passing run is
evidence for that dependency resolution, not a permanent compatibility guarantee.

## Local equivalents (PowerShell)

Use the repository virtual environment; create it first if absent:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[backend,test]'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
npm ci
npm run typecheck
npm run build
```

The wheel installation smoke commands are listed in the workflow's package job;
the commands above cover the test and frontend jobs only.
The matrix's Linux checks are run by GitHub; a Windows-only local pass does not
prove all matrix jobs passed.

## Publishing and activation

Adding the YAML file locally does not create a GitHub run. The workflow and the
source it tests must be committed and pushed to the repository. At the start of
this milestone, this checkout had no commits and its source was untracked.
Review the initial file selection before publishing. Keep runtime databases,
telemetry, credentials, .env files, node_modules and virtual environments out of
Git (the repository .gitignore excludes their expected locations).

After the first successful GitHub run, configure repository merge rules to
require its checks if available for the repository's plan. A workflow alone does
not prevent merging failed code. No remote run or merge protection is implied
by local verification.

## What follows

1. Add Docker/PostgreSQL support and exercise it in CI.
2. Explain and bootstrap Terraform locally: `init` prepares providers; `plan`
   previews changes; `apply` provisions resources after review.
3. Store Terraform state remotely with locking and restricted access.
4. Configure a GitHub OIDC deployment role scoped to this repository and staging.
   Use temporary credentials, not the local administrator's access keys.
5. Add a manually triggered staging release workflow for a tested commit,
   database migration step, deployment health checks and application rollback.
   Schema recovery must be considered separately from image rollback.
6. Keep Terraform applies separate from routine application deployment. Consider
   automatic staging releases only after the manual release path is dependable.

No AWS deployment, resource provisioning, OIDC trust or billable service is
created by the current CI workflow.

## Implementation verification

September 24, 2026: independent testing passed 78 tests without skips on Windows
Python 3.14, npm ci/typecheck/build, actionlint 1.7.12, and isolated wheel smoke.
Coordinator independently passed all 78 tests on Linux Python 3.10 in Docker.
Python 3.12 and the complete GitHub-hosted matrix await the first remote run.

The initial minimum-version Linux check exposed a Python 3.10 JSON parser
RecursionError for deeply nested malformed input. Upload and file readers now
isolate that record, and the file regression verifies surrounding valid records
are preserved. This was a compatibility fix required to make the existing
acceptance suite pass on the advertised minimum Python version.

The current dependency resolution emits a Starlette test-client deprecation
warning for httpx; it is not a test failure. Track dependency migration separately.
