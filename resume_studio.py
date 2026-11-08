"""Resume Studio — local web app (liquid-glass UI) for Honne's ATS scanner + AI tailoring.

Run:  python resume_studio.py      (or double-click "Resume Studio.bat")
Opens in its own Edge app window (falls back to the default browser).
Only listens on 127.0.0.1. Shuts itself down ~30 s after the window is closed.

AI: Google Gemini (key in Settings, stored in gitignored studio_config.json).
 - Smarter scoring: Gemini extracts must-have / nice-to-have keywords from the JD (cached per JD).
 - Auto-tailor: Gemini rewrites main.tex for the JD.
Without a key everything still works: built-in keyword scoring + copy-prompt for Claude/ChatGPT.
"""
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import ats_checker
import gemini

APP_DIR = os.path.dirname(os.path.abspath(__file__))
UI_FILE = os.path.join(APP_DIR, "studio", "index.html")
RESUMES_DIR = os.path.join(APP_DIR, "resumes")
MASTER = os.path.join(APP_DIR, "main.tex")
JD_FILE = os.path.join(APP_DIR, "job_description.txt")
CONFIG = os.path.join(APP_DIR, "studio_config.json")   # gitignored: API key + model
CACHE = os.path.join(APP_DIR, "studio_cache.json")     # gitignored: AI keywords per JD

JOBS = {}
LAST_PING = [time.time()]
CACHE_LOCK = threading.Lock()


# ---------------------------------------------------------------- helpers
def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def load_json(path):
    try:
        return json.loads(read(path))
    except Exception:
        return {}


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def cfg():
    return load_json(CONFIG)


def gemini_key():
    return cfg().get("gemini_key") or os.environ.get("GEMINI_API_KEY")


def gemini_model():
    return cfg().get("gemini_model") or gemini.MODELS[0]


def slug(text):
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")[:40] or "job"


def header_jd(jd, company, role):
    extra = ""
    if company:
        extra += f"Company: {company}\n"
    if role:
        extra += f"Job Title: {role}\n"
    return extra + jd


def ai_keywords(jd):
    """Gemini-extracted keywords for this JD, cached so before/after scores use the same set.
    Returns (keywords_or_None, error_or_None)."""
    key = gemini_key()
    if not key:
        return None, None
    h = hashlib.sha256(jd.strip().encode()).hexdigest()[:16]
    with CACHE_LOCK:
        cache = load_json(CACHE)
        if h in cache:
            return cache[h], None
    try:
        kw = gemini.extract_keywords(key, jd, model=gemini_model())
    except Exception as e:
        return None, str(e)
    with CACHE_LOCK:
        cache = load_json(CACHE)
        cache[h] = kw
        save_json(CACHE, dict(list(cache.items())[-50:]))   # keep the last 50 JDs
    return kw, None


def build_prompts(resume_tex, jd, company, role, missing):
    """System + user prompt. Rules come from AGENTS.md so there is one source of truth."""
    agents = os.path.join(APP_DIR, "AGENTS.md")
    rules = read(agents) if os.path.exists(agents) else ""
    must = [m["k"] for m in missing if m["p"] == "required"]
    other = [m["k"] for m in missing if m["p"] != "required"]
    system = (
        "You tailor Devi Sree Honne's LaTeX resume to a job description so it passes ATS "
        "keyword screening and reads well to a recruiter. Follow these project rules exactly, "
        "especially the truthfulness rules: never invent skills, tools, metrics, or experience.\n\n"
        + rules
    )
    user = f"""Company: {company or "(see JD)"}
Role: {role or "(see JD)"}

<master_resume>
{resume_tex}
</master_resume>

<job_description>
{jd}
</job_description>

The ATS scanner says these JD keywords are missing from the master resume:
- Must-have: {", ".join(must) if must else "(none)"}
- Other: {", ".join(other) if other else "(none)"}
Include a missing keyword only where the master resume gives honest evidence for it
(e.g. use the JD's exact wording for a skill Honne already shows). Otherwise list it as a gap.

Also keep: a summary, skills, projects, experience, education, contact links, and the existing
numbers/metrics (they raise the ATS score). One page.

Return exactly two parts:
<resume>
...the complete tailored LaTeX document, from \\documentclass to \\end{{document}}, same template and packages...
</resume>
<notes>
- Keywords added and where
- Genuine gaps (JD asks, Honne doesn't have) with one honest way to close each
</notes>"""
    return system, user


def extract_parts(text):
    m = re.search(r"<resume>\s*(.*?)\s*</resume>", text, re.S)
    tex = m.group(1) if m else text
    tex = re.sub(r"^```(?:latex|tex)?\s*|\s*```$", "", tex.strip())
    if "\\documentclass" in tex and not tex.lstrip().startswith("\\documentclass"):
        tex = tex[tex.index("\\documentclass"):]
    if "\\end{document}" in tex:
        tex = tex[:tex.index("\\end{document}") + len("\\end{document}")] + "\n"
    n = re.search(r"<notes>\s*(.*?)\s*</notes>", text, re.S)
    return tex, (n.group(1).strip() if n else "")


# ---------------------------------------------------------------- actions
def do_scan(resume, jd, company, role, save_jd=True):
    jd_full = header_jd(jd, company, role)
    if save_jd:
        with open(JD_FILE, "w", encoding="utf-8") as f:
            f.write(jd_full)
    kw, err = ai_keywords(jd)
    r = ats_checker.scan(resume or "main.tex", jd_full, kw)
    r["resume"] = os.path.relpath(r.pop("resume_path"), APP_DIR).replace("\\", "/")
    r["ai_error"] = err
    return r


