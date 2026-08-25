"""专家问答图片/附件：转 PDF 后打门户水印再下载。"""

from __future__ import annotations

import re
import tempfile
from datetime import datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote, urlparse
from zoneinfo import ZoneInfo

import fitz
from loguru import logger
from PIL import Image, UnidentifiedImageError

from bisheng.knowledge.pdf.watermark import PdfWatermarkError, PdfWatermarkSpec, apply_pdf_watermark
from bisheng.shougang_portal_config.domain.services.portal_config_service import (
    ShougangPortalConfigService,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
_PROXY_PREFIXES = (
    "tmp-dir/",
    "bisheng/",
    "skm-bisheng/",
    "workspace/bisheng/",
    "workspace/skm-bisheng/",
)
_UUID_OBJECT = re.compile(r"^[0-9a-fA-F-]{8,}\.[A-Za-z0-9]{1,8}$")
_IMAGE_TYPES = {
    ".bmp": "bmp",
    ".gif": "gif",
    ".jpeg": "jpeg",
    ".jpg": "jpeg",
    ".png": "png",
    ".webp": "webp",
}
_IMAGE_SUFFIXES = set(_IMAGE_TYPES)
# 问答附件视频：无法转 PDF 打水印，允许原文件直下（mp4/mov/webm）
_VIDEO_SUFFIXES = {".mp4", ".mov", ".webm"}
_VIDEO_MEDIA_TYPES = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
}


class QaWatermarkDownloadError(ValueError):
    """问答资源无法生成带水印 PDF。"""


def parse_qa_asset_location(source: str, *, default_bucket: str, tmp_bucket: str) -> tuple[str, str]:
    """从预签名或对象路径解析 MinIO bucket + object。只允许问答上传路径。"""
    raw = (source or "").strip()
    if not raw:
        raise QaWatermarkDownloadError("missing asset source")
    parsed = urlparse(raw)
    path = unquote(parsed.path or raw).lstrip("/")
    if not path or ".." in path.split("/"):
        raise QaWatermarkDownloadError("invalid asset source")

    bucket = default_bucket
    object_name = path
    for prefix in _PROXY_PREFIXES:
        if path.startswith(prefix):
            object_name = path[len(prefix) :]
            bucket = tmp_bucket if prefix.startswith("tmp-dir/") else default_bucket
            break

    if object_name.startswith("qa-expert/"):
        return default_bucket, object_name
    file_name = object_name.rsplit("/", 1)[-1]
    if _UUID_OBJECT.fullmatch(file_name) and "/" not in object_name:
        return bucket, object_name
    raise QaWatermarkDownloadError("asset source is not a QA upload")


def _sniff_video_suffix(data: bytes) -> str | None:
    """根据文件头识别 mp4/mov/webm，供展示名无后缀时仍能直下原视频。"""
    if len(data) >= 12 and data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand in {b"qt  ", b"moov", b"wide"}:
            return ".mov"
        return ".mp4"
    if len(data) >= 4 and data[:4] == b"\x1aE\xdf\xa3":
        return ".webm"
    return None


def resolve_qa_video_suffix(filename: str, data: bytes) -> str | None:
    """若附件为支持直下的视频格式则返回小写后缀，否则 None。"""
    suffix = Path(filename).suffix.lower()
    if suffix in _VIDEO_SUFFIXES:
        return suffix
    return _sniff_video_suffix(data)


def is_qa_video_asset(filename: str, data: bytes) -> bool:
    """判断问答上传附件是否应按原视频文件下载（不打水印）。"""
    return resolve_qa_video_suffix(filename, data) is not None


def resolve_conversion_filename(title: str, object_name: str) -> str:
    """标题无后缀时回退对象名，避免详情页「问题图片 1」丢失扩展名导致转 PDF 失败。"""
    titled = (title or "").strip()
    object_base = object_name.rsplit("/", 1)[-1] if object_name else ""
    if titled and Path(titled).suffix:
        return titled
    if object_base and Path(object_base).suffix:
        if titled:
            return f"{titled}{Path(object_base).suffix.lower()}"
        return object_base
    return titled or object_base or "qa-asset"


def _sniff_image_type(data: bytes) -> str | None:
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:6] in {b"GIF87a", b"GIF89a"}:
        return "gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:2] == b"BM":
        return "bmp"
    return None


def _image_bytes_to_pdf(data: bytes, image_type: str | None) -> bytes:
    """优先用 PyMuPDF；WEBP 等当前版本打不开时经 Pillow 转 PNG 再嵌入。"""
    if image_type and image_type != "webp":
        try:
            src = fitz.open(stream=data, filetype=image_type)
            try:
                return src.convert_to_pdf()
            finally:
                src.close()
        except Exception:
            logger.debug("fitz open image failed type={}, fallback to Pillow", image_type)

    try:
        with Image.open(BytesIO(data)) as image:
            image.load()
            if image.mode not in {"RGB", "L"}:
                image = image.convert("RGB")
            png_buf = BytesIO()
            image.save(png_buf, format="PNG")
            png_bytes = png_buf.getvalue()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise QaWatermarkDownloadError("unsupported attachment type for watermarked download") from exc

    src = fitz.open(stream=png_bytes, filetype="png")
    try:
        return src.convert_to_pdf()
    finally:
        src.close()


