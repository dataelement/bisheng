import asyncio
from collections.abc import Sequence
from datetime import datetime
from time import perf_counter

from fastapi.encoders import jsonable_encoder
from langchain_classic.memory import ConversationBufferWindowMemory
from loguru import logger

from bisheng.api.v1.schema.workflow import (
    WorkflowEvent,
    WorkflowEventType,
    WorkflowInputItem,
    WorkflowInputSchema,
    WorkflowOutputSchema,
)
from bisheng.api.v1.schemas import ChatResponse
from bisheng.common.chat.utils import SourceType
from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.flow import WorkFlowInitError
from bisheng.common.errcode.http_error import NotFoundError, UnAuthorizedError
from bisheng.common.services import telemetry_service
from bisheng.common.services.base import BaseService
from bisheng.core.context.tenant import DEFAULT_TENANT_ID, get_admin_scope_tenant_id, get_current_tenant_id
from bisheng.core.logger import trace_id_var
from bisheng.database.models.flow import Flow, FlowDao, FlowStatus, FlowType, UserLinkType
from bisheng.database.models.flow_version import FlowVersionDao
from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.role_access import AccessType
from bisheng.database.models.tag import TagBusinessTypeEnum, TagDao
from bisheng.database.models.user_link import UserLinkDao
from bisheng.permission.domain.services.application_permission_service import ApplicationPermissionService
from bisheng.permission.domain.workflow_app_permission import (
    batch_user_may_share_app,
    object_type_for_flow_type,
)
from bisheng.user.domain.models.user import UserDao
from bisheng.utils import generate_uuid
from bisheng.workflow.callback.base_callback import BaseCallback
from bisheng.workflow.common.node import BaseNodeData, NodeType
from bisheng.workflow.graph.graph_state import GraphState
from bisheng.workflow.graph.workflow import Workflow
from bisheng.workflow.nodes.node_manage import NodeFactory

# F027: when ReBAC fine-grained filtering shrinks a DB batch, refetch via keyset
# to fill the requested page_size. Batch size balances DB round-trips against
# wasted permission lookups when most rows are filtered out.
_FLOW_PERMISSION_SCAN_BATCH_SIZE = 50


