"""Uploaded resume file -> text. PDF via pypdf, DOCX via its XML, TEX/TXT as-is."""
import io
import re
import zipfile

MAX_BYTES = 5 * 1024 * 1024
KINDS = {".tex": "latex", ".txt": "text", ".md": "text", ".pdf": "pdf", ".docx": "docx"}


def kind_of(filename):
    for ext, k in KINDS.items():
        if filename.lower().endswith(ext):
            return k
    raise ValueError("Upload a .tex, .pdf, .docx or .txt resume.")


def pdf_text(data):
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    if len(reader.pages) > 6:
        raise ValueError("That PDF has more than 6 pages. Upload your resume only.")
    return "\n".join((p.extract_text() or "") for p in reader.pages)


def docx_text(data):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    except (zipfile.BadZipFile, KeyError):
        raise ValueError("That doesn't look like a valid .docx file.") from None
    paras = []
    for p in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S):
        t = "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p))
        if t.strip():
            paras.append(t)
    import html
    return html.unescape("\n".join(paras))


def read_upload(filename, data):
    """-> (kind, text)"""
    if len(data) > MAX_BYTES:
        raise ValueError("File is larger than 5 MB.")
    kind = kind_of(filename)
    if kind == "pdf":
        text = pdf_text(data)
    elif kind == "docx":
        text = docx_text(data)
    else:
        text = data.decode("utf-8", errors="replace")
    text = text.replace("\x00", "").strip()
    if len(text) < 200:
        raise ValueError("Couldn't read enough text from that file. If it's a scanned PDF, "
                         "upload a text-based PDF, DOCX or .tex instead.")
    return kind, text[:200_000]
