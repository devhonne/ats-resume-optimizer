"""ATS scanner — scores a resume (.tex or .json) against a job description.

Usage:
    python ats_checker.py                         # interactive menu
    python ats_checker.py main.tex                # score vs job_description.txt
    python ats_checker.py resumes/x.tex jd.txt    # score any resume vs any JD

Score = weighted mix of five checks, like real ATS + recruiter screens:
    Keywords 60%  ·  Job title 10%  ·  Sections & contact 10%  ·  Measurable impact 10%  ·  Length 10%
Keywords come from a built-in tech list, plus (in Resume Studio, with a Gemini key) AI-extracted
must-have / nice-to-have keywords from the JD. Synonyms count (ML = machine learning, JS = JavaScript).
"""
import json
import re
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

MASTER_TECH_LIST = {
    # languages
    "python", "javascript", "typescript", "java", "c++", "c#", "sql", "rust", "bash", "golang",
    # web / backend
    "react", "next.js", "vite", "vue", "angular", "node.js", "express", "fastapi", "flask", "django",
    "spring boot", "html", "css", "tailwind", "bootstrap", "redux", "rest api", "graphql", "jwt",
    "microservices", "pydantic",
    # data
    "postgresql", "mongodb", "mysql", "sqlite", "supabase", "firebase", "etl", "airflow",
    "data pipeline", "data analysis", "data science", "pyspark", "spark", "hadoop", "hive",
    "tableau", "power bi", "excel", "databricks", "pandas", "numpy",
    # cloud / devops
    "aws", "gcp", "azure", "docker", "kubernetes", "git", "github", "github actions", "ci/cd",
    "terraform", "ansible", "linux", "maven",
    # ai / ml
    "ai", "machine learning", "deep learning", "nlp", "computer vision", "opencv", "ocr", "pytorch",
    "tensorflow", "keras", "scikit-learn", "llm", "generative ai", "rag", "embeddings",
    "hugging face", "transformers", "prompt engineering", "langchain", "vector database",
    "gemini", "openai", "vertex ai", "tinyml", "edge ai", "model evaluation",
    # cs fundamentals / practice
    "data structures", "algorithms", "oop", "distributed systems", "software engineering",
    "agile", "scrum", "unit testing", "debugging", "troubleshooting", "technical documentation",
    "api integration", "problem solving", "communication",
}

# canonical keyword -> other ways resumes/JDs write it
SYNONYMS = {
    "javascript": ["js"], "c++": ["cpp"],
    "react": ["react.js", "reactjs"], "node.js": ["nodejs", "node"], "next.js": ["nextjs"],
    "express": ["express.js", "expressjs"], "vue": ["vue.js", "vuejs"],
    "rest api": ["rest apis", "restful", "restful api", "restful apis"],
    "postgresql": ["postgres", "psql"], "mongodb": ["mongo"], "kubernetes": ["k8s"],
    "ci/cd": ["cicd", "ci cd", "continuous integration"], "aws": ["amazon web services"],
    "gcp": ["google cloud", "google cloud platform"], "azure": ["microsoft azure"],
    "airflow": ["apache airflow"], "spark": ["apache spark"], "pyspark": ["spark"],
    "data pipeline": ["data pipelines", "etl pipeline", "etl pipelines"],
    "etl": ["extract transform load", "etl pipeline"],
    "ai": ["artificial intelligence", "ai/ml"], "machine learning": ["ml", "ai/ml", "ai & ml"],
    "deep learning": ["dl", "neural networks", "neural network"],
    "nlp": ["natural language processing"], "natural language processing": ["nlp"],
    "computer vision": ["cv", "image processing"], "llm": ["llms", "large language models", "large language model"],
    "generative ai": ["genai", "gen ai"], "rag": ["retrieval-augmented generation", "retrieval augmented generation"],
    "scikit-learn": ["sklearn", "scikit learn"], "hugging face": ["huggingface"],
    "oop": ["oops", "object-oriented", "object oriented", "object-oriented programming"],
    "data structures": ["dsa", "data structures and algorithms"], "algorithms": ["dsa", "algorithm"],
    "software engineering": ["software development", "software engineer", "software developer"],
    "unit testing": ["unit tests", "testing", "pytest", "junit"],
    "troubleshooting": ["debugging", "troubleshoot"], "debugging": ["troubleshooting", "debug"],
    "excel": ["microsoft excel", "ms excel"], "power bi": ["powerbi"],
    "technical documentation": ["documentation"], "communication": ["communication skills", "communicating"],
    "problem solving": ["problem-solving"], "github": ["git"],
    "computer science": ["cse", "computer science and engineering", "b.tech", "btech"],
    "bachelor's degree": ["b.tech", "btech", "bachelor", "bachelors", "b.e."],
}

