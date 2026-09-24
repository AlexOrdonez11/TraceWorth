# React applications and FastAPI: local milestone acceptance

Verified September 16, 2026. Coordinator integrated the React applications and
HTTP exporter; developer implemented the backend; independent tester authored
backend/exporter acceptance tests; usability reviewer reviewed source and
screenshots. The coordinator performed browser interaction checks.

| Requirement | Evidence | Result |
| --- | --- | --- |
| Separate React website and dashboard | Independent Vite workspaces on ports 18768 and 18767; both TypeScript checks and production builds pass | Accepted |
| Python FastAPI backend | `traceworth.backend` serves authenticated API on port 18766 | Accepted |
| Persistent account/application ownership | SQLite account/application queries and 18 backend acceptance tests, including foreign IDs, same event IDs across accounts, and spoofed ownership | Accepted |
| SDK sends events to account metrics | Live uvicorn + public TraceWorth/HttpExporter integration test; second account remains empty | Accepted |
| Auth and ingestion controls | Tests for sessions, logout, expiry, CSRF, origins, password verification, hashed secrets, scoped keys, revocation, atomic validation and replay | Accepted |
| Browser onboarding | Register, empty workspace, add application, create key, hide secret, revoke key, explicit synthetic demo, application selection and refresh exercised | Accepted |
| Browser sign-in/out and persistence | Sign-out shows login; sign-in after backend restart restores two labeled synthetic workflows | Accepted |
| Usable metric details | Native modal state and Escape verified; step IDs, attempts and provider/model usage identities visible | Accepted |
| Responsive layout | Desktop and 390px mobile screenshots inspected; mobile document width remains within viewport | Accepted |
| Documentation and next work | README, local-web guide, architecture, roadmap, agent instructions and usability review updated | Accepted |

Final verification: **77 Python tests passed, no skips**; `npm run typecheck` and
`npm run build` passed for both apps. The test suite emits a dependency
deprecation warning from Starlette's current httpx test client; tests still pass.

Resolved defects: malformed non-ASCII CSRF returned 500; HTTP error responses
were not closed; workflow dialog lacked native modal behavior; service identity
and retry evidence were omitted from detail rendering. Revoke/demo confirmation
uses inline confirmation rather than native browser confirm dialogs.

Full-page browser captures contained stitching repeats. Live DOM counts confirm
exactly one workflow section and one findings section; viewport screenshots are
the reliable layout reference.

The local test workspace is named **Browser QA** and contains synthetic data
only; its generated ingestion key was revoked. New registrations start empty.
No real pilot application's production traffic was integrated in this milestone.

Limits: one owner per account, explicit instrumentation/usage capture, best-effort
HTTP delivery without retry/spool, no recovery/invitations/email verification,
and no production deployment. See [roadmap](roadmap.md) for next work packages.
