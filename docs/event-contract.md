# Event contract: current version 1

This describes dictionaries emitted by `src/traceworth/sdk.py`. The formal
[JSON Schema](../schemas/event-v1.schema.json) and runtime validator in
`src/traceworth/validation.py` cover the current contract. The SDK validates
explicit recording inputs; the assessment reader validates complete envelopes.

## Shared envelope

| Field | Emitted representation | Meaning |
| --- | --- | --- |
| `schema_version` | Integer, currently 1 | Envelope revision |
| `event_id` | UUID string | Unique emission identity |
| `event_type` | String | One of the four types below |
| `occurred_at` | UTC ISO timestamp string | Time of emission in the application |
| `application_id` | String | Client's application label |
| `environment` | String | Client label, default `development` |
| `configuration_id` | String or null | Client-level configuration label |
| `workflow_id` | UUID string, or caller-supplied ID for outcomes | Workflow association |
| `step_id` | UUID string or null | Active step, when applicable |

No tenant ID, customer ID, ingestion timestamp, provider request ID, SDK version,
or sequence number is currently emitted. Application labels are not security
boundaries. A hosted receiver will need authenticated ownership independent of
labels supplied by callers.

## Step events

`step.started` and `step.finished` share `name`, `kind` (`workflow` or `operation`),
`parent_step_id` (string or null), and `attempt_number` (default 1).
Each invocation gets a new step ID. Ordinary nested operations retain the active
workflow ID and reference the active parent step. A new workflow gets a new ID
and no parent reference, even inside another workflow.

`step.finished` additionally carries:

| Field | Meaning |
| --- | --- |
| `status` | `completed`, `failed`, or `cancelled` |
| `error_category` | Exception class name, or null |
| `duration_ms` | Elapsed time measured with a performance counter |

`asyncio.CancelledError` produces `cancelled`; other escaping exceptions produce
`failed`. A caught exception does not fail its enclosing span. Step duration
includes child execution and can overlap concurrent steps: summing durations is
not workflow wall-clock latency.

## Usage events

`usage.recorded` carries these additional fields:

| Field | Meaning |
| --- | --- |
| `provider` | Caller-supplied provider name |
| `model_or_service` | Caller-supplied model or service identifier |
| `usage_units` | Unit-name mapping to nonnegative finite numbers |
| `amount` | Decimal string or null when unknown |
| `currency` | Caller-supplied currency label or null |
| `cost_basis` | `provider_reported`, `estimated`, `allocated`, or null |
| `price_version` | Caller-supplied pricing reference or null |

Unit names must be nonempty strings but are not normalized yet. Nested fields such as cached
tokens need a documented relationship to totals before pricing: adding both a
total and its subcategories can double-count usage. The SDK does not calculate
costs or enforce price versions for estimates. Currency format is three uppercase
letters; membership in an external currency registry is not verified. Unknown
costs require currency, basis, and price version to be null.

## Outcome events

`outcome.recorded` carries `outcome_type`, `value`, and `evaluator_version`.
The value must be a boolean, string, integer, or finite float. Containers and null
outcome values are rejected by runtime validation.

An explicit workflow ID takes precedence over active context. The step ID is
null when there is no active step in the target workflow. Feedback may arrive
after workflow completion. The local assessment uses the latest boolean
`accepted` outcome by timestamp, then event ID, within the supplied cohort. Other
outcome types are not interpreted as acceptance. Repeated feedback does not add
accepted workflows; there is no outcome revision API yet.

## Consumer accounting rules

1. Deduplicate transport replays by event ID. Two manual recordings of the same
   provider call receive different event IDs and cannot be deduplicated by that
   rule alone.
2. Pair start and finish records by application/environment, workflow, and step
   identifiers. Preserve incomplete and orphaned records for diagnosis.
3. Sum usage costs once per recorded service measurement. Do not add parent cost
   rollups to child costs. Keep currencies separate and disclose cost bases.
4. Keep missing cost distinct from a measured zero. Report how much observed
   usage has a known price; this does not prove all real usage was observed.
5. Use the root span duration for workflow latency when present. Report missing
   roots and overlapping work explicitly.
6. For a defined cohort, cost per accepted result equals all attributable cohort
   processing cost, including failures, divided by accepted workflows. A zero
   denominator yields an undefined result, not a finite amount. Incomplete costs
   require a partial-data label.
7. Define cohort time window, environment, configuration, acceptance rule, and
   feedback cutoff before comparing configurations. Keep completion, acceptance,
   and correctness separate.

## Compatibility and coverage gaps

The local assessment consumer handles version 1. No migration system is
implemented. Additive fields are permitted; incompatible meaning or structure
changes require a new schema version and retained historical fixtures. The
current runtime rejects unknown schema versions with a record diagnostic.

JSON Schema treats numbers such as `1.0` as integers mathematically. Python
runtime validation is deliberately stricter for schema and attempt numbers:
their JSON representation must decode as `int`, not `float` or `bool`. Use a
schema validator with date-time format checking enabled; the test extra installs
that support. Runtime timestamp validation additionally checks calendar values.

Queue loss counters are not exported with events. Whole missing workflows are
therefore invisible in the event file. Reliable coverage will require persisted
delivery diagnostics and, where possible, reconciliation against an independent
application or provider count. A balanced set of start/finish events alone does
not establish complete application coverage.
