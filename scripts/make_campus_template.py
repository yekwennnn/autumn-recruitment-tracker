#!/usr/bin/env python3
"""Generate the Chinese campus resume template from kami's, without forking it.

kami's resume.html is a 社招 (experienced-hire) layout: education last, a
"工作经历" section, and sections only a senior engineer can fill. Campus
resumes need education second and 实习经历 instead. But kami's <style> block
is the whole point of using kami — the typography, spacing and colour system.

So this splices rather than forks:

    kami resume.html  <head> + entire <style> + <body>   (byte-identical)
  + assets/campus-body.html                              (ours)
  = assets/templates/resume-campus-cn.html

Run it after every kami upgrade so the campus template inherits upstream CSS
fixes (CJK wrapping, spacing, font fallbacks) instead of silently rotting.

    python3 scripts/make_campus_template.py [--check]

--check exits non-zero if the generated file is stale, for CI or a pre-commit
sanity pass.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KAMI_TEMPLATE = ROOT / "vendor" / "kami" / "assets" / "templates" / "resume.html"
CAMPUS_BODY = ROOT / "assets" / "campus-body.html"
OUTPUT = ROOT / "assets" / "templates" / "resume-campus-cn.html"

BANNER = """<!-- ===================================================================
     自动生成，不要直接编辑本文件。

     版式（<head> 与 <style>）逐字节来自 kami {version} 的
     assets/templates/resume.html —— © Tw93, MIT License。
     正文结构来自本仓库 assets/campus-body.html。

     要改版式 → 改 kami 或等上游升级；要改章节结构 → 改 campus-body.html。
     改完重新生成：python3 scripts/make_campus_template.py
     =================================================================== -->
"""


def read_kami_version() -> str:
    version_file = ROOT / "vendor" / "kami" / "VERSION"
    try:
        return "V" + version_file.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return "(版本未知)"


def build() -> str:
    """Take kami's head+style verbatim, then splice our body in.

    The <body> tag is located *after* </style> on purpose: kami's stylesheet
    contains the literal text "<body>" inside a CSS comment ("add
    class="resume--dense" to <body> when 5+ projects overflow"), so a naive
    search for "<body>" lands in the middle of the stylesheet and silently
    truncates it.
    """
    kami = KAMI_TEMPLATE.read_text(encoding="utf-8")

    style_end = kami.find("</style>")
    if style_end == -1:
        raise SystemExit(
            f"在 {KAMI_TEMPLATE} 里找不到 </style> —— kami 模板结构变了，"
            "本脚本的拼接假设不再成立，需要人工检查后再改这里。"
        )

    match = re.search(r"<body\b[^>]*>", kami[style_end:])
    if match is None:
        raise SystemExit(
            f"在 {KAMI_TEMPLATE} 的 </style> 之后找不到 <body> 标签 —— "
            "kami 模板结构变了，需要人工检查后再改这里。"
        )
    head = kami[: style_end + match.end()]

    body = CAMPUS_BODY.read_text(encoding="utf-8").rstrip()
    banner = BANNER.format(version=read_kami_version())
    return f"{head}\n\n{banner}\n{body}\n\n</body>\n</html>\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="只检查产物是否最新，不写文件；过期则退出码 1")
    args = ap.parse_args()

    generated = build()

    if args.check:
        if not OUTPUT.exists():
            print(f"过期：{OUTPUT.relative_to(ROOT)} 还没生成", file=sys.stderr)
            return 1
        if OUTPUT.read_text(encoding="utf-8") != generated:
            print(
                f"过期：{OUTPUT.relative_to(ROOT)} 与 kami {read_kami_version()} "
                "或 campus-body.html 不同步，跑 "
                "`python3 scripts/make_campus_template.py` 重新生成",
                file=sys.stderr,
            )
            return 1
        print(f"最新：{OUTPUT.relative_to(ROOT)}（基于 kami {read_kami_version()}）")
        return 0

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(generated, encoding="utf-8")
    style_lines = generated[: generated.find("</style>")].count("\n") + 1
    print(f"已生成 {OUTPUT.relative_to(ROOT)}")
    print(f"  版式来自 kami {read_kami_version()}（{style_lines} 行 head+style，逐字节继承）")
    print(f"  正文来自 {CAMPUS_BODY.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
