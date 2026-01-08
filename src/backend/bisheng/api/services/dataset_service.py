from typing import Dict, List, Optional

from fastapi import HTTPException

from bisheng.api.services.base import BaseService
from bisheng.api.v1.schema.dataset_param import CreateDatasetParam
from bisheng.common.errcode.dataset import DatasetNameExistsError
from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync
from bisheng.database.models.dataset import Dataset, DatasetCreate, DatasetDao, DatasetRead
from bisheng.user.domain.models.user import UserDao


class DatasetService(BaseService):

    @classmethod
    def build_dataset_list(cls,
                           page: int,
                           limit: int,
                           keyword: Optional[str] = None) -> (List[Dict], int):
        """completelist DATA"""

        dataset_list = DatasetDao.filter_dataset_by_ids(dataset_ids=[],
                                                        keyword=keyword,
                                                        page=page,
                                                        limit=limit)
        count_filter = []
        if keyword:
            count_filter.append(Dataset.name.like('%{}%'.format(keyword)))
        total_count = DatasetDao.get_count_by_filter(count_filter)

        user_ids = [one.user_id for one in dataset_list]
        user_list = UserDao.get_user_by_ids(user_ids)
        user_dict = {one.user_id: one for one in user_list}
        res = [DatasetRead.model_validate(one) for one in dataset_list]
        for one in res:
            one.user_name = user_dict[one.user_id].user_name
            if one.object_name:
                one.url = one.object_name

        return res, total_count

    @classmethod
    def create_dataset(cls, user_id: int, data: CreateDatasetParam):
        """Create Dataset"""
        dataset_insert = DatasetCreate.validate(data)
        dataset_insert.user_id = user_id
        isExist = DatasetDao.get_dataset_by_name(data.name)
        if isExist:
            raise DatasetNameExistsError()
        dataset = DatasetDao.insert(dataset_insert)
        # Conditioning Documentation
        object_name = f'/dataset/{dataset.id}/{dataset.name}'
        if data.file_url:
            # MinioClient().upload_minio()
            dataset.object_name = object_name
        if data.qa_list:
            for qa in data.qa_list:
                qa.dataset_id = dataset.id
                # QADao.insert(qa)

        dataset = DatasetDao.update(dataset)
        return dataset

    @classmethod
    def delete_dataset(cls, dataset_id: int):
        dataset = DatasetDao.get_dataset_by_id(dataset_id)
        if not dataset:
            raise HTTPException(status_code=404, detail='Dataset not found')
        # <g id="Bold">Medical Treatment:</g>minio
        object_name = dataset.object_name
        if object_name:
            minio_client = get_minio_storage_sync()
            minio_client.remove_object_sync(object_name=object_name)
        DatasetDao.delete(dataset)
        return True

    @classmethod
    async def get_one_by_object_name(cls, object_name: str) -> Optional[Dataset]:
        dataset = await DatasetDao.aget_dataset_by_object_name(object_name)
