import asyncio
from datetime import datetime
from typing import Any, Union

from loguru import logger
from sqlmodel import and_, col, or_, select

from bisheng.core.database.dialect_helpers import json_array_contains


def _db_dialect() -> str:
    try:
        from bisheng.core.database.manager import sync_get_database_connection

        return sync_get_database_connection().engine.dialect.name
    except Exception:
        return "mysql"


from bisheng.api.v1.schema.chat_schema import AppChatList
from bisheng.api.v1.schema.workflow import WorkflowEventType
from bisheng.api.v1.schemas import resp_200
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    get_admin_scope_tenant_id,
    get_current_tenant_id,
)
from bisheng.core.database import get_async_db_session
from bisheng.database.models.app import AppDao
from bisheng.database.models.assistant import Assistant, AssistantDao
from bisheng.database.models.audit_log import AuditLog, AuditLogDao, EventType, ObjectType, SystemId
from bisheng.database.models.department import DepartmentDao
from bisheng.database.models.flow import Flow, FlowDao, FlowType
from bisheng.database.models.group import Group
from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.message import ChatMessageDao
from bisheng.database.models.role import Role
from bisheng.database.models.session import MessageSession, MessageSessionDao
from bisheng.database.models.tenant import TenantDao
from bisheng.database.models.user_group import UserGroupDao
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeDao
from bisheng.tool.domain.models.gpts_tools import GptsToolsType
from bisheng.user.domain.models.user import User, UserDao
from bisheng.user.domain.services.auth import LoginUser

# F056 AC-32: the system-audit export walks the same paginated query the
# list uses. The cap keeps one request bounded; the frontend tells the
# operator to narrow the filters when ``total`` exceeds it.
AUDIT_EXPORT_MAX_ROWS = 10_000
AUDIT_EXPORT_PAGE_SIZE = 500


