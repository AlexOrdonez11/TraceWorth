# TraceWorth

A Python SDK for collecting workflow execution, usage, and outcomes using the
same API across AI applications. The local MVP captures telemetry and produces
workflow assessments from JSONL. Automatic provider integrations are not implemented.
It includes separate React website and dashboard applications backed by a local
FastAPI API and persistent SQLite storage. Accounts own applications, ingestion
keys, and metrics. Automatic provider integrations remain planned.

## Documentation

- [CI and deployment workflow](docs/ci.md): automated checks, local verification,
  and the path to manually triggered AWS releases.
- [Run the local web apps](docs/local-web.md): website, account setup, applications,
  scoped API keys, SDK ingestion, persistent metrics, and legacy JSONL viewer.
- [Run the local MVP](docs/local-mvp.md): demo, assessment commands, report fields,
  and current limits.
- [Agent workflow](docs/agent-workflow.md): coordinator/developer/tester loop and
  local acceptance gates; reusable instructions are in [AGENTS.md](AGENTS.md).
- [Usability review](docs/usability-review.md): independent exploration of the
  CLI, onboarding, reports, and error recovery, with prioritized feedback.
- [Project direction and architecture](docs/architecture.md): product boundaries,
  implemented components, and the intended assessment pipeline.
- [Python integration guide](docs/python-sdk.md): setup, instrumentation, usage,
  outcomes, exporters, and operational limitations.
- [Event contract](docs/event-contract.md): current fields, accounting rules,
  and schema gaps.
- [Implementation roadmap](docs/roadmap.md): ordered work packages, dependencies,
  acceptance criteria, and the next development milestone.

These documents distinguish current behavior from proposed implementations.

## Run locally

Requires Python 3.10+ and Node.js 22.12+ for the React applications. Install from
the repository root:

```powershell
python -m pip install -e '.[backend,test]'
npm install
```

Run these commands in three separate terminals:

```powershell
python -m traceworth.backend --port 18766 --database local-data/traceworth.db
npm run dev:dashboard
npm run dev:website
```

