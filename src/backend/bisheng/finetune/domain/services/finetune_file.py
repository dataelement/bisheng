import asyncio
import hashlib
import json
import os
import re
import zipfile
from typing import Any
from urllib.parse import unquote, urlsplit

from fastapi import UploadFile
from loguru import logger
from PIL import UnidentifiedImageError
from pydantic import BaseModel, ValidationError

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.finetune import InvalidDatasetPackageError, InvalidExtraParamsError, TrainFileNotExistError
from bisheng.common.errcode.tenant import NoTenantContextError
from bisheng.common.schemas.api import PageList
from bisheng.core.context.tenant import get_current_tenant_id, strict_tenant_filter
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import QAKnoweldgeDao
from bisheng.knowledge.domain.services.preview_source_service import PreviewSourceService
from bisheng.knowledge.domain.services.temp_upload_service import TempUploadService
from bisheng.knowledge.domain.upload_file_size import validate_knowledge_upload_file_size
from bisheng.permission.application.business_authorization import require_business_action
from bisheng.utils import generate_uuid

from ..models.dataset import FinetuneDataset
from ..models.finetune import FinetuneTrainingFile
from ..models.preset_train import PresetTrain, PresetTrainDao
from ..repositories.dataset import FinetuneDatasetRepository
from ..repositories.dataset_catalog import DatasetCatalogRepository
from .dataset_validation import (
    MEDIA_MAX_BYTES,
    TEXT_MAX_BYTES,
    UPLOAD_MAX_BYTES,
    build_preview,
    inspect_media,
    inspect_package,
    package_preview,
    parse_manifest,
    validate_records,
)
from .legacy_dataset import classify_records


