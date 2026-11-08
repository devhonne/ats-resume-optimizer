"""Resume Studio — desktop GUI for Honne's ATS scanner and AI resume tailoring.

Run:  python resume_studio.py
AI tailoring needs:  pip install anthropic  and an Anthropic API key (Settings button).
Without a key, use "Copy AI prompt" and paste it into any AI chat, then "Paste AI result".
"""
import json
import os
import re
import shutil
import subprocess
import threading
import tkinter as tk
import webbrowser
from tkinter import ttk, filedialog, messagebox, scrolledtext

import ats_checker

APP_DIR = os.path.dirname(os.path.abspath(__file__))
RESUMES_DIR = os.path.join(APP_DIR, "resumes")
MASTER = os.path.join(APP_DIR, "main.tex")
CONFIG = os.path.join(APP_DIR, "studio_config.json")   # gitignored, holds the API key
MODEL = "claude-opus-5-5"

ACCENT = "#1f3a5f"
GOOD, MID, BAD = "#1e7d32", "#b26a00", "#c62828"


# ---------------------------------------------------------------- helpers
def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def load_config():
    try:
        return json.loads(read(CONFIG))
    except Exception:
        return {}


def save_config(cfg):
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def slug(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40] or "job"


def build_prompts(resume_tex, jd, company, role, missing):
    """System + user prompt. Rules come from AGENTS.md so there is one source of truth."""
    rules = read(os.path.join(APP_DIR, "AGENTS.md")) if os.path.exists(
        os.path.join(APP_DIR, "AGENTS.md")) else ""
    system = (
        "You tailor Devi Sree Honne's LaTeX resume to a job description so it passes ATS "
        "keyword screening and reads well to a recruiter. Follow these project rules exactly, "
        "especially the truthfulness rules: never invent skills, tools, metrics, or experience.\n\n"
        + rules
    )
    user = f"""Company: {company or "(see JD)"}
Role: {role or "(see JD)"}

<master_resume>
{resume_tex}
</master_resume>

<job_description>
{jd}
</job_description>

The keyword scanner reports these JD keywords as missing from the master resume:
{", ".join(missing) if missing else "(none)"}
Include a missing keyword only where the master resume gives honest evidence for it.

Return exactly two parts:
<resume>
...the complete tailored LaTeX document, from \\documentclass to \\end{{document}}, one page,
same template and packages...
</resume>
<notes>
- Keywords added and where
- Genuine gaps (JD asks, Honne doesn't have) with one honest way to close each
</notes>"""
    return system, user


def extract_parts(text):
    m = re.search(r"<resume>\s*(.*?)\s*</resume>", text, re.S)
    tex = m.group(1) if m else text
    tex = re.sub(r"^```(?:latex|tex)?\s*|\s*```$", "", tex.strip())
    n = re.search(r"<notes>\s*(.*?)\s*</notes>", text, re.S)
    return tex, (n.group(1) if n else "")


