import hashlib
from typing import List, Optional

from bisheng.api.services.knowledge_imp import (addEmbedding, create_knowledge, delete_knowledge_by,
                                                delete_knowledge_file_batch, text_knowledge)
from bisheng.api.v1.schemas import ChunkInput, UnifiedResponseModel, resp_200, resp_500
from bisheng.cache.utils import save_download_file
from bisheng.database.base import session_getter
from bisheng.database.models.knowledge import (Knowledge, KnowledgeCreate, KnowledgeRead,
                                               KnowledgeUpdate)
from bisheng.database.models.knowledge_file import KnowledgeFile, KnowledgeFileRead
from bisheng.database.models.role_access import AccessType, RoleAccess
from bisheng.database.models.user import User
from bisheng.settings import settings
from bisheng.utils.logger import logger
from bisheng.utils.minio_client import MinioClient
from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, or_
from sqlmodel import select

# build router
router = APIRouter(prefix='/filelib')


@router.post('/', response_model=KnowledgeRead, status_code=201)
def creat(knowledge: KnowledgeCreate):
    """创建知识库."""
    user_id = knowledge.user_id or settings.get_from_db('default_operator').get('user')
    db_knowldge = create_knowledge(knowledge, user_id)
    return db_knowldge


@router.put('/', response_model=KnowledgeRead, status_code=201)
def update_knowledge(*, knowledge: KnowledgeUpdate):
    """创建知识库."""
    with session_getter() as session:
        db_knowldge = session.get(Knowledge, knowledge.id)
    if not db_knowldge:
        raise HTTPException(status_code=500, detail='无知识库')

    with session_getter() as session:
        know = session.exec(
            select(Knowledge).where(
                Knowledge.name == knowledge.name,
                knowledge.user_id == settings.get_from_db('default_operator').get('user'))).all()
    if know:
        raise HTTPException(status_code=500, detail='知识库名称重复')

    db_knowldge.name = knowledge.name

    with session_getter() as session:
        session.add(db_knowldge)
        session.commit()
        session.refresh(db_knowldge)
    return db_knowldge


@router.get('/', status_code=200)
def get_knowledge(*, page_size: Optional[int], page_num: Optional[str]):
    """ 读取所有知识库信息. """
    default_user_id = settings.get_from_db('default_operator').get('user')
    try:
        sql = select(Knowledge)
        count_sql = select(func.count(Knowledge.id))
        if True:
            with session_getter() as session:
                role_third_id = session.exec(
                    select(RoleAccess).where(RoleAccess.role_id.in_([1]))).all()
            if role_third_id:
                third_ids = [
                    acess.third_id for acess in role_third_id
                    if acess.type == AccessType.KNOWLEDGE.value
                ]
                sql = sql.where(
                    or_(Knowledge.user_id == default_user_id, Knowledge.id.in_(third_ids)))
                count_sql = count_sql.where(
                    or_(Knowledge.user_id == default_user_id, Knowledge.id.in_(third_ids)))
            else:
                sql = sql.where(Knowledge.user_id == default_user_id)
                count_sql = count_sql.where(Knowledge.user_id == default_user_id)
        sql = sql.order_by(Knowledge.update_time.desc())

        # get total count
        with session_getter() as session:
            total_count = session.scalar(count_sql)

        if page_num and page_size and page_num != 'undefined':
            page_num = int(page_num)
            sql = sql.offset((page_num - 1) * page_size).limit(page_size)

        with session_getter() as session:
            knowledges = session.exec(sql).all()
        res = [jsonable_encoder(flow) for flow in knowledges]
        if knowledges:
            db_user_ids = {flow.user_id for flow in knowledges}
            with session_getter() as session:
                db_user = session.exec(select(User).where(User.user_id.in_(db_user_ids))).all()
            userMap = {user.user_id: user.user_name for user in db_user}
            for r in res:
                r['user_name'] = userMap[r['user_id']]
        return {'data': res, 'total': total_count}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete('/{knowledge_id}', status_code=200)
def delete_knowledge_api(*, knowledge_id: int):
    """ 删除知识库信息. """
    with session_getter() as session:
        knowledge = session.get(Knowledge, knowledge_id)
    if not knowledge:
        raise HTTPException(status_code=404, detail='knowledge not found')
    try:
        delete_knowledge_by(knowledge)
        return {'message': 'knowledge deleted successfully'}
    except Exception as e:
        logger.exception(e)
        return resp_500(message=f'错误 e={str(e)}')


