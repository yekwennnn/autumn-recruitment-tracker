"""End-to-end render verification for kami templates.

Renders each template through render.render_pdf, validates page-count against
per-template ceilings, inspects embedded PDF fonts to warn when only a
fallback is used, and runs an advisory density scan over the rendered
examples when invoked for the full suite. Self-sufficient: registries come
from shared, the render pipeline from render, the density scan from checks.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from checks import scan_density
from lint import scan_file
from optional_deps import MissingDepError, require_pypdf_reader
from render import build_slides, render_pdf
from shared import (
    DIAGRAMS,
    EXAMPLES,
    TEMPLATES,
    build_targets,
    default_example_pdfs,
    diagram_targets,
    load_checks_thresholds,
    pptx_targets,
    screen_targets,
)

# Primary fonts expected in embedded PDF font names
CN_PRIMARY_FONTS = {"TsangerJinKai02"}
EN_PRIMARY_FONTS = {"Charter"}
KO_PRIMARY_FONTS = {"Source-Han-Serif-K", "SourceHanSerifK"}
RECOGNIZABLE_FALLBACK_FONT_MARKERS = (
    "Georgia",
    "Palatino",
    "PT-Serif",
    "PTSerif",
    "TsangerJinKai",
    "YuMincho",
    "Hiragino",
    "SourceHan",
    "Noto",
    "Charter",
    "Songti",
    "DejaVu",
    "Liberation",
)


def show_fonts(pdf: Path) -> None:
    if not pdf.exists():
        return
    try:
        out = subprocess.run(["pdffonts", str(pdf)], capture_output=True, text=True, check=False)
        if out.returncode == 0:
            print("--- pdffonts ---")
            print(out.stdout.rstrip())
    except FileNotFoundError:
        pass  # pdffonts not installed; silent


def _pdf_font_names(pdf_path: Path) -> set[str]:
    def _resolve_pdf_obj(obj):
        if obj is None:
            return None
        try:
            return obj.get_object() if hasattr(obj, "get_object") else obj
        except Exception:
            return obj

    try:
        PdfReader = require_pypdf_reader()
        reader = PdfReader(str(pdf_path))
        fonts: set[str] = set()
        for page in reader.pages:
            resources = _resolve_pdf_obj(page.get("/Resources"))
            if resources is None or not hasattr(resources, "get"):
                continue
            font_dict = _resolve_pdf_obj(resources.get("/Font"))
            if font_dict is None or not hasattr(font_dict, "values"):
                continue
            for obj in font_dict.values():
                resolved = _resolve_pdf_obj(obj)
                if resolved is None or not hasattr(resolved, "get"):
                    continue
                base = resolved.get("/BaseFont")
                if base:
                    fonts.add(str(base).lstrip("/"))
        return fonts
    except Exception as exc:
        print(f"  WARN: could not read font names from PDF: {exc}")
        return set()


def _check_font_sources(html_path: Path) -> list[str]:
    """Return list of local @font-face src files that are missing on disk."""
    text = html_path.read_text(encoding="utf-8", errors="replace")
    missing: list[str] = []
    for url in re.findall(r"""url\(["']?([^"')]+)["']?\)""", text):
        if url.startswith(("http://", "https://", "data:", "#")):
            continue
        resolved = (html_path.parent / url).resolve()
        if not resolved.exists():
            missing.append(url)
    return missing


def verify_target(name: str, source: str, max_pages: int, src_dir: Path) -> list[str]:
    """Render `source` to a PDF, then run page-count and font checks."""
    issues: list[str] = []
    src = src_dir / source
    if not src.exists():
        issues.append(f"source not found: {src}")
        return issues

    # Warn about missing local font files before rendering
    missing_fonts = _check_font_sources(src)
    if missing_fonts:
        for mf in missing_fonts:
            print(f"  [FONT MISS] {name}: {mf} not found")
        print(f"  [FONT MISS] Repo fix: git checkout -- assets/fonts (commercial TTFs are tracked)")
        print(f"  [FONT MISS] Skill recovery (downloads to the user font dir, not the skill): bash scripts/ensure-fonts.sh")
        print(f"  [FONT MISS] Fallback: brew install --cask font-source-han-serif-sc")

    out = EXAMPLES / f"{name}.pdf"
    try:
        n = render_pdf(src, out)
    except MissingDepError as exc:
        issues.append(str(exc))
        return issues

    # page count check
    if max_pages and n > max_pages:
        over = n - max_pages
        hint = ""
        if "resume" in name and over == 1:
            hint = '; add class="resume--dense" to <body> or tighten .proj-text line-height to 1.38'
        issues.append(f"page overflow: {n} pages (limit {max_pages}){hint}")

    # font check
    embedded = _pdf_font_names(out)
    fallback_present = any(
        kw in font for font in embedded
        for kw in RECOGNIZABLE_FALLBACK_FONT_MARKERS
    )

    # Diagram templates are language-neutral and often rely on fallback stacks,
    # so only enforce that at least one recognizable serif/sans fallback exists.
    is_diagram = src_dir == DIAGRAMS
    if is_diagram:
        if not fallback_present:
            issues.append(f"no recognizable font embedded in {out.name}")
        return issues

    is_en = name.endswith("-en")
    is_ko = name.endswith("-ko")
    expected = EN_PRIMARY_FONTS if is_en else (KO_PRIMARY_FONTS if is_ko else CN_PRIMARY_FONTS)
    if not any(exp in font_name for exp in expected for font_name in embedded):
        primary = next(iter(expected))
        if not fallback_present:
            issues.append(f"no recognizable font embedded in {out.name}")
        elif os.environ.get("KAMI_ALLOW_FALLBACK_ONLY"):
            # CI / headless boxes never have commercial fonts (TsangerJinKai02,
            # Charter). Treat "primary missing, fallback present" as a warning
            # there so CI can still gate page-count regressions.
            print(f"  WARN: {name}: primary font ({primary}) not embedded; using fallback")
        else:
            issues.append(f"primary font ({primary}) not embedded; using fallback")

    return issues


def verify_screen_target(name: str, source: str) -> list[str]:
    """Lint a browser-only template via lint.scan_file."""
    src = TEMPLATES / source
    if not src.exists():
        return [f"source not found: {src}"]
    findings = scan_file(src)
    if findings:
        return [f"{len(findings)} template violation(s)"]
    return []


def verify_all(target: str | None) -> int:
    """Drive verification across the requested target set."""
    html_targets = build_targets()
    screen_targets_map = screen_targets()
    diagram_targets_map = diagram_targets()
    pptx_targets_map = pptx_targets()

    targets_to_run: dict[str, tuple[str, int, Path] | None] = {}
    screen_targets_to_run: dict[str, str] = {}
    if target:
        if target in html_targets:
            src, mp = html_targets[target]
            targets_to_run[target] = (src, mp, TEMPLATES)
        elif target in screen_targets_map:
            screen_targets_to_run[target] = screen_targets_map[target]
        elif target in diagram_targets_map:
            targets_to_run[target] = (diagram_targets_map[target], 0, DIAGRAMS)
        elif target in pptx_targets_map:
            targets_to_run[target] = None
        else:
            print(f"ERROR: unknown target: {target}")
            return 2
    else:
        for name, (src, mp) in html_targets.items():
            targets_to_run[name] = (src, mp, TEMPLATES)
        for name, src in screen_targets_map.items():
            screen_targets_to_run[name] = src
        for name, src in diagram_targets_map.items():
            targets_to_run[name] = (src, 0, DIAGRAMS)
        for name in pptx_targets_map:
            targets_to_run[name] = None

    failures = 0
    rows: list[tuple[str, str]] = []
    for name, config in targets_to_run.items():
        if config is None:
            issues = [] if build_slides(name) else ["slides build failed"]
        else:
            source, max_pages, src_dir = config
            issues = verify_target(name, source, max_pages, src_dir)
        if issues:
            rows.append((f"ERROR: {name}", "; ".join(issues)))
            failures += 1
        else:
            rows.append((f"OK: {name}", "ok"))

    for name, source in screen_targets_to_run.items():
        issues = verify_screen_target(name, source)
        if issues:
            rows.append((f"ERROR: {name}", "; ".join(issues)))
            failures += 1
        else:
            rows.append((f"OK: {name}", "static HTML template"))

    for status, detail in rows:
        print(f"{status}: {detail}")

    if target is None:
        pdfs = default_example_pdfs()
        if pdfs:
            print()
            print("Density scan (advisory):")
            scan = scan_density(pdfs)
            if scan is not None:
                sparse, warn, _, scanned = scan
                if sparse + warn == 0:
                    print(f"  OK: no density issues across {scanned} PDF(s)")
                else:
                    density_cfg = load_checks_thresholds()["density"]
                    sparse_pct_disp = int(round(float(density_cfg["sparse_pct"]) * 100))
                    warn_pct_disp = int(round(float(density_cfg["warn_pct"]) * 100))
                    if sparse:
                        print(f"  {sparse} SPARSE page(s) (>{sparse_pct_disp}% trailing whitespace) across {scanned} PDF(s)")
                    if warn:
                        print(f"  {warn} WARN page(s) (>{warn_pct_disp}%) across {scanned} PDF(s)")
                    print("  (advisory: re-author with SKILL.md Step 4.1 merge rule. Does not fail --verify.)")

    return 0 if failures == 0 else 1
