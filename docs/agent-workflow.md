# Local MVP agent workflow

## Custom dashboard creator milestone — September 27, 2026

The owner requested a more useful public demo and a tool for users to create
their own dashboards. This milestone adds a bounded local MVP: signed-in owners
can save named, application-scoped dashboards assembled from a fixed library of
report widgets, reorder or remove widgets, reopen and edit a saved view, and
delete it. The read-only public demo can try layouts in memory but must not
write to an account or API. Widgets use the bounded received-time assessment;
unknown costs and partial reports remain explicit. No arbitrary query, HTML,
cross-account sharing, or automated recommendations are in scope.

| Task | File owner | Acceptance |
| --- | --- | --- |
| Account-scoped storage/API | Developer: `src/traceworth/backend/` | Ordered SQLite/PostgreSQL migration; strict widget/name bounds; authenticated CRUD with CSRF and exact origin on mutations; application ownership and cross-account isolation; ingestion keys cannot read or write dashboards |
| Dashboard creator and demo redesign | Coordinator: `apps/dashboard/src/`, docs | Widget library, add/remove/reorder/edit/save/delete flow, application selection and empty states; demo offers in-memory customization and clearer narrative; cloud UI gates creator until API advertises support |
| Independent acceptance | Testing agent: `tests/` | CRUD/isolation/CSRF/validation/migration regressions plus actual-browser builder/demo journeys, reload persistence, mobile and no-API public demo |
| Usability review | Reviewer: read-only actual browser | Check creation, editing, deletion, empty/partial data, application switching, demo clarity, keyboard/mobile use, and recovery from failures |

Status: accepted locally. Independent tests passed 162 cases (34 PostgreSQL
integration skips without a disposable test DSN); five builder browser cases
cover persistence, cohort switching, mobile/keyboard operation, demo isolation,
and failed-save retry. The usability reviewer retested at desktop and phone
widths with a disposable SQLite database and found no blocking issue. The
existing staging API remains unchanged until a reviewed migration and separate
release gate. The static demo refresh was published to the staging dashboard
CloudFront distribution; its `/#demo` route was checked after invalidation with
four sample widgets and zero `/api` requests. The hosted authenticated creator
remains gated until the backend migration and API release.

## Landing and demo visualization milestone — September 27, 2026

The owner requested a more polished landing page and account-free demo with
interactive plots, responsive layouts, and animation. Keep all plotted values
derived from the existing synthetic fixture or explicitly illustrative website
examples. Preserve the read-only `#demo` route, no API calls, clear unknown-cost
labels, and the real account workspace behavior. Motion must respect reduced
motion preferences and must not hide essential information.

| Task | File owner | Acceptance |
| --- | --- | --- |
| Landing experience | Coordinator: `apps/website/src/` | Stronger visual hierarchy, responsive navigation, meaningful interactive preview, clear synthetic label and demo CTA |
| Demo visualizations | Developer: `apps/dashboard/src/` | Interactive chart(s) computed from the static assessment fixture, account-free operation, accessible labels and controls, responsive desktop/mobile layout, reduced-motion behavior |
| Independent acceptance | Testing agent: test files only | Verify chart values and interactions across both applications, no API calls, reduced-motion/mobile behavior, existing sign-in and modal regression |
| Usability review | Reviewer: read-only actual browser | Explore website and demo at desktop/mobile widths, keyboard navigation, plot interpretation, animation, synthetic/partial-data caveats and exit recovery |

Status: accepted locally; the dashboard update is published to the existing
staging CloudFront distribution. The website remains a separate local React app.
The independent browser suite passed 11/11 journeys; the full local suite passed
150 tests with 33 PostgreSQL cases skipped because no disposable test server was
configured. Both React typechecks and builds passed. The reviewer traversed the
website and dashboard at 1440, 800, 390, and 320 pixels, including keyboard,
mobile navigation, reduced motion, plot interpretation, and exit recovery. The
mobile table scroll cue and capture-scope headline were fixed and retested.
After CloudFront invalidation, the deployed dashboard opened at `/#demo`, its
plots switched measures and opened workflow detail, both sample applications
loaded, and the browser made no API requests. No MyHandyAI client was connected.

## Read-only dashboard demo milestone — September 27, 2026

