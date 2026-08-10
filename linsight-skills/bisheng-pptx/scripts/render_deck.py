#!/usr/bin/env python
"""Render a .pptx to one PNG per slide, for visual QA.

Replaces the official skill's ``soffice.py`` + ``pdftoppm`` chain, neither of
which works here: ``pdftoppm`` is not installed, and a bare ``soffice`` call
fails with "source file could not be loaded" unless it gets its own throwaway
user profile and an absolute input path. The same invocation the repo already
uses in ``knowledge/rag/pipeline/loader/utils/libreoffice_converter.py`` is
reproduced below.

Rendering goes through PyMuPDF (``fitz``), which is a declared backend
dependency, instead of Poppler.

Usage:
    python skills/bisheng-pptx/scripts/render_deck.py output/deck.pptx
    python skills/bisheng-pptx/scripts/render_deck.py output/deck.pptx --pages 1-4 --width 1600

Prints the workspace-relative PNG paths; pass them to read_file to look at them.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

import fitz

DEFAULT_WIDTH_PX = 1280
SOFFICE_TIMEOUT_S = 300


def _find_soffice() -> str | None:
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _to_pdf(pptx_path: str, out_dir: str) -> str | None:
    """Convert with a private LibreOffice profile; returns the pdf path or None."""
    soffice = _find_soffice()
    if not soffice:
        print("找不到 soffice/libreoffice，无法渲染预览。跳过视觉 QA，以 inspect_deck.py 的体检为准。")
        return None

    abs_input = os.path.abspath(pptx_path)
    os.makedirs(out_dir, exist_ok=True)
    expected = os.path.join(out_dir, os.path.splitext(os.path.basename(abs_input))[0] + ".pdf")

    with tempfile.TemporaryDirectory() as profile:
        command = [
            soffice,
            "--headless",
            "-env:SingleAppInstance=false",
            f"-env:UserInstallation=file://{profile}",
            "--convert-to",
            "pdf",
            "--outdir",
            out_dir,
            abs_input,
        ]
        try:
            proc = subprocess.run(command, capture_output=True, text=True, timeout=SOFFICE_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            print(f"soffice 转换超时（>{SOFFICE_TIMEOUT_S}s）。跳过视觉 QA。")
            return None

    if not os.path.exists(expected):
        # soffice exits 0 even when it converted nothing, so trust the file, not rc.
        message = (proc.stdout + proc.stderr).strip()
        print(f"soffice 未产出 PDF（rc={proc.returncode}）。输出: {message[:400]}")
        if "could not be loaded" in message:
            print("多半是这套环境的 LibreOffice 没装 Impress 组件（只有 Writer），无法打开 .pptx。")
        print("跳过视觉 QA 即可，不影响 .pptx 交付；以 inspect_deck.py 的体检结果为准。")
        return None
    return expected


def _parse_pages(spec: str | None, total: int) -> list[int]:
    if not spec:
        return list(range(total))
    wanted: set[int] = set()
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            start, end = chunk.split("-", 1)
            wanted.update(range(int(start) - 1, int(end)))
        else:
            wanted.add(int(chunk) - 1)
    return sorted(p for p in wanted if 0 <= p < total)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render pptx slides to PNG for visual QA")
    parser.add_argument("pptx", help="路径，相对工作区根，例如 output/deck.pptx")
    parser.add_argument("--outdir", default=None, help="默认 scratch/preview/<文件名>/")
    parser.add_argument("--pages", default=None, help="页码，如 1-4 或 2,5,7（默认全部）")
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH_PX, help=f"输出宽度 px（默认 {DEFAULT_WIDTH_PX}）")
    args = parser.parse_args()

    if not os.path.exists(args.pptx):
        print(f"文件不存在: {args.pptx}（注意用相对路径，且代码执行器写的文件不出现在 ls 里）")
        return 0

    stem = os.path.splitext(os.path.basename(args.pptx))[0]
    out_dir = args.outdir or os.path.join("scratch", "preview", stem)
    os.makedirs(out_dir, exist_ok=True)

    # Stale frames from a previous run read as "my fix did not apply".
    for name in os.listdir(out_dir):
        if name.startswith("slide-") and name.endswith(".png"):
            os.remove(os.path.join(out_dir, name))

    # Always exit 0 even when rendering is impossible: a non-zero exit makes the
    # code interpreter return stderr and drop stdout, hiding the reason.
    pdf_path = _to_pdf(args.pptx, out_dir)
    if not pdf_path:
        return 0

    written = []
    with fitz.open(pdf_path) as doc:
        pages = _parse_pages(args.pages, doc.page_count)
        for index in pages:
            page = doc[index]
            zoom = args.width / page.rect.width if page.rect.width else 1.0
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
            target = os.path.join(out_dir, f"slide-{index + 1}.png")
            pix.save(target)
            written.append(target)

    print(f"已渲染 {len(written)} 页（源 PDF: {pdf_path}）:")
    for path in written:
        print(f"  {path}")
    print("\n用 read_file 逐张查看上面的路径。重点看：文字是否溢出/被截断、元素是否重叠、留白是否失衡。")
    print("注意：渲染用的中文字体是文泉驿正黑，与用户 PowerPoint 里的实际字体宽度不同 ——")
    print("      预览里的文字松紧只作参考，容器请留约 10% 余量，不要为了预览效果反复微调字号。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
