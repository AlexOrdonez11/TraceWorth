let csrf = "";
export function setCsrf(value: string) {
  csrf = value;
}
export function clearCsrf() {
  csrf = "";
}
export async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const response = await fetch("/api" + path, {
    method,
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      ...(method !== "GET" ? { "X-CSRF-Token": csrf } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (response.status === 204) return undefined as T;
  const data = await response
    .json()
    .catch(() => ({
      detail:
        "Unable to reach the API. Retry shortly or contact your administrator.",
    }));
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith("/auth/"))
      window.dispatchEvent(new Event("session-expired"));
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "Check the form fields and try again.",
    );
  }
  return data;
}
