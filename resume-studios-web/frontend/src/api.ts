import { loadSettings } from "./storage";

/** Calls the FastAPI backend. Adds the user's own Gemini key/model if they set one. */
export async function api<T>(path: string, body?: unknown): Promise<T> {
  const s = loadSettings();
  const headers: Record<string, string> = {};
  if (s.key) headers["X-Gemini-Key"] = s.key;
  if (s.model) headers["X-Gemini-Model"] = s.model;
  let init: RequestInit = { headers };
  if (body instanceof FormData) init = { method: "POST", headers, body };
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    init = { method: "POST", headers, body: JSON.stringify(body) };
  }
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch {
    throw new Error("Can't reach Resume Studios. Check your connection and try again.");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = (data as { detail?: unknown }).detail;
    const msg = typeof d === "string" ? d : Array.isArray(d) ? "Some input is too long or missing." : `Request failed (${res.status})`;
    throw new Error(msg);
  }
  return data as T;
}
