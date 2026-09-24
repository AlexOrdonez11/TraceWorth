# Implementation roadmap

Planning baseline: September 16, 2026. Checked items are implemented; unchecked
items remain planned. Order reflects dependencies; no delivery dates are committed.
The narrower [local MVP](local-mvp.md) covers capture, validation, reconstruction,
and local assessments; it does not complete every milestone below.

## Current baseline

- [x] Shared Python client with workflow and operation decorators.
- [x] Nested sync/async scope and explicit usage/outcome recording.
- [x] Bounded background export and local JSONL output.
- [x] Synthetic examples for three application names.
- [x] Core and independent acceptance tests covering validation, async execution,
  delivery diagnostics, schema fixtures, accounting, and CLI behavior.
- [x] Local workflow reconstruction and assessments with evidence-linked findings.
- [x] Separate React website and account dashboard with a Python FastAPI API.
- [x] Persistent SQLite account/application ownership, owner sessions, scoped
  ingestion keys, revocation, and atomic replay-safe event batches.
- [x] Best-effort HTTP SDK exporter and account-scoped metrics; explicit synthetic
  demo seeding does not mix accounts or imply live provider integration.
- [ ] Real application integrations and provider adapters.
- [ ] Durable delivery, automatic pricing, verified experiments, and hosted UI.

## M1: Stabilize the event contract and SDK

**Objective:** make emitted data predictable before adding capture sources.

Implementation tasks:

- [x] Add a machine-readable event schema and representative version 1 fixtures.
- [x] Define and enforce scalar outcomes, nonempty labels, positive integer
  attempt numbers, unit keys, currency representation, and cost-field consistency.
- [x] Document version compatibility and behavior for invalid explicit inputs.
- [ ] Add supported Python-version CI and an install/build smoke check.
- [ ] Extend tests for generator rejection, nested workflows, post-close events,
  exporter file errors, and serialization boundaries.
- [ ] Measure instrumentation overhead under sync and concurrent async workloads;
  record the workload and baseline before setting an acceptable budget.

Suggested locations: `schemas/`, `tests/fixtures/`, validation helpers under
`src/traceworth/`, and CI configuration. These are proposed additions.

Acceptance: every generated fixture validates against its declared schema;
invalid inputs have documented behavior; tested Python versions install and run
the suite; overhead results are reproducible. No application-specific branches.

## M2: Automatic usage capture for a supported provider

Depends on M1 and inspection of actual pilot dependencies.

- [ ] Inventory provider SDKs, versions, async calls, streams, and hidden retries
  in two pilot applications. Select the first adapter from that inventory.
- [ ] Define an opt-in adapter interface and supported-version policy.
- [ ] Capture service/model identifiers and returned usage without storing content.
- [ ] Handle sync/async calls, streaming completion, early termination, failures,
  and cancellation according to the selected provider's documented behavior.
- [ ] Define how manual recording and automatic recording avoid duplicates.
- [ ] Add provider request identity and usage-availability metadata if the event
  contract requires them; distinguish unavailable usage from zero.
- [ ] Isolate adapter telemetry failures from application behavior and record
  diagnostics for unsupported response shapes.

Acceptance: recorded usage matches fixtures from the supported provider version;
return values, stream behavior, exceptions, and cancellation are preserved;
duplicate instrumentation does not double-count; no prompt/output capture by
default. Costs stay unknown unless backed by an explicit price source.

## M3: Background-job context and reliable delivery

Depends on M1; provider integration work can inform the required cases.

- [ ] Design public context export/import for workflow and parent-step IDs.
- [ ] Add worker examples with validation and guaranteed context cleanup.
- [ ] Define correlation across retries without reusing distinct attempt IDs.
- [ ] Add bounded persistent spooling, restart recovery, and export timeouts.
- [ ] Specify acknowledgement, retry/backoff, disk limits, and overflow policy.
- [ ] Preserve event IDs across retries and persist delivery diagnostics.

Acceptance: a queued worker remains associated with its source workflow;
concurrent jobs do not leak context; crash/restart tests recover acknowledged
spool state correctly; replay duplicates are identifiable; disk exhaustion and
shutdown never create unbounded blocking or storage growth. Document remaining
loss windows instead of promising exactly-once transport.

## M4: Local workflow assessment

Depends on M1; can start with fixtures before M2 and M3 finish.

- [x] Build a JSONL reader that isolates malformed records and deduplicates IDs.
- [x] Reconstruct workflows, step trees, attempts, and late outcomes.
- [x] Flag incomplete records and distinguish observed-data coverage from total
  application coverage.
- [x] Add decimal cost aggregation by currency and basis, keeping raw usage units
  separated by provider/service. Cross-provider unit normalization remains planned.
- [ ] Add a versioned price source with effective dates and explicit unknowns;
  implement only service/unit combinations backed by verified documentation.
- [x] Produce a CLI report with duration, failure counts, explicit retries,
  usage, known costs, outcome coverage, and evidence references.
- [x] Define repeat-outcome precedence and reporting cutoff behavior.

