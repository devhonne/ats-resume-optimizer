import type { Master, Settings, Version, Job } from "./types";

/** Everything personal lives in this browser only. The server stores nothing. */
const K = { master: "rs.master", versions: "rs.versions", settings: "rs.settings", job: "rs.job" };

function get<T>(k: string, fallback: T): T {
  try {
    const v = localStorage.getItem(k);
    return v ? (JSON.parse(v) as T) : fallback;
  } catch {
    return fallback;
  }
}
function set(k: string, v: unknown) {
  try {
    if (v === null) localStorage.removeItem(k);
    else localStorage.setItem(k, JSON.stringify(v));
  } catch {
    /* storage full or blocked: the app still works for this session */
  }
}

export const loadMaster = () => get<Master | null>(K.master, null);
export const saveMaster = (m: Master | null) => set(K.master, m);
export const loadVersions = () => get<Version[]>(K.versions, []);
export const saveVersions = (v: Version[]) => set(K.versions, v.slice(0, 25));
export const loadSettings = () => get<Settings>(K.settings, { key: "", model: "" });
export const saveSettings = (s: Settings) => set(K.settings, s);
export const loadJob = () => get<Job>(K.job, { url: "", company: "", role: "", jd: "" });
export const saveJob = (j: Job) => set(K.job, j);
export function clearAll() {
  Object.values(K).forEach((k) => set(k, null));
}
