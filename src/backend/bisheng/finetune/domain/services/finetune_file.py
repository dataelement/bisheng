import os.path

from fastapi import UploadFile
from loguru import logger
from pydantic import BaseModel

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.finetune import TrainFileNotExistError
from bisheng.common.schemas.api import PageList
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.utils import generate_uuid

from ..models.preset_train import PresetTrain, PresetTrainDao


class FinetuneFileService(BaseModel):
    """Training Tasks File management"""

    @classmethod
    async def get_download_url(cls, object_name: str, login_user: UserPayload) -> str:
        from bisheng.common.errcode.http_error import UnAuthorizedError
        from bisheng.core.context.tenant import get_current_tenant_id
        from bisheng.finetune.domain.repositories.file_download_repository import FileDownloadRepository
        from bisheng.knowledge.domain.services.preview_source_service import PreviewSourceService

        if (
            not object_name.startswith("finetune/train_file/")
            or any(part in {"", ".", ".."} for part in object_name.split("/"))
            or "\\" in object_name
            or "%" in object_name
        ):
            raise UnAuthorizedError()
        tenant_id = get_current_tenant_id() or login_user.tenant_id
        minio = await get_minio_storage()
        bound = await PreviewSourceService.is_owned_object(
            bucket=minio.bucket, object_name=object_name, login_user=login_user
        )
        record = await FileDownloadRepository.preset_by_object(object_name)
        if record is not None and record.tenant_id == tenant_id:
            # Preset catalog is a tenant-admin capability; no cross-tenant shortcut.
            from bisheng.permission.application import is_tenant_admin

            bound = (
                bound
                or str(record.user_id) == str(login_user.user_id)
                or login_user.is_admin()
                or await is_tenant_admin(login_user.user_id, tenant_id)
            )
        # Expired fresh-upload bindings can be recovered only for our new scoped
        # keys AND an actual persisted owning job, never arbitrary legacy JSON.
        scoped = (
            f"finetune/train_file/personal/{tenant_id}/{login_user.user_id}/",
            f"finetune/train_file/preset/{tenant_id}/{login_user.user_id}/",
        )
        if not bound and object_name.startswith(scoped):
            for job in await FileDownloadRepository.owned_jobs(login_user.user_id):
                if job.tenant_id == tenant_id and any(
                    item.get("url") == object_name
                    for item in (job.train_data or []) + (job.preset_data or [])
                    if isinstance(item, dict)
                ):
                    bound = True
                    break
        if not bound:
            raise UnAuthorizedError()
        return await minio.get_share_link(object_name, clear_host=False)

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
    async def upload_preset_file(cls, name: str, preset_type: int, file_path: str, user: UserPayload) -> PresetTrain:
        # Upload training files tominio
        from bisheng.core.context.tenant import get_current_tenant_id
        from bisheng.knowledge.domain.services.preview_source_service import PreviewSourceService

        tenant_id = get_current_tenant_id() or user.tenant_id
        file_root = f"{cls.get_upload_file_root(False)}/{tenant_id}/{user.user_id}"
        file_id = generate_uuid()
        file_ext = os.path.basename(file_path).split(".")[-1]
        object_name = f"{file_root}/{file_id}.{file_ext}"
        minio_client = await get_minio_storage()
        await minio_client.put_object(bucket_name=minio_client.bucket, object_name=object_name, file=file_path)
        await PreviewSourceService.bind_owned_object(
            bucket=minio_client.bucket, object_name=object_name, login_user=user
        )
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
            return "finetune/train_file/personal"

    @classmethod
    async def upload_file_to_minio(
        cls, files: list[UploadFile], file_root: str, user: UserPayload
    ) -> list[PresetTrain]:
        from bisheng.core.context.tenant import get_current_tenant_id
        from bisheng.knowledge.domain.services.preview_source_service import PreviewSourceService
        from bisheng.knowledge.domain.services.temp_upload_service import TempUploadService

        tenant_id = get_current_tenant_id() or user.tenant_id
        file_root = f"{file_root}/{tenant_id}/{user.user_id}"
        minio_client = await get_minio_storage()
        ret = []
        for file in files:
            file_id = generate_uuid()
            suffix = TempUploadService._safe_suffix(file.filename)
            file_info = PresetTrain(
                id=file_id,
                name=file.filename,
                url=f"{file_root}/{file_id}{suffix}",
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

        logger.info(f"delete preset train file, user: {user}; file: {file_data.model_dump()}")
        await PresetTrainDao.delete_one(file_data)
        logger.info("delete preset train file success")
        return None
