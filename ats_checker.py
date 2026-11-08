"""ATS keyword scanner.

Usage:
    python ats_checker.py                         # interactive menu
    python ats_checker.py main.tex                # score a resume vs job_description.txt
    python ats_checker.py resumes/x.tex jd.txt    # score any resume (.tex or .json) vs any JD

Exit output is plain text so AI agents can parse it.
"""
import json
import re
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Technology / skill keywords to look for in any JD.
# Multi-word phrases are matched as whole phrases; everything is case-insensitive.
MASTER_TECH_LIST = {
    # languages
    "python", "javascript", "typescript", "java", "c++", "c#", "sql", "r", "go", "rust", "bash",
    # web / backend
    "react", "react.js", "next.js", "vite", "vue", "angular", "node.js", "express", "express.js",
    "fastapi", "flask", "django", "spring boot", "html", "css", "tailwind", "bootstrap", "redux",
    "rest api", "rest apis", "graphql", "jwt", "microservices", "async python", "pydantic", "uvicorn",
    # data
    "postgresql", "mongodb", "mysql", "sqlite", "supabase", "firebase", "etl", "airflow",
    "apache airflow", "data pipeline", "data pipelines", "data analysis", "data science",
    "pyspark", "spark", "hadoop", "hive", "tableau", "power bi", "excel", "azure databricks",
    "pandas", "numpy",
    # cloud / devops
    "aws", "gcp", "azure", "docker", "kubernetes", "git", "github", "github actions", "ci/cd",
    "terraform", "ansible", "linux", "maven",
    # ai / ml
    "ai", "machine learning", "deep learning", "nlp", "natural language processing",
    "computer vision", "opencv", "ocr", "pytorch", "tensorflow", "keras", "scikit-learn",
    "llm", "llms", "generative ai", "rag", "retrieval-augmented generation", "embeddings",
    "hugging face", "transformers", "prompt engineering", "langchain", "vector database",
    "gemini", "openai", "vertex ai", "tinyml", "edge ai", "model evaluation",
    # cs fundamentals / practice
    "data structures", "algorithms", "oops", "object-oriented", "distributed systems",
    "software engineering", "software development", "agile", "scrum", "unit testing",
    "debugging", "troubleshooting", "technical documentation", "api integration",
    "problem solving", "communication",
}


def kw_regex(kw):
    """Whole-word / whole-phrase match that tolerates special chars like + # . /"""
    return re.compile(rf'(?<![\w]){re.escape(kw)}(?![\w])')


def get_resume_files():
    files = [f for f in os.listdir(SCRIPT_DIR)
             if (f.endswith('.json') and f.startswith('resume_') and 'template' not in f)
             or f == 'main.tex']
    resumes_dir = os.path.join(SCRIPT_DIR, 'resumes')
    if os.path.isdir(resumes_dir):
        files += [os.path.join('resumes', f) for f in sorted(os.listdir(resumes_dir))
                  if f.endswith('.tex') or f.endswith('.json')]
    return files


def latex_to_text(tex):
    """Rough LaTeX -> plain text so keywords inside the .tex can be scored."""
    tex = tex.split(r'\begin{document}', 1)[-1]
    tex = re.sub(r'(?<!\\)%.*', ' ', tex)                         # comments
    tex = re.sub(r'\\href\{[^}]*\}', ' ', tex)                     # drop URLs, keep link text
    tex = tex.replace(r'\&', '&').replace(r'\%', '%').replace(r'\#', '#')
    tex = tex.replace('--', '-')
    tex = re.sub(r'\\[a-zA-Z]+\*?(\[[^\]]*\])?', ' ', tex)         # commands
    tex = re.sub(r'[{}\\]', ' ', tex)
    return re.sub(r'\s+', ' ', tex)


def load_resume_text(path):
    """Returns (name, lowercase_text)."""
    with open(path, 'r', encoding='utf-8') as f:
        raw = f.read()
    if path.endswith('.json'):
        data = json.loads(raw)

        def walk(o):
            if isinstance(o, dict):
                return [x for v in o.values() for x in walk(v)]
            if isinstance(o, list):
                return [x for v in o for x in walk(v)]
            return [str(o)]

        name = data.get('personal_info', {}).get('name', 'User')
        return name, " ".join(walk(data)).lower()
    text = latex_to_text(raw)
    m = re.search(r'\\textbf\{([A-Z][A-Z .]+)\}', raw)
    name = m.group(1).strip() if m else os.path.basename(path)
    return name, text.lower()


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

    if len(company) > 35:
        company = company[:32] + "..."
    if len(role) > 40:
        role = role[:37] + "..."
    return company, role


def calculate_ats_score(resume_path, jd_path):
    resume_path = os.path.join(SCRIPT_DIR, resume_path) if not os.path.isabs(resume_path) else resume_path
    jd_path = os.path.join(SCRIPT_DIR, jd_path) if not os.path.isabs(jd_path) else jd_path
    try:
        name, resume_text = load_resume_text(resume_path)
        with open(jd_path, 'r', encoding='utf-8') as f:
            jd_raw = f.read()
    except Exception as e:
        print(f"Error: {e}")
        return None

    jd_text = jd_raw.lower()
    company, role = parse_jd_header(jd_raw)

    required = {kw for kw in MASTER_TECH_LIST if kw_regex(kw).search(jd_text)}
    matched = sorted(kw for kw in required if kw_regex(kw).search(resume_text))
    missing = sorted(required - set(matched))
    score = int(len(matched) / len(required) * 100) if required else 0

    print("\n" + "=" * 45)
    print(f"   ATS SCANNER: {name.upper()}")
    print("=" * 45)
    print(f"RESUME       : {os.path.relpath(resume_path, SCRIPT_DIR)}")
    print(f"COMPANY      : {company}")
    print(f"ROLE         : {role}")
    print(f"OVERALL MATCH: {score}%")
    print(f"Matched ({len(matched)}): {', '.join(matched)}")
    if missing:
        print(f"\n[!] MISSING KEYWORDS ({len(missing)}) (add only if truthful):")
        print("  - " + "\n  - ".join(missing))
    print("\n" + "-" * 45)
    print("NOTE: This only checks a fixed keyword list. Also read the JD for")
    print("role-specific terms not in the list (tools, domains, soft skills).")
    print("=" * 45)
    return score


if __name__ == "__main__":
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
