import { useState } from "react";
import { api } from "../api";
import type { Job } from "../types";
import { words } from "../util";
import { Icon } from "./Icons";

interface Props {
  job: Job;
  setJob: (j: Job) => void;
  onScan: (j?: Job) => void;
  scanning: boolean;
  toast: (msg: string, err?: boolean) => void;
  state: string;
}

export function JobCard({ job, setJob, onScan, scanning, toast, state }: Props) {
  const [mode, setMode] = useState<"link" | "paste">(job.url || !job.jd ? "link" : "paste");
  const [reading, setReading] = useState(false);
  const [open, setOpen] = useState(words(job.jd) > 15);

  async function read() {
    const url = job.url.trim();
    if (!/^https?:\/\//.test(url)) return toast("Paste the full job link (starts with https://)", true);
    setReading(true);
    setOpen(true);
    try {
      const j = await api<{ company: string; title: string; location?: string; description: string; source: string; note?: string }>("/api/job", { url });
      const next: Job = { url, company: j.company || "", role: j.title || "", jd: j.description || "", source: j.source, note: j.note, location: j.location };
      setJob(next);
      toast("Job loaded. Checking your score…");
      onScan(next);
    } catch (e) {
      const m = (e as Error).message;
      toast(m, true);
      if (/paste/i.test(m)) setMode("paste");
    }
    setReading(false);
  }

  return (
    <section className={`card ${state}`} aria-labelledby="h-job">
      <div className="ch">
        <span className="no">2</span>
        <h2 id="h-job">The job</h2>
        <span className="sp" />
        <div className="seg glass" role="group" aria-label="How to add the job">
          <button aria-pressed={mode === "link"} onClick={() => setMode("link")}><Icon name="link" />Job link</button>
          <button aria-pressed={mode === "paste"} onClick={() => { setMode("paste"); setOpen(true); }}><Icon name="paste" />Paste text</button>
        </div>
      </div>

      {mode === "link" && (
        <div>
          <label className="f" htmlFor="url">Job posting link</label>
          <div className="urlrow" style={{ marginTop: 6 }}>
            <input id="url" type="url" inputMode="url" autoComplete="off" value={job.url}
              placeholder="https://… LinkedIn · Naukri · Greenhouse · Lever · company careers page"
              onChange={(e) => setJob({ ...job, url: e.target.value })}
              onKeyDown={(e) => { if (e.key === "Enter") read(); }} />
            <button className="btn sun" onClick={read} disabled={reading}><Icon name="spark" />{reading ? "Reading…" : "Read job"}</button>
          </div>
          <p className="help" style={{ margin: "6px 0 0" }}>We download the page and Gemini pulls out the full description and qualifications.</p>
        </div>
      )}

      {job.source && (
        <div className={`source${job.note ? " warn" : ""}`}>
          <Icon name={job.note ? "alert" : "check"} />
          <span>{job.source}{job.location ? ` · ${job.location}` : ""}{job.note ? ` · ${job.note}` : ""}</span>
        </div>
      )}

      <div className="row">
        <label className="f">Company<input value={job.company} placeholder="e.g. Amazon" onChange={(e) => setJob({ ...job, company: e.target.value })} /></label>
        <label className="f">Role<input value={job.role} placeholder="e.g. SDE I Intern" onChange={(e) => setJob({ ...job, role: e.target.value })} /></label>
      </div>

      <details className="jd" open={open} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
        <summary>Job description <span className="help">· {words(job.jd)} words</span></summary>
        <div className={`scanbox${reading || scanning ? " scanning" : ""}`}>
          <textarea id="jd" aria-label="Job description" value={job.jd}
            placeholder="The job description appears here after Read job, or paste it yourself."
            onChange={(e) => setJob({ ...job, jd: e.target.value, source: undefined })} />
          <div className="brush" aria-hidden="true" />
        </div>
      </details>

      <div className="row" style={{ alignItems: "center" }}>
        <button className="btn ink lg" onClick={() => onScan()} disabled={scanning}><Icon name="search" /><span>{scanning ? "Scanning…" : "Check ATS score"}</span></button>
        <button className="btn quiet sm" onClick={() => setJob({ url: "", company: "", role: "", jd: "" })}>Clear</button>
      </div>
    </section>
  );
}