@router.post('/file/{knowledge_id}',
             response_model=UnifiedResponseModel[KnowledgeFileRead],
             status_code=200)
async def upload_file(*,
                      knowledge_id: int,
                      callback_url: Optional[str] = Form(None),
                      file: UploadFile = File(...),
                      background_tasks: BackgroundTasks):

    file_name = file.filename
    # 缓存本地
    file_byte = await file.read()
    file_path = save_download_file(file_byte, 'bisheng', file_name)
    auto_p = True
    if auto_p:
        separator = ['\n\n', '\n', ' ', '']
        chunk_size = 500
        chunk_overlap = 50
    with session_getter() as session:
        knowledge = session.get(Knowledge, knowledge_id)

    collection_name = knowledge.collection_name

    md5_ = file_path.rsplit('/', 1)[1].split('.')[0].split('_')[0]
    db_file = KnowledgeFile(knowledge_id=knowledge_id,
                            file_name=file_name,
                            status=1,
                            md5=md5_,
                            user_id=1)
    with session_getter() as session:
        session.add(db_file)
        session.commit()
        session.refresh(db_file)
    db_file = db_file.copy()
    logger.info(f'fileName={file_name} col={collection_name} file_id={db_file.id}')
    try:
        index_name = knowledge.index_name or knowledge.collection_name
        background_tasks.add_task(addEmbedding,
                                  collection_name=collection_name,
                                  index_name=index_name,
                                  knowledge_id=knowledge_id,
                                  model=knowledge.model,
                                  chunk_size=chunk_size,
                                  separator=separator,
                                  chunk_overlap=chunk_overlap,
                                  file_paths=[file_path],
                                  knowledge_files=[db_file],
                                  callback=callback_url)
    except Exception:
        # 失败，需要删除数据
        logger.info(f'delete file_id={db_file.id} status={db_file.status} reason={db_file.remark}')
        with session_getter() as session:
            session.delete(db_file)
            session.commit()
        raise HTTPException(status_code=500, detail=db_file.remark)
    knowledge.update_time = db_file.create_time
    with session_getter() as session:
        session.add(knowledge)
        session.commit()
    return resp_200(db_file)


@router.delete('/file/{file_id}', status_code=200)
def delete_knowledge_file(*, file_id: int):
    """ 删除知识文件信息 """
    with session_getter() as session:
        knowledge_file = session.get(KnowledgeFile, file_id)
    if not knowledge_file:
        raise HTTPException(status_code=404, detail='文件不存在')

    try:
        delete_knowledge_file_batch([file_id])
        return resp_200()
    except Exception as e:
        return resp_500(message=f'error e={str(e)}')


@router.post('/delete_file', status_code=200)
def delete_file_batch_api(file_ids: List[int]):
    """ 批量删除知识文件信息 """
    with session_getter() as session:
        knowledge_file = session.exec(select(KnowledgeFile).where(KnowledgeFile.id.in_(file_ids)))
    if not knowledge_file:
        raise HTTPException(status_code=404, detail='文件不存在')

    try:
        delete_knowledge_file_batch(file_ids)
        return resp_200()
    except Exception as e:
        return resp_500(message=f'error e={str(e)}')


@router.get('/file/{knowledge_id}', status_code=200)
def get_filelist(*, knowledge_id: int, page_size: int = 10, page_num: int = 1):
    """ 获取知识库文件信息. """

    # 查询当前知识库，是否有写入权限
    with session_getter() as session:
        db_knowledge = session.get(Knowledge, knowledge_id)
    if not db_knowledge:
        raise HTTPException(status_code=500, detail='当前知识库不可用，返回上级目录')

    writable = True

    # 查找上传的文件信息
    with session_getter() as session:
        total_count = session.scalar(
            select(func.count(KnowledgeFile.id)).where(KnowledgeFile.knowledge_id == knowledge_id))
        files = session.exec(
            select(KnowledgeFile).where(KnowledgeFile.knowledge_id == knowledge_id).order_by(
                KnowledgeFile.update_time.desc()).offset(page_size *
                                                         (page_num - 1)).limit(page_size)).all()
    return {
        'data': [jsonable_encoder(knowledgefile) for knowledgefile in files],
        'total': total_count,
        'writeable': writable
    }