The owner wants to evaluate TraceWorth itself before connecting MyHandyAI.
This task adds an unauthenticated, clearly synthetic dashboard example and a
landing-page entry point. MyHandyAI code, AWS account, and Lambda configuration
are outside this milestone. The demo must not create accounts, keys, or stored
events, and the real workspace must still begin with the account's own data.

| Task | File owner | Acceptance |
| --- | --- | --- |
| Dashboard demo and sample report | Developer: `apps/dashboard/src/` | `#demo` opens without sign-in, shows application/workflow examples, recorded and unknown costs, outcomes and findings, marks all content synthetic, and returns to sign-in without writes |
| Independent acceptance | Testing agent: test files only | Browser/API checks prove entry/exit, meaningful example values, no backend mutation, and existing sign-in behavior |
| Landing entry and integration | Coordinator: `apps/website/src/`, documentation | Website links to dashboard demo; build and tests pass; deployed dashboard demo is verified after reviewed release |
| Usability review | Reviewer: read-only browser exploration | Check desktop/mobile demo navigation, scope labels, interpretation, workflow details, and recovery |

Status: accepted locally and published to the existing staging dashboard.
The independent browser suite passed 4/4 journeys with API requests intercepted;
the full local suite passed 143 tests with 33 PostgreSQL cases skipped because
no disposable PostgreSQL test server was configured. TypeScript checks and both
React production builds passed. The usability reviewer traversed the website,
dashboard, workflow details, sign-in exit, API-offline recovery, and mobile view
in the actual browser; the brand-link finding was fixed and retested. The
deployed `/#demo` was checked in Chrome after CloudFront invalidation: HTTP 200,
both applications available, and no API requests. Cloud demo seeding into an
account remains disabled. The preview is not MyHandyAI telemetry.

## LangChain compatibility follow-up — September 27, 2026

The owner clarified that MyHandyAI calls OpenAI through LangChain. A local
`langchain-openai` 1.6.6 / OpenAI Python 3.19.2 `ChatOpenAI.invoke` test returned
model and token usage to LangChain, but TraceWorth emitted only a child operation
span: its adapter inspected the raw response before LangChain parsed it. This
follow-up is limited to supported non-streaming LangChain OpenAI calls. The
developer owns the OpenAI integration module, the independent tester owns
package-backed sync/async acceptance tests, the usability reviewer owns the
onboarding review, and the coordinator owns documentation and final integration.
Acceptance requires no change to the LangChain result or provider exception,
one usage event with the returned model and token counts when present, no
prompt/output/key capture, no duplicate event on repeated parsing, and the
existing direct OpenAI regressions to remain green. Streaming and other
LangChain providers remain outside scope. Status: accepted locally. The
independent tester installed `.[test]` and ran 139 tests with no failures; 33
PostgreSQL tests skipped without a test DSN. The same 19 Lambda/OpenAI tests
passed in an isolated OpenAI Python 2.54.0 + `langchain-openai` 1.6.6
environment. OpenAI Python 3.19.2 + `langchain-openai` 1.6.6 sync/async
`ChatOpenAI` calls, deferred raw parsing, import-time client construction,
provider failures, privacy, and step attribution were verified with mocked
provider HTTP and local ingestion. The usability reviewer retested sync/async
journeys and onboarding wording. No live provider or AWS ingestion was tested.

## Python Lambda integration milestone — September 27, 2026

Scope: reduce the code edits needed for a MyHandyAI staging pilot while keeping
the SDK generic. This is local implementation and verification, not a live AWS
integration. A configuration-based Lambda handler wrapper must preserve the
original handler result/exception, record one root workflow per invocation,
avoid payload and secret capture, and perform a bounded best-effort drain.
An opt-in OpenAI Python SDK adapter should record the returned model and usage
from supported non-streaming calls, if it can be tested against the real SDK
without provider API calls. Streaming, business outcomes, exact costs, and full
method discovery are outside this milestone.

