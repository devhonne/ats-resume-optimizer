"""Score-raising suggestions, validated locally.

Every suggestion is an exact edit (find -> replace) on the working resume. Before the user sees it we:
  1. locate `find` in the source (exact, or whitespace-tolerant),
  2. apply it to a copy and re-score -> the exact point gain,
  3. compare with the ORIGINAL resume:
       - removes any original fact  -> dropped (we never remove the user's facts)
       - adds a skill/keyword the original doesn't have -> needs_consent (user must confirm it's true)
"""
import hashlib
import re

import ats_checker


def locate(src, find):
    """-> (start, end) of `find` in src, tolerant of whitespace/line-break differences, or None."""
    if not find or not find.strip():
        return None
    i = src.find(find)
    if i >= 0:
        return i, i + len(find)
    parts = find.split()
    if not parts:
        return None
    m = re.search(r"\s+".join(map(re.escape, parts)), src)
    return (m.start(), m.end()) if m else None


def primary(scan):
    return scan["ai"] or scan["local"]


def _sid(find, replace):
    return hashlib.sha1((find + "\x00" + replace).encode()).hexdigest()[:10]


def evaluate(items, original, working, jd_full, kw, all_keywords):
    """Validate + score each suggestion against the current working source. Returns sorted list."""
    base_local = ats_checker.scan_text(working, jd_full, None)["score"]
    base_ai = ats_checker.scan_text(working, jd_full, kw)["score"] if kw else None
    base = base_ai if base_ai is not None else base_local
    cur = ats_checker.compare_resumes(original, working, all_keywords)
    cur_missing = {(m["kind"], m["item"]) for m in cur["missing"]}
    cur_added = set(cur["added_skills"]) | set(cur["added_keywords"])
    out, seen = [], set()
    for s in items:
        span = locate(working, s.get("find", ""))
        rep = s.get("replace", "")
        if not span or not rep.strip():
            continue
        found = working[span[0]:span[1]]
        if found == rep:
            continue
        new = working[:span[0]] + rep + working[span[1]:]
        sid = _sid(found, rep)
        if sid in seen:
            continue
        seen.add(sid)
        chk = ats_checker.compare_resumes(original, new, all_keywords)
        removed = [m["item"] for m in chk["missing"] if (m["kind"], m["item"]) not in cur_missing]
        if removed:
            continue                                   # would delete the user's facts: never offer it
        cur_low = {x.lower() for x in cur_added}
        adds, seen_low = [], set()
        for x in chk["added_skills"] + chk["added_keywords"]:
            if x.lower() not in cur_low and x.lower() not in seen_low:
                seen_low.add(x.lower())
                adds.append(x)
        local = ats_checker.scan_text(new, jd_full, None)["score"]
        ai = ats_checker.scan_text(new, jd_full, kw)["score"] if kw else None
        after = ai if ai is not None else local
        gain = after - base
        kind = s.get("type", "reword")
        if gain <= 0 and kind != "exact" and not s.get("keep_zero"):
            continue
        out.append({
            "id": sid, "title": s.get("title", "Edit"), "why": s.get("why", ""), "type": kind,
            "keywords": s.get("keywords", []), "evidence": s.get("evidence", ""),
            "find": found, "replace": rep, "gain": gain, "after": after,
            "after_local": local, "after_ai": ai,
            "needs_consent": bool(adds) or kind == "new_skill", "adds": adds, "source": s.get("source", "ai"),
        })
    out.sort(key=lambda x: (x["needs_consent"], -x["gain"]))
    return out


def local_suggestions(working, jd_raw, scan):
    """Offline suggestions (no AI): where the resume says a synonym, use the job's exact wording too.
    Our score already counts synonyms, but many real ATS only match the exact phrase."""
    out = []
    jd_low = jd_raw.lower()
    for m in primary(scan)["matched"]:
        via = m.get("via")
        if not via or via in ("all words of the phrase", "spread across the resume"):
            continue
        i = jd_low.find(m["k"])
        jd_form = jd_raw[i:i + len(m["k"])] if i >= 0 else m["k"]
        rx = re.compile(r"(?<![\\\w])" + re.escape(via) + r"(?![\w])", re.I)
        hit = rx.search(working)
        if not hit:
            continue
        orig = hit.group(0)
        out.append({"title": f"Also write “{jd_form}”", "type": "exact", "keywords": [m["k"]], "source": "local",
                    "why": f"Your resume says “{orig}”. Real ATS filters often look for the job's exact phrase “{jd_form}”.",
                    "evidence": f"Already in your resume as “{orig}”.",
                    "find": orig, "replace": f"{jd_form} ({orig})"})
    return out
