"""Minimal Google Gemini API client (stdlib only, no extra packages).

generate(key, system, user, schema=None) -> str
Tries a chain of models so a busy/retired model doesn't break the app.
"""
import json
import re
import socket
import time
import urllib.error
import urllib.request

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# First one is the default; the rest are fallbacks when a model is busy (503/429) or slow.
# As of Nov 2026 on a free-tier key: 3.5-flash is fast & reliable, the lite models are quick backups;
# 3.8-flash/flash-latest were intermittently overloaded and pro models have no free quota.
MODELS = ["gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-flash-latest"]


class GeminiError(Exception):
    pass


def _call(key, model, body, timeout):
    req = urllib.request.Request(
        API.format(model=model), data=json.dumps(body).encode(),
        headers={"x-goog-api-key": key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def generate(key, system, user, schema=None, model=None, timeout=240, max_tokens=32768, tools=None):
    body = {
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    if schema:
        body["generationConfig"].update(responseMimeType="application/json", responseSchema=schema)
    if tools:
        body["tools"] = tools

    chain = [model] + [m for m in MODELS if m != model] if model else list(MODELS)
    chain.insert(1, chain[0])   # one retry on the preferred model before falling back
    last = None
    for m in chain:
        try:
            d = _call(key, m, body, timeout)
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="ignore")
            try:
                msg = json.loads(msg)["error"]["message"]
            except Exception:
                pass
            if e.code in (400, 401, 403) and ("API key" in msg or "PERMISSION" in msg.upper()):
                raise GeminiError("Gemini rejected the API key. Check it in Settings.") from None
            last = f"{m}: HTTP {e.code} {msg[:160]}"
            if e.code in (429, 500, 503, 504, 404):
                time.sleep(1)
                continue
            raise GeminiError(last) from None
        except (TimeoutError, socket.timeout, urllib.error.URLError) as e:
            last = f"{m}: {getattr(e, 'reason', e) or 'timed out'}"
            continue

        if d.get("promptFeedback", {}).get("blockReason"):
            raise GeminiError("Gemini blocked this request (" + d["promptFeedback"]["blockReason"] + ").")
        cands = d.get("candidates") or []
        if not cands:
            last = f"{m}: empty response"
            continue
        c = cands[0]
        text = "".join(p.get("text", "") for p in c.get("content", {}).get("parts", []) if not p.get("thought"))
        reason = c.get("finishReason")
        if reason == "MAX_TOKENS":
            raise GeminiError("Gemini's reply was cut off (too long). Try again.")
        if reason in ("SAFETY", "RECITATION", "PROHIBITED_CONTENT"):
            raise GeminiError(f"Gemini stopped the reply ({reason}). Try the copy-prompt option instead.")
        if not text.strip():
            last = f"{m}: empty text"
            continue
        return text
    raise GeminiError("All Gemini models failed or are busy. Last error: " + (last or "unknown")
                      + ". Try again in a minute, or use Copy prompt with Claude/ChatGPT.")


KEYWORD_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "required": {"type": "ARRAY", "items": {"type": "STRING"}},
        "preferred": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["required", "preferred"],
}

KEYWORD_PROMPT = """You are an ATS (applicant tracking system) keyword extractor.
From the job description below, list the skill keywords a recruiter's ATS would screen for.

Rules:
- "required": hard requirements (must-have / minimum qualifications / "you will need").
- "preferred": nice-to-haves (preferred / bonus / plus).
- Short canonical keywords, 1-3 words each, lowercase: technologies, languages, tools, methods,
  domains, degrees/fields, and concrete soft skills (e.g. "communication").
- Use the JD's own wording. No duplicates across lists. No company names, benefits, locations, or
  generic filler ("team player", "fast-paced", "passion").
- At most 25 required and 20 preferred.

<job_description>
{jd}
</job_description>"""


def extract_keywords(key, jd, model=None):
    text = generate(key, None, KEYWORD_PROMPT.format(jd=jd), schema=KEYWORD_SCHEMA,
                    model=model, timeout=60, max_tokens=4096)
    d = json.loads(text)
    clean = lambda xs: [x.strip().lower() for x in xs if isinstance(x, str) and 1 < len(x.strip()) <= 40]
    req = list(dict.fromkeys(clean(d.get("required", []))))
    pref = [k for k in dict.fromkeys(clean(d.get("preferred", []))) if k not in req]
    return {"required": req[:25], "preferred": pref[:20]}


JOB_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "company": {"type": "STRING"},
        "title": {"type": "STRING"},
        "location": {"type": "STRING"},
        "description": {"type": "STRING"},
    },
    "required": ["company", "title", "description"],
}

