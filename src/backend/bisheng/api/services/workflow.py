import asyncio
from collections.abc import Sequence
from datetime import datetime
from time import perf_counter
from typing import TYPE_CHECKING

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
from bisheng.common.errcode.http_error import NotFoundError
from bisheng.common.services import telemetry_service
from bisheng.common.services.base import BaseService
from bisheng.core.logger import trace_id_var
from bisheng.database.models.flow import Flow, FlowDao, FlowStatus, FlowType, UserLinkType
from bisheng.database.models.flow_version import FlowVersionDao
from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.tag import TagBusinessTypeEnum, TagDao
from bisheng.database.models.user_link import UserLinkDao
from bisheng.common.errcode.permission import PermissionEnumerationIncompleteError
from bisheng.common.services.metric_log import emit_metric
from bisheng.permission.application.access import get_f048_runtime
from bisheng.permission.application.business_authorization import (
    batch_check_business_actions,
    require_business_action,
)
from bisheng.permission.application.identity import resolve_permission_actor
from bisheng.user.domain.models.user import UserDao
from bisheng.utils import generate_uuid
from bisheng.workflow.callback.base_callback import BaseCallback
from bisheng.workflow.common.node import BaseNodeData, NodeType
from bisheng.workflow.graph.graph_state import GraphState
from bisheng.workflow.graph.workflow import Workflow
from bisheng.workflow.nodes.node_manage import NodeFactory

if TYPE_CHECKING:
    from bisheng.common.schemas.api import PageInfiniteCursorData

# F027: when ReBAC fine-grained filtering shrinks a DB batch, refetch via keyset
# to fill the requested page_size. Batch size balances DB round-trips against
# wasted permission lookups when most rows are filtered out.
_FLOW_PERMISSION_SCAN_BATCH_SIZE = 50
_APP_COMPAT_PAGE_SCAN_BATCH_SIZE = 50

# F048 visible-first: upper bound on the number of visible app ids OpenFGA may
# return per resource type (workflow + assistant queried separately). Matches
# the ceiling used for knowledge_library / knowledge_space / channel so all
# visible-first flows share the same capacity envelope; the permission
# runtime emits ``capacity_80_percent`` telemetry before this hits the
# schema-level 5 000 hard cap.
_APP_VISIBLE_MAX_RESULTS = 5000


class WorkflowResourceAuthorizationPort:
    """Bind the shared application adapter to workflow resources."""

    def __init__(self, adapter) -> None:
        self._adapter = adapter

    async def resolve_permission_target(
        self,
        *,
        resource_id: str,
        actor,
        action: str,
    ):
        return await self._adapter.resolve_permission_target(
            resource_type="workflow",
            resource_id=resource_id,
            actor=actor,
            action=action,
        )


