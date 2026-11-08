"""Check every link in a resume: works, redirects, broken, or can't be verified."""
import re
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
BLOCKS_BOTS = ("linkedin.com",)          # returns 999/403 to any automated check


def extract(src):
    """-> list of {url, label} from \\href{url}{label}, \\url{url} and bare http(s) links."""
    found = []
    for url, label in re.findall(r"\\href\{([^}]*)\}\s*\{([^}]*)\}", src):
        found.append((url.strip(), re.sub(r"\\[a-zA-Z]+|[{}]", "", label).strip()))
    for url in re.findall(r"\\url\{([^}]*)\}", src):
        found.append((url.strip(), ""))
    for url in re.findall(r"(?<![{\w])(https?://[^\s}\\]+)", src):
        found.append((url.strip().rstrip(".,);"), ""))
    out, seen = [], set()
    for url, label in found:
        if url and url not in seen:
            seen.add(url)
            out.append({"url": url, "label": label})
    return out


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def _fetch(url, method):
    req = urllib.request.Request(url, method=method, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with _opener.open(req, timeout=12) as r:
            return r.status, None
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Location")


def check_one(item):
    url = item["url"]
    r = {**item, "status": "ok", "code": None, "final": url, "note": ""}
    if url.startswith("mailto:"):
        ok = re.match(r"^mailto:[\w.+-]+@[\w-]+\.[\w.-]+$", url)
        r.update(status="ok" if ok else "broken", note="Email address" if ok else "Email address looks malformed")
        return r
    if not url.startswith(("http://", "https://")):
        r.update(status="broken", note="Not a web link (should start with https://)")
        return r
    host = urllib.parse.urlparse(url).hostname or ""
    try:
        chain, cur = [], url
        for _ in range(6):
            code, loc = _fetch(cur, "HEAD")
            if code in (405, 403, 501):                     # some sites reject HEAD
                code, loc = _fetch(cur, "GET")
            if code in (301, 302, 303, 307, 308) and loc:
                cur = urllib.parse.urljoin(cur, loc)
                chain.append(cur)
                continue
            break
        r["code"], r["final"] = code, cur
        if any(b in host for b in BLOCKS_BOTS) and code in (999, 403, 429, None):
            r.update(status="unverified", note="LinkedIn blocks automated checks. Open it once to confirm.")
        elif 200 <= (code or 0) < 400:
            if chain:
                same = urllib.parse.urlparse(cur).netloc == urllib.parse.urlparse(url).netloc
                r.update(status="redirect", note=("Redirects to " + cur) + ("" if same else " (different site)"))
            else:
                r["note"] = "Opens fine"
        elif code == 404:
            r.update(status="broken", note="Page not found (404). Repo renamed, private or deleted?")
        else:
            r.update(status="broken", note=f"Server answered {code}")
    except Exception as e:
        reason = getattr(e, "reason", e)
        r.update(status="broken", note=f"Couldn't open: {reason}")
    if r["status"] == "ok" and "github.com" in host:
        parts = [p for p in urllib.parse.urlparse(r["final"]).path.split("/") if p]
        r["note"] = "GitHub repository opens" if len(parts) >= 2 else "GitHub profile opens"
    return r


def check_all(src):
    items = extract(src)
    with ThreadPoolExecutor(max_workers=8) as ex:
        return list(ex.map(check_one, items))
