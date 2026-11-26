import asyncio
import hashlib
import io
import json
import zipfile
from urllib.parse import urlencode

from fastapi import UploadFile
from minio.error import S3Error
from PIL import Image
from starlette.datastructures import Headers
from urllib3.exceptions import HTTPError

from bisheng.common.errcode.finetune import InvalidDatasetPackageError, TrainFileNotExistError
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.finetune.domain.repositories.dataset import FinetuneDatasetRepository
from bisheng.utils import generate_uuid

from ..models.dataset import FinetuneDataset
from ..models.preset_train import PresetTrain
from ..repositories.dataset_catalog import DatasetCatalogRepository
from .dataset_validation import LEGACY_PREVIEW_MAX_BYTES, MANIFEST_NAMES, PREVIEW_SAMPLES, parse_manifest, safe_path
from .finetune_file import FinetuneFileService
from .legacy_dataset import classify_records, convert_legacy_records
from .remote_dataset import RemoteDatasetError, plan_remote_dataset, public_source, remote_reader


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
        rows, total = await DatasetCatalogRepository.list(data_type=data_type, page=page, limit=limit, ready_only=True)
        return {
            "data": [
                {
                    **cls.public_version(version),
                    "catalog_id": catalog.id,
                    "data_type": catalog.data_type,
                    "source_type": catalog.source_type,
                }
                for catalog, version in rows
            ],
            "total": total,
        }

    @classmethod
    async def import_version(cls, request, user):
        remote_request = request.model_copy(update={"data_type": "text"}) if request.data_type == "legacy" else request
        try:
            plan, records, preview, facts = await asyncio.to_thread(plan_remote_dataset, remote_request)
        except RemoteDatasetError as exc:
            raise InvalidDatasetPackageError(msg=str(exc)) from None
        name = request.name.strip().replace("/", "_").replace("\\", "_")
        if plan is not None and request.data_type in {"legacy", "text"}:
            from .dataset_validation import TEXT_MAX_BYTES

            def read_text_zip():
                with remote_reader(remote_request) as session:
                    return session.read(plan["zip"]["path"], TEXT_MAX_BYTES + 1024 * 1024)

            try:
                content = await asyncio.to_thread(read_text_zip)
            except RemoteDatasetError as exc:
                raise InvalidDatasetPackageError(msg=str(exc)) from None
            upload = UploadFile(io.BytesIO(content), filename=name + ".zip", size=len(content))
            try:
                return (
                    await FinetuneFileService.upload_file(
                        [upload], False, user, expected_type=request.data_type, name=name, source_type=request.source
                    )
                )[0]
            finally:
                await upload.close()
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
                return (
                    await FinetuneFileService.upload_file(
                        [upload], False, user, expected_type=request.data_type, name=name, source_type=request.source
                    )
                )[0]
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
        record = FinetuneDataset(id=version_id, name=name, url=url, report=report, user_id=user.user_id)
        catalog = PresetTrain(
            id=version_id,
            name=name,
            url=url,
            user_id=str(user.user_id),
            user_name=user.user_name,
            data_type=request.data_type,
            source_type=request.source,
            version_id=version_id,
        )
        await DatasetCatalogRepository.save(catalog, record)
        return {
            **cls.public_version(record),
            "catalog_id": catalog.id,
            "data_type": request.data_type,
            "source_type": request.source,
        }

    @classmethod
    async def download_catalog(cls, identifier):
        record = await cls.get_catalog(identifier)
        if record.version_id:
            version = await FinetuneDatasetRepository.find_by_id(record.version_id)
            if not version or version.url != record.url:
                raise TrainFileNotExistError()
        storage = await get_minio_storage()
        return {"url": await storage.get_share_link(record.url, clear_host=False)}

    @staticmethod
    async def get_catalog(identifier):
        record = await DatasetCatalogRepository.find(identifier)
        if not record:
            raise TrainFileNotExistError()
        return record

    @staticmethod
    async def list_catalog(data_type=None, source_type=None, keyword=None, page=1, limit=20):
        rows, total = await DatasetCatalogRepository.list(data_type, source_type, keyword, page, limit)
        return {
            "data": [
                {**row.model_dump(), "dataset_report": version.report if version else None} for row, version in rows
            ],
            "total": total,
        }

    @classmethod
    async def save_text(cls, name, records, user, source_type="local", source_dataset_id=None, source_sha256=None):
        if classify_records(records) != "text":
            raise InvalidDatasetPackageError(msg="Expected messages-format text")
        content = json.dumps(records, ensure_ascii=False).encode("utf-8")
        upload = UploadFile(io.BytesIO(content), filename=name + ".json", size=len(content))
        try:
            return (
                await FinetuneFileService.upload_file(
                    [upload],
                    False,
                    user,
                    expected_type="text",
                    name=name,
                    source_type=source_type,
                    source_dataset_id=source_dataset_id,
                    source_sha256=source_sha256,
                )
            )[0]
        finally:
            await upload.close()

    @classmethod
    async def convert(cls, identifier, user):
        catalog = await DatasetCatalogRepository.find(identifier)
        if not catalog or catalog.data_type != "legacy":
            raise TrainFileNotExistError()
        records, digest = await cls.read_original(catalog.url)
        try:
            converted = convert_legacy_records(records)
        except ValueError as exc:
            raise InvalidDatasetPackageError(msg=str(exc)) from None
        return await cls.save_text(
            catalog.name + "-text",
            converted,
            user,
            source_type=catalog.source_type,
            source_dataset_id=catalog.id,
            source_sha256=digest,
        )

    @staticmethod
    async def read_original(url):
        import tempfile

        from .dataset_validation import TEXT_MAX_BYTES, UPLOAD_MAX_BYTES

        storage = await get_minio_storage()

        def read():
            response = storage.download_object_sync(storage.bucket, url)
            digest = hashlib.sha256()
            try:
                with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024) as stream:
                    size = 0
                    while chunk := response.read(1024 * 1024):
                        size += len(chunk)
                        if size > UPLOAD_MAX_BYTES:
                            raise ValueError("Dataset exceeds the upload limit")
                        digest.update(chunk)
                        stream.write(chunk)
                    stream.seek(0)
                    if url.lower().endswith(".zip"):
                        with zipfile.ZipFile(stream) as archive:
                            manifest = next((n for n in MANIFEST_NAMES if n in archive.namelist()), None)
                            if not manifest or archive.getinfo(manifest).file_size > TEXT_MAX_BYTES:
                                raise ValueError("Missing or oversized text manifest")
                            raw = archive.read(manifest)
                    else:
                        manifest = url
                        raw = stream.read(TEXT_MAX_BYTES + 1)
                        if len(raw) > TEXT_MAX_BYTES:
                            raise ValueError("Text manifest exceeds 200 MiB")
                    return parse_manifest(raw, manifest), digest.hexdigest()
            finally:
                response.close()
                response.release_conn()

        try:
            return await asyncio.to_thread(read)
        except (S3Error, HTTPError) as exc:
            raise InvalidDatasetPackageError(msg="Dataset object is unavailable; check its storage") from exc
        except (ValueError, OSError, zipfile.BadZipFile) as exc:
            raise InvalidDatasetPackageError(msg=str(exc)) from None

    @classmethod
    async def catalog_preview(cls, identifier):
        catalog = await DatasetCatalogRepository.find(identifier)
        if not catalog:
            raise TrainFileNotExistError()
        if catalog.version_id and catalog.data_type != "legacy":
            response = await cls.preview(catalog.version_id)
            for sample in response["samples"]:
                for media in sample["media"]:
                    media["url"] = media["url"].replace(
                        f"/datasets/{catalog.version_id}/", f"/dataset-catalog/{identifier}/"
                    )
            return response
        records, _ = await cls.read_original(catalog.url)
        try:
            converted = convert_legacy_records(records)
        except ValueError as exc:
            raise InvalidDatasetPackageError(msg=str(exc)) from None
        return {"samples": [{"messages": row["messages"], "media": []} for row in converted[:PREVIEW_SAMPLES]]}

    @classmethod
    async def _load(cls, version_id):
        """Return the version and the package its preview reads: the stored preview, or legacy full bytes."""
        record = await FinetuneDatasetRepository.find_by_id(version_id)
        if (
            not record
            or record.purpose != "training"
            or not await DatasetCatalogRepository.find(version_id, version=True)
        ):
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