# ---------------------------------------------------------------- app
class Studio(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Resume Studio — Devi Sree Honne")
        self.geometry("1180x760")
        self.minsize(900, 600)
        self.cfg = load_config()
        self.last_scan = None
        self.last_output = None
        self._style()
        self._build()
        self.refresh_resumes()
        jd_file = os.path.join(APP_DIR, "job_description.txt")
        if os.path.exists(jd_file):
            self.jd.insert("1.0", read(jd_file))

    # ---------- look
    def _style(self):
        s = ttk.Style(self)
        try:
            s.theme_use("clam")
        except tk.TclError:
            pass
        s.configure(".", font=("Segoe UI", 10))
        s.configure("Header.TLabel", font=("Segoe UI Semibold", 16), foreground=ACCENT)
        s.configure("Sub.TLabel", foreground="#555")
        s.configure("Score.TLabel", font=("Segoe UI Semibold", 40))
        s.configure("Accent.TButton", foreground="white", background=ACCENT, padding=(12, 6))
        s.map("Accent.TButton", background=[("active", "#2c5282"), ("disabled", "#9aa5b1")])
        s.configure("TButton", padding=(10, 5))

    # ---------- layout
    def _build(self):
        top = ttk.Frame(self, padding=(16, 12, 16, 4))
        top.pack(fill="x")
        ttk.Label(top, text="Resume Studio", style="Header.TLabel").pack(side="left")
        ttk.Label(top, text="  ATS scan + AI tailoring from main.tex", style="Sub.TLabel").pack(side="left")
        ttk.Button(top, text="Settings", command=self.open_settings).pack(side="right")
        ttk.Button(top, text="Open resumes folder", command=self.open_folder).pack(side="right", padx=6)

        bar = ttk.Frame(self, padding=(16, 4))
        bar.pack(fill="x")
        ttk.Label(bar, text="Resume:").pack(side="left")
        self.resume_var = tk.StringVar()
        self.resume_box = ttk.Combobox(bar, textvariable=self.resume_var, width=38, state="readonly")
        self.resume_box.pack(side="left", padx=(4, 16))
        ttk.Label(bar, text="Company:").pack(side="left")
        self.company_var = tk.StringVar()
        ttk.Entry(bar, textvariable=self.company_var, width=20).pack(side="left", padx=(4, 16))
        ttk.Label(bar, text="Role:").pack(side="left")
        self.role_var = tk.StringVar()
        ttk.Entry(bar, textvariable=self.role_var, width=28).pack(side="left", padx=4)

        body = ttk.PanedWindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=16, pady=8)

        # left: JD
        left = ttk.Frame(body)
        body.add(left, weight=3)
        head = ttk.Frame(left)
        head.pack(fill="x")
        ttk.Label(head, text="Job description (paste here)").pack(side="left")
        ttk.Button(head, text="Load file…", command=self.load_jd).pack(side="right")
        ttk.Button(head, text="Clear", command=lambda: self.jd.delete("1.0", "end")).pack(side="right", padx=4)
        self.jd = scrolledtext.ScrolledText(left, wrap="word", font=("Consolas", 10), undo=True)
        self.jd.pack(fill="both", expand=True, pady=(4, 0))

        # right: results / output
        right = ttk.Notebook(body)
        body.add(right, weight=2)
        self.tab_scan = ttk.Frame(right, padding=12)
        self.tab_out = ttk.Frame(right, padding=8)
        right.add(self.tab_scan, text="ATS result")
        right.add(self.tab_out, text="Tailored resume")
        self.notebook = right

        self.score_lbl = ttk.Label(self.tab_scan, text="–", style="Score.TLabel")
        self.score_lbl.pack(anchor="w")
        self.meta_lbl = ttk.Label(self.tab_scan, text="Paste a JD and press Scan.", style="Sub.TLabel")
        self.meta_lbl.pack(anchor="w", pady=(0, 8))
        self.progress = ttk.Progressbar(self.tab_scan, maximum=100)
        self.progress.pack(fill="x", pady=(0, 10))
        ttk.Label(self.tab_scan, text="Matched keywords").pack(anchor="w")
        self.matched_txt = tk.Text(self.tab_scan, height=6, wrap="word", fg=GOOD, relief="flat", bg="#f1f8f1")
        self.matched_txt.pack(fill="x", pady=(2, 10))
        ttk.Label(self.tab_scan, text="Missing keywords (add only if true)").pack(anchor="w")
        self.missing_txt = tk.Text(self.tab_scan, height=6, wrap="word", fg=BAD, relief="flat", bg="#fdf1f1")
        self.missing_txt.pack(fill="x", pady=(2, 10))
        ttk.Label(self.tab_scan, text="AI notes / gaps").pack(anchor="w")
        self.notes_txt = scrolledtext.ScrolledText(self.tab_scan, height=8, wrap="word", relief="flat", bg="#f6f7f9")
        self.notes_txt.pack(fill="both", expand=True, pady=(2, 0))

        out_bar = ttk.Frame(self.tab_out)
        out_bar.pack(fill="x")
        ttk.Button(out_bar, text="Copy LaTeX", command=self.copy_output).pack(side="left")
        ttk.Button(out_bar, text="Open Overleaf", command=lambda: webbrowser.open("https://www.overleaf.com/project")).pack(side="left", padx=4)
        self.pdf_btn = ttk.Button(out_bar, text="Compile PDF", command=self.compile_pdf)
        self.pdf_btn.pack(side="left")
        if not shutil.which("pdflatex"):
            self.pdf_btn.state(["disabled"])
        self.out_txt = scrolledtext.ScrolledText(self.tab_out, wrap="none", font=("Consolas", 9))
        self.out_txt.pack(fill="both", expand=True, pady=(6, 0))

        # bottom actions
        actions = ttk.Frame(self, padding=(16, 4, 16, 12))
        actions.pack(fill="x")
        ttk.Button(actions, text="1  Scan ATS", style="Accent.TButton", command=self.do_scan).pack(side="left")
        self.ai_btn = ttk.Button(actions, text="2  Tailor with AI", style="Accent.TButton", command=self.do_tailor)
        self.ai_btn.pack(side="left", padx=8)
        ttk.Separator(actions, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(actions, text="Copy AI prompt (no API key)", command=self.copy_prompt).pack(side="left")
        ttk.Button(actions, text="Paste AI result…", command=self.paste_result).pack(side="left", padx=6)
        self.status = tk.StringVar(value="Ready.")
        ttk.Label(actions, textvariable=self.status, style="Sub.TLabel").pack(side="right")

    # ---------- data
    def refresh_resumes(self, select=None):
        files = ats_checker.get_resume_files()
        self.resume_box["values"] = files
        if select and select in files:
            self.resume_var.set(select)
        elif "main.tex" in files and not self.resume_var.get():
            self.resume_var.set("main.tex")

    def jd_text(self):
        return self.jd.get("1.0", "end").strip()

    def header_jd(self):
        """JD with Company/Job Title lines so the scanner labels it correctly."""
        jd = self.jd_text()
        extra = ""
        if self.company_var.get().strip():
            extra += f"Company: {self.company_var.get().strip()}\n"
        if self.role_var.get().strip():
            extra += f"Job Title: {self.role_var.get().strip()}\n"
        return extra + jd

    def need_jd(self):
        if len(self.jd_text()) < 40:
            messagebox.showwarning("No job description", "Paste the job description first.")
            return False
        return True

    # ---------- actions
    def load_jd(self):
        p = filedialog.askopenfilename(initialdir=APP_DIR, filetypes=[("Text", "*.txt *.md"), ("All", "*.*")])
        if p:
            self.jd.delete("1.0", "end")
            self.jd.insert("1.0", read(p))

    def do_scan(self, resume=None, quiet=False):
        if not self.need_jd():
            return None
        resume = resume or self.resume_var.get() or "main.tex"
        jd = self.header_jd()
        with open(os.path.join(APP_DIR, "job_description.txt"), "w", encoding="utf-8") as f:
            f.write(jd)
        try:
            r = ats_checker.scan(resume, jd)
        except Exception as e:
            messagebox.showerror("Scan failed", str(e))
            return None
        if not self.company_var.get() and r["company"] != "Unknown Company":
            self.company_var.set(r["company"])
        if not self.role_var.get() and r["role"] != "Unknown Role":
            self.role_var.set(r["role"])
        self.show_scan(r)
        self.last_scan = r
        if not quiet:
            self.status.set(f"Scanned {resume}.")
        return r

    def show_scan(self, r, before=None):
        color = GOOD if r["score"] >= 80 else MID if r["score"] >= 60 else BAD
        txt = f"{r['score']}%" if before is None else f"{before}% → {r['score']}%"
        self.score_lbl.configure(text=txt, foreground=color)
        self.meta_lbl.configure(text=f"{os.path.relpath(r['resume_path'], APP_DIR)}  ·  {r['company']}  ·  {r['role']}")
        self.progress["value"] = r["score"]
        for box, items in ((self.matched_txt, r["matched"]), (self.missing_txt, r["missing"])):
            box.configure(state="normal")
            box.delete("1.0", "end")
            box.insert("1.0", ",  ".join(items) or "—")
            box.configure(state="disabled")
        self.notebook.select(self.tab_scan)

    def _prompt_inputs(self):
        base = self.do_scan(resume="main.tex", quiet=True)
        if not base:
            return None
        system, user = build_prompts(read(MASTER), self.jd_text(), self.company_var.get().strip(),
                                     self.role_var.get().strip(), base["missing"])
        return base, system, user

    def copy_prompt(self):
        got = self._prompt_inputs()
        if not got:
            return
        _, system, user = got
        self.clipboard_clear()
        self.clipboard_append(system + "\n\n---\n\n" + user)
        self.status.set("Prompt copied. Paste it into Claude/ChatGPT/Gemini, then use 'Paste AI result…'.")
        messagebox.showinfo("Prompt copied",
                            "Paste it into any AI chat (claude.ai, Gemini, ChatGPT).\n\n"
                            "Copy the AI's full reply, then click 'Paste AI result…'.")

    def paste_result(self):
        win = tk.Toplevel(self)
        win.title("Paste AI result")
        win.geometry("760x520")
        ttk.Label(win, text="Paste the AI's full reply (the <resume> part is enough):", padding=8).pack(anchor="w")
        box = scrolledtext.ScrolledText(win, wrap="none", font=("Consolas", 9))
        box.pack(fill="both", expand=True, padx=8)
        try:
            box.insert("1.0", self.clipboard_get())
        except tk.TclError:
            pass

        def ok():
            text = box.get("1.0", "end")
            if "\\documentclass" not in text:
                messagebox.showwarning("Not LaTeX", "That doesn't contain a LaTeX resume (\\documentclass).", parent=win)
                return
            win.destroy()
            self.finish(text)

        ttk.Button(win, text="Save & scan", style="Accent.TButton", command=ok).pack(pady=8)

    def do_tailor(self):
        try:
            import anthropic  # noqa: F401
        except ImportError:
            messagebox.showerror("Missing package", "Run:  pip install anthropic\n\nOr use 'Copy AI prompt' instead.")
            return
        key = self.cfg.get("api_key") or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            if messagebox.askyesno("API key needed", "No Anthropic API key set.\nOpen Settings to add one?\n\n"
                                   "(Or use 'Copy AI prompt' for free with any AI chat.)"):
                self.open_settings()
            return
        got = self._prompt_inputs()
        if not got:
            return
        _, system, user = got
        self.ai_btn.state(["disabled"])
        self.status.set("Tailoring with Claude… (30–90 s)")
        threading.Thread(target=self._call_claude, args=(key, system, user), daemon=True).start()

    def _call_claude(self, key, system, user):
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        chars = 0
        try:
            with client.beta.messages.stream(
                model=MODEL,
                max_tokens=64000,
                output_config={"effort": "high"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                system=system,
                messages=[{"role": "user", "content": user}],
            ) as stream:
                for text in stream.text_stream:
                    chars += len(text)
                    if chars % 400 < len(text):
                        self.after(0, self.status.set, f"Writing resume… {chars:,} characters")
                msg = stream.get_final_message()
            if msg.stop_reason == "refusal":
                raise RuntimeError("Claude declined this request. Try the Copy AI prompt option.")
            if msg.stop_reason == "max_tokens":
                raise RuntimeError("Response was cut off. Try again.")
            text = "".join(b.text for b in msg.content if b.type == "text")
            self.after(0, self.finish, text)
        except anthropic.AuthenticationError:
            self.after(0, self._fail, "Invalid API key. Check Settings.")
        except anthropic.RateLimitError:
            self.after(0, self._fail, "Rate limited. Wait a minute and retry.")
        except anthropic.APIConnectionError:
            self.after(0, self._fail, "Network error. Check your internet connection.")
        except anthropic.APIStatusError as e:
            self.after(0, self._fail, f"API error {e.status_code}: {e.message}")
        except Exception as e:
            self.after(0, self._fail, str(e))

    def _fail(self, msg):
        self.ai_btn.state(["!disabled"])
        self.status.set("Failed.")
        messagebox.showerror("AI tailoring failed", msg)

    def finish(self, reply):
        self.ai_btn.state(["!disabled"])
        tex, notes = extract_parts(reply)
        os.makedirs(RESUMES_DIR, exist_ok=True)
        name = f"{slug(self.company_var.get() or 'company')}_{slug(self.role_var.get() or 'role')}.tex"
        path = os.path.join(RESUMES_DIR, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(tex)
        self.last_output = path
        rel = os.path.join("resumes", name)
        before = self.last_scan["score"] if self.last_scan else None
        self.refresh_resumes(select=rel)
        r = ats_checker.scan(rel, self.header_jd())
        self.show_scan(r, before=before)
        self.notes_txt.delete("1.0", "end")
        self.notes_txt.insert("1.0", notes or "(no notes returned)")
        self.out_txt.delete("1.0", "end")
        self.out_txt.insert("1.0", tex)
        self.status.set(f"Saved {rel}")

    def copy_output(self):
        self.clipboard_clear()
        self.clipboard_append(self.out_txt.get("1.0", "end"))
        self.status.set("LaTeX copied. Paste into a new Overleaf project.")

    def compile_pdf(self):
        if not self.last_output:
            messagebox.showinfo("Nothing to compile", "Tailor a resume first.")
            return
        r = subprocess.run(["pdflatex", "-interaction=nonstopmode", "-output-directory", RESUMES_DIR,
                            self.last_output], capture_output=True, text=True)
        pdf = self.last_output[:-4] + ".pdf"
        if os.path.exists(pdf):
            os.startfile(pdf)
            self.status.set(f"PDF ready: {os.path.basename(pdf)}")
        else:
            messagebox.showerror("pdflatex failed", r.stdout[-1500:])

    def open_folder(self):
        os.makedirs(RESUMES_DIR, exist_ok=True)
        os.startfile(RESUMES_DIR)

    def open_settings(self):
        win = tk.Toplevel(self)
        win.title("Settings")
        win.resizable(False, False)
        frm = ttk.Frame(win, padding=16)
        frm.pack()
        ttk.Label(frm, text="Anthropic API key").grid(row=0, column=0, sticky="w")
        var = tk.StringVar(value=self.cfg.get("api_key", ""))
        ttk.Entry(frm, textvariable=var, width=52, show="•").grid(row=1, column=0, pady=4)
        ttk.Label(frm, text="Get one at console.anthropic.com. Stored only in studio_config.json\n"
                            "(this file is gitignored, so it never gets pushed).",
                  style="Sub.TLabel").grid(row=2, column=0, sticky="w")

        def save():
            self.cfg["api_key"] = var.get().strip()
            save_config(self.cfg)
            win.destroy()
            self.status.set("Settings saved.")

        ttk.Button(frm, text="Save", style="Accent.TButton", command=save).grid(row=3, column=0, pady=(12, 0), sticky="e")


if __name__ == "__main__":
    Studio().mainloop()
