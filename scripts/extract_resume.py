#!/usr/bin/env python3
"""Best-effort resume text and photo extraction.

The skill never invents text when extraction fails.  It returns a clear error
so the conversation can ask the user for a different format.
"""
from __future__ import annotations

import argparse
import base64
import mimetypes
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree


def _docx_text(path: Path) -> str:
    pandoc = shutil.which("pandoc")
    if pandoc:
        result = subprocess.run([pandoc, "-t", "plain", str(path)], capture_output=True, text=True, check=False)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    with zipfile.ZipFile(path) as archive:
        raw = archive.read("word/document.xml")
    root = ElementTree.fromstring(raw)
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs = []
    for paragraph in root.findall(".//w:p", ns):
        text = "".join(node.text or "" for node in paragraph.findall(".//w:t", ns))
        if text.strip():
            paragraphs.append(text.strip())
    return "\n".join(paragraphs)


def _pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        text = "\n".join((page.extract_text() or "") for page in reader.pages).strip()
        if text:
            return text
    except ImportError:
        pass
    except Exception as exc:
        raise RuntimeError(f"PDF 文本提取失败：{exc}") from exc
    try:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            text = "\n".join((page.extract_text() or "") for page in pdf.pages).strip()
        if text:
            return text
    except ImportError:
        pass
    except Exception as exc:
        raise RuntimeError(f"PDF 文本提取失败：{exc}") from exc
    try:
        import fitz
        import pytesseract
        from PIL import Image
        doc = fitz.open(str(path))
        pages = []
        for page in doc:
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            text = pytesseract.image_to_string(image, lang="chi_sim+eng")
            if text.strip():
                pages.append(text.strip())
        if pages:
            return "\n".join(pages)
    except ImportError:
        pass
    except Exception as exc:
        raise RuntimeError(f"扫描 PDF OCR 失败：{exc}") from exc
    raise RuntimeError("PDF 没有可提取文本；可能是扫描件且当前环境没有可用 OCR，请提供可复制文本的 PDF 或 TXT")


def _image_text(path: Path) -> str:
    try:
        import pytesseract
        from PIL import Image
        text = pytesseract.image_to_string(Image.open(path), lang="chi_sim+eng")
        if text.strip():
            return text.strip()
    except ImportError:
        pass
    except Exception as exc:
        raise RuntimeError(f"图片 OCR 失败：{exc}") from exc
    raise RuntimeError("图片没有可用 OCR 依赖，请提供 PDF、DOCX、TXT 或安装 OCR 后重试")


def extract_file(path: str | Path) -> str:
    path = Path(path)
    if not path.exists():
        raise RuntimeError(f"文件不存在：{path}")
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".text"}:
        text = path.read_text(encoding="utf-8", errors="replace")
    elif suffix == ".docx":
        text = _docx_text(path)
    elif suffix == ".pdf":
        text = _pdf_text(path)
    elif suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}:
        text = _image_text(path)
    else:
        raise RuntimeError(f"不支持的简历格式：{suffix}")
    text = text.replace("\x00", "").strip()
    if not text:
        raise RuntimeError("没有提取到简历文本，不能继续分析")
    return text


def photo_data_uri(path: str | Path) -> str:
    path = Path(path)
    if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        raise RuntimeError("证件照仅支持 PNG/JPG/JPEG/WEBP/GIF")
    raw = path.read_bytes()
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def photo_from_pdf(path: str | Path) -> bytes:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("从 PDF 提取证件照需要 PyMuPDF；请直接提供照片文件") from exc
    doc = fitz.open(str(path))
    if not doc.page_count:
        raise RuntimeError("PDF 没有页面")
    images = doc[0].get_images(full=True)
    if not images:
        raise RuntimeError("PDF 第一页没有内嵌图片，请直接提供照片文件")
    best = None
    for item in images:
        pix = fitz.Pixmap(doc, item[0])
        if pix.colorspace and pix.colorspace.n > 3:
            pix = fitz.Pixmap(fitz.csRGB, pix)
        area = pix.width * pix.height
        if best is None or area > best[0]:
            best = (area, pix)
    return best[1].tobytes("png")


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("extract"); p.add_argument("file"); p.set_defaults(func=lambda a: print(extract_file(a.file)))
    p = sub.add_parser("photo"); p.add_argument("file"); p.add_argument("--output"); p.set_defaults(func=lambda a: _photo_cmd(a))
    args = ap.parse_args(argv)
    try:
        args.func(args)
    except RuntimeError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    return 0


def _photo_cmd(args):
    path = Path(args.file)
    if path.suffix.lower() == ".pdf":
        raw = photo_from_pdf(path)
        uri = "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
    else:
        uri = photo_data_uri(path)
    if args.output:
        Path(args.output).write_text(uri, encoding="utf-8")
    else:
        print(uri)


if __name__ == "__main__":
    raise SystemExit(main())
