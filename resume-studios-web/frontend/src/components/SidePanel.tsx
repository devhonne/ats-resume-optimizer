import { useMemo } from "react";
import { diffLines } from "diff";
import type { Check, Master, Version } from "../types";
import { download, highlightTex, slug } from "../util";
import { Icon } from "./Icons";

type Tab = "resume" | "changes" | "review";

interface Props {
  master: Master | null; versions: Version[]; selected: string; setSelected: (id: string) => void;
  tab: Tab; setTab: (t: Tab) => void;
  onRestore: (v: Version) => void; restoring: boolean; onDelete: (v: Version) => void;
  toast: (msg: string, err?: boolean) => void;
}

function Diff({ a, b }: { a: string; b: string }) {
  const rows = useMemo(() => {
    const out: { t: string; l: string }[] = [];
    let added = 0, removed = 0;
    for (const part of diffLines(a, b)) {
      const lines = part.value.replace(/\n$/, "").split("\n");
      if (part.added) { added += lines.length; lines.forEach((l) => out.push({ t: "+", l })); }
      else if (part.removed) { removed += lines.length; lines.forEach((l) => out.push({ t: "-", l })); }
      else if (lines.length > 6) {
        out.push({ t: " ", l: lines[0] }, { t: " ", l: lines[1] }, { t: "…", l: `${lines.length - 4} unchanged lines` },
          { t: " ", l: lines[lines.length - 2] }, { t: " ", l: lines[lines.length - 1] });
      } else lines.forEach((l) => out.push({ t: " ", l }));
    }
    return { out, added, removed };
  }, [a, b]);
  return (
    <div className="diff">
      <div className="diffsum" style={{ padding: "12px 14px", borderBottom: "1px solid var(--line)", position: "sticky", top: 0, background: "var(--code)" }}>
        <b>vs your master resume</b><span className="a">+{rows.added} added</span><span className="r">−{rows.removed} removed</span><span className="help">lines</span>
      </div>
      {rows.out.map((r, i) => (
        <div key={i} className={r.t === "+" ? "add" : r.t === "-" ? "del" : r.t === "…" ? "gap" : ""}>{r.t === "…" ? `⋯ ${r.l}` : r.l}</div>
      ))}
    </div>
  );
}

function Review({ v, onRestore, restoring }: { v: Version; onRestore: () => void; restoring: boolean }) {
  const c: Check | undefined = v.check;
  if (!c) return <div className="empty">Run an ATS check for this job to review this version.</div>;
  const added = [...c.added_skills.map((s) => ({ s, k: "skill" })),
    ...c.added_keywords.filter((k) => !c.added_skills.some((s) => s.toLowerCase().includes(k))).map((s) => ({ s, k: "keyword" }))];
  const bad = c.missing.length > 0;
  return (
    <div className="review">
      <div className="sect">
        <h3>Facts kept from your master resume</h3>
        <div className="meter">
          <span className="big" style={{ color: bad ? "var(--bad)" : "var(--good)" }}>{c.preserved_pct}%</span>
          <div className="trk"><div className="fl" style={{ width: `${c.preserved_pct}%`, background: bad ? "var(--bad)" : "var(--good)" }} /></div>
        </div>
        <p className="help" style={{ margin: 0 }}>{c.kept} of {c.total} skills, projects, roles and numbers are in this version.</p>
      </div>
      {bad && (
        <div className="sect">
          <h3 style={{ color: "var(--bad)" }}>Removed. These are yours and should be back</h3>
          <ul className="list bad">{c.missing.map((m) => <li key={m.kind + m.item}><Icon name="alert" />{m.item}<small>{m.kind}</small></li>)}</ul>
          <div className="row"><button className="btn sun sm" onClick={onRestore} disabled={restoring}><Icon name="undo" />{restoring ? "Restoring…" : "Restore with Gemini"}</button></div>
        </div>
      )}
      {added.length > 0 && (
        <div className="sect">
          <h3 style={{ color: "var(--warn)" }}>New. Not in your master resume, confirm they're true</h3>
          <ul className="list warn">{added.map((a) => <li key={a.k + a.s}><Icon name="alert" />{a.s}<small>{a.k}</small></li>)}</ul>
          <p className="help" style={{ margin: 0 }}>Keep only what you can explain in an interview. Edit the .tex to remove the rest.</p>
        </div>
      )}
      {!bad && added.length === 0 && <div className="source"><Icon name="check" /><span>Everything from your resume is here, and nothing new was added.</span></div>}
      {v.notes && <div className="sect"><h3>AI notes &amp; real gaps</h3><div className="notes">{v.notes}</div></div>}
    </div>
  );
}