# todo change to async or submit thread pool
class AuditLogService:
    @classmethod
    async def _user_has_log_web_menu(cls, user: UserPayload) -> bool:
        """角色 / 部门管理员合并后的 web_menu 含 ``log``（审计页）时允许使用审计 API。"""
        db_user = await UserDao.aget_user(user.user_id)
        if not db_user:
            return False
        is_department_admin = bool(await DepartmentDao.aget_user_admin_departments(user.user_id))
        _, web_menu = await LoginUser.get_roles_web_menu(db_user, is_department_admin=is_department_admin)
        return "log" in set(web_menu)

    @classmethod
    def _get_audit_tenant_scope(cls, user: UserPayload) -> int | None:
        """Tenant id to scope audit reads to, or None to skip scoping.

        - Global super w/o F019 admin-scope     -> None  (sees all tenants)
        - Global super WITH F019 admin-scope=X  -> X
        - Tenant Admin / Dept admin / log-menu  -> their leaf tenant id

        ``is_admin()`` is role-based and true for Child Tenant Admins too,
        so we read the JWT-stamped ``is_global_super`` field (populated by
        ``init_login_user`` from the same FGA check) instead.
        ``get_current_tenant_id()`` already returns the F019 admin-scope
        override when set, so it does the right thing for super-with-scope.
        """
        if user.is_global_super and get_admin_scope_tenant_id() is None:
            return None
        return get_current_tenant_id()

    @classmethod
    async def _resolve_audit_groups(cls, login_user: UserPayload, group_ids: list[str]) -> list[str]:
        """Group filter the caller is allowed to run, or ``UnAuthorizedError``.

        Admins and log-menu roles filter by whatever they picked (possibly
        nothing); a user-group admin is pinned to the groups they manage,
        intersected with their pick.
        """
        if login_user.is_admin() or await cls._user_has_log_web_menu(login_user):
            return list(group_ids)
        groups = [str(one.group_id) for one in await UserGroupDao.aget_user_admin_group(login_user.user_id)]
        # Not an administrator of any user groups
        if not groups:
            raise UnAuthorizedError()
        # Filter by group_id and administrator-permission groups, doing intersections
        if group_ids:
            groups = list(set(groups) & set(group_ids))
            if not groups:
                raise UnAuthorizedError()
        return groups

    @classmethod
    async def _group_member_ids(cls, groups: list[str]) -> list[int]:
        """Current members of the selected groups (F056 design pit 15).

        Structured v2 rows never fill ``group_ids``, so the DAO also matches
        v2 rows by *operator membership*. Read only when a group filter is
        in force — the common admin path passes no groups and pays nothing.
        """
        if not groups:
            return []
        rows = await UserGroupDao.aget_group_users([int(one) for one in groups])
        return sorted({one.user_id for one in rows})

    @classmethod
    def _resolve_tenant_scope(cls, login_user: UserPayload, tenant_id: int | None) -> int | None:
        """Combine the role-derived scope with an explicit ``tenant_id`` filter.

        - global super (scope ``None``) → ``tenant_id`` narrows the view (AC-30);
        - anyone else → ``tenant_id`` must equal their own scope, otherwise the
          request is rejected outright rather than silently narrowed (AC-31).
        """
        scope = cls._get_audit_tenant_scope(login_user)
        if tenant_id is None:
            return scope
        if scope is None:
            return tenant_id
        if tenant_id != scope:
            raise UnAuthorizedError()
        return scope

    @classmethod
    async def _assert_app_in_scope(cls, app_id: str, tenant_scope: int | None) -> None:
        """The object-app filter must not reach into another tenant (AC-31).

        Looked up with the tenant filter bypassed on purpose: with it on, a
        foreign app simply reads as "not found" and the query would degrade
        to an empty list instead of the rejection the AC asks for. An unknown
        id is left to the predicate, which then matches nothing.
        """
        if tenant_scope is None:
            return
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                app = await AppDao.aget(session, app_id)
        if app is not None and int(app.tenant_id or 0) != tenant_scope:
            raise UnAuthorizedError()

    @classmethod
    async def _prepare_audit_query(
        cls, login_user: UserPayload, group_ids: list[str], target_app_id: str | None, tenant_id: int | None
    ) -> tuple[list[str], list[int], int | None]:
        """Role gate + tenant boundary shared by the list and the export.

        One function on purpose (spec 决议-8): an export whose scope differs
        from the query's is a bypass, so both go through here and receive
        the same ``(groups, member_ids, tenant_scope)``.
        """
        groups = await cls._resolve_audit_groups(login_user, group_ids)
        tenant_scope = cls._resolve_tenant_scope(login_user, tenant_id)
        if target_app_id:
            await cls._assert_app_in_scope(target_app_id, tenant_scope)
        member_ids = await cls._group_member_ids(groups)
        return groups, member_ids, tenant_scope

    @classmethod
    def _operator_kind(cls, row: AuditLog) -> str | None:
        """``service_account`` for rows a service account produced, else ``None``.

        Two shapes are recognised: an explicit ``metadata.operator.kind`` (the
        contract writers adopt going forward), and the beta2 convention used
        by ``OpenApiAuditMiddleware`` / ``write_release_audit`` — operator 0
        with the account's name (``operator_id=0`` *without* a name is a
        system trigger and renders as ``system``).
        """
        metadata = row.audit_metadata if isinstance(row.audit_metadata, dict) else {}
        operator = metadata.get("operator") if isinstance(metadata.get("operator"), dict) else {}
        if operator.get("kind") == "service_account":
            return "service_account"
        if row.operator_id == 0 and row.operator_name and row.operator_name != "system":
            return "service_account"
        return None

    @classmethod
    def _row_app_id(cls, row: AuditLog) -> str | None:
        """Which hosted application a row is about — mirrors ``_object_app_predicate``."""
        if row.target_type == "app" and row.target_id:
            return row.target_id
        metadata = row.audit_metadata if isinstance(row.audit_metadata, dict) else {}
        app_id = metadata.get("app_id")
        return app_id if isinstance(app_id, str) and app_id else None

    @classmethod
    async def _enrich_audit_rows(cls, rows: list[AuditLog]) -> list[dict[str, Any]]:
        """Project rows for the audit page / export (F056 AC-17, AC-29, AC-30).

        The raw ``metadata`` blob is deliberately **not** emitted: it is a
        free-form dict every writer fills differently and the one place a
        secret could leak through (AC-26). Only derived, named fields leave
        this function. Applications are resolved with the tenant filter
        bypassed — a global super's page spans tenants — and the rows
        themselves were already scoped by the query.
        """
        if not rows:
            return []
        app_ids = {app_id for row in rows if (app_id := cls._row_app_id(row))}
        tenant_ids = {row.tenant_id for row in rows if row.tenant_id is not None}

        apps_by_id: dict[str, Any] = {}
        if app_ids:
            with bypass_tenant_filter():
                async with get_async_db_session() as session:
                    apps_by_id = {app.id: app for app in await AppDao.alist_by_ids(session, sorted(app_ids))}
        tenants_by_id = {t.id: t for t in await TenantDao.aget_by_ids(sorted(tenant_ids))} if tenant_ids else {}

        owner_ids = {app.owner_user_id for app in apps_by_id.values() if app.owner_user_id}
        owners_by_id: dict[int, str] = {}
        if owner_ids:
            owners_by_id = {u.user_id: u.user_name for u in (await UserDao.aget_user_by_ids(sorted(owner_ids)) or [])}

        result: list[dict[str, Any]] = []
        for row in rows:
            item = row.model_dump(exclude={"audit_metadata"})
            metadata = row.audit_metadata if isinstance(row.audit_metadata, dict) else {}
            app_id = cls._row_app_id(row)
            app = apps_by_id.get(app_id) if app_id else None
            item["app_id"] = app_id
            # The live row wins for slug / state; the audit row's own
            # ``object_name`` is the name snapshot and stays authoritative
            # when the application row is gone or renamed since (AC-21).
            item["app_name"] = app.name if app is not None else (row.object_name if app_id else None)
            item["app_slug"] = app.slug if app is not None else metadata.get("app_slug")
            item["app_state"] = app.state if app is not None else None
            item["app_owner_name"] = owners_by_id.get(app.owner_user_id) if app is not None else None
            version_no = metadata.get("version_no")
            item["version_no"] = version_no if isinstance(version_no, int) else None
            tenant = tenants_by_id.get(row.tenant_id) if row.tenant_id is not None else None
            item["tenant_name"] = tenant.tenant_name if tenant is not None else None
            operator = metadata.get("operator") if isinstance(metadata.get("operator"), dict) else {}
            item["operator_kind"] = cls._operator_kind(row)
            # Only the mask a writer already produced is forwarded; nothing
            # here reconstructs one from a longer value (AC-26).
            key_mask = operator.get("key_mask")
            item["operator_key_mask"] = key_mask if item["operator_kind"] and isinstance(key_mask, str) else None
            result.append(item)
        return result

    @classmethod
    async def get_audit_log(
        cls,
        login_user: UserPayload,
        group_ids,
        operator_ids,
        start_time,
        end_time,
        system_id,
        event_type,
        page,
        limit,
        target_app_id: str | None = None,
        tenant_id: int | None = None,
    ) -> Any:
        try:
            groups, member_ids, tenant_scope = await cls._prepare_audit_query(
                login_user, group_ids, target_app_id, tenant_id
            )
        except UnAuthorizedError:
            return UnAuthorizedError.return_resp()
        data, total = await AuditLogDao.get_audit_logs(
            groups,
            operator_ids,
            start_time,
            end_time,
            system_id,
            event_type,
            page,
            limit,
            tenant_scope=tenant_scope,
            target_app_id=target_app_id,
            group_member_ids=member_ids,
        )
        return resp_200(data={"data": await cls._enrich_audit_rows(data), "total": total})

    @classmethod
    async def export_audit_log(
        cls,
        login_user: UserPayload,
        group_ids,
        operator_ids,
        start_time,
        end_time,
        system_id,
        event_type,
        target_app_id: str | None = None,
        tenant_id: int | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Every row the same query would list, in list order (F056 AC-32).

        Returns ``(rows, total)``; ``rows`` is capped at
        ``AUDIT_EXPORT_MAX_ROWS`` and the caller compares the two to tell the
        operator the export was truncated. Same gate, same scope, same
        projection as :meth:`get_audit_log` — the only difference is that
        pagination is driven from here.
        """
        groups, member_ids, tenant_scope = await cls._prepare_audit_query(
            login_user, group_ids, target_app_id, tenant_id
        )
        rows: list[dict[str, Any]] = []
        page = 1
        total = 0
        while len(rows) < AUDIT_EXPORT_MAX_ROWS:
            chunk, total = await AuditLogDao.get_audit_logs(
                groups,
                operator_ids,
                start_time,
                end_time,
                system_id,
                event_type,
                page,
                AUDIT_EXPORT_PAGE_SIZE,
                tenant_scope=tenant_scope,
                target_app_id=target_app_id,
                group_member_ids=member_ids,
            )
            if not chunk:
                break
            rows.extend(await cls._enrich_audit_rows(chunk))
            if len(chunk) < AUDIT_EXPORT_PAGE_SIZE:
                break
            page += 1
        return rows[:AUDIT_EXPORT_MAX_ROWS], total

    @classmethod
    async def search_audit_apps(cls, login_user: UserPayload, keyword: str, limit: int) -> list[dict[str, Any]]:
        """Options for the audit page's object-application selector (AC-28).

        Same gate as the list; same tenant scope, so a tenant admin only
        ever sees their own tenant's applications (AC-31). Deleted
        applications are included on purpose — their delete event is the
        one a reader is most likely looking for (AC-21).
        """
        await cls._resolve_audit_groups(login_user, [])
        tenant_scope = cls._get_audit_tenant_scope(login_user)
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                apps = await AppDao.asearch_for_audit(session, tenant_scope, keyword, limit)
        return [
            {"id": app.id, "name": app.name, "slug": app.slug, "state": app.state, "tenant_id": app.tenant_id}
            for app in apps
        ]

    @classmethod
    async def get_all_operators(cls, login_user: UserPayload) -> list[dict]:
        groups: list[int] = []
        if not login_user.is_admin():
            if not await cls._user_has_log_web_menu(login_user):
                groups = [one.group_id for one in await UserGroupDao.aget_user_admin_group(login_user.user_id)]
                if not groups:
                    raise UnAuthorizedError()

        tenant_scope = cls._get_audit_tenant_scope(login_user)
        data = AuditLogDao.get_all_operators(groups, tenant_scope=tenant_scope)
        res = {}
        for one in data:
            if not one[1]:
                continue
            res[one[0]] = {"user_id": one[0], "user_name": one[1]}
        return list(res.values())

    @classmethod
    def _chat_log(
        cls,
        user: UserPayload,
        ip_address: str,
        event_type: EventType,
        object_type: ObjectType,
        object_id: str,
        object_name: str,
        resource_type: ResourceTypeEnum,
    ):
        # F008: Use operator's user groups instead of resource group (ReBAC migration)
        user_groups = UserGroupDao.get_user_group(user.user_id)
        group_ids = [one.group_id for one in user_groups]
        audit_log = AuditLog(
            operator_id=user.user_id,
            operator_name=user.user_name,
            group_ids=group_ids,
            system_id=SystemId.CHAT.value,
            event_type=event_type.value,
            object_type=object_type.value,
            object_id=object_id,
            object_name=object_name,
            ip_address=ip_address,
        )
        AuditLogDao.insert_audit_logs([audit_log])

    @classmethod
    async def _chat_log_async(
        cls,
        user: UserPayload,
        ip_address: str,
        event_type: EventType,
        object_type: ObjectType,
        object_id: str,
        object_name: str,
        resource_type: ResourceTypeEnum,
        group_ids: list[int] = None,
    ):
        # F008: Use operator's user groups instead of resource group (ReBAC migration)
        if group_ids is None:
            user_groups = await UserGroupDao.aget_user_group(user.user_id)
            group_ids = [one.group_id for one in user_groups]
        audit_log = AuditLog(
            operator_id=user.user_id,
            operator_name=user.user_name,
            group_ids=group_ids,
            system_id=SystemId.CHAT.value,
            event_type=event_type.value,
            object_type=object_type.value,
            object_id=object_id,
            object_name=object_name,
            ip_address=ip_address,
        )
        await AuditLogDao.ainsert_audit_logs([audit_log])

    @classmethod
    def create_chat_assistant(cls, user: UserPayload, ip_address: str, assistant_id: str):
        """
        New Audit Log for Assistant Session
        """
        logger.info(f"act=create_chat_assistant user={user.user_name} ip={ip_address} assistant={assistant_id}")
        # Getting Assistant Details
        assistant_info = AssistantDao.get_one_assistant(assistant_id)
        cls._chat_log(
            user,
            ip_address,
            EventType.CREATE_CHAT,
            ObjectType.ASSISTANT,
            assistant_id,
            assistant_info.name,
            ResourceTypeEnum.ASSISTANT,
        )

    @classmethod
    def create_chat_workflow(cls, user: UserPayload, ip_address: str, flow_id: str, flow_info=None):
        """
        New Workflow Session Audit Log
        """
        logger.info(f"act=create_chat_workflow user={user.user_name} ip={ip_address} flow={flow_id}")
        if not flow_info:
            flow_info = FlowDao.get_flow_by_id(flow_id)
        cls._chat_log(
            user,
            ip_address,
            EventType.CREATE_CHAT,
            ObjectType.WORK_FLOW,
            flow_id,
            flow_info.name,
            ResourceTypeEnum.WORK_FLOW,
        )

    @classmethod
    async def delete_chat_workflow(cls, user: UserPayload, ip_address: str, flow_info: Flow):
        """
        Delete Audit Log for Workflow Session
        """
        logger.info(f"act=delete_chat_workflow user={user.user_name} ip={ip_address} flow={flow_info.id}")
        await cls._chat_log_async(
            user,
            ip_address,
            EventType.DELETE_CHAT,
            ObjectType.WORK_FLOW,
            flow_info.id,
            flow_info.name,
            ResourceTypeEnum.WORK_FLOW,
        )

    @classmethod
    async def delete_chat_assistant(cls, user: UserPayload, ip_address: str, assistant_info: Assistant):
        """
        Delete audit log for assistant session
        """
        logger.info(f"act=delete_assistant_flow user={user.user_name} ip={ip_address} assistant={assistant_info.id}")
        await cls._chat_log_async(
            user,
            ip_address,
            EventType.DELETE_CHAT,
            ObjectType.ASSISTANT,
            assistant_info.id,
            assistant_info.name,
            ResourceTypeEnum.ASSISTANT,
        )

    @classmethod
    def _build_log(
        cls,
        user: UserPayload,
        ip_address: str,
        event_type: EventType,
        object_type: ObjectType,
        object_id: str,
        object_name: str,
        resource_type: ResourceTypeEnum,
    ):
        """
        Build Module Audit Log
        """
        # F008: Use operator's user groups instead of resource group (ReBAC migration)
        user_groups = UserGroupDao.get_user_group(user.user_id)
        group_ids = [one.group_id for one in user_groups]

        # Insert Audit Log
        audit_log = AuditLog(
            operator_id=user.user_id,
            operator_name=user.user_name,
            group_ids=group_ids,
            system_id=SystemId.BUILD.value,
            event_type=event_type.value,
            object_type=object_type.value,
            object_id=object_id,
            object_name=object_name,
            ip_address=ip_address,
        )
        AuditLogDao.insert_audit_logs([audit_log])

    @classmethod
    async def _build_log_async(
        cls,
        user: UserPayload,
        ip_address: str,
        event_type: EventType,
        object_type: ObjectType,
        object_id: str,
        object_name: str,
        resource_type: ResourceTypeEnum,
    ):
        """
        Build Module Audit Log
        """
        # F008: Use operator's user groups instead of resource group (ReBAC migration)
        user_groups = await UserGroupDao.aget_user_group(user.user_id)
        group_ids = [one.group_id for one in user_groups]

        # Insert Audit Log
        audit_log = AuditLog(
            operator_id=user.user_id,
            operator_name=user.user_name,
            group_ids=group_ids,
            system_id=SystemId.BUILD.value,
            event_type=event_type.value,
            object_type=object_type.value,
            object_id=object_id,
            object_name=object_name,
            ip_address=ip_address,
        )
        await AuditLogDao.ainsert_audit_logs([audit_log])

    @classmethod
    def create_build_workflow(cls, user: UserPayload, ip_address: str, flow_id: str):
        """
        New Workflow Audit Log
        """
        logger.info(f"act=create_build_workflow user={user.user_name} ip={ip_address} flow={flow_id}")
        flow_info = FlowDao.get_flow_by_id(flow_id)
        cls._build_log(
            user,
            ip_address,
            EventType.CREATE_BUILD,
            ObjectType.WORK_FLOW,
            flow_info.id,
            flow_info.name,
            ResourceTypeEnum.WORK_FLOW,
        )

    @classmethod
    async def update_build_workflow(cls, user: UserPayload, ip_address: str, flow_id: str):
        """
        Update Workflow Audit Log
        """
        logger.info(f"act=update_build_workflow user={user.user_name} ip={ip_address} flow={flow_id}")
        flow_info = await FlowDao.aget_flow_by_id(flow_id)
        await cls._build_log_async(
            user,
            ip_address,
            EventType.UPDATE_BUILD,
            ObjectType.WORK_FLOW,
            flow_info.id,
            flow_info.name,
            ResourceTypeEnum.WORK_FLOW,
        )

    @classmethod
    def delete_build_workflow(cls, user: UserPayload, ip_address: str, flow_info: Flow):
        """
        Delete Workflow Audit Log
        """
        logger.info(f"act=delete_build_workflow user={user.user_name} ip={ip_address} flow={flow_info.id}")
        cls._build_log(
            user,
            ip_address,
            EventType.DELETE_BUILD,
            ObjectType.WORK_FLOW,
            flow_info.id,
            flow_info.name,
            ResourceTypeEnum.WORK_FLOW,
        )

    @classmethod
    def create_build_assistant(cls, user: UserPayload, ip_address: str, assistant_id: str):
        """
        New Assistant Audit Log
        """
        logger.info(f"act=create_build_assistant user={user.user_name} ip={ip_address} assistant={assistant_id}")
        assistant_info = AssistantDao.get_one_assistant(assistant_id)
        cls._build_log(
            user,
            ip_address,
            EventType.CREATE_BUILD,
            ObjectType.ASSISTANT,
            assistant_info.id,
            assistant_info.name,
            ResourceTypeEnum.ASSISTANT,
        )

    @classmethod
    def update_build_assistant(cls, user: UserPayload, ip_address: str, assistant_id: str):
        """
        Update the assistant's audit log
        """
        logger.info(f"act=update_build_assistant user={user.user_name} ip={ip_address} assistant={assistant_id}")
        assistant_info = AssistantDao.get_one_assistant(assistant_id)

        cls._build_log(
            user,
            ip_address,
            EventType.UPDATE_BUILD,
            ObjectType.ASSISTANT,
            assistant_info.id,
            assistant_info.name,
            ResourceTypeEnum.ASSISTANT,
        )

    @classmethod
    def delete_build_assistant(cls, user: UserPayload, ip_address: str, assistant_id: str):
        """
        Delete Audit Log for Assistant
        """
        logger.info(f"act=delete_build_assistant user={user.user_name} ip={ip_address} assistant={assistant_id}")
        assistant_info = AssistantDao.get_one_assistant(assistant_id)

        cls._build_log(
            user,
            ip_address,
            EventType.DELETE_BUILD,
            ObjectType.ASSISTANT,
            assistant_info.id,
            assistant_info.name,
            ResourceTypeEnum.ASSISTANT,
        )

    @classmethod
    async def create_chat_message(cls, user: UserPayload, ip_address: str, message: Union[str, MessageSession]):
        """
        New Chat Message Audit Log for Build Module
        """
        if isinstance(message, MessageSession):
            message_session = message
        else:
            message_session = await MessageSessionDao.async_get_one(message)

        logger.info(f"act=create_chat_message user={user.user_name} ip={ip_address} session={message_session.chat_id}")

        user_groups = await UserGroupDao.aget_user_group(message_session.user_id)
        group_ids = [ug.group_id for ug in user_groups]

        await cls._chat_log_async(
            user,
            ip_address,
            EventType.CREATE_CHAT,
            ObjectType.WORKSTATION,
            message_session.chat_id,
            message_session.name,
            ResourceTypeEnum.WORKSTATION,
            group_ids,
        )

    @classmethod
    async def delete_chat_message(cls, user: UserPayload, ip_address: str, message: Union[str, MessageSession]):
        """
        Delete Chat Message Audit Log for Build Module
        """
        if isinstance(message, MessageSession):
            message_session = message
        else:
            message_session = await MessageSessionDao.async_get_one(message)

        logger.info(f"act=delete_chat_message user={user.user_name} ip={ip_address} session={message_session.chat_id}")

        await cls._chat_log_async(
            user,
            ip_address,
            EventType.DELETE_CHAT,
            ObjectType.WORKSTATION,
            message_session.chat_id,
            message_session.name,
            ResourceTypeEnum.WORKSTATION,
        )

    @classmethod
    def _knowledge_log(
        cls,
        user: UserPayload,
        ip_address: str,
        event_type: EventType,
        object_type: ObjectType,
        object_id: str,
        object_name: str,
        resource_type: ResourceTypeEnum,
        resource_id: str,
    ):
        """
        Logs of Knowledge Base Modules
        """
        # F008: Use operator's user groups instead of resource group (ReBAC migration)
        user_groups = UserGroupDao.get_user_group(user.user_id)
        group_ids = [one.group_id for one in user_groups]

        # Insert Audit Log
        audit_log = AuditLog(
            operator_id=user.user_id,
            operator_name=user.user_name,
            group_ids=group_ids,
            system_id=SystemId.KNOWLEDGE.value,
            event_type=event_type.value,
            object_type=object_type.value,
            object_id=object_id,
            object_name=object_name,
            ip_address=ip_address,
        )
        AuditLogDao.insert_audit_logs([audit_log])

    @classmethod
    def create_knowledge(cls, user: UserPayload, ip_address: str, knowledge):
        """
        New Knowledge Base Audit Log

        :param knowledge: ``Knowledge`` ORM row (preferred — avoids a second DB read and
            races where ``query_by_id`` might not yet see the new row in some setups).
        """
        knowledge_id = knowledge.id if isinstance(knowledge, Knowledge) else int(knowledge)
        object_name = knowledge.name if isinstance(knowledge, Knowledge) else None
        if object_name is None:
            knowledge_info = KnowledgeDao.query_by_id(knowledge_id)
            object_name = knowledge_info.name if knowledge_info else str(knowledge_id)
        logger.info(f"act=create_knowledge user={user.user_name} ip={ip_address} knowledge={knowledge_id}")
        cls._knowledge_log(
            user,
            ip_address,
            EventType.CREATE_KNOWLEDGE,
            ObjectType.KNOWLEDGE,
            str(knowledge_id),
            object_name,
            ResourceTypeEnum.KNOWLEDGE,
            str(knowledge_id),
        )

    @classmethod
    def delete_knowledge(cls, user: UserPayload, ip_address: str, knowledge: Knowledge):
        """
        Delete Knowledge Base Audit Log
        """
        logger.info(f"act=delete_knowledge user={user.user_name} ip={ip_address} knowledge={knowledge.id}")
        cls._knowledge_log(
            user,
            ip_address,
            EventType.DELETE_KNOWLEDGE,
            ObjectType.KNOWLEDGE,
            str(knowledge.id),
            knowledge.name,
            ResourceTypeEnum.KNOWLEDGE,
            str(knowledge.id),
        )

    @classmethod
    async def create_knowledge_space(cls, user: UserPayload, ip_address: str, knowledge: Knowledge):
        """
        New Knowledge Space Audit Log
        """
        logger.info(f"act=create_knowledge_space user={user.user_name} ip={ip_address} knowledge={knowledge.id}")
        user_group = await UserGroupDao.aget_user_group(user.user_id)
        group_ids = [one.group_id for one in user_group]
        audit_log = AuditLog(
            operator_id=user.user_id,
            operator_name=user.user_name,
            group_ids=group_ids,
            system_id=SystemId.KNOWLEDGE_SPACE.value,
            event_type=EventType.CREATE_KNOWLEDGE_SPACE.value,
            object_type=ObjectType.KNOWLEDGE_SPACE.value,
            object_id=str(knowledge.id),
            object_name=knowledge.name,
            ip_address=ip_address,
        )
        await AuditLogDao.ainsert_audit_logs([audit_log])

    @classmethod
    async def delete_knowledge_space(cls, user: UserPayload, ip_address: str, knowledge: Knowledge):
        """
        Delete Knowledge Space Audit Log
        """
        logger.info(f"act=delete_knowledge_space user={user.user_name} ip={ip_address} knowledge={knowledge.id}")
        user_group = await UserGroupDao.aget_user_group(user.user_id)
        group_ids = [one.group_id for one in user_group]
        audit_log = AuditLog(
            operator_id=user.user_id,
            operator_name=user.user_name,
            group_ids=group_ids,
            system_id=SystemId.KNOWLEDGE_SPACE.value,
            event_type=EventType.DELETE_KNOWLEDGE_SPACE.value,
            object_type=ObjectType.KNOWLEDGE_SPACE.value,
            object_id=str(knowledge.id),
            object_name=knowledge.name,
            ip_address=ip_address,
        )
        await AuditLogDao.ainsert_audit_logs([audit_log])

    @classmethod
    def upload_knowledge_file(cls, user: UserPayload, ip_address: str, knowledge_id: int, file_name: str):
        """
        Audit Logs for Knowledge Base Upload Files
        """
        logger.info(
            f"act=upload_knowledge_file user={user.user_name} ip={ip_address} knowledge={knowledge_id} file={file_name}"
        )
        cls._knowledge_log(
            user,
            ip_address,
            EventType.UPLOAD_FILE,
            ObjectType.FILE,
            str(knowledge_id),
            file_name,
            ResourceTypeEnum.KNOWLEDGE,
            str(knowledge_id),
        )

    @classmethod
    def delete_knowledge_file(cls, user: UserPayload, ip_address: str, knowledge_id: int, file_name: str):
        """
        Audit Logs for Knowledge Base Deletion Files
        """
        logger.info(
            f"act=delete_knowledge_file user={user.user_name} ip={ip_address} knowledge={knowledge_id} file={file_name}"
        )
        cls._knowledge_log(
            user,
            ip_address,
            EventType.DELETE_FILE,
            ObjectType.FILE,
            str(knowledge_id),
            file_name,
            ResourceTypeEnum.KNOWLEDGE,
            str(knowledge_id),
        )

    @classmethod
    def link_file_version(cls, user: UserPayload, ip_address: str, knowledge_id: int, doc_summary: str):
        """Audit: file linked into an existing logical document as a new version."""
        logger.info(
            f"act=link_file_version user={user.user_name} ip={ip_address}"
            f" knowledge={knowledge_id} summary={doc_summary}"
        )
        cls._knowledge_log(
            user,
            ip_address,
            EventType.LINK_FILE_VERSION,
            ObjectType.FILE,
            str(knowledge_id),
            doc_summary,
            ResourceTypeEnum.KNOWLEDGE,
            str(knowledge_id),
        )

    @classmethod
    def set_primary_version(cls, user: UserPayload, ip_address: str, knowledge_id: int, doc_summary: str):
        """Audit: a historical version was promoted to primary."""
        logger.info(
            f"act=set_primary_version user={user.user_name} ip={ip_address}"
            f" knowledge={knowledge_id} summary={doc_summary}"
        )
        cls._knowledge_log(
            user,
            ip_address,
            EventType.SET_PRIMARY_VERSION,
            ObjectType.FILE,
            str(knowledge_id),
            doc_summary,
            ResourceTypeEnum.KNOWLEDGE,
            str(knowledge_id),
        )

    @classmethod
    def delete_file_version(cls, user: UserPayload, ip_address: str, knowledge_id: int, doc_summary: str):
        """Audit: historical version deleted."""
        logger.info(
            f"act=delete_file_version user={user.user_name} ip={ip_address}"
            f" knowledge={knowledge_id} summary={doc_summary}"
        )
        cls._knowledge_log(
            user,
            ip_address,
            EventType.DELETE_FILE_VERSION,
            ObjectType.FILE,
            str(knowledge_id),
            doc_summary,
            ResourceTypeEnum.KNOWLEDGE,
            str(knowledge_id),
        )

    @classmethod
    def dismiss_similar_file(cls, user: UserPayload, ip_address: str, knowledge_id: int, doc_summary: str):
        """Audit: user dismissed a similar-file recommendation."""
        logger.info(
            f"act=dismiss_similar_file user={user.user_name} ip={ip_address}"
            f" knowledge={knowledge_id} summary={doc_summary}"
        )
        cls._knowledge_log(
            user,
            ip_address,
            EventType.DISMISS_SIMILAR_FILE,
            ObjectType.FILE,
            str(knowledge_id),
            doc_summary,
            ResourceTypeEnum.KNOWLEDGE,
            str(knowledge_id),
        )

    @classmethod
    def _system_log(
        cls,
        user: UserPayload,
        ip_address: str,
        group_ids: list[int],
        event_type: EventType,
        object_type: ObjectType,
        object_id: str,
        object_name: str,
        note: str = "",
    ):

        audit_log = AuditLog(
            operator_id=user.user_id,
            operator_name=user.user_name,
            group_ids=group_ids,
            system_id=SystemId.SYSTEM.value,
            event_type=event_type.value,
            object_type=object_type.value,
            object_id=object_id,
            object_name=object_name,
            ip_address=ip_address,
            note=note,
        )
        AuditLogDao.insert_audit_logs([audit_log])

    @classmethod
    def update_user(cls, user: UserPayload, ip_address: str, user_id: int, group_ids: list[int], note: str):
        """
        Modify a user's user groups and roles
        """
        logger.info(f"act=update_system_user user={user.user_name} ip={ip_address} user_id={user_id} note={note}")
        user_info = UserDao.get_user(user_id)
        cls._system_log(
            user,
            ip_address,
            group_ids,
            EventType.UPDATE_USER,
            ObjectType.USER_CONF,
            str(user_id),
            user_info.user_name,
            note,
        )

    @classmethod
    def forbid_user(cls, user: UserPayload, ip_address: str, user_info: User):
        """
        user: Action User
        user_info: Operated by user
        """
        logger.info(f"act=forbid_user user={user.user_name} ip={ip_address} user_id={user.user_id}")
        # Get the group to which the user belongs
        user_group = UserGroupDao.get_user_group(user_info.user_id)
        user_group = [one.group_id for one in user_group]
        cls._system_log(
            user,
            ip_address,
            user_group,
            EventType.FORBID_USER,
            ObjectType.USER_CONF,
            str(user_info.user_id),
            user_info.user_name,
        )

    @classmethod
    def recover_user(cls, user: UserPayload, ip_address: str, user_info: User):
        logger.info(f"act=recover_user user={user.user_name} ip={ip_address} user_id={user_info.user_id}")
        # Get the group to which the user belongs
        user_group = UserGroupDao.get_user_group(user_info.user_id)
        user_group = [one.group_id for one in user_group]
        cls._system_log(
            user,
            ip_address,
            user_group,
            EventType.RECOVER_USER,
            ObjectType.USER_CONF,
            str(user_info.user_id),
            user_info.user_name,
        )

    @classmethod
    def create_user_group(cls, user: UserPayload, ip_address: str, group_info: Group):
        logger.info(f"act=create_user_group user={user.user_name} ip={ip_address} group_id={group_info.id}")
        cls._system_log(
            user,
            ip_address,
            [group_info.id],
            EventType.CREATE_USER_GROUP,
            ObjectType.USER_GROUP_CONF,
            str(group_info.id),
            group_info.group_name,
        )

    @classmethod
    def update_user_group(cls, user: UserPayload, ip_address: str, group_info: Group):
        logger.info(f"act=update_user_group user={user.user_name} ip={ip_address} group_id={group_info.id}")
        # Get user group information
        cls._system_log(
            user,
            ip_address,
            [group_info.id],
            EventType.UPDATE_USER_GROUP,
            ObjectType.USER_GROUP_CONF,
            str(group_info.id),
            group_info.group_name,
        )

    @classmethod
    def delete_user_group(cls, user: UserPayload, ip_address: str, group_info: Group):
        logger.info(f"act=delete_user_group user={user.user_name} ip={ip_address} group_id={group_info.id}")
        # Get user group information
        cls._system_log(
            user,
            ip_address,
            [group_info.id],
            EventType.DELETE_USER_GROUP,
            ObjectType.USER_GROUP_CONF,
            str(group_info.id),
            group_info.group_name,
        )

    @classmethod
    def create_role(cls, user: UserPayload, ip_address: str, role: Role):
        logger.info(f"act=create_role user={user.user_name} ip={ip_address} role_id={role.id}")
        user_groups = UserGroupDao.get_user_group(user.user_id)
        group_ids = [one.group_id for one in user_groups]
        cls._system_log(
            user, ip_address, group_ids, EventType.CREATE_ROLE, ObjectType.ROLE_CONF, str(role.id), role.role_name
        )

    @classmethod
    def update_role(cls, user: UserPayload, ip_address: str, role: Role):
        logger.info(f"act=update_role user={user.user_name} ip={ip_address} role_id={role.id}")
        user_groups = UserGroupDao.get_user_group(user.user_id)
        group_ids = [one.group_id for one in user_groups]
        cls._system_log(
            user, ip_address, group_ids, EventType.UPDATE_ROLE, ObjectType.ROLE_CONF, str(role.id), role.role_name
        )

    @classmethod
    def delete_role(cls, user: UserPayload, ip_address: str, role: Role):
        logger.info(f"act=delete_role user={user.user_name} ip={ip_address} role_id={role.id}")
        user_groups = UserGroupDao.get_user_group(user.user_id)
        group_ids = [one.group_id for one in user_groups]
        cls._system_log(
            user, ip_address, group_ids, EventType.DELETE_ROLE, ObjectType.ROLE_CONF, str(role.id), role.role_name
        )

    @classmethod
    def create_tool(cls, user: UserPayload, ip_address: str, group_ids: list[int], tool_type: GptsToolsType):
        logger.info(f"act=create_tool user={user.user_name} ip={ip_address} tool_type_id={tool_type.id}")

        cls._system_log(
            user, ip_address, group_ids, EventType.ADD_TOOL, ObjectType.TOOL, str(tool_type.id), tool_type.name
        )

    @classmethod
    def update_tool(cls, user: UserPayload, ip_address: str, group_ids: list[int], tool_type: GptsToolsType):
        logger.info(f"act=update_tool user={user.user_name} ip={ip_address} tool_type_id={tool_type.id}")

        cls._system_log(
            user, ip_address, group_ids, EventType.UPDATE_TOOL, ObjectType.TOOL, str(tool_type.id), tool_type.name
        )

    @classmethod
    def delete_tool(cls, user: UserPayload, ip_address: str, group_ids: list[int], tool_type: GptsToolsType):
        logger.info(f"act=delete_tool user={user.user_name} ip={ip_address} tool_type_id={tool_type.id}")
        cls._system_log(
            user, ip_address, group_ids, EventType.DELETE_TOOL, ObjectType.TOOL, str(tool_type.id), tool_type.name
        )

    @classmethod
    def user_login(cls, user: UserPayload, ip_address: str):
        logger.info(f"act=user_login user={user.user_name} ip={ip_address} user_id={user.user_id}")
        # bypass_tenant_filter: login-time audit captures the user's global
        # group membership before tenant context is established. Without
        # bypass, hotfix-3's tenant-aware user_group table trips
        # NoTenantContextError on every login.

        with bypass_tenant_filter():
            user_group = UserGroupDao.get_user_group(user.user_id)
        user_group = [one.group_id for one in user_group]
        cls._system_log(user, ip_address, user_group, EventType.USER_LOGIN, ObjectType.NONE, "", "")

    @classmethod
    async def _dashboard_log(
        cls,
        user: UserPayload,
        ip_address: str,
        group_ids: list[int],
        event_type: EventType,
        object_id: str,
        object_name: str,
    ):

        audit_log = AuditLog(
            operator_id=user.user_id,
            operator_name=user.user_name,
            group_ids=group_ids,
            system_id=SystemId.DASHBOARD.value,
            event_type=event_type.value,
            object_type=ObjectType.DASHBOARD.value,
            object_id=object_id,
            object_name=object_name,
            ip_address=ip_address,
        )
        await AuditLogDao.ainsert_audit_logs([audit_log])

    @classmethod
    async def create_dashboard(
        cls, user: UserPayload, ip_address: str, dashboard_id: str, dashboard_name: str, group_ids: list[int]
    ):
        logger.info(f"act=create_dashboard user={user.user_name} ip={ip_address} dashboard_id={dashboard_id}")
        await cls._dashboard_log(user, ip_address, group_ids, EventType.CREATE_DASHBOARD, dashboard_id, dashboard_name)

    @classmethod
    async def update_dashboard(
        cls, user: UserPayload, ip_address: str, dashboard_id: str, dashboard_name: str, group_ids: list[int]
    ):
        logger.info(f"act=update_dashboard user={user.user_name} ip={ip_address} dashboard_id={dashboard_id}")
        await cls._dashboard_log(user, ip_address, group_ids, EventType.UPDATE_DASHBOARD, dashboard_id, dashboard_name)

    @classmethod
    async def delete_dashboard(
        cls, user: UserPayload, ip_address: str, dashboard_id: str, dashboard_name: str, group_ids: list[int]
    ):
        logger.info(f"act=delete_dashboard user={user.user_name} ip={ip_address} dashboard_id={dashboard_id}")
        await cls._dashboard_log(user, ip_address, group_ids, EventType.DELETE_DASHBOARD, dashboard_id, dashboard_name)

    @classmethod
    async def create_channel(cls, user: UserPayload, ip_address: str, channel_id: str, channel_name: str):
        """
        New Channel Audit Log
        """
        logger.info(f"act=create_channel user={user.user_name} ip={ip_address} channel={channel_id}")
        user_group = await UserGroupDao.aget_user_group(user.user_id)
        group_ids = [one.group_id for one in user_group]
        audit_log = AuditLog(
            operator_id=user.user_id,
            operator_name=user.user_name,
            group_ids=group_ids,
            system_id=SystemId.SUBSCRIPTION.value,
            event_type=EventType.CREATE_CHANNEL.value,
            object_type=ObjectType.CHANNEL.value,
            object_id=channel_id,
            object_name=channel_name,
            ip_address=ip_address,
        )
        await AuditLogDao.ainsert_audit_logs([audit_log])

    @classmethod
    async def delete_channel(cls, user: UserPayload, ip_address: str, channel_id: str, channel_name: str):
        """
        Delete Channel Audit Log
        """
        logger.info(f"act=delete_channel user={user.user_name} ip={ip_address} channel={channel_id}")
        user_group = await UserGroupDao.aget_user_group(user.user_id)
        group_ids = [one.group_id for one in user_group]
        audit_log = AuditLog(
            operator_id=user.user_id,
            operator_name=user.user_name,
            group_ids=group_ids,
            system_id=SystemId.SUBSCRIPTION.value,
            event_type=EventType.DELETE_CHANNEL.value,
            object_type=ObjectType.CHANNEL.value,
            object_id=channel_id,
            object_name=channel_name,
            ip_address=ip_address,
        )
        await AuditLogDao.ainsert_audit_logs([audit_log])

    @classmethod
    async def get_filter_flow_ids(cls, user: UserPayload, flow_ids: list[str], group_ids: list[int]) -> (bool, list):
        """Filter workflow, assistant and workstation ids by visible groups."""
        flow_ids = [one for one in flow_ids]
        group_admins = []
        if not user.is_admin():
            if not await cls._user_has_log_web_menu(user):
                user_groups = await UserGroupDao.aget_user_admin_group(user.user_id)
                # Not a user group administrator, no permissions
                if not user_groups:
                    raise UnAuthorizedError.http_exception()
                group_admins = [one.group_id for one in user_groups]
        # GroupingidDoing Intersections
        if group_ids:
            if group_admins:
                # Query user group not belonging to user management, return empty
                group_admins = list(set(group_admins) & set(group_ids))
                if len(group_admins) == 0:
                    return False, []
            else:
                group_admins = group_ids

        # Get all apps under groupingID
        group_flows = []
        if group_admins:
            group_flows = await GroupResourceDao.get_groups_resource(
                group_admins,
                resource_types=[ResourceTypeEnum.WORK_FLOW, ResourceTypeEnum.ASSISTANT, ResourceTypeEnum.WORKSTATION],
            )
            # User group under user management has no resources
            if not group_flows:
                return False, []
            group_flows = [one.third_id for one in group_flows]

        # Acquire the final skillIDRestrict to list
        filter_flow_ids = []
        if flow_ids and group_flows:
            filter_flow_ids = list(set(group_flows) & set(flow_ids))
            if not filter_flow_ids:
                return False, []
        elif flow_ids:
            filter_flow_ids = flow_ids
        elif group_flows:
            filter_flow_ids = group_flows
        return True, filter_flow_ids

    @classmethod
    async def get_session_list(
        cls,
        user: UserPayload,
        flow_ids: list[str],
        user_ids: list[int],
        group_ids: list[int],
        start_date: datetime,
        end_date: datetime,
        feedback: str,
        sensitive_status: int,
        page: int,
        page_size: int,
    ) -> tuple[list[AppChatList], int]:

        if user.is_admin() or await cls._user_has_log_web_menu(user):
            # Administrator, or 角色中开启「审计」菜单：与超管同级的会话列表范围（可筛选用户组，不传则不过滤组）
            search_group_ids = group_ids or []
        else:
            # Regular users: 用户组管理员，仅能看所管组内会话
            user_managed_groups = await UserGroupDao.aget_user_admin_group(user.user_id)
            if not user_managed_groups:
                raise UnAuthorizedError.http_exception()

            managed_group_ids = {one.group_id for one in user_managed_groups}

            if group_ids:
                # Find the intersection: the intersection of the frontend requests
                valid_group_ids = list(set(group_ids) & managed_group_ids)
                if not valid_group_ids:
                    return [], 0
                search_group_ids = valid_group_ids
            else:
                # Default: All managed groups
                search_group_ids = list(managed_group_ids)

        tenant_scope = cls._get_audit_tenant_scope(user)

        conditions = []

        # v2.5.0 audit isolation: Tenant Admin (and anyone scoped) sees only
        # sessions whose creator's leaf tenant matches their tenant. Without
        # this the F012 IN-list lets Child users read Root sessions too.
        if tenant_scope is not None:
            conditions.append(MessageSession.tenant_id == tenant_scope)

        # Basic equality/range filtering
        if sensitive_status:
            conditions.append(MessageSession.sensitive_status == sensitive_status)

        if user_ids:
            conditions.append(col(MessageSession.user_id).in_(user_ids))

        if start_date:
            conditions.append(col(MessageSession.create_time) >= start_date)
        if end_date:
            conditions.append(col(MessageSession.create_time) <= end_date)

        if flow_ids:
            conditions.append(col(MessageSession.flow_id).in_(flow_ids))

        # Process type filtering (fixed enumeration)
        conditions.append(
            col(MessageSession.flow_type).in_(
                [FlowType.WORKFLOW.value, FlowType.ASSISTANT.value, FlowType.WORKSTATION.value]
            )
        )

        # Feedback status filtering
        feedback_map = {
            "like": col(MessageSession.like) > 0,
            "dislike": col(MessageSession.dislike) > 0,
            "copied": col(MessageSession.copied) > 0,
        }
        if feedback in feedback_map:
            conditions.append(feedback_map[feedback])

        # Group membership filtering
        if search_group_ids:
            dialect = _db_dialect()
            group_filters = [
                json_array_contains(MessageSession.group_ids, str(gid), dialect) for gid in search_group_ids
            ]
            conditions.append(or_(*group_filters))

        # build query statement
        statement = select(MessageSession).where(and_(*conditions)).order_by(col(MessageSession.create_time).desc())

        res_task = MessageSessionDao.get_statement_results(statement, page=page, limit=page_size)
        total_task = MessageSessionDao.get_statement_count(statement)

        res, total = await asyncio.gather(res_task, total_task)

        if not res:
            return [], total

        target_user_ids = set()
        target_flow_ids = set()  # Flow/Workflow
        target_assistant_ids = set()  # Assistant

        for session in res:
            target_user_ids.add(session.user_id)
            if session.flow_type in [FlowType.WORKFLOW.value, FlowType.WORKSTATION.value]:
                target_flow_ids.add(session.flow_id)
            elif session.flow_type == FlowType.ASSISTANT.value:
                target_assistant_ids.add(session.flow_id)

        target_user_ids_list = list(target_user_ids)

        async def get_users_groups_map(u_ids: list[int]):
            # get user groups for multiple users
            if not u_ids:
                return {}
            tasks = [user.get_user_groups(uid) for uid in u_ids]
            results = await asyncio.gather(*tasks)
            return dict(zip(u_ids, results))

        users_data, flows_data, assistants_data, user_groups_map = await asyncio.gather(
            UserDao.aget_user_by_ids(target_user_ids_list),
            FlowDao.aget_flow_by_ids(list(target_flow_ids)),
            AssistantDao.aget_assistants_by_ids(list(target_assistant_ids)),
            get_users_groups_map(target_user_ids_list),
        )

        user_map = {u.user_id: u.user_name for u in users_data}
        flow_map = {f.id: f.name for f in flows_data}
        assistant_map = {a.id: a.name for a in assistants_data}

        # Construct the return object
        result: list[AppChatList] = []

        for session in res:
            # Determine the current name
            current_name = session.flow_name
            if session.flow_type in [FlowType.WORKFLOW.value, FlowType.WORKSTATION.value]:
                current_name = flow_map.get(session.flow_id, current_name)
            elif session.flow_type == FlowType.ASSISTANT.value:
                current_name = assistant_map.get(session.flow_id, current_name)

            # Append to the result set
            result.append(
                AppChatList(
                    **session.model_dump(exclude={"flow_name"}),
                    flow_name=current_name,
                    like_count=session.like,
                    dislike_count=session.dislike,
                    copied_count=session.copied,
                    user_name=user_map.get(session.user_id, ""),  # get user name
                    user_groups=user_groups_map.get(session.user_id, []),
                )
            )

        return result, total

    @classmethod
    async def get_session_messages(
        cls,
        user: UserPayload,
        flow_ids: list[str],
        user_ids: list[int],
        group_ids: list[int],
        start_date: datetime,
        end_date: datetime,
        feedback: str,
        sensitive_status: int,
    ) -> list[AppChatList]:
        page = 1
        page_size = 50
        res = []
        while True:
            result, total = await cls.get_session_list(
                user, flow_ids, user_ids, group_ids, start_date, end_date, feedback, sensitive_status, page, page_size
            )
            if not result:
                break
            page += 1
            res.extend(await cls.get_chat_messages(result))
        return res

    @classmethod
    async def get_chat_messages(cls, chat_list: list[AppChatList]) -> list[AppChatList]:
        chat_ids = [chat.chat_id for chat in chat_list]

        chat_messages = await ChatMessageDao.get_all_message_by_chat_ids(chat_ids)
        chat_messages_map = {}
        for one in chat_messages:
            if one.chat_id not in chat_messages_map:
                chat_messages_map[one.chat_id] = []
            chat_messages_map[one.chat_id].append(one)
        for chat in chat_list:
            chat_messages = chat_messages_map.get(chat.chat_id, [])
            # remove workflow input event, because it's not show in web
            chat.messages = [
                message for message in chat_messages if message.category != WorkflowEventType.UserInput.value
            ]
        return chat_list