| Task | File owner | Acceptance |
| --- | --- | --- |
| Lambda wrapper and optional OpenAI adapter | Developer: `src/traceworth/integrations/` | Existing handler behavior preserved; sanitized telemetry; opt-in model capture only from verified response fields |
| Independent acceptance | Tester: new integration tests under `tests/` | Success/failure, repeated invocations, config faults, bounded drain, privacy, and real-package OpenAI compatibility if adapter is included |
| Guidance and integration | Coordinator: `docs/aws-lambda-integration.md`, `docs/python-sdk.md`, this record | Reproducible setup and clear pilot/deployment gates; full local regression |
| Onboarding review | Usability reviewer: `docs/lambda-integration-usability-review.md` | Exercise documented local path, report defects, confirm claims and recovery steps |

Status: accepted locally. The independent tester installed `.[test]` and ran
133 tests with no failures; 33 PostgreSQL integration cases skipped because no
test DSN was configured. The new Lambda/OpenAI cases passed against real
OpenAI Python 3.19.2 using mocked provider HTTP and a real loopback ingestion
receiver. The same 13 integration cases passed in an isolated OpenAI Python
2.54.0 environment. The usability reviewer exercised the local handler, failed
handler, invalid telemetry configuration, OpenAI capture, and layer ZIP layout;
the resolved and remaining findings are in
[the Lambda integration review](lambda-integration-usability-review.md).
No live OpenAI API call or AWS Lambda ingestion was claimed. The TraceWorth
cloud staging foundation is deployed but its API/dashboard are not yet running,
and MyHandyAI has not been connected. Live network/WAF access, account/key
creation, and capture-volume reconciliation are the next pilot gates.

## Staging foundation milestone — September 24, 2026

Scope: locally verified Docker/PostgreSQL support and reviewable Terraform for
the generated CloudFront hostname in us-east-2. No AWS apply or deployment is
part of this implementation. Existing SQLite and SDK flows must remain intact.

| Task | File owner | Acceptance |
| --- | --- | --- |
| PostgreSQL, migrations, config, container | Developer: backend, pyproject, Dockerfile, compose | Explicit migrations, non-root image, readiness, persistence, secure cloud defaults |
| Independent acceptance | Tester: tests and staging acceptance record | SQLite regressions, real PostgreSQL isolation/atomicity/replay, image and restart checks |
| Terraform and integration | Coordinator: infra, CI, dashboard, guides | Offline validate, private network/data, scoped IAM, remote state preparation, no cloud mutation |
| Onboarding and browser | Reviewer: staging usability record | Real browser flows, correct SDK endpoint, clear disabled features and query bounds |

Initial blocking findings: dashboard hardcodes a loopback SDK endpoint and offers
signup/demo unconditionally; cloud reports need visible query bounds. Final
evidence belongs in `staging-acceptance.md` and `staging-usability-review.md`.

Final CI recovery is limited to two verification defects: the container smoke
client must rediscover Docker's published port after restart, and the Terraform
lockfiles must include the Linux provider package hash used by GitHub runners.
The tester owns the smoke retest and acceptance record; the developer owns the
provider lockfiles; the coordinator owns publication and hosted verification.
The reviewer checks the deployment guide's claims. Existing browser evidence
remains scoped to the unchanged local UI. Acceptance requires all eight hosted
jobs to pass on the final code revision; an AWS deployment is a separate gate.

Status: accepted locally on September 24. Both CI defects were fixed and
independently retested; all eight hosted jobs passed for implementation commit
`ebee3c7` in [run 36047121331](https://github.com/AlexOrdonez11/TraceWorth/actions/runs/36047121331).
See the acceptance and usability records for exact scope. No AWS resources were
provisioned. The next milestone starts with a reviewed concrete Terraform plan
and then requires the documented real-cloud acceptance checks.

## CI milestone — September 24, 2026

Scope: automated checks for the existing application, with no AWS deployment.

| Task | Owner | Acceptance |
| --- | --- | --- |
| GitHub Actions workflow | Developer | Read-only permissions, pinned actions, Python matrix, React builds, isolated wheel smoke |
| Independent verification | Tester | Full local suite and frontend checks; workflow lint and package smoke |
| Documentation review | Usability reviewer | Commands and claims match workflow; distinguish local checks from hosted results |
| Integration and Linux baseline | Coordinator | Minimum Python version exercised on Linux; publish readiness and limitations recorded |

See [CI guide](ci.md) for activation, reading failures, and future deployment
steps. Docker/PostgreSQL and Terraform gates are covered by the staging
foundation milestone above. Earlier milestone records below remain historical.

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
