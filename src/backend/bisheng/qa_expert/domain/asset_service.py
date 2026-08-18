"""专家问答上传资源的解析、转正、补偿和读取签名。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from io import BytesIO
from pathlib import PurePosixPath
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlparse
from uuid import uuid4

from loguru import logger
from PIL import Image, UnidentifiedImageError

from bisheng.core.storage.base import ObjectMetadata

if TYPE_CHECKING:
    from bisheng.core.storage.minio.minio_storage import MinioStorage


IMAGE_FIELDS = {("question", "image_url"), ("answer", "images_url")}
ATTACHMENT_FIELDS = {
    ("question", "file_url"),
    ("question", "attachments"),
    ("answer", "attachments"),
}
# 与门户提问/回答页一致: 最多 3 张. 列名虽是单数 image_url, 实际按分号拼接多值.
QUESTION_IMAGE_LIMIT = 3
ANSWER_IMAGE_LIMIT = 3
FIELD_LIMITS = {
    ("question", "image_url"): QUESTION_IMAGE_LIMIT,
    ("answer", "images_url"): ANSWER_IMAGE_LIMIT,
}
ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}
GENERIC_CONTENT_TYPES = {"", "application/octet-stream", "binary/octet-stream"}
ACTIVE_CONTENT_TYPES = {"image/svg+xml", "text/html"}
IMAGE_FORMAT_CONTENT_TYPES = {
    "JPEG": ("image/jpeg", ".jpg"),
    "PNG": ("image/png", ".png"),
    "WEBP": ("image/webp", ".webp"),
}
QA_CONTENT_TYPES_BY_SUFFIX = {
    ".bmp": "image/bmp",
    ".csv": "text/csv",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".dps": "application/vnd.ms-powerpoint",
    ".et": "application/vnd.ms-excel",
    ".gif": "image/gif",
    ".htm": "text/html",
    ".html": "text/html",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".md": "text/markdown",
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".svg": "image/svg+xml",
    ".txt": "text/plain",
    ".webp": "image/webp",
    ".wps": "application/msword",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
MAX_IMAGE_BYTES = 20 * 1024 * 1024


def infer_qa_content_type(object_name: str, fallback: str | None = None) -> str:
    """Infer QA asset MIME from an allowlisted extension before using fallback."""
    suffix = PurePosixPath(urlparse(object_name).path).suffix.lower()
    inferred = QA_CONTENT_TYPES_BY_SUFFIX.get(suffix)
    if inferred:
        return inferred
    normalized_fallback = (fallback or "").split(";", 1)[0].strip().lower()
    return normalized_fallback or "application/octet-stream"


def inline_response_headers(object_name: str) -> dict[str, str]:
    content_type = infer_qa_content_type(object_name)
    if content_type in ACTIVE_CONTENT_TYPES:
        content_type = "text/plain"
    return {
        "response-content-disposition": "inline",
        "response-content-type": content_type,
    }


class QaAssetError(ValueError):
    """QA 资源引用不可信、不可用或不符合字段策略。"""


def qa_asset_user_message(exc: QaAssetError) -> str:
    """把内部校验失败转成可返回前端的中文说明。"""
    text = str(exc)
    if "too many QA images for question" in text:
        return f"提问最多上传 {QUESTION_IMAGE_LIMIT} 张图片"
    if "too many QA images for answer" in text:
        return f"回答最多上传 {ANSWER_IMAGE_LIMIT} 张图片"
    return "问答图片或附件不合法"


class AssetKind(str, Enum):
    TEMP_OBJECT = "temp_object"
    PERMANENT_OBJECT = "permanent_object"
    OPAQUE_ID = "opaque_id"


@dataclass(frozen=True)
class AssetReference:
    original: str
    kind: AssetKind
    bucket: str | None = None
    object_name: str | None = None


@dataclass(frozen=True)
class StoredObject:
    bucket: str
    object_name: str


@dataclass
class PromotionResult:
    values: dict[str, str | None]
    source_objects: list[StoredObject] = field(default_factory=list)
    created_objects: list[StoredObject] = field(default_factory=list)


def new_owner_stable_id() -> str:
    return uuid4().hex


def redact_reference(value: str) -> str:
    """移除查询参数以避免日志或迁移报告泄露预签名凭证。"""
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc:
        return parsed.path
    return value.split("?", 1)[0]


class QaAssetCodec:
    """按字段语义解析 QA 资源并默认保留未知附件业务 ID。"""

    def __init__(
        self,
        *,
        tmp_bucket: str,
        permanent_bucket: str,
        trusted_hosts: set[str],
    ) -> None:
        self.tmp_bucket = tmp_bucket
        self.permanent_bucket = permanent_bucket
        self.trusted_hosts = {host.lower() for host in trusted_hosts if host}

    @classmethod
    def from_storage(cls, storage: MinioStorage) -> QaAssetCodec:
        hosts: set[str] = set()
        for configured in (storage.minio_config.endpoint, storage.minio_config.sharepoint):
            if not configured:
                continue
            parsed = urlparse(configured if "://" in configured else f"//{configured}")
            if parsed.netloc:
                hosts.add(parsed.netloc.lower())
        return cls(
            tmp_bucket=storage.tmp_bucket,
            permanent_bucket=storage.bucket,
            trusted_hosts=hosts,
        )

    def parse(self, entity_type: str, field_name: str, value: str | list[str] | None) -> list[AssetReference]:
        self._ensure_field(entity_type, field_name)
        if value is None:
            return []
        raw_items = value if isinstance(value, list) else value.split(";")
        return [self._parse_one(entity_type, field_name, str(item).strip()) for item in raw_items if str(item).strip()]

    @staticmethod
    def serialize(values: list[str]) -> str | None:
        return ";".join(values) if values else None

    @staticmethod
    def _ensure_field(entity_type: str, field_name: str) -> None:
        if (entity_type, field_name) not in IMAGE_FIELDS | ATTACHMENT_FIELDS:
            raise QaAssetError(f"unsupported QA asset field: {entity_type}.{field_name}")

    def _parse_one(self, entity_type: str, field_name: str, raw: str) -> AssetReference:
        parsed = urlparse(raw)
        if parsed.scheme or parsed.netloc:
            if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() not in self.trusted_hosts:
                raise QaAssetError("untrusted QA asset URL")
            return self._from_bucket_path(raw, parsed.path)

        path = unquote(raw.split("?", 1)[0]).strip()
        if path.startswith("/"):
            return self._from_bucket_path(raw, path)
        if self._has_traversal(path):
            raise QaAssetError("invalid QA asset object path")

        for bucket, kind in (
            (self.tmp_bucket, AssetKind.TEMP_OBJECT),
            (self.permanent_bucket, AssetKind.PERMANENT_OBJECT),
        ):
            prefix = f"{bucket}/"
            if path.startswith(prefix):
                object_name = path[len(prefix) :]
                self._validate_object_name(object_name)
                if kind is AssetKind.PERMANENT_OBJECT and not object_name.startswith("qa-expert/"):
                    raise QaAssetError("untrusted QA permanent object path")
                return AssetReference(raw, kind, bucket, object_name)

        if path.startswith("qa-expert/"):
            self._validate_object_name(path)
            return AssetReference(raw, AssetKind.PERMANENT_OBJECT, self.permanent_bucket, path)

        if (entity_type, field_name) in IMAGE_FIELDS:
            self._validate_object_name(path)
            return AssetReference(raw, AssetKind.TEMP_OBJECT, self.tmp_bucket, path)

        return AssetReference(raw, AssetKind.OPAQUE_ID)

    def _from_bucket_path(self, raw: str, raw_path: str) -> AssetReference:
        path = unquote(raw_path).lstrip("/")
        if self._has_traversal(path):
            raise QaAssetError("invalid QA asset object path")
        bucket, separator, object_name = path.partition("/")
        if not separator or bucket not in {self.tmp_bucket, self.permanent_bucket}:
            raise QaAssetError("untrusted QA asset bucket")
        self._validate_object_name(object_name)
        kind = AssetKind.TEMP_OBJECT if bucket == self.tmp_bucket else AssetKind.PERMANENT_OBJECT
        if kind is AssetKind.PERMANENT_OBJECT and not object_name.startswith("qa-expert/"):
            raise QaAssetError("untrusted QA permanent object path")
        return AssetReference(raw, kind, bucket, object_name)

    @staticmethod
    def _has_traversal(path: str) -> bool:
        return any(segment in {"", ".", ".."} for segment in path.split("/"))

    @classmethod
    def _validate_object_name(cls, object_name: str) -> None:
        if not object_name or object_name.startswith("/") or cls._has_traversal(object_name):
            raise QaAssetError("invalid QA asset object path")


class QaAssetService:
    """将可信临时对象转为正式对象并在读取时生成短期访问链接。"""

    def __init__(self, storage: MinioStorage) -> None:
        self.storage = storage
        self.codec = QaAssetCodec.from_storage(storage)

    async def promote_fields(
        self,
        *,
        tenant_id: int | None,
        entity_type: str,
        owner_stable_id: str,
        values: dict[str, str | list[str] | None],
    ) -> PromotionResult:
        parsed_fields = {name: self.codec.parse(entity_type, name, value) for name, value in values.items()}
        self._validate_image_counts(entity_type, parsed_fields)
        result = PromotionResult(values={})
        try:
            for field_name, references in parsed_fields.items():
                persisted: list[str] = []
                for reference in references:
                    if reference.kind is AssetKind.OPAQUE_ID:
                        persisted.append(reference.original)
                        continue
                    if reference.kind is AssetKind.PERMANENT_OBJECT:
                        persisted.append(reference.object_name or "")
                        continue
                    target = await self._promote_one(
                        tenant_id=tenant_id,
                        entity_type=entity_type,
                        owner_stable_id=owner_stable_id,
                        field_name=field_name,
                        reference=reference,
                        result=result,
                    )
                    persisted.append(target.object_name)
                result.values[field_name] = self.codec.serialize(persisted)
        except Exception:
            await self.compensate(result)
            raise
        return result

    async def _promote_one(
        self,
        *,
        tenant_id: int | None,
        entity_type: str,
        owner_stable_id: str,
        field_name: str,
        reference: AssetReference,
        result: PromotionResult,
    ) -> StoredObject:
        if not reference.bucket or not reference.object_name:
            raise QaAssetError("temporary object reference is incomplete")
        metadata = await self.storage.stat_object(reference.bucket, reference.object_name)
        target_content_type = infer_qa_content_type(
            reference.object_name,
            metadata.content_type,
        )
        target_extension: str | None = None
        if (entity_type, field_name) in IMAGE_FIELDS:
            target_content_type, target_extension = await self._validate_image(
                reference,
                metadata,
            )

        target = StoredObject(
            bucket=self.storage.bucket,
            object_name=self._permanent_key(
                tenant_id=tenant_id,
                entity_type=entity_type,
                field_name=field_name,
                owner_stable_id=owner_stable_id,
                source_object=reference.object_name,
                extension=target_extension,
            ),
        )
        source = StoredObject(reference.bucket, reference.object_name)
        if not await self.storage.object_exists(target.bucket, target.object_name):
            await self.storage.copy_object(
                source_bucket=source.bucket,
                source_object=source.object_name,
                dest_bucket=target.bucket,
                dest_object=target.object_name,
                content_type=target_content_type,
            )
            result.created_objects.append(target)
        result.source_objects.append(source)
        return target

    async def _validate_image(
        self,
        reference: AssetReference,
        metadata: ObjectMetadata,
    ) -> tuple[str, str]:
        if metadata.size <= 0 or metadata.size > MAX_IMAGE_BYTES:
            raise QaAssetError("QA image size is invalid")
        content_type = (metadata.content_type or "").split(";", 1)[0].lower()
        if content_type not in GENERIC_CONTENT_TYPES and not content_type.startswith("image/"):
            raise QaAssetError("QA image content type is invalid")
        content = await self.storage.get_object(reference.bucket, reference.object_name)
        try:
            with Image.open(BytesIO(content or b"")) as image:
                image.verify()
                image_format = image.format
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise QaAssetError("QA image content is invalid") from exc
        if image_format not in ALLOWED_IMAGE_FORMATS:
            raise QaAssetError("QA image format is not allowed")
        return IMAGE_FORMAT_CONTENT_TYPES[image_format]

    @staticmethod
    def _validate_image_counts(
        entity_type: str,
        parsed_fields: dict[str, list[AssetReference]],
    ) -> None:
        for field_name, references in parsed_fields.items():
            limit = FIELD_LIMITS.get((entity_type, field_name))
            if limit is not None and len(references) > limit:
                raise QaAssetError(f"too many QA images for {entity_type}.{field_name}")

    @staticmethod
    def _permanent_key(
        *,
        tenant_id: int | None,
        entity_type: str,
        field_name: str,
        owner_stable_id: str,
        source_object: str,
        extension: str | None = None,
    ) -> str:
        safe_owner = "".join(char for char in owner_stable_id if char.isalnum() or char in {"-", "_"})
        if not safe_owner:
            raise QaAssetError("invalid QA asset owner id")
        extension = extension or PurePosixPath(source_object).suffix.lower()
        source_uuid = hashlib.sha256(source_object.encode("utf-8")).hexdigest()[:32]
        asset_type = "image" if (entity_type, field_name) in IMAGE_FIELDS else "attachment"
        return f"qa-expert/{tenant_id or 1}/{entity_type}/{asset_type}/{safe_owner}/{source_uuid}{extension}"

    async def compensate(self, result: PromotionResult) -> None:
        for target in reversed(result.created_objects):
            try:
                await self.storage.remove_object(target.bucket, target.object_name)
            except Exception:
                logger.exception(
                    "QA asset compensation failed bucket={} object={}",
                    target.bucket,
                    redact_reference(target.object_name),
                )

    async def cleanup_sources(self, result: PromotionResult) -> None:
        seen: set[tuple[str, str]] = set()
        for source in result.source_objects:
            marker = (source.bucket, source.object_name)
            if marker in seen:
                continue
            seen.add(marker)
            try:
                await self.storage.remove_object(source.bucket, source.object_name)
            except Exception:
                logger.warning(
                    "QA temporary asset cleanup failed bucket={} object={}",
                    source.bucket,
                    redact_reference(source.object_name),
                )

    async def resolve_fields(
        self,
        *,
        entity_type: str,
        values: dict[str, str | list[str] | None],
    ) -> dict[str, str | None]:
        resolved: dict[str, str | None] = {}
        for field_name, value in values.items():
            items: list[str] = []
            try:
                references = self.codec.parse(entity_type, field_name, value)
            except QaAssetError:
                resolved[field_name] = value if isinstance(value, str) else self.codec.serialize(value or [])
                continue
            for reference in references:
                if reference.kind is AssetKind.OPAQUE_ID:
                    items.append(reference.original)
                    continue
                try:
                    items.append(
                        await self.storage.get_share_link(
                            reference.object_name,
                            bucket=reference.bucket,
                            clear_host=False,
                            expire_days=1,
                            response_headers=inline_response_headers(reference.object_name or ""),
                        )
                    )
                except Exception:
                    logger.warning(
                        "QA asset signing failed bucket={} object={}",
                        reference.bucket,
                        redact_reference(reference.object_name or ""),
                    )
                    items.append(reference.original)
            resolved[field_name] = self.codec.serialize(items)
        return resolved
