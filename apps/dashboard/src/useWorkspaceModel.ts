import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { Application, Key, Metrics, Workflow } from "./types";

export function useWorkspaceModel() {
  const [page, setPage] = useState("Overview"),
    [apps, setApps] = useState<Application[]>([]),
    [selected, setSelected] = useState(""),
    [metrics, setMetrics] = useState<Metrics | null>(null),
    [keys, setKeys] = useState<Key[]>([]),
    [token, setToken] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [cohortIndex, setCohortIndex] = useState(0),
    [detail, setDetail] = useState<Workflow | null>(null);
  const [confirmation, setConfirmation] = useState("");
  const dialogRef = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (detail) dialogRef.current?.showModal();
  }, [detail]);
  const app = apps.find((a) => a.id === selected),
    cohort = metrics?.report.cohorts[cohortIndex];
  async function refresh(id = selected) {
    const [a, m, k] = await Promise.all([
      api<{ applications: Application[] }>("/applications"),
      api<Metrics>("/metrics" + (id ? "?application_id=" + id : "")),
      id
        ? api<{ keys: Key[] }>(`/applications/${id}/keys`)
        : Promise.resolve({ keys: [] }),
    ]);
    setApps(a.applications);
    setMetrics(m);
    setKeys(k.keys);
    setCohortIndex(0);
  }
  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    void run(() => refresh(""));
  }, []);
  function select(id: string) {
    setSelected(id);
    setToken("");
    setMetrics(null);
    setKeys([]);
    void run(() => refresh(id));
  }
  const snippet = `import os\nfrom traceworth import TraceWorth, HttpExporter\n\nexporter = HttpExporter(\n    "${window.location.origin}/api/events",\n    os.environ["TRACEWORTH_API_KEY"],\n)\nwith TraceWorth("${app?.slug || "your-application"}", exporter) as trace:\n    with trace.span("my_workflow", workflow=True):\n        # Call your application here\n        pass`;
  return {
    page,
    setPage,
    apps,
    setApps,
    selected,
    setSelected,
    metrics,
    setMetrics,
    keys,
    setKeys,
    token,
    setToken,
    busy,
    setBusy,
    error,
    setError,
    notice,
    setNotice,
    cohortIndex,
    setCohortIndex,
    detail,
    setDetail,
    confirmation,
    setConfirmation,
    dialogRef,
    app,
    cohort,
    refresh,
    run,
    select,
    snippet,
  };
}
export type WorkspaceModel = ReturnType<typeof useWorkspaceModel>;
