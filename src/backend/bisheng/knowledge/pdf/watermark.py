from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import fitz

from bisheng.knowledge.pdf.validator import PdfValidationError, validate_pdf


class PdfWatermarkError(ValueError):
    """PDF 水印无法安全生成。"""


@dataclass(frozen=True)
class PdfWatermarkSpec:
    lines: tuple[str, str]
    rotation: float = 35.0
    opacity: float = 0.31
    font_size: float = 12.0
    horizontal_gap: float = 180.0
    vertical_gap: float = 135.0
    color: tuple[float, float, float] = (0.45, 0.45, 0.45)

    def __post_init__(self) -> None:
        normalized = tuple(str(line).strip() for line in self.lines)
        if len(normalized) != 2 or any(not line for line in normalized):
            raise PdfWatermarkError("watermark requires two non-empty lines")
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


@dataclass(frozen=True)
class _WatermarkLayout:
    font_size: float
    line_height: float
    text_width: float
    block_height: float
    rotated_width: float
    rotated_height: float
    horizontal_step: float
    vertical_step: float


_CJK_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/opentype/noto-office/NotoSansCJKsc-Regular.otf",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/Library/Fonts/NotoSansCJKsc-Regular.otf",
    str(Path(__file__).resolve().parents[3] / "docker/fonts/NotoSansCJKsc-Regular.otf"),
)


def _resolve_cjk_font(candidates: Sequence[str] = _CJK_FONT_CANDIDATES) -> _FontSelection:
    for candidate in candidates:
        if Path(candidate).is_file():
            return _FontSelection(font_name="portal-cjk", font_file=candidate)
    raise PdfWatermarkError("CJK watermark font is unavailable")


_HORIZONTAL_CLEARANCE = 36.0
_VERTICAL_CLEARANCE = 27.0
_MIN_HORIZONTAL_STEP = 180.0
_MIN_VERTICAL_STEP = 135.0
# 文档页按 A4 竖向宽度排版；图片转 PDF 页常按像素放大，需按此比例放大字号。
_A4_PORTRAIT_WIDTH = 595.0


def _calculate_watermark_layout(
    page_rect: fitz.Rect,
    spec: PdfWatermarkSpec,
    font: _FontSelection,
    *,
    image_dominated: bool = False,
) -> _WatermarkLayout:
    """计算平铺水印几何。

    图片主导页（整页照片）页面远大于 A4 时，若仍用 12pt，适应宽度预览只有几像素，
    看起来像「下载没有水印」。按页宽相对 A4 放大，使屏幕观感接近文档页。
    """
    page_size = min(float(page_rect.width), float(page_rect.height))
    if image_dominated:
        font_size = spec.font_size * max(1.0, float(page_rect.width) / _A4_PORTRAIT_WIDTH)
    else:
        font_size = min(spec.font_size, max(8.0, page_size / 40.0))
    line_height = font_size * 1.25
    block_height = line_height * len(spec.lines)
    try:
        measurement_font = fitz.Font(fontfile=font.font_file, fontname=font.font_name)
        text_width = max(measurement_font.text_length(line, fontsize=font_size) for line in spec.lines)
    except Exception as exc:
        raise PdfWatermarkError("CJK watermark font cannot measure text") from exc

    angle = math.radians(abs(spec.rotation))
    rotated_width = text_width * math.cos(angle) + block_height * math.sin(angle)
    rotated_height = text_width * math.sin(angle) + block_height * math.cos(angle)
    return _WatermarkLayout(
        font_size=font_size,
        line_height=line_height,
        text_width=text_width,
        block_height=block_height,
        rotated_width=rotated_width,
        rotated_height=rotated_height,
        horizontal_step=max(
            _MIN_HORIZONTAL_STEP,
            spec.horizontal_gap,
            rotated_width + _HORIZONTAL_CLEARANCE,
        ),
        vertical_step=max(
            _MIN_VERTICAL_STEP,
            spec.vertical_gap,
            rotated_height + _VERTICAL_CLEARANCE,
        ),
    )


