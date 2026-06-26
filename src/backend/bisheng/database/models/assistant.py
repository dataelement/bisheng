from collections.abc import Sequence
from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, Column, DateTime, Integer, Text, and_, func, or_, text
from sqlmodel import Field, col, select

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_async_db_session, get_sync_db_session
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, JsonType
from bisheng.database.models.role_access import AccessType, RoleAccess
from bisheng.utils import generate_uuid


class AssistantStatus(Enum):
    OFFLINE = 1
    ONLINE = 2


class AssistantBase(SQLModelSerializable):
    id: str | None = Field(
        default_factory=generate_uuid, nullable=False, primary_key=True, description="Uniqueness quantificationID"
    )
    name: str = Field(default="", description="The assistant name.")
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=False, server_default=text("1"), index=True, comment="Tenant ID"),
    )
    logo: str = Field(default="", description="logoimage URL")
    desc: str = Field(default="", sa_column=Column(Text), description="Assistant description")
    system_prompt: str = Field(default="", sa_column=Column(Text), description="System Prompt")
    prompt: str = Field(default="", sa_column=Column(Text), description="User Visible Descriptor")
    guide_word: str | None = Field(default="", sa_column=Column(Text), description="Ice Breaker ")
    guide_question: list | None = Field(
        default_factory=list, sa_column=Column(JsonType), description="Facilitation Questions"
    )
    model_name: str = Field(default="", description="Corresponds to the only model in the model managementID")
    temperature: float = Field(default=1, description="Model Temperature")
    max_token: int = Field(default=32000, description="MaxtokenQuantity")
    status: int = Field(default=AssistantStatus.OFFLINE.value, description="Whether the assistant is online")
    user_id: int = Field(default=0, description="Create UserID")
    is_delete: int = Field(default=0, description="Remove logo")
    is_shared: bool = Field(
        default=False,
        sa_column=Column(
            Boolean,
            nullable=False,
            server_default=text("0"),
            comment="F017: Root resource shared to all children (mirrors FGA shared_with tuples)",
        ),
    )
    create_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, index=True, server_default=text("CURRENT_TIMESTAMP"))
    )
    update_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT)
    )


class AssistantLinkBase(SQLModelSerializable):
    id: int | None = Field(default=None, nullable=False, primary_key=True, description="Uniqueness quantificationID")
    assistant_id: str | None = Field(default=0, index=True, description="assistantID")
    tool_id: int | None = Field(default=0, index=True, description="ToolsID")
    flow_id: str | None = Field(default="", index=True, description="SkillID")
    knowledge_id: int | None = Field(default=0, index=True, description="The knowledge base uponID")
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=False, server_default=text("1"), index=True, comment="Tenant ID"),
    )
    create_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, index=True, server_default=text("CURRENT_TIMESTAMP"))
    )
    update_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT)
    )


class Assistant(AssistantBase, table=True):
    id: str = Field(default_factory=generate_uuid, primary_key=True, unique=True)


class AssistantLink(AssistantLinkBase, table=True):
    pass


