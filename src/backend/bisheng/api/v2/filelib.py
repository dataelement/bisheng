import hashlib
import json
import os
from typing import Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile, Request
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func
from sqlmodel import select
from starlette.responses import FileResponse

from bisheng.api.errcode.base import UnAuthorizedError, NotFoundError
from bisheng.api.services.knowledge import KnowledgeService
from bisheng.api.services.knowledge_imp import (addEmbedding, decide_vectorstores,
                                                delete_es,
                                                delete_knowledge_file_vectors, delete_vector,
                                                text_knowledge, process_file_task)
from bisheng.api.v1.schemas import ChunkInput, UnifiedResponseModel, resp_200, resp_500, KnowledgeFileProcess, \
    KnowledgeFileOne
from bisheng.api.v2.utils import get_default_operator
from bisheng.cache.utils import save_download_file
from bisheng.database.base import session_getter
from bisheng.database.models.knowledge import (Knowledge, KnowledgeCreate, KnowledgeRead,
                                               KnowledgeUpdate, KnowledgeDao)
from bisheng.database.models.knowledge_file import (KnowledgeFile, KnowledgeFileDao,
                                                    KnowledgeFileRead, KnowledgeFileStatus)
from bisheng.database.models.message import ChatMessageDao
from bisheng.database.models.role_access import AccessType
from bisheng.interface.embeddings.custom import FakeEmbedding
from bisheng.utils.logger import logger
from bisheng.utils.minio_client import MinioClient

# build router
router = APIRouter(prefix='/filelib', tags=['OpenAPI', 'Knowledge'])


@router.post('/', status_code=201)
def create(request: Request,
           knowledge: KnowledgeCreate):
    """创建知识库."""
    login_user = get_default_operator()
    db_knowledge = KnowledgeService.create_knowledge(request, login_user, knowledge)
    return resp_200(db_knowledge)


@router.put('/', status_code=201)
def update_knowledge(*, request: Request,
                     knowledge: KnowledgeUpdate):
    """ 更新知识库."""
    login_user = get_default_operator()
    db_knowledge = KnowledgeService.update_knowledge(request, login_user, knowledge)
    return resp_200(db_knowledge)


@router.get('/', status_code=200)
def get_knowledge(*, request: Request,
                  name: str = None,
                  page_size: Optional[int] = 10,
                  page_num: Optional[int] = 1):
    """ 读取所有知识库信息. """
    login_user = get_default_operator()
    res, total = KnowledgeService.get_knowledge(request, login_user, name, page_num, page_size)
    return resp_200(data={
        'data': res,
        'total': total
    })


@router.delete('/{knowledge_id}', status_code=200)
def delete_knowledge_api(*, request: Request,
                         knowledge_id: int):
    """ 删除知识库信息. """
    login_user = get_default_operator()
    KnowledgeService.delete_knowledge(request, login_user, knowledge_id)
    return resp_200(message='knowledge deleted successfully')


# 清空知识库的所有文件内容
@router.delete('/clear/{knowledge_id}', status_code=200)
def clear_knowledge_files(*, request: Request,
                          knowledge_id: int):
    """ 清空知识库的内容. """
    login_user = get_default_operator()
    KnowledgeService.delete_knowledge(request, login_user, knowledge_id, only_clear=True)
    return resp_200(message='knowledge clear successfully')


@router.post('/file/{knowledge_id}',
             response_model=UnifiedResponseModel[KnowledgeFileRead],
             status_code=200)
async def upload_file(request: Request,
                      knowledge_id: int,
                      separator: Optional[List[str]] = Form(default=None, description="切分文本规则, 不传则为默认"),
                      separator_rule: Optional[List[str]] = Form(default=None,
                                                                 description="切分规则前还是后进行切分；before/after"),
                      chunk_size: Optional[int] = Form(default=None, description="切分文本长度，不传则为默认"),
                      chunk_overlap: Optional[int] = Form(default=None, description="切分文本重叠长度，不传则为默认"),
                      callback_url: Optional[str] = Form(default=None, description="回调地址"),
                      file: UploadFile = File(...),
                      background_tasks: BackgroundTasks = None):
    file_name = file.filename
    if not file_name:
        return resp_500(message='file name must be not empty')
    # 缓存本地
    file_byte = await file.read()
    file_path = save_download_file(file_byte, 'bisheng', file_name)

    loging_user = get_default_operator()
    req_data = KnowledgeFileProcess(
        knowledge_id=knowledge_id,
        separator=separator,
        separator_rule=separator_rule,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        callback_url=callback_url,
        file_list=[KnowledgeFileOne(file_path=file_path)]
    )
    res = KnowledgeService.process_knowledge_file(request=request, login_user=loging_user,
                                                  background_tasks=background_tasks, req_data=req_data)
    return resp_200(data=res[0])


