#!/usr/bin/env python3
"""Render a .docx to per-page PNGs so the layout can be eyeballed.

    python skills/bisheng-docx/scripts/render_docx.py output/x.docx [--dpi 110]

The official skill does this with ``soffice`` + ``pdftoppm``. Poppler is not in
the BiSheng image, so the PDF is rasterised with PyMuPDF instead — same result,
one fewer missing binary, and it keeps the ``page-01.png`` zero-padded naming
the rest of the workflow expects.

Optional step: it only helps when the model can actually read images back. When
LibreOffice is absent, or has no Writer component, the script says so plainly
and the structural check in ``inspect_docx.py`` remains the source of truth.

Always exits 0 — the executor discards stdout on a non-zero exit.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
import uuid


def find_soffice() -> str | None:
    return shutil.which("soffice") or shutil.which("libreoffice")


def to_pdf(src: str, outdir: str, timeout: int) -> str | None:
    soffice = find_soffice()
    if not soffice:
        print("[跳过] 环境里没有 LibreOffice（soffice），无法渲染预览。")
        print("       这不影响 .docx 的生成与交付 —— 以 inspect_docx.py 的体检结果为准。")
        return None

    os.makedirs(outdir, exist_ok=True)
    # A private profile per run: a fixed profile path is what makes concurrent
    # conversions in a multi-task worker corrupt each other.
    profile = os.path.join(tempfile.gettempdir(), f"lo_profile_{uuid.uuid4().hex}")
    cmd = [
        soffice,
        "--headless",
        "--norestore",
        "--invisible",
        "-env:SingleAppInstance=false",
        f"-env:UserInstallation=file://{profile}",
        "--convert-to",
        "pdf",
        "--outdir",
        outdir,
        os.path.abspath(src),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"[跳过] LibreOffice 转换超时（{timeout}s）。")
        return None

    pdf = os.path.join(outdir, os.path.splitext(os.path.basename(src))[0] + ".pdf")
    if not os.path.exists(pdf):
        message = ((proc.stdout or "") + (proc.stderr or "")).strip()
        print(f"[跳过] LibreOffice 没能转出 PDF（退出码 {proc.returncode}）：{message[:200]}")
        if "source file could not be loaded" in message.lower():
            print("       这台机器的 LibreOffice 很可能没装 Writer 组件，请让运维补装 libreoffice-writer。")
        elif proc.returncode == 137:
            print("       退出码 137 = 被 OOM killer 杀掉，是内存配额太小，不是 LibreOffice 坏了。")
        return None
    return pdf


def rasterise(pdf: str, outdir: str, dpi: int) -> list[str]:
    try:
        import fitz
    except ImportError:
        print("[跳过] PyMuPDF(fitz) 不可用，无法把 PDF 转成图片。")
        return []

    doc = fitz.open(pdf)
    pad = max(2, len(str(doc.page_count)))
    written = []
    for index, page in enumerate(doc, start=1):
        pixmap = page.get_pixmap(dpi=dpi)
        path = os.path.join(outdir, f"page-{index:0{pad}d}.png")
        pixmap.save(path)
        written.append(path)
    doc.close()
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="把 .docx 渲染成逐页 PNG")
    parser.add_argument("path")
    parser.add_argument("--dpi", type=int, default=110)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--outdir", default=None, help="默认 scratch/preview/<文件名>/")
    args = parser.parse_args()

    if not os.path.exists(args.path):
        print(f"[FATAL] 文件不存在: {args.path}")
        print("提示：用相对路径 `output/x.docx`，不要写 `/output/x.docx`。")
        return

    stem = os.path.splitext(os.path.basename(args.path))[0]
    outdir = args.outdir or os.path.join("scratch", "preview", stem)

    try:
        os.makedirs(outdir, exist_ok=True)
        pdf = to_pdf(args.path, outdir, args.timeout)
        if not pdf:
            return
        pages = rasterise(pdf, outdir, args.dpi)
        if not pages:
            return
        print(f"已渲染 {len(pages)} 页到 {outdir}/")
        for path in pages:
            print(f"  {path}")
        print()
        print("用 read_file 逐张查看这些 PNG。注意：服务端只有文泉驿正黑一种中文字体，")
        print("和用户 Word 里的实际字体宽度不同 —— 预览里的行长松紧只作参考，")
        print("不要为了预览效果反复微调字号，以 inspect_docx.py 的体检结果为准。")
    except Exception:
        print("[FATAL] 渲染过程本身出错：")
        traceback.print_exc(file=sys.stdout)


if __name__ == "__main__":
    main()
    sys.exit(0)
