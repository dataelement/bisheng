from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, Request, Path

from bisheng.api.services.knowledge import KnowledgeService
from bisheng.api.services.knowledge_imp import retry_files
from bisheng.api.services.user_service import UserPayload, get_login_user
from bisheng.api.v1.schemas import UnifiedResponseModel, UploadFileResponse, resp_200, resp_500, PreviewFileChunk, \
    UpdatePreviewFileChunk, KnowledgeFileProcess
from bisheng.cache.utils import save_uploaded_file
from bisheng.database.models.knowledge import KnowledgeCreate, KnowledgeRead
from bisheng.database.models.knowledge_file import KnowledgeFile, KnowledgeFileDao
from bisheng.utils.logger import logger

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
        logger.error(f'Error saving file: {exc}')
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post('/preview')
async def preview_file_chunk(*, request: Request, login_user: UserPayload = Depends(get_login_user),
                             req_data: PreviewFileChunk):
    """ 获取某个文件的分块预览内容 """
    try:
        res = KnowledgeService.get_preview_file_chunk(request, login_user, req_data)
        return resp_200(res)
    except Exception as e:
        logger.exception('preview_file_chunk_error')
        return resp_500(data = str(e))


@router.put('/preview')
async def update_preview_file_chunk(*, request: Request, login_user: UserPayload = Depends(get_login_user),
                                    req_data: UpdatePreviewFileChunk):
    """ 更新某个文件的分块预览内容 """

    res = KnowledgeService.update_preview_file_chunk(request, login_user, req_data)
    return resp_200(res)


@router.delete('/preview')
async def delete_preview_file_chunk(*, request: Request, login_user: UserPayload = Depends(get_login_user),
                                    req_data: UpdatePreviewFileChunk):
    """ 删除某个文件的分块预览内容 """

    res = KnowledgeService.delete_preview_file_chunk(request, login_user, req_data)
    return resp_200(res)


@router.post('/process')
async def process_knowledge_file(*, request: Request, login_user: UserPayload = Depends(get_login_user),
                                 background_tasks: BackgroundTasks, req_data: KnowledgeFileProcess):
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


@router.get('/', status_code=200)
def get_knowledge(*,
                  request: Request,
                  login_user: UserPayload = Depends(get_login_user),
                  name: str = None,
                  page_size: Optional[int] = 10,
                  page_num: Optional[int] = 1):
    """ 读取所有知识库信息. """
    res, total = KnowledgeService.get_knowledge(request, login_user, name, page_num, page_size)
    return resp_200(data={
        'data': res,
        'total': total
    })


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
    data, total, flag = KnowledgeService.get_knowledge_files(request, login_user, knowledge_id, file_name, status,
                                                             page_num, page_size)

    return resp_200({
        'data': data,
        'total': total,
        'writeable': flag,
    })


@router.post('/retry', status_code=200)
def retry(data: dict, background_tasks: BackgroundTasks, login_user: UserPayload = Depends(get_login_user)):
    """失败重试"""
    db_file_retry = data.get('file_objs')
    if db_file_retry:
        id2input = {file.get('id'): KnowledgeFile.validate(file) for file in db_file_retry}
    else:
        return resp_500('参数错误')
    file_ids = list(id2input.keys())
    db_files = KnowledgeFileDao.select_list(file_ids=file_ids)
    for file in db_files:
        # file exist
        input_file = id2input.get(file.id)
        if input_file.remark and '对应已存在文件' in input_file.remark:
            file.file_name = input_file.remark.split(' 对应已存在文件 ')[0]
            file.remark = ''
        file.status = 1  # 解析中
        file = KnowledgeFileDao.update(file)
    background_tasks.add_task(retry_files, db_files, id2input)
    return resp_200()


@router.delete('/{knowledge_id}', status_code=200)
def delete_knowledge(*,
                     request: Request,
                     login_user: UserPayload = Depends(get_login_user),
                     knowledge_id: int = Path(...)):
    """ 删除知识库信息. """

    KnowledgeService.delete_knowledge(request, login_user, knowledge_id)
    return resp_200(message='删除成功')


@router.delete('/file/{file_id}', status_code=200)
def delete_knowledge_file(*,
                          request: Request,
                          file_id: int,
                          login_user: UserPayload = Depends(get_login_user)):
    """ 删除知识文件信息 """

    KnowledgeService.delete_knowledge_file(request, login_user, file_id)

    return resp_200(message='删除成功')