@router.post('/chunks', response_model=UnifiedResponseModel[KnowledgeFileRead], status_code=200)
async def post_chunks(*,
                      knowledge_id: int = Form(...),
                      metadata: str = Form(...),
                      file: UploadFile = File(...)):
    """ 获取知识库文件信息. """
    file_name = file.filename
    file_byte = await file.read()
    file_path = save_download_file(file_byte, 'bisheng', file_name)
    with session_getter() as session:
        db_knowledge = session.get(Knowledge, knowledge_id)
    if not db_knowledge:
        raise HTTPException(status_code=404, detail='当前知识库不可用，返回上级目录')

    # 重复判断
    md5_ = file_path.rsplit('/', 1)[1].split('.')[0]
    with session_getter() as session:
        repeat = session.exec(
            select(KnowledgeFile).where(KnowledgeFile.md5 == md5_,
                                        KnowledgeFile.knowledge_id == knowledge_id)).all()
    if repeat:
        return resp_500(code=422, message='文件重复')

    # 存储 mysql
    db_file = KnowledgeFile(knowledge_id=db_knowledge.id,
                            file_name=file_name,
                            md5=md5_,
                            extra_meta=metadata,
                            status=1)

    with session_getter() as session:
        session.add(db_file)
        session.commit()
        session.refresh(db_file)

    separator = ['\n\n', '\n', ' ', '']
    chunk_size = 500
    chunk_overlap = 50
    index_name = db_knowledge.index_name or db_knowledge.collection_name
    try:
        minio_client = MinioClient()
        db_file.object_name = 'original/' + str(db_file.id) + '.' + file_name.rsplit('.', 1)[-1]
        minio_client.upload_minio(db_file.object_name, file_path)
        with session_getter() as session:
            session.add(db_file)
            session.commit()
            session.refresh(db_file)
    except Exception as e:
        logger.exception(e)
        return resp_500(code=400, data=db_file, message='文件上传失败')
    try:
        addEmbedding(db_knowledge.collection_name, index_name, db_knowledge.id, db_knowledge.model,
                     chunk_size, separator, chunk_overlap, [file_path], [db_file], None, metadata)
    except Exception as e:
        logger.error(e)
        return resp_500(code=500, data=db_file, message='文件解析失败')

    with session_getter() as session:
        db_file = session.get(KnowledgeFile, db_file.id)

    if db_file.status == 3:
        return resp_500(data=db_file, message='文件解析失败')
    return resp_200(db_file)


@router.post('/chunks_string',
             response_model=UnifiedResponseModel[KnowledgeFileRead],
             status_code=200)
async def post_string_chunks(*, document: ChunkInput):
    """ 获取知识库文件信息. """
    with session_getter() as session:
        db_knowledge = session.get(Knowledge, document.knowledge_id)
    if not db_knowledge:
        raise HTTPException(status_code=500, detail='当前知识库不可用，返回上级目录')

    m = hashlib.md5()
    # 对字符串进行md5加密
    content = '\n\n'.join([doc.page_content for doc in document.documents])
    m.update(content.encode('utf-8'))
    md5_ = m.hexdigest()
    with session_getter() as session:
        repeat = session.exec(
            select(KnowledgeFile).where(
                KnowledgeFile.md5 == md5_,
                KnowledgeFile.knowledge_id == document.knowledge_id)).all()

    status = 3 if repeat else 1
    remark = 'file repeat' if repeat else ''

    if repeat:
        logger.info('upload_string_repeat md5={} history={}', md5_, repeat[0].id)
        return resp_500(code=422, message='文件重复')

    db_file = KnowledgeFile(knowledge_id=document.knowledge_id,
                            status=status,
                            md5=md5_,
                            extra_meta=document.documents[0].metadata,
                            remark=remark)
    with session_getter() as session:
        session.add(db_file)
        session.commit()
        session.refresh(db_file)

    # 将文本保存为文件
    minio_client = MinioClient()
    db_file.object_name = 'original/' + str(db_file.id) + '.txt'
    try:
        content_byte = bytes(content, encoding='utf-8')
        logger.info('content_byte={}', content_byte)
        minio_client.upload_minio_data(db_file.object_name, content_byte, len(content_byte),
                                       'application/octet-stream')
        with session_getter() as session:
            session.add(db_file)
            session.commit()
            session.refresh(db_file)
    except Exception as e:
        logger.exception(e)
        return resp_500(code=400, data=db_file, message='文件上传失败')

    db_file = text_knowledge(db_knowledge, db_file, document.documents)
    if db_file['status'] == 3:
        return resp_500(data=db_file, message='文件解析失败')
    return resp_200(db_file)
