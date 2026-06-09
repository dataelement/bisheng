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
import threading

from loguru import logger

from bisheng.common.errcode.knowledge import OfdConvertError

# Per-thread directory easyofd's FileRead should write its scratch files into.
_ofd_workdir = threading.local()
_patch_lock = threading.Lock()
_patched = False


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
