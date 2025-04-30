import json
import urllib.parse
from datetime import datetime
from io import BytesIO
from typing import List, Optional

import numpy as np

from bisheng.api.errcode.base import UnAuthorizedError
from bisheng.api.errcode.knowledge import KnowledgeCPError, KnowledgeQAError
from bisheng.api.services import knowledge_imp
from bisheng.api.services.knowledge import KnowledgeService
from bisheng.api.services.knowledge_imp import add_qa,add_qa_batch
from bisheng.api.services.user_service import UserPayload, get_login_user
from bisheng.api.v1.schemas import (KnowledgeFileProcess, PreviewFileChunk, UnifiedResponseModel,
                                    UpdatePreviewFileChunk, UploadFileResponse, resp_200, resp_500)
from bisheng.cache.utils import save_uploaded_file
from bisheng.database.base import session_getter
from bisheng.database.models.knowledge import (Knowledge, KnowledgeCreate, KnowledgeDao,
                                               KnowledgeRead, KnowledgeTypeEnum, KnowledgeUpdate)
from bisheng.database.models.knowledge_file import (KnowledgeFileDao, KnowledgeFileStatus,
                                                    QAKnoweldgeDao, QAKnowledgeUpsert, QAKnowledge)
from bisheng.database.models.role_access import AccessType
from bisheng.database.models.user import UserDao
from bisheng.utils.logger import logger
from fastapi import (APIRouter, BackgroundTasks, Body, Depends, File, HTTPException, Query, Request,
                     UploadFile)
from fastapi.encoders import jsonable_encoder
import pandas as pd

# build router
router = APIRouter(prefix='/knowledge', tags=['Knowledge'])


@router.post('/upload', response_model=UnifiedResponseModel[UploadFileResponse], status_code=201)
async def upload_file(*, file: UploadFile = File(...)):
    try:
        file_name = file.filename
        # 缓存本地
        file_path = save_uploaded_file(file.file, 'bisheng', file_name)
        if not isinstance(file_path, str):
            file_path = str(file_path)
        return resp_200(UploadFileResponse(file_path=file_path))
    except Exception as exc:
        logger.exception(f'Error saving file: {exc}')
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post('/preview')
async def preview_file_chunk(*,
                             request: Request,
                             login_user: UserPayload = Depends(get_login_user),
                             req_data: PreviewFileChunk):
    """ 获取某个文件的分块预览内容 """
    try:
        parse_type, file_share_url, res, partitions = KnowledgeService.get_preview_file_chunk(
            request, login_user, req_data)
        return resp_200(
            data={
                'parse_type': parse_type,
                'file_url': file_share_url,
                'chunks': res,
                'partitions': partitions
            })
    except Exception as e:
        logger.exception('preview_file_chunk_error')
        return resp_500(data=str(e))


@router.put('/preview')
async def update_preview_file_chunk(*,
                                    request: Request,
                                    login_user: UserPayload = Depends(get_login_user),
                                    req_data: UpdatePreviewFileChunk):
    """ 更新某个文件的分块预览内容 """

    res = KnowledgeService.update_preview_file_chunk(request, login_user, req_data)
    return resp_200(res)


@router.delete('/preview')
async def delete_preview_file_chunk(*,
                                    request: Request,
                                    login_user: UserPayload = Depends(get_login_user),
                                    req_data: UpdatePreviewFileChunk):
    """ 删除某个文件的分块预览内容 """

    res = KnowledgeService.delete_preview_file_chunk(request, login_user, req_data)
    return resp_200(res)


@router.post('/process')
async def process_knowledge_file(*,
                                 request: Request,
                                 login_user: UserPayload = Depends(get_login_user),
                                 background_tasks: BackgroundTasks,
                                 req_data: KnowledgeFileProcess):
    """ 上传文件到知识库内 """
    res = KnowledgeService.process_knowledge_file(request, login_user, background_tasks, req_data)
    return resp_200(res)