def _decode_attachment_text(data: bytes) -> str:
    """解码问答附件文本；无法严格解码时用 replace，避免整条下载失败。"""
    for encoding in ("utf-8-sig", "utf-16", "utf-8"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _plain_text_to_pdf(data: bytes) -> bytes:
    """不依赖 LibreOffice/Playwright：用 CJK 字体把纯文本按 A4 分页写入 PDF。

    `.md` / `.html` 按原文落 PDF（不做富文本排版）；保证水印下载链路始终可用。
    """
    from bisheng.knowledge.pdf.watermark import PdfWatermarkError, _resolve_cjk_font

    text = _decode_attachment_text(data).replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        text = " "
    try:
        font_sel = _resolve_cjk_font()
    except PdfWatermarkError as exc:
        raise QaWatermarkDownloadError("CJK font unavailable for text watermarked download") from exc

    font = fitz.Font(fontfile=font_sel.font_file, fontname=font_sel.font_name)
    page_width, page_height = 595.0, 842.0
    margin = 48.0
    fontsize = 11.0
    line_height = fontsize * 1.45
    max_width = page_width - margin * 2

    def iter_wrapped_lines() -> list[str]:
        lines: list[str] = []
        for paragraph in text.split("\n"):
            if not paragraph:
                lines.append("")
                continue
            buf = ""
            for ch in paragraph:
                trial = buf + ch
                if font.text_length(trial, fontsize=fontsize) <= max_width:
                    buf = trial
                    continue
                if buf:
                    lines.append(buf)
                buf = ch
            lines.append(buf)
        return lines

    wrapped = iter_wrapped_lines()
    doc = fitz.open()
    try:
        y = margin
        page = doc.new_page(width=page_width, height=page_height)
        for line in wrapped:
            if y + line_height > page_height - margin:
                page = doc.new_page(width=page_width, height=page_height)
                y = margin
            page.insert_text(
                (margin, y + fontsize),
                line or " ",
                fontsize=fontsize,
                fontfile=font_sel.font_file,
                fontname=font_sel.font_name,
            )
            y += line_height
        return doc.tobytes()
    finally:
        doc.close()


def _convert_via_pdf_registry(data: bytes, suffix: str) -> bytes:
    """走知识库统一转换器（Office→LibreOffice，md/txt/html→Playwright）。"""
    from bisheng.knowledge.pdf.converter import (
        ConversionContext,
        PdfConversionError,
        PdfConverterRegistry,
    )

    normalized = ".html" if suffix == ".htm" else suffix
    with tempfile.TemporaryDirectory(prefix="qa-wm-") as tmp:
        tmp_path = Path(tmp)
        src_path = tmp_path / f"source{normalized or '.bin'}"
        src_path.write_bytes(data)
        try:
            result = PdfConverterRegistry().convert(
                src_path,
                tmp_path / "out",
                ConversionContext(timeout_seconds=120),
            )
        except PdfConversionError as exc:
            raise QaWatermarkDownloadError("attachment cannot be converted for watermarked download") from exc
        if result.converter == "original-pdf":
            return data
        pdf_path = Path(result.pdf_path)
        if not pdf_path.is_file() or pdf_path.stat().st_size <= 0:
            raise QaWatermarkDownloadError("attachment cannot be converted for watermarked download")
        return pdf_path.read_bytes()


def _bytes_to_pdf(data: bytes, filename: str) -> bytes:
    suffix = Path(filename).suffix.lower()
    if data[:5] == b"%PDF-" or suffix == ".pdf":
        return data

    image_type = _IMAGE_TYPES.get(suffix) or _sniff_image_type(data)
    if image_type or suffix in _IMAGE_SUFFIXES:
        return _image_bytes_to_pdf(data, image_type)

    # 文本类：优先 Chromium 排版；失败则退回 fitz 纯文本（修复误用 convert_docx_to_pdf 导致 .md 500）
    text_suffixes = {".txt", ".md", ".html", ".htm"}
    if suffix in text_suffixes:
        try:
            return _convert_via_pdf_registry(data, suffix)
        except QaWatermarkDownloadError as exc:
            logger.info("QA text/web PDF converter unavailable, fallback to plain text: {}", exc)
            return _plain_text_to_pdf(data)

    office_suffixes = {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".csv"}
    if suffix in office_suffixes:
        return _convert_via_pdf_registry(data, suffix)

    # 国产 Office 后缀：LibreOffice 常可转，但不在 PdfConverterRegistry 白名单内
    legacy_office_suffixes = {".et", ".wps", ".dps"}
    if suffix in legacy_office_suffixes:
        from bisheng.knowledge.pdf.converter import (
            ConversionContext,
            OfficePdfConverter,
            PdfConversionError,
        )

        with tempfile.TemporaryDirectory(prefix="qa-wm-") as tmp:
            tmp_path = Path(tmp)
            src_path = tmp_path / f"source{suffix}"
            src_path.write_bytes(data)
            try:
                result = OfficePdfConverter().convert(
                    src_path,
                    tmp_path / "out",
                    ConversionContext(timeout_seconds=120),
                )
            except PdfConversionError as exc:
                raise QaWatermarkDownloadError("attachment cannot be converted for watermarked download") from exc
            return Path(result.pdf_path).read_bytes()

    raise QaWatermarkDownloadError("unsupported attachment type for watermarked download")


def _safe_pdf_filename(title: str) -> str:
    stem = Path((title or "qa-asset").strip()).stem or "qa-asset"
    cleaned = re.sub(r'[\\/<>:"|?*\x00-\x1f]', "_", stem)
    return f"{cleaned.strip('.') or 'qa-asset'}.pdf"


def _safe_attachment_filename(title: str, suffix: str) -> str:
    """保留原扩展名的安全下载文件名（视频等非 PDF 附件）。"""
    stem = Path((title or "qa-asset").strip()).stem or "qa-asset"
    cleaned = re.sub(r'[\\/<>:"|?*\x00-\x1f]', "_", stem)
    normalized = suffix if suffix.startswith(".") else f".{suffix}"
    return f"{cleaned.strip('.') or 'qa-asset'}{normalized.lower()}"


async def _load_qa_asset(source: str, title: str, storage) -> tuple[bytes, str]:
    """从 MinIO 读取问答上传对象，并解析用于类型识别的文件名。"""
    bucket, object_name = parse_qa_asset_location(
        source,
        default_bucket=storage.bucket,
        tmp_bucket=storage.tmp_bucket,
    )
    data = await storage.get_object(bucket_name=bucket, object_name=object_name)
    if not data:
        raise QaWatermarkDownloadError("asset not found")
    filename = resolve_conversion_filename(title, object_name)
    return data, filename


async def _apply_qa_pdf_watermark(
    pdf_bytes: bytes,
    *,
    filename: str,
    user_name: str,
    account: str,
    department_name: str,
    tenant_id: int | None,
) -> tuple[bytes, str]:
    """对已是 PDF 的字节叠门户水印，返回 (payload, 下载文件名)。"""
    identity = f"{department_name}-{user_name}" if department_name else user_name
    date_text = datetime.now(SHANGHAI).strftime("%Y/%m/%d")
    horizontal = await ShougangPortalConfigService.get_watermark_horizontal_text(tenant_id=tenant_id)
    spec = PdfWatermarkSpec(lines=(f"{identity}-{account}-{date_text}", horizontal))
    with tempfile.TemporaryDirectory(prefix="qa-wm-out-") as tmp:
        input_path = Path(tmp) / "in.pdf"
        output_path = Path(tmp) / "out.pdf"
        input_path.write_bytes(pdf_bytes)
        try:
            apply_pdf_watermark(input_path, output_path, spec)
        except PdfWatermarkError as exc:
            logger.warning("QA watermark failed: {}", exc)
            raise QaWatermarkDownloadError("watermark generation failed") from exc
        return output_path.read_bytes(), _safe_pdf_filename(filename)


async def build_qa_asset_download(
    *,
    source: str,
    title: str,
    user_name: str,
    account: str,
    department_name: str,
    tenant_id: int | None,
    storage,
) -> tuple[bytes, str, str]:
    """拉取问答附件：视频原文件直下，其余转带水印 PDF。返回 (内容, 文件名, media_type)。"""
    data, filename = await _load_qa_asset(source, title, storage)
    video_suffix = resolve_qa_video_suffix(filename, data)
    if video_suffix:
        safe_name = _safe_attachment_filename(filename, video_suffix)
        media_type = _VIDEO_MEDIA_TYPES.get(video_suffix, "application/octet-stream")
        return data, safe_name, media_type

    pdf_bytes = _bytes_to_pdf(data, filename)
    payload, pdf_name = await _apply_qa_pdf_watermark(
        pdf_bytes,
        filename=filename,
        user_name=user_name,
        account=account,
        department_name=department_name,
        tenant_id=tenant_id,
    )
    return payload, pdf_name, "application/pdf"


async def build_watermarked_qa_pdf(
    *,
    source: str,
    title: str,
    user_name: str,
    account: str,
    department_name: str,
    tenant_id: int | None,
    storage,
) -> tuple[bytes, str]:
    """拉取问答对象、转 PDF、打水印。"""
    data, filename = await _load_qa_asset(source, title, storage)
    pdf_bytes = _bytes_to_pdf(data, filename)
    return await _apply_qa_pdf_watermark(
        pdf_bytes,
        filename=filename,
        user_name=user_name,
        account=account,
        department_name=department_name,
        tenant_id=tenant_id,
    )
