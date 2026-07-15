import math
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Literal

import fitz
from loguru import logger

ImageSourceType = Literal["embedded", "rendered"]

_SAFE_IMAGE_EXTENSIONS = {"bmp", "gif", "jpeg", "jpg", "png", "webp"}
_CANDIDATE_COVERAGE_THRESHOLD = 0.90
_TARGET_COVERAGE_THRESHOLD = 0.70


@dataclass(frozen=True)
class ExtractedImage:
    filename: str
    source_type: ImageSourceType
    width: int
    height: int
    effective_dpi: float | None
    matched_xref: int | None
    fallback_reason: str | None


class PdfImageExtractor:
    """Extract an ETL image bbox without changing its PDF-point coordinates."""

    def __init__(self, strategy: str, fallback_dpi: int, max_pixels: int):
        if strategy not in {"render_only", "original_first"}:
            raise ValueError(f"Unsupported PDF image extraction strategy: {strategy}")
        if fallback_dpi <= 0:
            raise ValueError("fallback_dpi must be positive")
        if max_pixels <= 0:
            raise ValueError("max_pixels must be positive")
        self.strategy = strategy
        self.fallback_dpi = fallback_dpi
        self.max_pixels = max_pixels

    def extract(
        self,
        document: fitz.Document,
        page_number: int,
        bbox: Sequence[float],
        element_id: str,
        output_dir: str | Path,
    ) -> ExtractedImage:
        started_at = time.perf_counter()
        page, clip = self._validate_region(document, page_number, bbox)
        fallback_reason = "strategy_render_only" if self.strategy == "render_only" else None

        result = None
        if self.strategy == "original_first":
            matched_xref, fallback_reason = self._find_embedded_image(page, clip)
            if matched_xref is not None:
                result, fallback_reason = self._extract_embedded_image(
                    document=document,
                    xref=matched_xref,
                    element_id=element_id,
                    output_dir=output_dir,
                )

        if result is None:
            result = self._render_region(
                page=page,
                clip=clip,
                element_id=element_id,
                output_dir=output_dir,
                fallback_reason=fallback_reason,
            )

        logger.info(
            "act=etl4lm_extract_image page={} element_id={} source_type={} matched_xref={} "
            "width={} height={} effective_dpi={} fallback_reason={} duration_ms={:.2f}",
            page_number,
            self._safe_element_id(element_id),
            result.source_type,
            result.matched_xref,
            result.width,
            result.height,
            result.effective_dpi,
            result.fallback_reason,
            (time.perf_counter() - started_at) * 1000,
        )
        return result

    @staticmethod
    def _validate_region(
        document: fitz.Document,
        page_number: int,
        bbox: Sequence[float],
    ) -> tuple[fitz.Page, fitz.Rect]:
        if page_number < 0 or page_number >= document.page_count:
            raise ValueError(f"PDF page number is out of range: {page_number}")
        if len(bbox) != 4:
            raise ValueError("PDF image bbox must contain four coordinates")
        try:
            coordinates = [float(value) for value in bbox]
        except (TypeError, ValueError) as exc:
            raise ValueError("PDF image bbox contains a non-numeric coordinate") from exc
        if not all(math.isfinite(value) for value in coordinates):
            raise ValueError("PDF image bbox contains a non-finite coordinate")

        target = fitz.Rect(coordinates)
        if target.is_empty or target.is_infinite:
            raise ValueError(f"PDF image bbox is empty or invalid: {coordinates}")
        page = document[page_number]
        clip = target & page.rect
        if clip.is_empty or clip.is_infinite:
            raise ValueError(f"PDF image bbox does not intersect page {page_number}: {coordinates}")
        return page, clip

    def _find_embedded_image(self, page: fitz.Page, target: fitz.Rect) -> tuple[int | None, str]:
        candidates: list[int] = []
        for image_info in page.get_image_info(xrefs=True):
            xref = int(image_info.get("xref") or 0)
            if xref <= 0:
                continue
            if not self._is_axis_aligned_transform(image_info.get("transform")):
                continue
            candidate = fitz.Rect(image_info.get("bbox"))
            if candidate.is_empty or candidate.is_infinite:
                continue
            intersection = candidate & target
            if intersection.is_empty:
                continue
            candidate_coverage = intersection.get_area() / candidate.get_area()
            target_coverage = intersection.get_area() / target.get_area()
            center = (candidate.tl + candidate.br) / 2
            if (
                candidate_coverage < _CANDIDATE_COVERAGE_THRESHOLD
                or target_coverage < _TARGET_COVERAGE_THRESHOLD
                or not target.contains(center)
            ):
                continue
            width = int(image_info.get("width") or 0)
            height = int(image_info.get("height") or 0)
            if width <= 0 or height <= 0 or width * height > self.max_pixels:
                continue
            candidates.append(xref)

        unique_candidates = list(dict.fromkeys(candidates))
        if len(unique_candidates) != 1:
            return None, "no_high_confidence_candidate"
        return unique_candidates[0], None

    @staticmethod
    def _is_axis_aligned_transform(transform: Sequence[float] | None) -> bool:
        if transform is None or len(transform) != 6:
            return False
        try:
            scale_x, skew_y, skew_x, scale_y, _, _ = [float(value) for value in transform]
        except (TypeError, ValueError):
            return False
        tolerance = 1e-6
        return scale_x > 0 and scale_y > 0 and abs(skew_x) <= tolerance and abs(skew_y) <= tolerance

    def _extract_embedded_image(
        self,
        document: fitz.Document,
        xref: int,
        element_id: str,
        output_dir: str | Path,
    ) -> tuple[ExtractedImage | None, str | None]:
        try:
            if self._has_soft_mask(document, xref):
                return None, "embedded_image_has_soft_mask"
            extracted = document.extract_image(xref)
            extension = str(extracted.get("ext") or "").lower()
            image_bytes = extracted.get("image")
            width = int(extracted.get("width") or 0)
            height = int(extracted.get("height") or 0)
            if extension not in _SAFE_IMAGE_EXTENSIONS:
                return None, "unsupported_embedded_image_format"
            if not image_bytes or width <= 0 or height <= 0:
                return None, "invalid_embedded_image"
            if width * height > self.max_pixels:
                return None, "embedded_image_exceeds_pixel_limit"

            output_path = self._output_path(output_dir, element_id, extension)
            output_path.write_bytes(image_bytes)
            return (
                ExtractedImage(
                    filename=output_path.name,
                    source_type="embedded",
                    width=width,
                    height=height,
                    effective_dpi=None,
                    matched_xref=xref,
                    fallback_reason=None,
                ),
                None,
            )
        except Exception:
            logger.opt(exception=True).warning(
                "act=etl4lm_extract_embedded_image_failed xref={} element_id={} fallback_reason=extract_error",
                xref,
                self._safe_element_id(element_id),
            )
            return None, "embedded_image_extract_error"

    @staticmethod
    def _has_soft_mask(document: fitz.Document, xref: int) -> bool:
        key_type, value = document.xref_get_key(xref, "SMask")
        return key_type == "xref" and value not in {"0 0 R", "null"}

    def _render_region(
        self,
        page: fitz.Page,
        clip: fitz.Rect,
        element_id: str,
        output_dir: str | Path,
        fallback_reason: str | None,
    ) -> ExtractedImage:
        requested_scale = self.fallback_dpi / 72
        pixel_limited_scale = math.sqrt(self.max_pixels / clip.get_area())
        effective_scale = min(requested_scale, pixel_limited_scale)
        pixmap = page.get_pixmap(
            matrix=fitz.Matrix(effective_scale, effective_scale),
            clip=clip,
            alpha=False,
        )

        if pixmap.width * pixmap.height > self.max_pixels:
            correction = math.sqrt(self.max_pixels / (pixmap.width * pixmap.height)) * 0.999
            effective_scale *= correction
            pixmap = page.get_pixmap(
                matrix=fitz.Matrix(effective_scale, effective_scale),
                clip=clip,
                alpha=False,
            )

        output_path = self._output_path(output_dir, element_id, "png")
        output_path.write_bytes(pixmap.tobytes("png"))
        return ExtractedImage(
            filename=output_path.name,
            source_type="rendered",
            width=pixmap.width,
            height=pixmap.height,
            effective_dpi=effective_scale * 72,
            matched_xref=None,
            fallback_reason=fallback_reason,
        )

    @classmethod
    def _output_path(cls, output_dir: str | Path, element_id: str, extension: str) -> Path:
        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{cls._safe_element_id(element_id)}.{extension}"

    @staticmethod
    def _safe_element_id(element_id: str) -> str:
        raw_id = str(element_id)
        safe_id = re.sub(r"[^A-Za-z0-9._-]+", "_", raw_id).strip("._") or "image"
        if safe_id != raw_id:
            digest = sha256(raw_id.encode()).hexdigest()[:8]
            return f"{safe_id}-{digest}"
        return safe_id
