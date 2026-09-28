import { lazy, Suspense, useEffect, useState } from "react";
import { Auth } from "./Auth";
import { Workspace } from "./Workspace";
import { api, clearCsrf, setCsrf } from "./api";
import { website } from "./links";
import type { Capabilities, Session } from "./types";

const DemoWorkspace = lazy(() =>
  import("./DemoWorkspace").then((module) => ({
    default: module.DemoWorkspace,
  })),
);

export function App() {
  const [session, setSession] = useState<Session | null>(null),
    [config, setConfig] = useState<Capabilities | null>(null),
    [ready, setReady] = useState(false),
    [error, setError] = useState("");
  const [isDemo, setIsDemo] = useState(window.location.hash === "#demo");
  async function restore() {
    setError("");
    setReady(false);
    try {
      setConfig(await api<Capabilities>("/config"));
      const s = await api<Session>("/auth/me");
      setCsrf(s.csrf_token);
      setSession(s);
    } catch (e) {
      if (
        !(
          e instanceof Error &&
          /sign in|session|authenticated|authentication/i.test(e.message)
        )
      )
        setError(
          import.meta.env.DEV &&
            e instanceof Error &&
            [
              "Failed to fetch",
              "Unable to reach the API. Retry shortly or contact your administrator.",
            ].includes(e.message)
            ? "The local Python API is unavailable on port 18766."
            : String((e as Error).message),
        );
    } finally {
      setReady(true);
    }
  }
  useEffect(() => {
    const route = () => setIsDemo(window.location.hash === "#demo");
    window.addEventListener("hashchange", route);
    return () => window.removeEventListener("hashchange", route);
  }, []);
  useEffect(() => {
    if (!isDemo) void restore();
  }, [isDemo]);
  useEffect(() => {
    const expired = () => {
      clearCsrf();
      setSession(null);
    };
    window.addEventListener("session-expired", expired);
    return () => window.removeEventListener("session-expired", expired);
  }, []);
  if (isDemo)
    return (
      <Suspense
        fallback={<div className="startup">Opening synthetic demo…</div>}
      >
        <DemoWorkspace website={website} />
      </Suspense>
    );
  if (!ready) return <div className="startup">Opening your workspace…</div>;
  if (!config)
    return (
      <div className="startup">
        <p role="alert">{error || "Workspace configuration is unavailable."}</p>
        {import.meta.env.DEV && (
          <p>
            To use the workspace locally, start the Python API in another
            terminal from the repository root:
            <br />
            <code>
              .\.venv\Scripts\python.exe -m traceworth.backend --port 18766
              --database local-data/traceworth.db
            </code>
          </p>
        )}
        <button className="button primary" onClick={() => void restore()}>
          Retry connection
        </button>
        <button
          className="button secondary"
          onClick={() => {
            window.location.hash = "demo";
          }}
        >
          Explore synthetic demo
        </button>
      </div>
    );
  return session ? (
    <Workspace
      config={config}
      session={session}
      logout={async () => {
        await api("/auth/logout", "POST");
        clearCsrf();
        setSession(null);
      }}
    />
  ) : (
    <Auth
      config={config}
      error={error}
      done={(s) => {
        setCsrf(s.csrf_token);
        setSession(s);
        setError("");
      }}
    />
  );
}