def _tile_positions(page_rect: fitz.Rect, layout: _WatermarkLayout) -> list[fitz.Point]:
    width = max(float(page_rect.width), 1.0)
    height = max(float(page_rect.height), 1.0)
    left_anchor = min(20.0, width * 0.05)
    top_anchor = min(36.0, height * 0.05)
    positions: list[fitz.Point] = []
    row_index = 0
    y = top_anchor
    while y < height:
        x = left_anchor + (layout.horizontal_step / 2.0 if row_index % 2 else 0.0)
        if x >= width:
            x = left_anchor
        while x < width:
            positions.append(fitz.Point(x, y))
            x += layout.horizontal_step
        row_index += 1
        y += layout.vertical_step
    if not positions:
        positions.append(fitz.Point(left_anchor, top_anchor))
    return positions


# 图片页（照片/扫件）上单层浅灰半透明字对比度不足，需白底+深色双描提高可见性。
_IMAGE_PAGE_COVERAGE_RATIO = 0.45
_IMAGE_PAGE_HALO_COLOR = (1.0, 1.0, 1.0)
_IMAGE_PAGE_HALO_OPACITY = 0.55
_IMAGE_PAGE_FOREGROUND_COLOR = (0.15, 0.15, 0.15)
_IMAGE_PAGE_FOREGROUND_OPACITY = 0.5


def _page_image_coverage_ratio(page: fitz.Page) -> float:
    """估算页面被位图覆盖的面积占比（用于识别图片主导页）。"""
    page_area = abs(float(page.rect.width) * float(page.rect.height))
    if page_area <= 0:
        return 0.0
    covered = 0.0
    for image in page.get_images(full=True):
        xref = int(image[0])
        try:
            rects = page.get_image_rects(xref)
        except Exception:
            rects = []
        for rect in rects:
            covered += abs(float(rect.width) * float(rect.height))
    return min(covered / page_area, 1.0)


def _page_is_image_dominated(page: fitz.Page) -> bool:
    """
    判断是否为图片主导页（如 Pillow 转 PDF 的整页图）。

    文档页保持原有单层浅灰水印；图片页改用描边增强，避免「能下但看不见水印」。
    """
    if _page_image_coverage_ratio(page) >= _IMAGE_PAGE_COVERAGE_RATIO:
        return True
    # 扫件/照片页可能带白边，位图占比不足 45% 但仍几乎无正文，须走图片增强。
    return bool(page.get_images(full=True)) and not page.get_text().strip()


def _insert_watermark_line(
    page: fitz.Page,
    *,
    point: fitz.Point,
    line: str,
    font: _FontSelection,
    font_size: float,
    color: tuple[float, float, float],
    opacity: float,
    rotation_matrix: fitz.Matrix,
) -> None:
    kwargs = {
        "fontsize": font_size,
        "fontname": font.font_name,
        "color": color,
        "fill_opacity": opacity,
        "morph": (point, rotation_matrix),
        "overlay": True,
    }
    if font.font_file:
        kwargs["fontfile"] = font.font_file
    page.insert_text(point, line, **kwargs)


def _apply_page_watermark(
    page: fitz.Page,
    spec: PdfWatermarkSpec,
    font: _FontSelection,
) -> None:
    image_dominated = _page_is_image_dominated(page)
    layout = _calculate_watermark_layout(
        page.rect,
        spec,
        font,
        image_dominated=image_dominated,
    )
    rotation_matrix = fitz.Matrix(spec.rotation)
    for anchor in _tile_positions(page.rect, layout):
        for line_index, line in enumerate(spec.lines):
            point = fitz.Point(anchor.x, anchor.y + line_index * layout.line_height)
            if image_dominated:
                # 先铺浅色底，再叠深色字，保证深色/纹理照片上仍可读。
                _insert_watermark_line(
                    page,
                    point=point,
                    line=line,
                    font=font,
                    font_size=layout.font_size,
                    color=_IMAGE_PAGE_HALO_COLOR,
                    opacity=_IMAGE_PAGE_HALO_OPACITY,
                    rotation_matrix=rotation_matrix,
                )
                _insert_watermark_line(
                    page,
                    point=point,
                    line=line,
                    font=font,
                    font_size=layout.font_size,
                    color=_IMAGE_PAGE_FOREGROUND_COLOR,
                    opacity=_IMAGE_PAGE_FOREGROUND_OPACITY,
                    rotation_matrix=rotation_matrix,
                )
                continue
            _insert_watermark_line(
                page,
                point=point,
                line=line,
                font=font,
                font_size=layout.font_size,
                color=spec.color,
                opacity=spec.opacity,
                rotation_matrix=rotation_matrix,
            )


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
