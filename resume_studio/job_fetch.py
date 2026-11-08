"""Job link -> job description.

1. Download the page (works for most career sites: Amazon, Greenhouse, Lever, Workable, LinkedIn guest pages).
2. If the page embeds schema.org JobPosting data (most do, for Google Jobs), use it: no AI needed.
3. Otherwise strip the page to text and let Gemini pull the job out of it.
4. If the download is blocked or the page is JavaScript-only, let Gemini open the URL itself.
"""
import html
import json
import re
import urllib.request
from html.parser import HTMLParser

import gemini

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form"}
    BLOCK = {"p", "div", "li", "br", "h1", "h2", "h3", "h4", "h5", "tr", "section", "ul", "ol"}

    def __init__(self):
        super().__init__()
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag == "li":
            self.out.append("\n- ")
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_to_text(src):
    p = _Text()
    p.feed(src)
    text = html.unescape("".join(p.out))
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return "\n".join(l.strip() for l in text.splitlines()).strip()


def download(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-IN,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read(3_000_000)
        enc = r.headers.get_content_charset() or "utf-8"
    return raw.decode(enc, errors="replace")


def _walk(o):
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from _walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v)


def from_json_ld(page):
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page, re.S | re.I):
        try:
            data = json.loads(block.strip())
        except Exception:
            continue
        for o in _walk(data):
            t = o.get("@type")
            if t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t):
                org = o.get("hiringOrganization") or {}
                loc = o.get("jobLocation") or {}
                if isinstance(loc, list):
                    loc = loc[0] if loc else {}
                addr = (loc.get("address") or {}) if isinstance(loc, dict) else {}
                desc = html_to_text(o.get("description", ""))
                if len(desc) > 200:
                    return {
                        "company": org.get("name", "") if isinstance(org, dict) else str(org),
                        "title": o.get("title", ""),
                        "location": ", ".join(x for x in (addr.get("addressLocality"), addr.get("addressRegion"),
                                                          addr.get("addressCountry")) if isinstance(x, str) and x),
                        "description": desc,
                    }
    return None


def fetch_job(url, key=None, model=None):
    """Returns dict(company, title, location, description, source, note)."""
    if not re.match(r"^https?://", url or ""):
        raise ValueError("Paste a full link starting with http:// or https://")
    page, err = None, None
    try:
        page = download(url)
    except Exception as e:
        err = str(e)

    if page:
        job = from_json_ld(page)
        if job:
            job.update(source="Read the job data embedded in the page", note="")
            return job
        text = html_to_text(page)
        if key and len(text) > 400:
            job = gemini.extract_job(key, url, page_text=text, model=model)
            if len(job.get("description", "")) > 200:
                job.update(source="Gemini extracted the job from the page", note="")
                return job
        if not key and len(text) > 400:
            return {"company": "", "title": "", "location": "", "description": text[:20000],
                    "source": "Downloaded page text",
                    "note": "No Gemini key, so this is the raw page text. Trim anything that isn't the job."}

    if key:
        job = gemini.extract_job(key, url, model=model)
        if len(job.get("description", "")) > 100:
            job.update(source="Gemini opened the link",
                       note="Gemini read the page directly. Check that the qualifications are complete.")
            return job
    raise ValueError("Couldn't read that link" + (f" ({err})" if err else "")
                     + ". The site may need a login. Open it, copy the job text, and use Paste text.")
