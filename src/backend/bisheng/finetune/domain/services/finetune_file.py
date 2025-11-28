import os.path
from typing import List

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
    """ 训练任务 文件管理 """

    @classmethod
    async def upload_file(cls, files: List[UploadFile], is_preset: bool,
                          user: UserPayload) -> List[PresetTrain]:
        if len(files) == 0:
            raise TrainFileNotExistError()

        # 将训练文件上传到minio
        file_root = cls.get_upload_file_root(is_preset)
        file_list = await cls.upload_file_to_minio(files, file_root, user)
        # 将预置数据存入数据库
        if is_preset:
            logger.info(f'save preset file : {file_list}')
            file_list = await PresetTrainDao.insert_batch(file_list)
        return file_list

    @classmethod
    async def upload_preset_file(cls, name: str, preset_type: int, file_path: str,
                                 user: UserPayload) -> PresetTrain:
        # 将训练文件上传到minio
        file_root = cls.get_upload_file_root(False)
        file_id = generate_uuid()
        file_ext = os.path.basename(file_path).split('.')[-1]
        object_name = f'{file_root}/{file_id}.{file_ext}'
        minio_client = await get_minio_storage()
        await minio_client.put_object(bucket_name=minio_client.bucket, object_name=object_name, file=file_path)
        # 将预置数据存入数据库
        file_info = PresetTrain(id=file_id,
                                name=name,
                                url=object_name,
                                type=preset_type,
                                user_id=user.user_id,
                                user_name=user.user_name)
        await PresetTrainDao.insert_batch([file_info])
        return file_info

    @classmethod
    def get_upload_file_root(cls, is_preset: bool) -> str:
        if is_preset:
            return 'finetune/train_file/preset'
        else:
            return 'finetune/train_file/personal'

    @classmethod
    async def upload_file_to_minio(cls, files: List[UploadFile], file_root: str,
                                   user: UserPayload) -> List[PresetTrain]:
        minio_client = await get_minio_storage()
        ret = []
        for file in files:
            file_id = generate_uuid()
            file_ext = os.path.basename(file.filename).split('.')[-1]
            file_info = PresetTrain(id=file_id,
                                    name=file.filename,
                                    url=f'{file_root}/{file_id}.{file_ext}',
                                    user_id=user.user_id,
                                    user_name=user.user_name)
            await minio_client.put_object(bucket_name=minio_client.bucket, object_name=file_info.url,
                                          file=file.file, content_type=file.content_type, length=file.size)
            ret.append(file_info)
        return ret

    @classmethod
    async def get_preset_file(cls,
                              keyword: str = None,
                              page_size: int = None,
                              page_num: int = None) -> PageList:
        list_res, total_count = await PresetTrainDao.search_name(keyword, page_size, page_num)
        return PageList(list=list_res, total=total_count)

    @classmethod
    async def delete_preset_file(cls, file_id: str, user: UserPayload) -> None:
        file_data = await PresetTrainDao.find_one(file_id)
        if not file_data:
            raise TrainFileNotExistError()

        logger.info(f'delete preset train file, user: {user}; file: {file_data.model_dump()}')
        await PresetTrainDao.delete_one(file_data)
        logger.info('delete preset train file success')
        return None
