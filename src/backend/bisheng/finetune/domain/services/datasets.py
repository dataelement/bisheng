import asyncio
import hashlib
import io
import json
import zipfile
from urllib.parse import urlencode

from fastapi import UploadFile
from PIL import Image
from starlette.datastructures import Headers

from bisheng.common.errcode.finetune import InvalidDatasetPackageError, TrainFileNotExistError
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.finetune.domain.repositories.dataset import FinetuneDatasetRepository

from .dataset_validation import MAX_BYTES, safe_path
from .finetune_file import FinetuneFileService
from .remote_dataset import RemoteDatasetError, import_remote_bytes


class DatasetService:
    @staticmethod
    def public_version(record):
        return {
            "id": record.id,
            "version_id": record.id,
            "name": record.name,
            "url": record.url,
            "dataset_report": record.report,
            "create_time": record.create_time,
            "num": record.report.get("samples", 0),
        }

    @classmethod
    async def list_versions(cls, data_type, page, limit):
        records, total = await FinetuneDatasetRepository.list_training(data_type, page, limit)
        return {"data": [cls.public_version(record) for record in records], "total": total}

    @classmethod
    async def import_version(cls, request, user):
        try:
            content = await asyncio.to_thread(import_remote_bytes, request)
        except RemoteDatasetError as exc:
            raise InvalidDatasetPackageError(msg=str(exc)) from None
        # Remote sources converge into the same validation, storage and version path as local uploads.
        filename = request.name.strip().replace("/", "_").replace("\\", "_") + ".zip"
        upload = UploadFile(
            io.BytesIO(content),
            filename=filename,
            size=len(content),
            headers=Headers({"content-type": "application/zip"}),
        )
        try:
            return (await FinetuneFileService.upload_file([upload], False, user))[0]
        finally:
            await upload.close()

    @classmethod
    async def _load(cls, version_id):
        record = await FinetuneDatasetRepository.find_by_id(version_id)
        if not record or record.purpose != "training":
            raise TrainFileNotExistError()
        storage = await get_minio_storage()
        content = await storage.get_object(object_name=record.url)
        if not content or len(content) > MAX_BYTES or hashlib.sha256(content).hexdigest() != record.report["sha256"]:
            raise InvalidDatasetPackageError(msg="Dataset version bytes are missing or differ from their recorded hash")
        return record, content

    @staticmethod
    def _records(record, content):
        if record.url.lower().endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                manifest = next(
                    name
                    for name in ("train.json", "train.jsonl", "data.json", "data.jsonl")
                    if name in archive.namelist()
                )
                text = archive.read(manifest).decode("utf-8-sig")
        else:
            manifest = record.url
            text = content.decode("utf-8-sig")
        return (
            [json.loads(line) for line in text.splitlines() if line.strip()]
            if manifest.endswith(".jsonl")
            else json.loads(text)
        )

    @classmethod
    async def preview(cls, version_id):
        record, content = await cls._load(version_id)
        samples = []
        for item in cls._records(record, content)[:3]:
            messages = item.get("messages") or [
                {
                    "role": "user",
                    "content": item["instruction"] + ("\n" + str(item["input"]) if item.get("input") else ""),
                },
                {"role": "assistant", "content": item["output"]},
            ]
            media = []
            for field, kind in (("images", "image"), ("videos", "video")):
                for name in item.get(field, []):
                    media.append(
                        {
                            "name": name,
                            "type": kind,
                            "url": f"/api/v1/finetune/datasets/{version_id}/media?{urlencode({'path': name})}",
                        }
                    )
            samples.append({"messages": messages, "media": media})
        return {"samples": samples, "version_id": record.id, "dataset_report": record.report}

    @classmethod
    async def media(cls, version_id, path):
        if not safe_path(path):
            raise TrainFileNotExistError()
        record, content = await cls._load(version_id)
        records = cls._records(record, content)
        allowed = {name for item in records for name in item.get("images", []) + item.get("videos", [])}
        if path not in allowed or not record.url.endswith(".zip"):
            raise TrainFileNotExistError()
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            data = archive.read(path)
        if record.report["data_type"] == "video_text":
            content_type = "video/mp4"
        else:
            with Image.open(io.BytesIO(data)) as image:
                content_type = Image.MIME.get(image.format, "application/octet-stream")
        return data, content_type
