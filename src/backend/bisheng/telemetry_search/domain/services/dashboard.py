from collections.abc import Sequence
from datetime import datetime
from typing import Any

from fastapi import Request
from loguru import logger
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Row, RowMapping

from bisheng.api.services.audit_log import AuditLogService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import NotFoundError, UnAuthorizedError
from bisheng.common.errcode.telemetry import DashboardMaxError, DashBoardShareAuthError
from bisheng.core.database import get_async_db_session
from bisheng.core.search.elasticsearch.manager import get_es_connection
from bisheng.database.models.role_access import AccessType, WebMenuResource
from bisheng.permission.application.access import get_f048_resource_adapter
from bisheng.permission.application.business_authorization import (
    batch_check_business_actions,
    require_business_action,
)
from bisheng.permission.application.identity import resolve_permission_actor
from bisheng.telemetry_search.domain.models.dashboard import (
    Dashboard,
    DashboardComponent,
    DashboardDefault,
    DashboardStatus,
    DashboardType,
)
from bisheng.telemetry_search.domain.models.dashboard_dao import DashboardDao
from bisheng.telemetry_search.domain.repositories.implementations.dataset_repository_impl import (
    DashboardDatasetRepositoryImpl,
)
from bisheng.telemetry_search.domain.schemas.dashboard import DashboardCreate, DashboardRead
from bisheng.telemetry_search.domain.services.component import (
    ComponentDataConfig,
    DataQueryService,
    TimeFilter,
)
from bisheng.telemetry_search.domain.services.f048_dashboard_permission import (
    DashboardPermissionRecord,
)
from bisheng.telemetry_search.domain.utils import is_commercial
from bisheng.user.domain.services.user import UserService
from bisheng.utils import generate_uuid, get_request_ip

DASHBOARD_OPERATION_ACTIONS = {
    "list": "visible",
    "detail": "visible",
    "component_data": "visible",
    "copy_source": "visible",
    "set_default": "visible",
    "share_link": "visible",
    "title": "edit",
    "status": "edit",
    "layout": "edit",
    "component": "edit",
    "delete": "delete",
    "members": "manage_permission",
}


class DashboardResourceAuthorizationPort:
    """Bind the F048 dashboard adapter to the resource registry."""

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
            resource_id=resource_id,
            actor=actor,
            action=action,
        )