@router.post('/create', response_model=UnifiedResponseModel[KnowledgeRead], status_code=201)
def create_knowledge(*,
                     request: Request,
                     login_user: UserPayload = Depends(get_login_user),
                     knowledge: KnowledgeCreate):
    """ 创建知识库. """
    db_knowledge = KnowledgeService.create_knowledge(request, login_user, knowledge)
    return resp_200(db_knowledge)


@router.post('/copy', response_model=UnifiedResponseModel[KnowledgeRead], status_code=201)
async def copy_knowledge(*,
                         request: Request,
                         background_tasks: BackgroundTasks,
                         login_user: UserPayload = Depends(get_login_user),
                         knowledge_id: int = Body(..., embed=True)):
    """ 复制知识库. """
    knowledge = KnowledgeDao.query_by_id(knowledge_id)

    if not login_user.is_admin and knowledge.user_id != login_user.id:
        return UnAuthorizedError.return_resp()

    knowledge_count = KnowledgeFileDao.count_file_by_filters(
        knowledge_id,
        status=KnowledgeFileStatus.PROCESSING.value,
    )
    if knowledge.state != 1 or knowledge_count > 0:
        return KnowledgeCPError.return_resp()
    knowledge = KnowledgeService.copy_knowledge(background_tasks, login_user, knowledge)
    return resp_200(knowledge)


@router.get('', status_code=200)
def get_knowledge(*,
                  request: Request,
                  login_user: UserPayload = Depends(get_login_user),
                  name: str = None,
                  knowledge_type: int = Query(default=KnowledgeTypeEnum.NORMAL.value,
                                              alias='type'),
                  page_size: Optional[int] = 10,
                  page_num: Optional[int] = 1):
    """ 读取所有知识库信息. """
    knowledge_type = KnowledgeTypeEnum(knowledge_type)
    res, total = KnowledgeService.get_knowledge(request, login_user, knowledge_type, name,
                                                page_num, page_size)
    return resp_200(data={'data': res, 'total': total})


@router.put('/', status_code=200)
async def update_knowledge(*,
                           request: Request,
                           login_user: UserPayload = Depends(get_login_user),
                           knowledge: KnowledgeUpdate):
    res = KnowledgeService.update_knowledge(request, login_user, knowledge)
    return resp_200(data=res)


@router.delete('/', status_code=200)
def delete_knowledge(*,
                     request: Request,
                     login_user: UserPayload = Depends(get_login_user),
                     knowledge_id: int = Body(..., embed=True)):
    """ 删除知识库信息. """

    KnowledgeService.delete_knowledge(request, login_user, knowledge_id)
    return resp_200(message='删除成功')


@router.get('/file_list/{knowledge_id}', status_code=200)
def get_filelist(*,
                 request: Request,
                 login_user: UserPayload = Depends(get_login_user),
                 file_name: str = None,
                 knowledge_id: int = 0,
                 page_size: int = 10,
                 page_num: int = 1,
                 status: Optional[int] = None):
    """ 获取知识库文件信息. """
    data, total, flag = KnowledgeService.get_knowledge_files(request, login_user, knowledge_id,
                                                             file_name, status, page_num,
                                                             page_size)

    return resp_200({
        'data': data,
        'total': total,
        'writeable': flag,
    })