Open the [website](http://127.0.0.1:18768) or
[dashboard](http://127.0.0.1:18767). Register a local account, create an
application, and create its ingestion key. Use the application's **slug** in the
SDK. New accounts have no data; the dashboard offers an explicitly synthetic demo.
The backend persists account and telemetry data across restarts in the selected
SQLite database. Keep the services on loopback; this is a local development setup.

Verify the Python and React implementations:

```powershell
python -m unittest discover -s tests -v
npm run typecheck
npm run build
```

## Standalone CLI and legacy JSONL viewer

The original offline workflow is still available without React or an account:

```powershell
python -m pip install -e '.[test]'
python -m unittest discover -s tests -v
python -m traceworth demo --output local-demo/events.jsonl
python -m traceworth assess local-demo/events.jsonl
python -m traceworth assess local-demo/events.jsonl --format json --output local-demo/report.json
python -m traceworth serve --events local-demo/events.jsonl --port 18765
```

The demo emits explicitly synthetic events for MyHandyAI, ClientSignalEQ, and
AnalyticsAI. It does not connect to those applications. Use a new demo output
path on each run; the CLI refuses to replace an existing telemetry file.
The last command serves the legacy JSONL viewer at `http://127.0.0.1:18765/`
and `/dashboard`. It is separate from the account-based React dashboard and does
not persist imports or use API keys. Omit `--events` for a labeled synthetic demo.

## Instrument an application

```python
from traceworth import JsonlExporter, TraceWorth

telemetry = TraceWorth("my-application", JsonlExporter("events.jsonl"))

@telemetry.operation("generate_answer")
async def generate_answer():
    # Call your provider, then pass usage from its response here.
    telemetry.record_usage("example-provider", "example-model",
                           {"input_tokens": 120, "output_tokens": 30})

@telemetry.workflow("answer_request")
async def answer_request():
    await generate_answer()

# On application shutdown: telemetry.close()
```

Sync and async functions use identical decorators. A `telemetry.span("name")`
context manager measures blocks and yields the workflow ID. Use
`span("request", workflow=True)` to establish a new workflow. Record delayed
feedback with `record_outcome("accepted", True, workflow_id=saved_id)`.
Generators require an explicit span around consumption.

To send the same events to your account's application, replace `JsonlExporter`
with `HttpExporter`. Store the one-time key outside source code:

```python
import os
from traceworth import HttpExporter, TraceWorth

telemetry = TraceWorth(
    "my-application",  # Exact application slug from the dashboard.
    HttpExporter("http://127.0.0.1:18766/api/events",
                 os.environ["TRACEWORTH_API_KEY"]),
)
```

The key grants ingestion into one application only; it cannot read metrics.
`HttpExporter` sends each event once with a timeout. HTTP errors increment SDK
export diagnostics; there is no automatic retry or durable queue. Revocation
blocks subsequent ingestion. Keep the key available only to the application
process, never frontend code.

## Event contract and measurement

Version 1 envelopes have unique `event_id`, `schema_version`, UTC `occurred_at`,
application/environment/configuration identifiers, `workflow_id`, and `step_id`.
The four event types are `step.started`, `step.finished`, `usage.recorded`, and
`outcome.recorded`. Steps carry names, parent IDs, and attempt numbers; finished
steps add duration, status, and exception class. Usage events carry provider,
service, units, and optional cost metadata. Outcomes carry type, value, and
optional evaluator version.

Record each provider usage measurement once, inside the operation that incurred
it. Step completion does not add usage or cost. Represent each retry as a separate
span, with its attempt number and usage. Consumers should deduplicate by event ID
and aggregate usage events, not sum both parent and child cost rollups.

Costs are absent when unknown. Explicit costs use decimal strings, currency, and
one of `provider_reported`, `estimated`, or `allocated` as the cost basis. Supply
the pricing version when estimating. There is no built-in price catalog or
automatic provider bill reconciliation. Completion and user acceptance are
separate signals; neither establishes correctness.

## Delivery and privacy

Each client has a bounded queue and background export thread. Full queues drop
events; exporter failures discard the affected event. `diagnostics` reports
pending events, dropped events, and export failures. This initial transport is
best effort: it has no durable spool, retry, or crash recovery. Incomplete traces
must not be interpreted as complete accounting.

Use `close(timeout=5)` at shutdown or use the client as a context manager. An
explicit close returns false if export is still unfinished. Exporter exceptions
do not break application calls. Recording APIs raise for invalid usage/context.
Use one client per process; do not share it across a process fork. JSONL export
is intended for a single writer per file.

Context follows nested calls and asyncio tasks. Processes, job queues, and
ordinary threads need explicit propagation support in a later release. Work
launched in a task can outlive its parent span; finish application work before
closing telemetry.

Function arguments, return values, prompts, outputs, and exception messages are
not automatically captured. Explicit names and outcome values are stored as
supplied: use controlled labels and avoid secrets or personal content. There is
no automatic redaction of manually submitted data.

## Next milestones

1. Inspect the provider clients and worker systems used by the pilot applications.
2. Add opt-in provider adapters with verified usage accounting, including streams.
3. Add portable context propagation for background jobs and durable delivery.
4. Extend local assessments with provider pricing and stronger coverage reconciliation.
5. Integrate two real applications with the unchanged SDK core, then evaluate one
   proposed improvement against a defined quality threshold.

The account backend currently supports one owner per account. Invitations,
password recovery, verified email, production identity/hosting, retention/deletion,
and operational monitoring remain planned. See the roadmap for acceptance gates.

Automatic instrumentation of all Python methods and automatic recommendations
are outside this initial implementation. The SDK supplies meaningful boundaries;
provider adapters will automate supported usage collection.
