import { useEffect, useState } from "react";
import type { Before, Scan, ScanResult } from "../types";
import { tone, verdict } from "../util";

const CIRC = 276.5;

function useCountUp(target: number, key: unknown) {
  const [n, setN] = useState(0);
  useEffect(() => {
    const t0 = performance.now();
    const id = setInterval(() => {
      const k = Math.max(0, Math.min(1, (performance.now() - t0) / 1100));
      setN(Math.round(target * (1 - Math.pow(1 - k, 3))));
      if (k >= 1) clearInterval(id);
    }, 16);
    const done = setTimeout(() => { clearInterval(id); setN(target); }, 1300);
    return () => { clearInterval(id); clearTimeout(done); };
  }, [target, key]);
  return n;
}

function Gauge({ r, label, sub, desc, before, pressed, onClick, spinning, empty }: {
  r: ScanResult | null; label: string; sub: string; desc: string; before?: number | null;
  pressed: boolean; onClick: () => void; spinning: boolean; empty: string;
}) {
  const [offset, setOffset] = useState(CIRC);
  const n = useCountUp(r?.score ?? 0, r);
  useEffect(() => {
    setOffset(CIRC);
    const t = setTimeout(() => setOffset(r ? CIRC - (CIRC * r.score) / 100 : CIRC), 40);
    return () => clearTimeout(t);
  }, [r]);
  const c = r ? tone(r.score) : "var(--faint)";
  const delta = r && before != null ? r.score - before : null;
  return (
    <button className={`gauge${spinning ? " spin" : ""}`} aria-pressed={pressed} onClick={onClick}>
      <div className="enso">
        <svg className="ring" viewBox="0 0 104 104" aria-hidden="true">
          <circle className="track" cx="52" cy="52" r="44" />
          <circle className="arc" cx="52" cy="52" r="44" strokeDasharray={CIRC} style={{ strokeDashoffset: offset, stroke: c }} />
        </svg>
        <div className="num"><div><b>{r ? `${n}%` : "–"}</b><small>{sub}</small></div></div>
      </div>
      <div>
        <h3>{label}</h3>
        <p>{desc}</p>
        <span className="verdict" style={r ? { color: c, background: `color-mix(in srgb,${c} 13%,transparent)` } : { color: "var(--muted)", background: "var(--field)" }}>
          {r ? `${verdict(r.score)} match` : empty}
        </span>
        {delta != null && (
          <span className="delta" style={{ color: delta >= 0 ? "var(--good)" : "var(--bad)" }}>
            {before}% → {r!.score}% ({delta >= 0 ? "+" : ""}{delta})
          </span>
        )}
      </div>
    </button>
  );
}

function Bars({ r }: { r: ScanResult }) {
  const [grow, setGrow] = useState(false);
  useEffect(() => { setGrow(false); const t = setTimeout(() => setGrow(true), 120); return () => clearTimeout(t); }, [r]);
  return (
    <div className="bars">
      {r.parts.map((p, i) => (
        <div className="bar" key={p.id}>
          <div className="lb"><b>{p.name}{p.weight ? ` · ${p.weight}%` : ""}</b><small title={p.detail}>{p.detail}</small></div>
          <div className="tr"><div className="fl" style={{ background: p.pct == null ? "var(--faint)" : tone(p.pct), transform: `scaleX(${grow ? (p.pct ?? 0) / 100 : 0})`, transitionDelay: `${i * 0.12}s` }} /></div>
          <div className="v" style={{ color: p.pct == null ? "var(--faint)" : tone(p.pct) }}>{p.pct == null ? "n/a" : `${p.pct}%`}</div>
        </div>
      ))}
    </div>
  );
}

function Snip({ text, word }: { text: string; word: string }) {
  if (!text) return <span className="help">—</span>;
  const i = text.toLowerCase().indexOf(word.toLowerCase());
  if (i < 0) return <>{text}</>;
  return <>{text.slice(0, i)}<mark>{text.slice(i, i + word.length)}</mark>{text.slice(i + word.length)}</>;
}

