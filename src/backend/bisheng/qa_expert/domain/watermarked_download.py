"""专家问答图片/附件：转 PDF 后打门户水印再下载。"""

from __future__ import annotations

import re
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse
from zoneinfo import ZoneInfo

import fitz
from loguru import logger

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


def _bytes_to_pdf(data: bytes, filename: str) -> bytes:
    suffix = Path(filename).suffix.lower()
    if data[:5] == b"%PDF-" or suffix == ".pdf":
        return data
    image_type = _IMAGE_TYPES.get(suffix)
    if image_type is None and data[:3] == b"\xff\xd8\xff":
        image_type = "jpeg"
    if image_type is None and data[:8] == b"\x89PNG\r\n\x1a\n":
        image_type = "png"
    if image_type:
        src = fitz.open(stream=data, filetype=image_type)
        try:
            return src.convert_to_pdf()
        finally:
            src.close()

    office_suffixes = {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".et", ".wps", ".dps"}
    if suffix in office_suffixes or suffix in {".txt", ".md", ".csv", ".html", ".htm"}:
        from bisheng.knowledge.rag.pipeline.loader.utils.libreoffice_converter import (
            convert_docx_to_pdf,
            convert_ppt_to_pdf,
        )

        with tempfile.TemporaryDirectory(prefix="qa-wm-") as tmp:
            src_path = Path(tmp) / f"source{suffix or '.bin'}"
            src_path.write_bytes(data)
            try:
                if suffix in {".ppt", ".pptx", ".dps"}:
                    pdf_path = convert_ppt_to_pdf(str(src_path), tmp)
                else:
                    pdf_path = convert_docx_to_pdf(str(src_path), tmp)
            except Exception as exc:
                raise QaWatermarkDownloadError("attachment cannot be converted for watermarked download") from exc
            return Path(pdf_path).read_bytes()

    raise QaWatermarkDownloadError("unsupported attachment type for watermarked download")


def _safe_pdf_filename(title: str) -> str:
    stem = Path((title or "qa-asset").strip()).stem or "qa-asset"
    cleaned = re.sub(r'[\\/<>:"|?*\x00-\x1f]', "_", stem)
    return f"{cleaned.strip('.') or 'qa-asset'}.pdf"


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
    bucket, object_name = parse_qa_asset_location(
        source,
        default_bucket=storage.bucket,
        tmp_bucket=storage.tmp_bucket,
    )
    data = await storage.get_object(bucket_name=bucket, object_name=object_name)
    if not data:
        raise QaWatermarkDownloadError("asset not found")
    filename = title or object_name.rsplit("/", 1)[-1]
    pdf_bytes = _bytes_to_pdf(data, filename)
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
