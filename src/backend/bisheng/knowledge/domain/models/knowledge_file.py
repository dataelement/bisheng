import json
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any, Literal

# if TYPE_CHECKING:
from pydantic import field_validator
from sqlalchemy import JSON, Column, DateTime, String, or_, text, Text
from sqlmodel import Field, delete, func, select, update, col

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_async_db_session, get_sync_db_session
from bisheng.database.base import async_get_count, get_count


class KnowledgeFileStatus(Enum):
    PROCESSING = 1  # Sedang diproses
    SUCCESS = 2  # Berhasil
    FAILED = 3  # Parse Failure
    REBUILDING = 4  # Rebuilding
    WAITING = 5  # In queue:
    TIMEOUT = 6  # Super24Hour not parsed, parsing timeout


class QAStatus(Enum):
    DISABLED = 0  # User manually closedQA
    ENABLED = 1  # Enabled
    PROCESSING = 2  # Sedang diproses
    FAILED = 3  # QAFailed to insert vector library


class ParseType(Enum):
    LOCAL = 'local'  # Local mode resolution
    UNS = 'uns'  # unsService resolution, all converted topdfDoc.

    # 1.3.0After the enumeration, the previous belongs to the file parsed on the version
    ETL4LM = 'etl4lm'  # etl4lmService Insights, includingpdfLayout Analysis for
    UN_ETL4LM = 'un_etl4lm'  # Nonetl4lmService parsing, nobboxContent, only source files andmdDoc.


class KnowledgeFileBase(SQLModelSerializable):
    user_id: Optional[int] = Field(default=None, index=True)
    user_name: Optional[str] = Field(default=None, index=True)
    knowledge_id: int = Field(index=True)
    file_name: str = Field(max_length=200, index=True)
    file_size: Optional[int] = Field(default=None, index=False, description='File size inbytes')
    md5: Optional[str] = Field(default=None, index=False)
    parse_type: Optional[str] = Field(default=ParseType.LOCAL.value,
                                      index=False,
                                      description='Files parsed in what mode')
    split_rule: Optional[str] = Field(default=None, sa_column=Column(Text), description='Files parsed in what mode')
    bbox_object_name: Optional[str] = Field(default='', description='bboxFiles inminioStored object name')
    status: Optional[int] = Field(default=KnowledgeFileStatus.WAITING.value,
                                  index=False,
                                  description='1: Parsing;2: Resolved successfully;3: Parse Failure')
    object_name: Optional[str] = Field(default=None, index=False, description='Files inminioStored object name')
    user_metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, sa_column=Column(JSON, nullable=True),
                                                    description='User-defined metadata')
    remark: Optional[str] = Field(default='', sa_column=Column(String(length=4096)))
    updater_id: Optional[int] = Field(default=None, index=True, description='Last updated by userID')
    updater_name: Optional[str] = Field(default=None, index=True)
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class QAKnowledgeBase(SQLModelSerializable):
    user_id: Optional[int] = Field(default=None, index=True)
    knowledge_id: int = Field(index=True)
    questions: List[str] = Field(index=False)
    answers: str = Field(index=False)
    source: Optional[int] = Field(default=0, index=False, description='0: Unknown 1: Manual2: Audit, 3: api, 4: Batch import')
    status: Optional[int] = Field(default=1, index=False,
                                  description='1: Activate0: Close, the user manually closes;2: Sedang diproses3Failed to insert')
    extra_meta: Optional[str] = Field(default=None, index=False)
    remark: Optional[str] = Field(default='', sa_column=Column(String(length=4096)))
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))

    @field_validator('questions')
    @classmethod
    def validate_json(cls, v):
        # dict_keys(['description', 'name', 'id', 'data'])
        if not v:
            return v
        if not isinstance(v, List):
            raise ValueError('question must be a valid JSON')

        return v

    @field_validator('answers')
    @classmethod
    def validate_answer(cls, v):
        # dict_keys(['description', 'name', 'id', 'data'])
        if not v:
            return v
        if isinstance(v, List):
            return json.dumps(v, ensure_ascii=False)

        return v


class KnowledgeFile(KnowledgeFileBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)