JOB_FROM_TEXT = """Below is the text of a job posting web page (navigation, cookie banners and other junk included).
Extract the job. "description" must be the COMPLETE job description copied verbatim: about the role,
responsibilities, basic/minimum qualifications, preferred qualifications, skills. Keep line breaks and
bullet points (use "- "). Do not summarise or shorten it. Drop site navigation, legal footers, and
"similar jobs" lists.

<page url="{url}">
{text}
</page>"""

JOB_FROM_URL = """Open this job posting: {url}
Return ONLY a JSON object with keys company, title, location, description.
"description" must be the COMPLETE job description copied verbatim from the page (about the role,
responsibilities, basic/minimum qualifications, preferred qualifications), with bullet points as "- ".
Do not summarise."""


def extract_job(key, url, page_text=None, model=None):
    """Job posting -> {company, title, location, description}. Uses page text when we have it,
    otherwise lets Gemini open the URL itself (url_context tool)."""
    if page_text:
        text = generate(key, None, JOB_FROM_TEXT.format(url=url, text=page_text[:60000]),
                        schema=JOB_SCHEMA, model=model, timeout=90, max_tokens=16384)
        return json.loads(text)
    text = generate(key, None, JOB_FROM_URL.format(url=url), model=model, timeout=120,
                    max_tokens=16384, tools=[{"url_context": {}}])
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise GeminiError("Gemini couldn't read that page. Paste the job text instead.")
    return json.loads(m.group(0))


def read_pdf(key, data, model=None):
    """PDF bytes -> plain text, for scanned/odd PDFs that local parsing can't read."""
    import base64
    body = {"contents": [{"role": "user", "parts": [
        {"inline_data": {"mime_type": "application/pdf", "data": base64.b64encode(data).decode()}},
        {"text": "Transcribe this resume to plain text. Keep every word, link, date and number. "
                 "Keep section headings on their own lines and bullets as '- '. No commentary."}]}],
        "generationConfig": {"maxOutputTokens": 16384}}
    last = None
    for m in ([model] if model else []) + MODELS:
        try:
            d = _call(key, m, body, 120)
            c = (d.get("candidates") or [{}])[0]
            text = "".join(p.get("text", "") for p in c.get("content", {}).get("parts", []) if not p.get("thought"))
            if text.strip():
                return text
        except Exception as e:
            last = e
    raise GeminiError(f"Gemini couldn't read that PDF ({last or 'empty reply'}).")


SUGGEST_SCHEMA = {
    "type": "OBJECT",
    "properties": {"suggestions": {"type": "ARRAY", "items": {
        "type": "OBJECT",
        "properties": {
            "title": {"type": "STRING"},
            "why": {"type": "STRING"},
            "type": {"type": "STRING", "enum": ["reword", "surface", "reorder", "new_skill"]},
            "keywords": {"type": "ARRAY", "items": {"type": "STRING"}},
            "evidence": {"type": "STRING"},
            "find": {"type": "STRING"},
            "replace": {"type": "STRING"},
        },
        "required": ["title", "why", "type", "keywords", "find", "replace"]}}},
    "required": ["suggestions"],
}

SUGGEST_PROMPT = """You are an ATS resume coach. Propose small, surgical edits to the candidate's resume source
that raise its match with the job description below. The candidate decides on each edit one by one.

Rules for every suggestion:
- It edits ONE contiguous piece of the resume source. "find" must be copied character-for-character
  from the source (a phrase, a bullet, or one skills line; max ~300 characters). "replace" is that
  same piece rewritten.
- Never delete facts: keep every skill, tool, project, number and link that is already in the piece.
- Prefer, in this order:
  "reword"  - use the job's exact wording for something the candidate already has;
  "surface" - make explicit a skill clearly shown by existing content; put the proof in "evidence";
  "reorder" - move the most job-relevant items first within one line or bullet.
- If the job needs a skill the resume does not show at all, you MAY suggest adding it, but then
  "type" must be "new_skill" and "why" must say to accept only if it is true.
- Keep the source valid (LaTeX: escape & % # _ ; plain text stays plain).
- 4 to 10 suggestions, highest score impact first, aimed at the missing must-have keywords.
- "keywords": the job keywords each edit adds. "title": a short imperative, e.g. "Use 'RESTful APIs' in Skills".

Job keywords NOT visible in the resume yet:
- Must-have: {must}
- Nice-to-have: {nice}
- Other: {other}

<job_description>
{jd}
</job_description>

<resume_source>
{resume}
</resume_source>"""


def suggest(key, resume, jd, missing, model=None):
    grp = lambda p: ", ".join(m["k"] for m in missing if m["p"] == p) or "(none)"
    text = generate(key, None, SUGGEST_PROMPT.format(must=grp("required"), nice=grp("preferred"), other=grp("general"),
                                                     jd=jd[:30000], resume=resume),
                    schema=SUGGEST_SCHEMA, model=model, timeout=150, max_tokens=16384)
    return json.loads(text).get("suggestions", [])
