# sta_manager · Resume Studios (branch `honne`)

Personal toolkit for **Devi Sree Honne** to match a resume to any job: ATS scoring, honest
score-raising suggestions, tailoring with AI, and link checks. Built with Claude Code.

> **Continue work:** open this folder in Claude Code (or any AI agent). It reads `CLAUDE.md` → `AGENTS.md`
> automatically. Status, TODOs and how to run everything are below.

---

## 1. What's in here

| Path | What it is |
|---|---|
| `main.tex` | **Master resume** (source of truth for all facts). Never edited by the tools. |
| `ats_checker.py` | **Offline ATS scorer** (no AI). CLI + library used by both apps. |
| `job_description.txt` | Last job description used (the apps save it here). |
| `resumes/` | Tailored copies, one per job (`<company>_<role>.tex`). |
| `uploads/` | Other "original" resumes uploaded in the desktop app (never edited). |
| `resume_studio/` | **Desktop app (Python)**, Honne's daily tool. Details in section 3. |
| `resume-studios-web/` | **Public beta web app (React + FastAPI)**. Details in section 4. Has its own README. |
| `AGENTS.md` | Instructions for any AI agent: tailoring pipeline + truthfulness rules. |
| `CLAUDE.md` | Loads `AGENTS.md` for Claude Code. |
| `.claude/skills/tailor-resume/` | `/tailor-resume` skill for Claude Code. |
| `skills-lock.json` | Third-party design skills (`ui-ux-pro-max` etc.). Reinstall: `npx skills experimental_install`. |
| `branch_honne.txt`, `resume_honne.json/.tex` | Older profile/resume copies (`main.tex` wins if they differ). |
| `resume_template.json` | Blank JSON resume template. |

**Not in git (create locally):**
- `resume_studio/config.json` → `{"gemini_key": "...", "gemini_model": "gemini-3.5-flash"}`. Easiest: open the app → Settings.
- `resume-studios-web/.env` → copy `.env.example`, set `GEMINI_API_KEY`.

---

## 2. The scoring engine (`ats_checker.py`)

```
python ats_checker.py                         # menu
python ats_checker.py main.tex                # score vs job_description.txt
python ats_checker.py resumes/x.tex jd.txt    # any resume vs any JD
```
**Score = Keywords 60% + Job title 10% + Sections & contact 10% + Measurable impact 10% + Length 10%**

- Keywords: built-in list of ~120 tech terms + **synonyms** (ML = machine learning, JS = JavaScript…),
  whole-word matching. With Gemini, the apps add AI-extracted **must-have (3×)** / **nice-to-have (2×)**
  keywords (cached per JD so before/after scores are comparable).
- `find_evidence()`: where each keyword was found ("How we matched").
- `compare_resumes(original, tailored)`: facts **kept / removed / newly added** (skills, projects, roles, numbers).
- `scan_text()`: score in-memory text (used for suggestion point gains).

---

## 3. Desktop app: `resume_studio/` (Python, stdlib server + one HTML page)

**Run:** double-click `resume_studio/Resume Studio.bat`, or `python resume_studio/app.py`.
Opens in an Edge app window at `127.0.0.1:<random port>`; shuts down ~30 s after the window closes.
Needs: Python 3.11, `pypdf` (`pip install pypdf`). A Gemini key is optional (AI features).

**Flow**
1. **Original resume.** `main.tex`, or **upload/paste** .tex/.pdf/.docx/.txt → saved in `uploads/`, never edited.
   PDFs are read locally; if that fails, **Gemini reads the PDF**. Non-LaTeX is converted to LaTeX (every fact kept).
   **Check links** → every link: works / redirects / broken (404) / can't verify (LinkedIn).
