import json
from bisheng.api.v1.schema.mark_schema import MarkTaskCreate
from bisheng.api.v1.schemas import resp_200, resp_500
from bisheng.database.models.mark_app_user import MarkAppUser, MarkAppUserDao
from bisheng.database.models.mark_task import  MarkTask, MarkTaskDao
from bisheng.database.models.mark_record import MarkRecord, MarkRecordDao
from fastapi_jwt_auth import AuthJWT
from bisheng.api.services.user_service import UserPayload, get_login_user
from fastapi import (APIRouter, BackgroundTasks, Body, Depends, File, HTTPException, Query, Request)


router = APIRouter(prefix='/mark', tags=['Mark'])


@router.get('/list')
def list(request: Request,Authorize: AuthJWT = Depends(),login_user: UserPayload = Depends(get_login_user)):
    """
    非admin 只能查看自己已标注和未标注的
    """
    Authorize.jwt_required()
    if login_user.is_admin():
        task_List = MarkTaskDao.get_task_list(user_id=None)
    else:
        task_List = MarkTaskDao.get_task_list(user_id=login_user.user_id)

    return resp_200(data=task_List)


@router.post('/create_task')
async def create(task_create: MarkTaskCreate,login_user: UserPayload = Depends(get_login_user)):
    """
    应用和用户是多对多对关系，依赖一条主任务记录
    """


    user_app = [MarkAppUser(create_id=login_user.user_id,app_id=app, user_id=user) for app in task_create.app_list for user in task_create.user_list]
    MarkAppUserDao.create_task(user_app)
    return resp_200(data="ok")


@router.get('/get_session')
async def get_session(id:str, type:str):
    """
    查询此应用下 所有的会话记录
    """

    #根据type 查询不同的会话

    return resp_200(data="")

@router.post('/mark')
async def mark(session_id:str ,task_id:int,
               login_user: UserPayload = Depends(get_login_user)):

    """
    标记任务为当前用户，并且其他人不能进行覆盖
    """

    record = MarkRecordDao.get_record(task_id,session_id)
    if record:
        return resp_500(data="已经标注过了")

    record_info = MarkRecord(create_id=login_user.user_id,session_id=session_id,task_id=task_id)
    #创建一条 用户标注记录 
    MarkRecordDao.create_record(record_info)

    return resp_200(data="ok")

@router.delete('/del')
def del_task(request: Request,task_id:int,Authorize: AuthJWT = Depends() ):
    """
    非admin 只能查看自己已标注和未标注的
    """
    Authorize.jwt_required()

    task = MarkTask(id=task_id)

    MarkTaskDao.delete_task(task)

    return resp_200(data="ok")
