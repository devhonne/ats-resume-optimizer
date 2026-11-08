---
name: tailor-resume
description: Build an ATS-optimised, one-page LaTeX resume for Devi Sree Honne tailored to a pasted job description, using only true facts from main.tex. Use when the user pastes a JD, a job link's text, or says "tailor/make my resume for <company/role>".
---

# Tailor resume to a job description

Input: the job description in `$ARGUMENTS` or in the user's message. If neither has one, read
`job_description.txt`. Only ask the user when no JD exists anywhere.

Follow the pipeline in `AGENTS.md` ("Main task") end to end, without pausing for confirmation:

1. Save the JD → `job_description.txt` (first lines `Company:` and `Job Title:`).
2. `python ats_checker.py main.tex` → baseline.
3. Read `main.tex` fully. Build a requirement → evidence table (keep it internal):
   | JD requirement (exact wording) | Evidence in main.tex | Status: have / related / gap |
4. Write `resumes/<company>_<role>.tex` from a copy of `main.tex`:
   headline, summary, skills order, project/experience order and bullets, all aligned to the JD.
   Truthfulness rules in AGENTS.md are absolute.
5. `python ats_checker.py resumes/<company>_<role>.tex` → iterate until only genuine gaps remain.
   Also check by hand that every must-have JD term Honne really has appears verbatim at least once.
6. One-page check: `main.tex` fills about one page, so the tailored file must not be longer than it
   (same sections, similar bullet count). Trim the least relevant bullets rather than adding any. Compile with `pdflatex` if available; otherwise point to Overleaf.
7. Reply with:
   - `Score: X% → Y%` and the file path
   - Keywords now covered
   - Genuine gaps + one concrete, honest way to close each (course, mini-project)
   - Optional: offer a cover letter.

Quality bar for bullets: action verb + what was built + tech used (JD's wording) + result/metric.
Example: "Built an automated ETL pipeline with Apache Airflow, Docker, and PostgreSQL processing
10,000+ sales records across star-schema dimension tables."