2. **Job.** Paste a link (page download → JSON-LD → Gemini extraction → Gemini opens the URL itself) or paste text.
3. **ATS score.** Two animated gauges (**Gemini** + **Local**), breakdown bars, "How we matched", missing keywords.
4. **Raise your score.** Gemini + offline suggestions as **exact edits** (find → replace). Each is re-scored locally
   (**+N pts**). Edits that **remove** an original fact are discarded. Edits that **add** a skill not in the original
   go under **"Needs your OK"** and can't be accepted until the user ticks "this is true".
   Accept → score animates up and a working copy is written to `resumes/`. **Undo** supported.
   "Other ways": copy prompt for Claude/ChatGPT + paste reply, or Auto-tailor with Gemini (auto-restores dropped facts).
- Right panel: **Resume** · **Changes** (diff vs original) · **Review** (facts kept %, removed → Restore with Gemini, new claims) · **Links**.

**Files:** `app.py` (HTTP server + API) · `gemini.py` (Gemini REST client, model fallback, keyword extraction,
suggestions, PDF reading, job extraction) · `suggest.py` (validation + scoring of edits) · `links.py` (link checker) ·
`job_fetch.py` (job link → description) · `resume_parse.py` (PDF/DOCX/TXT → text) · `template.tex` (LaTeX template
for conversions) · `index.html` (whole UI) · `assets/` (logo, favicon).

**Design:** sumi-e ink + vermilion on paper, Noto Serif/Sans JP, liquid glass on nav/controls, ensō score
gauges, SVG icons, light/dark, reduced-motion/transparency support (guided by the `ui-ux-pro-max` skill).
No background image.

**Gemini models** (free tier, Nov 2026): `gemini-3.5-flash` default → falls back to `gemini-3.1-flash-lite`,
`gemini-3.5-flash-lite`, `gemini-flash-latest`. `2.5-*` models are retired for new users; pro models have no free quota.

---

## 4. Public beta web app: `resume-studios-web/` (React + FastAPI)

Separate app for other users (see `resume-studios-web/README.md`).
- `frontend/`: React 18 + Vite 5 + TypeScript. Resumes and versions live in the **browser** (localStorage).
- `backend/`: stateless FastAPI. Same scoring engine (`app/ats.py`), Gemini, job fetch with an **SSRF guard**,
  upload limits, per-IP AI rate limit (shared key) or bring-your-own key.
- Dev: `resume-studios-web/dev.bat` (API :8765 + React :5173). Prod: `docker build` → one container.
- Tested end-to-end (upload → job → scores → paste reply → review → reload → mobile). **Not deployed yet.**
- Does **not** yet have the desktop app's newest features (suggestions with consent, link checker, original upload by Gemini PDF reading).

---

## 5. Rules the tools follow (see `AGENTS.md`)
- **Never remove** anything from the original resume (skills, projects, roles, links, numbers).
- **Never invent** skills, tools, courses, dates, availability or metrics. A missing JD keyword is a **gap**, not an edit.
- Anything that adds a skill is shown to the user and needs explicit consent.

---

## 6. Status & next steps (as of 2026-11-09)

**Done**
- [x] Offline ATS scorer with weighted breakdown, synonyms, evidence, fact comparison
- [x] Desktop app: job links, dual scores, suggestions with consent + animated score, undo, link checker,
      original upload (PDF via Gemini), review/restore, diff, full-rewrite flows
- [x] Web app (public beta) built and tested locally
- [x] Agent docs (`AGENTS.md`, `CLAUDE.md`, `/tailor-resume` skill)

**Open / ideas**
- [ ] Port desktop features (suggestions + consent, link checker) to the web app
- [ ] Deploy the web app (Render/Railway/Cloud Run); set `GEMINI_API_KEY` as a secret
- [ ] Add GitHub repo links to each project in `main.tex` (link checker flagged none)
- [ ] Review `resumes/amazon_sde_1.tex` (has AI-added claims to confirm) and
      `resumes/amazon_sde_i_intern_amazon_university_talent_ac.tex`
- [ ] Optional: install MiKTeX so the **PDF** button works (otherwise use Overleaf)
- [ ] Rotate the Gemini API key once (it was pasted in a chat); new key → app Settings

**Known limits**
- Score is keyword-based: it measures presence, not quality. Real ATS products differ.
- Gemini free tier can be busy (503) or slow; the client retries other models automatically.
