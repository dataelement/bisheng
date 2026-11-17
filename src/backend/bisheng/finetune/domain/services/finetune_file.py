import hashlib
import json
import os.path
import zipfile
from typing import Any

from fastapi import UploadFile
from loguru import logger
from PIL import UnidentifiedImageError
from pydantic import BaseModel

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.finetune import InvalidDatasetPackageError, TrainFileNotExistError
from bisheng.common.schemas.api import PageList
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.utils import generate_uuid

from ..models.dataset import FinetuneDataset
from ..models.preset_train import PresetTrain, PresetTrainDao
from ..repositories.dataset import FinetuneDatasetRepository
from .dataset_validation import MAX_BYTES, inspect_media, inspect_package, validate_records


class FinetuneFileService(BaseModel):
    """Training Tasks File management"""

    @classmethod
    async def upload_file(
        cls, files: list[UploadFile], is_preset: bool, user: UserPayload
    ) -> list[PresetTrain] | list[dict[str, Any]]:
        if len(files) == 0:
            raise TrainFileNotExistError()

        reports = []
        if not is_preset:
            reports = [await cls.inspect_training_upload(file) for file in files]
        file_root = cls.get_upload_file_root(is_preset)
        file_list = await cls.upload_file_to_minio(files, file_root, user)
        # Store preset data in database
        if is_preset:
            logger.info(f"save preset file : {file_list}")
            file_list = await PresetTrainDao.insert_batch(file_list)
        if is_preset:
            return file_list
        result = []
        for item, report in zip(file_list, reports, strict=True):
            record = await FinetuneDatasetRepository.save(
                FinetuneDataset(
                    id=item.id,
                    name=item.name,
                    url=item.url,
                    report=report,
                    user_id=user.user_id,
                )
            )
            result.append({**item.model_dump(), "dataset_report": report, "version_id": record.id})
        return result

    @classmethod
    async def inspect_training_upload(cls, file: UploadFile) -> dict[str, Any]:
        content = await file.read(MAX_BYTES + 1)
        await file.seek(0)
        if not content or len(content) > 20 * 1024 * 1024:
            raise InvalidDatasetPackageError.http_exception(msg="Dataset must be between 1 byte and 20 MiB")
        extension = os.path.splitext(file.filename or "")[1].lower()
        try:
            if extension in {".json", ".jsonl"}:
                raw = content.decode("utf-8-sig")
                records = (
                    [json.loads(line) for line in raw.splitlines() if line.strip()]
                    if extension == ".jsonl"
                    else json.loads(raw)
                )
                cls.validate_text_records(records)
                return cls.dataset_report("text", content, len(records), 0)
            if extension == ".zip":
                modality, samples, media = inspect_package(content)
                return cls.dataset_report(modality, content, samples, media)
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            ValueError,
            zipfile.BadZipFile,
            UnidentifiedImageError,
            OSError,
        ) as exc:
            raise InvalidDatasetPackageError.http_exception(msg=str(exc)) from exc
        raise InvalidDatasetPackageError.http_exception(
            msg="Use JSON/JSONL text data or a ZIP text, image or video package"
        )

    @staticmethod
    def dataset_report(data_type: str, content: bytes, samples: int, media: int) -> dict[str, Any]:
        return {
            "data_type": data_type,
            "samples": samples,
            "media": media,
            "sha256": hashlib.sha256(content).hexdigest(),
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
    async def upload_validation_media(cls, job_id: str, modality: str, file: UploadFile, user: UserPayload):
        content = await file.read(MAX_BYTES + 1)
        await file.seek(0)
        try:
            inspect_media(content, file.filename or "", modality)
        except (ValueError, OSError) as exc:
            raise InvalidDatasetPackageError.http_exception(msg=str(exc)) from exc
        report = cls.dataset_report(modality, content, 1, 1)
        items = await cls.upload_file_to_minio([file], f"finetune/validation/{get_current_tenant_id()}/{job_id}", user)
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
    async def upload_preset_file(cls, name: str, preset_type: int, file_path: str, user: UserPayload) -> PresetTrain:
        # Upload training files tominio
        file_root = cls.get_upload_file_root(False)
        file_id = generate_uuid()
        file_ext = os.path.basename(file_path).split(".")[-1]
        object_name = f"{file_root}/{file_id}.{file_ext}"
        minio_client = await get_minio_storage()
        await minio_client.put_object(bucket_name=minio_client.bucket, object_name=object_name, file=file_path)
        # Store preset data in database
        file_info = PresetTrain(
            id=file_id, name=name, url=object_name, type=preset_type, user_id=user.user_id, user_name=user.user_name
        )
        await PresetTrainDao.insert_batch([file_info])
        return file_info

    @classmethod
    def get_upload_file_root(cls, is_preset: bool) -> str:
        if is_preset:
            return "finetune/train_file/preset"
        else:
            return f"finetune/train_file/personal/{get_current_tenant_id()}"

    @classmethod
    async def upload_file_to_minio(
        cls, files: list[UploadFile], file_root: str, user: UserPayload
    ) -> list[PresetTrain]:
        minio_client = await get_minio_storage()
        ret = []
        for file in files:
            file_id = generate_uuid()
            file_ext = os.path.basename(file.filename).split(".")[-1]
            file_info = PresetTrain(
                id=file_id,
                name=file.filename,
                url=f"{file_root}/{file_id}.{file_ext}",
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
            ret.append(file_info)
        return ret

    @classmethod
    async def get_preset_file(
        cls,
        keyword: str | None = None,
        page_size: int | None = None,
        page_num: int | None = None,
    ) -> PageList:
        list_res, total_count = await PresetTrainDao.search_name(keyword, page_size, page_num)
        return PageList(list=list_res, total=total_count)

    @classmethod
    async def delete_preset_file(cls, file_id: str, user: UserPayload) -> None:
        file_data = await PresetTrainDao.find_one(file_id)
        if not file_data:
            raise TrainFileNotExistError()

        logger.info(f"delete preset train file, user: {user}; file: {file_data.model_dump()}")
        await PresetTrainDao.delete_one(file_data)
        logger.info("delete preset train file success")
        return None
