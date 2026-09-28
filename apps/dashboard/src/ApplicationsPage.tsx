import { api } from "./api";
import type { Application } from "./types";
import type { WorkspaceModel } from "./useWorkspaceModel";

export function ApplicationsPage({ model }: { model: WorkspaceModel }) {
  const {
    page,
    apps,
    busy,
    run,
    setSelected,
    setToken,
    refresh,
    setPage,
    setNotice,
    select,
  } = model;
  return (
    <>
      {page === "Applications" && (
        <>
          <section className="panel setup-panel">
            <h2>Add an application</h2>
            <p>Use a stable identifier in your Python SDK configuration.</p>
            <form
              className="inline-form"
              onSubmit={(e) => {
                e.preventDefault();
                const f = e.currentTarget;
                const values = Object.fromEntries(new FormData(f));
                void run(async () => {
                  const data = await api<{ application: Application }>(
                    "/applications",
                    "POST",
                    values,
                  );
                  setSelected(data.application.id);
                  setToken("");
                  await refresh(data.application.id);
                  f.reset();
                  setPage("API keys");
                  setNotice(
                    "Application created. Create a key to connect your SDK.",
                  );
                });
              }}
            >
              <label>
                Name
                <input
                  name="name"
                  placeholder="My Handy AI"
                  required
                  maxLength={80}
                />
              </label>
              <label>
                Application identifier
                <input
                  name="slug"
                  placeholder="my-handy-ai"
                  required
                  maxLength={64}
                  pattern="[a-z0-9]+(-[a-z0-9]+)*"
                  title="Lowercase letters and numbers, separated by hyphens"
                />
              </label>
              <button className="button primary" disabled={busy}>
                Add application
              </button>
            </form>
          </section>
          <div className="app-grid">
            {apps.map((a) => (
              <article className="panel app-card" key={a.id}>
                <span className="app-symbol">▦</span>
                <h2>{a.name}</h2>
                <code>{a.slug}</code>
                <button
                  className="button secondary"
                  disabled={busy}
                  onClick={() => {
                    select(a.id);
                    setPage("Overview");
                  }}
                >
                  View metrics →
                </button>
              </article>
            ))}
          </div>
        </>
      )}
    </>
  );
}
