# Project direction and architecture

Status: local capture, assessment, and account workspace, September 16, 2026.

## Purpose

TraceWorth should help developers understand what their AI applications execute,
what resources that execution consumes, and which changes deserve testing.
It begins with application telemetry. Assessment and improvement verification
will be built on that evidence.

The same library and event model must work for ClientSignalEQ, MyHandyAI, and
AnalyticsAI. Application names, workflow names, and outcome definitions belong in
integrations and configuration, not conditional branches in the SDK core.
The included three-application example is synthetic; none of these applications
has been integrated or inspected as part of this implementation.

## Capture strategy

Explicit workflow and operation boundaries provide application meaning. Future
provider adapters should automatically capture supported service usage within
those boundaries. Optional module instrumentation may later capture selected
functions, subject to exclusions and overhead measurements.

Execution telemetry does not explain business intent or establish correctness by
itself. A function name is a label, not a semantic assessment. Outcome definitions,
evaluation rubrics, and representative examples must come from each application.
Capturing every Python function is not a prerequisite for useful assessment.

## Implemented path

```text
Application decorators / spans / explicit recording calls
                    |
            ContextVar scope
                    |
         Version 1 event envelopes
                    |
           Bounded memory queue
                    |
          Background export thread
                    |
       Export callback (JSONL or HTTP)
```

The SDK uses only Python's standard library at runtime. It supports synchronous
and asynchronous functions, nested steps, explicit attempt numbers, usage records,
and immediate or delayed outcomes. The queue isolates exporter I/O from request
execution; queue insertion, timestamps, and event construction still run in the
application thread.

Export is best effort. An overflow, exporter exception, or process crash can lose
events. Diagnostics are local counters, not persisted coverage records. The
consumer cannot prove complete capture from JSONL files alone.

`HttpExporter` uses the standard library and sends one event per request to an
application-scoped bearer-key endpoint. It has a timeout but no retry or disk
spool. Backend persistence begins only after successful ingestion; it cannot
recover an event lost in the application's exporter queue.

## Account workspace: implemented locally

```text
React website :18768 -> React dashboard :18767
                               |
                     /api development proxy
                               |
                      FastAPI API :18766
                               |
              SQLite accounts / applications / keys / events
                               |
                    account-scoped assessments

Python SDK -> HttpExporter -> scoped bearer-key ingestion -> same SQLite events
```

The website and dashboard are separate Vite/React/TypeScript applications.
The backend is a separate Python process. Core SDK users need no FastAPI or
JavaScript dependencies; backend packages are installed with the `backend` extra.

Each account currently has one owner. A salted scrypt password hash verifies
sign-in. Session cookies are HttpOnly and SameSite Strict, expire after 12 hours,
and refer to hashed server-side session records. Session-authenticated writes
require a CSRF token. Exact browser origins are allowlisted. The local process
rate-limits authentication attempts; production identity controls remain planned.

API keys are random, stored as hashes, and scoped to account plus application.
They authorize ingestion only. The key determines ownership; supplied
account/tenant/user fields cannot override it. Every application/key lookup and
metrics query includes account ownership. Application slugs are unique within
an account, not globally. API resource paths use UUIDs; SDK events use the slug.

Ingestion validates complete batches of at most 500 events and 2 MiB, commits
atomically, and deduplicates by account/application/event ID. Conflicting replays
roll back the batch. Account reports assess each application independently before
combining cohorts so equal event IDs in separate applications do not suppress data.

The SQLite file persists across server restarts. Reports are computed from its
events in memory, not stored as derived warehouse tables. There is no automatic
sample data at registration; demo seeding is an explicit owner action scoped to
an application and labeled synthetic. See [local web setup](local-web.md).

The earlier standard-library JSONL viewer (`traceworth serve`) remains separate,
without accounts or persistent imports. Its port-18765 examples do not refer to
the new React dashboard.

## Local assessment path

The CLI now validates JSONL, isolates malformed rows, deduplicates event IDs,
reconstructs steps/workflows, and reports recorded costs, outcomes, and
evidence-based findings. It runs entirely locally. A formal version 1 event
schema is checked against fixtures. The [local guide](local-mvp.md) explains
commands and limits.

## Proposed production path, not implemented

```text
SDK + opt-in provider adapters
             |
Durable export / authenticated ingestion
             |
Raw events -> validation / deduplication -> reconstructed workflows
             |
Usage normalization + versioned pricing + data coverage
             |
Application assessments -> improvement hypotheses -> evaluated experiments
```

The local CLI makes accounting reviewable without deploying infrastructure.
Its processing interfaces also serve the local account API and dashboard.
Public deployment, production identity, and durable transport remain unimplemented.

The original brief proposes Azure and potentially Databricks. Hosting, storage,
compute, region, budget, and processing frequency remain open decisions. Recheck
service documentation and pricing when implementing deployment. No cloud services
are provisioned by this repository.

## Design boundaries

- Preserve the application's return values, exceptions, and cancellation behavior.
- Make supported capture and known blind spots explicit; do not label unknown
  usage as zero or promise complete cost coverage.
- Separate execution, usage, pricing, outcomes, and recommendations so each can
  evolve without application-specific SDK branches.
- Keep provider integrations optional; the core must work without provider SDKs.
- Collect metadata by default. Do not capture arguments, results, prompts, or
  exception messages automatically.
- Treat recommendations as hypotheses until an evaluation tests the change.

## Repository map

| Location | Responsibility |
| --- | --- |
| `src/traceworth/sdk.py` | Context, decorators, events, queue, JSONL exporter |
| `src/traceworth/__init__.py` | Public exports: `TraceWorth`, `JsonlExporter`, `HttpExporter` |
| `src/traceworth/exporters.py` | Best-effort HTTP ingestion delivery |
| `src/traceworth/backend/` | FastAPI, authentication, account ownership, SQLite, scoped ingestion |
| `apps/website/` | Independent React marketing/entry application |
| `apps/dashboard/` | Independent React account and metrics application |
| `src/traceworth/web.py`, `static/` | Legacy standalone in-memory JSONL viewer |
| `src/traceworth/validation.py` | SDK inputs and full event validation |
| `src/traceworth/assessment.py` | Reconstruction, accounting, and findings |
| `src/traceworth/cli.py` | Demo and assessment commands |
| `schemas/event-v1.schema.json` | Machine-readable event contract |
| `tests/test_sdk.py` | Current core behavior tests |
| `examples/three_apps.py` | Synthetic examples using the shared API |
| `docs/roadmap.md` | Planned implementations and completion criteria |

## Scope deferred

Billing, customer margin reporting, comprehensive infrastructure allocation,
automatic production changes, and universal integrations are deferred. The
first useful assessment should explain recorded application execution and usage.
Account invitations, roles, password recovery, email verification, data deletion,
retention controls, backups, and production operational hardening are also deferred.
