import os.path
import uuid
from typing import Any, List

from bisheng.api.errcode.finetune import TrainFileNotExistError
from bisheng.api.v1.schema.base_schema import PageList
from bisheng.api.v1.schemas import UnifiedResponseModel, resp_200
from bisheng.database.models.preset_train import PresetTrain, PresetTrainDao
from bisheng.utils.logger import logger
from bisheng.utils.minio_client import MinioClient
from fastapi import UploadFile
from pydantic import BaseModel


class FinetuneFileService(BaseModel):
    """ 训练任务 文件管理 """

    @classmethod
    def upload_file(cls, files: List[UploadFile], is_preset: bool,
                    user: Any) -> UnifiedResponseModel:
        if len(files) == 0:
            return TrainFileNotExistError.return_resp()

        # 将训练文件上传到minio
        file_root = cls.get_upload_file_root(is_preset)
        file_list = cls.upload_file_to_minio(files, file_root, user)
        # 将预置数据存入数据库
        if is_preset:
            logger.info(f'save preset file : {file_list}')
            PresetTrainDao.insert_batch(file_list)
        return resp_200(data=file_list)

    @classmethod
    def upload_preset_file(cls, name: str, type: int, file_path: str,
                           user: Any) -> UnifiedResponseModel:
        # 将训练文件上传到minio
        file_root = cls.get_upload_file_root(False)
        file_id = uuid.uuid4().hex
        file_ext = os.path.basename(file_path).split('.')[-1]
        object_name = f'{file_root}/{file_id}.{file_ext}'
        MinioClient().upload_minio(object_name, file_path)
        # 将预置数据存入数据库
        file_info = PresetTrain(id=file_id,
                                name=name,
                                url=object_name,
                                type=type,
                                user_id=user.get('user_id'),
                                user_name=user.get('user_name'))
        PresetTrainDao.insert_batch([file_info])
        return resp_200(data=file_info)

    @classmethod
    def get_upload_file_root(cls, is_preset: bool) -> str:
        if is_preset:
            return 'finetune/train_file/preset'
        else:
            return 'finetune/train_file/personal'

    @classmethod
    def upload_file_to_minio(cls, files: List[UploadFile], file_root: str,
                             user: Any) -> List[PresetTrain]:
        minio_client = MinioClient()
        ret = []
        for file in files:
            file_id = uuid.uuid4().hex
            file_ext = os.path.basename(file.filename).split('.')[-1]
            file_info = PresetTrain(id=file_id,
                                    name=file.filename,
                                    url=f'{file_root}/{file_id}.{file_ext}',
                                    user_id=user.get('user_id'),
                                    user_name=user.get('user_name'))
            minio_client.upload_minio_file(file_info.url,
                                           file.file,
                                           length=file.size,
                                           content_type=file.content_type)
            ret.append(file_info)
        return ret

    @classmethod
    def get_preset_file(cls,
                        keyword: str = None,
                        page_size: int = None,
                        page_num: int = None) -> List[PresetTrain]:
        list_res, total_count = PresetTrainDao.search_name(keyword, page_size, page_num)
        return PageList(list=list_res, total=total_count)

    @classmethod
    def delete_preset_file(cls, file_id: uuid.UUID, user: Any) -> UnifiedResponseModel:
        file_data = PresetTrainDao.find_one(file_id)
        if not file_data:
            return TrainFileNotExistError.return_resp()

        logger.info(f'delete preset train file, user: {user}; file: {file_data.dict()}')
        PresetTrainDao.delete_one(file_data)
        logger.info('delete preset train file success')
        return resp_200()
