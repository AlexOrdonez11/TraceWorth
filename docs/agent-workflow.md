# Local MVP agent workflow

## CI milestone — September 24, 2026

Scope: automated checks for the existing application, with no AWS deployment.

| Task | Owner | Acceptance |
| --- | --- | --- |
| GitHub Actions workflow | Developer | Read-only permissions, pinned actions, Python matrix, React builds, isolated wheel smoke |
| Independent verification | Tester | Full local suite and frontend checks; workflow lint and package smoke |
| Documentation review | Usability reviewer | Commands and claims match workflow; distinguish local checks from hosted results |
| Integration and Linux baseline | Coordinator | Minimum Python version exercised on Linux; publish readiness and limitations recorded |

See [CI guide](ci.md) for activation, reading failures, and future deployment
steps. Docker/PostgreSQL and Terraform gates will accompany their respective
implementations. Earlier milestone records below remain historical.

This is the working protocol for the coordinator, developer, testing, and
usability-review agents.
It runs within the current development session; it is not a scheduled service or
a background process that continues after the session ends.

## Responsibilities

| Role | Responsibility | Output |
| --- | --- | --- |
| Coordinator | Define the next bounded task, resolve scope, assign file ownership, triage defects, decide acceptance | Task board and acceptance evidence |
| Developer | Implement tasks and fix reported defects; run targeted checks | Code and implementation notes |
| Testing agent | Independently exercise acceptance cases, report reproducible failures, retest fixes | Regression tests and pass/fail verdict |
| Usability-review agent | Explore onboarding and real user journeys; evaluate clarity, discoverability, reports, and error recovery | Prioritized feedback with commands or screen evidence |

The coordinator may implement a separate supporting component while the developer
works. Agents share a checkout, so ownership is explicit and concurrent edits to
the same files are avoided. Tests evaluate behavior and hand-calculated results,
not merely the implementation's internal structure.

## Loop

1. Coordinator selects a task with inputs, expected behavior, and acceptance cases.
2. Developer implements it and reports limitations or decisions.
3. Testing agent runs independent tests and records any reproducible failure.
4. Usability-review agent walks the application as a new user and reports
   confusing behavior, missing guidance, and reproducible defects.
5. Coordinator prioritizes test failures and usability findings; the responsible
   developer fixes blocking issues and records follow-up enhancements.
6. Testing agent retests the failure and relevant regressions; usability reviewer
   rechecks affected journeys when changes alter user-facing behavior.
7. Repeat until all requested milestone gates pass. Stop rather than silently expanding
   into the full hosted-product roadmap.

Failure reports include a command or fixture, expected result, observed result,
severity, owner, and retest outcome. Crashes on ordinary invalid inputs, incorrect
accounting, application/cohort mixing, or misleading completeness claims block
acceptance. Optional enhancements enter the later roadmap.

## Usability review scope

The application has a CLI and a local web interface. Explore help, documented installation,
synthetic-demo creation, text/JSON assessments, report interpretation, repeated
commands, missing files, malformed input, and output handling. Use temporary
files and distinguish synthetic examples from real integration evidence.

The web interface must also be explored through actual browser navigation,
including empty/loading/error states and keyboard interaction. Do not invent a
browser checks that were not actually performed. See [the web review](web-usability-review.md).

Save each review with the application version/state, journeys actually exercised,
reproduction steps, observed behavior, user impact, severity, recommended fix,
and blocker/follow-up classification. Current feedback is in
[the usability review](usability-review.md). Product improvements are proposed
tasks until assigned; a feedback request alone does not authorize an endless
development loop.

## Local MVP boundary

The first local MVP is a Python capture-to-assessment pipeline. It must run
without credentials, external services, or paid infrastructure:

- Validate the reusable SDK event contract and reject invalid explicit inputs.
- Capture sync/async operations, recorded usage, outcomes, and delivery diagnostics.
- Generate explicitly synthetic examples for three application types.
- Read local events, isolate malformed records, and deduplicate replayed IDs.
- Reconstruct workflows with visible incomplete/orphan data.
- Report duration, failures, retries, known costs, and outcome coverage.
- Keep costs separated by currency/basis and cohorts by app/environment/config.
- Produce evidence-based findings, with unknown costs and zero acceptance handled.
- Provide a CLI, install instructions, and independently passing acceptance tests.

Live provider adapters, complete automatic function capture, durable transport,
real pilot validation, a dashboard, and cloud hosting remain subsequent milestones.
This MVP can assess only the application data that its integration records.

## Current task board

| ID | Task | Owner | Status |
| --- | --- | --- | --- |
| MVP-01 | Runtime event validation and machine-readable schema | Coordinator | Passed |
| MVP-02 | Workflow reconstruction and accounting | Developer | Passed |
| MVP-03 | CLI and synthetic multi-application demo | Developer | Passed |
| MVP-04 | Independent edge-case and CLI acceptance tests | Testing agent | Passed |
| MVP-05 | Documentation, installation check, final acceptance | Coordinator | Passed |

## Verification record

Local acceptance on September 16, 2026, Windows with Python 3.14:

- Independent testing agent: 31 tests passed with no skips using the project
  virtual environment and test extras, including real CLI subprocess checks.
- Editable installation and wheel build passed; the built wheel was installed
  in a separate temporary virtual environment and ran demo/assessment commands
  outside the repository successfully.
- Saved demonstration: 60 valid synthetic events across three application
  cohorts, with zero invalid records or duplicates.
- Schema fixtures validate with runtime and JSON Schema validators.
- SDK, malformed input, replay, decimal accounting, cohorts, outcomes, partial
  data, direct step costs, and timestamp regressions passed.
- Developer self-checks were followed by independent tester approval.

## Defects resolved in the loop

| Finding | Resolution | Retest |
| --- | --- | --- |
| Incomplete telemetry could show a non-partial cost flag | Propagate incomplete/invalid/conflicting input indicators to cost reporting | Passed |
| Workflow-only totals obscured expensive operations | Add direct step costs and highest recorded cost evidence | Passed |
| Date-time schema format support was absent in the test environment | Install format-checking test extras and enforce timestamp syntax | Passed |
| Valid lowercase timestamp suffix could fail in assessment parsing | Normalize timestamp parsing and add regression tests | Passed |

All local gates passed; the development loop stops here. The broader
[roadmap](roadmap.md) continues beyond this local MVP. Python versions other than
the local 3.14 environment still need CI verification.

## Local web milestone

The subsequent user-requested milestone resolves UX-01 through UX-05 and adds a
local landing page plus a dashboard connected to the shared assessment engine.
The developer fixed CLI behavior; the coordinator implemented web surfaces;
the independent tester verified CLI/HTTP/package behavior; the reviewer
retested CLI journeys and reviewed source/screenshots. The coordinator performed
browser interactions because the reviewer's browser surface was unavailable.

All five prior findings passed retests. The suite now has 51 passing tests.
Browser checks and resolved web findings are recorded in
[web-usability-review.md](web-usability-review.md). Connection instructions are
in [local-web.md](local-web.md). Hosted deployment and actual provider integrations
remain out of scope.