class QAKnowledge(QAKnowledgeBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    questions: Optional[List[str]] = Field(default=None, sa_column=Column(JSON))
    answers: Optional[str] = Field(default=None, sa_column=Column(Text))


class KnowledgeFileRead(KnowledgeFileBase):
    id: int


class KnowledgeFileCreate(KnowledgeFileBase):
    pass


class QAKnowledgeUpsert(QAKnowledgeBase):
    """Support modification"""
    id: Optional[int] = None
    answers: Optional[List[str] | str] = None


class KnowledgeFileDao(KnowledgeFileBase):

    @classmethod
    async def query_by_id(cls, file_id: int) -> Optional[KnowledgeFile]:
        async with get_async_db_session() as session:
            result = await session.execute(select(KnowledgeFile).where(KnowledgeFile.id == file_id))
            return result.scalars().first()

    @classmethod
    def query_by_id_sync(cls, file_id: int) -> Optional[KnowledgeFile]:
        with get_sync_db_session() as session:
            return session.exec(select(KnowledgeFile).where(KnowledgeFile.id == file_id)).first()

    @classmethod
    def get_file_simple_by_knowledge_id(cls, knowledge_id: int, page: int, page_size: int):
        offset = (page - 1) * page_size
        with get_sync_db_session() as session:
            return session.query(KnowledgeFile.id, KnowledgeFile.object_name).filter(
                KnowledgeFile.knowledge_id == knowledge_id).order_by(
                KnowledgeFile.id.asc()).offset(offset).limit(page_size).all()

    @classmethod
    def count_file_by_knowledge_id(cls, knowledge_id: int):
        with get_sync_db_session() as session:
            return session.query(func.count(
                KnowledgeFile.id)).filter(KnowledgeFile.knowledge_id == knowledge_id).scalar()

    @classmethod
    def delete_batch(cls, file_ids: List[int]) -> bool:
        with get_sync_db_session() as session:
            session.exec(delete(KnowledgeFile).where(KnowledgeFile.id.in_(file_ids)))
            session.commit()
            return True

    @classmethod
    def add_file(cls, knowledge_file: KnowledgeFile) -> KnowledgeFile:
        with get_sync_db_session() as session:
            session.add(knowledge_file)
            session.commit()
            session.refresh(knowledge_file)
        return knowledge_file

    @classmethod
    def update(cls, knowledge_file):
        with get_sync_db_session() as session:
            session.add(knowledge_file)
            session.commit()
            session.refresh(knowledge_file)
        return knowledge_file

    @classmethod
    async def async_update(cls, knowledge_file):
        async with get_async_db_session() as session:
            session.add(knowledge_file)
            await session.commit()
            await session.refresh(knowledge_file)
        return knowledge_file

    @classmethod
    def update_file_status(cls, file_ids: list[int], status: KnowledgeFileStatus, reason: str = None):
        """ Batch update file status """
        statement = update(KnowledgeFile).where(KnowledgeFile.id.in_(file_ids)).values(status=status.value,
                                                                                       remark=reason)
        with get_sync_db_session() as session:
            session.exec(statement)
            session.commit()

    @classmethod
    def get_file_by_condition(cls, knowledge_id: int, md5_: str = None, file_name: str = None):
        with get_sync_db_session() as session:
            sql = select(KnowledgeFile).where(KnowledgeFile.knowledge_id == knowledge_id)
            if md5_:
                sql = sql.where(KnowledgeFile.md5 == md5_)
            if file_name:
                sql = sql.where(KnowledgeFile.file_name == file_name)
            return session.exec(sql).all()

    @classmethod
    async def get_repeat_file(cls, knowledge_id: int, md5_: str = None, file_name: str = None):
        sql = select(KnowledgeFile).where(KnowledgeFile.knowledge_id == knowledge_id)
        if md5_ and file_name:
            sql = sql.where(
                or_(
                    KnowledgeFile.md5 == md5_,
                    KnowledgeFile.file_name == file_name
                )
            )
        elif md5_:
            sql = sql.where(KnowledgeFile.md5 == md5_)
        elif file_name:
            sql = sql.where(KnowledgeFile.file_name == file_name)
        async with get_async_db_session() as session:
            result = await session.exec(sql)
            return result.first()

    @classmethod
    def select_list(cls, file_ids: List[int]):
        if not file_ids:
            return []
        with get_sync_db_session() as session:
            knowledge_files = session.exec(
                select(KnowledgeFile).where(KnowledgeFile.id.in_(file_ids))).all()
        if not knowledge_files:
            raise ValueError('Doc.IDDoes not exist')
        return knowledge_files

    @classmethod
    def get_file_by_ids(cls, file_ids: List[int]) -> List[KnowledgeFile]:
        if not file_ids:
            return []
        with get_sync_db_session() as session:
            return session.exec(select(KnowledgeFile).where(KnowledgeFile.id.in_(file_ids))).all()

    @classmethod
    def get_file_by_filters(cls,
                            knowledge_id: int,
                            file_name: str = None,
                            status: List[int] = None,
                            page: int = 0,
                            page_size: int = 0,
                            file_ids: List[int] = None) -> List[KnowledgeFile]:
        statement = select(KnowledgeFile).where(KnowledgeFile.knowledge_id == knowledge_id)
        if file_name:
            statement = statement.where(KnowledgeFile.file_name.like(f'%{file_name}%'))
        if status:
            statement = statement.where(KnowledgeFile.status.in_(status))
        if file_ids:
            statement = statement.where(KnowledgeFile.id.in_(file_ids))
        if page and page_size:
            statement = statement.offset((page - 1) * page_size).limit(page_size)
        statement = statement.order_by(KnowledgeFile.update_time.desc())
        with get_sync_db_session() as session:
            return session.exec(statement).all()

    @classmethod
    def get_files_by_multiple_status(cls, knowledge_id: int, status_list: List[int]) -> List[KnowledgeFile]:
        """
        Based on Knowledge BaseIDand status list query file
        
        Args:
            knowledge_id: The knowledge base uponID
            status_list: List of status values
            
        Returns:
            List[KnowledgeFile]: Matching Files List
        """
        statement = select(KnowledgeFile).where(
            KnowledgeFile.knowledge_id == knowledge_id,
            KnowledgeFile.status.in_(status_list)
        )

        with get_sync_db_session() as session:
            return session.exec(statement).all()

    @classmethod
    def count_file_by_filters(cls,
                              knowledge_id: int,
                              file_name: str = None,
                              status: List[int] = None,
                              file_ids: List[int] = None) -> int:
        statement = select(func.count(
            KnowledgeFile.id)).where(KnowledgeFile.knowledge_id == knowledge_id)
        if file_name:
            statement = statement.where(KnowledgeFile.file_name.like(f'%{file_name}%'))
        if status:
            statement = statement.where(KnowledgeFile.status.in_(status))
        if file_ids:
            statement = statement.where(KnowledgeFile.id.in_(file_ids))
        with get_sync_db_session() as session:
            return session.scalar(statement)

    @classmethod
    async def async_count_file_by_filters(cls,
                                          knowledge_id: int,
                                          file_name: str = None,
                                          status: List[int] = None,
                                          file_ids: List[int] = None) -> int:
        statement = select(func.count(
            KnowledgeFile.id)).where(KnowledgeFile.knowledge_id == knowledge_id)
        if file_name:
            statement = statement.where(KnowledgeFile.file_name.like(f'%{file_name}%'))
        if status:
            statement = statement.where(KnowledgeFile.status.in_(status))
        if file_ids:
            statement = statement.where(KnowledgeFile.id.in_(file_ids))
        async with get_async_db_session() as session:
            result = await session.execute(statement)
            return result.scalar_one()

    @classmethod
    def get_knowledge_ids_by_name(cls, file_name: str) -> List[int]:
        statement = select(KnowledgeFile.knowledge_id).where(KnowledgeFile.file_name.like(f'%{file_name}%')).group_by(
            KnowledgeFile.knowledge_id)
        with get_sync_db_session() as session:
            return session.exec(statement).all()

    @classmethod
    def update_status_bulk(cls, file_ids: List[int], status: KnowledgeFileStatus, remark: str = "") -> None:
        """
        Batch update file status

        Args:
            file_ids: Doc.IDVertical
            status: New status value

        Returns:
            None
        """
        if not file_ids:
            return

        statement = (
            update(KnowledgeFile)
            .where(col(KnowledgeFile.id).in_(file_ids))
        )

        statement = statement.values(status=status.value)

        if remark:
            statement = statement.values(remark=remark)

        with get_sync_db_session() as session:
            session.exec(statement)
            session.commit()

    @classmethod
    def filter_file_by_metadata_fields(cls, knowledge_id: int, logical: Literal["and", "or"],
                                       metadata_filters: List[Dict[str, Dict[str, Any]]]) -> List[int]:
        """
        Filter knowledge files based on user-defined metadata fields
        :param knowledge_id: The knowledge base uponID
        :param logical: Logical operators, supporting "AND" OR "OR"
        :param metadata_filters: User-defined metadata fields and their corresponding values
          [{
            field_a: {
                'comparison': '=',
                'value': 'some_value',
                'extra_filter': [
                    {
                        'comparison': '!=',
                        'value': 'other_value'
                    }
                ]
            }
          }]
        :return: Eligible Knowledge FilesIDVertical
        """

        statement = "select id from knowledgefile where knowledge_id = :knowledge_id and "
        params = {"knowledge_id": knowledge_id}

        params_index = 1
        field_statement = []
        for metadata_filter in metadata_filters:
            for key, key_info in metadata_filter.items():
                key_comparison = key_info['comparison']
                key_value = key_info['value']
                extra_filter = key_info.get('extra_filter')
                if key_value is not None:
                    params_key = f"tmp_params_{params_index}"
                    params[params_key] = key_value
                    sub_statement = f"{key} {key_comparison} :{params_key}"
                else:
                    sub_statement = f"{key} {key_comparison}"
                if extra_filter:
                    for sub_info in extra_filter:
                        params_index += 1
                        params_key = f"tmp_params_{params_index}"
                        params[params_key] = sub_info['value']
                        sub_statement += f" AND {key} {sub_info['comparison']} :{params_key}"
                    sub_statement = f"({sub_statement})"
                field_statement.append(sub_statement)
                params_index += 1
        field_statement = f" {logical} ".join(field_statement)
        statement += f"({field_statement})"

        with get_sync_db_session() as session:
            file_ids = []
            result = session.execute(text(statement), params)
            for one in result:
                file_ids.append(one[0])
            return file_ids

    @classmethod
    def update_file_updater(cls, file_id: int, updater_id: int, updater_name: str) -> None:
        """
        Update Knowledge File Updater Information
        :param file_id: Knowledge DocumentsID
        :param updater_id: User who updated  ID
        :param updater_name: Updated By Username
        :return: None
        """

        statement = update(KnowledgeFile).where(col(KnowledgeFile.id) == file_id)

        statement = statement.values(updater_id=updater_id, updater_name=updater_name)
        with get_sync_db_session() as session:
            session.exec(statement)
            session.commit()


class QAKnoweldgeDao(QAKnowledgeBase):

    @classmethod
    def get_qa_knowledge_by_knowledge_id(cls, knowledge_id: int, page: int, page_size: int):
        offset = (page - 1) * page_size
        state = select(QAKnowledge).where(
            QAKnowledge.knowledge_id == knowledge_id, ).offset(offset).limit(page_size)
        with get_sync_db_session() as session:
            return session.exec(state).all()

    @classmethod
    def get_qa_knowledge_by_knowledge_ids(cls, knowledge_ids: List[int]) -> List[QAKnowledge]:
        with get_sync_db_session() as session:
            return session.exec(
                select(QAKnowledge).where(QAKnowledge.knowledge_id.in_(knowledge_ids))).all()

    @classmethod
    async def aget_qa_knowledge_by_knowledge_ids(cls, knowledge_ids: List[int]) -> List[QAKnowledge]:
        async with get_async_db_session() as session:
            result = await session.exec(
                select(QAKnowledge).where(col(QAKnowledge.knowledge_id).in_(knowledge_ids)))
            return result.all()

    @classmethod
    def get_qa_knowledge_by_primary_id(cls, qa_id: int) -> QAKnowledge:
        with get_sync_db_session() as session:
            return session.exec(select(QAKnowledge).where(QAKnowledge.id == qa_id)).first()

    @classmethod
    def get_qa_knowledge_by_name(cls, question: List[str], knowledge_id: int, exclude_id: int = None) -> QAKnowledge:
        with get_sync_db_session() as session:
            group_filters = []
            for one in question:
                group_filters.append(func.json_contains(QAKnowledge.questions, json.dumps(one)))
            statement = select(QAKnowledge).where(
                or_(*group_filters)).where(QAKnowledge.knowledge_id == knowledge_id)
            if exclude_id:
                statement = statement.where(QAKnowledge.id != exclude_id)
            return session.exec(statement).first()

    @classmethod
    def update(cls, qa_knowledge: QAKnowledge):
        if qa_knowledge.id is None:
            raise ValueError('idTidak boleh kosong.')
        with get_sync_db_session() as session:
            session.add(qa_knowledge)
            session.commit()
            session.refresh(qa_knowledge)
        return qa_knowledge

    @classmethod
    def delete_batch(cls, qa_ids: List[int]) -> bool:
        with get_sync_db_session() as session:
            session.exec(delete(QAKnowledge).where(QAKnowledge.id.in_(qa_ids)))
            session.commit()
            return True

    @classmethod
    def select_list(cls, ids: List[int]) -> List[QAKnowledge]:
        with get_sync_db_session() as session:
            QAKnowledges = session.exec(select(QAKnowledge).where(QAKnowledge.id.in_(ids))).all()
        if not QAKnowledges:
            raise ValueError('Knowledge base does not exist')
        return QAKnowledges

    @classmethod
    def insert_qa(cls, qa_knowledge: QAKnowledgeUpsert):
        with get_sync_db_session() as session:
            qa = QAKnowledge.model_validate(qa_knowledge)
            session.add(qa)
            session.commit()
            session.refresh(qa)
        return qa

    @classmethod
    def batch_insert_qa(cls, qa_knowledges: List[QAKnowledgeUpsert]) -> List[QAKnowledge]:
        with get_sync_db_session() as session:
            qas = []
            for qa_knowledge in qa_knowledges:
                qa = QAKnowledge.model_validate(qa_knowledge)
                qas.append(qa)
            session.add_all(qas)
            session.commit()
            for qa in qas:
                session.refresh(qa)
            return qas

    @classmethod
    async def total_count(cls, sql):
        async with get_async_db_session() as session:
            return await async_get_count(session, sql)

    @classmethod
    async def query_by_condition(cls, sql):
        async with get_async_db_session() as session:
            result = await session.exec(sql)
            return result.all()

    @classmethod
    def query_by_condition_v1(cls, source: List[int], create_start: str, create_end: str):
        with get_sync_db_session() as session:
            sql = select(QAKnowledge).where(QAKnowledge.source.in_(source)).where(
                QAKnowledge.create_time.between(create_start, create_end))

            return session.exec(sql).all()

    # accordingqa_idTotal Fetched
    @classmethod
    async def async_count_by_id(cls, qa_id: int) -> int:
        async with get_async_db_session() as session:
            statement = select(func.count(QAKnowledge.id)).where(QAKnowledge.knowledge_id == qa_id)
            return await async_get_count(session, statement)

    @classmethod
    def count_by_id(cls, qa_id: int) -> int:
        with get_sync_db_session() as session:
            statement = select(func.count(QAKnowledge.id)).where(QAKnowledge.knowledge_id == qa_id)
            return get_count(session, statement)

    @classmethod
    def batch_update_status_by_ids(cls, qa_ids: List[int],
                                   status: QAStatus,
                                   remark: str = "") -> None:
        """
        accordingQAkey learning pointsIDBulk Update Status
        :param qa_ids: QAkey learning pointsIDVertical
        :param status: Status
        :param remark: Remark
        :return:
        """

        statement = (
            update(QAKnowledge).where(col(QAKnowledge.id).in_(qa_ids))
        )

        statement = statement.values(status=status.value).values(remark=remark)
        with get_sync_db_session() as session:
            session.exec(statement)
            session.commit()

    # according knowledge_id Update status
    @classmethod
    def update_status_by_knowledge_id(cls, knowledge_id: int, status: QAStatus, remark: str = "") -> None:
        """
        according knowledge_id Update status
        :param knowledge_id: The knowledge base uponID
        :param status: Status
        :param remark: Remark
        :return:
        """

        statement = (
            update(QAKnowledge).where(col(QAKnowledge.knowledge_id) == knowledge_id)
        )

        statement = statement.values(status=status.value).values(remark=remark)
        with get_sync_db_session() as session:
            session.exec(statement)
            session.commit()
