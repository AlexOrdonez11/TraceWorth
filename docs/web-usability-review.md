# Local web usability review

Review date: September 16, 2026. Scope: local landing page and dashboard plus
retest of the original CLI findings. Test records are synthetic, not live
application integrations or evidence of verified optimizations.

## Verification ownership and limits

The independent reviewer executed CLI journeys and inspected HTML/JavaScript.
Its browser session returned `Browser is not available: iab` and then
`No browser is available`. Therefore it cannot claim an independently completed
browser crawl. Browser interaction evidence was collected by the
coordinator, whose browser surface is available. HTTP/source inspection alone
does not establish that a browser interaction passed.

The intended local URL for this review is `http://127.0.0.1:18765`.
Port 8765 was occupied by another application; the coordinator identified and
fixed exclusive binding and verified port-conflict regressions. Do not use the unrelated application as
TraceWorth review evidence.

## Findings sent to the developer

| ID | Priority | Observation and impact | Proposed acceptance |
| --- | --- | --- | --- |
| WEB-01 | P2 | Landing headline “Every workflow. Every cost.” and “Trace the complete path” imply completeness beyond explicit, best-effort telemetry. Source-confirmed copy concern. | Use recorded/observed scope in prominent copy; retain missing-cost and capture caveats. |
| WEB-02 | P2 | The workflow dialog has a visible heading but lacks an explicit accessible name. Source-confirmed accessibility concern. | Add `aria-labelledby="detail-title"` and verify dialog announcement and keyboard dismissal in browser. |
| CLI UX-04 | P3 | Updated help explains fields/default format but initially still omitted report replacement and malformed-row exit semantics. | `assess --help` explains both; saved report feedback remains on stderr. |

No production files were changed by this reviewer. The original CLI findings
and executed retest results are in [usability-review.md](usability-review.md).

Follow-up verification: WEB-01 is corrected in source (“Your workflows.
Recorded costs.” and “Follow the recorded path”). WEB-02 now has
`aria-labelledby="detail-title"`; its runtime keyboard behavior passed the
coordinator's browser check. CLI UX-04 passed a second executed `assess --help` check: report
replacement and successful-exit limitations are now explicit. All five original
CLI findings have passed their explored retest paths.

## Browser acceptance checklist

Coordinator-executed browser results (September 16, 2026):

- [x] Landing call to action opens the dashboard.
- [x] Synthetic source is visibly labeled; cohort switching updates metrics.
- [x] Workflow detail shows ordered steps, usage, and distinct feedback states;
  close button and Escape return to the dashboard.
- [x] Refresh source visibly completes and identifies its source.
- [x] File chooser imports a synthetic event file; empty and malformed inputs
  display useful no-data states and diagnostics.
- [x] JSON download completes with a usable report file.
- [x] Desktop and narrow viewport layouts remain usable with readable controls.

The native file chooser imported both a zero-byte file and a generated 60-event
file. Pasted malformed JSONL exposed a line-1 diagnostic and an actionable empty
state. Refresh switched the uploaded source back to the labeled server demo.
The downloaded report was independently parsed from the Downloads folder: 60
valid events, three cohorts. The browser tool's download-event wait timed out,
so the saved file itself was used as completion evidence.

The workflow dialog visibly ordered parent, failed attempt 1, and successful
attempt 2; it displayed 200 input tokens and 50 output tokens for that synthetic
retry case. Escape dismissed it. Valid WebMCP cohort selection changed visible
state and invalid selection was rejected. No browser console errors were observed.

Independent screenshot inspection found a mobile horizontal scrollbar. The
coordinator traced it to an absolutely positioned table header label escaping
the table's scroll container and fixed the containing block. At a 390px viewport,
document scroll/client widths now both measure 375px (excluding the scrollbar);
the table retains its own intentional horizontal scroll. Landing document widths
also match at that breakpoint. Viewport overrides were reset afterward.

Screenshots are saved locally under `local-demo/web-review/` (ignored generated
artifacts): `landing-desktop.png`, `dashboard-desktop.png`, and
`dashboard-mobile.png`. The independent reviewer inspected the desktop/mobile
dashboard captures; it did not independently drive browser interactions.

Verification: 51 Python tests pass with no skips. An isolated installed wheel
served all page/static/API routes and accepted uploads. These are local pilot
checks, not a full accessibility audit or production load certification.
