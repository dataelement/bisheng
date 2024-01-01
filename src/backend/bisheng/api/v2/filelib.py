import time
from typing import Optional
from uuid import uuid4

from bisheng.api.v1.knowledge import (addEmbedding, decide_embeddings, decide_vectorstores,
                                      file_knowledge, text_knowledge)
from bisheng.api.v1.schemas import ChunkInput
from bisheng.cache.utils import save_download_file
from bisheng.database.base import get_session
from bisheng.database.models.knowledge import (Knowledge, KnowledgeCreate, KnowledgeRead,
                                               KnowledgeUpdate)
from bisheng.database.models.knowledge_file import KnowledgeFile
from bisheng.database.models.role_access import AccessType, RoleAccess
from bisheng.database.models.user import User
from bisheng.settings import settings
from bisheng.utils import minio_client
from bisheng.utils.logger import logger
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.encoders import jsonable_encoder
from langchain.vectorstores import Milvus
from sqlalchemy import func, or_
from sqlmodel import Session, select

# build router
router = APIRouter(prefix='/filelib')


@router.post('/', response_model=KnowledgeRead, status_code=201)
def create_knowledge(
        *,
        session: Session = Depends(get_session),
        knowledge: KnowledgeCreate,
):
    """创建知识库."""
    db_knowldge = Knowledge.from_orm(knowledge)
    know = session.exec(
        select(Knowledge).where(
            Knowledge.name == knowledge.name,
            knowledge.user_id == settings.get_from_db('default_operator').get('user'))).all()
    if know:
        raise HTTPException(status_code=500, detail='知识库名称重复')
    if not db_knowldge.collection_name:
        # 默认collectionName
        db_knowldge.collection_name = f'col_{int(time.time())}_{str(uuid4())[:8]}'
    db_knowldge.user_id = settings.get_from_db('default_operator').get('user')
    session.add(db_knowldge)
    session.commit()
    session.refresh(db_knowldge)
    return db_knowldge


@router.put('/', response_model=KnowledgeRead, status_code=201)
def update_knowledge(
        *,
        session: Session = Depends(get_session),
        knowledge: KnowledgeUpdate,
):
    """创建知识库."""

    db_knowldge = session.get(Knowledge, knowledge.id)
    if not db_knowldge:
        raise HTTPException(status_code=500, detail='无知识库')

    know = session.exec(
        select(Knowledge).where(
            Knowledge.name == knowledge.name,
            knowledge.user_id == settings.get_from_db('default_operator').get('user'))).all()
    if know:
        raise HTTPException(status_code=500, detail='知识库名称重复')

    db_knowldge.name = knowledge.name
    session.add(db_knowldge)
    session.commit()
    session.refresh(db_knowldge)
    return db_knowldge


@router.get('/', status_code=200)
def get_knowledge(
        *,
        session: Session = Depends(get_session),
        page_size: Optional[int],
        page_num: Optional[str],
):
    """ 读取所有知识库信息. """
    default_user_id = settings.get_from_db('default_operator').get('user')
    try:
        sql = select(Knowledge)
        count_sql = select(func.count(Knowledge.id))
        if True:
            role_third_id = session.exec(select(RoleAccess).where(RoleAccess.role_id.in_(
                [1]))).all()
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
        total_count = session.scalar(count_sql)

        if page_num and page_size and page_num != 'undefined':
            page_num = int(page_num)
            sql = sql.offset((page_num - 1) * page_size).limit(page_size)

        knowledges = session.exec(sql).all()
        res = [jsonable_encoder(flow) for flow in knowledges]
        if knowledges:
            db_user_ids = {flow.user_id for flow in knowledges}
            db_user = session.exec(select(User).where(User.user_id.in_(db_user_ids))).all()
            userMap = {user.user_id: user.user_name for user in db_user}
            for r in res:
                r['user_name'] = userMap[r['user_id']]
        return {'data': res, 'total': total_count}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete('/{knowledge_id}', status_code=200)
def delete_knowledge(
        *,
        session: Session = Depends(get_session),
        knowledge_id: int,
):
    """ 删除知识库信息. """
    knowledge = session.get(Knowledge, knowledge_id)
    if not knowledge:
        raise HTTPException(status_code=404, detail='knowledge not found')

    session.delete(knowledge)
    session.commit()
    return {'message': 'knowledge deleted successfully'}