Acceptance: hand-calculated fixtures match reports; duplicates, out-of-order
events, missing roots, late feedback, mixed currencies, and zero accepted results
produce documented results. Every finding links to the contributing workflow or
step IDs. No generated advice is required for this milestone.

## M5: Prove reuse in real applications

Depends on M2 and M4, plus M3 when the chosen workflow crosses workers.

- [ ] Integrate one complete path in MyHandyAI and one in ClientSignalEQ or
  AnalyticsAI, based on repository availability.
- [ ] Keep provider adapters shared and business labels in application code.
- [ ] Reconcile recorded calls/usage with known application executions.
- [ ] Define one outcome signal per pilot and collect a representative baseline.
- [ ] Record setup effort, unsupported calls, overhead, and missing-data cases.
- [ ] Integrate the third application after resolving gaps exposed by the first two.

Acceptance: two different real applications use the same released SDK interface
and schema without application-specific core changes. Reports distinguish real,
synthetic, estimated, and missing data.

## M6: Evidence-backed improvement suggestions

Depends on M4 and M5.

- [x] Start with deterministic findings: high recorded cost, repeated failures,
  explicit retry cost, or slow steps relative to a defined cohort.
- [ ] Include evidence, sample size, coverage, and assumptions with each finding.
- [ ] Separate an observed problem from a proposed explanation or optimization.
- [ ] Define a baseline/alternative experiment with a quality threshold and
  comparable inputs/configurations.
- [ ] Report cost, latency, and quality together; retain rejected optimizations.
- [ ] Add model-generated explanations only after computed facts can be checked.

Acceptance: one experiment supports or rejects a proposed improvement using
documented conditions. No production change is applied automatically, and a
cost reduction alone is not presented as a quality-preserving improvement.

## M7: Hosted collection and interface

Depends on a useful local assessment and an agreed hosting budget.

- [ ] Choose Azure region, retention policy, budget, and processing schedule.
- [x] Implement local authenticated ingestion with server-validated account and
  application ownership, payload limits, and replay-safe SQLite storage.
- [ ] Harden identity and ingestion for public hosting; local account tests are
  not a production security, resilience, or deployment acceptance claim.
- [ ] Add raw event retention, derived tables, and saved report serving.
- [ ] Introduce Databricks only for a defined processing/evaluation workload.
- [ ] Build a workflow explorer and comparison views with freshness, coverage,
  and cost-basis labels.
- [ ] Add deletion/access policies and operational monitoring before external pilots.

Acceptance: tenant isolation is tested, replay does not duplicate accounting,
deployment cost is measured, and dashboards read saved results with clear
freshness. Verify current service documentation before implementation.

## Immediate next implementation

The local capture-to-assessment and account workspace are implemented. The next
milestone should connect a real pilot to its scoped ingestion key, measure the
delivery gaps, then select **M2: opt-in automatic provider capture** from actual
pilot dependencies. No specific provider is chosen without inspecting the pilot.

The next input needed for M2 is access to two pilot repositories and their
dependency files. Also identify which workflows use streaming or background
workers. Version-matrix CI and overhead measurement can proceed independently.

## Next account-workspace implementations

These are pending work packages, not capabilities of the current local release:

1. **Real ingestion baseline.** Instrument one real workflow, confirm its usage
   and outcomes in the account dashboard, reconcile counts with an independent
   application execution log, then repeat in a second application. Acceptance:
   shared SDK code, correct account/application ownership, documented missing
   calls, and no synthetic data presented as the baseline.
2. **Reliable delivery.** Add bounded disk spooling, retry/backoff and shutdown
   rules, replay the same event IDs, and persist loss diagnostics. Acceptance:
   server outage/restart and application crash tests show which events recover;
   queue/disk limits remain bounded and retries do not inflate costs.
3. **Dashboard data controls.** Add server-side time filtering and pagination,
   retention/deletion, export, and backup/restore workflows. Acceptance: account
   scoping holds on every new route; large fixtures remain usable; deletion and
   restores have explicit, tested behavior.
4. **Account lifecycle.** Decide a production identity approach before adding
   invitations/roles, email verification, recovery, and stronger session controls.
   Acceptance: recovery/invite flows and permissions are independently tested;
   current single-owner assumptions are migrated explicitly.
5. **Deployment readiness.** Choose hosting, TLS/origins, secrets management,
   database operations, rate limiting across processes, monitoring, and budget.
   Acceptance: isolated tenants, backup recovery, load tests, and operational
   failure handling pass before any public exposure.

Continue the coordinator → developer → independent tester → usability reviewer
loop in [agent workflow](agent-workflow.md) for each bounded milestone. Preserve
the working offline CLI while these backend and browser capabilities evolve.

## Later, optional work

Selected-module auto-instrumentation should be evaluated after basic capture is
reliable, with an allowlist, exclusions, and measured overhead. OpenTelemetry or
existing tracing connectors are integration candidates requiring separate design.
Billing, revenue attribution, infrastructure allocation, and broad provider
coverage remain later product decisions rather than prerequisites for the SDK.
