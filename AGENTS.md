# sta_manager — Honne's resume tailoring workspace

Instructions for any AI agent (Claude Code, Antigravity/Gemini, Codex, Cursor, Copilot) working here.

## Owner
**Devi Sree Honne** (branch `honne`). This branch is personal; do not add other people's resumes or documents.

## Source of truth
- **`main.tex`** is the master resume and the only trusted source of Honne's facts:
  education, CGPA, internships, projects, patent, certifications, links.
- `branch_honne.txt` is a supplementary profile (same facts, prose form; adds location preference:
  Hyderabad, open to relocation, immediate joining).
- `resume_honne.json` / `resume_honne.tex` are older derived copies; if they disagree with `main.tex`, `main.tex` wins.
- **Never edit `main.tex` while tailoring.** Tailored versions go in `resumes/`.

## Main task: "Here's a job description, make my resume"
When the user pastes a JD (or says "tailor my resume for <job>"), do the full pipeline in one go,
without asking for confirmation in between:

1. **Save the JD** to `job_description.txt`. Put `Company: <name>` and `Job Title: <title>` as the first
   two lines if they are not already obvious, so the scanner labels the report correctly.
2. **Baseline score:** `python ats_checker.py main.tex`
3. **Analyse the JD yourself**, not just the scanner's list. Extract:
   - must-have skills/tools, nice-to-haves, the exact job title, domain words, soft skills,
   - the exact phrasing the JD uses (e.g. "RESTful services" vs "REST APIs").
4. **Map each requirement to real evidence in `main.tex`.** Classify every JD keyword as
   *have it, use JD wording* / *have related evidence* / *genuine gap*.
5. **Write `resumes/<company>_<role>.tex`** (lowercase, underscores) starting from a copy of `main.tex`:
   - Headline line under the name → mirror the JD's job title + top 3–4 matching skills.
   - Professional summary → 3–4 lines, rewritten around the JD's top requirements.
   - Technical skills → reorder so JD-relevant categories/skills come first; use the JD's exact terms
     for skills Honne actually has; drop irrelevant ones if space is tight.
   - Projects/experience → reorder by relevance; rewrite bullets with JD keywords, strong action
     verbs, and the metrics that exist (10,000 records, 40-question eval set, 88% Hit Rate@5).
   - Keep it **one page**, same LaTeX template/packages, no tables/columns/images/icons for content
     (ATS parsers break on them), standard section headings.
6. **Re-score:** `python ats_checker.py resumes/<file>.tex` and iterate until the remaining
   missing keywords are only genuine gaps.
7. **Compile if possible:** `pdflatex -output-directory resumes resumes/<file>.tex`. pdflatex is not
   installed on this machine as of Nov 2026; if missing, tell the user to upload the .tex to Overleaf.
8. **Report back** briefly: before→after score, keywords added, genuine gaps (with honest
   suggestions like "a small project using X would cover this"), and the file path.

## Hard rules — truthfulness
Getting shortlisted on a fabricated resume ends in a failed interview or a rescinded offer.
- **Never invent** skills, tools, employers, dates, metrics, grades, or certifications.
- Allowed: rephrasing, reordering, emphasising, using the JD's synonym for something Honne did,
  surfacing details already implied (e.g. ANPR work used Python and deep learning).
- Not allowed: adding a tool just because the JD lists it. Report it as a gap instead.
- Keep dates, CGPA (8.14), percentages, and the patent number (IN-202641108206) exact.

## ATS formatting checklist
- Single column, plain text in standard fonts, no text inside images or tables.
- Standard headings: Summary, Skills, Projects, Experience, Education, Certifications.
- Spell out acronyms once where the JD does (e.g. "Natural Language Processing (NLP)").
- Escape LaTeX special chars: `\&`, `\%`, `\#`, `\_`.
- File name for upload: `Devi_Sree_Honne_<Company>_Resume.pdf`.

## Other artifacts
On request, also write a cover letter (`resumes/<company>_<role>_cover_letter.txt`) using the same
facts and rules. Keep it under 300 words.

## Scanner
`python ats_checker.py [resume.tex|resume.json] [jd.txt]`. With no args it shows a menu.
It only checks a fixed keyword list (`MASTER_TECH_LIST`), so step 3 (your own JD analysis) is required.
