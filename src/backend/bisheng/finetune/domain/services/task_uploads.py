"""Private, expiring task uploads. Never creates catalog or dataset-version rows."""

import hashlib
import io
import json
import re
import zipfile
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from bisheng.common.errcode.finetune import InvalidDatasetPackageError, TaskUploadExpiredError
from bisheng.common.errcode.tenant import NoTenantContextError
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.utils import generate_uuid

from .dataset_validation import MANIFEST_NAMES, PREVIEW_SAMPLES, safe_path
from .finetune_file import FinetuneFileService


class TaskUploadService:
    TTL = 24 * 60 * 60

    @staticmethod
    def key(upload_id, user):
        tenant = get_current_tenant_id()
        if tenant is None:
            raise NoTenantContextError()
        if not isinstance(upload_id, str) or not re.fullmatch(r"[a-f0-9]{32}", upload_id):
            raise TaskUploadExpiredError()
        return f"finetune:task-upload:{tenant}:{user.user_id}:{upload_id}"

    @classmethod
    async def upload(cls, file, user):
        report, preview = await FinetuneFileService.inspect_training_upload(file)
        if report["data_type"] == "legacy":
            raise InvalidDatasetPackageError(
                msg="Convert legacy data to messages-format text in dataset management first"
            )
        identifier = generate_uuid()
        key = cls.key(identifier, user)
        extension = "." + file.filename.rsplit(".", 1)[-1].lower()
        url = f"finetune/task-upload/{get_current_tenant_id()}/{user.user_id}/{identifier}{extension}"
        storage = await get_minio_storage()
        await storage.put_object(bucket_name=storage.bucket, object_name=url, file=file.file, length=file.size)
        preview_url = url + ".preview.zip"
        await storage.put_object(
            bucket_name=storage.bucket, object_name=preview_url, file=preview, content_type="application/zip"
        )
        report = {**report, "preview_url": preview_url, "preview_sha256": hashlib.sha256(preview).hexdigest()}
        record = {
            "id": identifier,
            "upload_id": identifier,
            "name": file.filename,
            "url": url,
            "dataset_report": report,
            "num": report["samples"],
            "temporary": True,
            "expires_at": (datetime.now(UTC) + timedelta(seconds=cls.TTL)).isoformat(),
        }
        cache = await get_redis_client()
        await cache.aset(key, record, expiration=cls.TTL)
        return record

    @classmethod
    async def resolve(cls, upload_id, user):
        cache = await get_redis_client()
        record = await cache.aget(cls.key(upload_id, user))
        if not isinstance(record, dict) or record.get("upload_id") != upload_id:
            raise TaskUploadExpiredError()
        return record

    @classmethod
    async def preview_bytes(cls, upload_id, user):
        record = await cls.resolve(upload_id, user)
        storage = await get_minio_storage()
        content = await storage.get_object(object_name=record["dataset_report"]["preview_url"])
        if not content or hashlib.sha256(content).hexdigest() != record["dataset_report"]["preview_sha256"]:
            raise InvalidDatasetPackageError()
        return record, content

    @classmethod
    async def preview(cls, upload_id, user):
        _record, content = await cls.preview_bytes(upload_id, user)
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            manifest = next(name for name in MANIFEST_NAMES if name in archive.namelist())
            records = json.loads(archive.read(manifest))[:PREVIEW_SAMPLES]
        samples = []
        for item in records:
            media = [
                {
                    "name": name,
                    "type": kind,
                    "url": f"/api/v1/finetune/task-uploads/{upload_id}/media?{urlencode({'path': name})}",
                }
                for field, kind in [("images", "image"), ("videos", "video")]
                for name in item.get(field, [])
            ]
            samples.append({"messages": item["messages"], "media": media})
        return {"samples": samples}

    @classmethod
    async def media(cls, upload_id, path, user):
        if not safe_path(path):
            raise TaskUploadExpiredError()
        record, content = await cls.preview_bytes(upload_id, user)
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            manifest = next(name for name in MANIFEST_NAMES if name in archive.namelist())
            rows = json.loads(archive.read(manifest))
            allowed = {name for row in rows for name in row.get("images", []) + row.get("videos", [])}
            if path not in allowed:
                raise TaskUploadExpiredError()
            data = archive.read(path)
        if record["dataset_report"]["data_type"] == "video_text":
            return data, "video/mp4"
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            return data, Image.MIME.get(image.format, "application/octet-stream")
