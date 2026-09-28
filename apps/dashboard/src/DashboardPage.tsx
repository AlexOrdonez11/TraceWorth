import { DashboardCreator } from "./DashboardCreator";
import { api } from "./api";
import type { Capabilities } from "./types";
import type { WorkspaceModel } from "./useWorkspaceModel";

export function DashboardPage({
  model,
  config,
}: {
  model: WorkspaceModel;
  config: Capabilities;
}) {
  const {
    page,
    app,
    metrics,
    cohort,
    cohortIndex,
    setCohortIndex,
    selected,
    setPage,
  } = model;
  return (
    <>
      {page === "Dashboards" && config.dashboard_builder_enabled && (
        <>
          {app && metrics?.report.cohorts.length ? (
            <div className="source-panel builder-cohort-picker">
              <span className="status">
                {cohort?.environment === "synthetic-demo"
                  ? "Synthetic demo"
                  : "Recorded telemetry"}
              </span>
              <label htmlFor="dashboard-cohort">
                Environment / configuration
              </label>
              <select
                id="dashboard-cohort"
                value={cohortIndex}
                onChange={(event) => setCohortIndex(Number(event.target.value))}
              >
                {metrics.report.cohorts.map((item, index) => (
                  <option key={index} value={index}>
                    {item.environment} · {item.configuration_id}
                  </option>
                ))}
              </select>
              <p>
                This dashboard shows only the selected cohort, not all activity
                for this application.
              </p>
            </div>
          ) : null}
          <DashboardCreator
            key={selected}
            application={app}
            cohort={cohort}
            cohortLabel={
              cohort
                ? cohort.environment + " · " + cohort.configuration_id
                : undefined
            }
            scope={metrics?.scope}
            request={api}
            onManageApplications={() => setPage("Applications")}
          />
        </>
      )}
    </>
  );
}
