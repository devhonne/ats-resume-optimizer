"""Resume Studios (desktop) — local web app: ATS score, score-raising suggestions, tailoring, link checks.

Run:  python resume_studio/app.py      (or double-click "resume_studio/Resume Studio.bat")
Only listens on 127.0.0.1 and shuts down ~30 s after the window closes.

Folder layout
  resume_studio/   this app (app.py, gemini.py, job_fetch.py, suggest.py, links.py, resume_parse.py,
                   index.html, assets/, config.json*, cache.json*)                * = gitignored
  ../              offline files: main.tex (default original resume), uploads/ (other originals you
                   upload), ats_checker.py (local scoring), job_description.txt, resumes/ (tailored)

The ORIGINAL resume (main.tex or an upload) is never edited. Tailored copies go to resumes/.
"""
import base64
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
import links         # noqa: E402
import resume_parse  # noqa: E402
import suggest       # noqa: E402

UI_FILE = os.path.join(APP_DIR, "index.html")
ASSETS = os.path.join(APP_DIR, "assets")
CONFIG = os.path.join(APP_DIR, "config.json")
CACHE = os.path.join(APP_DIR, "cache.json")
TEMPLATE = os.path.join(APP_DIR, "template.tex")
RESUMES_DIR = os.path.join(ROOT, "resumes")
UPLOADS_DIR = os.path.join(ROOT, "uploads")
JD_FILE = os.path.join(ROOT, "job_description.txt")
SOURCE_EXT = (".tex", ".txt")

JOBS = {}
LAST_PING = [time.time()]
CACHE_LOCK = threading.Lock()
MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".svg": "image/svg+xml", ".webp": "image/webp"}


# ---------------------------------------------------------------- helpers
def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


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
    return (f"Company: {company}\n" if company else "") + (f"Job Title: {role}\n" if role else "") + jd


def rel(path):
    return os.path.relpath(path, ROOT).replace("\\", "/")


def safe(relpath, dirs=("", "uploads", "resumes")):
    """Resolve a resume path inside ROOT (main.tex, uploads/, resumes/), .tex or .txt only."""
    full = os.path.realpath(os.path.join(ROOT, relpath or "main.tex"))
    parent = os.path.relpath(os.path.dirname(full), os.path.realpath(ROOT)).replace("\\", "/")
    if parent == ".":
        parent = ""
    if parent not in dirs or not full.endswith(SOURCE_EXT) or not os.path.exists(full):
        raise FileNotFoundError(f"resume not found: {relpath}")
    return full


def unique(path):
    base, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(path):
        path = f"{base}_{n}{ext}"
        n += 1
    return path


def list_sources(folder):
    d = os.path.join(ROOT, folder)
    if not os.path.isdir(d):
        return []
    return [f"{folder}/{f}" for f in sorted(os.listdir(d)) if f.endswith(SOURCE_EXT)]


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


# ---------------------------------------------------------------- prompts (full rewrite flow)
PRESERVE_RULES = """NON-NEGOTIABLE: this is the candidate's real resume. Do not change who they are.
1. KEEP EVERYTHING. Every skill in the skills section, every project, internship, education entry,
   certification, award, every link, and every number/metric must still be in your output.
   You may reorder, regroup and reword them; you may not delete any.
2. ADD NOTHING NEW. No new skills, tools, courses/coursework, dates, availability, locations,
   responsibilities or metrics that are not already in the original resume.
3. Matching the job means: put the most relevant existing items first, and where the candidate
   already has a skill, use the job description's exact wording for it. A JD keyword the candidate
   does not have is a GAP: leave it out of the resume and list it in <notes>.
4. Same format (LaTeX template and packages, or plain text), one page."""


