from datetime import datetime
from typing import Any, List, Optional, Tuple

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
from sqlalchemy import Column, DateTime, Text, and_, text, func
from sqlmodel import Field, select
from uuid import UUID


class EvaluationBase(SQLModelSerializable):
    user_id: int = Field(default=None, index=True)
    file_name: str = Field(default='', description='上传的文件名')
    file_path: str = Field(default='', description='文件 minio 地址')
    exec_type: str = Field(description='执行主体类别。助手还是技能 flow 和 assistant')
    unique_id: str = Field(index=True, description='助手或技能唯一ID')
    version: Optional[int] = Field(default=None, description='技能的版本ID')
    status: int = Field(index=True, default=1, description='任务执行状态。1:执行中 2: 执行失败 3:执行成功')
    prompt: str = Field(default='', sa_column=Column(Text), description='评测指令文本')
    result_file_path: str = Field(default='', description='评测结果的 minio 地址')
    result_score: str = Field(default='', description='最终评测分数')
    is_delete: int = Field(default=0, description='是否删除')
    create_time: Optional[datetime] = Field(
        sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=True,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))


class Evaluation(EvaluationBase, table=True):
    id: int = Field(default=None, primary_key=True, unique=True)


class EvaluationRead(EvaluationBase):
    id: int
    user_name: Optional[str]


class EvaluationCreate(EvaluationBase):
    pass


# class EvaluationDao(EvaluationBase):
#     @classmethod
#     def query_by_id(cls, id: int) -> Evaluation:
#         with session_getter() as session:
#             return session.get(Evaluation, id)


class EvaluationDao(EvaluationBase):

    # @classmethod
    # def create_assistant(cls, data: Assistant) -> Assistant:
    #     with session_getter() as session:
    #         session.add(data)
    #         session.commit()
    #         session.refresh(data)
    #         return data

    # @classmethod
    # def update_assistant(cls, data: Assistant) -> Assistant:
    #     with session_getter() as session:
    #         session.add(data)
    #         session.commit()
    #         session.refresh(data)
    #         return data
    #
    # @classmethod
    # def delete_assistant(cls, data: Assistant) -> Assistant:
    #     with session_getter() as session:
    #         data.is_delete = 1
    #         session.add(data)
    #         session.commit()
    #         return data

    # @classmethod
    # def get_one_assistant(cls, assistant_id: UUID) -> Assistant:
    #     with session_getter() as session:
    #         statement = select(Assistant).where(Assistant.id == assistant_id)
    #         return session.exec(statement).first()
    #
    # @classmethod
    # def get_assistants_by_ids(cls, assistant_ids: List[UUID]) -> List[Assistant]:
    #     with session_getter() as session:
    #         statement = select(Assistant).where(Assistant.id.in_(assistant_ids))
    #         return session.exec(statement).all()
    #
    # @classmethod
    # def get_assistant_by_name_user_id(cls, name: str, user_id: int) -> Assistant:
    #     with session_getter() as session:
    #         statement = select(Assistant).filter(Assistant.name == name,
    #                                              Assistant.user_id == user_id,
    #                                              Assistant.is_delete == 0)
    #         return session.exec(statement).first()
    #
    # @classmethod
    # def get_assistants(cls, user_id: int, name: str, assistant_ids: List[UUID],
    #                    status: Optional[int], page: int, limit: int) -> (List[Assistant], int):
    #     with session_getter() as session:
    #         count_statement = session.query(func.count(
    #             Assistant.id)).where(Assistant.is_delete == 0)
    #         statement = select(Assistant).where(Assistant.is_delete == 0)
    #         if assistant_ids:
    #             # 需要or 加入的条件
    #             statement = statement.where(
    #                 or_(Assistant.id.in_(assistant_ids), Assistant.user_id == user_id))
    #             count_statement = count_statement.where(
    #                 or_(Assistant.id.in_(assistant_ids), Assistant.user_id == user_id))
    #         else:
    #             statement = statement.where(Assistant.user_id == user_id)
    #             count_statement = count_statement.where(Assistant.user_id == user_id)
    #
    #         if name:
    #             statement = statement.where(or_(
    #                 Assistant.name.like(f'%{name}%'),
    #                 Assistant.desc.like(f'%{name}%')
    #             ))
    #             count_statement = count_statement.where(or_(
    #                 Assistant.name.like(f'%{name}%'),
    #                 Assistant.desc.like(f'%{name}%')
    #             ))
    #         if status is not None:
    #             statement = statement.where(Assistant.status == status)
    #             count_statement = count_statement.where(Assistant.status == status)
    #         if limit == 0 and page == 0:
    #             # 获取全部，不分页
    #             statement = statement.order_by(Assistant.update_time.desc())
    #         else:
    #             statement = statement.offset(
    #                 (page - 1) * limit).limit(limit).order_by(Assistant.update_time.desc())
    #         return session.exec(statement).all(), session.exec(count_statement).scalar()
    #
    # @classmethod
    # def get_all_online_assistants(cls) -> List[Assistant]:
    #     """ 获取所有已上线的助手 """
    #     with session_getter() as session:
    #         statement = select(Assistant).filter(Assistant.status == AssistantStatus.ONLINE.value,
    #                                              Assistant.is_delete == 0)
    #         return session.exec(statement).all()

    @classmethod
    def get_all_evaluations(cls, page: int, limit: int) -> (List[Evaluation], int):
        with session_getter() as session:
            statement = select(Evaluation).where(Evaluation.is_delete == 0)
            count_statement = session.query(func.count(
                Evaluation.id)).where(Evaluation.is_delete == 0)
            statement = statement.offset(
                (page - 1) * limit
            ).limit(limit).order_by(
                Evaluation.update_time.desc()
            )
            return session.exec(statement).all(), session.exec(count_statement).scalar()

    # @classmethod
    # def get_assistants_by_access(cls, role_id: int, name: str, page_size: int,
    #                              page_num: int) -> List[Tuple[Assistant, RoleAccess]]:
    #     statment = select(Assistant,
    #                       RoleAccess).join(RoleAccess,
    #                                        and_(RoleAccess.role_id == role_id,
    #                                             RoleAccess.type == AccessType.ASSISTANT_READ.value,
    #                                             RoleAccess.third_id == Assistant.id),
    #                                        isouter=True).where(Assistant.is_delete == 0)
    #
    #     if name:
    #         statment = statment.where(Assistant.name.like('%' + name + '%'))
    #     if page_num and page_size and page_num != 'undefined':
    #         page_num = int(page_num)
    #         statment = statment.order_by(RoleAccess.type.desc()).order_by(
    #             Assistant.update_time.desc()).offset((page_num - 1) * page_size).limit(page_size)
    #     with session_getter() as session:
    #         return session.exec(statment).all()
    #
    # @classmethod
    # def get_count_by_filters(cls, filters: List) -> int:
    #     with session_getter() as session:
    #         count_statement = session.query(func.count(Assistant.id))
    #         filters.append(Assistant.is_delete == 0)
    #         return session.exec(count_statement.where(*filters)).scalar()
