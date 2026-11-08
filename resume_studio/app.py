"""Resume Studio — local web app for Honne's ATS scanner + AI tailoring.

Run:  python resume_studio/app.py      (or double-click "resume_studio/Resume Studio.bat")
Only listens on 127.0.0.1 and shuts down ~30 s after the window closes.

Folder layout
  resume_studio/   this app: app.py, gemini.py, job_fetch.py, index.html, assets/, config.json*, cache.json*
  ../              offline files: main.tex (master resume), ats_checker.py (local scoring),
                   job_description.txt, resumes/ (tailored outputs)            * = gitignored
"""
import difflib
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

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(APP_DIR)
sys.path.insert(0, ROOT)

import ats_checker   # noqa: E402  (offline scorer lives outside the studio folder)
import gemini        # noqa: E402
import job_fetch     # noqa: E402

UI_FILE = os.path.join(APP_DIR, "index.html")
ASSETS = os.path.join(APP_DIR, "assets")
CONFIG = os.path.join(APP_DIR, "config.json")
CACHE = os.path.join(APP_DIR, "cache.json")
RESUMES_DIR = os.path.join(ROOT, "resumes")
MASTER = os.path.join(ROOT, "main.tex")
JD_FILE = os.path.join(ROOT, "job_description.txt")

JOBS = {}
LAST_PING = [time.time()]
CACHE_LOCK = threading.Lock()
MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".svg": "image/svg+xml", ".webp": "image/webp"}


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
    extra = (f"Company: {company}\n" if company else "") + (f"Job Title: {role}\n" if role else "")
    return extra + jd


def rel(path):
    return os.path.relpath(path, ROOT).replace("\\", "/")


def safe_tex(relpath):
    full = os.path.realpath(os.path.join(ROOT, relpath))
    if not full.startswith(os.path.realpath(ROOT)) or not full.endswith(".tex") or not os.path.exists(full):
        raise FileNotFoundError("file not found")
    return full


def ai_keywords(jd):
    """Gemini must-have/nice-to-have keywords, cached per JD so before/after scores are comparable."""
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
        save_json(CACHE, dict(list(cache.items())[-50:]))
    return kw, None


# ---------------------------------------------------------------- prompts
PRESERVE_RULES = """NON-NEGOTIABLE: this is the candidate's real resume. Do not change who they are.
1. KEEP EVERYTHING. Every skill in the skills section, every project, internship, education entry,
   certification, the patent, every link, and every number/metric must still be in your output.
   You may reorder, regroup and reword them; you may not delete any.
2. ADD NOTHING NEW. No new skills, tools, courses/coursework, dates, availability, locations,
   responsibilities or metrics that are not already in the master resume.
3. Matching the job means: put the most relevant existing items first, and where the candidate
   already has a skill, use the job description's exact wording for it (e.g. "REST APIs" ->
   "RESTful services" if the JD says that). A JD keyword the candidate does not have is a GAP:
   leave it out of the resume and list it in <notes>.
4. Same LaTeX template and packages, one page, compiles as-is."""


def build_prompts(resume_tex, jd, company, role, missing):
    agents = os.path.join(ROOT, "AGENTS.md")
    rules = read(agents) if os.path.exists(agents) else ""
    must = [m["k"] for m in missing if m["p"] == "required"]
    other = [m["k"] for m in missing if m["p"] != "required"]
    system = ("You tailor Devi Sree Honne's LaTeX resume to one job description so it passes ATS keyword "
              "screening and reads well to a recruiter.\n\n" + PRESERVE_RULES + "\n\nProject rules:\n" + rules)
    user = f"""Company: {company or "(see JD)"}
Role: {role or "(see JD)"}

{PRESERVE_RULES}

<master_resume>
{resume_tex}
</master_resume>

<job_description>
{jd}
</job_description>

The ATS scanner reports these JD keywords as not visible in the master resume:
- Must-have: {", ".join(must) if must else "(none)"}
- Other: {", ".join(other) if other else "(none)"}
Use one only if the master resume already proves it (then use the JD's exact wording). Otherwise it is a gap.

Return exactly two parts:
<resume>
...the complete tailored LaTeX document, from \\documentclass to \\end{{document}}...
</resume>
<notes>
- What you reordered or reworded, and which JD keywords that surfaced
- Genuine gaps (JD asks, candidate doesn't have) with one honest way to close each
</notes>"""
    return system, user


REPAIR_PROMPT = """The tailored resume below dropped facts from the candidate's master resume.
Put back every item listed under <missing> in the right section, without removing or rewording
anything else, and without adding anything new. Return only the complete LaTeX document.

<missing>
{missing}
</missing>

<master_resume>
{master}
</master_resume>

<tailored_resume>
{tailored}
</tailored_resume>"""


