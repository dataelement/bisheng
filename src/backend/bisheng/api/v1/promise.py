from fastapi import APIRouter, BackgroundTasks, Body, Depends, Query, Request

from bisheng.api.services.promise import PromiseService
from bisheng.api.services.user_service import UserPayload, get_login_user
from bisheng.api.v1.schemas import UnifiedResponseModel, resp_200

router = APIRouter(prefix='/promise', tags=['Promise'])


@router.post('/business', response_model=UnifiedResponseModel)
async def create_business_promise(request: Request, login_user: UserPayload = Depends(get_login_user),
                                  business_id: str = Body(..., embed=True, description='业务唯一标识'),
                                  promise_id: str = Body(..., embed=True, description='文件ID')):
    """ 给业务创建承诺书，业务已存在承诺书的话会删除旧的 """
    ret = PromiseService.create_promise(login_user, business_id, promise_id)
    return resp_200(data=ret)


@router.get('/business', response_model=UnifiedResponseModel)
async def get_business_promise(request: Request, login_user: UserPayload = Depends(get_login_user),
                               business_id: str = Query(..., embed=True, description='业务唯一标识')):
    """ 获取业务的承诺书，以及用户是否签署过 """
    ret = PromiseService.get_user_promise(login_user, business_id)
    return resp_200(data=ret)


@router.post('/business/user', response_model=UnifiedResponseModel)
async def write_business_promise(request: Request, login_user: UserPayload = Depends(get_login_user),
                                 business_id: str = Body(..., embed=True, description='业务唯一标识'),
                                 business_name: str = Body(..., embed=True, description='业务名称'),
                                 promise_id: str = Body(..., embed=True, description='文件ID'),
                                 promise_name: str = Body(..., embed=True, description='文件名称')):
    """ 用户签署承诺书 """
    ret = PromiseService.user_write_promise(login_user, business_id, business_name, promise_id, promise_name)
    return resp_200(data=ret)