export function SidePanel({ master, versions, selected, setSelected, tab, setTab, onRestore, restoring, onDelete, toast }: Props) {
  const v = versions.find((x) => x.id === selected);
  const tex = v ? v.tex : master?.tex || "";
  const html = useMemo(() => highlightTex(tex), [tex]);
  const issues = v?.check ? v.check.missing.length + v.check.added_skills.length : 0;
  const copy = async () => { await navigator.clipboard.writeText(tex); toast("LaTeX copied. Paste it into Overleaf"); };
  const file = v ? `${slug(v.company || "company")}_${slug(v.role || "role")}.tex` : "master_resume.tex";

  return (
    <aside className="side">
      <section className="card" aria-label="Resume file">
        <div className="ch">
          <div className="tabs glass" role="tablist">
            <button role="tab" aria-selected={tab === "resume"} onClick={() => setTab("resume")}><Icon name="file" />Resume</button>
            <button role="tab" aria-selected={tab === "changes"} onClick={() => setTab("changes")}><Icon name="diff" />Changes</button>
            <button role="tab" aria-selected={tab === "review"} onClick={() => setTab("review")}><Icon name="shield" />Review
              {v?.check && <span className={`cnt${issues ? "" : " ok"}`}>{issues || "✓"}</span>}</button>
          </div>
          <span className="sp" /><span className={`badge${v ? " new" : ""}`}>{v ? "Tailored" : "Master"}</span>
        </div>
        <div className="texbar">
          <label className="sr" htmlFor="ver">Resume version</label>
          <select id="ver" value={selected} onChange={(e) => setSelected(e.target.value)} disabled={!master}>
            <option value="master">{master ? `${master.name} · master (never changed)` : "No resume yet"}</option>
            {versions.map((x) => <option key={x.id} value={x.id}>{x.name}{x.score != null ? ` · ${x.score}%` : ""}</option>)}
          </select>
          <button className="btn sm" onClick={copy} disabled={!tex}><Icon name="copy" />Copy</button>
          <button className="btn sm" onClick={() => download(file, tex)} disabled={!tex}><Icon name="inbox" />.tex</button>
          <a className="btn sm" href="https://www.overleaf.com/project" target="_blank" rel="noreferrer"><Icon name="ext" />Overleaf</a>
          {v && <button className="btn sm quiet danger" onClick={() => onDelete(v)} aria-label="Delete this version"><Icon name="trash" /></button>}
        </div>
        <div className="pane">
          {!master ? (
            <div className="empty"><Icon name="user" />Add your resume on the left. It appears here, and stays in your browser.</div>
          ) : tab === "resume" ? (
            <pre className="tex" dangerouslySetInnerHTML={{ __html: html }} />
          ) : tab === "changes" ? (
            v ? <Diff a={master.tex} b={v.tex} /> : <div className="empty">Pick a tailored version to see exactly what changed from your master resume.</div>
          ) : v ? (
            <Review v={v} onRestore={() => onRestore(v)} restoring={restoring} />
          ) : (
            <div className="empty">After tailoring, this checks that every skill, project and number from your master resume is still there, and lists anything new.</div>
          )}
        </div>
        <p className="help" style={{ margin: 0 }}>PDF: <b>Copy</b> → <b>Overleaf</b> → New project → Blank → paste over everything → Recompile → Download.</p>
      </section>
    </aside>
  );
}