@router.get('/qa/list/{qa_knowledge_id}', status_code=200)
def get_QA_list(*,
                qa_knowledge_id: int,
                page_size: int = 10,
                page_num: int = 1,
                question: Optional[str] = None,
                answer: Optional[str] = None,
                keyword: Optional[str] = None,
                status: Optional[int] = None,
                login_user: UserPayload = Depends(get_login_user)):
    """ 获取知识库文件信息. """

    # 查询当前知识库，是否有写入权限
    with session_getter() as session:
        db_knowledge: Knowledge = session.get(Knowledge, qa_knowledge_id)
    if not db_knowledge:
        raise HTTPException(status_code=500, detail='当前知识库不可用，返回上级目录')
    if not login_user.access_check(db_knowledge.user_id, str(qa_knowledge_id),
                                   AccessType.KNOWLEDGE):
        return UnAuthorizedError.return_resp()

    if db_knowledge.type == KnowledgeTypeEnum.NORMAL.value:
        return HTTPException(status_code=500, detail='知识库为普通知识库')

    if keyword:
        question = keyword

    qa_list, total_count = knowledge_imp.list_qa_by_knowledge_id(qa_knowledge_id, page_size,
                                                                 page_num, question, answer,
                                                                 status)
    user_list = UserDao.get_user_by_ids([qa.user_id for qa in qa_list])
    user_map = {user.user_id: user.user_name for user in user_list}
    data = [jsonable_encoder(qa) for qa in qa_list]
    for qa in data:
        qa['questions'] = qa['questions'][0]
        qa['answers'] = json.loads(qa['answers'])[0]
        qa['user_name'] = user_map.get(qa['user_id'], qa['user_id'])

    return resp_200({
        'data':
        data,
        'total':
        total_count,
        'writeable':
        login_user.access_check(db_knowledge.user_id, str(qa_knowledge_id),
                                AccessType.KNOWLEDGE_WRITE)
    })


@router.post('/retry', status_code=200)
def retry(*,
          request: Request,
          login_user: UserPayload = Depends(get_login_user),
          background_tasks: BackgroundTasks,
          req_data: dict):
    """失败重试"""
    KnowledgeService.retry_files(request, login_user, background_tasks, req_data)
    return resp_200()


@router.delete('/file/{file_id}', status_code=200)
def delete_knowledge_file(*,
                          request: Request,
                          file_id: int,
                          login_user: UserPayload = Depends(get_login_user)):
    """ 删除知识文件信息 """
    KnowledgeService.delete_knowledge_file(request, login_user, [file_id])
    return resp_200(message='删除成功')


@router.get('/chunk', status_code=200)
async def get_knowledge_chunk(request: Request,
                              login_user: UserPayload = Depends(get_login_user),
                              knowledge_id: int = Query(..., description='知识库ID'),
                              file_ids: List[int] = Query(default=[], description='文件ID'),
                              keyword: str = Query(default='', description='关键字'),
                              page: int = Query(default=1, description='页数'),
                              limit: int = Query(default=10, description='每页条数条数')):
    """ 获取知识库分块内容 """
    # 为了解决keyword参数有时候没有进行urldecode的bug
    if keyword.startswith('%'):
        keyword = urllib.parse.unquote(keyword)
    res, total = KnowledgeService.get_knowledge_chunks(request, login_user, knowledge_id, file_ids,
                                                       keyword, page, limit)
    return resp_200(data={'data': res, 'total': total})


@router.put('/chunk', status_code=200)
async def update_knowledge_chunk(request: Request,
                                 login_user: UserPayload = Depends(get_login_user),
                                 knowledge_id: int = Body(..., embed=True, description='知识库ID'),
                                 file_id: int = Body(..., embed=True, description='文件ID'),
                                 chunk_index: int = Body(..., embed=True, description='分块索引号'),
                                 text: str = Body(..., embed=True, description='分块内容'),
                                 bbox: str = Body(default='', embed=True, description='分块框选位置')):
    """ 更新知识库分块内容 """
    KnowledgeService.update_knowledge_chunk(request, login_user, knowledge_id, file_id,
                                            chunk_index, text, bbox)
    return resp_200()


@router.delete('/chunk', status_code=200)
async def delete_knowledge_chunk(request: Request,
                                 login_user: UserPayload = Depends(get_login_user),
                                 knowledge_id: int = Body(..., embed=True, description='知识库ID'),
                                 file_id: int = Body(..., embed=True, description='文件ID'),
                                 chunk_index: int = Body(..., embed=True, description='分块索引号')):
    """ 删除知识库分块内容 """
    KnowledgeService.delete_knowledge_chunk(request, login_user, knowledge_id, file_id,
                                            chunk_index)
    return resp_200()


