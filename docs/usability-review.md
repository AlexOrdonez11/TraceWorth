# Local usability review

Reviewed September 16, 2026 by an independent exploratory reviewer agent.
Scope: the local SDK's command-line application, documentation, and generated
reports. TraceWorth currently has no browser UI to crawl. No live application,
provider, cloud resource, or paid API was exercised.

Snapshot: installed TraceWorth 0.1.0, Python 3.14.0, Windows. The checkout had
no HEAD commit (`git rev-parse --short HEAD` could not resolve a revision).
This is a review of that local working tree, not a release certification.

## Implementation retest

Independently rerun September 16, 2026 after the CLI usability changes. Original
findings below are retained as the historical reproduction record.

| Finding | Retest result |
| --- | --- |
| UX-01 | Passed for the original failing demo: `assess .../traceworth-usability-g8et3lve/events.jsonl --detail` now shows parents first and failed attempt 1 before successful attempt 2, with child indentation. |
| UX-02 | Passed for the demo: default text shows separate input/output quantities (390/130 per cohort) and explicitly labels priced usage as records. JSON retains per-workflow usage. |
| UX-03 | Passed: fresh empty and all-invalid fixtures show “No usable telemetry to assess” and next steps; invalid line details remain visible. |
| UX-04 | Passed after follow-up: descriptive help/example, saved-path stderr confirmation, and new-path collision guidance work. A second `assess --help` retest confirms explicit existing-report replacement and malformed-row exit semantics. |
| UX-05 | Passed: default report puts findings first, detail is opt-in, durations display readable units, and accepted/not accepted/acceptance unknown replace raw Python values. |

Fresh synthetic fixtures were generated in
`C:\Users\ale11\AppData\Local\Temp\traceworth-retest-0d8kqdrl`.
Commands exercised: `demo --output`, default and `--detail` assessments,
empty/all-invalid assessments, `assess --help`, JSON file export, and repeated
demo creation. JSON save confirmation was on stderr with empty stdout. Existing
demo preservation returned exit 2. All successful assessments returned exit 0.
No live integrations were exercised. See [web review](web-usability-review.md)
for the separate web-interface scope and its verification limits.

## Verdict and coverage

No blocking failure was reproduced in the explored paths. The five findings
below are follow-ups; they do not replace independent regression testing or
prove correctness outside the exercised journeys. Production code and tests
were not changed by this review.

Walked README and the local MVP guide, top-level and subcommand help, a fresh
demo, text assessment, JSON file export, repeat demo creation, missing input,
input/output collision, empty input, all-invalid input, and mixed valid/invalid
input. JSON output was parsed independently.

The fresh demo produced 60 valid events and nine workflows across three
application labels. All data, prices, and provider activity were synthetic.
The app labels do not indicate real integrations. Each cohort showed three
completed workflows, one accepted workflow, one failed step, one retry, and
three priced usage records out of four. Recorded estimated cost was 0.05 USD
per cohort, explicitly marked partial.

Strengths: setup guidance distinguishes current features from planned work;
synthetic labels and unknown-cost caveats are visible; failed attempts remain
visible even when a workflow completes; common file errors return code 2
without a traceback. Reusing the demo path and selecting the input file as
report output were both rejected.

## Commands and fixtures

The commands below use the actual temporary directory from this review.
For a fresh review, replace `$reviewDir` with a newly created temporary directory
before generating the demo. Never reuse a user's telemetry file for fixtures.

```powershell
$python = '.\.venv\Scripts\python.exe'
$reviewDir = 'C:\Users\ale11\AppData\Local\Temp\traceworth-usability-g8et3lve'
& $python -m traceworth --help
& $python -m traceworth demo --help
& $python -m traceworth assess --help
& $python -m traceworth demo --output "$reviewDir/events.jsonl"
& $python -m traceworth assess "$reviewDir/events.jsonl"
& $python -m traceworth assess "$reviewDir/events.jsonl" --format json --output "$reviewDir/report.json"
& $python -m traceworth demo --output "$reviewDir/events.jsonl"
& $python -m traceworth assess "$reviewDir/missing.jsonl"
& $python -m traceworth assess "$reviewDir/events.jsonl" --output "$reviewDir/events.jsonl"
& $python -m traceworth assess "$reviewDir/empty.jsonl"
& $python -m traceworth assess "$reviewDir/bad.jsonl"
& $python -m traceworth assess "$reviewDir/mixed.jsonl"
```

The CLI commands were executed via Python subprocesses using the repository
virtual environment; the PowerShell above is their equivalent invocation.
Fixtures were created using Python `Path.write_text`: `empty.jsonl` contained
zero bytes, `bad.jsonl` contained `not json\n`, and `mixed.jsonl` contained that
invalid line followed by all 60 generated event lines. Empty and invalid-input
assessments returned code 0, as currently documented. Mixed input preserved all
60 valid records and reported the invalid line.

