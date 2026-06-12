"""OFD -> PDF conversion via easyofd (in-process).

easyofd's ``FileRead`` writes scratch files (``{pid}_{uuid}.ofd`` + a same-stem
unzip dir) to ``os.getcwd()`` and offers no directory parameter. Rather than
``chdir`` (process-global, unsafe in the threaded worker), we patch
``FileRead.__init__`` once to honor a thread-local target dir, and point it at
the per-call ``output_dir`` (the pipeline's TemporaryDirectory). The scratch
files land there and are reclaimed with it — which also covers the corrupt-OFD
case where easyofd skips its own cleanup. Thread-local state keeps concurrent
conversions isolated.
"""

import contextlib
import io
import os
import shutil
import subprocess
import threading

from loguru import logger

from bisheng.common.errcode.knowledge import OfdConvertError

# Per-thread directory easyofd's FileRead should write its scratch files into.
_ofd_workdir = threading.local()
_patch_lock = threading.Lock()
_patched = False

# easyofd's draw_chars hard-codes ``setFont("宋体")`` and its font_map also draws
# 楷体/黑体; we register these exact names so those calls resolve to a real glyph
# source instead of falling back to Helvetica (which has no CJK glyphs → blank).
_HARDCODED_CJK_FONT_NAMES = ("宋体", "楷体", "黑体")

# Probed in order, first existing wins. Covers our deploy image (fonts-wqy-zenhei)
# and common dev hosts (Debian/Ubuntu Noto CJK, macOS). Not exhaustive — fc-match
# is the cross-distro fallback in _detect_cjk_font.
_CJK_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",  # deploy image (fonts-wqy-zenhei)
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",  # macOS dev
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
)

# Warn at most once per process when the host has no CJK font; repeated conversions
# shouldn't spam the log, but the misconfiguration must not be silent.
_warned_missing_font = False


def _detect_cjk_font() -> str | None:
    """Return a path to a CJK-capable font file on this host, or None if none.

    Tries well-known paths first, then ``fc-match`` (fontconfig) so we pick up
    whatever CJK font a distro actually shipped without hard-coding every layout.
    """
    for path in _CJK_FONT_CANDIDATES:
        if os.path.isfile(path):
            return path

    fc_match = shutil.which("fc-match")
    if fc_match:
        try:
            # -f %{file} prints the resolved font file path; :lang=zh asks for one
            # that can render Chinese.
            out = subprocess.run(
                [fc_match, "-f", "%{file}", ":lang=zh"],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            ).stdout.strip()
            if out and os.path.isfile(out):
                return out
        except (subprocess.SubprocessError, OSError):
            logger.warning("fc-match CJK font probe failed", exc_info=True)

    return None


def _ensure_cjk_fonts_registered() -> None:
    """Register easyofd's hard-coded CJK font names against a host CJK font.

    easyofd draws every glyph with ``setFont("宋体")`` but only registers that
    name if a file literally named ``simsun.ttc`` is on reportlab's search path —
    which our deploy image lacks, so text renders blank. reportlab's font registry
    is process-global and shared with easyofd, so registering the names here makes
    its draw calls resolve, with no change to the library. Idempotent.
    """
    global _warned_missing_font

    font_path = _detect_cjk_font()
    if not font_path:
        if not _warned_missing_font:
            logger.warning(
                "no CJK font found on host; OFD previews will render without "
                "Chinese text. Install a CJK font (e.g. fonts-wqy-zenhei) in the image."
            )
            _warned_missing_font = True
        return

    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    registered = pdfmetrics.getRegisteredFontNames()
    for name in _HARDCODED_CJK_FONT_NAMES:
        if name in registered:
            continue
        try:
            # subfontIndex=0 is needed for .ttc collections (wqy-zenhei, Songti)
            # and harmless for plain .ttf.
            pdfmetrics.registerFont(TTFont(name, font_path, subfontIndex=0))
        except Exception:
            logger.warning("failed to register CJK font {!r} from {}", name, font_path, exc_info=True)


def _ensure_easyofd_patched() -> None:
    """Patch easyofd's FileRead once so it writes scratch files into the
    thread-local ``_ofd_workdir.path`` instead of ``os.getcwd()``."""
    global _patched
    if _patched:
        return
    with _patch_lock:
        if _patched:
            return
        from easyofd.parser_ofd import file_deal

        original_init = file_deal.FileRead.__init__

        def _init(self, ofdb64, *args, **kwargs):
            original_init(self, ofdb64, *args, **kwargs)
            workdir = getattr(_ofd_workdir, "path", None)
            if workdir:
                # FileRead.unzip_path is derived from zip_path later, so redirecting
                # zip_path moves both the .ofd scratch and the unzip dir.
                self.zip_path = os.path.join(workdir, self.name)

        file_deal.FileRead.__init__ = _init
        _patched = True


def convert_ofd_to_pdf(input_path: str, output_dir: str) -> str:
    """Convert an OFD file to PDF and return the generated PDF path.

    Raises:
        OfdConvertError: the OFD is corrupt / invalid, or conversion yields no PDF.
    """
    # Lazy import: easyofd registers fonts at import time (verbose); keep it off
    # the hot import path.
    from easyofd import OFD

    _ensure_easyofd_patched()
    _ensure_cjk_fonts_registered()

    input_path = os.path.abspath(input_path)
    output_dir = os.path.abspath(output_dir)
    base_name = os.path.splitext(os.path.basename(input_path))[0]
    pdf_path = os.path.join(output_dir, f"{base_name}.pdf")

    _ofd_workdir.path = output_dir
    try:
        ofd = OFD()
        # easyofd prints verbose debug to stdout; silence it.
        with contextlib.redirect_stdout(io.StringIO()):
            ofd.read(input_path, fmt="path")
            pdf_bytes = ofd.to_pdf()
    except Exception as exc:
        # Third-party lib raises arbitrary errors on malformed OFD; translate to a
        # domain error so the frontend can surface code 10917, and log the traceback.
        logger.exception("OFD -> PDF conversion failed: {}", input_path)
        raise OfdConvertError() from exc
    finally:
        _ofd_workdir.path = None

    if not pdf_bytes:
        logger.error("OFD -> PDF conversion produced empty output: {}", input_path)
        raise OfdConvertError()

    with open(pdf_path, "wb") as f:
        f.write(pdf_bytes)
    return pdf_path