@router.get('/file_share')
async def get_file_share_url(request: Request,
                             login_user: UserPayload = Depends(get_login_user),
                             file_id: int = Query(description='文件唯一ID')):
    url = KnowledgeService.get_file_share_url(request, login_user, file_id)
    return resp_200(data=url)


@router.get('/file_bbox')
async def get_file_bbox(request: Request,
                        login_user: UserPayload = Depends(get_login_user),
                        file_id: int = Query(description='文件唯一ID')):
    res = KnowledgeService.get_file_bbox(request, login_user, file_id)
    return resp_200(data=res)


@router.post('/qa/add', status_code=200)
async def qa_add(*, QACreate: QAKnowledgeUpsert,
                 login_user: UserPayload = Depends(get_login_user)):
    """ 增加知识库信息. """
    QACreate.user_id = login_user.user_id
    db_knowledge = KnowledgeDao.query_by_id(QACreate.knowledge_id)
    if db_knowledge.type != KnowledgeTypeEnum.QA.value:
        raise HTTPException(status_code=404, detail='知识库类型错误')

    db_q = QAKnoweldgeDao.get_qa_knowledge_by_name(QACreate.questions, QACreate.knowledge_id)
    if db_q and not QACreate.id:
        raise KnowledgeQAError.http_exception()

    add_qa(db_knowledge=db_knowledge, data=QACreate)
    return resp_200()


@router.post('/qa/status_switch', status_code=200)
def qa_status_switch(*,
                     status: int = Body(embed=True),
                     id: int = Body(embed=True),
                     login_user: UserPayload = Depends(get_login_user)):
    """ 修改知识库信息. """
    new_qa_db = knowledge_imp.qa_status_change(id, status)
    if not new_qa_db:
        return resp_200()
    if new_qa_db.status != status:
        # 说明状态切换失败
        return resp_500(message=f'状态切换失败: {new_qa_db.remark}')
    return resp_200()


@router.get('/qa/detail', status_code=200)
def qa_list(*, id: int, login_user: UserPayload = Depends(get_login_user)):
    """ 增加知识库信息. """
    qa_knowledge = QAKnoweldgeDao.get_qa_knowledge_by_primary_id(id)
    qa_knowledge.answers = json.loads(qa_knowledge.answers)[0]
    return resp_200(data=qa_knowledge)


@router.post('/qa/append', status_code=200)
def qa_append(
        *,
        ids: list[int] = Body(..., embed=True),
        question: str = Body(..., embed=True),
        login_user: UserPayload = Depends(get_login_user),
):
    """ 增加知识库信息. """
    QA_list = QAKnoweldgeDao.select_list(ids)
    knowledge = KnowledgeDao.query_by_id(QA_list[0].knowledge_id)
    for q in QA_list:
        if question in q.questions:
            raise KnowledgeQAError.http_exception()
    for qa in QA_list:
        qa.questions.append(question)
        knowledge_imp.add_qa(knowledge, qa)
    return resp_200()


@router.delete('/qa/delete', status_code=200)
def qa_delete(*,
              ids: list[int] = Body(embed=True),
              login_user: UserPayload = Depends(get_login_user)):
    """ 删除知识文件信息 """
    knowledge_dbs = QAKnoweldgeDao.select_list(ids)
    knowledge = KnowledgeDao.query_by_id(knowledge_dbs[0].knowledge_id)
    if not login_user.access_check(knowledge.user_id, str(knowledge.id),
                                   AccessType.KNOWLEDGE_WRITE):
        raise HTTPException(status_code=404, detail='没有权限执行操作')

    if knowledge.type == KnowledgeTypeEnum.NORMAL.value:
        return HTTPException(status_code=500, detail='知识库类型错误')

    knowledge_imp.delete_vector_data(knowledge, ids)
    QAKnoweldgeDao.delete_batch(ids)
    return resp_200()


