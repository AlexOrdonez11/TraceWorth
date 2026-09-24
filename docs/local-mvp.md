# Run the local MVP

The local MVP is a Python SDK, command-line assessment tool, and local web app.
See the [web guide](local-web.md) for the landing page and dashboard. It requires no
provider keys or cloud resources. It measures the operations and usage explicitly
recorded by an application. Live provider capture and universal method tracing
remain planned work.

## Install and run

From the repository root on Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[test]'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m traceworth demo --output local-demo/events.jsonl
.\.venv\Scripts\python.exe -m traceworth assess local-demo/events.jsonl
.\.venv\Scripts\python.exe -m traceworth assess local-demo/events.jsonl --format json --output local-demo/report.json
```

The installed `traceworth` command exposes the same subcommands. The demo requires
a new output file and creates parent directories. Choose another directory when
rerunning it. Assessment output can replace an existing report; never use a real
telemetry file as the report destination. The CLI rejects using its input file
as its output destination.

`examples/three_apps.py` remains a smaller SDK-only example. The CLI demo is the
full assessment example with nine workflows across three application labels,
including failed steps, explicit retries, accepted/rejected/missing feedback,
and known/unknown costs. Every demo record uses environment `synthetic-demo`;
all prices and provider calls are simulated.

## Assess your application

Use the [SDK integration guide](python-sdk.md) to create a client, annotate
workflow/operation boundaries, and record actual usage. Drain the exporter at
shutdown, check its diagnostics, then point `traceworth assess` at the JSONL file.
Use `record_outcome("accepted", True, ...)` for the current assessment's acceptance
signal. Other outcome types remain in source data but are not interpreted as
accepted results.

Reports group records by application, environment, and configuration. They include:

- Input counts, invalid record locations, and duplicate counts.
- Workflow status, root duration, steps, parent references, and explicit attempts.
- Completed/failed/cancelled workflow counts and observed cohort time bounds.
- Usage grouped by provider/service/unit and recorded costs by currency/basis.
- Direct per-step costs and highest recorded cost findings for each currency/basis.
- Acceptance using the latest boolean `accepted` event by timestamp, breaking
  ties by event ID. Repeated feedback does not add accepted workflows.
- Findings with event, workflow, or step IDs as evidence.

The report includes all supplied records. It does not apply a date filter;
prepare the intended input cohort before making comparisons. The observed time
range describes records present, not proof that capture began and ended there.

## Interpret costs and findings

Amounts are decimal strings. Costs are summed once from usage records; step
durations and parent totals are not added to usage costs. Currencies and cost
bases remain separate. Per-accepted-result amounts include failed/unaccepted
workflow costs from the same cohort. No accepted workflows means the ratio is
null/undefined.

Unknown prices remain unknown. Partial-data indicators expose observed gaps;
even a report with no detected gaps cannot prove total application coverage.
The SDK's local drop/export-error counters must also be inspected. Whole missing
workflows cannot be inferred from the surviving event file.

Findings identify recorded failures, retries, missing data, and cost concentration.
They are investigation starting points. The MVP does not claim that changing a
model or prompt will preserve quality, and it never changes application behavior.

## Delivery and scale limits

JSONL delivery remains best effort, with no durable spool or export retries.
Reports load accepted events into memory, so this version targets local pilot
datasets, not unbounded production histories. The input is validated record by
record; malformed rows are reported while valid rows continue to be assessed.
A successful CLI exit does not mean every input row was valid: inspect the input
diagnostics. File/command errors return exit code 2.

The SDK has no cross-worker context propagation API yet. Provider pricing,
provider request deduplication, authenticated ingestion, hosted dashboards, and real
pilot integrations remain in the [roadmap](roadmap.md).
