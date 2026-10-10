"""Object-storage-backed temporary uploads with caller binding."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath
from urllib.parse import unquote, urlparse
from uuid import uuid4

from fastapi import UploadFile

from bisheng.chat_session.domain.session_subject import SessionSubject
from bisheng.common.errcode.http_error import NotFoundError
from bisheng.core.cache.utils import save_uploaded_file
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
            object_name = item.get("object_name")
            if object_name is not None:
                if not str(object_name).startswith(permanent_prefix):
                    raise NotFoundError.http_exception()
                continue
            reference = item.get("filepath") or item.get("file_path")
            resolved = cls._object_name_from_url(str(reference or ""), minio.tmp_bucket)
            if resolved is None or not resolved.startswith(temp_prefix):
                raise NotFoundError.http_exception()

    @staticmethod
    def _safe_suffix(filename: str) -> str:
        suffix = PurePath(filename).suffix.lower()
        if len(suffix) > 10 or not suffix[1:].isalnum():
            return ""
        return suffix

    @staticmethod
    def _object_name_from_url(value: str, bucket: str) -> str | None:
        path = urlparse(value).path
        marker = f"/{bucket}/"
        position = path.find(marker)
        if position < 0:
            return None
        object_name = unquote(path[position + len(marker) :])
        while object_name != unquote(object_name):
            object_name = unquote(object_name)
        return object_name or None
