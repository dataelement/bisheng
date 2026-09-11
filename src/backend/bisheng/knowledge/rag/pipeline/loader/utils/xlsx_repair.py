"""Make an .xlsx that openpyxl refuses loadable, without touching its data.

openpyxl parses ``xl/styles.xml`` through typed descriptors, and a handful of
constructs Excel and WPS write happily are rejected there outright — the whole
workbook then fails to open even though every cell in it is fine.

The one seen in the field: a bare ``<fill/>`` with no ``patternFill`` or
``gradientFill`` child. ``Fill`` is an abstract type that dispatches on that
child, so an empty element yields nothing and openpyxl raises
``TypeError: expected <class 'openpyxl.styles.fills.Fill'>`` before it has read a
single sheet. A 28 MB customer workbook with 18 populated sheets was unreadable
for exactly three such elements.

The repair rewrites those elements as an explicit "no fill" and copies every
other zip entry byte-for-byte, so cell values, formulas and sheet structure are
untouched — only a style that meant nothing to begin with is spelled out. It is
deliberately narrow: repairing anything openpyxl merely dislikes risks turning a
readable workbook into a subtly wrong one, and a failure that stays a failure is
better than that.
"""

from __future__ import annotations

import contextlib
import os
import re
import zipfile

from loguru import logger

STYLES_PART = "xl/styles.xml"

# ``<fill/>`` / ``<fill></fill>``, with or without a namespace prefix. The prefix
# is captured so the replacement keeps whatever the writer used.
_EMPTY_FILL_RE = re.compile(r"<(?:(?P<ns>[\w.-]+):)?fill\s*(?:/>|>\s*</(?:[\w.-]+:)?fill>)")


def _fill_replacement(match: re.Match) -> str:
    prefix = f"{match.group('ns')}:" if match.group("ns") else ""
    return f'<{prefix}fill><{prefix}patternFill patternType="none"/></{prefix}fill>'


def repair_xlsx_styles(src_path: str, dst_dir: str | None = None) -> str | None:
    """Write a repaired copy of ``src_path``; ``None`` when there is nothing to repair.

    Args:
        src_path: the .xlsx that failed to load.
        dst_dir: where to put the copy. Defaults to the source's own directory.

    Returns:
        Path of the repaired copy, or ``None`` when the workbook carries no
        styles part, none of the known-bad constructs, or cannot be read as a
        zip at all (a genuinely corrupt file is not this function's problem).
    """
    try:
        with zipfile.ZipFile(src_path) as archive:
            if STYLES_PART not in archive.namelist():
                return None
            styles = archive.read(STYLES_PART).decode("utf-8", errors="replace")
    except (zipfile.BadZipFile, OSError, KeyError):
        # Not a readable zip / unreadable member: nothing to repair here, and the
        # caller's original error already describes the real problem.
        return None

    repaired_styles, replaced = _EMPTY_FILL_RE.subn(_fill_replacement, styles)
    if not replaced:
        return None

    base, ext = os.path.splitext(os.path.basename(src_path))
    target_dir = dst_dir or os.path.dirname(src_path) or "."
    dst_path = os.path.join(target_dir, f"{base}.styles-repaired{ext or '.xlsx'}")
    try:
        with zipfile.ZipFile(src_path) as src, zipfile.ZipFile(dst_path, "w", zipfile.ZIP_DEFLATED) as dst:
            for item in src.infolist():
                # Every other part is copied verbatim: this is a style fix, not a
                # rewrite of the workbook.
                payload = repaired_styles.encode("utf-8") if item.filename == STYLES_PART else src.read(item.filename)
                dst.writestr(item, payload)
    except Exception:
        logger.opt(exception=True).warning("xlsx style repair failed to write {}", dst_path)
        # A half-written copy would fail to open and mask the real cause.
        if os.path.exists(dst_path):
            with contextlib.suppress(OSError):
                os.remove(dst_path)
        return None

    logger.info("xlsx style repair: rewrote {} empty <fill> element(s) in {}", replaced, os.path.basename(src_path))
    return dst_path
