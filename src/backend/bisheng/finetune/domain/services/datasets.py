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
from bisheng.utils import generate_uuid

from ..models.dataset import FinetuneDataset
from .dataset_validation import LEGACY_PREVIEW_MAX_BYTES, MANIFEST_NAMES, PREVIEW_SAMPLES, parse_manifest, safe_path
from .finetune_file import FinetuneFileService
from .remote_dataset import RemoteDatasetError, plan_remote_dataset, public_source


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
            plan, records, preview, facts = await asyncio.to_thread(plan_remote_dataset, request)
        except RemoteDatasetError as exc:
            raise InvalidDatasetPackageError(msg=str(exc)) from None
        name = request.name.strip().replace("/", "_").replace("\\", "_")
        if plan is None:
            # Text rows are the data itself, so they are stored and validated like a local JSON upload.
            content = json.dumps(records, ensure_ascii=False).encode("utf-8")
            upload = UploadFile(
                io.BytesIO(content),
                filename=name + ".json",
                size=len(content),
                headers=Headers({"content-type": "application/json"}),
            )
            try:
                return (await FinetuneFileService.upload_file([upload], False, user))[0]
            finally:
                await upload.close()
        content = json.dumps(plan, ensure_ascii=False, sort_keys=True).encode("utf-8")
        version_id = generate_uuid()
        url = f"{FinetuneFileService._personal_prefix(user)}{version_id}.plan.json"
        storage = await get_minio_storage()
        await storage.put_object(
            bucket_name=storage.bucket, object_name=url, file=content, content_type="application/json"
        )
        report = {
            "data_type": request.data_type,
            "samples": facts["samples"],
            "media": facts["media"],
            "sha256": hashlib.sha256(content).hexdigest(),
            "validated": True,
            "validation_stage": facts["validation_stage"],
            # Only the preview samples were decoded here; FT checks every file after downloading it.
            "requires_ft_decode": True,
            "delivery": "remote",
            "total_bytes": facts["total_bytes"],
            "remote": public_source(request, plan),
        }
        if preview:
            report = await FinetuneFileService.store_preview(url, report, preview)
        record = await FinetuneDatasetRepository.save(
            FinetuneDataset(id=version_id, name=name, url=url, report=report, user_id=user.user_id)
        )
        return {"id": record.id, "name": record.name, "url": url, "dataset_report": report, "version_id": record.id}

    @classmethod
    async def _load(cls, version_id):
        """Return the version and the package its preview reads: the stored preview, or legacy full bytes."""
        record = await FinetuneDatasetRepository.find_by_id(version_id)
        if not record or record.purpose != "training":
            raise TrainFileNotExistError()
        report = record.report
        if report.get("delivery") == "remote" and not report.get("preview_url"):
            # A remote ZIP is only opened on the training host.
            return record, None
        object_name, digest = (
            (report["preview_url"], report["preview_sha256"])
            if report.get("preview_url")
            else (record.url, report["sha256"])
        )
        storage = await get_minio_storage()
        content = await storage.get_object(object_name=object_name)
        limit = None if report.get("preview_url") else LEGACY_PREVIEW_MAX_BYTES
        if not content or (limit and len(content) > limit) or hashlib.sha256(content).hexdigest() != digest:
            raise InvalidDatasetPackageError(msg="Dataset version bytes are missing or differ from their recorded hash")
        return record, content

    @staticmethod
    def _records(record, content):
        if content is None:
            return []
        if record.report.get("preview_url") or record.url.lower().endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                manifest = next(name for name in MANIFEST_NAMES if name in archive.namelist())
                raw = archive.read(manifest)
        else:
            manifest, raw = record.url, content
        return parse_manifest(raw, manifest.lower())

    @classmethod
    async def preview(cls, version_id):
        record, content = await cls._load(version_id)
        samples = []
        for item in cls._records(record, content)[:PREVIEW_SAMPLES]:
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
        if path not in allowed or not (record.report.get("preview_url") or record.url.endswith(".zip")):
            raise TrainFileNotExistError()
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            data = archive.read(path)
        if record.report["data_type"] == "video_text":
            content_type = "video/mp4"
        else:
            with Image.open(io.BytesIO(data)) as image:
                content_type = Image.MIME.get(image.format, "application/octet-stream")
        return data, content_type