STOP = {"and", "or", "of", "the", "a", "an", "in", "with", "for", "to", "on", "skills", "skill",
        "experience", "knowledge", "strong", "good", "proficiency", "understanding", "ability",
        "familiarity", "using", "based", "etc", "tools", "tool"}
TITLE_STOP = STOP | {"intern", "internship", "i", "ii", "iii", "1", "2", "senior", "junior", "sr", "jr",
                     "trainee", "associate", "graduate", "fresher", "entry", "level", "2025", "2026", "2027"}

WEIGHTS = {"keywords": 60, "title": 10, "sections": 10, "impact": 10, "length": 10}


def kw_regex(kw):
    """Whole-word / whole-phrase match that tolerates special chars like + # . /"""
    return re.compile(rf'(?<![\w]){re.escape(kw)}(?![\w])')


def has_keyword(kw, text):
    kw = kw.lower().strip()
    for variant in [kw] + SYNONYMS.get(kw, []):
        if kw_regex(variant).search(text):
            return True
    # multi-word AI keywords ("strong python skills"): all meaningful words present
    # e.g. "c/c++" -> ["c++"], "distributed, multi-tiered systems" -> [...]
    words = [w for w in re.findall(r"[a-z0-9+#]+(?:\.[a-z0-9]+)*", kw) if w not in STOP and len(w) > 1]
    if words and words != [kw]:
        return all(any(kw_regex(v).search(text) for v in [w] + SYNONYMS.get(w, [])) for w in words)
    return False


def get_resume_files():
    files = [f for f in os.listdir(SCRIPT_DIR)
             if (f.endswith('.json') and f.startswith('resume_') and 'template' not in f)
             or f == 'main.tex']
    resumes_dir = os.path.join(SCRIPT_DIR, 'resumes')
    if os.path.isdir(resumes_dir):
        files += ['resumes/' + f for f in sorted(os.listdir(resumes_dir))
                  if f.endswith('.tex') or f.endswith('.json')]
    return files


def latex_to_text(tex):
    """Rough LaTeX -> plain text so keywords inside the .tex can be scored."""
    tex = tex.split(r'\begin{document}', 1)[-1]
    tex = re.sub(r'(?<!\\)%.*', ' ', tex)
    tex = re.sub(r'\\href\{([^}]*)\}', r' \1 ', tex)          # keep URLs (linkedin/github check)
    tex = tex.replace(r'\&', '&').replace(r'\%', '%').replace(r'\#', '#').replace(r'\_', '_')
    tex = tex.replace('--', '-')
    tex = re.sub(r'\\section\*?\{([^}]*)\}', r'\n## \1\n', tex)  # keep section headings
    tex = re.sub(r'\\[a-zA-Z]+\*?(\[[^\]]*\])?', ' ', tex)
    tex = re.sub(r'[{}\\]', ' ', tex)
    return re.sub(r'[ \t]+', ' ', tex)


def load_resume_text(path):
    """Returns (name, plain_text)."""
    with open(path, 'r', encoding='utf-8') as f:
        raw = f.read()
    if path.endswith('.json'):
        data = json.loads(raw)

        def walk(o, key=""):
            if isinstance(o, dict):
                out = []
                for k, v in o.items():
                    out.append(f"\n## {k}\n")
                    out += walk(v, k)
                return out
            if isinstance(o, list):
                return [x for v in o for x in walk(v, key)]
            return [str(o)]

        name = data.get('personal_info', {}).get('name', 'User')
        return name, " ".join(walk(data))
    m = re.search(r'\\textbf\{([A-Z][A-Z .]+)\}', raw)
    name = m.group(1).strip() if m else os.path.basename(path)
    return name, latex_to_text(raw)