@router.post('/file/{knowledge_id}', status_code=200)
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
    session = next(get_session())
    knowledge = session.get(Knowledge, knowledge_id)

    collection_name = knowledge.collection_name

    md5_ = file_path.rsplit('/', 1)[1].split('.')[0].split('_')[0]
    db_file = KnowledgeFile(knowledge_id=knowledge_id,
                            file_name=file_name,
                            status=1,
                            md5=md5_,
                            user_id=1)
    session.add(db_file)
    session.commit()
    session.refresh(db_file)

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
        session.delete(db_file)
        session.commit()
        raise HTTPException(status_code=500, detail=db_file.remark)
    knowledge.update_time = db_file.create_time
    session.add(knowledge)
    session.commit()
    session.refresh(db_file)
    return {'status_code': 200, 'message': 'success', 'data': jsonable_encoder(db_file)}


@router.delete('/file/{file_id}', status_code=200)
def delete_knowledge_file(
        *,
        session: Session = Depends(get_session),
        file_id: int,
):
    """ 删除知识文件信息 """
    knowledge_file = session.get(KnowledgeFile, file_id)
    if not knowledge_file:
        raise HTTPException(status_code=404, detail='文件不存在')

    knowledge = session.get(Knowledge, knowledge_file.knowledge_id)

    # 处理vectordb
    collection_name = knowledge.collection_name
    embeddings = decide_embeddings(knowledge.model)
    vectore_client = decide_vectorstores(collection_name, 'Milvus', embeddings)
    if isinstance(vectore_client, Milvus) and vectore_client.col:
        pk = vectore_client.col.query(expr=f'file_id == {file_id}', output_fields=['pk'])
        res = vectore_client.col.delete(f"pk in {[p['pk'] for p in pk]}")
        logger.info(f'act=delete_vector file_id={file_id} res={res}')

    # minio
    minio_client.MinioClient().delete_minio(str(knowledge_file.id))
    # elastic
    esvectore_client = decide_vectorstores(collection_name, 'ElasticKeywordsSearch', embeddings)
    if esvectore_client:
        esvectore_client.client.delete_by_query(index=collection_name,
                                                query={'match': {
                                                    'metadata.file_id': file_id
                                                }})
        logger.info(f'act=delete_es file_id={file_id} res={res}')

    session.delete(knowledge_file)
    session.commit()
    return {'message': 'knowledge file deleted successfully'}


@router.get('/file/{knowledge_id}', status_code=200)
def get_filelist(
    *,
    session: Session = Depends(get_session),
    knowledge_id: int,
    page_size: int = 10,
    page_num: int = 1,
):
    """ 获取知识库文件信息. """

    # 查询当前知识库，是否有写入权限

    db_knowledge = session.get(Knowledge, knowledge_id)
    if not db_knowledge:
        raise HTTPException(status_code=500, detail='当前知识库不可用，返回上级目录')

    writable = True

    # 查找上传的文件信息
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


@router.post('/chunks', status_code=200)
async def post_chunks(
        *,
        knowledge_id: int = Form(...),
        metadata: str = Form(...),
        file: UploadFile = File(...),
        session: Session = Depends(get_session),
):
    """ 获取知识库文件信息. """
    file_name = file.filename
    file_byte = await file.read()
    file_path = save_download_file(file_byte, 'bisheng', file_name)

    db_knowledge = session.get(Knowledge, knowledge_id)
    if not db_knowledge:
        raise HTTPException(status_code=500, detail='当前知识库不可用，返回上级目录')

    file_knowledge(db_knowledge, file_path, file_name, metadata, session)

    return {'status_code': 200, 'message': 'success'}


@router.post('/chunks_string', status_code=200)
async def post_string_chunks(
        *,
        document: ChunkInput,
        session: Session = Depends(get_session),
):
    """ 获取知识库文件信息. """
    db_knowledge = session.get(Knowledge, document.knowledge_id)
    if not db_knowledge:
        raise HTTPException(status_code=500, detail='当前知识库不可用，返回上级目录')

    text_knowledge(db_knowledge, document.documents, session)

    return {'status_code': 200, 'message': 'success'}
