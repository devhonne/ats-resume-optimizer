"""Prompts for tailoring, repairing and converting resumes. Candidate-agnostic (public beta)."""
import os
import re

TEMPLATE = open(os.path.join(os.path.dirname(__file__), "template.tex"), encoding="utf-8").read()

PRESERVE_RULES = """NON-NEGOTIABLE: this is the candidate's real resume. Do not change who they are.
1. KEEP EVERYTHING. Every skill in the skills section, every project, job/internship, education entry,
   certification, award, link, and every number/metric must still be in your output.
   You may reorder, regroup and reword them; you may not delete any.
2. ADD NOTHING NEW. No new skills, tools, courses/coursework, dates, availability, locations,
   responsibilities or metrics that are not already in the master resume.
3. Matching the job means: put the most relevant existing items first, and where the candidate
   already has a skill, use the job description's exact wording for it. A JD keyword the candidate
   does not have is a GAP: leave it out of the resume and list it in <notes>.
4. ATS-friendly: single column, standard section headings, no tables/images for content,
   escape LaTeX special characters (\\& \\% \\# \\_). Same LaTeX template and packages, one page."""

SYSTEM = ("You tailor a candidate's LaTeX resume to one job description so it passes ATS keyword "
          "screening and reads well to a recruiter.\n\n" + PRESERVE_RULES)


def tailor_prompt(resume_tex, jd, company, role, missing):
    must = [m["k"] for m in missing if m["p"] == "required"]
    other = [m["k"] for m in missing if m["p"] != "required"]
    return f"""Company: {company or "(see JD)"}
Role: {role or "(see JD)"}

{PRESERVE_RULES}

<master_resume>
{resume_tex}
</master_resume>

<job_description>
{jd}
</job_description>

The ATS scanner reports these JD keywords as not visible in the master resume:
- Must-have: {", ".join(must) if must else "(none)"}
- Other: {", ".join(other) if other else "(none)"}
Use one only if the master resume already proves it (then use the JD's exact wording). Otherwise it is a gap.

Return exactly two parts:
<resume>
...the complete tailored LaTeX document, from \\documentclass to \\end{{document}}...
</resume>
<notes>
- What you reordered or reworded, and which JD keywords that surfaced
- Genuine gaps (JD asks, candidate doesn't have) with one honest way to close each
</notes>"""


REPAIR = """The tailored resume below dropped facts from the candidate's master resume.
Put back every item listed under <missing> in the right section, without removing or rewording
anything else, and without adding anything new. Return only the complete LaTeX document.

<missing>
{missing}
</missing>

<master_resume>
{master}
</master_resume>

<tailored_resume>
{tailored}
</tailored_resume>"""

CONVERT = """Convert this resume into the LaTeX template below.

Rules:
- Use EVERY fact from the resume text: name, contact details, links, every skill, job, internship,
  project, education entry, grade, certification, award, and every number. Do not drop anything.
- Do not invent anything. If the resume has no summary, write 2-3 sentences using only its facts.
- Group skills into sensible categories in the "\\textbf{{Category:}} a, b, c" format.
- Drop template sections the resume has no content for; add standard sections it needs.
- Escape LaTeX special characters (\\& \\% \\# \\_ \\$). Keep it to about one page.
- Return only the complete LaTeX document, from \\documentclass to \\end{{document}}.

<template>
{template}
</template>

<resume_text>
{text}
</resume_text>"""


def extract_parts(text):
    """AI reply -> (latex, notes)."""
    m = re.search(r"<resume>\s*(.*?)\s*</resume>", text, re.S)
    tex = m.group(1) if m else text
    tex = re.sub(r"^```(?:latex|tex)?\s*|\s*```$", "", tex.strip())
    if "\\documentclass" in tex:
        tex = tex[tex.index("\\documentclass"):]
    if "\\end{document}" in tex:
        tex = tex[:tex.index("\\end{document}") + len("\\end{document}")] + "\n"
    n = re.search(r"<notes>\s*(.*?)\s*</notes>", text, re.S)
    return tex, (n.group(1).strip() if n else "")


def is_full_latex(tex):
    return "\\documentclass" in tex and "\\end{document}" in tex