def build_prompts(resume_src, jd, company, role, missing):
    must = [m["k"] for m in missing if m["p"] == "required"]
    other = [m["k"] for m in missing if m["p"] != "required"]
    system = ("You tailor a candidate's resume to one job description so it passes ATS keyword screening "
              "and reads well to a recruiter.\n\n" + PRESERVE_RULES)
    user = f"""Company: {company or "(see JD)"}
Role: {role or "(see JD)"}

{PRESERVE_RULES}

<original_resume>
{resume_src}
</original_resume>

<job_description>
{jd}
</job_description>

The ATS scanner reports these JD keywords as not visible in the resume:
- Must-have: {", ".join(must) if must else "(none)"}
- Other: {", ".join(other) if other else "(none)"}
Use one only if the resume already proves it (then use the JD's exact wording). Otherwise it is a gap.

Return exactly two parts:
<resume>
...the complete tailored resume in the same format (for LaTeX: \\documentclass to \\end{{document}})...
</resume>
<notes>
- What you reordered or reworded, and which JD keywords that surfaced
- Genuine gaps (JD asks, candidate doesn't have) with one honest way to close each
</notes>"""
    return system, user


REPAIR_PROMPT = """The tailored resume below dropped facts from the candidate's original resume.
Put back every item listed under <missing> in the right section, without removing or rewording
anything else, and without adding anything new. Return only the complete resume.

<missing>
{missing}
</missing>

<original_resume>
{master}
</original_resume>

<tailored_resume>
{tailored}
</tailored_resume>"""

CONVERT_PROMPT = """Convert this resume into the LaTeX template below.
- Use EVERY fact: name, contact details, links, every skill, job, internship, project, education
  entry, grade, certification, award and number. Do not drop anything. Do not invent anything.
- Group skills as "\\textbf{{Category:}} a, b, c". Drop template sections with no content.
- Escape LaTeX special characters (\\& \\% \\# \\_ \\$). Return only the LaTeX document.

<template>
{template}
</template>

<resume_text>
{text}
</resume_text>"""


def extract_parts(text):
    m = re.search(r"<resume>\s*(.*?)\s*</resume>", text, re.S)
    src = m.group(1) if m else text
    src = re.sub(r"^```(?:latex|tex|text)?\s*|\s*```$", "", src.strip())
    if "\\documentclass" in src:
        src = src[src.index("\\documentclass"):]
        if "\\end{document}" in src:
            src = src[:src.index("\\end{document}") + len("\\end{document}")]
    n = re.search(r"<notes>\s*(.*?)\s*</notes>", text, re.S)
    return src.strip() + "\n", (n.group(1).strip() if n else "")


def valid_output(src, master_path):
    if master_path.endswith(".tex"):
        return "\\documentclass" in src and "\\end{document}" in src
    return len(src.strip()) > 200


# ---------------------------------------------------------------- core actions
def do_scan(resume, jd, company, role, save_jd=True, text=None):
    """Both scores for a resume file (or for `text`): local (offline) and Gemini (AI keywords)."""
    jd_full = header_jd(jd, company, role)
    if save_jd:
        write(JD_FILE, jd_full)
    src = text if text is not None else read(safe(resume))
    local = ats_checker.scan_text(src, jd_full, None)
    kw, err = ai_keywords(jd)
    ai = ats_checker.scan_text(src, jd_full, kw) if kw else None
    return {"local": local, "ai": ai, "ai_error": err, "resume": resume,
            "company": local["company"], "role": local["role"]}


def primary(scan):
    return scan["ai"] or scan["local"]


def all_keywords(scan):
    p = primary(scan)
    return [m["k"] for m in p["matched"] + p["missing"]]


def check(master_path, src, scan):
    return ats_checker.compare_resumes(read(master_path), src, all_keywords(scan))


def tailored_path(master_path, company, role):
    ext = os.path.splitext(master_path)[1]
    return unique(os.path.join(RESUMES_DIR, f"{slug(company or 'company')}_{slug(role or 'role')}{ext}"))


def repair(master_path, tailored_file, chk):
    missing = "\n".join(f"- {m['kind']}: {m['item']}" for m in chk["missing"])
    reply = gemini.generate(gemini_key(), None, REPAIR_PROMPT.format(
        missing=missing, master=read(master_path), tailored=read(tailored_file)), model=gemini_model(), timeout=180)
    src, _ = extract_parts(reply)
    if valid_output(src, master_path):
        write(tailored_file, src)


