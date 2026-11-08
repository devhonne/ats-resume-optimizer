import { useRef, useState } from "react";
import { api } from "../api";
import type { Master } from "../types";
import { Icon } from "./Icons";

interface Props {
  master: Master | null;
  onMaster: (m: Master | null) => void;
  toast: (msg: string, err?: boolean) => void;
  state: "now" | "done" | "locked" | "";
}

export function ResumeCard({ master, onMaster, toast, state }: Props) {
  const [busy, setBusy] = useState("");
  const [over, setOver] = useState(false);
  const [pasting, setPasting] = useState(false);
  const [text, setText] = useState("");
  const input = useRef<HTMLInputElement>(null);

  async function upload(f: File) {
    if (f.size > 5 * 1024 * 1024) return toast("That file is larger than 5 MB.", true);
    const isTex = f.name.toLowerCase().endsWith(".tex");
    setBusy(isTex ? "Reading your resume…" : "Gemini is converting your resume to LaTeX, keeping every fact…");
    try {
      const fd = new FormData();
      fd.append("file", f);
      const r = await api<{ tex: string; converted: boolean; note?: string }>("/api/resume/upload", fd);
      onMaster({ tex: r.tex, name: f.name, converted: r.converted, note: r.note, saved: Date.now() });
      toast(r.converted ? "Converted to LaTeX. Check it on the right" : "Resume loaded");
    } catch (e) {
      toast((e as Error).message, true);
    }
    setBusy("");
  }

  async function usePasted() {
    const t = text.trim();
    if (t.length < 200) return toast("Paste your full resume.", true);
    if (t.includes("\\documentclass")) {
      if (!t.includes("\\end{document}")) return toast("That LaTeX is incomplete (missing \\end{document}).", true);
      onMaster({ tex: t, name: "Pasted LaTeX", saved: Date.now() });
      setPasting(false);
      return toast("Resume loaded");
    }
    setBusy("Gemini is converting your resume to LaTeX, keeping every fact…");
    try {
      const r = await api<{ tex: string; converted: boolean; note?: string }>("/api/resume/text", { text: t });
      onMaster({ tex: r.tex, name: "Pasted resume", converted: r.converted, note: r.note, saved: Date.now() });
      setPasting(false);
      toast("Converted to LaTeX. Check it on the right");
    } catch (e) {
      toast((e as Error).message, true);
    }
    setBusy("");
  }

  return (
    <section className={`card ${state}`} aria-labelledby="h-resume">
      <div className="ch">
        <span className="no">1</span>
        <h2 id="h-resume">Your resume</h2>
        <span className="sp" />
        {master && <button className="btn quiet sm" onClick={() => onMaster(null)}>Replace</button>}
      </div>

      {master ? (
        <>
          <div className="mastercard">
            <Icon name="check" />
            <div><b>{master.name}</b><div className="help">Your master resume. Tailoring never edits it, and every version is checked against it.</div></div>
          </div>
          {master.note && <div className="source warn"><Icon name="alert" /><span>{master.note}</span></div>}
        </>
      ) : busy ? (
        <div className="drop" aria-busy="true"><div className="inksun" style={{ width: 56, height: 56 }} /><b>{busy}</b><small>About 20–40 seconds for PDF/DOCX</small></div>
      ) : pasting ? (
        <>
          <label className="f">Paste your resume (LaTeX source or plain text)
            <textarea rows={10} value={text} onChange={(e) => setText(e.target.value)} placeholder="\documentclass… or your resume's text" />
          </label>
          <div className="row">
            <button className="btn sun" onClick={usePasted}><Icon name="check" />Use this resume</button>
            <button className="btn quiet" onClick={() => setPasting(false)}>Cancel</button>
          </div>
        </>
      ) : (
        <>
          <div className={`drop${over ? " over" : ""}`} role="button" tabIndex={0}
            onClick={() => input.current?.click()}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") input.current?.click(); }}
            onDragOver={(e) => { e.preventDefault(); setOver(true); }}
            onDragLeave={() => setOver(false)}
            onDrop={(e) => { e.preventDefault(); setOver(false); const f = e.dataTransfer.files[0]; if (f) upload(f); }}>
            <Icon name="upload" />
            <b>Drop your resume here, or click to choose</b>
            <small>.tex works best · .pdf, .docx, .txt are converted to LaTeX with every fact kept · max 5 MB</small>
          </div>
          <input ref={input} type="file" accept=".tex,.pdf,.docx,.txt,.md" hidden
            onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f); e.target.value = ""; }} />
          <div className="row" style={{ alignItems: "center" }}>
            <button className="btn quiet sm" onClick={() => setPasting(true)}><Icon name="paste" />Paste text instead</button>
            <span className="help"><Icon name="lock" /> Stays in your browser. Not stored on our server.</span>
          </div>
        </>
      )}
    </section>
  );
}
