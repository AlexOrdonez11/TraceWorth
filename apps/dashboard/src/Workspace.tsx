import { Brand } from "../../../packages/ui/Brand";
import { hasWebsite, website } from "./links";
import type { Capabilities, Session } from "./types";
import { OverviewPage } from "./OverviewPage";
import { DashboardPage } from "./DashboardPage";
import { ApplicationsPage } from "./ApplicationsPage";
import { ApiKeysPage } from "./ApiKeysPage";
import { money } from "./money";
import { useWorkspaceModel } from "./useWorkspaceModel";

export function Workspace({
  session,
  logout,
  config,
}: {
  session: Session;
  logout: () => Promise<void>;
  config: Capabilities;
}) {
  const model = useWorkspaceModel();
  const {
    page,
    setPage,
    apps,
    selected,
    metrics,
    setToken,
    busy,
    error,
    notice,
    detail,
    setDetail,
    dialogRef,
    refresh,
    run,
    select,
  } = model;
  return (
    <div className="dashboard-shell">
      <aside className="sidebar">
        <Brand href={website} />
        <p className="workspace-label">WORKSPACE</p>
        <nav>
          {[
            "Overview",
            ...(config.dashboard_builder_enabled ? ["Dashboards"] : []),
            "Applications",
            "API keys",
          ].map((p, i) => (
            <button
              disabled={busy}
              className={"side-link " + (page === p ? "active" : "")}
              aria-current={page === p ? "page" : undefined}
              key={p}
              onClick={() => {
                setPage(p);
                setToken("");
              }}
            >
              <b>
                {
                  (
                    {
                      Overview: "◫",
                      Dashboards: "▤",
                      Applications: "▦",
                      "API keys": "⌘",
                    } as Record<string, string>
                  )[p]
                }
              </b>{" "}
              {p}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <strong>{session.account.name}</strong>
          <p>{session.user.email}</p>
          <button
            className="link-button"
            onClick={() => void run(logout)}
            disabled={busy}
          >
            Sign out
          </button>
        </div>
      </aside>
      <main className="dashboard-main">
        <div className="dashboard-top">
          <span className="breadcrumb">Workspace / {page}</span>
          <span className="local-label">
            ●{" "}
            {config.mode === "cloud"
              ? "Private staging pilot"
              : "Local development"}
          </span>
          <button
            className="mobile-logout link-button"
            onClick={() => void run(logout)}
          >
            Sign out
          </button>
        </div>
        <header className="page-title">
          <div>
            <span className="eyebrow">{session.account.name}</span>
            <h1>
              {page === "Overview"
                ? "Application overview"
                : page === "Dashboards"
                  ? "Your dashboards"
                  : page}
            </h1>
            <p>
              {page === "Overview"
                ? "Follow recorded work, usage, and outcomes."
                : page === "Dashboards"
                  ? "Arrange the evidence into application-specific views."
                  : page === "Applications"
                    ? "Connect each product with its own application identity."
                    : "Control which applications can send telemetry."}
            </p>
          </div>
          <button
            className="button secondary"
            disabled={busy}
            onClick={() => void run(() => refresh())}
          >
            {busy ? "Loading…" : "↻ Refresh"}
          </button>
        </header>
        {error && (
          <p role="alert" className="error">
            {error}
            {metrics &&
              " Previous report remains displayed; refresh to update it."}
          </p>
        )}
        {notice && (
          <p role="status" className="notice">
            {notice}
          </p>
        )}
        <div className="filter-row">
          <label htmlFor="application">Application</label>
          <select
            id="application"
            value={selected}
            disabled={busy}
            onChange={(e) => select(e.target.value)}
          >
            <option value="">All applications</option>
            {apps.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
          <span className="quiet">
            Account-scoped data
            {metrics && (
              <> · Last loaded {new Date(metrics.loaded_at).toLocaleString()}</>
            )}
          </span>
        </div>
        <OverviewPage model={model} config={config} />
        <DashboardPage model={model} config={config} />
        <ApplicationsPage model={model} />
        <ApiKeysPage model={model} />
        <footer className="dashboard-footer">
          <span>TraceWorth · Observed data, explicit assumptions</span>
          <a href={website}>{hasWebsite ? "Website ↗" : "Workspace home"}</a>
        </footer>
      </main>
      {detail && (
        <dialog
          ref={dialogRef}
          onCancel={() => setDetail(null)}
          aria-modal="true"
          aria-labelledby="workflow-heading"
          className="workflow-dialog"
          onKeyDown={(e) => {
            if (e.key === "Escape") setDetail(null);
          }}
        >
          <div className="dialog-header">
            <h2 id="workflow-heading">Workflow details</h2>
            <button
              className="button secondary"
              autoFocus
              onClick={() => setDetail(null)}
            >
              Close
            </button>
          </div>
          <div className="detail-body">
            <p className="detail-id">{detail.workflow_id}</p>
            {detail.steps.map((s) => (
              <article
                className="step-card"
                key={s.step_id}
                style={{ marginLeft: Math.min(s.depth, 4) * 12 }}
              >
                <strong>{s.name}</strong>
                <p className="detail-id">
                  {s.step_id} · Attempt {s.attempt_number}
                </p>
                <p>
                  {s.status} ·{" "}
                  {s.duration_ms === null
                    ? "Duration unknown"
                    : s.duration_ms.toFixed(2) + " ms"}
                </p>
                <p>
                  {s.costs.map(money).join(", ") || "No directly recorded cost"}
                </p>
              </article>
            ))}
            <h3>Recorded usage</h3>
            {detail.usage.map((u, i) => (
              <p key={i}>
                {u.provider} / {u.model_or_service} · {u.unit}: {u.value}
              </p>
            ))}
          </div>
        </dialog>
      )}
    </div>
  );
}