def save_tailored(reply, b, base, auto_repair=False):
    mpath = safe(b["master"])
    src, notes = extract_parts(reply)
    if not valid_output(src, mpath):
        raise ValueError("That reply doesn't contain a complete resume"
                         + (" (\\documentclass … \\end{document})." if mpath.endswith(".tex") else "."))
    path = tailored_path(mpath, b["company"] or base["company"], b["role"] or base["role"])
    write(path, src)
    chk, repaired = check(mpath, src, base), False
    if auto_repair and chk["missing"] and gemini_key():
        try:
            repair(mpath, path, chk)
            chk, repaired = check(mpath, read(path), base), True
        except Exception:
            pass
    after = do_scan(rel(path), b["jd"], b["company"], b["role"])
    return {"scan": after, "before": {"local": base["local"]["score"], "ai": base["ai"]["score"] if base["ai"] else None},
            "notes": notes, "file": rel(path), "check": chk, "repaired": repaired}


def tailor_job(job_id, b):
    job = JOBS[job_id]
    try:
        base = do_scan(b["master"], b["jd"], b["company"], b["role"])
        p = primary(base)
        system, user = build_prompts(read(safe(b["master"])), b["jd"], b["company"] or p["company"], b["role"] or p["role"], p["missing"])
        job["state"] = "writing"
        reply = gemini.generate(gemini_key(), system, user, model=gemini_model(), timeout=240)
        job["state"] = "checking"
        job.update(state="done", result=save_tailored(reply, b, base, auto_repair=True))
    except Exception as e:
        job.update(state="error", error=str(e))


def make_suggestions(b):
    """Validated, scored suggestions for the working copy (or the original if none yet)."""
    mpath = safe(b["master"])
    working = read(safe(b["file"])) if b.get("file") else read(mpath)
    scan = do_scan(b.get("file") or b["master"], b["jd"], b["company"], b["role"], save_jd=False, text=working)
    jd_full = header_jd(b["jd"], b["company"], b["role"])
    kw, _ = ai_keywords(b["jd"])
    items = suggest.local_suggestions(working, b["jd"], scan)
    ai_error = None
    if gemini_key():
        try:
            for s in gemini.suggest(gemini_key(), working, b["jd"], primary(scan)["missing"], model=gemini_model()):
                s["source"] = "ai"
                items.append(s)
        except Exception as e:
            ai_error = str(e)
    else:
        ai_error = "Add a Gemini key in Settings for AI suggestions. Showing offline suggestions only."
    out = suggest.evaluate(items, read(mpath), working, jd_full, kw, all_keywords(scan))
    return {"suggestions": out, "scan": scan, "ai_error": ai_error}


def apply_suggestion(b):
    """Apply one edit to the working copy (creating it from the original on first accept)."""
    mpath = safe(b["master"])
    if b.get("file"):
        path = safe(b["file"], dirs=("resumes",))
    else:
        path = tailored_path(mpath, b["company"], b["role"])
        write(path, read(mpath))
    prev = read(path)
    span = suggest.locate(prev, b["find"])
    if not span:
        raise ValueError("That text changed since the suggestion was made. Refresh the suggestions.")
    new = prev[:span[0]] + b["replace"] + prev[span[1]:]
    write(path, new)
    scan = do_scan(rel(path), b["jd"], b["company"], b["role"], save_jd=False, text=new)
    kw, _ = ai_keywords(b["jd"])
    pending = suggest.evaluate([dict(s, keep_zero=s.get("type") == "exact") for s in b.get("pending", [])],
                               read(mpath), new, header_jd(b["jd"], b["company"], b["role"]), kw, all_keywords(scan))
    return {"file": rel(path), "previous": prev, "scan": scan, "check": check(mpath, new, scan), "pending": pending}