def parse_jd_header(jd_raw):
    jd_lines = [line.strip() for line in jd_raw.splitlines() if line.strip()]
    company, role = "Unknown Company", "Unknown Role"
    if not jd_lines:
        return company, role
    company_line = next((l for l in jd_lines if l.lower().startswith("company:")), None)
    if company_line:
        company = company_line.split(":", 1)[1].strip()
    else:
        about_line = next((l for l in jd_lines if l.lower().startswith("about ")), None)
        if about_line:
            company = about_line.split(" ", 1)[1].strip()
    role_line = next((l for l in jd_lines
                      if l.lower().startswith("job title:") or l.lower().startswith("role:")), None)
    if role_line:
        role = role_line.split(":", 1)[1].strip()
    else:
        first = jd_lines[0]
        if first.lower().startswith("position summary") and len(jd_lines) > 1:
            role = jd_lines[1].split(",")[0].strip()
        else:
            role = first
    for prefix in ("as a ", "as an "):
        if role.lower().startswith(prefix):
            role = role[len(prefix):].strip()
    return company[:40], role[:60]


# ------------------------------------------------------------------ checks
def check_sections(text):
    t = text.lower()
    checks = {
        "Summary": r"summary|objective|profile",
        "Skills": r"skills",
        "Experience": r"experience|internship|intern\b",
        "Projects": r"projects?",
        "Education": r"education",
        "Email": r"[\w.+-]+@[\w-]+\.[\w.]+",
        "LinkedIn / GitHub": r"linkedin|github",
    }
    found = [k for k, rx in checks.items() if re.search(rx, t)]
    missing = [k for k in checks if k not in found]
    return len(found) / len(checks), found, missing


def check_impact(text):
    body = re.sub(r"\b(19|20)\d{2}\b", " ", text)                       # drop years
    body = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+|https?://\S+|IN-\d+", " ", body)  # emails, urls, patent no.
    nums = re.findall(r"(?<![\w.])\d[\d,]*(?:\.\d+)?\s*(?:%|\+|k\b|x\b|/10)?", body)
    metrics = [n.strip() for n in nums if n.strip() not in ("0", "1")]
    return min(1.0, len(metrics) / 6), metrics


def check_length(text):
    n = len(re.findall(r"[A-Za-z][A-Za-z+#.\-]*", text))
    if 350 <= n <= 850:
        s = 1.0
    elif n < 350:
        s = max(0.0, n / 350)
    else:
        s = max(0.4, 1 - (n - 850) / 1000)
    return s, n


def check_title(role, text):
    if not role or role.startswith("Unknown"):
        return None, []
    words = [w for w in re.findall(r"[a-z0-9+#.]+", role.lower()) if w not in TITLE_STOP and len(w) > 1]
    if not words:
        return None, []
    hits = [w for w in words if has_keyword(w, text.lower())
            or (w == "sde" and has_keyword("software development", text.lower()))
            or (w in ("researcher", "research") and "research" in text.lower())]
    return len(hits) / len(words), words


