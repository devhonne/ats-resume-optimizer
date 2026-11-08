"""Resume Studios — public beta API (FastAPI).

Stateless: resumes and job descriptions are processed in memory and never stored on the server.
The browser keeps the user's master resume and tailored versions (localStorage).

Gemini key: the user's own key (header X-Gemini-Key) or the server's GEMINI_API_KEY, which is
rate-limited per client IP (AI_CALLS_PER_HOUR, default 30).
"""
import hashlib
import os
import threading
import time
from collections import OrderedDict, defaultdict, deque

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import ats, gemini, job_fetch, prompts, resume_parse


def _load_dotenv():
    """Read resume-studios-web/.env for local runs (real env vars win)."""
    path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            k, sep, v = line.strip().partition("=")
            if sep and k and not k.startswith("#"):
                os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()
SERVER_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
AI_PER_HOUR = int(os.environ.get("AI_CALLS_PER_HOUR", "30"))
DIST = os.environ.get("FRONTEND_DIST") or os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")
MAX_RESUME = 200_000
MAX_JD = 60_000

app = FastAPI(title="Resume Studios API", version="0.1.0-beta", docs_url="/api/docs", openapi_url="/api/openapi.json")
origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
if origins:
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])


# ---------------------------------------------------------------- AI access + limits
_calls = defaultdict(deque)
_lock = threading.Lock()


def client_ip(req: Request):
    # Never read X-Forwarded-For here (clients can fake it). Behind a hosting proxy, run uvicorn with
    # --proxy-headers --forwarded-allow-ips=<proxy> so req.client.host is the real client address.
    return req.client.host if req.client else "?"


def ai_access(req: Request, cost=1):
    """-> (key, model). Raises 400 if no key, 429 if the shared key's hourly limit is used up."""
    own = (req.headers.get("x-gemini-key") or "").strip()
    model = req.headers.get("x-gemini-model")
    model = model if model in gemini.MODELS else gemini.MODELS[0]
    if own:
        return own, model
    if not SERVER_KEY:
        raise HTTPException(400, "AI features need a Gemini API key. Add your own in Settings.")
    now = time.time()
    with _lock:
        q = _calls[client_ip(req)]
        while q and now - q[0] > 3600:
            q.popleft()
        if len(q) + cost > AI_PER_HOUR:
            wait = int(3600 - (now - q[0])) // 60 + 1
            raise HTTPException(429, f"Beta limit reached ({AI_PER_HOUR} AI actions per hour). "
                                     f"Try again in ~{wait} min, or add your own free Gemini key in Settings.")
        q.extend([now] * cost)
    return SERVER_KEY, model


def ai_available(req: Request):
    return bool((req.headers.get("x-gemini-key") or "").strip() or SERVER_KEY)


