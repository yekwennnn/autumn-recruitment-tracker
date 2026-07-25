#!/usr/bin/env python3
"""Extract plain text from a resume file (PDF/DOCX/MD/TXT).

Fallback chain for agents that cannot read PDFs natively:
  PDF  -> pdftotext (poppler) -> pypdf (if installed) -> error with guidance
  DOCX -> stdlib zipfile + regex strip
  MD/TXT -> read as-is

Usage:
  python3 extract_text.py --file /path/to/resume.pdf

Prints plain text to stdout. On failure exits non-zero with guidance on stderr.
"""
import argparse
import html
import importlib
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


def extract_plain(path):
    return Path(path).read_text(encoding="utf-8", errors="replace")


def extract_docx(path):
    with zipfile.ZipFile(path) as zf:
        xml = zf.read("word/document.xml").decode("utf-8", errors="replace")
    xml = xml.replace("</w:p>", "\n")
    xml = xml.replace("<w:tab/>", "\t")
    text = re.sub(r"<[^>]+>", "", xml)
    text = html.unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def extract_pdf(path):
    if shutil.which("pdftotext"):
        proc = subprocess.run(
            ["pdftotext", "-layout", path, "-"],
            capture_output=True, text=True,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout
    try:
        pypdf = importlib.import_module("pypdf")
    except ImportError:
        sys.stderr.write(
            "无法抽取PDF文本：未找到 pdftotext（poppler），也未安装 pypdf。"
            "请任选其一：pip install pypdf；或将简历导出为 TXT/MD/DOCX 后重试。\n"
        )
        sys.exit(2)
    reader = pypdf.PdfReader(path)
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    args = ap.parse_args()

    path = Path(args.file)
    if not path.exists():
        sys.stderr.write(f"文件不存在：{path}\n")
        sys.exit(2)

    ext = path.suffix.lower()
    if ext in (".md", ".markdown", ".txt"):
        text = extract_plain(path)
    elif ext == ".docx":
        text = extract_docx(path)
    elif ext == ".pdf":
        text = extract_pdf(str(path))
    else:
        sys.stderr.write(f"不支持的格式：{ext}。支持 PDF/DOCX/MD/TXT。\n")
        sys.exit(2)

    sys.stdout.write(text)


if __name__ == "__main__":
    main()