interface Props {
  scan: Scan | null; before: Before | null; scanning: boolean; hasAI: boolean;
  onSettings: () => void; state: string;
}

export function ScoreCard({ scan, before, scanning, hasAI, onSettings, state }: Props) {
  const [view, setView] = useState<"ai" | "local">("ai");
  const v = view === "ai" && scan?.ai ? "ai" : "local";
  const r = scan ? (v === "ai" ? scan.ai : scan.local) : null;
  return (
    <section className={`card ${state}`} aria-labelledby="h-score" aria-live="polite">
      <div className="ch"><span className="no">3</span><h2 id="h-score">ATS score</h2></div>
      {!scan ? (
        <div className="waiting">{scanning ? (hasAI ? "Gemini is reading the job and finding its must-have keywords…" : "Scanning your resume…") : <>Your scores appear here after <b>Check ATS score</b>.</>}</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          <div className="gauges">
            <Gauge r={scan.ai} label="Gemini match" sub="Gemini" desc="AI finds the job's must-have and nice-to-have keywords"
              before={before?.ai} pressed={v === "ai"} spinning={scanning}
              onClick={() => (scan.ai ? setView("ai") : onSettings())} empty={scan.ai_error ? "Unavailable" : "Add key in Settings"} />
            <Gauge r={scan.local} label="Local match" sub="Local" desc="Built-in list of 120+ tech keywords, no AI"
              before={before?.local} pressed={v === "local"} spinning={scanning} onClick={() => setView("local")} empty="" />
          </div>
          {scan.ai_error && <div className="source warn"><span>Gemini score unavailable: {scan.ai_error}</span></div>}
          {r && (
            <>
              <div className="sect"><h3>Score breakdown <span className="sp" /><small>{v === "ai" ? "Gemini view" : "Local view"}</small></h3><Bars r={r} /></div>
              <div className="sect">
                <h3>How we matched <span className="sp" /><small>{r.matched.length} found</small></h3>
                <div className="howwrap">
                  <table className="how">
                    <thead><tr><th>Keyword</th><th>Found in your resume</th></tr></thead>
                    <tbody>
                      {r.matched.length === 0 && <tr><td colSpan={2} className="help">No job keywords found yet.</td></tr>}
                      {r.matched.map((m) => (
                        <tr key={m.k}>
                          <td className="k">{m.k}<br /><span className="tagp">{m.p === "required" ? "must-have" : m.p === "preferred" ? "nice-to-have" : "general"}</span></td>
                          <td>
                            {m.section && <><b>{m.section}</b> · </>}
                            <Snip text={m.snip || ""} word={m.via && !/words|spread/.test(m.via) ? m.via : m.k} />
                            {m.via && <div className="via">matched via “{m.via}”</div>}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
              <div className="sect">
                <h3>Not visible in your resume <span className="sp" /><small>{r.missing.length}</small></h3>
                <div className="chips">
                  {r.missing.length === 0 && <span className="help">Nothing missing</span>}
                  {r.missing.map((m, i) => (
                    <span key={m.k} className={`chip ${m.p === "required" ? "req" : m.p === "preferred" ? "pref" : ""}`} style={{ animationDelay: `${Math.min(i, 30) * 30}ms` }}>
                      {m.k}{m.p !== "general" && <span className="t">{m.p === "required" ? "must" : "nice"}</span>}
                    </span>
                  ))}
                </div>
                <div className="legend">
                  <span style={{ ["--c" as string]: "var(--bad)" }}>Must-have · counts 3×</span>
                  <span style={{ ["--c" as string]: "var(--warn)" }}>Nice-to-have · 2×</span>
                  <span style={{ ["--c" as string]: "var(--faint)" }}>General tech term · 1×</span>
                </div>
                <p className="help" style={{ margin: 0 }}>If you truly have one of these, tailoring uses the job's wording for it. If you don't, it stays a gap and is never added.</p>
              </div>
            </>
          )}
        </div>
      )}
    </section>
  );
}