## Prioritized findings

### UX-01 — P2 usability defect: steps do not read in execution order

**Reproduce:** assess the generated `events.jsonl` in text format. In this run,
AnalyticsAI workflow `49fb86c3-c444-4033-a3e6-83567cca53fc` displayed successful
attempt 2 before failed attempt 1. Workflow
`b7f8e779-ef73-4d1a-9dd8-8d37db91e6e5` displayed its child before its root.
Fresh demos have random IDs, so the particular inversion can vary.

**Impact:** readers must manually follow parent UUIDs to reconstruct a simple
request. The report can visually imply an incorrect order even though attempts
and references remain accurate. Source inspection confirmed steps are sorted
by step ID rather than execution time.

**Suggested fix:** render parents before children, order siblings by observed
start time with a stable tie-breaker, and indent the hierarchy. Preserve exact
IDs for evidence. Do not infer order for missing timestamps without labeling it.

**Acceptance:** an intentionally reverse-sorted-ID retry fixture displays root,
attempt 1, then attempt 2; orphan and incomplete steps remain visible.
**Disposition:** follow-up, not an accounting blocker.

### UX-02 — P2 usability gap: default text hides captured usage units

**Reproduce:** compare the text assessment with
`cohorts[*].workflows[*].usage` in `report.json`. The AnalyticsAI retry workflow
above contains 200 input tokens and 50 output tokens for
`synthetic / fixture-model` in JSON. The text report does not display these unit
totals; its `Priced observed usage: 3/4` counts records, not tokens.

**Impact:** the default journey does not let a user inspect the quantities that
explain the cost. This is especially limiting for unknown-price usage. The local
guide says reports include grouped usage but does not explain this format gap.

**Suggested fix:** include provider/service/unit totals in text, label the price
coverage ratio as usage records, and keep unlike units separate.

**Acceptance:** text and JSON expose the same workflow usage totals without
turning unknown prices into zero.
**Disposition:** follow-up enhancement; JSON already preserves the measurements.

### UX-03 — P2 enhancement: no-data results need a clear next action

**Reproduce:** assess `empty.jsonl` and `bad.jsonl`. Both return code 0 and show
the normal report heading and assumption footer; the latter also reports its
one invalid line. Neither explicitly says no workflows could be assessed.

**Impact:** a new user can mistake successful command completion for successful
instrumentation and has no direct next step when capture produced no usable data.
The existing exit behavior is documented, so this is not a regression claim.

**Suggested fix:** show a distinct no-assessable-data message with suggestions to
check instrumentation, exporter shutdown/diagnostics, and input format. Consider
an opt-in strict flag for scripts that require valid input.

**Acceptance:** zero valid records explain why no assessment exists; mixed input
still produces a useful partial assessment and reports invalid line locations.
**Disposition:** follow-up enhancement.

### UX-04 — P3 enhancement: help and file-save feedback are sparse

**Reproduce:** run `assess --help`, then assess with `--format json --output`.
Help lists `path`, `--format`, and `--output` without explanatory descriptions;
successful report saving emits no confirmation. Repeating demo creation reports
an operating-system `File exists` message without suggesting a fresh path.

**Impact:** terminal-first users must consult the guide to discover defaults,
output replacement behavior, malformed-row handling, and where their result went.

**Suggested fix:** add argument help and a small example; provide a concise saved
path confirmation on stderr so JSON stdout stays machine-readable; suggest a new
demo output path when a file already exists.

**Acceptance:** help explains defaults and report replacement; successful saved
reports announce their path without contaminating JSON stdout.
**Disposition:** follow-up enhancement.

### UX-05 — P3 enhancement: raw values make reports difficult to scan

**Reproduce:** inspect the default text report. Durations include values such as
`0.06739981472492218`, and feedback appears as `accepted=None`, `True`, or `False`.
Long identifiers and detailed step lines precede each cohort's findings.

**Impact:** important failure, missing-feedback, and unknown-cost findings compete
with implementation-oriented formatting, even for only nine workflows.

**Suggested fix:** round displayed durations while preserving JSON precision,
write `accepted`, `rejected`, and `not recorded`, and offer a concise summary with
findings before optional detail. Preserve completion versus acceptance as separate
signals and keep completeness caveats visible.

**Acceptance:** a reader can distinguish rejected from missing feedback and find
the cohort's main issues without reading every UUID. JSON retains exact values.
**Disposition:** follow-up enhancement.

## Recommended next review

Have the coordinator choose a bounded usability milestone from these findings.
After development and independent testing, repeat these same journeys and record
each finding's retest result. When a browser interface exists, add actual browser
navigation, form/error states, keyboard access, and narrow-screen exploration;
none of those browser behaviors were tested here.
