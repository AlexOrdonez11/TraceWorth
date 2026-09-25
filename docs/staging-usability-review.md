# Staging foundation usability review

Review started September 24, 2026. Scope: Docker/PostgreSQL staging preparation,
configuration, onboarding and recovery instructions, dashboard capability labels,
and preservation of the standalone CLI. No AWS resources were provisioned by
this reviewer. Terraform configuration is not evidence of a deployed service.

## Evidence boundaries

The reviewer read AGENTS.md, the existing AWS staging pilot and CI guides, and
the dashboard source. Browser discovery through `cua.getState()` returned empty
app and browser inventories. This reviewer cannot independently claim browser
coverage; coordinator browser evidence must be attributed separately. A source
review or HTTP request is not a browser acceptance test.

## Findings and current status

| ID | Priority | Reproduction / impact | Status |
| --- | --- | --- | --- |
| STAGE-UX-01 | P2 | Open the API-key onboarding source: the original SDK snippet hardcoded the loopback API port, which would send staging users to their own machine instead of the deployed service. | Source recheck passed: endpoint now derives from the dashboard origin plus `/api/events`. Browser and actual proxy ingestion remain separate acceptance checks. |
| STAGE-UX-02 | P2 | Auth and Overview originally offered registration/demo actions without considering disabled cloud policies. Users could follow unsupported onboarding paths. | Source recheck passed: `/api/config` gates both controls; restricted registration explains contacting the staging administrator and absent password recovery. |
| STAGE-UX-03 | P2 | Bounded staging reports must not look like all-time or complete application totals. | Source recheck passed: scope banner shows received-event window, returned count, limit, possible incomplete workflows and explicit non-all-time wording. Truncation warns against complete accounting. Runtime payload compatibility remains to verify. |
| STAGE-UX-04 | P3 | A failed metrics refresh leaves old metrics visible without explicitly identifying them as the prior report; the initial reviewed UI did not show `loaded_at`. | Source recheck passed: retained metrics have an explicit previous-report message alongside errors, and the last successful load time is displayed. Runtime outage journey remains a separate check. |
| STAGE-UX-05 | P2 documentation | Existing AWS pilot guide says cloud capabilities are absent and describes unbounded queries. Those statements must be reconciled with new code without implying AWS deployment. | Documentation retest passed: pilot guide now links the setup guide, identifies implemented foundation capabilities and bounded snapshots, and preserves explicit unverified-AWS/scheduled-retention/Lambda gates. |
| STAGE-UX-06 | P2 | Bootstrap and the API accept passwords up to 256 characters, but the dashboard input initially limits entry to 128. A valid administrator-created password of 129 characters cannot be entered normally. | Source retest passed: dashboard now allows 256 characters, matching the server contract. Independent tester notified of the boundary case. |

Startup source inspection also confirms unavailable configuration presents an
error and Retry connection, rather than pretending registration is available.
This is a source observation, not a simulated browser-outage result.

The reviewer also identified a production navigation gap: without a separately
deployed marketing website, the original default linked to localhost. Source
recheck confirms production now defaults to workspace home (`/`) with an accurate
label; development retains its separate local website address.

The revised `docs/staging-setup.md` correctly distinguishes Terraform validation
from a real AWS plan and identifies billable resources even at zero API tasks.
Reviewer checked its local Docker/PostgreSQL commands against Compose and its
admin commands against the CLI/wrapper source. It now includes migration order,
bootstrap owner/email input, runtime-role provisioning, password length and
persistence guidance, one-batch retention semantics, frontend build-time URLs,
and preserving the rehearsal volume. These documentation fixes pass source
review; the reviewer did not execute cloud admin commands.

The minor wrapper-region follow-up also passed documentation retest: the guide
now states the defaults (`us-east-2`, profile `traceworth-staging`) and requires
matching `-Region` and `-Profile` arguments when those differ. The earlier AWS
pilot guide's capability and bounded-metrics descriptions are now reconciled.

## Independently executed CLI preservation smoke

Using the repository virtual environment, generated fresh synthetic fixtures in
`C:\Users\ale11\AppData\Local\Temp\traceworth-staging-review-l38dmmav`.

Executed `python -m traceworth` with these arguments:

- `--help`: exit 0.
- `demo --output <temporary-dir>/events.jsonl`: exit 0.
- `assess <temporary-dir>/events.jsonl --output <temporary-dir>/report.txt`: exit 0.
- `assess <temporary-dir>/events.jsonl --format json --output <temporary-dir>/report.json`: exit 0; JSON independently parsed, 60 valid events, zero invalid records, three cohorts.
- Repeated demo to the same temporary path: exit 2, existing data preserved, new-path recovery guidance displayed.
- Assessment of a missing temporary input: exit 2 with a file-not-found message.

The text report was created successfully. All fixture events and prices are
synthetic; this smoke does not establish live application integration or cloud
delivery guarantees.

## Runtime evidence and final review boundary

### Coordinator browser evidence received

Coordinator reports actual browser checks at `http://localhost:18777` against
the tester's real PostgreSQL 16 database and API on port 18776 in **local mode**:

- Signed into a prepared account; its empty state showed zero events and a
  thirty-day received-event window.
- Created application `staging-browser-fixture`; its SDK snippet targeted the
  current dashboard origin at port 18777 followed by `/api/events`.
- Created a disposable ingestion key, hid its one-time secret without printing
  it, and completed the explicit revoke confirmation with visible revoked status.
- Selected the application and confirmed synthetic demo creation explicitly.
  The report showed 12 `synthetic-demo` events, two workflows, one accepted result,
  and 0.04 USD estimated recorded cost.
- Report-window and last-loaded labels were visible; coordinator reports a
  readable 640-pixel view.
- With the PostgreSQL-backed API stopped by the tester, Refresh preserved the
  previous 12-event report and its last-loaded time while explicitly reporting
  the unavailable API and retained previous results. Reloading the page showed
  an unavailable-API message and Retry connection instead of workspace data.
- After the API restarted against the same PostgreSQL fixture with a five-event
  maximum, Retry connection restored the persisted session. The dashboard showed
  five of the twelve events, a visible partial-report warning, incomplete
  accounting guidance, and partial recorded cost.
- Workflow Inspect opened a modal and Escape closed it. Sign out returned to
  the sign-in screen.
- Registering a second disposable account through the browser produced an empty
  account with zero events and no applications. The coordinator signed out and
  closed the temporary review browser when checks finished.

These are coordinator-executed browser checks. This reviewer independently
verified the corresponding source changes, not the interactive journeys. They
do not establish cloud-mode registration restrictions, TLS, or AWS deployment.

Tester reports independent PostgreSQL/TestClient checks for cloud-disabled
endpoints and Secure cookies; these are API tests, not browser verification of
cloud-restricted screens. Actual TLS/CloudFront behavior remains outside this
local milestone. The local-mode checks above do not mark deployed-cloud gates
passed.

All six identified source/documentation findings were corrected and rechecked.
The local browser journeys above have coordinator acceptance evidence; the CLI
smoke and source/documentation review were independently executed by this
reviewer. No remaining blocking usability finding was identified within those
reviewed paths. The reviewer did not execute AWS changes or print key secrets.

Final copy adjustment completed: the heading now says “report limit reached”
and the banner includes the byte limit, so byte-limited responses do not imply
their event count limit was reached. The five-event runtime check above exercised
the event cap, not the byte-cap browser case; byte-cap behavior has separate
independent API tests.