def make_prompt(jd, company, role):
    base = do_scan("main.tex", jd, company, role)
    system, user = build_prompts(read(MASTER), jd, company or base["company"],
                                 role or base["role"], base["missing"])
    return base, system, user


def save_tailored(reply, jd, company, role, before):
    tex, notes = extract_parts(reply)
    if "\\documentclass" not in tex or "\\end{document}" not in tex:
        raise ValueError("That reply doesn't contain a complete LaTeX resume "
                         "(needs \\documentclass … \\end{document}).")
    os.makedirs(RESUMES_DIR, exist_ok=True)
    rel = f"resumes/{slug(company or 'company')}_{slug(role or 'role')}.tex"
    with open(os.path.join(APP_DIR, rel), "w", encoding="utf-8") as f:
        f.write(tex)
    r = do_scan(rel, jd, company, role)
    r.update({"before": before, "notes": notes, "file": rel})
    return r


def tailor_job(job_id, jd, company, role):
    job = JOBS[job_id]
    try:
        base, system, user = make_prompt(jd, company, role)
        company, role = company or base["company"], role or base["role"]
        job["state"] = "writing"
        reply = gemini.generate(gemini_key(), system, user, model=gemini_model(), timeout=240)
        job.update(state="done", result=save_tailored(reply, jd, company, role, base["score"]))
    except Exception as e:
        job.update(state="error", error=str(e))


# ---------------------------------------------------------------- http
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        LAST_PING[0] = time.time()
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self._send(200, read(UI_FILE).encode(), "text/html; charset=utf-8")
        if path == "/api/init":
            return self._send(200, {
                "resumes": ats_checker.get_resume_files(),
                "jd": read(JD_FILE) if os.path.exists(JD_FILE) else "",
                "has_key": bool(gemini_key()),
                "model": gemini_model(),
                "models": gemini.MODELS,
                "pdflatex": bool(shutil.which("pdflatex")),
            })
        if path == "/api/tex":
            rel = parse_qs(urlparse(self.path).query).get("file", ["main.tex"])[0]
            full = os.path.realpath(os.path.join(APP_DIR, rel))
            if not full.startswith(os.path.realpath(APP_DIR)) or not full.endswith(".tex") or not os.path.exists(full):
                return self._send(404, {"error": "file not found"})
            return self._send(200, {"file": rel, "tex": read(full)})
        if path == "/api/ping":
            return self._send(200, {"ok": True})
        if path.startswith("/api/job/"):
            job = JOBS.get(path.rsplit("/", 1)[-1])
            return self._send(200 if job else 404, job or {"error": "no such job"})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        LAST_PING[0] = time.time()
        try:
            b = self._body()
            jd, company, role = b.get("jd", ""), b.get("company", "").strip(), b.get("role", "").strip()
            if self.path == "/api/scan":
                return self._send(200, do_scan(b.get("resume"), jd, company, role))
            if self.path == "/api/prompt":
                _, system, user = make_prompt(jd, company, role)
                return self._send(200, {"prompt": system + "\n\n---\n\n" + user})
            if self.path == "/api/tailor":
                if not gemini_key():
                    return self._send(400, {"error": "no_key"})
                job_id = uuid.uuid4().hex[:10]
                JOBS[job_id] = {"state": "thinking", "result": None, "error": None, "started": time.time()}
                threading.Thread(target=tailor_job, args=(job_id, jd, company, role), daemon=True).start()
                return self._send(200, {"job": job_id})
            if self.path == "/api/save_result":
                before = do_scan("main.tex", jd, company, role)
                company, role = company or before["company"], role or before["role"]
                return self._send(200, save_tailored(b.get("reply", ""), jd, company, role, before["score"]))
            if self.path == "/api/settings":
                c = cfg()
                if "gemini_key" in b:
                    c["gemini_key"] = b["gemini_key"].strip()
                if b.get("gemini_model"):
                    c["gemini_model"] = b["gemini_model"]
                save_json(CONFIG, c)
                return self._send(200, {"has_key": bool(c.get("gemini_key")), "model": gemini_model()})
            if self.path == "/api/open_folder":
                os.makedirs(RESUMES_DIR, exist_ok=True)
                os.startfile(RESUMES_DIR)
                return self._send(200, {"ok": True})
            if self.path == "/api/compile":
                full = os.path.join(APP_DIR, b.get("file", ""))
                subprocess.run(["pdflatex", "-interaction=nonstopmode", "-output-directory",
                                RESUMES_DIR, full], capture_output=True, text=True)
                pdf = full[:-4] + ".pdf"
                if not os.path.exists(pdf):
                    return self._send(500, {"error": "pdflatex failed"})
                os.startfile(pdf)
                return self._send(200, {"pdf": os.path.relpath(pdf, APP_DIR)})
            self._send(404, {"error": "not found"})
        except Exception as e:
            self._send(500, {"error": str(e)})


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def open_window(url):
    for p in (os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
              os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe")):
        if os.path.exists(p):
            subprocess.Popen([p, f"--app={url}", "--window-size=1400,900"])
            return
    webbrowser.open(url)


def watchdog(server):
    while True:
        time.sleep(5)
        busy = any(j["state"] in ("thinking", "writing") for j in JOBS.values())
        if not busy and time.time() - LAST_PING[0] > 30:
            server.shutdown()
            return


if __name__ == "__main__":
    port = free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"Resume Studio running at {url}  (close the window to quit)")
    if "--no-open" not in sys.argv:
        open_window(url)
        threading.Thread(target=watchdog, args=(server,), daemon=True).start()
    server.serve_forever()
