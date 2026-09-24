# React workspace usability review

Reviewed September 16, 2026. Scope: React website on port 18768, React dashboard
on port 18767, and its account/application journeys backed by the API on 18766.
This review does not replace backend security or ingestion acceptance tests.

## Evidence and ownership

The independent usability reviewer inspected `apps/dashboard/src/main.tsx`,
`workspace.css`, and `apps/website/src/main.tsx`, then rechecked the three fixes
below. Its browser tooling was unavailable, so direct browser interaction was
performed by the coordinator and is attributed accordingly.

The reviewer independently viewed coordinator-supplied screenshots:

- `local-demo/react-review/dashboard-desktop.png`
- `local-demo/react-review/dashboard-mobile.png`

Visible controls, metrics, account/application selectors, synthetic labels, and
cost assumptions have a clear hierarchy. The narrow layout stacks sections and
retains navigation. The workflow table requires horizontal scrolling to reach
all columns. These screenshots alone do not verify keyboard behavior.

Both full-page captures visibly repeat portions of the page, despite the reviewed
source containing one workflow table. This was reported to the coordinator to
distinguish a stitching artifact from actual duplicate content; use live DOM
counts or viewport captures to resolve it before treating the full-page images
as faithful layout evidence.

## Findings and retest

| ID | Priority | Source finding | Resolution and evidence |
| --- | --- | --- | --- |
| REACT-UX-01 | P2 | `<dialog open>` looked modal but did not make the background inert or constrain keyboard focus. | Source now uses a dialog ref with `showModal()` and cancel handling. Coordinator reports actual browser `:modal` state true and Escape closes it. Source fix independently rechecked. |
| REACT-UX-02 | P2 | Usage rows omitted model/service identity, making measurements for multiple services of one provider indistinguishable. | Type and rendering now include `model_or_service` alongside provider, unit, and quantity. Source independently rechecked; coordinator reports full identities visible in browser detail. |
| REACT-UX-03 | P2 | Step detail omitted exact step IDs and explicit attempt numbers, preventing precise matching to finding evidence and retry identification. | Type and rendering now include `step_id` and `attempt_number`. Source independently rechecked. |

All three reported source defects are fixed. No additional blocking source issue
was identified in this bounded review. Focus restoration and repeated Tab cycling
were not independently exercised by this reviewer; the verified browser claim is
limited to the coordinator's modal-state and Escape checks.

## Coordinator-reported browser checks

The coordinator reports successful browser journeys for registration, application
creation, API-key creation and revocation, explicit synthetic-demo seeding, and
viewing metrics. These are actual coordinator browser checks, not inferred from
HTTP responses or reviewer source inspection. Synthetic workflows remain labeled
`synthetic-demo`; they are not real application integrations.

The independent testing agent separately reports 77 passing tests, including SDK
ingestion and account isolation. That result is attributed to the testing agent;
the usability reviewer did not rerun or author those tests in this review.

No production files were edited by the reviewer. This document records the
bounded findings, their fixes, and the distinction between independently reviewed
source/screenshots and coordinator-executed browser behavior.
