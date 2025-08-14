from typing import List

from bisheng.api.services.dataset_service import DatasetService
from bisheng.api.services.user_service import UserPayload, get_login_user
from bisheng.api.v1.schema.dataset_param import CreateDatasetParam
from bisheng.api.v1.schemas import UnifiedResponseModel, resp_200
from bisheng.database.models.dataset import DatasetRead
from fastapi import APIRouter, Depends, Request

# build router
router = APIRouter(prefix='/dataset', tags=['FineTune'])


@router.get('/list', summary='获取数据集列表')
def list_dataset(*,
                 keyword: str = None,
                 page: int = 1,
                 limit: int = 10) -> UnifiedResponseModel[List[DatasetRead]]:
    """
    获取数据集列表
    """
    res, count = DatasetService.build_dataset_list(page, limit, keyword)
    return resp_200(data={'list': res, 'total': count})


@router.post('/create', summary='创建数据集')
def create_dataset(
        *,
        request: Request,
        data: CreateDatasetParam,
        login_user: UserPayload = Depends(get_login_user),
) -> UnifiedResponseModel:
    """
    创建数据集
    """
    dataset = DatasetService.create_dataset(login_user.user_id, data)
    return resp_200(data=dataset)


@router.delete('/del', summary='删除数据集')
def delete_dataset(
        *,
        request: Request,
        dataset_id: int,
        login_user: UserPayload = Depends(get_login_user),
) -> UnifiedResponseModel:
    """
    创建数据集
    """
    DatasetService.delete_dataset(dataset_id)
    return resp_200()