def extract_parts(text):
    m = re.search(r"<resume>\s*(.*?)\s*</resume>", text, re.S)
    tex = m.group(1) if m else text
    tex = re.sub(r"^```(?:latex|tex)?\s*|\s*```$", "", tex.strip())
    if "\\documentclass" in tex:
        tex = tex[tex.index("\\documentclass"):]
    if "\\end{document}" in tex:
        tex = tex[:tex.index("\\end{document}") + len("\\end{document}")] + "\n"
    n = re.search(r"<notes>\s*(.*?)\s*</notes>", text, re.S)
    return tex, (n.group(1).strip() if n else "")


# ---------------------------------------------------------------- actions
def do_scan(resume, jd, company, role, save_jd=True):
    """Both scores: local (offline keyword list) and Gemini (AI must-have keywords)."""
    jd_full = header_jd(jd, company, role)
    if save_jd:
        with open(JD_FILE, "w", encoding="utf-8") as f:
            f.write(jd_full)
    path = os.path.join(ROOT, resume or "main.tex")
    local = ats_checker.scan(path, jd_full, None)
    kw, err = ai_keywords(jd)
    ai = ats_checker.scan(path, jd_full, kw) if kw else None
    for r in (local, ai):
        if r:
            r["resume"] = rel(r.pop("resume_path"))
    return {"local": local, "ai": ai, "ai_error": err, "resume": rel(path),
            "company": local["company"], "role": local["role"]}


def primary(scan):
    return scan["ai"] or scan["local"]


def make_prompt(jd, company, role):
    base = do_scan("main.tex", jd, company, role)
    p = primary(base)
    system, user = build_prompts(read(MASTER), jd, company or p["company"], role or p["role"], p["missing"])
    return base, system, user


def all_keywords(scan):
    p = primary(scan)
    return [m["k"] for m in p["matched"] + p["missing"]]


def review(tailored_path, scan):
    return ats_checker.compare_resumes(read(MASTER), read(tailored_path), all_keywords(scan))


def repair(tailored_path, check):
    """Ask Gemini to restore dropped facts. Returns the new check."""
    missing = "\n".join(f"- {m['kind']}: {m['item']}" for m in check["missing"])
    reply = gemini.generate(gemini_key(), None, REPAIR_PROMPT.format(
        missing=missing, master=read(MASTER), tailored=read(tailored_path)), model=gemini_model(), timeout=180)
    tex, _ = extract_parts(reply)
    if "\\documentclass" in tex and "\\end{document}" in tex:
        with open(tailored_path, "w", encoding="utf-8") as f:
            f.write(tex)


def save_tailored(reply, jd, company, role, base, auto_repair=False):
    tex, notes = extract_parts(reply)
    if "\\documentclass" not in tex or "\\end{document}" not in tex:
        raise ValueError("That reply doesn't contain a complete LaTeX resume (\\documentclass … \\end{document}).")
    os.makedirs(RESUMES_DIR, exist_ok=True)
    path = os.path.join(RESUMES_DIR, f"{slug(company or 'company')}_{slug(role or 'role')}.tex")
    with open(path, "w", encoding="utf-8") as f:
        f.write(tex)
    check = review(path, base)
    repaired = False
    if auto_repair and check["missing"] and gemini_key():
        try:
            repair(path, check)
            check, repaired = review(path, base), True
        except Exception:
            pass
    after = do_scan(rel(path), jd, company, role)
    return {"scan": after, "before": {"local": base["local"]["score"],
                                      "ai": base["ai"]["score"] if base["ai"] else None},
            "notes": notes, "file": rel(path), "check": check, "repaired": repaired}


def tailor_job(job_id, jd, company, role):
    job = JOBS[job_id]
    try:
        base, system, user = make_prompt(jd, company, role)
        company, role = company or base["company"], role or base["role"]
        job["state"] = "writing"
        reply = gemini.generate(gemini_key(), system, user, model=gemini_model(), timeout=240)
        job["state"] = "checking"
        job.update(state="done", result=save_tailored(reply, jd, company, role, base, auto_repair=True))
    except Exception as e:
        job.update(state="error", error=str(e))


def diff(file):
    a = read(MASTER).splitlines()
    b = read(safe_tex(file)).splitlines()
    rows, added, removed = [], 0, 0
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            n = i2 - i1
            if n > 6:
                rows += [{"t": " ", "l": a[i1]}, {"t": " ", "l": a[i1 + 1]},
                         {"t": "…", "l": f"{n - 4} unchanged lines"},
                         {"t": " ", "l": a[i2 - 2]}, {"t": " ", "l": a[i2 - 1]}]
            else:
                rows += [{"t": " ", "l": x} for x in a[i1:i2]]
            continue
        rows += [{"t": "-", "l": x} for x in a[i1:i2]]
        rows += [{"t": "+", "l": x} for x in b[j1:j2]]
        removed += i2 - i1
        added += j2 - j1
    return {"rows": rows, "added": added, "removed": removed}


