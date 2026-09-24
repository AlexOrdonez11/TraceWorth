# Local website, dashboard, and Python API

The current account-based workspace has three independently run applications:

| Component | Location | Local address | Purpose |
| --- | --- | --- | --- |
| React website | `apps/website` | `http://127.0.0.1:18768` | Product introduction and dashboard entry |
| React dashboard | `apps/dashboard` | `http://127.0.0.1:18767` | Account, application, key, and metric management |
| FastAPI backend | `src/traceworth/backend` | `http://127.0.0.1:18766` | Authentication, ownership, ingestion, SQLite storage, assessments |

These are local development services, not a cloud deployment. The dashboard's
Vite development server proxies `/api` to the Python backend. The website has no
backend credentials. Use the same hostname consistently for dashboard sessions.

## Install and start

Use Python 3.10+ and Node.js 22.12+. From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[backend,test]'
npm install
```

Start each service in its own terminal at the repository root:

```powershell
.\.venv\Scripts\python.exe -m traceworth.backend --port 18766 --database local-data/traceworth.db
```

```powershell
npm run dev:dashboard
```

```powershell
npm run dev:website
```

Open the website on port 18768 or dashboard on port 18767. Ctrl+C stops a
foreground process. An occupied port must be freed or deliberately reconfigured;
changing the dashboard port also requires updating the backend's exact origin
allowlist, and changing the API port requires updating the dashboard proxy.
Backend `--allowed-origin` can be repeated; specifying it replaces the defaults.
The defaults include localhost/127.0.0.1 on dashboard 18767 and API 18766.

The database path is relative to the process working directory. Reuse the same
file to retain accounts, applications, keys, sessions, and events across restarts.
Starting with a different database creates an independent workspace.

## First account and application

1. Register with an email, password, and account name. Registration creates a
   local owner and signs them in. It does not send or verify email.
2. Create an application with a display name and stable slug. The slug is the
   identifier passed as the first argument to `TraceWorth` in your Python app.
3. Generate a named ingestion key. Copy its full token immediately: subsequent
   key listings show only metadata and a prefix. A lost key can be replaced with
   a new key; revoke the old one when appropriate.
4. Instrument the application and configure `HttpExporter`, or explicitly add
   synthetic demo data to explore the dashboard. New accounts are empty.
5. Refresh metrics after the application has flushed its exporter. Choose an
   application and cohort to inspect recorded costs, usage, outcomes, and findings.

Synthetic demo data is scoped to the selected application and labeled
`synthetic-demo` / `synthetic-v1`. Each explicit seed action appends two new
synthetic workflows. It does not overwrite real telemetry or represent a live
integration with MyHandyAI, ClientSignalEQ, or AnalyticsAI.

## Connect the Python SDK

Provide the ingestion key through `TRACEWORTH_API_KEY` in the application's
environment; do not commit it or pass it to browser code.

```python
import os
from traceworth import HttpExporter, TraceWorth

with TraceWorth(
    'my-application',  # Exact dashboard application slug.
    HttpExporter('http://127.0.0.1:18766/api/events',
                 os.environ['TRACEWORTH_API_KEY'], timeout=5),
    environment='development', configuration_id='baseline-v1',
) as telemetry:
    with telemetry.span('answer_request', workflow=True) as workflow_id:
        with telemetry.span('generate_answer'):
            # Replace these example quantities with measured provider usage.
            telemetry.record_usage('example-provider', 'example-model',
                                   {'input_tokens': 120, 'output_tokens': 30})
    telemetry.record_outcome('accepted', True, workflow_id=workflow_id)
```

Usage stays explicitly recorded; no provider is automatically intercepted.
Unknown prices remain unknown. Only record acceptance when your application has
an actual acceptance signal; the snippet demonstrates the API rather than a
quality evaluation.

The exporter sends one event per request from the SDK's bounded worker queue.
Delivery is best effort: timeouts, network failures, revoked keys, and rejected
payloads increment `export_errors`, and full queues drop events. There is no retry,
persistent spool, or reconciliation. Check `telemetry.diagnostics` and the result
of `telemetry.close()` during integration. Redirects are not followed; HTTPS is
required except for HTTP on loopback.

## API contract and ownership

- `POST /api/auth/register`, `/login`, `/logout`, and `GET /api/auth/me` manage
  the owner's session. The cookie is HttpOnly and SameSite Strict; mutations
  authenticated by cookie require `X-CSRF-Token` from the authentication response.
- `GET/POST /api/applications` lists or creates applications in the current account.
- `GET/POST /api/applications/{id}/keys` lists metadata or creates a one-time token;
  `DELETE /api/applications/{id}/keys/{key_id}` revokes a key.
- `POST /api/events` accepts a bearer key and `{"events": [...]}`. Batches are
  atomic, contain 1–500 version 1 events, and have a 2 MiB request limit. Event
  `application_id` must match the key's application slug. Ownership comes from
  the key; caller-supplied account/tenant/user ownership fields are rejected.
- Replay deduplication is scoped to account + application + event ID. Identical
  replays return duplicate counts; conflicting replays reject the whole batch.
- `GET /api/metrics?application_id=<application UUID>` returns the current
  account's assessment. Omitting the filter includes its applications only.
  An ingestion key does not authorize reading metrics.
- `POST /api/applications/{id}/demo` is an authenticated, CSRF-protected explicit
  synthetic seed. `GET /api/health` is an unauthenticated health check.

Passwords use salted scrypt hashes. API and session tokens are stored as hashes;
full ingestion secrets appear only in the creation response. Sessions expire
12 hours after creation. Sign-out invalidates the server session. Authentication
attempts are limited per source IP in the single API process; restarting resets
that limiter. Browser origins are checked against an exact allowlist.

## Boundaries and verification

One owner per account is supported. There are no invitations, role management,
password recovery, email verification, production identity integration, billing,
or public hosting in this milestone. The API binds to IPv4 loopback and local
HTTP cookies are not Secure; TLS and deployment hardening are future work.
SQLite persistence does not make SDK delivery durable. Account isolation is
covered by tests, but this local foundation is not a production authentication
or availability claim. No API for deleting accounts/events is implemented yet.

Assessment runs in memory over the selected account's stored events. Use local
pilot-sized data; pagination, retention limits, backups, and operational
monitoring remain planned. Review account/application selection and synthetic
labels before interpreting results. Captured metadata is supplied by the caller;
there is no automatic redaction of explicitly submitted sensitive content.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
npm run typecheck
npm run build
```

## Legacy standalone JSONL viewer

The earlier standard-library web viewer and CLI are preserved:

```powershell
.\.venv\Scripts\python.exe -m traceworth serve --events C:\path\to\events.jsonl --port 18765
```

This serves `/` and `/dashboard` on port 18765. It has no account login and does
not use the new API database. Omitting `--events` loads its labeled synthetic
three-application demo. **Refresh source** rereads the configured file; **Import
JSONL** assesses up to 10 MiB in memory without persisting it. Browser report
exports, cohort selection, and workflow dialogs still work. This legacy viewer
must remain on loopback and is distinct from the React account dashboard.

See [local MVP](local-mvp.md) for offline CLI usage and [web review](web-usability-review.md)
for the earlier viewer's review record; that review is not evidence for the new
account application.
