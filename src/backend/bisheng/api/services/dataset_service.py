from fastapi import HTTPException

from bisheng.api.v1.schema.dataset_param import CreateDatasetParam
from bisheng.common.errcode.dataset import DatasetNameExistsError
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.services.base import BaseService
from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync
from bisheng.database.models.dataset import Dataset, DatasetCreate, DatasetDao, DatasetRead
from bisheng.user.domain.models.user import UserDao


class DatasetService(BaseService):
    @classmethod
    def build_dataset_list(cls, page: int, limit: int, keyword: str | None = None) -> (list[dict], int):
        """completelist DATA"""

        dataset_list = DatasetDao.filter_dataset_by_ids(dataset_ids=[], keyword=keyword, page=page, limit=limit)
        count_filter = []
        if keyword:
            count_filter.append(Dataset.name.like(f"%{keyword}%"))
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
        object_name = f"/dataset/{dataset.id}/{dataset.name}"
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
    def delete_dataset(cls, dataset_id: int, login_user):
        rows = DatasetDao.filter_dataset_by_ids([dataset_id])
        dataset = rows[0] if rows else None
        if not dataset:
            raise HTTPException(status_code=404, detail="Dataset not found")
        # The row carries only user_id (no tenant column), and the DAO delete is a
        # bulk DELETE by id, so ownership must be checked here.
        if dataset.user_id != login_user.user_id and not login_user.is_admin():
            raise UnAuthorizedError()
        # <g id="Bold">Medical Treatment:</g>minio
        object_name = dataset.object_name
        if object_name:
            minio_client = get_minio_storage_sync()
            minio_client.remove_object_sync(object_name=object_name)
        DatasetDao.delete(dataset.id)
        return True

    @classmethod
    async def get_one_by_object_name(cls, object_name: str) -> Dataset | None:
        dataset = await DatasetDao.aget_dataset_by_object_name(object_name)
