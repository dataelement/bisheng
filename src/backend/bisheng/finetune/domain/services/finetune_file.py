import json
import re
from urllib.parse import unquote, urlsplit

from fastapi import UploadFile
from loguru import logger
from pydantic import BaseModel, ValidationError

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.finetune import InvalidExtraParamsError, TrainFileNotExistError
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

from ..models.finetune import FinetuneTrainingFile
from ..models.preset_train import PresetTrain, PresetTrainDao


class FinetuneFileService(BaseModel):
    """Training Tasks File management"""

    @classmethod
    async def upload_file(cls, files: list[UploadFile], is_preset: bool, user: UserPayload) -> list[PresetTrain]:
        if len(files) == 0:
            raise TrainFileNotExistError()

        # Upload training files tominio
        file_root = cls.get_upload_file_root(is_preset)
        file_list = await cls.upload_file_to_minio(files, file_root, user)
        # Store preset data in database
        if is_preset:
            logger.info(f"save preset file : {file_list}")
            file_list = await PresetTrainDao.insert_batch(file_list)
        return file_list

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
    ) -> PresetTrain:
        tenant_id = cls._tenant_id()
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
                {"instruction": question, "input": "", "output": json.loads(qa.answers)[0]}
                for qa in qa_rows
                for question in qa.questions
            ]
            payload = json.dumps(samples, ensure_ascii=False).encode("utf-8")
            preset_type = 1
        else:
            raise TrainFileNotExistError()
        if payload is None:
            raise TrainFileNotExistError()
        file_id = generate_uuid()
        object_name = f"finetune/dataset/{tenant_id}/{file_id}.json"
        await minio.put_object(bucket_name=minio.bucket, object_name=object_name, file=payload)
        await PreviewSourceService.bind_owned_object(bucket=minio.bucket, object_name=object_name, login_user=user)
        file_info = PresetTrain(
            id=file_id, name=name, url=object_name, type=preset_type, user_id=user.user_id, user_name=user.user_name
        )
        await PresetTrainDao.insert_batch([file_info])
        return file_info

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
                    if dataset is None or (source.id is not None and source.id != dataset.id):
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
        return await minio.get_share_link(object_name, clear_host=False)

    @classmethod
    async def get_download_url(cls, file_url: str, user: UserPayload) -> str:
        if isinstance(file_url, str) and file_url.startswith("finetune/train_file/"):
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
        dataset = await PresetTrainDao.find_by_url(file_url)
        if dataset is None or dataset.url != file_url:
            raise TrainFileNotExistError()
        minio = await get_minio_storage()
        return await minio.get_share_link(dataset.url, clear_host=False)

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
        cls, keyword: str | None = None, page_size: int | None = None, page_num: int | None = None
    ) -> PageList:
        list_res, total_count = await PresetTrainDao.search_name(keyword, page_size, page_num)
        return PageList(list=list_res, total=total_count)

    @classmethod
    async def delete_preset_file(cls, file_id: str, user: UserPayload) -> None:
        file_data = await PresetTrainDao.find_one(file_id)
        if not file_data:
            raise TrainFileNotExistError()

        logger.info("delete preset train file, user_id={}, file_id={}", user.user_id, file_id)
        await PresetTrainDao.delete_one(file_data)
        logger.info("delete preset train file success")
        return None
