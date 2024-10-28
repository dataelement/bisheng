from collections import deque
import itertools
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
from bisheng.utils.linked_list import DoubleLinkList
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
    groups = UserGroupDao.get_user_admin_group(login_user.user_id)
    if login_user.is_admin():
        task_list,count = MarkTaskDao.get_task_list(page_size=page_size,page_num=page_num,status=status,create_id=None,user_id=None)
    else:
        task_list,count = MarkTaskDao.get_task_list(page_size=page_size,page_num=page_num,status=status,create_id=login_user.user_id if groups else None,user_id=login_user.user_id)

    result_list = [] 
    for task in task_list:
        record= MarkRecordDao.get_count(task.id)
        process_list= []
        user_count = {}

        for c in task.process_users.split(","):
            user = UserDao.get_user(int(c))
            process_count = "{}:{}".format(user.user_name,0)
            user_count[int(c)] = process_count

        for c in record:
            process_count = "{}:{}".format(c.create_user,c.user_count)
            user_count[c.create_id] = process_count

        for c in user_count:
            process_list.append(user_count[c])

        result_list.append(MarkTaskRead(**task.model_dump(),mark_process=process_list))

    result = {"list":result_list,"total":count}
    return resp_200(data=result)


@router.get('/get_status')
async def get_status(task_id:int,chat_id:str,
                login_user: UserPayload = Depends(get_login_user)):

    record = MarkRecordDao.get_record(task_id,chat_id)
    if not record:
        return resp_200(data={"status":""})

    if login_user.user_id == record.create_id:
        is_self = True
    else:
        is_self = False
    result = {"status":record.status,"is_self":is_self}
    if record:
        return resp_200(result)



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

    # record = MarkRecordDao.get_record(data.task_id,data.session_id)
    # if record:
    #     return resp_500(data="已经标注过了")

    msg = ChatMessageDao.get_msg_by_chat_id(data.session_id)

    flow = FlowDao.get_flow_by_idstr(msg[0].flow_id)
    if flow:
        data.flow_type = "flow"
    else:
        data.flow_type = "assistant"

    db_r = MarkRecordDao.get_record(data.task_id,data.session_id)
    if db_r:
        db_r.status = data.status
        MarkRecordDao.update_record(db_r)

    else:
        record_info = MarkRecord(create_user=login_user.user_name,create_id=login_user.user_id,session_id=data.session_id,task_id=data.task_id,status=data.status,flow_type=data.flow_type)
        #创建一条 用户标注记录 
        MarkRecordDao.create_record(record_info)

    task = MarkTaskDao.get_task_byid(task_id=data.task_id) 
    msg_list = ChatMessageDao.get_msg_by_flows(task.app_id.split(","))
    m_list = [msg.chat_id for msg in msg_list]
    r_list = MarkRecordDao.get_list_by_taskid(data.task_id)
    app_record = [r.session_id for r in r_list ]

    m_list = [s.strip() for s in m_list if s.strip()]
    app_record = [s.strip() for s in app_record if s.strip()]

    m_list.sort()
    app_record.sort()


    logger.info("m_list={} app_record={}",m_list,app_record)

    if m_list == app_record:
        MarkTaskDao.update_task(data.task_id,MarkTaskStatus.DONE.value)
    else:
        MarkTaskDao.update_task(data.task_id,MarkTaskStatus.ING.value)


    # ChatMessageDao.update_message_mark(data.session_id,MarkTaskStatus.DONE.value)


    return resp_200(data="ok")

@router.get('/get_record')
async def get_record(chat_id:str , task_id:int):
    record = MarkRecordDao.get_record(task_id,chat_id)
    return resp_200(data=record)

@router.get("/next")
async def pre_or_next(chat_id:str,action:str,task_id:int,login_user: UserPayload = Depends(get_login_user)):
    """
    prev or next 
    """

    if action not in ["prev","next"]:
        return resp_500(data="action参数错误")

    result = {"task_id":task_id}

    if action == "prev":
        record = MarkRecordDao.get_prev_task(login_user.user_id,task_id)
        if record:
            queue = deque()
            for r in record:
                if r.session_id == chat_id:
                    break
                queue.append(r)

            if len(queue) == 0:
                return resp_200()
            record = queue.pop()
            logger.info("queue={} record={}",queue,record)
            chat = ChatMessageDao.get_msg_by_chat_id(record.session_id)
            result["chat_id"] = record.session_id
            result["flow_type"] = record.flow_type
            result["flow_id"] = chat[0].flow_id
            return resp_200(data=result)
    else:
        task = MarkTaskDao.get_task_byid(task_id)
        record = MarkRecordDao.get_list_by_taskid(task_id)
        chat_list = [r.session_id for r in record]
        msg = ChatMessageDao.get_last_msg_by_flow_id(task.app_id.split(","),chat_list)
        linked = DoubleLinkList()
        k_list = {}
        for m in msg:
            k_list[m.chat_id] = m
            linked.append(m.chat_id)

        cur = linked.find(chat_id)

        logger.info("k_list={} cur={}",k_list,cur.data)

        if cur:
            if cur.next is None:
                if linked.length() == 1 and linked.head().data == chat_id:
                    return resp_200()
                cur = k_list[linked.head().data]
            else:
                cur = k_list[cur.next.data]
            flow = FlowDao.get_flow_by_idstr(cur.flow_id)
            if flow:
                result['flow_type'] = 'flow'
            else:
                result['flow_type'] = 'assistant'

            result["chat_id"] = cur.chat_id
            result["flow_id"] = cur.flow_id
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
