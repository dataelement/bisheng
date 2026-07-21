from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import fitz

from bisheng.knowledge.pdf.validator import PdfValidationError, validate_pdf


class PdfWatermarkError(ValueError):
    """PDF 水印无法安全生成。"""


@dataclass(frozen=True)
class PdfWatermarkSpec:
    lines: tuple[str, str, str]
    rotation: float = -35.0
    opacity: float = 0.16
    font_size: float = 12.0
    horizontal_gap: float = 180.0
    vertical_gap: float = 120.0
    color: tuple[float, float, float] = (0.45, 0.45, 0.45)

    def __post_init__(self) -> None:
        normalized = tuple(str(line).strip() for line in self.lines)
        if len(normalized) != 3 or any(not line for line in normalized):
            raise PdfWatermarkError("watermark requires three non-empty lines")
        if not 0 < self.opacity < 1:
            raise PdfWatermarkError("watermark opacity must be between zero and one")
        if self.font_size <= 0 or self.horizontal_gap <= 0 or self.vertical_gap <= 0:
            raise PdfWatermarkError("watermark dimensions must be positive")
        object.__setattr__(self, "lines", normalized)


@dataclass(frozen=True)
class PdfWatermarkResult:
    page_count: int
    artifact_size: int


@dataclass(frozen=True)
class _FontSelection:
    font_name: str
    font_file: str | None = None


_CJK_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/Library/Fonts/NotoSansCJKsc-Regular.otf",
)


def _resolve_cjk_font(candidates: Sequence[str] = _CJK_FONT_CANDIDATES) -> _FontSelection:
    for candidate in candidates:
        if Path(candidate).is_file():
            return _FontSelection(font_name="portal-cjk", font_file=candidate)
    try:
        fitz.Font(fontname="china-s")
    except Exception as exc:
        raise PdfWatermarkError("CJK watermark font is unavailable") from exc
    return _FontSelection(font_name="china-s")


def _tile_positions(page_rect: fitz.Rect, spec: PdfWatermarkSpec) -> list[fitz.Point]:
    width = max(float(page_rect.width), 1.0)
    height = max(float(page_rect.height), 1.0)
    x_step = min(spec.horizontal_gap, max(width / 2.0, 72.0))
    y_step = min(spec.vertical_gap, max(height / 2.0, 72.0))
    x_values: list[float] = []
    y_values: list[float] = []
    x = 20.0
    while x < width:
        x_values.append(x)
        x += x_step
    y = 36.0
    while y < height:
        y_values.append(y)
        y += y_step
    if len(x_values) < 2:
        x_values = [10.0, max(width / 2.0, 20.0)]
    if len(y_values) < 2:
        y_values = [24.0, max(height / 2.0, 48.0)]
    return [fitz.Point(x, y) for y in y_values for x in x_values]


def _apply_page_watermark(
    page: fitz.Page,
    spec: PdfWatermarkSpec,
    font: _FontSelection,
) -> None:
    page_size = min(float(page.rect.width), float(page.rect.height))
    font_size = min(spec.font_size, max(8.0, page_size / 50.0))
    line_height = font_size * 1.25
    rotation_matrix = fitz.Matrix(spec.rotation)
    for anchor in _tile_positions(page.rect, spec):
        for line_index, line in enumerate(spec.lines):
            point = fitz.Point(anchor.x, anchor.y + line_index * line_height)
            kwargs = {
                "fontsize": font_size,
                "fontname": font.font_name,
                "color": spec.color,
                "fill_opacity": spec.opacity,
                "morph": (point, rotation_matrix),
                "overlay": True,
            }
            if font.font_file:
                kwargs["fontfile"] = font.font_file
            page.insert_text(point, line, **kwargs)


def apply_pdf_watermark(
    input_path: str | Path,
    output_path: str | Path,
    spec: PdfWatermarkSpec,
) -> PdfWatermarkResult:
    source_path = Path(input_path).resolve()
    target_path = Path(output_path).resolve()
    if source_path == target_path:
        raise PdfWatermarkError("watermark output must use a new path")
    if not source_path.is_file():
        raise PdfWatermarkError("source PDF is invalid")

    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.unlink(missing_ok=True)
    document: fitz.Document | None = None
    try:
        try:
            document = fitz.open(source_path)
        except Exception as exc:
            raise PdfWatermarkError("source PDF is invalid") from exc
        if document.needs_pass or document.is_encrypted:
            raise PdfWatermarkError("encrypted PDF is not supported")
        if document.page_count <= 0:
            raise PdfWatermarkError("source PDF has no pages")

        font = _resolve_cjk_font()
        for page_number in range(document.page_count):
            _apply_page_watermark(document.load_page(page_number), spec, font)
        document.save(target_path, garbage=4, deflate=True)
    except PdfWatermarkError:
        target_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        target_path.unlink(missing_ok=True)
        raise PdfWatermarkError("PDF watermark generation failed") from exc
    finally:
        if document is not None:
            document.close()

    try:
        validation = validate_pdf(target_path)
    except PdfValidationError as exc:
        target_path.unlink(missing_ok=True)
        raise PdfWatermarkError("PDF watermark output is invalid") from exc
    return PdfWatermarkResult(
        page_count=validation.page_count,
        artifact_size=validation.artifact_size,
    )
