import { OverviewVisuals } from "./OverviewVisuals";
import { Empty } from "./Empty";
import { api } from "./api";
import type { Capabilities } from "./types";
import type { WorkspaceModel } from "./useWorkspaceModel";
import { money } from "./money";

export function OverviewPage({
  model,
  config,
}: {
  model: WorkspaceModel;
  config: Capabilities;
}) {
  const {
    page,
    metrics,
    cohort,
    busy,
    apps,
    cohortIndex,
    setCohortIndex,
    setDetail,
    setPage,
    app,
    selected,
    confirmation,
    setConfirmation,
    setNotice,
    run,
    refresh,
  } = model;
  return (
    <>
      {page === "Overview" && metrics?.scope && (
        <section className="notice" role="status">
          <strong>
            {metrics.scope.truncated
              ? "Partial report — report limit reached"
              : "Report window"}
          </strong>
          <p>
            Received from {new Date(metrics.scope.since).toLocaleString()} to{" "}
            {new Date(metrics.scope.until).toLocaleString()}. Showing{" "}
            {metrics.scope.returned_events} events, up to{" "}
            {metrics.scope.limit.toLocaleString()}
            {metrics.scope.max_bytes
              ? ` and ${(metrics.scope.max_bytes / 1048576).toFixed(0)} MiB of event data`
              : null}
            . Workflows crossing this window may be incomplete. This is not an
            all-time total.
          </p>
          {metrics.scope.truncated && (
            <p>
              Do not use these totals as complete accounting. Ask your
              administrator for a narrower API report window before drawing
              conclusions.
            </p>
          )}
        </section>
      )}
      {page === "Overview" &&
        (!cohort ? (
          <Empty
            title={
              busy
                ? "Loading your metrics…"
                : "Your application story starts here"
            }
            text={
              apps.length
                ? "Create an API key, instrument your Python application, and send your first workflow."
                : "Add an application to start capturing its workflows, usage, and outcomes."
            }
            action={() => setPage(apps.length ? "API keys" : "Applications")}
            button={
              apps.length ? "Connect your SDK" : "Add your first application"
            }
          />
        ) : (
          <>
            <div className="source-panel">
              <span className="status">
                {cohort.environment === "synthetic-demo"
                  ? "Synthetic demo"
                  : "Recorded telemetry"}
              </span>
              <label htmlFor="cohort">Environment / configuration</label>
              <select
                id="cohort"
                value={cohortIndex}
                onChange={(e) => setCohortIndex(Number(e.target.value))}
              >
                {metrics?.report.cohorts.map((c, i) => (
                  <option key={i} value={i}>
                    {c.application_id} · {c.environment} · {c.configuration_id}
                  </option>
                ))}
              </select>
            </div>
            <OverviewVisuals
              key={`${cohort.application_id}-${cohort.environment}-${cohort.configuration_id}`}
              cohort={cohort}
              synthetic={cohort.environment === "synthetic-demo"}
              onInspectWorkflow={(id) =>
                setDetail(
                  cohort.workflows.find(
                    (workflow) => workflow.workflow_id === id,
                  ) ?? null,
                )
              }
              onBuild={
                config.dashboard_builder_enabled
                  ? () => setPage("Dashboards")
                  : undefined
              }
              buildLabel="Build a dashboard"
            />
            <section className="panel setup-panel">
              <h2>Recorded costs</h2>
              <p>
                Separated by currency and basis. Application-wide coverage is
                unknown.
              </p>
              <div className="cost-grid">
                {cohort.costs.length ? (
                  cohort.costs.map((c, i) => (
                    <article key={i}>
                      <strong>{money(c)}</strong>
                      <p>
                        Per accepted result:{" "}
                        {c.cost_per_accepted_result ?? "Unavailable"}{" "}
                        {c.cost_per_accepted_result ? c.currency : ""}
                      </p>
                    </article>
                  ))
                ) : (
                  <p>No priced usage recorded.</p>
                )}
              </div>
            </section>
            <section className="panel">
              <div className="panel-heading">
                <h2>Workflows</h2>
                <span>{cohort.workflows.length} recorded</span>
              </div>
              <p className="workflow-table-hint">
                Swipe table sideways for recorded cost and Inspect →
              </p>
              <div
                className="table-scroll"
                tabIndex={0}
                role="region"
                aria-label="Workflows table, scroll horizontally for recorded cost and details"
              >
                <table>
                  <thead>
                    <tr>
                      <th>Workflow</th>
                      <th>Status</th>
                      <th>Accepted</th>
                      <th>Recorded cost</th>
                      <th>Details</th>
                    </tr>
                  </thead>
                  <tbody>
                    {cohort.workflows.map((w) => (
                      <tr key={w.workflow_id}>
                        <td>
                          <span className="workflow-name">
                            {w.steps[0]?.name || "Missing root"}
                          </span>
                          <span className="workflow-id">{w.workflow_id}</span>
                        </td>
                        <td>
                          <span className={"status " + w.status}>
                            {w.status}
                          </span>
                        </td>
                        <td>
                          {w.accepted === null
                            ? "Not recorded"
                            : w.accepted
                              ? "Yes"
                              : "No"}
                        </td>
                        <td>
                          {w.costs.map(money).join(", ") || "Not recorded"}
                        </td>
                        <td>
                          <button
                            className="inspect"
                            onClick={() => setDetail(w)}
                          >
                            Inspect
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
            <section className="findings-section">
              <h2>What to investigate</h2>
              <div className="finding-list">
                {cohort.findings.map((f, i) => (
                  <article className="finding-card" key={i}>
                    <span className="finding-symbol">↗</span>
                    <div>
                      <h3>{f.code.replaceAll("_", " ")}</h3>
                      <p>{f.message}</p>
                      <details>
                        <summary>Evidence</summary>
                        {f.evidence.map((id) => (
                          <span className="evidence-id" key={id}>
                            {id}
                          </span>
                        ))}
                      </details>
                    </div>
                  </article>
                ))}
              </div>
            </section>
            <details className="diagnostics">
              <summary>Assessment scope & assumptions</summary>
              {metrics?.report.assumptions.map((a) => (
                <p key={a}>{a}</p>
              ))}
            </details>
          </>
        ))}
      {page === "Overview" && app && config.demo_enabled && (
        <div className="demo-strip">
          <p>
            Want to explore the layout before connecting? Add clearly labeled
            synthetic workflows.
          </p>
          <button
            className="button secondary"
            disabled={busy}
            onClick={() => {
              if (confirmation !== "demo") {
                setConfirmation("demo");
                setNotice(
                  "Click Confirm demo to add synthetic workflows in a separate synthetic-demo environment.",
                );
                return;
              }
              setConfirmation("");
              void run(async () => {
                await api(`/applications/${selected}/demo`, "POST");
                await refresh();
                setNotice("Synthetic demo workflows added.");
              });
            }}
          >
            {confirmation === "demo" ? "Confirm demo" : "Add synthetic demo"}
          </button>
        </div>
      )}
    </>
  );
}
