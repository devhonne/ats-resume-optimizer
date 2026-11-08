export type Priority = "required" | "preferred" | "general";

export interface Match { k: string; p: Priority; via?: string | null; section?: string; snip?: string }
export interface Part { id: string; name: string; weight: number; pct: number | null; detail: string }
export interface ScanResult { company: string; role: string; score: number; parts: Part[]; matched: Match[]; missing: Match[]; ai_keywords: boolean }
export interface Scan { local: ScanResult; ai: ScanResult | null; ai_error: string | null; company: string; role: string }
export interface Before { local: number; ai: number | null }

export interface Check {
  total: number; kept: number; preserved_pct: number;
  missing: { kind: string; item: string }[];
  added_skills: string[]; added_keywords: string[];
}

export interface Master { tex: string; name: string; converted?: boolean; note?: string; saved: number }
export interface Version {
  id: string; name: string; tex: string; created: number;
  company: string; role: string; notes?: string; check?: Check; score?: number;
}
export interface Job { url: string; company: string; role: string; jd: string; source?: string; note?: string; location?: string }
export interface Settings { key: string; model: string }
export interface Health { ok: boolean; version: string; server_ai: boolean; ai_per_hour: number; models: string[] }
export interface TailorResult { tex: string; notes: string; check: Check; repaired: boolean; scan: Scan; before: Before }
