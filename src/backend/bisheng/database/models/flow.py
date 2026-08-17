# Path: src/backend/bisheng/database/models/flow.py

from collections.abc import Sequence
from datetime import datetime
from enum import Enum
from typing import Union

from pydantic import field_validator
from sqlalchemy import Boolean, Column, DateTime, Integer, String, and_, case, cast, false, func, null, or_, text
from sqlmodel import Field, col, select, update

from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum, BaseTelemetryTypeEnum
from bisheng.common.models.base import SQLModelSerializable
from bisheng.common.schemas.telemetry.event_data_schema import NewApplicationEventData
from bisheng.common.services import telemetry_service
from bisheng.core.database import get_async_db_session, get_sync_db_session
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, JsonType
from bisheng.core.database.tenant_filter import build_tenant_filter_clause
from bisheng.core.logger import trace_id_var
from bisheng.database.models.app import APP_STATE_DELETED, APP_STATE_ONLINE, App
from bisheng.database.models.assistant import Assistant
from bisheng.database.models.role_access import AccessType, RoleAccess
from bisheng.database.models.session import MessageSession
from bisheng.utils import generate_uuid

# if TYPE_CHECKING:


class FlowStatus(Enum):
    OFFLINE = 1
    ONLINE = 2


class FlowType(Enum):
    ASSISTANT = 5
    WORKFLOW = 10
    WORKSTATION = 15
    LINSIGHT = 20  # Inspiration Mode
    CHANNEL_ARTICLE = 25  # Channel Article AI Assistant
    KNOLEDGE_SPACE = 30
    # F054: hosted application. Only a *type tag* for the shared list pipeline —
    # the row lives in ``app``, not in ``flow`` (design D8). 35 is the next free
    # value; 5/10/15/20/25/30 are taken.
    HOSTED_APP = 35


class AppEnum(Enum):
    Flow = "flow"
    ASSISTANT = "assistant"
    WORKFLOW = "workflow"


class UserLinkType(Enum):
    app = AppEnum


class FlowBase(SQLModelSerializable):
    name: str = Field(index=True)
    user_id: int | None = Field(default=None, index=True)
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=False, server_default=text("1"), index=True, comment="Tenant ID"),
    )
    description: str | None = Field(default=None, sa_column=Column(String(length=1000)))
    data: dict | None = Field(default=None)
    logo: str | None = Field(default=None, index=False)
    status: int | None = Field(index=False, default=1)
    flow_type: int | None = Field(index=False, default=FlowType.WORKFLOW.value)
    is_shared: bool = Field(
        default=False,
        sa_column=Column(
            Boolean,
            nullable=False,
            server_default=text("0"),
            comment="F017: Root resource shared to all children (mirrors FGA shared_with tuples)",
        ),
    )
    guide_word: str | None = Field(default=None, sa_column=Column(String(length=1000)))
    create_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, index=True, server_default=text("CURRENT_TIMESTAMP"))
    )
    update_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT)
    )

    @field_validator("data", mode="before")
    @classmethod
    def validate_json(cls, v):
        if not v:
            return v
        if not isinstance(v, dict):
            raise ValueError("Flow must be a valid JSON")

        # data must contain nodes and edges
        if "nodes" not in v.keys():
            raise ValueError("Flow must have nodes")
        if "edges" not in v.keys():
            raise ValueError("Flow must have edges")

        return v


class Flow(FlowBase, table=True):
    id: str = Field(default_factory=generate_uuid, primary_key=True, unique=True)
    data: dict | None = Field(default=None, sa_column=Column(JsonType))


class FlowCreate(SQLModelSerializable):
    name: str = Field(index=True)
    user_id: int | None = Field(default=None, index=True)
    description: str | None = Field(default=None, sa_column=Column(String(length=1000)))
    data: dict | None = Field(default=None)
    logo: str | None = Field(default=None, index=False)
    status: int | None = Field(index=False, default=1)
    flow_type: int | None = Field(index=False, default=FlowType.WORKFLOW.value)
    is_shared: bool = Field(default=False)
    guide_word: str | None = Field(default=None, sa_column=Column(String(length=1000)))
    flow_id: str | None = None

    @field_validator("data", mode="before")
    @classmethod
    def validate_json(cls, v):
        if not v:
            return v
        if not isinstance(v, dict):
            raise ValueError("Flow must be a valid JSON")

        if "nodes" not in v.keys():
            raise ValueError("Flow must have nodes")
        if "edges" not in v.keys():
            raise ValueError("Flow must have edges")

        return v


