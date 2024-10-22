import json
from typing import Optional
from bisheng.api.v1.schema.mark_schema import MarkData, MarkTaskCreate
from bisheng.api.v1.schemas import resp_200, resp_500
from bisheng.database.models.flow import FlowDao
from bisheng.database.models.mark_app_user import MarkAppUser, MarkAppUserDao
from bisheng.database.models.mark_task import  MarkTask, MarkTaskDao, MarkTaskRead, MarkTaskStatus
from bisheng.database.models.mark_record import MarkRecord, MarkRecordDao
from bisheng.database.models.message import ChatMessageDao
from bisheng.database.models.user import UserDao
from bisheng.database.models.user_group import UserGroupDao
from bisheng.utils.logger import logger
from fastapi_jwt_auth import AuthJWT
from bisheng.api.services.user_service import UserPayload, get_login_user
from fastapi import (APIRouter, BackgroundTasks, Body, Depends, File, HTTPException, Query, Request)


router = APIRouter(prefix='/mark', tags=['Mark'])


@router.get('/list')
def list(request: Request,Authorize: AuthJWT = Depends(),
                status:Optional[int] = None,
                page_size: int = 10,
                page_num: int = 1,
         login_user: UserPayload = Depends(get_login_user)):
    """
    非admin 只能查看自己已标注和未标注的
    """
    Authorize.jwt_required()
    groups = UserGroupDao.get_user_admin_group(login_user.user_id)
    if login_user.is_admin():
        task_list,count = MarkTaskDao.get_task_list(page_size=page_size,page_num=page_num,status=status,create_id=None)
    else:
        task_list,count = MarkTaskDao.get_task_list(page_size=page_size,page_num=page_num,status=status,create_id=login_user.user_id if groups else None)

    result_list = [] 
    for task in task_list:
        count = MarkRecordDao.get_count(task.id)
        process_list= []
        for c in count:
            process_count = "{}:{}".format(c.create_user,c.user_count)
            process_list.append(process_count)

        logger.info(process_list)
        result_list.append(MarkTaskRead(**task.model_dump(),mark_process=process_list))

    result = {"list":result_list,"total":count}
    return resp_200(data=result)


@router.post('/create_task')
async def create(task_create: MarkTaskCreate,login_user: UserPayload = Depends(get_login_user)):
    """
    应用和用户是多对多对关系，依赖一条主任务记录
    """

    task = MarkTask(create_id=login_user.user_id,
                    create_user=login_user.user_name,
                    app_id=",".join(task_create.app_list),
                    process_users=",".join(task_create.user_list)
                    )
    MarkTaskDao.create_task(task)

    user_app = [MarkAppUser(task_id=task.id,create_id=login_user.user_id,app_id=app, user_id=user) for app in task_create.app_list for user in task_create.user_list]
    
    MarkAppUserDao.create_task(user_app)
    return resp_200(data="ok")


@router.get('/get_user')
async def get_user(task_id:int):
    """
    查询此应用下 所有的用户
    """

    #根据type 查询不同的会话
    task = MarkTaskDao.get_task_byid(task_id)
    user_list = []

    for u in task.process_users.split(","):
        user = UserDao.get_user(int(u))
        user_list.append(user)

    return resp_200(data=user_list)

@router.post('/mark')
async def mark(data: MarkData,
               login_user: UserPayload = Depends(get_login_user)):

    """
    标记任务为当前用户，并且其他人不能进行覆盖
    flow_type flow assistant
    """

    record = MarkRecordDao.get_record(data.task_id,data.session_id)
    if record:
        return resp_500(data="已经标注过了")

    msg = ChatMessageDao.get_msg_by_chat_id(data.session_id)

    flow = FlowDao.get_flow_by_idstr(msg[0].flow_id)
    if flow:
        data.flow_type = "flow"
    else:
        data.flow_type = "assistant"

    record_info = MarkRecord(create_user=login_user.user_name,create_id=login_user.user_id,session_id=data.session_id,task_id=data.task_id,status=data.status,flow_type=data.flow_type)
    #创建一条 用户标注记录 
    MarkRecordDao.create_record(record_info)
    MarkTaskDao.update_task(data.task_id,MarkTaskStatus.ING.value)
    # msg.mark_status = data.status
    # ChatMessageDao.update_message_model(msg)


    return resp_200(data="ok")

@router.get('/get_record')
async def get_record(chat_id:str , task_id:int):
    record = MarkRecordDao.get_record(task_id,chat_id)
    return resp_200(data=record)

@router.get("/next")
async def pre_or_next(action:str,task_id:int,login_user: UserPayload = Depends(get_login_user)):
    """
    prev or next 
    """

    if action not in ["prev","next"]:
        return resp_500(data="action参数错误")

    result = {"task_id":task_id}

    if action == "prev":
        record = MarkRecordDao.get_prev_task(login_user.user_id)
        if record:
            chat = ChatMessageDao.get_msg_by_chat_id(record.session_id)
            result["chat_id"] = record.session_id
            result["flow_type"] = record.flow_type
            result["flow_id"] = chat[0].flow_id
            return resp_200(data=result)
    else:
        task = MarkTaskDao.get_task_byid(task_id)
        msg = ChatMessageDao.get_last_msg_by_flow_id(task.app_id.split(","))
        if msg:
            
            flow = FlowDao.get_flow_by_idstr(msg.flow_id)
            if flow:
                result['flow_type'] = 'flow'
            else:
                result['flow_type'] = 'assistant'

            result["chat_id"] = msg.chat_id
            result["flow_id"] = msg.flow_id
        return resp_200(data=result)

    return resp_200()

@router.delete('/del')
def del_task(request: Request,task_id:int,Authorize: AuthJWT = Depends() ):
    """
    非admin 只能查看自己已标注和未标注的
    """
    Authorize.jwt_required()

    MarkTaskDao.delete_task(task_id)
    MarkRecordDao.del_record(task_id)

    return resp_200(data="ok")