# ---------------------------------------------------------------- http
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store" if ctype.startswith(("application/json", "text/html")) else "max-age=3600")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        LAST_PING[0] = time.time()
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path in ("/", "/index.html"):
                return self._send(200, read(UI_FILE).encode(), "text/html; charset=utf-8")
            if u.path.startswith("/assets/"):
                name = os.path.basename(u.path)
                full = os.path.join(ASSETS, name)
                ext = os.path.splitext(name)[1].lower()
                if ext in MIME and os.path.exists(full):
                    with open(full, "rb") as f:
                        return self._send(200, f.read(), MIME[ext])
                return self._send(404, {"error": "not found"})
            if u.path == "/api/init":
                return self._send(200, {
                    "resumes": [f for f in ats_checker.get_resume_files() if f.endswith(".tex")],
                    "jd": read(JD_FILE) if os.path.exists(JD_FILE) else "",
                    "has_key": bool(gemini_key()), "model": gemini_model(), "models": gemini.MODELS,
                    "pdflatex": bool(shutil.which("pdflatex")),
                })
            if u.path == "/api/tex":
                f = q.get("file", ["main.tex"])[0]
                return self._send(200, {"file": f, "tex": read(safe_tex(f))})
            if u.path == "/api/diff":
                return self._send(200, diff(q.get("file", [""])[0]))
            if u.path == "/api/ping":
                return self._send(200, {"ok": True})
            if u.path.startswith("/api/job/"):
                job = JOBS.get(u.path.rsplit("/", 1)[-1])
                return self._send(200 if job else 404, job or {"error": "no such job"})
            self._send(404, {"error": "not found"})
        except FileNotFoundError as e:
            self._send(404, {"error": str(e)})
        except Exception as e:
            self._send(500, {"error": str(e)})

    def do_POST(self):
        LAST_PING[0] = time.time()
        try:
            b = self._body()
            jd, company, role = b.get("jd", ""), b.get("company", "").strip(), b.get("role", "").strip()
            if self.path == "/api/fetch_job":
                return self._send(200, job_fetch.fetch_job(b.get("url", "").strip(), gemini_key(), gemini_model()))
            if self.path == "/api/scan":
                return self._send(200, do_scan(b.get("resume"), jd, company, role))
            if self.path == "/api/prompt":
                _, system, user = make_prompt(jd, company, role)
                return self._send(200, {"prompt": system + "\n\n---\n\n" + user})
            if self.path == "/api/tailor":
                if not gemini_key():
                    return self._send(400, {"error": "no_key"})
                job_id = uuid.uuid4().hex[:10]
                JOBS[job_id] = {"state": "thinking", "result": None, "error": None}
                threading.Thread(target=tailor_job, args=(job_id, jd, company, role), daemon=True).start()
                return self._send(200, {"job": job_id})
            if self.path == "/api/save_result":
                base = do_scan("main.tex", jd, company, role)
                company, role = company or base["company"], role or base["role"]
                return self._send(200, save_tailored(b.get("reply", ""), jd, company, role, base))
            if self.path == "/api/review":
                base = do_scan("main.tex", jd, company, role, save_jd=False)
                path = safe_tex(b.get("file", ""))
                check = review(path, base)
                if b.get("repair") and check["missing"]:
                    if not gemini_key():
                        return self._send(400, {"error": "Add a Gemini key in Settings to auto-restore."})
                    repair(path, check)
                    check = review(path, base)
                return self._send(200, {"check": check, "scan": do_scan(rel(path), jd, company, role, save_jd=False)})
            if self.path == "/api/settings":
                c = cfg()
                if b.get("gemini_key"):
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
                full = safe_tex(b.get("file", ""))
                subprocess.run(["pdflatex", "-interaction=nonstopmode", "-output-directory", RESUMES_DIR, full],
                               capture_output=True, text=True)
                pdf = full[:-4] + ".pdf"
                if not os.path.exists(pdf):
                    return self._send(500, {"error": "pdflatex failed"})
                os.startfile(pdf)
                return self._send(200, {"pdf": rel(pdf)})
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
            subprocess.Popen([p, f"--app={url}", "--window-size=1440,920"])
            return
    webbrowser.open(url)


def watchdog(server):
    while True:
        time.sleep(5)
        busy = any(j["state"] in ("thinking", "writing", "checking") for j in JOBS.values())
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
