export const website =
  import.meta.env.VITE_WEBSITE_URL ||
  (import.meta.env.DEV ? "http://127.0.0.1:18768" : "/");
export const hasWebsite =
  Boolean(import.meta.env.VITE_WEBSITE_URL) || import.meta.env.DEV;
