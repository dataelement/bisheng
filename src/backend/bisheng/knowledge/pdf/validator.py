"""所有统一 PDF 候选共用的有效性与摘要校验。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import fitz


class PdfValidationError(ValueError):
    """候选对象不能作为统一 PDF。"""


@dataclass(frozen=True)
class PdfValidationResult:
    page_count: int
    artifact_size: int
    artifact_sha256: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_pdf(path: str | Path) -> PdfValidationResult:
    pdf_path = Path(path)
    try:
        artifact_size = pdf_path.stat().st_size
    except OSError as exc:
        raise PdfValidationError("PDF candidate is unavailable") from exc
    if artifact_size <= 0:
        raise PdfValidationError("PDF candidate is empty")

    try:
        with fitz.open(pdf_path) as document:
            if document.needs_pass or document.is_encrypted:
                raise PdfValidationError("Encrypted PDF is not supported")
            page_count = document.page_count
            if page_count <= 0:
                raise PdfValidationError("PDF has no pages")
            for page_number in range(page_count):
                _ = document.load_page(page_number).rect
    except PdfValidationError:
        raise
    except Exception as exc:
        raise PdfValidationError("PDF structure validation failed") from exc

    return PdfValidationResult(
        page_count=page_count,
        artifact_size=artifact_size,
        artifact_sha256=_sha256(pdf_path),
    )