@router.delete('/file/{file_id}', status_code=200)
def delete_knowledge_file(request: Request, file_id: int):
    """ 删除知识库中的文件 """
    login_user = get_default_operator()
    KnowledgeService.delete_knowledge_file(request, login_user, [file_id])
    return resp_200()


@router.post('/delete_file', status_code=200)
def delete_file_batch_api(request: Request, file_ids: List[int]):
    """ 批量删除知识文件信息 """
    login_user = get_default_operator()
    KnowledgeService.delete_knowledge_file(request, login_user, file_ids)
    return resp_200()


@router.get('/file/list', status_code=200)
def get_filelist(request: Request,
                 knowledge_id: int,
                 keyword: str = None,
                 status: Optional[int] = None,
                 page_size: int = 10,
                 page_num: int = 1):
    """ 获取知识库文件信息. """
    login_user = get_default_operator()
    data, total, flag = KnowledgeService.get_knowledge_files(request, login_user, knowledge_id, keyword, status,
                                                             page_num, page_size)
    return resp_200(data={
        'data': data,
        'total': total,
        'writeable': flag
    })


@router.post('/chunks', response_model=UnifiedResponseModel[KnowledgeFileRead], status_code=200)
async def post_chunks(request: Request,
                      knowledge_id: int = Form(...),
                      metadata: str = Form(...),
                      separator: Optional[List[str]] = Form(default=None),
                      separator_rule: Optional[List[str]] = Form(default=None),
                      chunk_size: Optional[int] = Form(default=None),
                      chunk_overlap: Optional[int] = Form(default=None),
                      file: UploadFile = File(...)):
    """ 上传文件到知识库内，同步接口 """
    file_name = file.filename
    if not file_name:
        return resp_500(message='file name must be not empty')
    file_byte = await file.read()
    file_path = save_download_file(file_byte, 'bisheng', file_name)

    login_user = get_default_operator()

    req_data = KnowledgeFileProcess(
        knowledge_id=knowledge_id,
        separator=separator,
        separator_rule=separator_rule,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        file_list=[KnowledgeFileOne(file_path=file_path)],
        extra=metadata
    )

    res = KnowledgeService.sync_process_knowledge_file(request, login_user, req_data)
    return resp_200(data=res[0])


@router.post('/chunks_string',
             response_model=UnifiedResponseModel[KnowledgeFileRead],
             status_code=200)
async def post_string_chunks(request: Request, document: ChunkInput):
    """ 获取知识库文件信息. """

    # 字符串存入到文件中
    content = '\n\n'.join([doc.page_content for doc in document.documents])
    content_bytes = bytes(content, encoding='utf-8')
    file_name = document.documents[0].metadata.get('source')
    file_path = save_download_file(content_bytes, 'bisheng', file_name)

    login_user = get_default_operator()

    req_data = KnowledgeFileProcess(
        knowledge_id=document.knowledge_id,
        separator=["\n\n"],
        separator_rule=["after"],
        file_list=[KnowledgeFileOne(file_path=file_path)],
        extra=json.dumps(document.documents[0].metadata, ensure_ascii=False)
    )

    knowledge, failed_files, process_files, _ = KnowledgeService.save_knowledge_file(login_user,
                                                                                     req_data)
    if failed_files:
        return resp_200(data=failed_files[0])

    res = text_knowledge(knowledge, process_files[0], document.documents)

    return resp_200(data=res)


@router.post('/chunk_clear', status_code=200)
async def clear_tmp_chunks_data(body: Dict):
    # 通过接口删除milvus、es 数据
    flow_id = body.get('flow_id')
    chat_id = body.get('chat_id')

    if flow_id and not chat_id:
        # 清理技能下的临时文件
        flow_id = flow_id.replace('-', '')
        collection_name = f'tmp_{flow_id}_1'
        delete_es(collection_name)
        delete_vector(collection_name, None)
    if chat_id:
        #  查询自动生成的
        message = ChatMessageDao.get_latest_message_by_chatid(chat_id)
        if message:
            collection_name = f'tmp_{message.flow_id.hex}_{chat_id}'
            delete_es(collection_name)
            delete_vector(collection_name, None)

    return resp_200()


@router.get('/dump_vector', status_code=200)
def dump_vector_knowledge(collection_name: str, expr: str = None, store: str = 'Milvus'):
    # dump vector db
    embedding_tmp = FakeEmbedding()
    vector_store = decide_vectorstores(collection_name, store, embedding_tmp)

    if vector_store and vector_store.col:
        fields = [
            s.name for s in vector_store.col.schema.fields
            if s.name not in ['pk', 'bbox', 'vector']
        ]
        res_list = vector_store.col.query('file_id>1', output_fields=fields)
        return resp_200(res_list)
    else:
        return resp_500('参数错误')


@router.get('/download_statistic')
def download_statistic_file(file_path: str):
    file_name = os.path.basename(file_path)
    return FileResponse(file_path, filename=file_name)
