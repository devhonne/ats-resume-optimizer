"""Resume Studio — local web app (liquid-glass UI) for Honne's ATS scanner + AI tailoring.

Run:  python resume_studio.py      (or double-click "Resume Studio.bat")
Opens in its own Edge app window (falls back to the default browser).
Only listens on 127.0.0.1. Shuts itself down ~30 s after the window is closed.
"""
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

import ats_checker

APP_DIR = os.path.dirname(os.path.abspath(__file__))
UI_FILE = os.path.join(APP_DIR, "studio", "index.html")
RESUMES_DIR = os.path.join(APP_DIR, "resumes")
MASTER = os.path.join(APP_DIR, "main.tex")
JD_FILE = os.path.join(APP_DIR, "job_description.txt")
CONFIG = os.path.join(APP_DIR, "studio_config.json")   # gitignored, holds the API key
MODEL = "claude-opus-5-5"

JOBS = {}                 # job_id -> {"state", "chars", "result", "error"}
LAST_PING = [time.time()]


# ---------------------------------------------------------------- helpers
def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def load_config():
    try:
        return json.loads(read(CONFIG))
    except Exception:
        return {}


def save_config(cfg):
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def api_key():
    return load_config().get("api_key") or os.environ.get("ANTHROPIC_API_KEY")


def slug(text):
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")[:40] or "job"


def header_jd(jd, company, role):
    extra = ""
    if company:
        extra += f"Company: {company}\n"
    if role:
        extra += f"Job Title: {role}\n"
    return extra + jd


def build_prompts(resume_tex, jd, company, role, missing):
    """System + user prompt. Rules come from AGENTS.md so there is one source of truth."""
    agents = os.path.join(APP_DIR, "AGENTS.md")
    rules = read(agents) if os.path.exists(agents) else ""
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

The keyword scanner reports these JD keywords as missing from the master resume:
{", ".join(missing) if missing else "(none)"}
Include a missing keyword only where the master resume gives honest evidence for it.

Return exactly two parts:
<resume>
...the complete tailored LaTeX document, from \\documentclass to \\end{{document}}, one page,
same template and packages...
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
    n = re.search(r"<notes>\s*(.*?)\s*</notes>", text, re.S)
    return tex, (n.group(1).strip() if n else "")


# ---------------------------------------------------------------- actions
def do_scan(resume, jd, company, role):
    jd_full = header_jd(jd, company, role)
    with open(JD_FILE, "w", encoding="utf-8") as f:
        f.write(jd_full)
    r = ats_checker.scan(resume or "main.tex", jd_full)
    r["resume"] = os.path.relpath(r.pop("resume_path"), APP_DIR).replace("\\", "/")
    return r


def make_prompt(jd, company, role):
    base = do_scan("main.tex", jd, company, role)
    system, user = build_prompts(read(MASTER), jd, company or base["company"],
                                 role or base["role"], base["missing"])
    return base, system, user


def save_tailored(reply, jd, company, role, before):
    tex, notes = extract_parts(reply)
    if "\\documentclass" not in tex:
        raise ValueError("That reply doesn't contain a LaTeX resume (no \\documentclass).")
    os.makedirs(RESUMES_DIR, exist_ok=True)
    rel = f"resumes/{slug(company or 'company')}_{slug(role or 'role')}.tex"
    with open(os.path.join(APP_DIR, rel), "w", encoding="utf-8") as f:
        f.write(tex)
    r = do_scan(rel, jd, company, role)
    r.update({"before": before, "notes": notes, "tex": tex, "file": rel})
    return r


def tailor_job(job_id, jd, company, role):
    job = JOBS[job_id]
    try:
        import anthropic
    except ImportError:
        job.update(state="error", error="The 'anthropic' package is missing. Run: pip install anthropic")
        return
    try:
        base, system, user = make_prompt(jd, company, role)
        company, role = company or base["company"], role or base["role"]
        client = anthropic.Anthropic(api_key=api_key())
        with client.beta.messages.stream(
            model=MODEL,
            max_tokens=64000,
            output_config={"effort": "high"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=system,
            messages=[{"role": "user", "content": user}],
        ) as stream:
            job["state"] = "writing"
            for text in stream.text_stream:
                job["chars"] += len(text)
            msg = stream.get_final_message()
        if msg.stop_reason == "refusal":
            raise RuntimeError("Claude declined this request. Try the free Copy-prompt option.")
        if msg.stop_reason == "max_tokens":
            raise RuntimeError("The response was cut off. Please try again.")
        reply = "".join(b.text for b in msg.content if b.type == "text")
        job.update(state="done", result=save_tailored(reply, jd, company, role, base["score"]))
    except anthropic.AuthenticationError:
        job.update(state="error", error="Invalid API key. Check Settings.")
    except anthropic.RateLimitError:
        job.update(state="error", error="Rate limited. Wait a minute and retry.")
    except anthropic.APIConnectionError:
        job.update(state="error", error="Network error. Check your internet connection.")
    except anthropic.APIStatusError as e:
        job.update(state="error", error=f"API error {e.status_code}: {e.message}")
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
        if self.path in ("/", "/index.html"):
            return self._send(200, read(UI_FILE).encode(), "text/html; charset=utf-8")
        if self.path == "/api/init":
            return self._send(200, {
                "resumes": ats_checker.get_resume_files(),
                "jd": read(JD_FILE) if os.path.exists(JD_FILE) else "",
                "has_key": bool(api_key()),
                "pdflatex": bool(shutil.which("pdflatex")),
            })
        if self.path == "/api/ping":
            return self._send(200, {"ok": True})
        if self.path.startswith("/api/job/"):
            job = JOBS.get(self.path.rsplit("/", 1)[-1])
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
                if not api_key():
                    return self._send(400, {"error": "no_key"})
                job_id = uuid.uuid4().hex[:10]
                JOBS[job_id] = {"state": "thinking", "chars": 0, "result": None, "error": None}
                threading.Thread(target=tailor_job, args=(job_id, jd, company, role), daemon=True).start()
                return self._send(200, {"job": job_id})
            if self.path == "/api/save_result":
                before = do_scan("main.tex", jd, company, role)
                company, role = company or before["company"], role or before["role"]
                return self._send(200, save_tailored(b.get("reply", ""), jd, company, role, before["score"]))
            if self.path == "/api/settings":
                cfg = load_config()
                cfg["api_key"] = b.get("api_key", "").strip()
                save_config(cfg)
                return self._send(200, {"has_key": bool(cfg["api_key"])})
            if self.path == "/api/open_folder":
                os.makedirs(RESUMES_DIR, exist_ok=True)
                os.startfile(RESUMES_DIR)
                return self._send(200, {"ok": True})
            if self.path == "/api/compile":
                path = os.path.join(APP_DIR, b.get("file", ""))
                subprocess.run(["pdflatex", "-interaction=nonstopmode", "-output-directory",
                                RESUMES_DIR, path], capture_output=True, text=True)
                pdf = path[:-4] + ".pdf"
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
    edge_paths = [
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
    ]
    for p in edge_paths:
        if os.path.exists(p):
            subprocess.Popen([p, f"--app={url}", "--window-size=1280,820"])
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
