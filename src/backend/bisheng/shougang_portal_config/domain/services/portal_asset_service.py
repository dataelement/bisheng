from __future__ import annotations

import io
import uuid
from dataclasses import dataclass
from typing import Final
from urllib.parse import quote

from fastapi import UploadFile
from PIL import Image, UnidentifiedImageError

from bisheng.common.services.config_service import settings as bisheng_settings
from bisheng.core.storage.minio.minio_manager import get_minio_storage

MAX_IMAGE_BYTES: Final[int] = 5 * 1024 * 1024
MAX_IMAGE_EDGE: Final[int] = 4096
MAX_IMAGE_PIXELS: Final[int] = 16 * 1024 * 1024
ALLOWED_CATEGORIES: Final[frozenset[str]] = frozenset({"banner", "app-icon"})
ALLOWED_MIME: Final[frozenset[str]] = frozenset(
    {"image/jpeg", "image/png", "image/webp"}
)
FORMAT_METADATA: Final[dict[str, tuple[str, str]]] = {
    "JPEG": ("jpg", "image/jpeg"),
    "PNG": ("png", "image/png"),
    "WEBP": ("webp", "image/webp"),
}


@dataclass(frozen=True)
class PortalAssetValidationError(ValueError):
    status_code: int
    message: str

    def __str__(self) -> str:
        return self.message


async def _upload_public_asset(
    payload: bytes,
    *,
    object_name: str,
    content_type: str,
) -> str:
    storage = await get_minio_storage()
    bucket_name = bisheng_settings.object_storage.minio.public_bucket
    await storage.ensure_public_read_prefix(
        bucket_name=bucket_name,
        object_prefix="portal-assets/",
    )
    await storage.put_object(
        bucket_name=bucket_name,
        object_name=object_name,
        file=io.BytesIO(payload),
        content_type=content_type,
        length=len(payload),
    )
    return f"/{quote(bucket_name, safe='')}/{quote(object_name, safe='/')}"


class ShougangPortalAssetService:
    @classmethod
    async def upload(
        cls,
        *,
        file: UploadFile,
        category: str,
        tenant_id: int,
    ) -> dict[str, str]:
        normalized_category = category.strip().lower()
        if normalized_category not in ALLOWED_CATEGORIES:
            raise PortalAssetValidationError(422, "不支持的公共资源类别")
        if tenant_id <= 0:
            raise PortalAssetValidationError(403, "租户上下文无效")

        content_type = (file.content_type or "").strip().lower()
        if content_type not in ALLOWED_MIME:
            raise PortalAssetValidationError(415, "不支持的图片类型")

        payload = await file.read(MAX_IMAGE_BYTES + 1)
        if not payload:
            raise PortalAssetValidationError(422, "文件为空")
        if len(payload) > MAX_IMAGE_BYTES:
            raise PortalAssetValidationError(413, "图片不得超过 5MB")

        image_format = cls._validate_image(payload)
        extension, decoded_content_type = FORMAT_METADATA[image_format]
        if content_type != decoded_content_type:
            raise PortalAssetValidationError(415, "图片类型与实际内容不一致")

        object_name = (
            f"portal-assets/{tenant_id}/{normalized_category}/"
            f"{uuid.uuid4().hex}.{extension}"
        )
        image_url = await _upload_public_asset(
            payload,
            object_name=object_name,
            content_type=decoded_content_type,
        )
        return {
            "image_url": image_url,
            "object_key": object_name,
        }

    @staticmethod
    def _validate_image(payload: bytes) -> str:
        try:
            with Image.open(io.BytesIO(payload)) as image:
                width, height = image.size
                if (
                    width > MAX_IMAGE_EDGE
                    or height > MAX_IMAGE_EDGE
                    or width * height > MAX_IMAGE_PIXELS
                ):
                    raise PortalAssetValidationError(
                        413,
                        "图片尺寸不得超过 4096x4096",
                    )
                image.verify()
            with Image.open(io.BytesIO(payload)) as image:
                image_format = (image.format or "").upper()
        except PortalAssetValidationError:
            raise
        except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError):
            raise PortalAssetValidationError(
                415,
                "图片解析失败, 可能不是有效的图片",
            ) from None

        if image_format not in FORMAT_METADATA:
            raise PortalAssetValidationError(415, "不支持的图片格式")
        return image_format