def gemini_call(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except gemini.GeminiError as e:
        raise HTTPException(502, str(e)) from None


# keyword cache: same JD -> same AI keywords, so before/after scores are comparable
_kw_cache = OrderedDict()


def ai_keywords(req: Request, jd):
    h = hashlib.sha256(jd.strip().encode()).hexdigest()
    if h in _kw_cache:
        _kw_cache.move_to_end(h)
        return _kw_cache[h], None
    if not ai_available(req):
        return None, None
    try:
        key, model = ai_access(req)
        kw = gemini.extract_keywords(key, jd, model=model)
    except HTTPException as e:
        return None, e.detail
    except Exception as e:
        return None, str(e)
    _kw_cache[h] = kw
    while len(_kw_cache) > 1000:
        _kw_cache.popitem(last=False)
    return kw, None


# ---------------------------------------------------------------- models
class JobIn(BaseModel):
    url: str = Field(max_length=2000)


class TextIn(BaseModel):
    text: str = Field(max_length=MAX_RESUME)


class ScanIn(BaseModel):
    resume: str = Field(max_length=MAX_RESUME)
    jd: str = Field(max_length=MAX_JD)
    company: str = Field("", max_length=200)
    role: str = Field("", max_length=200)


class ReplyIn(ScanIn):
    reply: str = Field(max_length=MAX_RESUME * 2)


class ReviewIn(ScanIn):
    tailored: str = Field(max_length=MAX_RESUME)
    repair: bool = False


def header_jd(b: ScanIn):
    return (f"Company: {b.company}\n" if b.company else "") + (f"Job Title: {b.role}\n" if b.role else "") + b.jd


def need(b: ScanIn):
    if len(b.resume.strip()) < 100:
        raise HTTPException(400, "Add your resume first.")
    if len(b.jd.split()) < 15:
        raise HTTPException(400, "Add the job description first.")


def do_scan(req, b: ScanIn, resume=None):
    jd = header_jd(b)
    resume = resume if resume is not None else b.resume
    local = ats.scan(resume, jd, None)
    kw, err = ai_keywords(req, b.jd)
    ai = ats.scan(resume, jd, kw) if kw else None
    return {"local": local, "ai": ai, "ai_error": err, "company": local["company"], "role": local["role"]}


def primary(s):
    return s["ai"] or s["local"]


def all_kw(s):
    p = primary(s)
    return [m["k"] for m in p["matched"] + p["missing"]]


def finish(req, b: ScanIn, reply, base, auto_repair):
    tex, notes = prompts.extract_parts(reply)
    if not prompts.is_full_latex(tex):
        raise HTTPException(422, "That reply doesn't contain a complete LaTeX resume (\\documentclass … \\end{document}).")
    check = ats.compare_resumes(b.resume, tex, all_kw(base))
    repaired = False
    if auto_repair and check["missing"]:
        try:
            tex = repair(req, b.resume, tex, check)
            check, repaired = ats.compare_resumes(b.resume, tex, all_kw(base)), True
        except HTTPException:
            pass
    before = {"local": base["local"]["score"], "ai": base["ai"]["score"] if base["ai"] else None}
    return {"tex": tex, "notes": notes, "check": check, "repaired": repaired,
            "scan": do_scan(req, b, tex), "before": before}


def repair(req, master, tailored, check):
    key, model = ai_access(req)
    missing = "\n".join(f"- {m['kind']}: {m['item']}" for m in check["missing"])
    reply = gemini_call(gemini.generate, key, None, prompts.REPAIR.format(missing=missing, master=master, tailored=tailored),
                        model=model, timeout=180)
    tex, _ = prompts.extract_parts(reply)
    return tex if prompts.is_full_latex(tex) else tailored


# ---------------------------------------------------------------- routes
@app.get("/api/health")
def health():
    return {"ok": True, "version": app.version, "server_ai": bool(SERVER_KEY),
            "ai_per_hour": AI_PER_HOUR, "models": gemini.MODELS}


@app.post("/api/job")
def fetch_job(b: JobIn, req: Request):
    key = model = None
    if ai_available(req):
        key, model = ai_access(req)
    try:
        return job_fetch.fetch_job(b.url.strip(), key, model)
    except gemini.GeminiError as e:
        raise HTTPException(502, str(e)) from None
    except ValueError as e:
        raise HTTPException(400, str(e)) from None


def to_latex(req, kind, text):
    if kind == "latex":
        if not prompts.is_full_latex(text):
            raise HTTPException(400, "That .tex file isn't a complete document (needs \\documentclass … \\end{document}).")
        return {"tex": text, "converted": False}
    key, model = ai_access(req)
    reply = gemini_call(gemini.generate, key, None, prompts.CONVERT.format(template=prompts.TEMPLATE, text=text),
                        model=model, timeout=180)
    tex, _ = prompts.extract_parts(reply)
    if not prompts.is_full_latex(tex):
        raise HTTPException(502, "Gemini couldn't convert that resume. Try again or upload a .tex file.")
    facts = ats.resume_facts(tex)
    return {"tex": tex, "converted": True,
            "note": f"Converted from {kind.upper()} with Gemini. Check that every fact came across "
                    f"({len(facts['skills'])} skills and {len(facts['titles'])} roles/projects found)."}


@app.post("/api/resume/upload")
async def upload_resume(req: Request, file: UploadFile = File(...)):
    data = await file.read(resume_parse.MAX_BYTES + 1)
    try:
        kind, text = resume_parse.read_upload(file.filename or "", data)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    from starlette.concurrency import run_in_threadpool
    out = await run_in_threadpool(to_latex, req, kind, text)
    return {**out, "kind": kind, "filename": file.filename}


@app.post("/api/resume/text")
def resume_from_text(b: TextIn, req: Request):
    text = b.text.strip()
    if len(text) < 200:
        raise HTTPException(400, "Paste your full resume.")
    kind = "latex" if "\\documentclass" in text else "text"
    return {**to_latex(req, kind, text), "kind": kind}


@app.post("/api/scan")
def scan(b: ScanIn, req: Request):
    need(b)
    return do_scan(req, b)


@app.post("/api/prompt")
def prompt(b: ScanIn, req: Request):
    need(b)
    base = do_scan(req, b)
    p = primary(base)
    text = prompts.SYSTEM + "\n\n---\n\n" + prompts.tailor_prompt(b.resume, b.jd, b.company or p["company"],
                                                                  b.role or p["role"], p["missing"])
    return {"prompt": text}


@app.post("/api/tailor")
def tailor(b: ScanIn, req: Request):
    need(b)
    base = do_scan(req, b)
    key, model = ai_access(req, cost=2)
    p = primary(base)
    reply = gemini_call(gemini.generate, key, prompts.SYSTEM,
                        prompts.tailor_prompt(b.resume, b.jd, b.company or p["company"], b.role or p["role"], p["missing"]),
                        model=model, timeout=240)
    return finish(req, b, reply, base, auto_repair=True)


@app.post("/api/reply")
def from_reply(b: ReplyIn, req: Request):
    need(b)
    return finish(req, b, b.reply, do_scan(req, b), auto_repair=False)


@app.post("/api/review")
def review(b: ReviewIn, req: Request):
    need(b)
    base = do_scan(req, b)
    tex = b.tailored
    check = ats.compare_resumes(b.resume, tex, all_kw(base))
    if b.repair and check["missing"]:
        tex = repair(req, b.resume, tex, check)
        check = ats.compare_resumes(b.resume, tex, all_kw(base))
    return {"tex": tex, "check": check, "scan": do_scan(req, b, tex)}


# ---------------------------------------------------------------- frontend (built React app)
if os.path.isdir(DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(DIST, "assets")), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        full = os.path.realpath(os.path.join(DIST, path))
        if path and full.startswith(os.path.realpath(DIST)) and os.path.isfile(full):
            return FileResponse(full)
        return FileResponse(os.path.join(DIST, "index.html"))
