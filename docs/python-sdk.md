# Python integration guide

This guide documents the current local SDK. Provider usage capture is manual;
automatic provider adapters and remote ingestion are planned. Local assessments
are available through the [CLI](local-mvp.md).

## Install and verify

Python 3.10 or newer is declared in the package metadata. A full supported-version
test matrix has not yet been established. From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[test]'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe examples/three_apps.py
```

The example appends synthetic events to `demo-events.jsonl`. It makes no provider
calls and reports no actual costs. Installation above is from the local checkout;
publication to a package index is not part of the current project state.

## Create a client

```python
from traceworth import JsonlExporter, TraceWorth

telemetry = TraceWorth(
    application="my-application",
    exporter=JsonlExporter("events.jsonl"),
    environment="development",
    configuration_id="baseline-v1",
    queue_size=1024,
)
```

Create one long-lived client per application process after any process fork.
Use a separate output file per writer. The exporter appends to the file but does
not create parent directories. Keep environment and configuration labels stable
for comparisons; tenant authentication and customer attribution are not provided.

## Decorate selected functions

```python
@telemetry.operation("analyze_input")
async def analyze_input(text):
    # Real application work belongs here.
    return {"completed": True}

@telemetry.workflow("analysis_request")
async def handle_request(text):
    return await analyze_input(text)
```

Both decorators support regular functions and `async def`. They preserve return
values and propagate exceptions. Each invocation emits a start and finish event;
the finish includes elapsed duration and status. Arguments and results are not
recorded. Generator functions are rejected; instrument their consumption with a
span instead.

Every workflow decorator starts a new workflow, including when nested. Use
operation decorators for children that should stay in their parent's workflow.
An operation outside any active scope gets a new workflow ID but retains kind
`operation`.

## Measure blocks and record usage

```python
with telemetry.span("analysis_request", workflow=True) as workflow_id:
    with telemetry.span("model_call", attempt_number=1):
        # Synthetic example: replace units with measured provider response usage.
        telemetry.record_usage(
            provider="example-provider",
            service="example-model",
            units={"input_tokens": 100, "output_tokens": 25},
            amount="0.0025",
            currency="USD",
            cost_basis="estimated",
            price_version="synthetic-example-v1",
        )

# Delayed feedback may arrive outside the original span.
telemetry.record_outcome(
    "accepted", True, workflow_id=workflow_id,
    evaluator_version="human-feedback-v1",
)
```

The amount and units above are illustrative, not a pricing claim. Omit cost
fields if cost is unknown. Units must be nonnegative finite numbers. Supplied
costs require a three-letter uppercase currency and a supported basis:
`provider_reported`, `estimated`, or `allocated`. Amounts must be nonnegative
plain decimal strings. Unknown costs require all cost metadata to be omitted.
Usage recording requires an active span and a nonempty unit mapping.

Record each service call once. Put retries in distinct operation spans with
explicit attempt numbers and record the usage each attempt actually incurred.
The SDK does not perform retries or discover retries hidden inside another
library. Decorators use attempt number 1; use spans to supply another number.

An outcome needs an active scope or an explicit workflow ID. The span context
manager yields that ID; decorators do not expose it through a public accessor.
Acceptance, completion, and evaluated correctness should use separate signals.

## Export and shutdown

An exporter is a synchronous callable taking one event dictionary. The worker
calls it sequentially. It should return promptly and implement its own I/O
timeouts; a blocked exporter cannot be forcibly stopped by `close()`.

```python
# Stop accepting application work and finish active workflows first.
drained = telemetry.close(timeout=5.0)
print({"drained": drained, **telemetry.diagnostics})
```

`close()` stops new events and waits up to the timeout for the worker. False means
the worker is still running. True means the worker exited, not that every event
was successfully exported: inspect the error and drop counters too. Calls after
close increment the drop counter. A client used in a `with` block closes on exit,
but the context manager does not report the close result.

| Diagnostic | Meaning |
| --- | --- |
| `pending_events` | Queued events plus the event currently being exported |
| `dropped_events` | Events rejected because the queue was full or the client closed |
| `export_errors` | Export calls that raised an ordinary exception; their events are discarded |

An exporter error does not raise in the application call. Invalid explicit
recording calls can raise. Automatic adapters will need an additional isolation
boundary for telemetry extraction failures.

## Context and privacy limits

Context follows nested calls and inherited asyncio task context. There is no
SDK API for cross-process, queue, or manual thread propagation. Do not assume a
background job retains its originating workflow. Finish spawned tasks before
closing the client; tasks can outlive their parent's span.

Names and explicit outcome values are stored as supplied. No redaction or size
limits are applied to those fields. Use controlled labels rather than personal
data or secrets. The current API does not collect function bodies, infer business
meaning, measure arbitrary CPU/memory usage, or intercept all external services.