def scan(resume_path, jd_raw, ai_keywords=None):
    """Score a resume file against JD text. Returns a dict (used by the GUI and CLI).

    ai_keywords: optional {"required": [...], "preferred": [...]} from gemini.extract_keywords.
    """
    if not os.path.isabs(resume_path):
        resume_path = os.path.join(SCRIPT_DIR, resume_path)
    name, resume_plain = load_resume_text(resume_path)
    text = resume_plain.lower()
    jd_text = jd_raw.lower()
    company, role = parse_jd_header(jd_raw)

    # ---- keyword set with priorities (required=3, preferred=2, general=1)
    kws = {}
    if ai_keywords:
        for k in ai_keywords.get("required", []):
            kws[k] = "required"
        for k in ai_keywords.get("preferred", []):
            kws.setdefault(k, "preferred")
    def covered(kw):  # already listed by the AI, directly or as a synonym
        return any(kw == k or kw in SYNONYMS.get(k, []) or k in SYNONYMS.get(kw, []) for k in kws)

    for kw in sorted(MASTER_TECH_LIST):
        # only the canonical spelling is searched in the JD, to avoid false hits like "CV" = resume
        if kw_regex(kw).search(jd_text) and not covered(kw):
            kws[kw] = "general"
    weight = {"required": 3, "preferred": 2, "general": 1}

    matched, missing = [], []
    got = total = 0
    for kw, pri in kws.items():
        total += weight[pri]
        if has_keyword(kw, text):
            got += weight[pri]
            matched.append({"k": kw, "p": pri})
        else:
            missing.append({"k": kw, "p": pri})
    order = {"required": 0, "preferred": 1, "general": 2}
    matched.sort(key=lambda x: (order[x["p"]], x["k"]))
    missing.sort(key=lambda x: (order[x["p"]], x["k"]))
    kw_score = got / total if total else 0
    req = [m for m in matched if m["p"] == "required"]
    req_total = sum(1 for p in kws.values() if p == "required")

    # ---- other checks
    sec_score, sec_found, sec_missing = check_sections(resume_plain)
    imp_score, metrics = check_impact(resume_plain)
    len_score, words = check_length(resume_plain)
    title_score, title_words = check_title(role, resume_plain)

    parts = [
        {"id": "keywords", "name": "Keyword match", "score": kw_score,
         "detail": f"{len(matched)} of {len(kws)} keywords" +
                   (f" · {len(req)}/{req_total} must-haves" if req_total else "")},
        {"id": "title", "name": "Job title match", "score": title_score,
         "detail": ("Title words: " + ", ".join(title_words)) if title_words else "No job title given"},
        {"id": "sections", "name": "Sections & contact", "score": sec_score,
         "detail": "All present" if not sec_missing else "Missing: " + ", ".join(sec_missing)},
        {"id": "impact", "name": "Measurable impact", "score": imp_score,
         "detail": f"{len(metrics)} numbers/metrics found (aim for 6+)"},
        {"id": "length", "name": "Length", "score": len_score,
         "detail": f"{words} words (ideal 350–850 for one page)"},
    ]
    active = [p for p in parts if p["score"] is not None]
    wsum = sum(WEIGHTS[p["id"]] for p in active)
    overall = sum(p["score"] * WEIGHTS[p["id"]] for p in active) / wsum if wsum else 0
    for p in parts:
        p["weight"] = WEIGHTS[p["id"]] if p["score"] is not None else 0
        p["pct"] = None if p["score"] is None else round(p["score"] * 100)
        del p["score"]

    return {
        "name": name, "resume_path": resume_path, "company": company, "role": role,
        "score": round(overall * 100), "parts": parts,
        "matched": matched, "missing": missing,
        "ai_keywords": bool(ai_keywords),
    }


def calculate_ats_score(resume_path, jd_path):
    jd_path = os.path.join(SCRIPT_DIR, jd_path) if not os.path.isabs(jd_path) else jd_path
    try:
        with open(jd_path, 'r', encoding='utf-8') as f:
            r = scan(resume_path, f.read())
    except Exception as e:
        print(f"Error: {e}")
        return None
    print("\n" + "=" * 50)
    print(f"   ATS SCANNER: {r['name'].upper()}")
    print("=" * 50)
    print(f"RESUME       : {os.path.relpath(r['resume_path'], SCRIPT_DIR)}")
    print(f"COMPANY      : {r['company']}")
    print(f"ROLE         : {r['role']}")
    print(f"OVERALL SCORE: {r['score']}%")
    print("-" * 50)
    for p in r["parts"]:
        pct = "n/a" if p["pct"] is None else f"{p['pct']}%"
        print(f"  {p['name']:<20} {pct:>5}  (weight {p['weight']}%)  {p['detail']}")
    print("-" * 50)
    print(f"Matched ({len(r['matched'])}): {', '.join(m['k'] for m in r['matched'])}")
    if r["missing"]:
        print(f"\n[!] MISSING KEYWORDS ({len(r['missing'])}) (add only if truthful):")
        print("  - " + "\n  - ".join(m['k'] + ("  [must-have]" if m['p'] == 'required' else "")
                                    for m in r["missing"]))
    print("=" * 50)
    return r["score"]


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) >= 2:
        calculate_ats_score(sys.argv[1], sys.argv[2] if len(sys.argv) >= 3 else 'job_description.txt')
        sys.exit(0)
    resumes = get_resume_files()
    if not resumes:
        print("No resumes found (main.tex, resume_*.json, or resumes/*).")
        sys.exit(1)
    print("\nChoose Resume:")
    for i, f in enumerate(resumes):
        print(f"{i + 1}. {f}")
    try:
        idx = int(input("\nEnter choice: ")) - 1
        calculate_ats_score(resumes[idx], 'job_description.txt')
    except (ValueError, IndexError):
        print("Invalid input.")