class AssistantDao(AssistantBase):
    @classmethod
    def create_assistant(cls, data: Assistant) -> Assistant:
        with get_sync_db_session() as session:
            session.add(data)
            session.commit()
            session.refresh(data)
            return data

    @classmethod
    def update_assistant(cls, data: Assistant) -> Assistant:
        with get_sync_db_session() as session:
            session.add(data)
            session.commit()
            session.refresh(data)
            return data

    @classmethod
    def delete_assistant(cls, data: Assistant) -> Assistant:
        with get_sync_db_session() as session:
            data.is_delete = 1
            session.add(data)
            session.commit()
            session.refresh(data)
            return data

    @classmethod
    def get_one_assistant(cls, assistant_id: str) -> Assistant:
        with get_sync_db_session() as session:
            statement = select(Assistant).where(Assistant.id == assistant_id)
            return session.exec(statement).first()

    @classmethod
    async def aget_one_assistant(cls, assistant_id: str) -> Assistant:
        statement = select(Assistant).where(Assistant.id == assistant_id)
        async with get_async_db_session() as session:
            return (await session.exec(statement)).first()

    @classmethod
    def get_assistants_by_ids(cls, assistant_ids: list[str]) -> list[Assistant]:
        if not assistant_ids:
            return []
        with get_sync_db_session() as session:
            statement = select(Assistant).where(Assistant.id.in_(assistant_ids))
            return session.exec(statement).all()

    @classmethod
    async def aget_assistants_by_ids(cls, assistant_ids: list[str]) -> list[Assistant]:
        if not assistant_ids:
            return []
        statement = select(Assistant).where(col(Assistant.id).in_(assistant_ids))
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    def get_assistant_by_name_user_id(cls, name: str, user_id: int) -> Assistant:
        with get_sync_db_session() as session:
            statement = select(Assistant).filter(
                Assistant.name == name, Assistant.user_id == user_id, Assistant.is_delete == 0
            )
            return session.exec(statement).first()

    @classmethod
    def get_assistants(
        cls,
        user_id: int,
        name: str,
        assistant_ids_extra: list[str],
        status: int | None,
        page: int,
        limit: int,
        assistant_ids: list[str] = None,
    ) -> (list[Assistant], int):
        with get_sync_db_session() as session:
            count_statement = session.query(func.count(Assistant.id)).where(Assistant.is_delete == 0)
            statement = select(Assistant).where(Assistant.is_delete == 0)
            if assistant_ids_extra:
                # Membutuhkanor Requirements to join
                statement = statement.where(or_(Assistant.id.in_(assistant_ids_extra), Assistant.user_id == user_id))
                count_statement = count_statement.where(
                    or_(Assistant.id.in_(assistant_ids_extra), Assistant.user_id == user_id)
                )
            else:
                statement = statement.where(Assistant.user_id == user_id)
                count_statement = count_statement.where(Assistant.user_id == user_id)

            if assistant_ids:
                statement = statement.where(Assistant.id.in_(assistant_ids))
                count_statement = count_statement.where(Assistant.id.in_(assistant_ids))

            if name:
                statement = statement.where(or_(Assistant.name.like(f"%{name}%"), Assistant.desc.like(f"%{name}%")))
                count_statement = count_statement.where(
                    or_(Assistant.name.like(f"%{name}%"), Assistant.desc.like(f"%{name}%"))
                )
            if status is not None:
                statement = statement.where(Assistant.status == status)
                count_statement = count_statement.where(Assistant.status == status)
            if limit == 0 and page == 0:
                # Get all, no pagination
                statement = statement.order_by(Assistant.update_time.desc())
            else:
                statement = statement.offset((page - 1) * limit).limit(limit).order_by(Assistant.update_time.desc())
            return session.exec(statement).all(), session.exec(count_statement).scalar()

    @classmethod
    def get_all_online_assistants(cls, flow_ids: list[str]) -> list[Assistant]:
        """Get all live assistants"""
        statement = select(Assistant).filter(Assistant.status == AssistantStatus.ONLINE.value, Assistant.is_delete == 0)
        if flow_ids:
            statement = statement.where(Assistant.flow_id.in_(flow_ids))
        statement = statement.order_by(Assistant.update_time.desc())
        with get_sync_db_session() as session:
            return session.exec(statement).all()

    @classmethod
    def get_all_assistants(
        cls, name: str, page: int, limit: int, assistant_ids: list[str] = None, status: int = None
    ) -> (list[Assistant], int):
        with get_sync_db_session() as session:
            statement = select(Assistant).where(Assistant.is_delete == 0)
            count_statement = session.query(func.count(Assistant.id)).where(Assistant.is_delete == 0)
            if name:
                statement = statement.where(or_(Assistant.name.like(f"%{name}%"), Assistant.desc.like(f"%{name}%")))
                count_statement = count_statement.where(
                    or_(Assistant.name.like(f"%{name}%"), Assistant.desc.like(f"%{name}%"))
                )
            if assistant_ids:
                statement = statement.where(Assistant.id.in_(assistant_ids))
                count_statement = count_statement.where(Assistant.id.in_(assistant_ids))
            if status is not None:
                statement = statement.where(Assistant.status == status)
                count_statement = count_statement.where(Assistant.status == status)
            if page and limit:
                statement = statement.offset((page - 1) * limit).limit(limit)
            statement = statement.order_by(Assistant.update_time.desc())
            return session.exec(statement).all(), session.exec(count_statement).scalar()

    @classmethod
    async def aget_all_assistants_cursor(
        cls,
        name: str,
        status: int | None,
        assistant_ids: list[str] | None,
        cursor: Sequence | None,
        limit: int,
    ) -> tuple[list["Assistant"], bool]:
        """F040/F027: keyset-paginated assistant listing for the cursor list API.

        Mirrors ``FlowDao.aget_all_apps``'s keyset contract: no ``count`` side
        query (INV-6 — list APIs drop ``total``); ``has_more`` is detected by
        fetching ``limit + 1`` rows and trimming. Sort order is
        ``(update_time DESC, id DESC)`` so ``cursor=(update_time, id)`` from the
        previous page's last row continues strictly after it.

        ``assistant_ids`` semantics match ``get_all_assistants``: ``None`` means
        no id prefilter; an empty list means "no candidates" → empty page.
        """
        if assistant_ids is not None and not assistant_ids:
            return [], False

        statement = select(Assistant).where(Assistant.is_delete == 0)
        if name:
            statement = statement.where(
                or_(
                    Assistant.name.like(f"%{name}%"),
                    Assistant.desc.like(f"%{name}%"),
                )
            )
        if assistant_ids is not None:
            statement = statement.where(Assistant.id.in_(assistant_ids))
        if status is not None:
            statement = statement.where(Assistant.status == status)

        if cursor is not None:
            from bisheng.database.utils.keyset import build_keyset_where

            statement = statement.where(
                build_keyset_where(
                    (Assistant.update_time, Assistant.id),
                    tuple(cursor),
                    descending=True,
                )
            )

        statement = statement.order_by(Assistant.update_time.desc(), Assistant.id.desc())
        fetch_limit = (limit + 1) if limit else 0
        if fetch_limit:
            statement = statement.limit(fetch_limit)

        async with get_async_db_session() as session:
            ret = (await session.exec(statement)).all()

        has_more = bool(limit) and len(ret) > limit
        if has_more:
            ret = ret[:limit]
        return list(ret), has_more

    @classmethod
    def get_assistants_by_access(
        cls, role_id: int, name: str, page_size: int, page_num: int
    ) -> list[tuple[Assistant, RoleAccess]]:
        statment = (
            select(Assistant, RoleAccess)
            .join(
                RoleAccess,
                and_(
                    RoleAccess.role_id == role_id,
                    RoleAccess.type == AccessType.ASSISTANT_READ.value,
                    RoleAccess.third_id == Assistant.id,
                ),
                isouter=True,
            )
            .where(Assistant.is_delete == 0)
        )

        if name:
            statment = statment.where(Assistant.name.like("%" + name + "%"))
        if page_num and page_size and page_num != "undefined":
            page_num = int(page_num)
            statment = (
                statment.order_by(RoleAccess.type.desc())
                .order_by(Assistant.update_time.desc())
                .offset((page_num - 1) * page_size)
                .limit(page_size)
            )
        with get_sync_db_session() as session:
            return session.exec(statment).all()

    @classmethod
    def get_count_by_filters(cls, filters: list) -> int:
        with get_sync_db_session() as session:
            count_statement = session.query(func.count(Assistant.id))
            filters.append(Assistant.is_delete == 0)
            return session.exec(count_statement.where(*filters)).scalar()

    @classmethod
    def filter_assistant_by_id(
        cls, assistant_ids: list[str], keywords: str = None, page: int = 0, limit: int = 0
    ) -> (list[Assistant], int):
        """
        Based on keywords and assistantsidFilter out corresponding assistants
        """
        statement = select(Assistant).where(Assistant.is_delete == 0)
        count_statement = select(func.count(Assistant.id)).where(Assistant.is_delete == 0)
        if assistant_ids:
            statement = statement.where(Assistant.id.in_(assistant_ids))
            count_statement = count_statement.where(Assistant.id.in_(assistant_ids))
        if keywords:
            statement = statement.where(or_(Assistant.name.like(f"%{keywords}%"), Assistant.desc.like(f"%{keywords}%")))
            count_statement = count_statement.where(
                or_(Assistant.name.like(f"%{keywords}%"), Assistant.desc.like(f"%{keywords}%"))
            )
        if page and limit:
            statement = statement.offset((page - 1) * limit).limit(limit)
        statement = statement.order_by(Assistant.update_time.desc())

        with get_sync_db_session() as session:
            result = session.exec(statement).all()
            return result, session.scalar(count_statement)


