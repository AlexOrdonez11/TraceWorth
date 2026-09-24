# TraceWorth development workflow

When asked to implement a milestone or run the agent workflow, use a coordinator,
developer, independent testing agent, and usability-review agent. Follow
`docs/agent-workflow.md`.

- The coordinator defines bounded tasks and acceptance criteria before assigning
  work, maintains the task/defect record, and owns final integration.
- The developer implements assigned production files and fixes reproduced defects.
- The testing agent owns independent acceptance/regression tests, reports exact
  reproduction steps, and retests fixes. A passing developer check alone is not
  the final acceptance gate.
- The usability-review agent explores the actual user-facing application and
  onboarding, records reproduction steps and prioritized feedback, and checks
  whether results and recovery actions are understandable. For the CLI,
  walk help, installation instructions, demo, reports, and error cases. Also
  explore the local browser interface's real screens and navigation. Do not
  claim browser coverage for a CLI review.
- The coordinator triages usability findings into blocking defects or follow-up
  tasks; the developer fixes assigned issues, the tester verifies behavior, and
  the reviewer rechecks the affected user journey. Review itself does not expand
  a completed milestone into unbounded implementation work.
- Agree on file ownership before parallel edits. Agents share one checkout.
- Repeat implementation and testing until the requested milestone passes its
  gates or a concrete external blocker requires user input. Do not expand scope
  silently. Stop when the requested milestone is accepted.

Keep the Python SDK application-independent. Business labels belong in examples
and caller configuration. Never present synthetic data as live integration,
unknown cost as zero, partial capture as complete accounting, or an untested
recommendation as a verified improvement.

Use the repository virtual environment where available. Verification:

```powershell
.\.venv\Scripts\python.exe -m pip install -e '.[test]'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

For CLI acceptance, generate a demo in a new temporary directory, then assess it
in text and JSON formats. Do not overwrite a user's telemetry file. See the
local MVP guide for commands and current limits.

## Separate web applications and API

- `apps/website` is the React entry/marketing application, port 18768.
- `apps/dashboard` is the React account workspace, port 18767; its development
  `/api` proxy targets the Python API on port 18766.
- `src/traceworth/backend` is the FastAPI + SQLite backend. The core SDK remains
  independent of backend dependencies. Preserve the legacy `traceworth serve`
  JSONL viewer and CLI unless a requested change explicitly replaces them.
- Scope every backend data operation to the authenticated account and relevant
  application. SDK bearer keys authorize ingestion only. Never accept ownership
  from event metadata or expose full key tokens in later listings/logs.
- Keep HttpOnly/SameSite session behavior, CSRF checks, exact origin checks,
  atomic batch ingestion, replay handling, and key revocation covered by tests.
- New accounts start empty. Synthetic demo seeding requires an explicit action
  and must remain distinguishable from application data.
- Review registration, sign-in/out, application selection, key creation/revocation,
  empty states, demo seeding, and metrics refresh in the actual browser. Two-account
  isolation and live SDK ingestion must also be tested independently.

Install and verify the complete local stack from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pip install -e '.[backend,test]'
npm install
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
npm run typecheck
npm run build
```

Run each process in a separate terminal:

```powershell
.\.venv\Scripts\python.exe -m traceworth.backend --port 18766 --database local-data/traceworth.db
npm run dev:dashboard
npm run dev:website
```

Use Python 3.10+ and Node.js 22.12+. Preserve the SQLite file and real telemetry;
test with temporary databases and generated keys. Do not commit runtime account
data or credentials. SQLite is persistent local storage, not a durable SDK spool.
The HTTP exporter remains best effort without retries. One owner per account,
no recovery/invitations/email verification, and no production deployment are the
current boundaries; do not imply stronger guarantees in UI or documentation.