class WorkFlowService(BaseService):
    SUPPORTED_APP_TYPES = {FlowType.WORKFLOW.value, FlowType.ASSISTANT.value}
    _APP_PERMISSION_TO_MIN_RELATION = {
        "view_app": "can_read",
        "use_app": "can_read",
        "edit_app": "can_edit",
        "delete_app": "can_delete",
        "publish_app": "can_manage",
        "unpublish_app": "can_manage",
        "share_app": "can_manage",
        "manage_app_owner": "can_manage",
        "manage_app_manager": "can_manage",
        "manage_app_viewer": "can_manage",
    }

    @classmethod
    def filter_supported_apps(cls, data: list[dict]) -> list[dict]:
        return [one for one in data if one.get("flow_type") in cls.SUPPORTED_APP_TYPES]

    @staticmethod
    def _is_scoped_super_admin(user: UserPayload) -> bool:
        current_tid = get_current_tenant_id()
        return bool(
            getattr(user, "is_global_super", False)
            and get_admin_scope_tenant_id() is not None
            and current_tid is not None
            and current_tid != DEFAULT_TENANT_ID
        )

    @classmethod
    def add_extra_field(
        cls,
        user: UserPayload,
        data: list[dict],
        managed: bool = False,
        writeable_ids: set[str] | None = None,
    ) -> list[dict]:
        """Add some extra fields for app list"""
        data = cls.filter_supported_apps(data)
        # ApplicationsIDVertical
        resource_ids = []
        # Skill Creation User'sIDVertical
        user_ids = []
        for one in data:
            one["id"] = one["id"]
            resource_ids.append(one["id"])
            user_ids.append(one["user_id"])
        # Get user information in the list
        user_infos = UserDao.get_user_by_ids(user_ids)
        user_dict = {one.user_id: one.user_name for one in user_infos}

        # Get version information in the list
        version_infos = FlowVersionDao.get_list_by_flow_ids(resource_ids)
        flow_versions = {}
        for one in version_infos:
            if one.flow_id not in flow_versions:
                flow_versions[one.flow_id] = []
            flow_versions[one.flow_id].append(jsonable_encoder(one))

        resource_tag_dict = TagDao.get_tags_by_resource(None, resource_ids)

        # Add additional information (F008: removed group_ids, AC-08)
        for one in data:
            if one["flow_type"] == FlowType.WORKFLOW.value:
                access_type = AccessType.WORKFLOW_WRITE
            else:
                access_type = AccessType.ASSISTANT_WRITE

            one["user_name"] = user_dict.get(one["user_id"], one["user_id"])
            if managed:
                one["write"] = True
            elif writeable_ids is not None:
                one["write"] = str(one["id"]) in writeable_ids
            else:
                one["write"] = user.access_check(one["user_id"], one["id"], access_type)
            one["version_list"] = flow_versions.get(one["id"], [])
            one["tags"] = resource_tag_dict.get(one["id"], [])
            one["logo"] = cls.get_logo_share_link(one["logo"])
        return data

    @classmethod
    async def aenrich_apps_can_share(cls, user: UserPayload, data: list[dict], managed: bool = False) -> list[dict]:
        """Set ``can_share`` from ReBAC relation-model ``share_app`` (fail-closed when unknown type)."""
        if not data:
            return data
        if (user.is_admin() and not cls._is_scoped_super_admin(user)) or managed:
            for one in data:
                one["can_share"] = True
            return data
        entries: list[tuple[dict, str | None]] = []
        pairs: list[tuple[str, str]] = []
        for one in data:
            ot = object_type_for_flow_type(int(one.get("flow_type") or 0))
            entries.append((one, ot))
            if ot:
                pairs.append((ot, str(one["id"])))
        if not pairs:
            for one, ot in entries:
                one["can_share"] = False
            return data
        flags = await batch_user_may_share_app(user, pairs)
        fi = 0
        for one, ot in entries:
            if not ot:
                one["can_share"] = False
            else:
                one["can_share"] = bool(flags[fi])
                fi += 1
        return data

    @classmethod
    async def get_all_flows(
        cls,
        user: UserPayload,
        name: str,
        status: int,
        tag_id: int | None,
        flow_type: int | None,
        page: int = 1,
        page_size: int = 10,
        managed: bool = False,
        skip_pagination: bool = False,
        search_description: bool = False,
        permission_id: str = "use_app",
        cursor: Sequence | None = None,
    ) -> tuple[list[dict], bool]:
        """Get all the skills (async, ReBAC + 部门管理员隐式可见 兼容)."""
        total_start = perf_counter()
        if flow_type is not None and flow_type not in cls.SUPPORTED_APP_TYPES:
            return [], False
        scoped_super_admin = cls._is_scoped_super_admin(user)

        # SetujutagDapatkanidVertical
        flow_ids = []
        if tag_id:
            ret = TagDao.get_resources_by_tags_batch([tag_id], [ResourceTypeEnum.WORK_FLOW, ResourceTypeEnum.ASSISTANT])
            if not ret:
                return [], False
            flow_ids = [one.resource_id for one in ret]

        query_page = page
        query_page_size = page_size
        if skip_pagination:
            query_page = 0
            query_page_size = 0

        readable_type_ids = None
        if not user.is_admin() or scoped_super_admin:
            required_permission = "edit_app" if managed else permission_id
            prefilter_start = perf_counter()
            readable_type_ids = await cls._app_type_ids_for_permission(user, required_permission, flow_type)
            logger.info(
                "[perf][workflow.list.prefilter] user_id={} flow_type={} managed={} permission_id={} "
                "workflow_ids={} assistant_ids={} took_ms={:.2f}",
                user.user_id,
                flow_type,
                managed,
                required_permission,
                len((readable_type_ids or {}).get(FlowType.WORKFLOW.value, []) or []),
                len((readable_type_ids or {}).get(FlowType.ASSISTANT.value, []) or []),
                (perf_counter() - prefilter_start) * 1000,
            )

        # Get a list of skills visible to the user
        dao_start = perf_counter()
        if user.is_admin() and not scoped_super_admin:
            data, has_more = await FlowDao.aget_all_apps(
                name,
                status,
                flow_ids,
                flow_type,
                None,
                None,
                None,
                query_page,
                query_page_size,
                search_description=search_description,
                cursor=cursor,
            )
        else:
            data, has_more = await FlowDao.aget_all_apps(
                name,
                status,
                flow_ids,
                flow_type,
                None,
                None,
                None,
                query_page,
                query_page_size,
                search_description=search_description,
                app_type_ids=readable_type_ids,
                cursor=cursor,
            )
        logger.info(
            "[perf][workflow.list.dao] user_id={} flow_type={} page={} page_size={} skip_pagination={} "
            "tag_filter_count={} rows={} has_more={} took_ms={:.2f}",
            user.user_id,
            flow_type,
            page,
            page_size,
            skip_pagination,
            len(flow_ids),
            len(data),
            has_more,
            (perf_counter() - dao_start) * 1000,
        )
        data = cls.filter_supported_apps(data)
        writeable_ids: set[str] | None = None
        if (not user.is_admin() or scoped_super_admin) and data:
            required_permission = "edit_app" if managed else permission_id
            permission_map_start = perf_counter()
            permission_map = await ApplicationPermissionService.get_app_permission_map_async(
                user,
                data,
                list(dict.fromkeys([required_permission, "edit_app"])),
            )
            data = [one for one in data if required_permission in permission_map.get(str(one.get("id")), set())]
            writeable_ids = {
                str(app_id) for app_id, permission_ids in permission_map.items() if "edit_app" in permission_ids
            }
            logger.info(
                "[perf][workflow.list.permission_map] user_id={} flow_type={} rows={} kept={} writeable={} "
                "permission_id={} took_ms={:.2f}",
                user.user_id,
                flow_type,
                len(permission_map),
                len(data),
                len(writeable_ids),
                required_permission,
                (perf_counter() - permission_map_start) * 1000,
            )
        enrich_start = perf_counter()
        data = cls.add_extra_field(user, data, managed, writeable_ids=writeable_ids)
        logger.info(
            "[perf][workflow.list.enrich] user_id={} flow_type={} rows={} took_ms={:.2f}",
            user.user_id,
            flow_type,
            len(data),
            (perf_counter() - enrich_start) * 1000,
        )
        logger.info(
            "[perf][workflow.list.total] user_id={} flow_type={} page={} page_size={} skip_pagination={} "
            "managed={} permission_id={} rows={} has_more={} took_ms={:.2f}",
            user.user_id,
            flow_type,
            page,
            page_size,
            skip_pagination,
            managed,
            permission_id,
            len(data),
            has_more,
            (perf_counter() - total_start) * 1000,
        )
        # data = await cls.aenrich_apps_can_share(user, data, managed)  # because frontend not need and this cost most time
        return data, has_more

    @classmethod
    async def _scan_visible_flows_cursor(
        cls,
        *,
        user: UserPayload,
        name: str | None,
        status: int | None,
        flow_ids: list[str],
        flow_type: int | None,
        cursor: Sequence | None,
        page_size: int,
        managed: bool,
        search_description: bool,
        permission_id: str,
        readable_type_ids: dict[int, list[str]] | None,
        is_admin_bypass: bool,
        required_permission: str,
    ) -> tuple[list[dict], bool, set[str]]:
        """F027 cursor-paginated scan for /workflow/list: keep fetching DB
        batches via keyset, apply ReBAC fine-grained filtering, accumulate
        until we have ``page_size + 1`` visible items (the +1 probes
        ``has_more``) or the DB is exhausted.

        Returns ``(visible_items[:page_size], has_more, writeable_ids)`` —
        ``writeable_ids`` aggregates across all scanned batches so the
        ``can_write`` flag in the response stays accurate.
        """
        visible: list[dict] = []
        writeable_ids: set[str] = set()
        batch_cursor: list | None = list(cursor) if cursor else None

        while True:
            dao_start = perf_counter()
            batch, db_has_more = await FlowDao.aget_all_apps(
                name,
                status,
                flow_ids,
                flow_type,
                None,
                None,
                None,
                0,  # cursor mode bypasses OFFSET
                _FLOW_PERMISSION_SCAN_BATCH_SIZE,
                search_description=search_description,
                app_type_ids=readable_type_ids,
                cursor=batch_cursor,
            )
            logger.info(
                "[perf][workflow.list.dao] user_id={} flow_type={} batch_size={} rows={} db_has_more={} took_ms={:.2f}",
                user.user_id,
                flow_type,
                _FLOW_PERMISSION_SCAN_BATCH_SIZE,
                len(batch),
                db_has_more,
                (perf_counter() - dao_start) * 1000,
            )

            batch = cls.filter_supported_apps(batch)
            if not batch:
                return visible[:page_size], False, writeable_ids

            if is_admin_bypass:
                kept = batch
            else:
                permission_map_start = perf_counter()
                permission_map = await ApplicationPermissionService.get_app_permission_map_async(
                    user,
                    batch,
                    list(dict.fromkeys([required_permission, "edit_app"])),
                )
                kept = [one for one in batch if required_permission in permission_map.get(str(one.get("id")), set())]
                writeable_ids |= {str(app_id) for app_id, perms in permission_map.items() if "edit_app" in perms}
                logger.info(
                    "[perf][workflow.list.permission_map] user_id={} flow_type={} rows={} kept={} writeable={} "
                    "permission_id={} took_ms={:.2f}",
                    user.user_id,
                    flow_type,
                    len(batch),
                    len(kept),
                    len(writeable_ids),
                    required_permission,
                    (perf_counter() - permission_map_start) * 1000,
                )

            for item in kept:
                visible.append(item)
                if len(visible) > page_size:
                    # Got the +1 probe — done scanning.
                    return visible[:page_size], True, writeable_ids

            if not db_has_more:
                return visible[:page_size], False, writeable_ids

            # Advance batch_cursor to the LAST DB row of this batch (not last
            # visible) so the next batch picks up strictly after; if we used
            # the last visible, items filtered out between them would be
            # re-emitted on the next batch.
            last_db = batch[-1]
            batch_cursor = [last_db["update_time"], last_db["id"]]

    @classmethod
    async def get_all_flows_envelope(
        cls,
        user: UserPayload,
        name: str | None,
        status: int | None,
        tag_id: int | None,
        flow_type: int | None,
        cursor: str | None = None,
        page_size: int = 10,
        managed: bool = False,
        search_description: bool = False,
        permission_id: str = "use_app",
    ) -> "PageInfiniteCursorData":
        """F027 cursor envelope wrapper for ``/api/v1/workflow/list``.

        Decodes the cursor, runs a fetch-until-enough scan loop (so a DB
        batch shrunken by fine-grained ReBAC filtering is refilled from the
        next keyset window), then wraps the result into
        ``PageInfiniteCursorData`` with ``next_cursor`` derived from the last
        visible row's ``(update_time, id)``.
        """
        from bisheng.common.cursor import CursorDecodeError, decode_cursor, encode_cursor
        from bisheng.common.errcode.flow import AppInvalidCursorError
        from bisheng.common.schemas.api import PageInfiniteCursorData

        total_start = perf_counter()
        context = "flow|sort=update_time"
        try:
            decoded = decode_cursor(
                cursor,
                expected_key_len=2,
                expected_context=context,
            )
        except CursorDecodeError as exc:
            raise AppInvalidCursorError(exception=exc)

        if flow_type is not None and flow_type not in cls.SUPPORTED_APP_TYPES:
            return PageInfiniteCursorData(data=[], page_size=page_size, has_more=False, next_cursor=None)

        # Tag-based prefilter: empty match short-circuits to empty page.
        flow_ids: list[str] = []
        if tag_id:
            ret = TagDao.get_resources_by_tags_batch([tag_id], [ResourceTypeEnum.WORK_FLOW, ResourceTypeEnum.ASSISTANT])
            if not ret:
                return PageInfiniteCursorData(data=[], page_size=page_size, has_more=False, next_cursor=None)
            flow_ids = [one.resource_id for one in ret]

        scoped_super_admin = cls._is_scoped_super_admin(user)
        is_admin_bypass = user.is_admin() and not scoped_super_admin
        required_permission = "edit_app" if managed else permission_id

        readable_type_ids: dict[int, list[str]] | None = None
        if not is_admin_bypass:
            prefilter_start = perf_counter()
            readable_type_ids = await cls._app_type_ids_for_permission(user, required_permission, flow_type)
            logger.info(
                "[perf][workflow.list.prefilter] user_id={} flow_type={} managed={} permission_id={} "
                "workflow_ids={} assistant_ids={} took_ms={:.2f}",
                user.user_id,
                flow_type,
                managed,
                required_permission,
                len((readable_type_ids or {}).get(FlowType.WORKFLOW.value, []) or []),
                len((readable_type_ids or {}).get(FlowType.ASSISTANT.value, []) or []),
                (perf_counter() - prefilter_start) * 1000,
            )

        data, has_more, writeable_ids = await cls._scan_visible_flows_cursor(
            user=user,
            name=name,
            status=status,
            flow_ids=flow_ids,
            flow_type=flow_type,
            cursor=decoded,
            page_size=page_size,
            managed=managed,
            search_description=search_description,
            permission_id=permission_id,
            readable_type_ids=readable_type_ids,
            is_admin_bypass=is_admin_bypass,
            required_permission=required_permission,
        )

        enrich_start = perf_counter()
        data = cls.add_extra_field(
            user,
            data,
            managed,
            writeable_ids=None if is_admin_bypass else writeable_ids,
        )
        logger.info(
            "[perf][workflow.list.enrich] user_id={} flow_type={} rows={} took_ms={:.2f}",
            user.user_id,
            flow_type,
            len(data),
            (perf_counter() - enrich_start) * 1000,
        )
        logger.info(
            "[perf][workflow.list.total] user_id={} flow_type={} page_size={} managed={} permission_id={} "
            "rows={} has_more={} took_ms={:.2f}",
            user.user_id,
            flow_type,
            page_size,
            managed,
            permission_id,
            len(data),
            has_more,
            (perf_counter() - total_start) * 1000,
        )

        next_cursor: str | None = None
        if has_more and data:
            last = data[-1]
            # F027: app listing is a UNION of workflows (int id) and
            # assistants (UUID hex string id); pass the raw id through —
            # encode_cursor JSON-serialises either type, and the keyset
            # WHERE compares against ``sub_query.c.id`` whose column type
            # absorbs both via SQLAlchemy literal binding.
            next_cursor = encode_cursor(
                (last["update_time"], last["id"]),
                context=context,
            )
        return PageInfiniteCursorData(
            data=data,
            page_size=page_size,
            has_more=has_more,
            next_cursor=next_cursor,
        )

    @classmethod
    def _relation_for_app_permission(cls, permission_id: str) -> str:
        return cls._APP_PERMISSION_TO_MIN_RELATION.get(permission_id, "can_read")

    @classmethod
    async def _app_type_ids_for_permission(
        cls,
        user: UserPayload,
        permission_id: str,
        flow_type: int | None,
    ) -> dict[int, list[str]]:
        from bisheng.permission.domain.services.permission_service import PermissionService

        relation = cls._relation_for_app_permission(permission_id)
        targets: list[tuple[int, str]] = []
        if flow_type in (None, FlowType.WORKFLOW.value):
            targets.append((FlowType.WORKFLOW.value, "workflow"))
        if flow_type in (None, FlowType.ASSISTANT.value):
            targets.append((FlowType.ASSISTANT.value, "assistant"))

        fga_results, binding_type_ids = await asyncio.gather(
            asyncio.gather(
                *[
                    PermissionService.list_accessible_ids(
                        user_id=user.user_id,
                        relation=relation,
                        object_type=object_type,
                        login_user=user,
                    )
                    for _, object_type in targets
                ]
            ),
            ApplicationPermissionService.get_bound_app_type_ids_async(
                user,
                [permission_id],
                flow_type,
            ),
        )

        app_type_ids: dict[int, list[str]] = {}
        for (app_type, _), ids in zip(targets, fga_results):
            merged = [
                *(str(one) for one in (ids or [])),
                *(str(one) for one in binding_type_ids.get(app_type, [])),
            ]
            app_type_ids[app_type] = list(dict.fromkeys(merged))
        return app_type_ids

    @staticmethod
    def _has_any_app_type_ids(app_type_ids: dict[int, list[str]] | None) -> bool:
        return any(app_type_ids.values()) if app_type_ids else False

    @classmethod
    async def filter_apps_by_permission_id(
        cls,
        user: UserPayload,
        data: list[dict],
        permission_id: str = "use_app",
    ) -> list[dict]:
        if (user.is_admin() and not cls._is_scoped_super_admin(user)) or not data:
            return data
        permission_map = await ApplicationPermissionService.get_app_permission_map_async(
            user,
            data,
            [permission_id],
        )
        return [one for one in data if permission_id in permission_map.get(str(one.get("id")), set())]

    @classmethod
    def run_once(cls, login_user: UserPayload, node_input: dict[str, any], node_data: dict[any, any], workflow_id: str):
        workflow_info = FlowDao.get_flow_by_id(workflow_id)
        if not workflow_info:
            raise NotFoundError()
        if not ApplicationPermissionService.has_any_permission_sync(
            login_user,
            "workflow",
            str(workflow_info.id),
            ["edit_app"],
        ):
            raise UnAuthorizedError()

        node_data = BaseNodeData(**node_data.get("data", {}))
        base_callback = BaseCallback()
        graph_state = GraphState()
        graph_state.history_memory = ConversationBufferWindowMemory(k=10)
        node = NodeFactory.instance_node(
            node_type=node_data.type,
            node_data=node_data,
            user_id=login_user.user_id,
            workflow_id=workflow_info.id,
            workflow_name=workflow_info.name,
            graph_state=graph_state,
            target_edges=None,
            max_steps=233,
            callback=base_callback,
        )
        if node_data.type == NodeType.CODE.value:
            node.handle_input({"code_input": [{"key": k, "value": v, "type": "input"} for k, v in node_input.items()]})
        elif node_data.type == NodeType.TOOL.value:
            user_input = {}
            for k, v in node_input.items():
                user_input[k] = v
            node.handle_input(user_input)
        else:
            for key, val in node_input.items():
                graph_state.set_variable_by_str(key, val)

        exec_id = generate_uuid()
        result = node._run(exec_id)
        log_data = node.parse_log(exec_id, result)
        res = []
        for one_batch in log_data:
            ret = []
            for one in one_batch:
                if node_data.type == NodeType.QA_RETRIEVER.value and one["key"] != "retrieved_result":
                    continue
                if (
                    node_data.type == NodeType.RAG.value
                    and one["key"] != "retrieved_result"
                    and one["type"] != "variable"
                ):
                    continue
                if node_data.type == NodeType.LLM.value and one["type"] != "variable":
                    continue
                if node_data.type == NodeType.AGENT.value and one["type"] not in ["tool", "variable"]:
                    continue
                if node_data.type == NodeType.CODE.value and one["key"] != "code_output":
                    continue
                if node_data.type == NodeType.TOOL.value and one["key"] != "output":
                    continue
                ret.append({"key": one["key"], "value": one["value"], "type": one["type"]})
            res.append(ret)
        return res

    @classmethod
    async def update_flow_status(cls, login_user: UserPayload, flow_id: str, version_id: int, status: int):
        """
        Modify workflow status, Also modify the current version of the workflow
        """
        db_flow = await FlowDao.aget_flow_by_id(flow_id)
        if not db_flow:
            raise NotFoundError()
        required_permission = "publish_app" if status == FlowStatus.ONLINE.value else "unpublish_app"
        if not await ApplicationPermissionService.has_any_permission_async(
            login_user,
            "workflow",
            str(flow_id),
            [required_permission],
        ):
            raise UnAuthorizedError()

        version_info = await FlowVersionDao.aget_version_by_id(version_id)
        if not version_info or version_info.flow_id != flow_id:
            raise NotFoundError()
        if status == FlowStatus.ONLINE.value:
            # workflowInitialization check for
            try:
                _ = Workflow(flow_id, db_flow.name, login_user.user_id, version_info.data, False, 10, 10, None)
            except Exception as e:
                raise WorkFlowInitError(msg=str(e))

            await FlowVersionDao.change_current_version(flow_id, version_info)
        db_flow.status = status
        await FlowDao.aupdate_flow(db_flow)
        await telemetry_service.log_event(
            user_id=login_user.user_id, event_type=BaseTelemetryTypeEnum.EDIT_APPLICATION, trace_id=trace_id_var.get()
        )
        return

    @classmethod
    def convert_chat_response_to_workflow_event(cls, chat_response: ChatResponse) -> WorkflowEvent:
        workflow_event = WorkflowEvent(
            event=chat_response.category,
            message_id=chat_response.message_id,
            status="end",
            node_id=chat_response.message.get("node_id"),
            node_name=chat_response.message.get("name"),
            node_execution_id=chat_response.message.get("unique_id"),
        )
        match workflow_event.event:
            case WorkflowEventType.UserInput.value:
                return cls.convert_user_input_event(chat_response, workflow_event)
            case WorkflowEventType.GuideWord.value:
                workflow_event.output_schema = WorkflowOutputSchema(message=chat_response.message.get("guide_word"))
            case WorkflowEventType.GuideQuestion.value:
                workflow_event.output_schema = WorkflowOutputSchema(message=chat_response.message.get("guide_question"))
            case WorkflowEventType.OutputMsg.value:
                return cls.convert_output_event(chat_response, workflow_event)
            case WorkflowEventType.OutputWithChoose.value:
                return cls.convert_output_choose_event(chat_response, workflow_event)
            case WorkflowEventType.OutputWithInput.value:
                return cls.convert_output_input_event(chat_response, workflow_event)
            case WorkflowEventType.StreamMsg.value:
                workflow_event.status = chat_response.type
                workflow_event.output_schema = WorkflowOutputSchema(
                    message=chat_response.message.get("msg"),
                    reasoning_content=chat_response.message.get("reasoning_content"),
                    output_key=chat_response.message.get("output_key"),
                )
                cls.handle_source(chat_response, workflow_event)
            case WorkflowEventType.Error.value:
                workflow_event.event = WorkflowEventType.Close.value
                workflow_event.output_schema = WorkflowOutputSchema(message=chat_response.message)

        return workflow_event

    @classmethod
    def handle_source(cls, chat_response: ChatResponse, workflow_event: WorkflowEvent):
        if chat_response.source in [SourceType.LINK.value, SourceType.QA.value]:
            workflow_event.output_schema.extra = chat_response.extra

    @classmethod
    def convert_user_input_event(cls, chat_response: ChatResponse, workflow_event: WorkflowEvent) -> WorkflowEvent:
        event_input_schema = chat_response.message.get("input_schema")
        input_schema = WorkflowInputSchema(
            input_type=event_input_schema.get("tab"),
        )
        if input_schema.input_type == "form_input":
            # Front-end form definitions go to back-end form definitions
            input_schema.value = [WorkflowInputItem(**one) for one in event_input_schema.get("value", [])]
            for one in input_schema.value:
                one.label = one.value
                one.value = ""
        else:
            # Description is input box input
            input_schema.value = [
                WorkflowInputItem(key=event_input_schema.get("key"), type="text", required=True, value="")
            ]
            for one in event_input_schema.get("value", []):
                if not one:
                    continue
                tmp = WorkflowInputItem(**one)
                if tmp.key == "dialog_files_content":
                    tmp.type = "dialog_file"
                    tmp.value = []
                elif tmp.key == "dialog_file_accept":
                    tmp.type = "dialog_file_accept"
                input_schema.value.append(tmp)
        workflow_event.input_schema = input_schema
        return workflow_event

    @classmethod
    def convert_output_event(cls, chat_response: ChatResponse, workflow_event: WorkflowEvent) -> WorkflowEvent:
        workflow_event.output_schema = WorkflowOutputSchema(
            message=chat_response.message.get("msg"),
            files=chat_response.files,
            output_key=chat_response.message.get("output_key"),
        )
        cls.handle_source(chat_response, workflow_event)
        return workflow_event

    @classmethod
    def convert_output_input_event(cls, chat_response: ChatResponse, workflow_event: WorkflowEvent) -> WorkflowEvent:
        workflow_event = cls.convert_output_event(chat_response, workflow_event)
        workflow_event.input_schema = WorkflowInputSchema(
            input_type="message_inline_input",
            value=[
                WorkflowInputItem(
                    key=chat_response.message.get("key"),
                    type="text",
                    required=True,
                    value=chat_response.message.get("input_msg", ""),
                )
            ],
        )
        return workflow_event

    @classmethod
    def convert_output_choose_event(cls, chat_response: ChatResponse, workflow_event: WorkflowEvent) -> WorkflowEvent:
        workflow_event = cls.convert_output_event(chat_response, workflow_event)
        workflow_event.input_schema = WorkflowInputSchema(
            input_type="message_inline_option",
            value=[
                WorkflowInputItem(
                    key=chat_response.message.get("key"),
                    type="select",
                    required=True,
                    value="",
                    options=chat_response.message.get("options", []),
                )
            ],
        )
        return workflow_event

    @classmethod
    async def get_frequently_used_flows(
        cls, user: UserPayload, user_link_type: str, page: int = 1, page_size: int = 8
    ) -> (list[dict], int):
        """
        Get common skills
        """
        # Setujuuser_idAndtagDapatkanidlist and keep pressingcreate_timeAscending order
        flow_ids = []
        user_link_order = {}  # Record the order of each app in the common list of users

        ret = UserLinkDao.get_user_link(user.user_id, [app_type.value for app_type in UserLinkType.app.value])
        if not ret:
            return [], 0

        # Save original order andflow_ids
        for index, user_link in enumerate(ret):
            flow_ids.append(user_link.type_detail)
            user_link_order[user_link.type_detail] = index

        # Get a list of skills visible to the user (no pagination as we need to sort manually)
        if user.is_admin():
            data, _ = FlowDao.get_all_apps(status=FlowStatus.ONLINE.value, id_list=flow_ids, page=0, limit=0)
        else:
            data, _ = FlowDao.get_all_apps(status=FlowStatus.ONLINE.value, id_list=flow_ids, page=0, limit=0)
        data = cls.filter_supported_apps(data)
        data = await cls.filter_apps_by_permission_id(user, data, "view_app")

        # Reorder users in the order they are added to the stock
        data.sort(key=lambda x: user_link_order.get(x["id"], float("inf")))

        # Manual pagination
        total = len(data)
        start_index = (page - 1) * page_size
        end_index = start_index + page_size
        data = data[start_index:end_index]

        data = cls.add_extra_field(user, data)
        data = await cls.aenrich_apps_can_share(user, data)

        return data, total

    @classmethod
    def delete_frequently_used_flows(cls, user: UserPayload, user_link_type: str, type_detail: str):
        UserLinkDao.delete_user_link(user.user_id, user_link_type, type_detail)
        return True

    @classmethod
    def add_frequently_used_flows(cls, user: UserPayload, user_link_type: str, type_detail: str):
        user_link, is_new = UserLinkDao.add_user_link(user.user_id, user_link_type, type_detail)
        return is_new

    @classmethod
    async def get_uncategorized_flows(
        cls,
        user: UserPayload,
        page: int = 1,
        page_size: int = 8,
        keyword: str | None = None,
    ) -> tuple[list, int]:
        """
        Get a list of unsorted skills
        """
        # SetujutagDapatkanidVertical
        all_tags = TagDao.search_tags(
            None, 0, 0, business_type=TagBusinessTypeEnum.APPLICATION, business_id=TagBusinessTypeEnum.APPLICATION.value
        )
        tag_id = [tag.id for tag in all_tags]
        flow_ids_not_in = []
        if tag_id:
            ret = TagDao.get_resources_by_tags_batch(tag_id, [ResourceTypeEnum.WORK_FLOW, ResourceTypeEnum.ASSISTANT])
            if not ret:
                return [], 0
            flow_ids_not_in = [one.resource_id for one in ret]

        # Get a list of skills visible to the user
        if user.is_admin():
            data, _ = FlowDao.get_all_apps(
                keyword, FlowStatus.ONLINE.value, None, None, None, None, flow_ids_not_in, 0, 0
            )
        else:
            data, _ = FlowDao.get_all_apps(
                keyword, FlowStatus.ONLINE.value, None, None, None, None, flow_ids_not_in, 0, 0
            )
        data = cls.filter_supported_apps(data)
        data = await cls.filter_apps_by_permission_id(user, data, "view_app")
        total = len(data)
        start_index = (page - 1) * page_size
        end_index = start_index + page_size
        data = data[start_index:end_index]

        # <g id="Bold">Medical Treatment:</g>logo URL, convert relative paths to full accessible links
        for one in data:
            one["logo"] = cls.get_logo_share_link(one["logo"])

        data = await cls.aenrich_apps_can_share(user, data)

        return data, total

    @classmethod
    async def get_one_workflow_simple_info(cls, workflow_id: str) -> Flow | None:
        """
        Get individual workflow details
        """
        return await FlowDao.get_one_flow_simple(workflow_id)

    @classmethod
    def get_one_workflow_simple_info_sync(cls, workflow_id: str) -> Flow | None:
        """
        Get individual workflow details (Sync)
        """
        return FlowDao.get_one_flow_simple_sync(workflow_id)

    @classmethod
    def get_all_apps_by_time_range_sync(
        cls, start_time: datetime, end_time: datetime, page: int = 1, page_size: int = 100
    ) -> list[dict]:
        """
        Get all apps based on timeframe
        """
        return FlowDao.get_all_app_by_time_range_sync(start_time, end_time, page, page_size)

    @classmethod
    def get_first_app(cls) -> dict | None:
        return FlowDao.get_first_app()