class FlowRead(FlowBase):
    id: str
    user_name: str | None = None
    version_id: int | None = None


class FlowReadWithStyle(FlowRead):
    # style: Optional['FlowStyleRead'] = None
    total: int | None = None


class FlowUpdate(SQLModelSerializable):
    name: str | None = None
    logo: str | None = None
    description: str | None = None
    data: dict | None = None
    status: int | None = None
    guide_word: str | None = None


class FlowDao(FlowBase):
    @classmethod
    def create_flow(cls, flow_info: Flow, flow_type: int | None) -> Flow:
        from bisheng.database.models.flow_version import FlowVersion

        with get_sync_db_session() as session:
            session.add(flow_info)
            # Create a default version
            flow_version = FlowVersion(
                name="v0",
                is_current=1,
                data=flow_info.data,
                flow_id=flow_info.id,
                create_time=datetime.now(),
                user_id=flow_info.user_id,
                flow_type=flow_type,
            )
            session.add(flow_version)
            session.commit()
            session.refresh(flow_info)

            if flow_type == FlowType.WORKFLOW.value:
                app_type = ApplicationTypeEnum.WORKFLOW
            elif flow_type == FlowType.ASSISTANT.value:
                app_type = ApplicationTypeEnum.ASSISTANT
            elif flow_type == FlowType.LINSIGHT.value:
                app_type = ApplicationTypeEnum.LINSIGHT
            else:
                app_type = ApplicationTypeEnum.DAILY_CHAT

            # RecordTelemetryJournal
            telemetry_service.log_event_sync(
                user_id=flow_info.user_id,
                event_type=BaseTelemetryTypeEnum.NEW_APPLICATION,
                trace_id=trace_id_var.get(),
                event_data=NewApplicationEventData(app_id=flow_info.id, app_name=flow_info.name, app_type=app_type),
            )

            return flow_info

    @classmethod
    def delete_flow(cls, flow_info: Flow) -> Flow:
        from bisheng.database.models.flow_version import FlowVersion

        with get_sync_db_session() as session:
            session.delete(flow_info)
            # Delete the corresponding version information
            update_statement = update(FlowVersion).where(FlowVersion.flow_id == flow_info.id).values(is_delete=1)
            session.exec(update_statement)
            session.commit()
            return flow_info

    @classmethod
    def get_flow_by_id(cls, flow_id: str) -> Flow | None:
        with get_sync_db_session() as session:
            statement = select(Flow).where(Flow.id == flow_id)
            return session.exec(statement).first()

    @classmethod
    async def aget_flow_by_id(cls, flow_id: str) -> Flow | None:
        async with get_async_db_session() as session:
            statement = select(Flow).where(Flow.id == flow_id)
            result = await session.exec(statement)
            return result.first()

    @classmethod
    def get_flow_by_idstr(cls, flow_id: str) -> Flow | None:
        with get_sync_db_session() as session:
            statement = select(Flow).where(Flow.id == flow_id)
            return session.exec(statement).first()

    @classmethod
    def get_flow_by_ids(cls, flow_ids: list[str]) -> list[Flow]:
        if not flow_ids:
            return []
        with get_sync_db_session() as session:
            statement = select(Flow).where(Flow.id.in_(flow_ids))
            return session.exec(statement).all()

    @classmethod
    async def aget_flow_by_ids(cls, flow_ids: list[str]) -> list[Flow]:
        if not flow_ids:
            return []
        async with get_async_db_session() as session:
            statement = select(Flow).where(col(Flow.id).in_(flow_ids))
            result = await session.exec(statement)
            return result.all()

    @classmethod
    def get_flow_by_user(cls, user_id: int) -> list[Flow]:
        with get_sync_db_session() as session:
            statement = select(Flow).where(Flow.user_id == user_id)
            return session.exec(statement).all()

    @classmethod
    def get_flow_by_name(cls, user_id: int, name: str) -> Flow | None:
        with get_sync_db_session() as session:
            statement = select(Flow).where(Flow.user_id == user_id, Flow.name == name)
            return session.exec(statement).first()

    @classmethod
    def get_flow_list_by_name(cls, name: str) -> list[Flow]:
        with get_sync_db_session() as session:
            statement = select(Flow).where(Flow.name.like(f"%{name}%"))
            return session.exec(statement).all()

    @classmethod
    def get_flow_by_access(
        cls, role_id: int, name: str, page_size: int, page_num: int
    ) -> list[tuple[Flow, RoleAccess]]:
        statment = select(Flow, RoleAccess).join(
            RoleAccess,
            and_(
                RoleAccess.role_id == role_id,
                RoleAccess.type == AccessType.WORKFLOW.value,
                RoleAccess.third_id == Flow.id,
            ),
            isouter=True,
        )
        statment = statment.where(Flow.flow_type == FlowType.WORKFLOW.value)

        if name:
            statment = statment.where(Flow.name.like("%" + name + "%"))
        if page_num and page_size and page_num != "undefined":
            page_num = int(page_num)
            statment = (
                statment.order_by(RoleAccess.type.desc())
                .order_by(Flow.update_time.desc())
                .offset((page_num - 1) * page_size)
                .limit(page_size)
            )
        with get_sync_db_session() as session:
            return session.exec(statment).all()

    @classmethod
    def get_count_by_filters(cls, filters) -> int:
        with get_sync_db_session() as session:
            count_statement = session.query(func.count(Flow.id))
            return session.exec(count_statement.where(*filters)).scalar()

    @classmethod
    def get_flows(
        cls,
        user_id: int | None,
        extra_ids: Union[list[str], str],
        name: str,
        status: int | None = None,
        flow_ids: list[str] | None = None,
        page: int = 0,
        limit: int = 0,
        flow_type: int | None = None,
    ) -> list[Flow]:
        with get_sync_db_session() as session:
            # data The amount of data is too large, yesmysql Influential
            statement = select(
                Flow.id,
                Flow.user_id,
                Flow.name,
                Flow.status,
                Flow.create_time,
                Flow.logo,
                Flow.update_time,
                Flow.description,
                Flow.guide_word,
                Flow.flow_type,
            )
            if extra_ids and isinstance(extra_ids, list):
                statement = statement.where(or_(Flow.id.in_(extra_ids), Flow.user_id == user_id))
            elif not extra_ids:
                statement = statement.where(Flow.user_id == user_id)
            if name:
                statement = statement.where(or_(Flow.name.like(f"%{name}%"), Flow.description.like(f"%{name}%")))
            if status is not None:
                statement = statement.where(Flow.status == status)
            if flow_type is not None:
                statement = statement.where(Flow.flow_type == flow_type)
            if flow_ids:
                statement = statement.where(Flow.id.in_(flow_ids))
            statement = statement.order_by(Flow.update_time.desc())
            if page > 0 and limit > 0:
                statement = statement.offset((page - 1) * limit).limit(limit)
            flows = session.exec(statement)
            flows_partial = flows.mappings().all()
            return [Flow.model_validate(f) for f in flows_partial]

    @classmethod
    def count_flows(
        cls,
        user_id: int | None,
        extra_ids: Union[list[str], str],
        name: str,
        status: int | None = None,
        flow_ids: list[str] | None = None,
        flow_type: int | None = None,
    ) -> int:
        with get_sync_db_session() as session:
            count_statement = session.query(func.count(Flow.id))
            if extra_ids and isinstance(extra_ids, list):
                count_statement = count_statement.filter(or_(Flow.id.in_(extra_ids), Flow.user_id == user_id))
            elif not extra_ids:
                count_statement = count_statement.filter(Flow.user_id == user_id)
            if name:
                count_statement = count_statement.filter(
                    or_(Flow.name.like(f"%{name}%"), Flow.description.like(f"%{name}%"))
                )
            if flow_type is not None:
                count_statement = count_statement.where(Flow.flow_type == flow_type)
            if flow_ids:
                count_statement = count_statement.filter(Flow.id.in_(flow_ids))
            if status is not None:
                count_statement = count_statement.filter(Flow.status == status)
            return count_statement.scalar()

    @classmethod
    def filter_flows_by_ids(
        cls,
        flow_ids: list[str],
        keyword: str | None = None,
        page: int = 0,
        limit: int = 0,
        flow_type: int = FlowType.WORKFLOW.value,
    ) -> (list[Flow], int):
        """
        Filter flow records by ids and return brief information without graph data.
        """
        statement = select(
            Flow.id,
            Flow.user_id,
            Flow.name,
            Flow.status,
            Flow.create_time,
            Flow.update_time,
            Flow.description,
            Flow.guide_word,
        )
        count_statement = select(func.count(Flow.id))
        if flow_ids:
            statement = statement.where(Flow.id.in_(flow_ids))
            count_statement = count_statement.where(Flow.id.in_(flow_ids))
        if keyword:
            statement = statement.where(or_(Flow.name.like(f"%{keyword}%"), Flow.description.like(f"%{keyword}%")))
            count_statement = count_statement.where(
                or_(Flow.name.like(f"%{keyword}%"), Flow.description.like(f"%{keyword}%"))
            )
        if page and limit:
            statement = statement.offset((page - 1) * limit).limit(limit)
        statement = statement.where(Flow.flow_type == flow_type)
        statement = statement.order_by(Flow.update_time.desc())
        with get_sync_db_session() as session:
            result = session.exec(statement).mappings().all()
            return [Flow.model_validate(f) for f in result], session.scalar(count_statement)

    @classmethod
    def update_flow(cls, flow: Flow) -> Flow:
        with get_sync_db_session() as session:
            session.add(flow)
            session.commit()
            session.refresh(flow)
        return flow

    @classmethod
    async def aupdate_flow(cls, flow: Flow) -> Flow:
        async with get_async_db_session() as session:
            session.add(flow)
            await session.commit()
            await session.refresh(flow)
        return flow

    @classmethod
    def get_all_apps(
        cls,
        name: str | None = None,
        status: int | None = None,
        id_list: list | None = None,
        flow_type: int | None = None,
        user_id: int | None = None,
        id_extra: list | None = None,
        id_list_not_in: list | None = None,
        page: int = 0,
        limit: int = 0,
        search_description: bool = False,
        app_type_ids: dict[int, list[str]] | None = None,
        app_state: str | None = None,
    ) -> (list[dict], int):
        """Get all flow-based apps, assistants and hosted applications."""
        sub_query = cls._build_apps_subquery()

        statement = select(
            sub_query.c.id,
            sub_query.c.name,
            sub_query.c.description,
            sub_query.c.flow_type,
            sub_query.c.logo,
            sub_query.c.user_id,
            sub_query.c.status,
            sub_query.c.create_time,
            sub_query.c.update_time,
            sub_query.c.app_state,
        )
        count_statement = select(func.count(sub_query.c.id))
        if name:
            if search_description:
                keyword_filter = or_(
                    sub_query.c.name.like(f"%{name}%"),
                    sub_query.c.description.like(f"%{name}%"),
                )
            else:
                keyword_filter = sub_query.c.name.like(f"%{name}%")
            statement = statement.where(keyword_filter)
            count_statement = count_statement.where(keyword_filter)
        if status is not None:
            statement = statement.where(sub_query.c.status == status)
            count_statement = count_statement.where(sub_query.c.status == status)
        if app_state:
            # Hosted-application state (F054). The other two legs project NULL
            # here, so an equality predicate narrows to hosted apps by itself —
            # this filter never needs a companion ``flow_type`` condition.
            statement = statement.where(sub_query.c.app_state == app_state)
            count_statement = count_statement.where(sub_query.c.app_state == app_state)
        if id_list:
            statement = statement.where(sub_query.c.id.in_(id_list))
            count_statement = count_statement.where(sub_query.c.id.in_(id_list))
        app_type_ids_filter = cls._build_app_type_ids_filter(sub_query, app_type_ids)
        if app_type_ids_filter is not None:
            statement = statement.where(app_type_ids_filter)
            count_statement = count_statement.where(app_type_ids_filter)
        if flow_type is not None:
            statement = statement.where(sub_query.c.flow_type == flow_type)
            count_statement = count_statement.where(sub_query.c.flow_type == flow_type)
        if user_id is not None:
            if id_extra:
                statement = statement.where(or_(sub_query.c.user_id == user_id, sub_query.c.id.in_(id_extra)))
                count_statement = count_statement.where(
                    or_(sub_query.c.user_id == user_id, sub_query.c.id.in_(id_extra))
                )
            else:
                statement = statement.where(sub_query.c.user_id == user_id)
                count_statement = count_statement.where(sub_query.c.user_id == user_id)
        if id_list_not_in:
            statement = statement.where(~sub_query.c.id.in_(id_list_not_in))
            count_statement = count_statement.where(~sub_query.c.id.in_(id_list_not_in))
        if page and limit:
            statement = statement.offset((page - 1) * limit).limit(limit)
        statement = statement.order_by(sub_query.c.update_time.desc())
        with get_sync_db_session() as session:
            ret = session.exec(statement).all()
            total = session.scalar(count_statement)
        data = []
        for one in ret:
            data.append(cls._app_row_to_dict(one))
        return data, total

    @staticmethod
    def _app_row_to_dict(one) -> dict:
        """Map one UNION row to the list payload.

        ``app_state`` is attached **only to hosted-application rows**. Workflows
        and assistants keep the exact payload they had before F054 — a null
        ``app_state`` on every card would be a new field in a response two
        front-ends already parse, for no reader (AC-59).
        """
        item = {
            "id": one[0],
            "name": one[1],
            "description": one[2],
            "flow_type": one[3],
            "logo": one[4],
            "user_id": one[5],
            "status": one[6],
            "create_time": one[7],
            "update_time": one[8],
        }
        if one[3] == FlowType.HOSTED_APP.value:
            item["app_state"] = one[9]
        return item

    @classmethod
    async def aget_all_apps(
        cls,
        name: str | None = None,
        status: int | None = None,
        id_list: list | None = None,
        flow_type: int | None = None,
        user_id: int | None = None,
        id_extra: list | None = None,
        id_list_not_in: list | None = None,
        page: int = 0,
        limit: int = 0,
        search_description=False,
        app_type_ids: dict[int, list[str]] | None = None,
        cursor: Sequence | None = None,
        ranking_user_id: int | None = None,
        app_state: str | None = None,
        status_exempt_flow_types: set[int] | None = None,
        app_state_in: set[str] | None = None,
    ) -> tuple[list[dict], bool]:
        """List flow-based apps, assistants and hosted applications (F027 cursor-paginated).

        Total-count side query removed per spec AC-11; ``has_more`` is
        detected by fetching ``limit + 1`` rows.

        Args:
            cursor: ``(update_time, id)`` from the previous page's last visible
                row. With ``ranking_user_id``, the cursor is
                ``(used_rank, sort_time, id)``. When set, applies keyset WHERE
                and ignores ``page``.
            ranking_user_id: Rank apps used by this user first, ordered by the
                latest session create time; unused apps follow by update time.
            app_state: F054 hosted-application state. Narrows to hosted apps on
                its own (the other legs project NULL for that column).
            status_exempt_flow_types: F056 square. Flow types the outer
                ``status`` equality does not apply to, so a stopped hosted
                application (projected ``status`` 1) still reaches the square.
                ``None`` — every other caller — leaves the SQL untouched.
            app_state_in: F056 square. Hosted-application states allowed into
                the result, pushed onto the third leg. The square pins it to
                ``{online, stopped}`` server-side; it is deliberately not an
                HTTP parameter, because both directions (stopped must appear,
                drafts must not) are product rules rather than user choices.

        Returns:
            ``(data, has_more)`` — the list of app dicts and whether a
            further page exists. The legacy ``(data, total)`` shape is gone.
        """
        sub_query = cls._build_apps_subquery(app_state_in=app_state_in)

        statement = select(
            sub_query.c.id,
            sub_query.c.name,
            sub_query.c.description,
            sub_query.c.flow_type,
            sub_query.c.logo,
            sub_query.c.user_id,
            sub_query.c.status,
            sub_query.c.create_time,
            sub_query.c.update_time,
            sub_query.c.app_state,
        )
        used_rank = None
        sort_time = None
        if ranking_user_id is not None:
            last_used = cls._build_user_last_used_subquery(ranking_user_id, flow_type)
            statement = statement.outerjoin(
                last_used,
                and_(
                    sub_query.c.id == last_used.c.flow_id,
                    sub_query.c.flow_type == last_used.c.flow_type,
                ),
            )
            used_rank = case((last_used.c.last_used_time.is_not(None), 0), else_=1)
            sort_time = func.coalesce(last_used.c.last_used_time, sub_query.c.update_time)
            statement = statement.add_columns(
                used_rank.label("_used_rank"),
                sort_time.label("_sort_time"),
            )
        if name:
            if search_description:
                keyword_filter = or_(
                    sub_query.c.name.like(f"%{name}%"),
                    sub_query.c.description.like(f"%{name}%"),
                )
            else:
                keyword_filter = sub_query.c.name.like(f"%{name}%")
            statement = statement.where(keyword_filter)

        if status is not None:
            statement = statement.where(
                cls._build_status_clause(
                    sub_query,
                    status=status,
                    status_exempt_flow_types=status_exempt_flow_types,
                )
            )
        if app_state:
            # See ``get_all_apps``: hosted-application state, self-narrowing.
            statement = statement.where(sub_query.c.app_state == app_state)
        if id_list:
            statement = statement.where(sub_query.c.id.in_(id_list))
        app_type_ids_filter = cls._build_app_type_ids_filter(sub_query, app_type_ids)
        if app_type_ids_filter is not None:
            statement = statement.where(app_type_ids_filter)
        if flow_type is not None:
            statement = statement.where(sub_query.c.flow_type == flow_type)
        if user_id is not None:
            if id_extra:
                statement = statement.where(or_(sub_query.c.user_id == user_id, sub_query.c.id.in_(id_extra)))
            else:
                statement = statement.where(sub_query.c.user_id == user_id)
        if id_list_not_in:
            statement = statement.where(~sub_query.c.id.in_(id_list_not_in))

        # F027: cursor (keyset) takes precedence over OFFSET. When neither is
        # set we return everything (skip_pagination path used by chat.py online
        # rankings).
        fetch_limit = (limit + 1) if limit else 0
        if cursor is not None:
            from bisheng.database.utils.keyset import build_keyset_where

            if ranking_user_id is not None:
                statement = statement.where(
                    build_keyset_where(
                        (used_rank, sort_time, sub_query.c.id),
                        tuple(cursor),
                        descending=(False, True, True),
                    )
                )
            else:
                statement = statement.where(
                    build_keyset_where(
                        (sub_query.c.update_time, sub_query.c.id),
                        tuple(cursor),
                        descending=True,
                    )
                )
            if fetch_limit:
                statement = statement.limit(fetch_limit)
        elif page and limit:
            statement = statement.offset((page - 1) * limit).limit(fetch_limit)
        elif limit:
            statement = statement.limit(fetch_limit)

        if ranking_user_id is not None:
            statement = statement.order_by(used_rank.asc(), sort_time.desc(), sub_query.c.id.desc())
        else:
            statement = statement.order_by(sub_query.c.update_time.desc(), sub_query.c.id.desc())

        async with get_async_db_session() as session:
            result = await session.exec(statement)
            ret = result.all()

        has_more = bool(limit) and len(ret) > limit
        if has_more:
            ret = ret[:limit]
        data = []
        for one in ret:
            item = cls._app_row_to_dict(one)
            if ranking_user_id is not None:
                # Indices 9 is ``app_state``; the ranking columns are appended
                # after it by ``add_columns`` above.
                item["_used_rank"] = one[10]
                item["_sort_time"] = one[11]
            data.append(item)
        return data, has_more

    @classmethod
    def _build_status_clause(cls, sub_query, *, status: int, status_exempt_flow_types: set[int] | None = None):
        """The outer ``status`` predicate, with an optional per-type exemption (F056 design D9).

        The square must keep listing stopped hosted applications: hiding them
        reads as "you lost access" rather than "this app is paused" (决议-5).
        Their ``status`` projection is 1 (offline), so the square exempts
        ``flow_type = 35`` from the equality instead of changing the
        projection — folding "stopped" into 2 would silently break the build
        page's online/offline filter, which reads the same column.
        """
        clause = sub_query.c.status == status
        if status_exempt_flow_types:
            clause = or_(clause, sub_query.c.flow_type.in_(sorted(status_exempt_flow_types)))
        return clause

    @classmethod
    def _build_apps_subquery(cls, *, app_state_in: set[str] | None = None):
        """Build the workflow+assistant+hosted-app ``UNION ALL`` subquery with tenant isolation.

        The ``do_orm_execute`` auto-filter (see ``core/database/tenant_filter.py``)
        only inspects the outer statement's ``column_descriptions`` /
        ``get_final_froms``. Wrapping ``select(Flow) UNION ALL select(Assistant)``
        in ``.subquery()`` hides every tenant-aware table behind a Subquery, so
        the listener finds no table to filter and the outer SELECT leaks cross
        tenant rows. Inject the per-table tenant clause on each inner SELECT
        before unioning so all four callers (sync/async list, time-range stats,
        first-app) stay in lockstep with the listener's semantics. **A new leg
        that forgets its own clause leaks through all four at once** — there is
        no auto-filter behind this to catch it (design K5 ③).

        The third leg (F054 design D8) projects the ``app`` table onto the same
        column set: ``flow_type`` becomes the constant 35, ``user_id`` becomes
        the owner, and ``status`` is folded to 2 (online) / 1 (everything else)
        so the existing on/off switch and ``status`` filter keep working
        unchanged. The five real application states ride a **tenth column**,
        ``app_state``, which the other two legs fill with a typed NULL — a UNION
        needs one column count, and that NULL is what lets a single query carry
        a per-type field instead of the build page fetching a detail per card.
        ``deleted`` apps are excluded here rather than filtered later: the row
        survives for audit, but it is not an application any list should show.
        """
        flow_select = select(
            Flow.id,
            Flow.name,
            Flow.description,
            Flow.flow_type,
            Flow.logo,
            Flow.user_id,
            Flow.status,
            Flow.create_time,
            Flow.update_time,
            cast(null(), String(16)).label("app_state"),
        )
        assistant_select = select(
            Assistant.id,
            Assistant.name,
            Assistant.desc,
            FlowType.ASSISTANT.value,
            Assistant.logo,
            Assistant.user_id,
            Assistant.status,
            Assistant.create_time,
            Assistant.update_time,
            cast(null(), String(16)).label("app_state"),
        ).where(Assistant.is_delete == 0)
        app_select = select(
            App.id,
            App.name,
            App.description,
            FlowType.HOSTED_APP.value,
            App.logo,
            App.owner_user_id,
            case((App.state == APP_STATE_ONLINE, FlowStatus.ONLINE.value), else_=FlowStatus.OFFLINE.value),
            App.create_time,
            App.update_time,
            col(App.state).label("app_state"),
        ).where(App.state != APP_STATE_DELETED)
        if app_state_in:
            # Pushed onto the leg rather than applied outside: the other two legs
            # project a typed NULL for this column, so an outer predicate would
            # have to spell out "or the row is not a hosted application". Down
            # here it also keeps drafts out of the row set entirely, which is
            # why "not visible even to the owner" needs no permission code.
            app_select = app_select.where(col(App.state).in_(sorted(app_state_in)))

        flow_clause = build_tenant_filter_clause(Flow.tenant_id)
        if flow_clause is not None:
            flow_select = flow_select.where(flow_clause)
        assistant_clause = build_tenant_filter_clause(Assistant.tenant_id)
        if assistant_clause is not None:
            assistant_select = assistant_select.where(assistant_clause)
        app_clause = build_tenant_filter_clause(App.tenant_id)
        if app_clause is not None:
            app_select = app_select.where(app_clause)

        return flow_select.union_all(assistant_select, app_select).subquery()

    @classmethod
    def _build_user_last_used_subquery(cls, user_id: int, flow_type: int | None = None):
        """Aggregate one user's last session time with explicit tenant scope."""
        statement = select(
            MessageSession.flow_id,
            MessageSession.flow_type,
            func.max(MessageSession.create_time).label("last_used_time"),
        ).where(
            MessageSession.user_id == user_id,
            MessageSession.is_delete == false(),
        )
        tenant_clause = build_tenant_filter_clause(MessageSession.tenant_id)
        if tenant_clause is not None:
            statement = statement.where(tenant_clause)
        if flow_type is not None:
            statement = statement.where(MessageSession.flow_type == flow_type)
        return statement.group_by(MessageSession.flow_id, MessageSession.flow_type).subquery()

    @staticmethod
    def _build_app_type_ids_filter(sub_query, app_type_ids: dict[int, list[str]] | None = None):
        """Build a type-aware app ID filter for the workflow/assistant union."""
        if app_type_ids is None:
            return None

        conditions = []
        for app_type, ids in app_type_ids.items():
            normalized_ids = [str(one) for one in (ids or []) if one is not None]
            if not normalized_ids:
                continue
            conditions.append(
                and_(
                    sub_query.c.flow_type == int(app_type),
                    sub_query.c.id.in_(normalized_ids),
                )
            )
        if not conditions:
            return false()
        return or_(*conditions)

    @classmethod
    async def get_one_flow_simple(cls, flow_id: str) -> Flow | None:
        """get simple info of one flow by id. not contain data field"""
        statement = select(
            Flow.id,
            Flow.name,
            Flow.description,
            Flow.flow_type,
            Flow.logo,
            Flow.user_id,
            Flow.status,
            Flow.create_time,
            Flow.update_time,
        ).where(Flow.id == flow_id)
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            one = result.first()
            if not one:
                return None
            return Flow(
                **{
                    "id": one[0],
                    "name": one[1],
                    "description": one[2],
                    "flow_type": one[3],
                    "logo": one[4],
                    "user_id": one[5],
                    "status": one[6],
                    "create_time": one[7],
                    "update_time": one[8],
                }
            )

    @classmethod
    def get_one_flow_simple_sync(cls, flow_id: str) -> Flow | None:
        """get simple info of one flow by id. not contain data field"""
        statement = select(
            Flow.id,
            Flow.name,
            Flow.description,
            Flow.flow_type,
            Flow.logo,
            Flow.user_id,
            Flow.status,
            Flow.create_time,
            Flow.update_time,
        ).where(Flow.id == flow_id)
        with get_sync_db_session() as session:
            result = session.exec(statement)
            one = result.first()
            if not one:
                return None
            return Flow(
                **{
                    "id": one[0],
                    "name": one[1],
                    "description": one[2],
                    "flow_type": one[3],
                    "logo": one[4],
                    "user_id": one[5],
                    "status": one[6],
                    "create_time": one[7],
                    "update_time": one[8],
                }
            )

    @classmethod
    def get_all_app_by_time_range_sync(
        cls, start_time: datetime, end_time: datetime, page: int = 0, page_size: int = 0
    ):
        """Applications created in a window — the telemetry mid-table feed.

        F054 reviewed and accepted: hosted applications flow through here too,
        because they are platform applications and leaving them out would
        silently undercount "apps created". The consumer
        (``worker/telemetry/mid_table.py``) reads only id / name / user_id /
        flow_type / create_time, all of which the third leg projects, and its
        ``convert_flow_type`` already has a total fallback — so a new type
        widens a bucket, it cannot break the sync.
        """
        sub_query = cls._build_apps_subquery()

        statement = select(
            sub_query.c.id,
            sub_query.c.name,
            sub_query.c.description,
            sub_query.c.flow_type,
            sub_query.c.logo,
            sub_query.c.user_id,
            sub_query.c.status,
            sub_query.c.create_time,
            sub_query.c.update_time,
        )
        statement = statement.where(and_(sub_query.c.create_time >= start_time, sub_query.c.create_time < end_time))
        if page and page_size:
            statement = statement.offset((page - 1) * page_size).limit(page_size)
        with get_sync_db_session() as session:
            result = session.exec(statement).all()
            data = []
            for one in result:
                data.append(
                    {
                        "id": one[0],
                        "name": one[1],
                        "description": one[2],
                        "flow_type": one[3],
                        "logo": one[4],
                        "user_id": one[5],
                        "status": one[6],
                        "create_time": one[7],
                        "update_time": one[8],
                    }
                )
            return data

    @classmethod
    def get_first_app(cls):
        """Oldest application — only its ``create_time`` is read.

        Used by ``scripts/sync_increment_table.py`` to pick the backfill start
        date. F054 reviewed and accepted that hosted applications participate:
        the worst case is an earlier start date, i.e. a wider backfill window.
        """
        sub_query = cls._build_apps_subquery()

        statement = select(
            sub_query.c.id,
            sub_query.c.name,
            sub_query.c.description,
            sub_query.c.flow_type,
            sub_query.c.logo,
            sub_query.c.user_id,
            sub_query.c.status,
            sub_query.c.create_time,
            sub_query.c.update_time,
        )
        statement = statement.order_by(sub_query.c.create_time.asc()).limit(1)
        with get_sync_db_session() as session:
            result = session.exec(statement).all()
            data = []
            for one in result:
                data.append(
                    {
                        "id": one[0],
                        "name": one[1],
                        "description": one[2],
                        "flow_type": one[3],
                        "logo": one[4],
                        "user_id": one[5],
                        "status": one[6],
                        "create_time": one[7],
                        "update_time": one[8],
                    }
                )
            return data[0] if data else None
