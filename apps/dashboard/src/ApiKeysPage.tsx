import { api } from "./api";
import { Empty } from "./Empty";
import type { WorkspaceModel } from "./useWorkspaceModel";

export function ApiKeysPage({ model }: { model: WorkspaceModel }) {
  const {
    page,
    app,
    selected,
    busy,
    token,
    setToken,
    keys,
    confirmation,
    setConfirmation,
    setNotice,
    setError,
    run,
    refresh,
    snippet,
    setPage,
  } = model;
  return (
    <>
      {page === "API keys" &&
        (app ? (
          <>
            <section className="panel setup-panel">
              <h2>Connect {app.name}</h2>
              <p>
                Each key can send events only for <code>{app.slug}</code>. Save
                the secret when it is shown; it cannot be retrieved later.
              </p>
              <form
                className="inline-form"
                onSubmit={(e) => {
                  e.preventDefault();
                  const f = e.currentTarget;
                  const name = new FormData(f).get("name");
                  void run(async () => {
                    const result = await api<{ token: string }>(
                      `/applications/${selected}/keys`,
                      "POST",
                      { name },
                    );
                    setToken(result.token);
                    f.reset();
                    await refresh();
                  });
                }}
              >
                <label>
                  Key name
                  <input
                    name="name"
                    required
                    maxLength={80}
                    placeholder="Local development"
                  />
                </label>
                <button className="button primary" disabled={busy}>
                  Create API key
                </button>
              </form>
              {token && (
                <div className="secret">
                  <strong>Copy this key now</strong>
                  <code>{token}</code>
                  <button
                    className="button secondary"
                    onClick={() => {
                      void navigator.clipboard
                        .writeText(token)
                        .then(() => setNotice("Key copied."))
                        .catch(() =>
                          setError("Select and copy the key manually."),
                        );
                    }}
                  >
                    Copy key
                  </button>{" "}
                  <button className="link-button" onClick={() => setToken("")}>
                    Hide key
                  </button>
                </div>
              )}
              <div className="key-list">
                {keys.map((k) => (
                  <div key={k.id}>
                    <span>
                      <strong>{k.name}</strong>
                      <br />
                      <code>{k.prefix}…</code>
                    </span>
                    <span>
                      {k.revoked_at ? (
                        "Revoked"
                      ) : (
                        <button
                          className="button secondary"
                          disabled={busy}
                          onClick={() => {
                            if (confirmation !== k.id) {
                              setConfirmation(k.id);
                              setNotice(
                                "Click Confirm revoke to stop this key from sending events.",
                              );
                              return;
                            }
                            setConfirmation("");
                            void run(async () => {
                              await api(
                                `/applications/${selected}/keys/${k.id}`,
                                "DELETE",
                              );
                              setToken("");
                              await refresh();
                              setNotice("API key revoked.");
                            });
                          }}
                        >
                          {confirmation === k.id ? "Confirm revoke" : "Revoke"}
                        </button>
                      )}
                    </span>
                  </div>
                ))}
              </div>
            </section>
            <section className="code-card">
              <div className="code-top">
                Python · install traceworth from this repository
              </div>
              <pre>
                <code>{snippet}</code>
              </pre>
            </section>
            <p className="integration-note">
              Set TRACEWORTH_API_KEY in your application's environment. Usage
              and costs are recorded explicitly; instrument the methods you want
              to assess. Delivery is best effort; inspect SDK export_errors.
            </p>
          </>
        ) : (
          <Empty
            title="Choose an application"
            text="Select an application above, or add your first application to create its ingestion key."
            action={() => setPage("Applications")}
            button="Manage applications"
          />
        ))}
    </>
  );
}