class WorkFlowService(BaseService):
    SUPPORTED_APP_TYPES = {FlowType.WORKFLOW.value, FlowType.ASSISTANT.value}
    _FLOW_TYPE_TO_RESOURCE_TYPE = {
        FlowType.WORKFLOW.value: "workflow",
        FlowType.ASSISTANT.value: "assistant",
    }

    @classmethod
    def filter_supported_apps(cls, data: list[dict]) -> list[dict]:
        return [one for one in data if one.get("flow_type") in cls.SUPPORTED_APP_TYPES]

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

        writeable_ids = writeable_ids or set()
        # Add additional information (F008: removed group_ids, AC-08)
        for one in data:
            one["user_name"] = user_dict.get(one["user_id"], one["user_id"])
            one["write"] = managed or str(one["id"]) in writeable_ids
            one["version_list"] = flow_versions.get(one["id"], [])
            one["tags"] = resource_tag_dict.get(one["id"], [])
            one["logo"] = cls.get_logo_share_link(one["logo"])
        return data

    @classmethod
    async def aenrich_apps_can_share(cls, user: UserPayload, data: list[dict], managed: bool = False) -> list[dict]:
        """Set ``can_share`` from the concrete F048 share action."""
        if not data:
            return data
        permission_map = await cls._application_action_map(
            user,
            data,
            ("share",),
        )
        for one in data:
            one["can_share"] = managed or "share" in permission_map.get(
                str(one.get("id")),
                frozenset(),
            )
        return data

    @classmethod
    async def _application_action_map(
        cls,
        user: UserPayload,
        data: list[dict],
        actions: tuple[str, ...],
    ) -> dict[str, frozenset[str]]:
        grouped: dict[str, list[str]] = {
            "workflow": [],
            "assistant": [],
        }
        for item in cls.filter_supported_apps(data):
            resource_type = cls._FLOW_TYPE_TO_RESOURCE_TYPE.get(
                int(item.get("flow_type") or 0)
            )
            if resource_type is not None:
                grouped[resource_type].append(str(item.get("id")))

        results = await asyncio.gather(
            *(
                batch_check_business_actions(
                    user,
                    resource_type=resource_type,
                    resource_ids=resource_ids,
                    actions=actions,
                )
                for resource_type, resource_ids in grouped.items()
                if resource_ids
            )
        )
        merged: dict[str, frozenset[str]] = {}
        for result in results:
            merged.update(result)
        return merged

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
        action: str = "use",
        cursor: Sequence | None = None,
    ) -> tuple[list[dict], bool]:
        """Get a bounded application candidate page and check exact actions."""
        total_start = perf_counter()
        if flow_type is not None and flow_type not in cls.SUPPORTED_APP_TYPES:
            return [], False

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

        dao_start = perf_counter()
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
        writeable_ids: set[str] = set()
        required_action = "edit" if managed else action
        if data:
            permission_map_start = perf_counter()
            permission_map = await cls._application_action_map(
                user,
                data,
                tuple(dict.fromkeys((required_action, "edit"))),
            )
            data = [
                one
                for one in data
                if required_action
                in permission_map.get(str(one.get("id")), frozenset())
            ]
            writeable_ids = {
                str(app_id)
                for app_id, action_codes in permission_map.items()
                if "edit" in action_codes
            }
            logger.info(
                "[perf][workflow.list.permission_map] user_id={} flow_type={} rows={} kept={} writeable={} "
                "action={} took_ms={:.2f}",
                user.user_id,
                flow_type,
                len(permission_map),
                len(data),
                len(writeable_ids),
                required_action,
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
            "managed={} action={} rows={} has_more={} took_ms={:.2f}",
            user.user_id,
            flow_type,
            page,
            page_size,
            skip_pagination,
            managed,
            action,
            len(data),
            has_more,
            (perf_counter() - total_start) * 1000,
        )
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
        required_action: str,
        admin_bypass: bool = False,
    ) -> tuple[list[dict], bool, set[str]]:
        """F027 cursor-paginated scan for /workflow/list: keep fetching DB
        batches via keyset, apply ReBAC fine-grained filtering, accumulate
        until we have ``page_size + 1`` visible items (the +1 probes
        ``has_more``) or the DB is exhausted.

        Returns ``(visible_items[:page_size], has_more, writeable_ids)`` —
        ``writeable_ids`` aggregates across all scanned batches so the
        ``can_write`` flag in the response stays accurate.

        ``admin_bypass=True`` skips the per-batch F048 BatchCheck and marks
        every row as writeable; the envelope selects this branch when the
        actor is a super admin or a tenant admin of the current tenant. The
        envelope also handles ``flow_ids`` prefiltering (visible-id union for
        regular users, tag prefilter for admins), so the scan loop only sees
        the pre-filtered candidate universe and does not need to distinguish
        between the two callers itself.
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

            if admin_bypass:
                # Admin sees everything and edits everything — no BatchCheck,
                # every row is kept and every id counts toward writeable_ids.
                kept = batch
                writeable_ids |= {str(one.get("id")) for one in batch}
            else:
                permission_map_start = perf_counter()
                permission_map = await cls._application_action_map(
                    user,
                    batch,
                    tuple(dict.fromkeys((required_action, "edit"))),
                )
                kept = [
                    one
                    for one in batch
                    if required_action
                    in permission_map.get(str(one.get("id")), frozenset())
                ]
                writeable_ids |= {
                    str(app_id)
                    for app_id, action_codes in permission_map.items()
                    if "edit" in action_codes
                }
                logger.info(
                    "[perf][workflow.list.permission_map] user_id={} flow_type={} rows={} kept={} "
                    "writeable={} action={} took_ms={:.2f}",
                    user.user_id,
                    flow_type,
                    len(batch),
                    len(kept),
                    len(writeable_ids),
                    required_action,
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
    async def _scan_visible_apps_cursor(
        cls,
        *,
        user: UserPayload,
        page_size: int,
        name: str | None = None,
        status: int | None = None,
        id_list: list[str] | None = None,
        id_list_not_in: list[str] | None = None,
        flow_type: int | None = None,
        search_description: bool = False,
        action: str = "visible",
        ranking_user_id: int | None = None,
        cursor: Sequence | None = None,
    ) -> tuple[list[dict], bool, dict[str, frozenset[str]]]:
        """Fill ONE cursor page by scanning keyset batches until enough visible.

        Unlike the retired offset scan (which re-scanned and re-permission-checked
        pages 1..N to serve page N), this resumes strictly after ``cursor`` so the
        per-page permission-check cost is bounded by ``page_size`` no matter how
        deep the caller has scrolled.

        Returns ``(page_items, has_more, page_actions)``. ``page_items`` still
        carry the ranking helper columns (``_used_rank``/``_sort_time``) when
        ``ranking_user_id`` is set so the caller can derive ``next_cursor``; the
        caller MUST strip them before serving the response.
        """
        normalized_page_size = max(int(page_size or 1), 1)
        requested_actions = tuple(dict.fromkeys((action, "edit", "share")))

        visible: list[dict] = []
        visible_actions: dict[str, frozenset[str]] = {}
        batch_cursor: list | None = list(cursor) if cursor else None

        # Accumulate one extra visible row (page_size + 1) to probe has_more.
        while len(visible) <= normalized_page_size:
            batch, db_has_more = await FlowDao.aget_all_apps(
                name=name,
                status=status,
                id_list=id_list,
                flow_type=flow_type,
                id_list_not_in=id_list_not_in,
                page=0,
                limit=_APP_COMPAT_PAGE_SCAN_BATCH_SIZE,
                search_description=search_description,
                cursor=batch_cursor,
                ranking_user_id=ranking_user_id,
            )
            if not batch:
                break

            last_db = batch[-1]
            batch = cls.filter_supported_apps(batch)
            if batch:
                action_map = await cls._application_action_map(
                    user,
                    batch,
                    requested_actions,
                )
                for item in batch:
                    item_id = str(item.get("id"))
                    if action in action_map.get(item_id, frozenset()):
                        visible.append(item)
                        visible_actions[item_id] = action_map.get(
                            item_id,
                            frozenset(),
                        )

            if not db_has_more:
                break
            if ranking_user_id is not None:
                batch_cursor = [last_db["_used_rank"], last_db["_sort_time"], last_db["id"]]
            else:
                batch_cursor = [last_db["update_time"], last_db["id"]]

        has_more = len(visible) > normalized_page_size
        page_items = visible[:normalized_page_size]
        page_actions = {
            str(item.get("id")): visible_actions.get(
                str(item.get("id")),
                frozenset(),
            )
            for item in page_items
        }
        return page_items, has_more, page_actions

    @classmethod
    def _apply_page_can_share(
        cls,
        user: UserPayload,
        data: list[dict],
        action_map: dict[str, frozenset[str]],
    ) -> list[dict]:
        del user
        for item in data:
            item["can_share"] = "share" in action_map.get(
                str(item.get("id")),
                frozenset(),
            )
        return data

    @classmethod
    async def get_online_flows_cursor(
        cls,
        user: UserPayload,
        name: str | None,
        status: int,
        tag_id: int | None,
        flow_type: int | None,
        cursor: str | None = None,
        page_size: int = 10,
        *,
        search_description: bool = False,
        action: str = "use",
    ) -> "PageInfiniteCursorData":
        """Ranked online-app page as an F027 cursor envelope.

        Apps the user has conversations with rank first (by last-used), then the
        rest by update_time. The ranked keyset is ``(_used_rank, _sort_time, id)``.
        Per-page permission-check cost is bounded by ``page_size`` regardless of
        scroll depth (no offset re-scan of earlier pages).
        """
        from bisheng.common.cursor import CursorDecodeError, decode_cursor, encode_cursor
        from bisheng.common.errcode.flow import AppInvalidCursorError
        from bisheng.common.schemas.api import PageInfiniteCursorData

        context = f"online|action={action}|search_description={int(bool(search_description))}"
        try:
            decoded = decode_cursor(cursor, expected_key_len=3, expected_context=context)
        except CursorDecodeError as exc:
            raise AppInvalidCursorError(exception=exc)

        if flow_type is not None and flow_type not in cls.SUPPORTED_APP_TYPES:
            return PageInfiniteCursorData(data=[], page_size=page_size, has_more=False, next_cursor=None)

        tagged_ids: list[str] | None = None
        if tag_id:
            resource_types = []
            if flow_type in (None, FlowType.WORKFLOW.value):
                resource_types.append(ResourceTypeEnum.WORK_FLOW)
            if flow_type in (None, FlowType.ASSISTANT.value):
                resource_types.append(ResourceTypeEnum.ASSISTANT)
            tagged_rows = await asyncio.gather(
                *[TagDao.aget_resources_by_tags([tag_id], resource_type) for resource_type in resource_types]
            )
            tagged_ids = [row.resource_id for rows in tagged_rows for row in rows]
            if not tagged_ids:
                return PageInfiniteCursorData(data=[], page_size=page_size, has_more=False, next_cursor=None)

        page_items, has_more, action_map = await cls._scan_visible_apps_cursor(
            user=user,
            page_size=page_size,
            name=name,
            status=status,
            id_list=tagged_ids,
            flow_type=flow_type,
            search_description=search_description,
            action=action,
            ranking_user_id=user.user_id,
            cursor=decoded,
        )

        # Derive the cursor from the last PAGE item's ranked keyset BEFORE the
        # helper columns are stripped for serialization.
        next_cursor: str | None = None
        if has_more and page_items:
            last = page_items[-1]
            next_cursor = encode_cursor(
                (last["_used_rank"], last["_sort_time"], last["id"]),
                context=context,
            )
        for item in page_items:
            item.pop("_used_rank", None)
            item.pop("_sort_time", None)

        writeable_ids = {
            app_id
            for app_id, action_codes in action_map.items()
            if "edit" in action_codes
        }
        data = cls.add_extra_field(user, page_items, writeable_ids=writeable_ids)
        data = cls._apply_page_can_share(user, data, action_map)
        return PageInfiniteCursorData(
            data=data,
            page_size=page_size,
            has_more=has_more,
            next_cursor=next_cursor,
        )

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
        action: str = "use",
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
        required_action = "edit" if managed else action
        context = (
            f"flow|sort=update_time|action={required_action}|"
            f"managed={int(managed)}"
        )
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

        # F048 visible-first strategy:
        #   * Super admins and tenant admins skip the permission system
        #     entirely and scan the business DB directly; every returned row
        #     gets ``write=True`` because they are effectively unrestricted.
        #     Enumerating "all apps in a tenant" through OpenFGA is wasteful
        #     for these identities and prone to trip the 5 000-object visible
        #     enumeration cap.
        #   * Regular users first ask OpenFGA for the small set of workflow
        #     and assistant ids they can see (``list_visible_objects`` per
        #     resource_type), pass their union into ``_scan_visible_flows_cursor``
        #     as an ``id_list`` prefilter, and keep the per-batch BatchCheck
        #     because visible ⊇ edit ⊇ use — the pre-filter is a valid
        #     superset for the concrete action, but the action itself still
        #     needs to be verified per page.
        actor = await resolve_permission_actor(user)
        is_admin = actor.super_admin or actor.current_tenant_id in actor.tenant_admin_tenant_ids

        fga_elapsed_ms = 0.0
        effective_flow_ids: list[str]
        visible_id_count: int | None = None
        if is_admin:
            # Admin bypass — no permission enumeration; tag prefilter only.
            effective_flow_ids = flow_ids
        else:
            fga_started = perf_counter()
            try:
                visible_id_list = await cls._collect_visible_app_ids(actor, flow_type)
            except PermissionEnumerationIncompleteError:
                fga_elapsed_ms = (perf_counter() - fga_started) * 1000
                emit_metric(
                    "permission_visible_list",
                    tenant=actor.current_tenant_id,
                    resource_type="application",
                    strategy="visible_ids_first_flow_list",
                    candidate_count=0,
                    visible_count=0,
                    scanned_count=0,
                    scan_amplification=0,
                    stream_completed=False,
                    capacity=_APP_VISIBLE_MAX_RESULTS,
                    db_elapsed_ms=0,
                    fga_elapsed_ms=fga_elapsed_ms,
                    total_elapsed_ms=(perf_counter() - total_start) * 1000,
                    alert="stream_incomplete",
                )
                raise
            fga_elapsed_ms = (perf_counter() - fga_started) * 1000
            visible_id_count = len(visible_id_list)
            if flow_ids:
                tag_set = {str(fid) for fid in flow_ids}
                visible_id_list = [i for i in visible_id_list if i in tag_set]
            if not visible_id_list:
                return PageInfiniteCursorData(
                    data=[],
                    page_size=page_size,
                    has_more=False,
                    next_cursor=None,
                )
            effective_flow_ids = visible_id_list

        data, has_more, writeable_ids = await cls._scan_visible_flows_cursor(
            user=user,
            name=name,
            status=status,
            flow_ids=effective_flow_ids,
            flow_type=flow_type,
            cursor=decoded,
            page_size=page_size,
            managed=managed,
            search_description=search_description,
            required_action=required_action,
            admin_bypass=is_admin,
        )

        enrich_start = perf_counter()
        data = cls.add_extra_field(
            user,
            data,
            managed,
            writeable_ids=writeable_ids,
        )
        logger.info(
            "[perf][workflow.list.enrich] user_id={} flow_type={} rows={} took_ms={:.2f}",
            user.user_id,
            flow_type,
            len(data),
            (perf_counter() - enrich_start) * 1000,
        )
        logger.info(
            "[perf][workflow.list.total] user_id={} flow_type={} page_size={} managed={} action={} "
            "rows={} has_more={} took_ms={:.2f} strategy={}",
            user.user_id,
            flow_type,
            page_size,
            managed,
            required_action,
            len(data),
            has_more,
            (perf_counter() - total_start) * 1000,
            "admin_bypass" if is_admin else "visible_ids_first",
        )

        if not is_admin and visible_id_count is not None:
            emit_metric(
                "permission_visible_list",
                tenant=actor.current_tenant_id,
                resource_type="application",
                strategy="visible_ids_first_flow_list",
                candidate_count=visible_id_count,
                visible_count=visible_id_count,
                scanned_count=len(data),
                scan_amplification=(visible_id_count / max(len(data), 1)) if visible_id_count else 0,
                stream_completed=True,
                capacity=_APP_VISIBLE_MAX_RESULTS,
                db_elapsed_ms=(perf_counter() - enrich_start) * 1000,
                fga_elapsed_ms=fga_elapsed_ms,
                total_elapsed_ms=(perf_counter() - total_start) * 1000,
                returned_count=len(data),
                alert=(
                    "capacity_80_percent"
                    if visible_id_count >= _APP_VISIBLE_MAX_RESULTS * 0.8
                    else None
                ),
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
    async def _collect_visible_app_ids(
        cls,
        actor,
        flow_type: int | None,
    ) -> list[str]:
        """Union OpenFGA visible-id enumerations across workflow + assistant.

        ``flow_type`` narrows which resource_types are queried: ``None`` fans
        out to both, otherwise only the matching one is asked. Returns the
        list of raw resource ids as strings (workflow ids are integer-typed
        but stored as strings in ``FlowDao.aget_all_apps`` id filters, and
        assistant ids are UUID hex strings — both are compared against
        ``sub_query.c.id`` in the UNION ALL query without adapter shims).
        """
        resource_types: list[str] = []
        if flow_type is None:
            resource_types = ["workflow", "assistant"]
        elif flow_type == FlowType.WORKFLOW.value:
            resource_types = ["workflow"]
        elif flow_type == FlowType.ASSISTANT.value:
            resource_types = ["assistant"]
        else:
            return []

        runtime = await get_f048_runtime()
        results = await asyncio.gather(
            *(
                runtime.list_visible_objects(
                    actor,
                    resource_type=resource_type,
                    max_results=_APP_VISIBLE_MAX_RESULTS,
                )
                for resource_type in resource_types
            )
        )
        ids: list[str] = []
        for result in results:
            ids.extend(str(object_id) for object_id in result.object_ids)
        return ids

    @classmethod
    async def filter_apps_by_action(
        cls,
        user: UserPayload,
        data: list[dict],
        action: str = "use",
    ) -> list[dict]:
        if not data:
            return data
        action_map = await cls._application_action_map(
            user,
            data,
            (action,),
        )
        return [
            one
            for one in data
            if action in action_map.get(str(one.get("id")), frozenset())
        ]

    @classmethod
    async def aget_writeable_app_ids(cls, user: UserPayload, data: list[dict]) -> set[str]:
        """Which of these apps the caller may edit.

        Exists so an async endpoint can fill `add_extra_field`'s `writeable_ids`
        without it reaching for a synchronous permission check of its own. Asked
        through the F048 action map, like every other permission question here —
        the 2.6 line resolved this against ApplicationPermissionService, which
        the F048 rework replaced.
        """
        action_map = await cls._application_action_map(user, data, ("edit",))
        return {
            app_id
            for app_id, action_codes in action_map.items()
            if "edit" in action_codes
        }

    @classmethod
    async def run_once(
        cls,
        login_user: UserPayload,
        node_input: dict[str, any],
        node_data: dict[any, any],
        workflow_id: str,
    ):
        workflow_info = FlowDao.get_flow_by_id(workflow_id)
        if not workflow_info:
            raise NotFoundError()
        await require_business_action(
            login_user,
            resource_type="workflow",
            resource_id=workflow_info.id,
            action="edit",
        )

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
        required_action = (
            "publish"
            if status == FlowStatus.ONLINE.value
            else "unpublish"
        )
        await require_business_action(
            login_user,
            resource_type="workflow",
            resource_id=flow_id,
            action=required_action,
        )

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
        data = await cls.filter_apps_by_action(user, data, "visible")

        # Reorder users in the order they are added to the stock
        data.sort(key=lambda x: user_link_order.get(x["id"], float("inf")))

        # Manual pagination
        total = len(data)
        start_index = (page - 1) * page_size
        end_index = start_index + page_size
        data = data[start_index:end_index]

        writeable_ids = await cls.aget_writeable_app_ids(user, data)
        data = cls.add_extra_field(user, data, writeable_ids=writeable_ids)
        data = await cls.aenrich_apps_can_share(user, data)

        return data, total

    @classmethod
    def delete_frequently_used_flows(cls, user: UserPayload, user_link_type: str, type_detail: str):
        UserLinkDao.delete_user_link(user.user_id, user_link_type, type_detail)
        return True

    @classmethod
    def add_frequently_used_flows(cls, user: UserPayload, user_link_type: str, type_detail: str):
        _user_link, is_new = UserLinkDao.add_user_link(user.user_id, user_link_type, type_detail)
        return is_new

    @classmethod
    async def get_uncategorized_flows_envelope(
        cls,
        user: UserPayload,
        cursor: str | None = None,
        page_size: int = 8,
        keyword: str | None = None,
    ) -> "PageInfiniteCursorData":
        """Unsorted (untagged) online apps as an F027 cursor envelope.

        Candidate = online apps NOT bound to any APPLICATION tag. Scans forward
        from the cursor and permission-filters by ``visible``; per-page cost is
        bounded by ``page_size`` regardless of scroll depth (the offset version
        re-scanned pages 1..N and degraded on deep pages).
        """
        from bisheng.common.cursor import CursorDecodeError, decode_cursor, encode_cursor
        from bisheng.common.errcode.flow import AppInvalidCursorError
        from bisheng.common.schemas.api import PageInfiniteCursorData

        context = "uncategorized|action=visible"
        try:
            decoded = decode_cursor(cursor, expected_key_len=2, expected_context=context)
        except CursorDecodeError as exc:
            raise AppInvalidCursorError(exception=exc)

        all_tags = await TagDao.asearch_tags(
            None,
            0,
            0,
            business_type=TagBusinessTypeEnum.APPLICATION,
            business_id=TagBusinessTypeEnum.APPLICATION.value,
        )
        tag_id = [tag.id for tag in all_tags]
        flow_ids_not_in: list[str] = []
        if tag_id:
            tagged_rows = await asyncio.gather(
                TagDao.aget_resources_by_tags(tag_id, ResourceTypeEnum.WORK_FLOW),
                TagDao.aget_resources_by_tags(tag_id, ResourceTypeEnum.ASSISTANT),
            )
            flow_ids_not_in = list({row.resource_id for rows in tagged_rows for row in rows})

        page_items, has_more, permission_map = await cls._scan_visible_apps_cursor(
            user=user,
            page_size=page_size,
            name=keyword,
            status=FlowStatus.ONLINE.value,
            id_list_not_in=flow_ids_not_in,
            action="visible",
            cursor=decoded,
        )

        next_cursor: str | None = None
        if has_more and page_items:
            last = page_items[-1]
            next_cursor = encode_cursor((last["update_time"], last["id"]), context=context)

        for one in page_items:
            one["logo"] = cls.get_logo_share_link(one["logo"])
        cls._apply_page_can_share(user, page_items, permission_map)

        return PageInfiniteCursorData(
            data=page_items,
            page_size=page_size,
            has_more=has_more,
            next_cursor=next_cursor,
        )

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