@router.post('/qa/auto_question')
def qa_auto_question(
        *,
        number: int = Body(default=3, embed=True),
        ori_question: str = Body(default='', embed=True),
        answer: str = Body(default='', embed=True),
):
    """通过大模型自动生成问题"""
    questions = knowledge_imp.recommend_question(ori_question, number=number, answer=answer)
    return resp_200(data={'questions': questions})

@router.get('/qa/export/template', status_code=200)
def get_export_template_url():
    data = [{"问题":"","答案":"","相似问题1":"","相似问题2":""}]
    df = pd.DataFrame(data)
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Sheet1", index=False)
    file_name = f"QA知识库导入模板.xlsx"
    file_path = save_uploaded_file(bio, 'bisheng', file_name)
    return resp_200({"url": file_path})


@router.get('/qa/export/{qa_knowledge_id}', status_code=200)
def get_export_url(*,
                   qa_knowledge_id: int,
                   question: Optional[str] = None,
                   answer: Optional[str] = None,
                   keyword: Optional[str] = None,
                   status: Optional[int] = None,
                   max_lines: Optional[int] = 10000,
                   login_user: UserPayload = Depends(get_login_user)):

    # 查询当前知识库，是否有写入权限
    with session_getter() as session:
        db_knowledge: Knowledge = session.get(Knowledge, qa_knowledge_id)
    if not db_knowledge:
        raise HTTPException(status_code=500, detail='当前知识库不可用，返回上级目录')
    if not login_user.access_check(db_knowledge.user_id, str(qa_knowledge_id),
                                   AccessType.KNOWLEDGE):
        return UnAuthorizedError.return_resp()

    if db_knowledge.type == KnowledgeTypeEnum.NORMAL.value:
        return HTTPException(status_code=500, detail='知识库为普通知识库')

    if keyword:
        question = keyword
    def get_qa_source(source):
        '0: 未知 1: 手动；2: 审计, 3: api'
        if int(source) == 1:
            return "手动创建"
        elif int(source) == 2:
            return "审计创建"
        elif int(source) == 3:
            return "api创建"
        return "未知"

    def get_status(statu):
        if int(statu) == 1:
            return "开启"
        return "关闭"

    page_num = 1
    total_num = 0
    page_size = max_lines
    user_list = UserDao.get_all_users()
    user_map = {user.user_id: user.user_name for user in user_list}
    file_list = []
    file_pr = datetime.now().strftime('%Y%m%d%H%M%S')
    file_index = 1
    while True:
        qa_list, total_count = knowledge_imp.list_qa_by_knowledge_id(qa_knowledge_id, page_size,
                                                                 page_num, question, answer,
                                                                 status)

        data = [jsonable_encoder(qa) for qa in qa_list]
        qa_dict_list = []
        all_title = ["问题","答案"]
        for qa in data:
            qa_dict_list.append({
                "问题":qa['questions'][0],
                "答案":json.loads(qa['answers'])[0],
                # "类型":get_qa_source(qa['source']),
                # "创建时间":qa['create_time'],
                # "更新时间":qa['update_time'],
                # "创建者":user_map.get(qa['user_id'], qa['user_id']),
                # "状态":get_status(qa['status']),
            })
            for index,question in enumerate(qa['questions']):
                if index == 0:
                    continue
                key = f"相似问题{index}"
                if key not in all_title:
                    all_title.append(key)
                qa_dict_list[-1][key] = question
        if len(qa_dict_list) != 0:
            df = pd.DataFrame(qa_dict_list)
        else:
            df = pd.DataFrame([{"问题": "", "答案": "", "相似问题1": "", "相似问题2": ""}])
        df = df[all_title]
        bio = BytesIO()
        with pd.ExcelWriter(bio, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Sheet1",index=False)
        file_name = f"{file_pr}_{file_index}.xlsx"
        file_index = file_index + 1
        file_path = save_uploaded_file(bio,'bisheng', file_name)
        file_list.append(file_path)
        total_num += len(qa_list)
        if len(qa_list) < page_size or total_num>=total_count:
            break

    return resp_200({"file_list": file_list})

@router.post('/qa/preview/{qa_knowledge_id}', status_code=200)
def post_import_file(*,
                     qa_knowledge_id: int,
                     file_url: str = Body(..., embed=True),
                     size: Optional[int] = Body(default=0, embed=True),
                     offset: Optional[int] = Body(default=0, embed=True),
                     login_user: UserPayload = Depends(get_login_user)):
    df = pd.read_excel(file_url)
    columns = df.columns.to_list()
    if '答案' not in columns or '问题' not in columns:
        HTTPException(status_code=500, detail='文件格式错误，没有 ‘问题’ 或 ‘答案’ 列')
    data = df.T.to_dict().values()
    insert_data = []
    for dd in data:
        d = QAKnowledgeUpsert(
            user_id=login_user.user_id,
            knowledge_id=qa_knowledge_id,
            answers=[dd['答案']],
            questions=[dd['问题']],
            source=4,
            status=1,
            create_time=datetime.now(),
            update_time=datetime.now())
        for key, value in dd.items():
            if key.startswith('相似问题'):
                d.questions.append(value)
        insert_data.append(d)
    try:
        if size>0 and offset>=0:
            if offset >= len(insert_data):
                insert_data = []
            else:
                insert_data = insert_data[offset:size]
    except Exception as e:
        raise HTTPException(status_code=500, detail=e)
    return resp_200({"result": insert_data})

@router.post('/qa/import/{qa_knowledge_id}', status_code=200)
def post_import_file(*,
                     qa_knowledge_id: int,
                     file_list: list[str] = Body(..., embed=True),
                     login_user: UserPayload = Depends(get_login_user)):
    # 查询当前知识库，是否有写入权限
    with session_getter() as session:
        db_knowledge: Knowledge = session.get(Knowledge, qa_knowledge_id)
    if not db_knowledge:
        raise HTTPException(status_code=500, detail='当前知识库不可用，返回上级目录')
    if not login_user.access_check(db_knowledge.user_id, str(qa_knowledge_id),
                                   AccessType.KNOWLEDGE):
        return UnAuthorizedError.return_resp()

    if db_knowledge.type == KnowledgeTypeEnum.NORMAL.value:
        return HTTPException(status_code=500, detail='知识库为普通知识库')

    insert_result = []
    error_result = []
    have_question = []
    for file_url in file_list:
        df = pd.read_excel(file_url)
        columns = df.columns.to_list()
        if '答案' not in columns or '问题' not in columns:
            insert_result.append(0)
            continue
        data = df.T.to_dict().values()
        insert_data = []
        have_data = []
        all_questions = set()
        for index,dd in enumerate(data):
            tmp_questions = set()
            QACreate = QAKnowledgeUpsert(
            user_id = login_user.user_id,
            knowledge_id = qa_knowledge_id,
            answers = [dd['答案']],
            questions = [dd['问题']],
            source = 4,
            status = 1)
            tmp_questions.add(QACreate.questions[0])
            for key,value in dd.items():
                if key.startswith('相似问题'):
                    if value is not np.nan and value and value is not None and str(value) != 'nan' and str(value) != 'null':
                        if value not in tmp_questions:
                            QACreate.questions.append(value)
                            tmp_questions.add(value)

            db_q = QAKnoweldgeDao.get_qa_knowledge_by_name(QACreate.questions, QACreate.knowledge_id)
            if db_q and not QACreate.id or len(tmp_questions & all_questions) > 0:
                have_data.append(index)
            else:
                insert_data.append(QACreate)
                all_questions = all_questions | tmp_questions
        db_knowledge = KnowledgeDao.query_by_id(qa_knowledge_id)
        result = add_qa_batch(db_knowledge,insert_data)
        insert_result.append(result)
        error_result.append(have_data)

    return resp_200({"result": insert_result,"errors": error_result})



