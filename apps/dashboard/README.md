# Dashboard application

This is the React account workspace. Vite uses `index.html` only to mount
`src/main.tsx`; the screens and behavior live in React modules under `src/`.

- `App.tsx` restores the session and switches between the synthetic demo,
  authentication, and the signed-in workspace.
- `Auth.tsx` contains registration and sign-in.
- `Workspace.tsx` renders the shared navigation, application selector, and
  workflow detail dialog. `useWorkspaceModel.ts` manages its account-scoped
  data and UI state.
- `OverviewPage.tsx`, `DashboardPage.tsx`, `ApplicationsPage.tsx`, and
  `ApiKeysPage.tsx` render the workspace sections.
- `api.ts` owns same-origin API requests and CSRF handling. `types.ts`
  describes the dashboard's API data.

Run `npm run dev:dashboard` from the repository root with the Python API on
port 18766. `npm run build --workspace @traceworth/dashboard` produces
`apps/dashboard/dist/`; deploy the complete directory, including its hashed
JavaScript and CSS assets, to the dashboard S3 bucket.
