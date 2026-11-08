# Resume Studios (public beta)

Match your resume to any job. Upload a resume, paste a job link, get an ATS score, and tailor the
resume to the job **without losing or inventing a single fact**.

- **React + Vite + TypeScript** frontend (`frontend/`) with a sumi-e ink-wash, liquid-glass design
- **FastAPI** backend (`backend/`) reusing the Resume Studio scoring engine
- **Google Gemini** for job-link reading, PDF/DOCX → LaTeX conversion, AI keyword scoring and tailoring

## Features
| | |
|---|---|
| Resume input | Upload `.tex`, `.pdf`, `.docx`, `.txt` or paste. Non-LaTeX resumes are converted to a clean LaTeX template with every fact kept. |
| Job input | Paste a job link (we download the page; Gemini extracts the description) or paste the text. |
| Two scores | **Local** (offline keyword list + synonyms) and **Gemini** (AI-extracted must-have / nice-to-have keywords). Score = keywords 60% · title 10% · sections 10% · measurable impact 10% · length 10%. |
| How we matched | Every matched keyword shows where it was found in the resume. |
| Enhance | Copy a ready prompt for Claude/ChatGPT and paste the reply back, or auto-tailor with Gemini. |
| Review | Each version is checked against the master: facts kept %, anything removed (one-click restore), anything new (flagged). |
| Changes | Line diff of each version vs the master `.tex`. |

## Privacy model
- **The server is stateless.** Resumes and job descriptions are processed in memory and never stored.
- The master resume, versions and settings live in the user's browser (`localStorage`); "Delete all my data" is in Settings.
- AI features send the needed text to Google Gemini. The local score uses no AI.

## Run locally (Windows)
```bat
copy .env.example .env      &rem then put your Gemini key in .env
pip install -r backend\requirements.txt
dev.bat                     &rem API on :8765, React on :5173, opens the browser
```
Or production-style (one server):
```bash
cd frontend && npm ci && npm run build && cd ..
cd backend && uvicorn app.main:app --port 8000      # serves the built app at http://localhost:8000
```

## Deploy (one container)
```bash
docker build -t resume-studios .
docker run -p 8000:8000 -e GEMINI_API_KEY=... -e AI_CALLS_PER_HOUR=30 resume-studios
```
Works on Render, Railway, Fly.io, Google Cloud Run, etc. (set `GEMINI_API_KEY` as a secret; the
platform provides `PORT`). API docs: `/api/docs`.

## Configuration
| Variable | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | — | Shared key for the free beta tier. Without it, users must add their own key. |
| `AI_CALLS_PER_HOUR` | `30` | AI actions per client IP per hour on the shared key (tailoring counts 2). |
| `CORS_ORIGINS` | — | Comma-separated origins, only if the frontend is hosted on another domain. |

## Security notes
- Job-link fetching blocks private, loopback, link-local and metadata addresses (also on redirects), non-standard ports and non-http(s) schemes (SSRF guard).
- Upload limit 5 MB; allowed types `.tex .pdf .docx .txt .md`; request body fields are length-limited.
- Rate limiting uses the connection address. Run uvicorn with `--proxy-headers` behind a trusted proxy (the Dockerfile does).
- User-supplied Gemini keys are sent per request in a header and never stored server-side.

## Beta limitations
- No PDF export on the server: download the `.tex` or copy it into Overleaf.
- The in-memory rate limit and keyword cache reset on restart and are per-instance.
- Scanned (image-only) PDFs can't be read; use a text PDF, DOCX or `.tex`.
