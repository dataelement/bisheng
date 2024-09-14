import urllib.parse
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, Request, Body, Query

from bisheng.api.services.knowledge import KnowledgeService
from bisheng.api.services.knowledge_imp import retry_files
from bisheng.api.services.user_service import UserPayload, get_login_user
from bisheng.api.v1.schemas import UnifiedResponseModel, UploadFileResponse, resp_200, resp_500, PreviewFileChunk, \
    UpdatePreviewFileChunk, KnowledgeFileProcess
from bisheng.cache.utils import save_uploaded_file
from bisheng.database.models.knowledge import KnowledgeCreate, KnowledgeRead, KnowledgeUpdate, KnowledgeDao
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
        logger.exception(f'Error saving file: {exc}')
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post('/preview')
async def preview_file_chunk(*, request: Request, login_user: UserPayload = Depends(get_login_user),
                             req_data: PreviewFileChunk):
    """ 获取某个文件的分块预览内容 """
    try:
        parse_type, file_share_url, res, partitions = KnowledgeService.get_preview_file_chunk(request, login_user,
                                                                                              req_data)
        return resp_200(data={
            "parse_type": parse_type,
            "file_url": file_share_url,
            "chunks": res,
            "partitions": partitions
        })
    except Exception as e:
        logger.exception('preview_file_chunk_error')
        return resp_500(data=str(e))


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


@router.put('/', status_code=200)
async def update_knowledge(*, request: Request, login_user: UserPayload = Depends(get_login_user),
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
    data, total, flag = KnowledgeService.get_knowledge_files(request, login_user, knowledge_id, file_name, status,
                                                             page_num, page_size)

    return resp_200({
        'data': data,
        'total': total,
        'writeable': flag,
    })


@router.post('/retry', status_code=200)
def retry(*, request: Request, login_user: UserPayload = Depends(get_login_user),
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
async def get_knowledge_chunk(request: Request, login_user: UserPayload = Depends(get_login_user),
                              knowledge_id: int = Query(..., description='知识库ID'),
                              file_ids: List[int] = Query(default=[], description='文件ID'),
                              keyword: str = Query(default='', description='关键字'),
                              page: int = Query(default=1, description='页数'),
                              limit: int = Query(default=10, description='每页条数条数')):
    """ 获取知识库分块内容 """
    # 为了解决keyword参数有时候没有进行urldecode的bug
    if keyword.startswith("%"):
        keyword = urllib.parse.unquote(keyword)
    res, total = KnowledgeService.get_knowledge_chunks(request, login_user, knowledge_id, file_ids, keyword, page,
                                                       limit)
    return resp_200(data={
        "data": res,
        "total": total
    })


@router.put('/chunk', status_code=200)
async def update_knowledge_chunk(request: Request, login_user: UserPayload = Depends(get_login_user),
                                 knowledge_id: int = Body(..., embed=True, description='知识库ID'),
                                 file_id: int = Body(..., embed=True, description='文件ID'),
                                 chunk_index: int = Body(..., embed=True, description='分块索引号'),
                                 text: str = Body(..., embed=True, description='分块内容'),
                                 bbox: str = Body(default='', embed=True, description='分块框选位置')):
    """ 更新知识库分块内容 """
    KnowledgeService.update_knowledge_chunk(request, login_user, knowledge_id, file_id, chunk_index, text, bbox)
    return resp_200()


@router.delete('/chunk', status_code=200)
async def delete_knowledge_chunk(request: Request, login_user: UserPayload = Depends(get_login_user),
                                 knowledge_id: int = Body(..., embed=True, description='知识库ID'),
                                 file_id: int = Body(..., embed=True, description='文件ID'),
                                 chunk_index: int = Body(..., embed=True, description='分块索引号')):
    """ 删除知识库分块内容 """
    KnowledgeService.delete_knowledge_chunk(request, login_user, knowledge_id, file_id, chunk_index)
    return resp_200()


@router.get('/file_share')
async def get_file_share_url(request: Request, login_user: UserPayload = Depends(get_login_user),
                             file_id: int = Query(description='文件唯一ID')):
    url = KnowledgeService.get_file_share_url(request, login_user, file_id)
    return resp_200(data=url)


@router.get('/file_bbox')
async def get_file_bbox(request: Request, login_user: UserPayload = Depends(get_login_user),
                        file_id: int = Query(description='文件唯一ID')):
    res = KnowledgeService.get_file_bbox(request, login_user, file_id)
    return resp_200(data=res)
