import { useState, type FormEvent } from "react";
import { Brand } from "../../../packages/ui/Brand";
import { api } from "./api";
import { hasWebsite, website } from "./links";
import type { Capabilities, Session } from "./types";

export function Auth({
  done,
  error: initial,
  config,
}: {
  done: (s: Session) => void;
  error: string;
  config: Capabilities;
}) {
  const [register, setRegister] = useState(
      config.registration_enabled && location.hash === "#register",
    ),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(initial);
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setBusy(true);
    setError("");
    try {
      done(
        await api<Session>(
          register ? "/auth/register" : "/auth/login",
          "POST",
          Object.fromEntries(form),
        ),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="auth-page">
      <section className="auth-story">
        <Brand href={website} />
        <div>
          <span className="eyebrow">YOUR APPLICATION, IN PERSPECTIVE</span>
          <h1>
            Understand the work.
            <br />
            See what it costs.
          </h1>
          <p>
            Connect your Python applications and bring recorded workflows,
            usage, and outcomes into one workspace.
          </p>
          <div className="auth-points">
            01 &nbsp;{" "}
            {config.registration_enabled
              ? "Create your workspace"
              : "Sign in to your workspace"}
            <hr />
            02 &nbsp; Connect an application
            <hr />
            03 &nbsp; Explore the evidence
          </div>
        </div>
        <p>
          TraceWorth ·{" "}
          {config.mode === "cloud"
            ? "Private staging pilot"
            : "Local development"}
        </p>
      </section>
      <section className="auth-form-area">
        <div className="auth-form">
          <span className="eyebrow">LET’S GET STARTED</span>
          <h2>{register ? "Create your workspace" : "Welcome back"}</h2>
          <p>
            {register
              ? "A separate home for your applications and telemetry."
              : "Sign in to explore your recorded application activity."}
          </p>
          <form onSubmit={submit}>
            {register && (
              <label>
                Workspace name
                <input
                  name="account_name"
                  required
                  maxLength={80}
                  autoComplete="organization"
                />
              </label>
            )}
            <label>
              Email
              <input name="email" type="email" required autoComplete="email" />
            </label>
            <label>
              Password
              <input
                name="password"
                type="password"
                required
                minLength={register ? 12 : 1}
                maxLength={256}
                autoComplete={register ? "new-password" : "current-password"}
              />
            </label>
            {register && (
              <small>
                Use at least 12 characters. Local accounts do not yet have
                password recovery.
              </small>
            )}
            {error && (
              <p className="error" role="alert">
                {error}
              </p>
            )}
            <button className="button primary" disabled={busy}>
              {busy
                ? "Please wait…"
                : register
                  ? "Create workspace →"
                  : "Sign in →"}
            </button>
          </form>
          {config.registration_enabled ? (
            <p>
              {register ? "Already have a workspace?" : "New to TraceWorth?"}{" "}
              <button
                className="link-button"
                onClick={() => {
                  setRegister(!register);
                  setError("");
                }}
              >
                {register ? "Sign in" : "Create workspace"}
              </button>
            </p>
          ) : (
            <p>
              Access is limited to pilot accounts. Ask your staging
              administrator to create your workspace. Password recovery is not
              available yet.
            </p>
          )}
          <div className="auth-demo">
            <p>
              See a read-only sample first. It uses generated events and
              requires no account.
            </p>
            <a className="button secondary" href="#demo">
              Explore synthetic demo →
            </a>
          </div>
          <a className="text-link" href={website}>
            {hasWebsite ? "← Back to website" : "← Workspace home"}
          </a>
        </div>
      </section>
    </main>
  );
}