def diff(master, file):
    a = read(safe(master)).splitlines()
    b = read(safe(file)).splitlines()
    rows, added, removed = [], 0, 0
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            n = i2 - i1
            if n > 6:
                rows += [{"t": " ", "l": a[i1]}, {"t": " ", "l": a[i1 + 1]}, {"t": "…", "l": f"{n - 4} unchanged lines"},
                         {"t": " ", "l": a[i2 - 2]}, {"t": " ", "l": a[i2 - 1]}]
            else:
                rows += [{"t": " ", "l": x} for x in a[i1:i2]]
            continue
        rows += [{"t": "-", "l": x} for x in a[i1:i2]]
        rows += [{"t": "+", "l": x} for x in b[j1:j2]]
        removed += i2 - i1
        added += j2 - j1
    return {"rows": rows, "added": added, "removed": removed}


def upload_resume(b):
    """Save an uploaded/pasted ORIGINAL resume into uploads/. PDFs/DOCX are read locally, or by Gemini
    if local reading fails; with a Gemini key they're converted to LaTeX (every fact kept)."""
    name = os.path.basename(b.get("name") or "pasted.txt")
    if b.get("text"):
        data = b["text"].encode("utf-8")
        name = name if name.endswith((".tex", ".txt")) else ("pasted.tex" if "\\documentclass" in b["text"] else "pasted.txt")
    else:
        data = base64.b64decode(b.get("data", ""))
    stem = slug(os.path.splitext(name)[0])
    kind, text, note = None, None, ""
    try:
        kind, text = resume_parse.read_upload(name, data)
    except ValueError as e:
        if name.lower().endswith(".pdf") and gemini_key():
            kind, text = "pdf", gemini.read_pdf(gemini_key(), data, model=gemini_model())
            note = "Local PDF reading failed, so Gemini read it. "
        else:
            raise e
    if kind == "latex":
        if "\\documentclass" not in text or "\\end{document}" not in text:
            raise ValueError("That .tex file isn't a complete document (needs \\documentclass … \\end{document}).")
        path = unique(os.path.join(UPLOADS_DIR, stem + ".tex"))
        write(path, text)
        return {"master": rel(path), "converted": False, "note": note + "Saved as your original. It will never be edited."}
    if gemini_key():
        reply = gemini.generate(gemini_key(), None, CONVERT_PROMPT.format(template=read(TEMPLATE), text=text),
                                model=gemini_model(), timeout=180)
        src, _ = extract_parts(reply)
        if "\\documentclass" in src and "\\end{document}" in src:
            path = unique(os.path.join(UPLOADS_DIR, stem + ".tex"))
            write(path, src)
            write(unique(os.path.join(UPLOADS_DIR, stem + "_original_text.txt")), text)
            return {"master": rel(path), "converted": True,
                    "note": note + f"Converted from {kind.upper()} to LaTeX with Gemini. Check it on the right; "
                                   "the extracted text is saved next to it."}
    path = unique(os.path.join(UPLOADS_DIR, stem + ".txt"))
    write(path, text)
    return {"master": rel(path), "converted": False,
            "note": note + "Saved as plain text (add a Gemini key to convert it to LaTeX). Scoring and suggestions work on it."}


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
        b = json.loads(self.rfile.read(n) or b"{}")
        for k in ("jd", "company", "role"):
            b[k] = (b.get(k) or "").strip() if k != "jd" else (b.get(k) or "")
        b["master"] = b.get("master") or "main.tex"
        return b

    def do_GET(self):
        LAST_PING[0] = time.time()
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path in ("/", "/index.html"):
                return self._send(200, read(UI_FILE).encode(), "text/html; charset=utf-8")
            if u.path.startswith("/assets/"):
                name = os.path.basename(u.path)
                full, ext = os.path.join(ASSETS, name), os.path.splitext(name)[1].lower()
                if ext in MIME and os.path.exists(full):
                    with open(full, "rb") as f:
                        return self._send(200, f.read(), MIME[ext])
                return self._send(404, {"error": "not found"})
            if u.path == "/api/init":
                masters = (["main.tex"] if os.path.exists(os.path.join(ROOT, "main.tex")) else []) + \
                          [f for f in list_sources("uploads") if not f.endswith("_original_text.txt")]
                return self._send(200, {
                    "masters": masters, "resumes": list_sources("resumes"),
                    "jd": read(JD_FILE) if os.path.exists(JD_FILE) else "",
                    "has_key": bool(gemini_key()), "model": gemini_model(), "models": gemini.MODELS,
                    "pdflatex": bool(shutil.which("pdflatex")),
                })
            if u.path == "/api/tex":
                f = q.get("file", ["main.tex"])[0]
                return self._send(200, {"file": f, "tex": read(safe(f))})
            if u.path == "/api/diff":
                return self._send(200, diff(q.get("master", ["main.tex"])[0], q.get("file", [""])[0]))
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
            if self.path == "/api/fetch_job":
                return self._send(200, job_fetch.fetch_job(b.get("url", "").strip(), gemini_key(), gemini_model()))
            if self.path == "/api/upload_resume":
                return self._send(200, upload_resume(b))
            if self.path == "/api/scan":
                return self._send(200, do_scan(b.get("resume") or b["master"], b["jd"], b["company"], b["role"]))
            if self.path == "/api/prompt":
                base = do_scan(b["master"], b["jd"], b["company"], b["role"])
                p = primary(base)
                system, user = build_prompts(read(safe(b["master"])), b["jd"], b["company"] or p["company"],
                                             b["role"] or p["role"], p["missing"])
                return self._send(200, {"prompt": system + "\n\n---\n\n" + user})
            if self.path == "/api/suggest":
                return self._send(200, make_suggestions(b))
            if self.path == "/api/apply":
                return self._send(200, apply_suggestion(b))
            if self.path == "/api/write":          # undo: restore a previous working-copy text
                path = safe(b.get("file", ""), dirs=("resumes",))
                write(path, b.get("text", ""))
                scan = do_scan(rel(path), b["jd"], b["company"], b["role"], save_jd=False)
                return self._send(200, {"scan": scan, "check": check(safe(b["master"]), read(path), scan)})
            if self.path == "/api/links":
                return self._send(200, {"links": links.check_all(read(safe(b.get("file") or b["master"])))})
            if self.path == "/api/tailor":
                if not gemini_key():
                    return self._send(400, {"error": "Add a Gemini key in Settings first."})
                job_id = uuid.uuid4().hex[:10]
                JOBS[job_id] = {"state": "thinking", "result": None, "error": None}
                threading.Thread(target=tailor_job, args=(job_id, b), daemon=True).start()
                return self._send(200, {"job": job_id})
            if self.path == "/api/save_result":
                base = do_scan(b["master"], b["jd"], b["company"], b["role"])
                return self._send(200, save_tailored(b.get("reply", ""), b, base))
            if self.path == "/api/review":
                base = do_scan(b["master"], b["jd"], b["company"], b["role"], save_jd=False)
                mpath, path = safe(b["master"]), safe(b.get("file", ""), dirs=("resumes",))
                chk = check(mpath, read(path), base)
                if b.get("repair") and chk["missing"]:
                    if not gemini_key():
                        return self._send(400, {"error": "Add a Gemini key in Settings to auto-restore."})
                    repair(mpath, path, chk)
                    chk = check(mpath, read(path), base)
                return self._send(200, {"check": chk, "scan": do_scan(rel(path), b["jd"], b["company"], b["role"], save_jd=False)})
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
                full = safe(b.get("file", ""))
                subprocess.run(["pdflatex", "-interaction=nonstopmode", "-output-directory", os.path.dirname(full), full],
                               capture_output=True, text=True)
                pdf = full[:-4] + ".pdf"
                if not os.path.exists(pdf):
                    return self._send(500, {"error": "pdflatex failed"})
                os.startfile(pdf)
                return self._send(200, {"pdf": rel(pdf)})
            self._send(404, {"error": "not found"})
        except FileNotFoundError as e:
            self._send(404, {"error": str(e)})
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
    port = int(os.environ.get("RS_PORT") or 0) or free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"Resume Studios running at {url}  (close the window to quit)")
    if "--no-open" not in sys.argv:
        open_window(url)
        threading.Thread(target=watchdog, args=(server,), daemon=True).start()
    server.serve_forever()