class AssistantLinkDao(AssistantLink):
    @classmethod
    def insert_batch(cls, assistant_id: str, tool_list: list[int] = None, flow_list: list[str] = None):
        if not tool_list and not flow_list:
            return []
        with get_sync_db_session() as session:
            if tool_list:
                for one in tool_list:
                    if one == 0:
                        continue
                    session.add(AssistantLink(assistant_id=assistant_id, tool_id=one))
            if flow_list:
                for one in flow_list:
                    if not one:
                        continue
                    session.add(AssistantLink(assistant_id=assistant_id, flow_id=one))
            session.commit()

    @classmethod
    async def get_assistant_link(cls, assistant_id: str) -> list[AssistantLink]:
        async with get_async_db_session() as session:
            statement = select(AssistantLink).where(AssistantLink.assistant_id == assistant_id)
            result = await session.exec(statement)
            return result.all()

    @classmethod
    def update_assistant_tool(cls, assistant_id: str, tool_list: list[int]):
        with get_sync_db_session() as session:
            session.query(AssistantLink).filter(
                AssistantLink.assistant_id == assistant_id, AssistantLink.tool_id != 0
            ).delete()
            for one in tool_list:
                if one == 0:
                    continue
                session.add(AssistantLink(assistant_id=assistant_id, tool_id=one))
            session.commit()

    @classmethod
    def update_assistant_flow(cls, assistant_id: str, flow_list: list[str]):
        with get_sync_db_session() as session:
            session.query(AssistantLink).filter(
                AssistantLink.assistant_id == assistant_id, AssistantLink.flow_id != "", AssistantLink.knowledge_id == 0
            ).delete()
            for one in flow_list:
                if not one:
                    continue
                session.add(AssistantLink(assistant_id=assistant_id, flow_id=one))
            session.commit()

    @classmethod
    def update_assistant_knowledge(cls, assistant_id: str, knowledge_list: list[int], flow_id: str):
        # Must have skills when saving knowledge base associationsID
        with get_sync_db_session() as session:
            session.query(AssistantLink).filter(
                AssistantLink.assistant_id == assistant_id, AssistantLink.knowledge_id != 0
            ).delete()
            for one in knowledge_list:
                if one == 0:
                    continue
                session.add(AssistantLink(assistant_id=assistant_id, knowledge_id=one, flow_id=flow_id))
            session.commit()
