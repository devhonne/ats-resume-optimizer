import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { clearAll, loadJob, loadMaster, loadSettings, loadVersions, saveJob, saveMaster, saveSettings, saveVersions } from "./storage";
import type { Before, Health, Job, Master, Scan, Settings, TailorResult, Version } from "./types";
import { confetti, uid, words } from "./util";
import { Icon } from "./components/Icons";
import { Modal, Toast, useLiquidGlass } from "./components/Ui";
import { ResumeCard } from "./components/ResumeCard";
import { JobCard } from "./components/JobCard";
import { ScoreCard } from "./components/ScoreCard";
import { EnhanceCard } from "./components/EnhanceCard";
import { SidePanel } from "./components/SidePanel";

type Tab = "resume" | "changes" | "review";
const STEPS = ["Resume", "Job", "ATS score", "Enhance", "Review"];

export default function App() {
  useLiquidGlass();
  const [master, setMasterState] = useState<Master | null>(loadMaster);
  const [versions, setVersionsState] = useState<Version[]>(loadVersions);
  const [job, setJobState] = useState<Job>(loadJob);
  const [settings, setSettingsState] = useState<Settings>(loadSettings);
  const [health, setHealth] = useState<Health | null>(null);
  const [scan, setScan] = useState<Scan | null>(null);
  const [before, setBefore] = useState<Before | null>(null);
  const [prompt, setPrompt] = useState("");
  const [scanning, setScanning] = useState(false);
  const [tailoring, setTailoring] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [selected, setSelected] = useState("master");
  const [tab, setTab] = useState<Tab>("resume");
  const [modal, setModal] = useState<"" | "settings" | "paste" | "loading" | "about">("");
  const [reply, setReply] = useState("");
  const [keyInput, setKeyInput] = useState("");
  const [toastMsg, setToastMsg] = useState({ msg: "", err: false });
  const [elapsed, setElapsed] = useState(0);
  const toastTimer = useRef<number>();

  const toast = useCallback((msg: string, err = false) => {
    setToastMsg({ msg, err });
    clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToastMsg({ msg: "", err: false }), err ? 6000 : 2800);
  }, []);

  const setMaster = (m: Master | null) => {
    setMasterState(m); saveMaster(m);
    setScan(null); setBefore(null); setPrompt(""); setSelected("master"); setTab("resume");
  };
  const setVersions = (v: Version[]) => { setVersionsState(v); saveVersions(v); };
  const setJob = (j: Job) => { setJobState(j); saveJob(j); };
  const setSettings = (s: Settings) => { setSettingsState(s); saveSettings(s); };

  useEffect(() => { api<Health>("/api/health").then(setHealth).catch(() => toast("Can't reach the Resume Studios server.", true)); }, [toast]);

  const aiReady = !!settings.key || !!health?.server_ai;
  const aiNote = settings.key ? `Using your own Gemini key · ${settings.model || health?.models[0] || ""}`
    : health?.server_ai ? `Free beta: ${health.ai_per_hour} AI actions/hour. Add your own key in Settings for more.`
    : "Add a free Gemini key in Settings to enable AI features.";

  // step logic
  const jobReady = words(job.jd) >= 15;
  const step = !master ? 1 : !jobReady ? 2 : !scan ? 3 : versions.some((v) => v.company === job.company && v.role === job.role) ? 5 : 4;
  const cardState = (n: number) => (n < step ? "done" : n === step ? "now" : n > step && n > 3 && !scan ? "locked" : "");

  const body = (j: Job = job) => ({ resume: master?.tex || "", jd: j.jd, company: j.company, role: j.role });

  async function runScan(j?: Job) {
    const jj = j || job;
    if (!master) return toast("Add your resume first", true);
    if (words(jj.jd) < 15) return toast("Read a job link or paste the job description first", true);
    setScanning(true);
    try {
      const s = await api<Scan>("/api/scan", body(jj));
      setScan(s); setBefore(null);
      if (!jj.company && s.company && !s.company.startsWith("Unknown")) setJob({ ...jj, company: s.company });
      const p = await api<{ prompt: string }>("/api/prompt", body(jj));
      setPrompt(p.prompt);
      setTimeout(() => document.getElementById("h-score")?.scrollIntoView({ behavior: "smooth", block: "start" }), 100);
    } catch (e) { toast((e as Error).message, true); }
    setScanning(false);
  }

  function addVersion(r: TailorResult, how: string) {
    const v: Version = {
      id: uid(), created: Date.now(), tex: r.tex, notes: r.notes, check: r.check,
      company: job.company, role: job.role, score: (r.scan.ai || r.scan.local).score,
      name: `${job.company || "Company"} · ${job.role || "Role"} · ${how}`,
    };
    setVersions([v, ...versions]);
    setScan(r.scan); setBefore(r.before);
    setSelected(v.id); setTab("review");
    const after = (r.scan.ai || r.scan.local).score, prev = r.before.ai ?? r.before.local;
    if (after > prev) setTimeout(confetti, 600);
    toast(r.repaired ? "Saved. The AI had dropped some of your facts; they were restored automatically" : "Saved in this browser. Review it on the right");
  }

  async function tailor() {
    if (!aiReady) { setModal("settings"); return; }
    setTailoring(true); setModal("loading"); setElapsed(0);
    const t0 = Date.now(); const id = setInterval(() => setElapsed(Math.round((Date.now() - t0) / 1000)), 1000);
    try { addVersion(await api<TailorResult>("/api/tailor", body()), "Gemini"); }
    catch (e) { toast((e as Error).message, true); }
    clearInterval(id); setTailoring(false); setModal("");
  }

  async function saveReply() {
    if (!reply.includes("\\documentclass")) return toast("That doesn't contain a LaTeX resume. Copy the AI's whole reply.", true);
    setModal("");
    try { addVersion(await api<TailorResult>("/api/reply", { ...body(), reply }), "Claude/ChatGPT"); setReply(""); }
    catch (e) { toast((e as Error).message, true); }
  }

  async function restore(v: Version) {
    if (!jobReady) return toast("Load the job for this version first, then restore.", true);
    setRestoring(true);
    try {
      const r = await api<{ tex: string; check: Version["check"]; scan: Scan }>("/api/review", { ...body(), tailored: v.tex, repair: true });
      setVersions(versions.map((x) => (x.id === v.id ? { ...x, tex: r.tex, check: r.check, score: (r.scan.ai || r.scan.local).score } : x)));
      setScan(r.scan);
      toast(r.check && r.check.missing.length ? "Some items are still missing. Check the list" : "All your facts are back", !!r.check?.missing.length);
    } catch (e) { toast((e as Error).message, true); }
    setRestoring(false);
  }

  const copyPrompt = async () => {
    if (!prompt) return toast("Check your ATS score first", true);
    await navigator.clipboard.writeText(prompt); toast("Prompt copied. Paste it into Claude or ChatGPT");
  };

  return (
    <>
      <div className="scene" aria-hidden="true" /><div className="veil" aria-hidden="true" /><div className="mist" aria-hidden="true" />

      <nav className="nav glass" aria-label="Resume Studios">
        <div className="brand"><img className="logo" src="/favicon.png" alt="" /><b>Resume Studios</b><span className="betatag">Beta</span></div>
        <div className="steps glass" role="list" aria-label="Progress">
          {STEPS.map((s, i) => (
            <div key={s} role="listitem" className={`step${i + 1 === step ? " on" : i + 1 < step ? " done" : ""}`}><i>{i + 1}</i><span>{s}</span></div>
          ))}
        </div>
        <div className="navbtns">
          <button className="btn glassbtn sm" onClick={() => setModal("about")}><Icon name="lock" /><span className="lbl">Privacy</span></button>
          <button className="btn glassbtn sm" onClick={() => { setKeyInput(""); setModal("settings"); }}><Icon name="sliders" /><span className="lbl">Settings</span></button>
        </div>
      </nav>

      <main>
        <div className="intro">
          <h1>Match your resume to any job</h1>
          <p>Upload your resume, paste a job link, and see your ATS score. Then tailor it to the job, surfacing the skills you already have without changing who you are.</p>
        </div>
        <div className="grid">
          <div className="col">
            <ResumeCard master={master} onMaster={setMaster} toast={toast} state={cardState(1) as "now"} />
            <JobCard job={job} setJob={setJob} onScan={runScan} scanning={scanning} toast={toast} state={master ? cardState(2) : "locked"} />
            <ScoreCard scan={scan} before={before} scanning={scanning} hasAI={aiReady} onSettings={() => setModal("settings")} state={scan || scanning ? cardState(3) : "locked"} />
            <EnhanceCard prompt={prompt} aiReady={aiReady} aiNote={aiNote} tailoring={tailoring} state={scan ? cardState(4) : "locked"}
              onCopy={copyPrompt} onPaste={() => setModal("paste")} onTailor={tailor} />
          </div>
          <SidePanel master={master} versions={versions} selected={selected} setSelected={(id) => { setSelected(id); if (id === "master") setTab("resume"); }}
            tab={tab} setTab={setTab} onRestore={restore} restoring={restoring} toast={toast}
            onDelete={(v) => { setVersions(versions.filter((x) => x.id !== v.id)); setSelected("master"); toast("Version deleted"); }} />
        </div>
      </main>

      <footer className="beta">
        <span className="pill glass">Public beta {health?.version ? `· v${health.version}` : ""}</span>
        <span><Icon name="lock" /> Your resume stays in this browser. AI features send text to Google Gemini to process it; nothing is saved on our server.</span>
      </footer>

      <Modal open={modal === "settings"} onClose={() => setModal("")} title="Settings">
        <h3>Settings</h3>
        <p>{health?.server_ai ? <>The beta includes <b>{health.ai_per_hour} free AI actions per hour</b>. For more, add your own free Gemini key from <b>aistudio.google.com</b> → Get API key.</> : <>AI features need a Gemini key. Get a free one at <b>aistudio.google.com</b> → Get API key.</>}</p>
        <label className="f">Your Gemini API key (optional)<input type="password" autoComplete="off" value={keyInput} onChange={(e) => setKeyInput(e.target.value)} placeholder={settings.key ? "•••• saved in this browser (paste a new one to replace)" : "Paste key"} /></label>
        <p className="help">Stored only in this browser and sent with your requests. It's never saved on our server.</p>
        <label className="f">Gemini model
          <select value={settings.model} onChange={(e) => setSettings({ ...settings, model: e.target.value })}>
            <option value="">Default ({health?.models[0] || "recommended"})</option>
            {health?.models.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        </label>
        <div className="acts" style={{ justifyContent: "space-between" }}>
          <div className="row">
            {settings.key && <button className="btn quiet danger" onClick={() => { setSettings({ ...settings, key: "" }); toast("Key removed"); }}>Remove my key</button>}
            <button className="btn quiet danger" onClick={() => { clearAll(); location.reload(); }}><Icon name="trash" />Delete all my data</button>
          </div>
          <div className="row">
            <button className="btn" onClick={() => setModal("")}>Cancel</button>
            <button className="btn sun" onClick={() => { if (keyInput.trim()) setSettings({ ...settings, key: keyInput.trim() }); setModal(""); toast("Settings saved"); }}>Save</button>
          </div>
        </div>
      </Modal>

      <Modal open={modal === "paste"} onClose={() => setModal("")} title="Paste the AI's reply">
        <h3>Paste the AI's reply</h3>
        <p>Paste everything Claude or ChatGPT wrote. We pull out the LaTeX, re-score it, and check nothing of yours was removed.</p>
        <textarea value={reply} onChange={(e) => setReply(e.target.value)} placeholder="Ctrl + V" aria-label="AI reply" />
        <div className="acts"><button className="btn" onClick={() => setModal("")}>Cancel</button><button className="btn sun" onClick={saveReply}>Save &amp; check</button></div>
      </Modal>

      <Modal open={modal === "loading"} onClose={() => {}} title="Tailoring" dismissable={false} className="loading">
        <div className="inksun" aria-hidden="true" />
        <h3>Gemini is tailoring your resume…</h3>
        <div className="stages">
          <div className={elapsed < 6 ? "on" : "ok"}>Reading the job and your resume</div>
          <div className={elapsed < 6 ? "" : elapsed < 35 ? "on" : "ok"}>Writing the tailored version</div>
          <div className={elapsed < 35 ? "" : "on"}>Checking every skill is kept</div>
        </div>
        <p className="help">{elapsed}s · usually 20–60 seconds</p>
      </Modal>

      <Modal open={modal === "about"} onClose={() => setModal("")} title="Privacy">
        <h3>Privacy &amp; how it works</h3>
        <p><b>Your resume stays in your browser.</b> Your master resume, tailored versions and settings are saved in this browser's storage only. Our server processes each request in memory and keeps nothing.</p>
        <p><b>AI features</b> (reading job links, converting PDF/DOCX, the Gemini score, auto-tailor, restore) send the needed text to <b>Google Gemini</b>. The local score uses no AI.</p>
        <p><b>Honesty rule:</b> tailoring may reorder and reword, but never removes your facts or adds skills you don't have. Every version is checked and anything new is flagged for you.</p>
        <div className="acts"><button className="btn sun" onClick={() => setModal("")}>Got it</button></div>
      </Modal>

      <Toast msg={toastMsg.msg} err={toastMsg.err} />
      <canvas id="confetti" aria-hidden="true" />
    </>
  );
}
