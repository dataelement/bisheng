import re
import time
from uuid import uuid4

from bisheng.database.base import session_getter
from bisheng.database.models.knowledge import Knowledge, KnowledgeCreate
from bisheng.settings import settings
from fastapi import HTTPException
from sqlmodel import select


def create_knowledge(knowledge: KnowledgeCreate, user_id: int):
    """ 创建知识库. """
    knowledge.is_partition = knowledge.is_partition or settings.get_knowledge().get(
        'vectorstores', {}).get('Milvus', {}).get('is_partition', True)
    db_knowldge = Knowledge.model_validate(knowledge)
    with session_getter() as session:
        know = session.exec(
            select(Knowledge).where(Knowledge.name == knowledge.name,
                                    knowledge.user_id == user_id)).all()
    if know:
        raise HTTPException(status_code=500, detail='知识库名称重复')
    if not db_knowldge.collection_name:
        if knowledge.is_partition:
            embedding = re.sub(r'[^\w]', '_', knowledge.model)
            suffix_id = settings.get_knowledge().get('vectorstores').get('Milvus', {}).get(
                'partition_suffix', 1)
            db_knowldge.collection_name = f'partition_{embedding}_knowledge_{suffix_id}'
        else:
            # 默认collectionName
            db_knowldge.collection_name = f'col_{int(time.time())}_{str(uuid4())[:8]}'
    db_knowldge.index_name = f'col_{int(time.time())}_{str(uuid4())[:8]}'
    db_knowldge.user_id = user_id
    with session_getter() as session:
        session.add(db_knowldge)
        session.commit()
        session.refresh(db_knowldge)
        return db_knowldge.copy()
