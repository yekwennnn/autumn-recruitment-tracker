#!/usr/bin/env python3
"""Generate the two Chinese resume templates from the shared Kami shell."""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
TEMPLATES = ASSETS / "templates"


def remove_paid_font_faces(text: str) -> str:
    text = re.sub(r"\s*/\* W04 / regular face.*?font-style: normal;\s*}\s*", "\n", text, flags=re.S)
    text = re.sub(r"\s*/\* W05 / medium face.*?font-style: normal;\s*}\s*", "\n", text, flags=re.S)
    text = re.sub(r'--serif:\s*"TsangerJinKai02"[^;]+;', '--serif: "LXGW WenKai", "Noto Serif CJK SC", "Source Han Serif SC", "Songti SC", "STSong", Georgia, serif;', text)
    return text


def replace_body(shell: str, body: str) -> str:
    start = shell.find("<body>")
    end = shell.find("</body>")
    if start < 0 or end < 0 or end <= start:
        raise RuntimeError("Kami shell 缺少 body 标签")
    return shell[: start + len("<body>")] + "\n" + body.strip() + "\n" + shell[end:]


def main():
    shell = remove_paid_font_faces((TEMPLATES / "resume-campus-cn.html").read_text(encoding="utf-8"))
    campus_body = (ASSETS / "campus-body.html").read_text(encoding="utf-8")
    social_body = (ASSETS / "social-body.html").read_text(encoding="utf-8")
    (TEMPLATES / "resume-campus-cn.html").write_text(replace_body(shell, campus_body), encoding="utf-8")
    (TEMPLATES / "resume-social-cn.html").write_text(replace_body(shell, social_body), encoding="utf-8")
    print("generated resume-campus-cn.html and resume-social-cn.html")


if __name__ == "__main__":
    main()