class FinetuneFileService(BaseModel):
    """Training Tasks File management"""

    @classmethod
    async def upload_file(
        cls,
        files: list[UploadFile],
        is_preset: bool,
        user: UserPayload,
        *,
        expected_type=None,
        name=None,
        source_type="local",
        source_dataset_id=None,
        source_sha256=None,
    ) -> list[PresetTrain] | list[dict[str, Any]]:
        if len(files) == 0:
            raise TrainFileNotExistError()

        inspections = []
        if not is_preset:
            inspections = [await cls.inspect_training_upload(file) for file in files]
            if any(report["data_type"] == "legacy" for report, _ in inspections):
                raise InvalidDatasetPackageError(
                    msg="Legacy-format imports are no longer supported; use messages-format text"
                )
            if expected_type and any(report["data_type"] != expected_type for report, _ in inspections):
                raise InvalidDatasetPackageError(msg="Dataset content does not match the selected category")
        file_root = cls.get_upload_file_root(is_preset)
        file_list = await cls.upload_file_to_minio(files, file_root, user)
        # Store preset data in database
        if is_preset:
            logger.info(f"save preset file : {file_list}")
            file_list = await PresetTrainDao.insert_batch(file_list)
        if is_preset:
            return file_list
        result = []
        for item, (report, preview) in zip(file_list, inspections, strict=True):
            report = await cls.store_preview(item.url, report, preview)
            if source_sha256:
                report = {**report, "source_sha256": source_sha256}
            version = FinetuneDataset(
                id=item.id, name=name or item.name, url=item.url, report=report, user_id=user.user_id
            )
            catalog = PresetTrain(
                id=item.id,
                name=name or item.name,
                url=item.url,
                user_id=str(user.user_id),
                user_name=user.user_name,
                type=1 if source_type == "qa" else 0,
                data_type=report["data_type"],
                source_type=source_type,
                source_dataset_id=source_dataset_id,
                version_id=version.id,
            )
            await DatasetCatalogRepository.save(catalog, version)
            result.append(
                {
                    **catalog.model_dump(),
                    "id": catalog.id,
                    "name": catalog.name,
                    "catalog_id": catalog.id,
                    "data_type": catalog.data_type,
                    "source_type": source_type,
                    "dataset_report": report,
                    "version_id": catalog.version_id,
                }
            )
        return result

    @staticmethod
    async def store_preview(url: str, report: dict[str, Any], preview: bytes) -> dict[str, Any]:
        minio_client = await get_minio_storage()
        preview_url = f"{url}.preview.zip"
        await minio_client.put_object(
            bucket_name=minio_client.bucket, object_name=preview_url, file=preview, content_type="application/zip"
        )
        return {**report, "preview_url": preview_url, "preview_sha256": hashlib.sha256(preview).hexdigest()}

    @staticmethod
    def _inspect_stream(stream, extension: str) -> tuple[str, str, int, int, bytes]:
        """Hash and validate an upload from its spooled file without loading a 2 GiB package into memory."""
        digest = hashlib.sha256()
        stream.seek(0)
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
        stream.seek(0)
        if extension in {".json", ".jsonl"}:
            raw = stream.read(TEXT_MAX_BYTES + 1)
            if len(raw) > TEXT_MAX_BYTES:
                raise ValueError("JSON / JSONL datasets must be at most 200 MiB; pack larger data as a ZIP")
            records = parse_manifest(raw, extension)
            validate_records(records)
            preview = build_preview(records, lambda name: b"")
            modality, samples, media = classify_records(records), len(records), 0
        else:
            modality, samples, media = inspect_package(stream)
            if modality == "text":
                stream.seek(0)
                with zipfile.ZipFile(stream) as archive:
                    manifest = next(
                        name
                        for name in ("train.json", "train.jsonl", "data.json", "data.jsonl")
                        if name in archive.namelist()
                    )
                    modality = classify_records(parse_manifest(archive.read(manifest), manifest))
            stream.seek(0)
            preview = package_preview(stream)
        stream.seek(0)
        return modality, digest.hexdigest(), samples, media, preview

    @classmethod
    async def inspect_training_upload(cls, file: UploadFile) -> tuple[dict[str, Any], bytes]:
        file.file.seek(0, os.SEEK_END)
        size = file.file.tell()
        file.file.seek(0)
        if not size or size > UPLOAD_MAX_BYTES:
            raise InvalidDatasetPackageError.http_exception(msg="Dataset must be between 1 byte and 2 GiB")
        extension = os.path.splitext(file.filename or "")[1].lower()
        if extension not in {".json", ".jsonl", ".zip"}:
            raise InvalidDatasetPackageError.http_exception(
                msg="Use JSON/JSONL text data or a ZIP text, image or video package"
            )
        try:
            modality, digest, samples, media, preview = await asyncio.to_thread(
                cls._inspect_stream, file.file, extension
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            ValueError,
            zipfile.BadZipFile,
            UnidentifiedImageError,
            OSError,
        ) as exc:
            raise InvalidDatasetPackageError.http_exception(msg=str(exc)) from exc
        return cls.dataset_report(modality, digest, samples, media), preview

    @staticmethod
    def dataset_report(data_type: str, digest: str, samples: int, media: int) -> dict[str, Any]:
        return {
            "data_type": data_type,
            "samples": samples,
            "media": media,
            "sha256": digest,
            "validated": True,
            "validation_stage": "structure_checked" if data_type == "video_text" else "content_checked",
            "requires_ft_decode": data_type == "video_text",
        }

    @staticmethod
    def validate_text_records(records: Any) -> None:
        validate_records(records)

    @staticmethod
    def validate_image_text_archive(content: bytes) -> tuple[int, int]:
        modality, samples, media = inspect_package(content)
        if modality != "image_text":
            raise ValueError("Expected an image-text dataset")
        return samples, media

    @classmethod
    def _tenant_id(cls) -> int:
        tenant_id = get_current_tenant_id()
        if tenant_id is None:
            raise NoTenantContextError()
        return tenant_id

    @classmethod
    def _personal_prefix(cls, user: UserPayload) -> str:
        return f"{cls.get_upload_file_root(False)}/{cls._tenant_id()}/{user.user_id}/"

    @classmethod
    def _staging_prefix(cls, user: UserPayload) -> str:
        return f"finetune/dataset-upload/{cls._tenant_id()}/{user.user_id}/"

    @classmethod
    async def stage_dataset_file(cls, file: UploadFile, user: UserPayload) -> dict:
        validate_knowledge_upload_file_size(file.filename or "dataset.json", file.size)
        minio = await get_minio_storage()
        object_name = f"{cls._staging_prefix(user)}{generate_uuid()}.json"
        await minio.put_object_tmp(object_name=object_name, file=file.file)
        return {"file_path": await minio.get_share_link(object_name, minio.tmp_bucket, clear_host=False)}

    @classmethod
    async def create_dataset(
        cls, name: str, files: str | None, qa_ids: list[int] | None, user: UserPayload
    ) -> dict[str, Any]:
        cls._tenant_id()
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise InvalidExtraParamsError()
        name = name.strip()
        minio = await get_minio_storage()
        if files:
            try:
                path = unquote(urlsplit(files).path)
            except ValueError as exc:
                raise TrainFileNotExistError() from exc
            prefix = f"/{minio.tmp_bucket}/{cls._staging_prefix(user)}"
            if not path.startswith(prefix) or not re.fullmatch(r"[0-9a-f]{32}\.json", path[len(prefix) :]):
                raise TrainFileNotExistError()
            payload = await minio.get_object(minio.tmp_bucket, path[len(minio.tmp_bucket) + 2 :])
            preset_type = 0
        elif qa_ids:
            ids = list(dict.fromkeys(qa_ids))
            with strict_tenant_filter():
                knowledge = await KnowledgeDao.aget_list_by_ids(ids)
            if {row.id for row in knowledge} != set(ids) or any(
                row.type != KnowledgeTypeEnum.QA.value for row in knowledge
            ):
                raise TrainFileNotExistError()
            for row in knowledge:
                await require_business_action(
                    user, resource_type="knowledge_library", resource_id=row.id, action="visible"
                )
            with strict_tenant_filter():
                qa_rows = await QAKnoweldgeDao.aget_qa_knowledge_by_knowledge_ids(ids)
            samples = [
                {
                    "messages": [
                        {"role": "user", "content": question},
                        {"role": "assistant", "content": json.loads(qa.answers)[0]},
                    ]
                }
                for qa in qa_rows
                for question in qa.questions
            ]
            payload = json.dumps(samples, ensure_ascii=False).encode("utf-8")
            preset_type = 1
        else:
            raise TrainFileNotExistError()
        if payload is None:
            raise TrainFileNotExistError()
        from .datasets import DatasetService

        try:
            records = parse_manifest(payload, "train.json")
            kind = classify_records(records)
            if kind != "text":
                raise ValueError("Legacy-format imports are no longer supported; use messages-format text")
        except (ValueError, UnicodeDecodeError) as exc:
            raise InvalidDatasetPackageError(msg=str(exc)) from None
        return await DatasetService.save_text(
            name, records, user, source_type="qa" if preset_type == 1 else "collection"
        )

    @classmethod
    async def validate_training_files(
        cls, train_data: list[dict] | None, preset_data: list[dict] | None, user: UserPayload
    ) -> None:
        # Normalize the complete payload before signing any object or starting FT.
        for items, is_preset in ((train_data, False), (preset_data, True)):
            normalized = []
            for item in items or []:
                try:
                    source = FinetuneTrainingFile.model_validate(item)
                except ValidationError as exc:
                    raise InvalidExtraParamsError() from exc
                if is_preset:
                    dataset = await PresetTrainDao.find_by_url(source.url)
                    if (
                        dataset is None
                        or dataset.data_type != "legacy"
                        or (source.id is not None and source.id != dataset.id)
                    ):
                        raise TrainFileNotExistError()
                    # Use the canonical stored key, including on case-insensitive DBs.
                    source.url, source.id, source.name = dataset.url, dataset.id, dataset.name
                else:
                    cls.validate_personal_file(source.url, user)
                normalized.append(source.model_dump(exclude_none=True))
            if items is not None:
                items[:] = normalized

    @classmethod
    def validate_personal_file(cls, file_url: str, user: UserPayload) -> None:
        prefix = cls._personal_prefix(user)
        if (
            not isinstance(file_url, str)
            or not file_url.startswith(prefix)
            or not re.fullmatch(r"[0-9a-f]{32}\.[a-zA-Z0-9]{1,10}", file_url[len(prefix) :])
        ):
            raise TrainFileNotExistError()

    @classmethod
    async def _download_owned_training_file(cls, object_name: str, login_user: UserPayload) -> str:
        """Sign only a training-file key the caller owns, administers, or attached to their job."""
        from bisheng.finetune.domain.repositories.file_download_repository import FileDownloadRepository
        from bisheng.permission.application import is_tenant_admin

        if (
            not object_name.startswith("finetune/train_file/")
            or any(part in {"", ".", ".."} for part in object_name.split("/"))
            or "\\" in object_name
            or "%" in object_name
        ):
            raise TrainFileNotExistError()
        tenant_id = get_current_tenant_id() or getattr(login_user, "tenant_id", None)
        minio = await get_minio_storage()
        bound = await PreviewSourceService.is_owned_object(
            bucket=minio.bucket, object_name=object_name, login_user=login_user
        )
        record = await FileDownloadRepository.preset_by_object(object_name)
        if record is not None and record.tenant_id == tenant_id:
            bound = (
                bound
                or str(record.user_id) == str(login_user.user_id)
                or (callable(getattr(login_user, "is_admin", None)) and login_user.is_admin())
                or await is_tenant_admin(login_user.user_id, tenant_id)
            )
        scoped = (
            f"finetune/train_file/personal/{tenant_id}/{login_user.user_id}/",
            f"finetune/train_file/preset/{tenant_id}/{login_user.user_id}/",
        )
        if not bound and object_name.startswith(scoped):
            for job in await FileDownloadRepository.owned_jobs(login_user.user_id):
                if job.tenant_id == tenant_id and any(
                    isinstance(item, dict) and item.get("url") == object_name
                    for item in (job.train_data or []) + (job.preset_data or [])
                ):
                    bound = True
                    break
        if not bound:
            raise TrainFileNotExistError()
        return await minio.get_share_link(object_name, clear_host=True)

    @classmethod
    async def get_download_url(cls, file_url: str, user: UserPayload) -> str:
        if isinstance(file_url, str) and file_url.startswith("finetune/train_file/"):
            catalog = await DatasetCatalogRepository.find_url(file_url, include_deleted=True)
            if catalog is not None and catalog.is_deleted:
                raise TrainFileNotExistError()
            return await cls._download_owned_training_file(file_url, user)
        # Dataset catalog keys are not training-file keys. Only a tenant-scoped row may be signed.
        if (
            not isinstance(file_url, str)
            or any(part in {"", ".", ".."} for part in file_url.split("/"))
            or "\\" in file_url
            or "%" in file_url
            or not (file_url.startswith("finetune/dataset/") or file_url.startswith("dataset/"))
        ):
            raise TrainFileNotExistError()
        dataset = await DatasetCatalogRepository.find_url(file_url)
        if dataset is None or dataset.url != file_url:
            raise TrainFileNotExistError()
        minio = await get_minio_storage()
        return await minio.get_share_link(dataset.url, clear_host=True)

    @classmethod
    async def upload_validation_media(cls, job_id: str, modality: str, file: UploadFile, user: UserPayload):
        content = await file.read(MEDIA_MAX_BYTES + 1)
        await file.seek(0)
        try:
            inspect_media(content, file.filename or "", modality)
        except (ValueError, OSError) as exc:
            raise InvalidDatasetPackageError.http_exception(msg=str(exc)) from exc
        report = cls.dataset_report(modality, hashlib.sha256(content).hexdigest(), 1, 1)
        items = await cls.upload_file_to_minio([file], f"finetune/validation/{job_id}", user)
        item = items[0]
        await FinetuneDatasetRepository.save(
            FinetuneDataset(
                id=item.id,
                name=item.name,
                url=item.url,
                purpose="inference",
                job_id=job_id,
                report=report,
                user_id=user.user_id,
            )
        )
        return {"url": item.url, "name": item.name, **report}

    @classmethod
    def get_upload_file_root(cls, is_preset: bool) -> str:
        if is_preset:
            return "finetune/train_file/preset"
        else:
            return "finetune/train_file/personal"

    @classmethod
    async def upload_file_to_minio(
        cls, files: list[UploadFile], file_root: str, user: UserPayload
    ) -> list[PresetTrain]:
        tenant_id = get_current_tenant_id()
        if tenant_id is None:
            tenant_id = getattr(user, "tenant_id", None)
        if isinstance(tenant_id, bool) or not isinstance(tenant_id, int) or tenant_id <= 0:
            raise NoTenantContextError()
        minio_client = await get_minio_storage()
        ret = []
        for file in files:
            suffix = TempUploadService._safe_suffix(file.filename or "")
            if not suffix:
                raise TrainFileNotExistError()
            file_id = generate_uuid()
            file_info = PresetTrain(
                id=file_id,
                name=file.filename,
                url=f"{file_root}/{tenant_id}/{user.user_id}/{file_id}{suffix}",
                user_id=user.user_id,
                user_name=user.user_name,
            )
            await minio_client.put_object(
                bucket_name=minio_client.bucket,
                object_name=file_info.url,
                file=file.file,
                content_type=file.content_type,
                length=file.size,
            )
            await PreviewSourceService.bind_owned_object(
                bucket=minio_client.bucket, object_name=file_info.url, login_user=user
            )
            ret.append(file_info)
        return ret

    @classmethod
    async def get_preset_file(
        cls, keyword: str | None = None, page_size: int | None = None, page_num: int | None = None, data_type=None
    ) -> PageList:
        rows, total_count = await DatasetCatalogRepository.list(
            keyword=keyword, page=page_num or 1, limit=page_size or 20, data_type=data_type
        )
        return PageList(list=[record for record, _ in rows], total=total_count)

    @classmethod
    async def delete_preset_file(cls, file_id: str, user: UserPayload) -> None:
        file_data = await DatasetCatalogRepository.find(file_id)
        if not file_data:
            raise TrainFileNotExistError()

        logger.info("delete preset train file, user_id={}, file_id={}", user.user_id, file_id)
        await DatasetCatalogRepository.delete(file_id)
        logger.info("delete preset train file success")
        return None
