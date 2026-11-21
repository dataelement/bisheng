"""Object-storage-backed temporary uploads with caller binding."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath
from urllib.parse import unquote
from uuid import uuid4

from fastapi import UploadFile

from bisheng.chat_session.domain.session_subject import SessionSubject
from bisheng.common.errcode.http_error import NotFoundError
from bisheng.core.cache.utils import save_uploaded_file
from bisheng.core.storage.browser_object_path import parse_browser_object_reference
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.knowledge.domain.upload_file_size import validate_knowledge_upload_file_size


@dataclass(frozen=True, slots=True)
class TempUploadResult:
    file_path: str
    relative_path: str
    file_name: str


class TempUploadService:
    @classmethod
    async def upload(cls, file: UploadFile, subject: SessionSubject) -> TempUploadResult:
        original_name = PurePath((file.filename or "upload").replace("\\", "/")).name
        validate_knowledge_upload_file_size(original_name, file.size)
        suffix = cls._safe_suffix(original_name)
        object_name = f"open-api/{subject.storage_partition}/{uuid4().hex}{suffix}"
        file_path = await save_uploaded_file(file, "bisheng", object_name)
        return TempUploadResult(
            file_path=str(file_path),
            relative_path=object_name,
            file_name=original_name,
        )

    @classmethod
    async def assert_owned_references(cls, files: list[dict] | None, subject: SessionSubject) -> None:
        if not files:
            return
        minio = await get_minio_storage()
        temp_prefix = f"open-api/{subject.storage_partition}/"
        permanent_prefix = f"chat/{subject.storage_partition}/"
        for item in files:
            if not isinstance(item, dict):
                raise NotFoundError.http_exception()
            from bisheng.core.storage.minio.signed_reference import verify_signed_reference

            primary, alias = item.get("filepath"), item.get("file_path")
            if primary and alias and primary != alias:
                raise NotFoundError.http_exception()
            reference = primary or alias
            try:
                resolved = verify_signed_reference(reference, minio)
            except (ValueError, TypeError):
                raise NotFoundError.http_exception() from None
            object_name = item.get("object_name")
            if object_name is not None:
                if (
                    resolved.bucket != minio.bucket
                    or resolved.object_name != object_name
                    or not resolved.object_name.startswith(permanent_prefix)
                ):
                    raise NotFoundError.http_exception()
            elif resolved.bucket != minio.tmp_bucket or not resolved.object_name.startswith(temp_prefix):
                raise NotFoundError.http_exception()
            # Validation and downstream consumption must use the same exact
            # signed source, never a caller-supplied object_name decoy.
            item["filepath"] = reference

    @staticmethod
    def _safe_suffix(filename: str) -> str:
        suffix = PurePath(filename).suffix.lower()
        if len(suffix) > 10 or not suffix[1:].isalnum():
            return ""
        return suffix

    @staticmethod
    def _object_name_from_url(value: str, bucket: str) -> str | None:
        parsed = parse_browser_object_reference(value, "", bucket)
        if parsed is None:
            return None
        object_name = unquote(parsed[1])
        while object_name != unquote(object_name):
            object_name = unquote(object_name)
        return object_name or None
