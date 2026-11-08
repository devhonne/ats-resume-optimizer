"""Minimal Google Gemini API client (stdlib only, no extra packages).

generate(key, system, user, schema=None) -> str
Tries a chain of models so a busy/retired model doesn't break the app.
"""
import json
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


def generate(key, system, user, schema=None, model=None, timeout=240, max_tokens=32768):
    body = {
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    if schema:
        body["generationConfig"].update(responseMimeType="application/json", responseSchema=schema)

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