class DashboardService(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    request: Request = None
    login_user: UserPayload = None

    async def _require_action(
        self,
        dashboard: Dashboard,
        action: str,
    ) -> None:
        await require_business_action(
            self.login_user,
            resource_type="dashboard",
            resource_id=str(dashboard.id),
            action=action,
        )

    async def _action_map(
        self,
        dashboards: list[Dashboard],
        actions: tuple[str, ...],
    ) -> dict[str, frozenset[str]]:
        return await batch_check_business_actions(
            self.login_user,
            resource_type="dashboard",
            resource_ids=(str(dashboard.id) for dashboard in dashboards if dashboard.id is not None),
            actions=actions,
        )

    @staticmethod
    def _new_permission_record(
        dashboard: Dashboard,
    ) -> DashboardPermissionRecord:
        return DashboardPermissionRecord(
            tenant_id=int(dashboard.tenant_id or 0),
            resource_id=str(dashboard.id),
            dashboard_type=str(dashboard.dashboard_type),
            status=str(dashboard.status),
            owner_user_id=dashboard.user_id,
            permission_version=0,
            context_version=f"dashboard-create:{dashboard.id}"[:64],
        )

    async def get_dashboards(
        self,
        keyword: str | None = None,
    ) -> list[DashboardRead]:
        """
        Get a list of Kanban boards
        :param keyword: Search by keywords
        :return:
        """
        filter_types = [DashboardType.PRESET_OSS]
        if is_commercial():
            filter_types = [DashboardType.PRESET_COMMERCIAL, DashboardType.CUSTOM]
        candidates = await DashboardDao.get_dashboards(
            keyword=keyword,
            dashboard_type=filter_types,
        )
        # The list only decides visibility. Whether the user may edit/delete/
        # manage a board is resolved lazily by the client (per-resource
        # my-permissions) at the moment it reaches for those actions, so the
        # list no longer pays to BatchCheck "edit" for every candidate — the
        # cost drops from (candidates x 2) to (candidates x 1).
        action_map = await self._action_map(
            candidates,
            ("visible",),
        )
        res = [dashboard for dashboard in candidates if "visible" in action_map.get(str(dashboard.id), frozenset())]
        default_dashboard = await DashboardDao.get_default_dashboard(user_id=self.login_user.user_id)
        result = []
        for one in res:
            tmp = DashboardRead.model_validate(one)
            if default_dashboard and one.id == default_dashboard.dashboard_id:
                tmp.is_default = True
            result.append(tmp)
        return result

    async def create_dashboard(self, data: DashboardCreate) -> Dashboard:
        """
        Create a board
        :param data:
        :return:
        """
        if not is_commercial():
            raise UnAuthorizedError()
        if not await self.login_user.async_access_check(
            0, target_id=WebMenuResource.CREATE_DASHBOARD.value, access_type=AccessType.WEB_MENU
        ):
            raise UnAuthorizedError()

        user_total = await DashboardDao.count_dashboards(
            dashboard_type=[DashboardType.PRESET_COMMERCIAL, DashboardType.CUSTOM]
        )
        if user_total >= 20:
            raise DashboardMaxError()

        dashboard = Dashboard.model_validate(data)

        dashboard.dashboard_type = DashboardType.CUSTOM.value
        dashboard.user_id = self.login_user.user_id
        dashboard.tenant_id = self.login_user.tenant_id

        dashboard = await DashboardDao.insert(dashboard)
        try:
            adapter = await get_f048_resource_adapter("dashboard")
            await adapter.authorize_created(
                record=self._new_permission_record(dashboard),
                actor=await resolve_permission_actor(self.login_user),
            )
        except Exception:
            try:
                await DashboardDao.delete_one(int(dashboard.id))
            except Exception:
                logger.exception(
                    "Failed to remove dashboard {} after permission projection failure",
                    dashboard.id,
                )
            raise
        await self.create_dashboard_hook(dashboard)
        return dashboard

    async def create_dashboard_hook(self, dashboard: Dashboard):
        """
        Create a Kanban Hook
        :param dashboard:
        :return:
        """
        await AuditLogService.create_dashboard(
            self.login_user, get_request_ip(self.request), str(dashboard.id), dashboard.title, group_ids=[]
        )

    async def delete_dashboard(self, dashboard_id: int) -> bool:
        dashboard = await DashboardDao.get_one(dashboard_id)
        if not dashboard:
            return True
        if dashboard.dashboard_type == DashboardType.PRESET_OSS.value:
            raise UnAuthorizedError()
        await self._require_action(dashboard, "delete")
        adapter = await get_f048_resource_adapter("dashboard")
        record = await adapter.load_permission_record(str(dashboard.id))
        if record is None:
            raise NotFoundError()
        await adapter.project_delete(
            record=record,
            actor=await resolve_permission_actor(self.login_user),
        )

        await self.delete_dashboard_hook(dashboard)

        return await DashboardDao.delete_one(dashboard_id)

    async def delete_dashboard_hook(self, dashboard: Dashboard):
        """
        Remove Kanban Hook
        :param dashboard:
        :return:
        """
        await AuditLogService.delete_dashboard(
            self.login_user, get_request_ip(self.request), str(dashboard.id), dashboard.title, group_ids=[]
        )

    async def update_dashboard_title(self, dashboard_id: int, new_title: str) -> bool:
        dashboard = await DashboardDao.get_one(dashboard_id)
        if not dashboard:
            return True
        await self._require_action(dashboard, "edit")

        await DashboardDao.update_dashboard_title(dashboard_id, new_title)
        dashboard.title = new_title
        await self.update_dashboard_hook(dashboard)
        return True

    async def update_dashboard_hook(self, dashboard: Dashboard):
        """
        Update Kanban Hook
        :param dashboard:
        :return:
        """
        await AuditLogService.update_dashboard(
            self.login_user, get_request_ip(self.request), str(dashboard.id), dashboard.title, group_ids=[]
        )

    async def update_dashboard_status(self, dashboard_id: int, new_status: DashboardStatus) -> bool:
        dashboard = await DashboardDao.get_one(dashboard_id)
        if not dashboard:
            return True
        await self._require_action(dashboard, "edit")
        if dashboard.status == new_status.value:
            return True
        await DashboardDao.update_dashboard_status(dashboard_id, new_status)
        await self.update_dashboard_hook(dashboard)
        return True

    async def set_default_dashboard(self, dashboard_id: int) -> DashboardDefault:
        dashboard = await DashboardDao.get_one(dashboard_id)
        if dashboard is None:
            raise NotFoundError()
        await self._require_action(dashboard, "visible")
        return await DashboardDao.set_default_dashboard(self.login_user.user_id, dashboard_id)

    async def get_dashboard_detail(self, dashboard_id: int, from_share: bool) -> DashboardRead:
        dashboard = await DashboardDao.get_one(dashboard_id)
        if not dashboard:
            raise NotFoundError()
        if not is_commercial() and dashboard.dashboard_type != DashboardType.PRESET_OSS.value:
            raise NotFoundError()
        try:
            await self._require_action(dashboard, "visible")
        except UnAuthorizedError:
            if from_share:
                raise DashBoardShareAuthError()
            raise UnAuthorizedError()
        actions = await self._action_map([dashboard], ("edit",))
        write_flag = "edit" in actions.get(
            str(dashboard.id),
            frozenset(),
        )

        components = await DashboardDao.get_components(dashboard_id)
        result = DashboardRead.model_validate(dashboard)
        result.write = write_flag
        default_dashboard = await DashboardDao.get_default_dashboard(user_id=self.login_user.user_id)
        if default_dashboard and default_dashboard.dashboard_id == result.id:
            result.is_default = True

        result.components = components
        user_name = self.login_user.user_name
        if result.user_id != self.login_user.user_id:
            user_info = await UserService.get_user_by_id(result.user_id)
            user_name = user_info.user_name if user_info else str(result.user_id)
        result.user_name = user_name
        return result

    async def copy_dashboard(self, dashboard_id: int, new_title: str) -> Dashboard:
        dashboard = await DashboardDao.get_one(dashboard_id)
        if not dashboard:
            raise NotFoundError()
        await self._require_action(dashboard, "visible")
        adapter = await get_f048_resource_adapter("dashboard")
        source_permission = await adapter.load_permission_record(str(dashboard.id))
        if source_permission is None:
            raise NotFoundError()

        user_total = await DashboardDao.count_dashboards(
            dashboard_type=[DashboardType.PRESET_COMMERCIAL, DashboardType.CUSTOM]
        )
        if user_total >= 20:
            raise DashboardMaxError()

        # create new dashboard
        new_dashboard = Dashboard.model_validate(dashboard)
        new_dashboard.id = None
        new_dashboard.title = new_title
        new_dashboard.dashboard_type = DashboardType.CUSTOM.value
        new_dashboard.user_id = self.login_user.user_id
        new_dashboard.tenant_id = self.login_user.tenant_id
        new_dashboard.status = DashboardStatus.DRAFT.value
        new_dashboard.create_time = None
        new_dashboard.update_time = None

        # get and copy components
        components = await DashboardDao.get_components(dashboard_id)
        change_layout_ids = {}
        new_components = []
        for one in components:
            change_layout_ids[one.id] = generate_uuid()
            new_component = DashboardComponent.model_validate(one)
            new_component.id = change_layout_ids[one.id]
            new_components.append(new_component)

        # update query components data config
        for one in new_components:
            if one.type == "query":
                linked_components = one.data_config.get("linkedComponentIds", [])
                if linked_components:
                    new_linked_components = []
                    for component_id in linked_components:
                        new_linked_components.append(change_layout_ids.get(component_id, component_id))
                    one.data_config["linkedComponentIds"] = new_linked_components

        # update layout config
        for one in new_dashboard.layout_config.get("layouts", []):
            if one.get("i") in change_layout_ids:
                one["i"] = change_layout_ids[one["i"]]

        # insert dashboard
        new_dashboard = await DashboardDao.insert(new_dashboard)
        try:
            await adapter.project_copy(
                source=source_permission,
                target=self._new_permission_record(new_dashboard),
                actor=await resolve_permission_actor(self.login_user),
                new_owner_user_id=self.login_user.user_id,
            )
        except Exception:
            try:
                await DashboardDao.delete_one(int(new_dashboard.id))
            except Exception:
                logger.exception(
                    "Failed to remove copied dashboard {} after permission projection failure",
                    new_dashboard.id,
                )
            raise
        for one in new_components:
            one.dashboard_id = new_dashboard.id

        # insert_components
        await DashboardDao.insert_components(new_components)
        await self.create_dashboard_hook(new_dashboard)
        return new_dashboard

    async def update_dashboard(self, dashboard: DashboardRead) -> Dashboard:
        old_dashboard = await DashboardDao.get_one(dashboard.id)
        if not old_dashboard:
            raise NotFoundError()
        await self._require_action(old_dashboard, "edit")

        # update dashboard basic info
        old_dashboard.title = dashboard.title
        old_dashboard.description = dashboard.description
        old_dashboard.layout_config = dashboard.layout_config
        old_dashboard.style_config = dashboard.style_config
        old_dashboard.update_time = datetime.now()

        new_components = []
        for component in dashboard.components:
            new_component = DashboardComponent.model_validate(component)
            new_component.dashboard_id = dashboard.id
            new_components.append(new_component)
        res = await DashboardDao.replace_dashboard_components(old_dashboard, new_components)
        await self.update_dashboard_hook(old_dashboard)
        return res

    async def query_component_data(
        self,
        dashboard_id: int,
        component_id: str | None = None,
        component: DashboardComponent | None = None,
        time_filters: list[TimeFilter] | None = None,
    ) -> Any:
        """query component telemetry data"""
        dashboard = await DashboardDao.get_one(dashboard_id)
        if not dashboard:
            raise NotFoundError()
        await self._require_action(dashboard, "visible")
        if component_id is not None:
            component = await DashboardDao.get_one_component(component_id)
            if not component or component.dashboard_id != dashboard_id:
                raise NotFoundError()
        if component is None:
            raise NotFoundError()
        if component.dashboard_id != dashboard_id:
            raise NotFoundError()
        data_config = ComponentDataConfig(**component.data_config)
        res = await DataQueryService(
            dataset_code=component.dataset_code, data_config=data_config, time_filters=time_filters
        ).query_telemetry_data()
        return res

    @staticmethod
    async def get_dataset_options() -> Sequence[Row[Any] | RowMapping | Any]:
        """
        Can get all available datasets for dashboards
        :return:
        """

        async with get_async_db_session() as session:
            dashboard_dataset_repository = DashboardDatasetRepositoryImpl(session)
            if is_commercial():
                datasets = await dashboard_dataset_repository.find_all()
            else:
                datasets = await dashboard_dataset_repository.find_all(is_commercial_only=False)

        return datasets

    @staticmethod
    async def get_dataset_field_enums(
        index_name: str,
        field: str,
        keyword: str | None = None,
        size: int = 20,
        page: int = 1,
    ) -> dict[str, Any]:
        """
        Get dataset field enum value with server-side pagination using aggregation filters
        """
        skip = (page - 1) * size
        es_client = await get_es_connection()

        core_aggs = {
            "enum_values": {
                "terms": {"field": field, "size": 65536, "order": {"_key": "asc"}},
                "aggs": {"pagination": {"bucket_sort": {"from": skip, "size": size}}},
            },
            "total_count": {"cardinality": {"field": field}},
        }

        current_aggs = core_aggs

        if keyword:
            filter_query = {"match_phrase": {f"{field}.text": keyword}}

            current_aggs = {"filter_wrapper": {"filter": filter_query, "aggs": core_aggs}}

        if "." in field:
            path = field.rsplit(".", 1)[0]
            aggs_body = {"nested_agg": {"nested": {"path": path}, "aggs": current_aggs}}
        else:
            aggs_body = current_aggs

        body = {"size": 0, "aggs": aggs_body}

        resp = await es_client.search(index=index_name, body=body)

        aggs_root = resp.get("aggregations", {})

        if "." in field:
            aggs_root = aggs_root.get("nested_agg", {})

        if keyword:
            aggs_root = aggs_root.get("filter_wrapper", {})

        total = aggs_root.get("total_count", {}).get("value", 0)
        buckets = aggs_root.get("enum_values", {}).get("buckets", [])
        enums = [bucket.get("key") for bucket in buckets]

        return {"total": total, "enums": enums}
