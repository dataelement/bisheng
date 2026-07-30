from datetime import datetime
from typing import List, Any, Sequence, Dict, ClassVar

from fastapi import Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Row, RowMapping

from bisheng.api.services.audit_log import AuditLogService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import UnAuthorizedError, NotFoundError
from bisheng.common.errcode.telemetry import DashboardMaxError, DashBoardShareAuthError
from bisheng.core.database import get_async_db_session
from bisheng.core.context.tenant import (
    DEFAULT_TENANT_ID,
    get_current_tenant_id,
)
from bisheng.core.search.elasticsearch.manager import get_es_connection
from bisheng.database.models.group_resource import GroupResourceDao, GroupResource, ResourceTypeEnum
from bisheng.database.models.role_access import AccessType, WebMenuResource
from bisheng.user.domain.services.user import UserService
from bisheng.utils import generate_uuid, get_request_ip
from ..models.dashboard import DashboardType, DashboardStatus, Dashboard, DashboardDefault, DashboardComponent
from ..models.dashboard_dao import DashboardDao
from ..repositories.implementations.dataset_repository_impl import DashboardDatasetRepositoryImpl
from ..schemas.dashboard import DashboardRead, DashboardCreate
from ..schemas.component import DimensionQueryFilter
from ..services.component import TimeFilter, ComponentDataConfig, DataQueryService
from ..utils import is_commercial


class DashboardService(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    request: Request = None
    login_user: UserPayload = None

    REALTIME_SCOPED_DATASETS: ClassVar[set[str]] = {
        "mid_knowledge_space_content_stat",
        "mid_realtime_qa_question_fact",
        "mid_user_daily_participation",
    }
    FILE_SPACE_LEVEL_LABELS: ClassVar[dict[str, str]] = {
        "public": "公共库",
        "department": "部门库",
        "team": "团队库（含科室库）",
    }

    @classmethod
    def _uses_realtime_dataset(
        cls,
        components: Sequence[DashboardComponent],
    ) -> bool:
        return any(
            component.dataset_code in cls.REALTIME_SCOPED_DATASETS
            for component in components
        )

    async def _is_department_admin(self) -> bool:
        if self.login_user.is_admin():
            return True
        from bisheng.database.models.department import DepartmentDao

        return bool(
            await DepartmentDao.aget_user_admin_departments(
                self.login_user.user_id
            )
        )

    async def _ensure_realtime_dashboard_write(
        self,
        dashboard_id: int,
        incoming_components: Sequence[DashboardComponent] = (),
    ) -> None:
        if self.login_user.is_admin():
            return
        existing_components = await DashboardDao.get_components(dashboard_id)
        if self._uses_realtime_dataset(
            [*existing_components, *incoming_components]
        ):
            raise UnAuthorizedError()

    async def _get_realtime_scope_filters(
        self,
        dataset_code: str,
    ) -> List[DimensionQueryFilter]:
        if dataset_code not in self.REALTIME_SCOPED_DATASETS:
            return []
        filters = [
            DimensionQueryFilter(
                fieldId="tenant_id",
                values=[get_current_tenant_id() or DEFAULT_TENANT_ID],
            )
        ]
        if self.login_user.is_admin():
            return filters

        from bisheng.database.models.department import DepartmentDao

        admin_departments = await DepartmentDao.aget_user_admin_departments(
            self.login_user.user_id
        )
        if not admin_departments:
            raise UnAuthorizedError()

        if dataset_code == "mid_knowledge_space_content_stat":
            from bisheng.common.models.space_channel_member import SpaceChannelMemberDao
            from bisheng.permission.domain.services.permission_service import PermissionService

            accessible_ids = await PermissionService.list_accessible_ids(
                user_id=self.login_user.user_id,
                relation="can_manage",
                object_type="knowledge_space",
                login_user=self.login_user,
            )
            managed_members = await SpaceChannelMemberDao.async_get_user_managed_members(
                self.login_user.user_id
            )
            space_ids = {
                int(member.business_id)
                for member in managed_members
                if str(member.business_id).isdigit()
            }
            if accessible_ids is not None:
                space_ids.update(
                    int(space_id)
                    for space_id in accessible_ids
                    if str(space_id).isdigit()
                )
            filters.append(
                DimensionQueryFilter(
                    fieldId="space_id",
                    values=sorted(space_ids) or ["__deny_all__"],
                )
            )
            return filters

        department_ids = set()
        for department in admin_departments:
            department_ids.add(int(department.id))
            if department.path:
                department_ids.update(
                    int(department_id)
                    for department_id in await DepartmentDao.aget_subtree_ids(
                        department.path
                    )
                )
        filters.append(
            DimensionQueryFilter(
                fieldId="primary_department_id",
                values=sorted(department_ids) or ["__deny_all__"],
            )
        )
        return filters

    @classmethod
    async def get_simple_dashboards(cls, keyword: str = None, filter_ids: List[int] = None) -> List[Dashboard]:
        """
        Get a list of simple Kanban boards
        :param keyword: Search by keywords
        :param filter_ids: Filtered KanbanIDVertical
        :return:
        """
        filter_types = [DashboardType.PRESET_OSS]
        if is_commercial():
            filter_types = [DashboardType.PRESET_COMMERCIAL, DashboardType.CUSTOM]
        res = await DashboardDao.get_dashboards(dashboard_type=filter_types, keyword=keyword, filter_ids=filter_ids)
        return res

    async def get_dashboards(self, keyword: str = None) -> List[DashboardRead]:
        """
        Get a list of Kanban boards
        :param keyword: Search by keywords
        :return:
        """
        manage_ids = []
        filter_types = [DashboardType.PRESET_OSS]
        if is_commercial():
            filter_types = [DashboardType.PRESET_COMMERCIAL, DashboardType.CUSTOM]
        is_department_admin = False
        components_by_dashboard_id = {}
        if self.login_user.is_admin():
            res = await DashboardDao.get_dashboards(keyword=keyword, dashboard_type=filter_types)
        else:
            # find extra dashboard ids
            manage_ids = await self.login_user.aget_user_access_resource_ids(
                access_types=[AccessType.DASHBOARD_WRITE])
            manage_ids = [int(one) for one in manage_ids]
            extra_ids = await self.login_user.aget_user_access_resource_ids(access_types=[AccessType.DASHBOARD])
            extra_ids = [int(one) for one in extra_ids]
            extra_ids = list(set(extra_ids) - set(manage_ids))

            accessible_dashboards = await DashboardDao.get_dashboards(
                keyword=keyword,
                dashboard_type=filter_types,
                user_id=self.login_user.user_id,
                extra_status=DashboardStatus.PUBLISHED,
                extra_ids=extra_ids,
                manage_ids=manage_ids,
            )
            res = accessible_dashboards
            is_department_admin = await self._is_department_admin()
            if is_department_admin:
                accessible_ids = {
                    dashboard.id for dashboard in accessible_dashboards
                }
                all_dashboards = await DashboardDao.get_dashboards(
                    keyword=keyword,
                    dashboard_type=filter_types,
                )
                res = []
                for dashboard in all_dashboards:
                    if dashboard.id in accessible_ids:
                        res.append(dashboard)
                        continue
                    if dashboard.status != DashboardStatus.PUBLISHED.value:
                        continue
                    components = await DashboardDao.get_components(dashboard.id)
                    components_by_dashboard_id[dashboard.id] = components
                    if self._uses_realtime_dataset(components):
                        res.append(dashboard)
        default_dashboard = await DashboardDao.get_default_dashboard(user_id=self.login_user.user_id)
        result = []
        for one in res:
            components = components_by_dashboard_id.get(one.id)
            if components is None:
                components = await DashboardDao.get_components(one.id)
            uses_realtime = self._uses_realtime_dataset(components)
            if uses_realtime and not self.login_user.is_admin():
                if (
                    one.status != DashboardStatus.PUBLISHED.value
                    or not is_department_admin
                ):
                    continue
            tmp = DashboardRead.model_validate(one)
            if default_dashboard and one.id == default_dashboard.dashboard_id:
                tmp.is_default = True
            if (
                not uses_realtime
                and (
                    tmp.user_id == self.login_user.user_id
                    or tmp.id in manage_ids
                )
            ) or self.login_user.is_admin():
                tmp.write = True
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
        if not await self.login_user.async_access_check(0, target_id=WebMenuResource.CREATE_DASHBOARD.value,
                                                        access_type=AccessType.WEB_MENU):
            raise UnAuthorizedError()

        user_total = await DashboardDao.count_dashboards(
            dashboard_type=[DashboardType.PRESET_COMMERCIAL, DashboardType.CUSTOM])
        if user_total >= 20:
            raise DashboardMaxError()

        dashboard = Dashboard.model_validate(data)

        dashboard.dashboard_type = DashboardType.CUSTOM.value
        dashboard.user_id = self.login_user.user_id

        dashboard = await DashboardDao.insert(dashboard)
        await self.create_dashboard_hook(dashboard)
        return dashboard

    async def create_dashboard_hook(self, dashboard: Dashboard):
        """
        Create a Kanban Hook
        :param dashboard:
        :return:
        """
        group_ids = await self.login_user.get_user_group_ids()
        group_ids = list(set(group_ids))
        if group_ids:
            batch_resource = []
            for one in group_ids:
                batch_resource.append(GroupResource(
                    group_id=one,
                    third_id=dashboard.id,
                    type=ResourceTypeEnum.DASHBOARD.value))
            await GroupResourceDao.ainsert_group_batch(batch_resource)
        await AuditLogService.create_dashboard(self.login_user, get_request_ip(self.request), str(dashboard.id),
                                               dashboard.title, group_ids=group_ids)

    async def delete_dashboard(self, dashboard_id: int) -> bool:
        dashboard = await DashboardDao.get_one(dashboard_id)
        if not dashboard:
            return True
        if dashboard.dashboard_type == DashboardType.PRESET_OSS.value:
            raise UnAuthorizedError()
        await self._ensure_realtime_dashboard_write(dashboard_id)
        if not await self.login_user.async_access_check(dashboard.user_id, target_id=str(dashboard.id),
                                                        access_type=AccessType.DASHBOARD_WRITE):
            raise UnAuthorizedError()

        await self.delete_dashboard_hook(dashboard)

        return await DashboardDao.delete_one(dashboard_id)

    async def delete_dashboard_hook(self, dashboard: Dashboard):
        """
        Remove Kanban Hook
        :param dashboard:
        :return:
        """
        resource_group = await GroupResourceDao.aget_resource_group(ResourceTypeEnum.DASHBOARD, str(dashboard.id))
        group_ids = [int(one.group_id) for one in resource_group]
        await AuditLogService.delete_dashboard(self.login_user, get_request_ip(self.request), str(dashboard.id),
                                               dashboard.title, group_ids=group_ids)

    async def update_dashboard_title(self, dashboard_id: int, new_title: str) -> bool:
        dashboard = await DashboardDao.get_one(dashboard_id)
        if not dashboard:
            return True
        await self._ensure_realtime_dashboard_write(dashboard_id)
        if not await self.login_user.async_access_check(dashboard.user_id, target_id=str(dashboard.id),
                                                        access_type=AccessType.DASHBOARD_WRITE):
            raise UnAuthorizedError()

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
        resource_group = await GroupResourceDao.aget_resource_group(ResourceTypeEnum.DASHBOARD, str(dashboard.id))
        group_ids = [int(one.group_id) for one in resource_group]
        await AuditLogService.update_dashboard(self.login_user, get_request_ip(self.request), str(dashboard.id),
                                               dashboard.title, group_ids=group_ids)

    async def update_dashboard_status(self, dashboard_id: int, new_status: DashboardStatus) -> bool:
        dashboard = await DashboardDao.get_one(dashboard_id)
        if not dashboard:
            return True
        await self._ensure_realtime_dashboard_write(dashboard_id)
        if not await self.login_user.async_access_check(dashboard.user_id, target_id=str(dashboard.id),
                                                        access_type=AccessType.DASHBOARD_WRITE):
            raise UnAuthorizedError()
        if dashboard.status == new_status.value:
            return True
        await DashboardDao.update_dashboard_status(dashboard_id, new_status)
        await self.update_dashboard_hook(dashboard)
        return True

    async def set_default_dashboard(self, dashboard_id: int) -> DashboardDefault:
        return await DashboardDao.set_default_dashboard(self.login_user.user_id, dashboard_id)

    async def get_dashboard_detail(self, dashboard_id: int, from_share: bool) -> DashboardRead:
        dashboard = await DashboardDao.get_one(dashboard_id)
        if not dashboard:
            raise NotFoundError()
        if not is_commercial() and dashboard.dashboard_type != DashboardType.PRESET_OSS.value:
            raise NotFoundError()
        write_flag = await self.login_user.async_access_check(dashboard.user_id, target_id=str(dashboard.id),
                                                              access_type=AccessType.DASHBOARD_WRITE)
        read_flag = write_flag or await self.login_user.async_access_check(
            dashboard.user_id,
            target_id=str(dashboard.id),
            access_type=AccessType.DASHBOARD,
        )
        components = await DashboardDao.get_components(dashboard_id)
        uses_realtime = self._uses_realtime_dataset(components)
        department_realtime_view = (
            uses_realtime
            and dashboard.status == DashboardStatus.PUBLISHED.value
            and not self.login_user.is_admin()
            and await self._is_department_admin()
        )
        if not read_flag and not department_realtime_view:
            if from_share:
                raise DashBoardShareAuthError()

            raise UnAuthorizedError()

        if uses_realtime and not self.login_user.is_admin():
            if (
                dashboard.status != DashboardStatus.PUBLISHED.value
                or not await self._is_department_admin()
            ):
                raise UnAuthorizedError()
        result = DashboardRead.model_validate(dashboard)
        result.write = write_flag and (
            self.login_user.is_admin() or not uses_realtime
        )
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
        await self._ensure_realtime_dashboard_write(dashboard_id)
        if not await self.login_user.async_access_check(dashboard.user_id, target_id=str(dashboard.id),
                                                        access_type=AccessType.DASHBOARD):
            raise UnAuthorizedError()

        user_total = await DashboardDao.count_dashboards(
            dashboard_type=[DashboardType.PRESET_COMMERCIAL, DashboardType.CUSTOM])
        if user_total >= 20:
            raise DashboardMaxError()

        # create new dashboard
        new_dashboard = Dashboard.model_validate(dashboard)
        new_dashboard.id = None
        new_dashboard.title = new_title
        new_dashboard.user_id = self.login_user.user_id
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

        # update filter components data config
        for one in new_components:
            if one.type in {'query', 'dimension-filter'}:
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
        await self._ensure_realtime_dashboard_write(
            dashboard.id,
            dashboard.components,
        )
        if not await self.login_user.async_access_check(old_dashboard.user_id, target_id=str(old_dashboard.id),
                                                        access_type=AccessType.DASHBOARD_WRITE):
            raise UnAuthorizedError()

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
        component_id: str = None,
        component: DashboardComponent = None,
        time_filters: List[TimeFilter] = None,
        dimension_filters=None,
    ) -> Any:
        """ query component telemetry data """
        dashboard = await DashboardDao.get_one(dashboard_id)
        if not dashboard:
            raise NotFoundError()
        read_flag = await self.login_user.async_access_check(
            dashboard.user_id,
            target_id=str(dashboard.id),
            access_type=AccessType.DASHBOARD,
        )
        if not read_flag:
            stored_components = await DashboardDao.get_components(dashboard_id)
            if (
                dashboard.status != DashboardStatus.PUBLISHED.value
                or not self._uses_realtime_dataset(stored_components)
                or not await self._is_department_admin()
                or component_id is None
            ):
                raise UnAuthorizedError()
        if component_id is not None:
            component = await DashboardDao.get_one_component(component_id)
            if (
                not component
                or str(component.dashboard_id) != str(dashboard_id)
            ):
                raise NotFoundError()
        if component is None:
            raise NotFoundError()
        if (
            component.dataset_code in self.REALTIME_SCOPED_DATASETS
            and not self.login_user.is_admin()
            and dashboard.status != DashboardStatus.PUBLISHED.value
        ):
            raise UnAuthorizedError()
        data_config = ComponentDataConfig(**component.data_config)
        scope_filters = await self._get_realtime_scope_filters(component.dataset_code)
        res = await DataQueryService(
            dataset_code=component.dataset_code,
            data_config=data_config,
            time_filters=time_filters,
            dimension_filters=dimension_filters or [],
            scope_filters=scope_filters,
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

    async def get_dataset_field_enums(
        self,
        dataset_code: str,
        field: str,
        keyword: str = None,
        size: int = 20,
        page: int = 1,
        label_field: str = None,
        exact_values: str = None,
    ) -> Dict[str, Any]:
        """
        Get dataset field enum value with server-side pagination using aggregation filters
        """
        async with get_async_db_session() as session:
            repository = DashboardDatasetRepositoryImpl(session)
            dataset = await repository.find_one(dataset_code=dataset_code)
        if not dataset:
            raise NotFoundError()
        schema_config = dataset.schema_config if isinstance(dataset.schema_config, dict) else {}
        allowed_fields = {
            dimension.get("field")
            for dimension in schema_config.get("dimensions", [])
            if dimension.get("field")
        }
        if field not in allowed_fields or (
            label_field and label_field not in allowed_fields
        ):
            raise UnAuthorizedError()

        scope_filters = await self._get_realtime_scope_filters(dataset_code)
        skip = (page - 1) * size
        es_client = await get_es_connection()

        core_aggs = {
            "enum_values": {
                "terms": {
                    "field": field,
                    "size": 65536,
                    "order": {"_key": "asc"}
                },
                "aggs": {
                    **(
                        {
                            "label_value": {
                                "terms": {
                                    "field": label_field,
                                    "size": 1,
                                    "order": {"_key": "asc"},
                                }
                            }
                        }
                        if label_field
                        else {}
                    ),
                    "pagination": {
                        "bucket_sort": {
                            "from": skip,
                            "size": size
                        }
                    }
                }
            },
            "total_count": {
                "cardinality": {
                    "field": field
                }
            }
        }

        current_aggs = core_aggs

        if keyword:
            search_field = label_field or field
            filter_query = {"match_phrase": {f"{search_field}.text": keyword}}

            current_aggs = {
                "filter_wrapper": {
                    "filter": filter_query,
                    "aggs": core_aggs
                }
            }

        if "." in field:
            path = field.rsplit('.', 1)[0]
            aggs_body = {
                "nested_agg": {
                    "nested": {"path": path},
                    "aggs": current_aggs
                }
            }
        else:
            aggs_body = current_aggs

        body = {
            "size": 0,
            "aggs": aggs_body
        }
        query_filters = [
            {
                "terms": {
                    scope_filter.field_id: scope_filter.values,
                }
            }
            for scope_filter in scope_filters
        ]
        normalized_exact_values = [
            value.strip()
            for value in (exact_values or "").split(",")
            if value.strip()
        ]
        if normalized_exact_values:
            query_filters.append({"terms": {field: normalized_exact_values}})
        if query_filters:
            body["query"] = {
                "bool": {
                    "filter": query_filters,
                }
            }

        resp = await es_client.search(index=dataset.es_index_name, body=body)

        aggs_root = resp.get("aggregations", {})

        if "." in field:
            aggs_root = aggs_root.get("nested_agg", {})

        if keyword:
            aggs_root = aggs_root.get("filter_wrapper", {})

        total = aggs_root.get("total_count", {}).get("value", 0)
        buckets = aggs_root.get("enum_values", {}).get("buckets", [])
        enums = [bucket.get("key") for bucket in buckets]
        options = []
        for bucket in buckets:
            value = bucket.get("key")
            label_buckets = bucket.get("label_value", {}).get("buckets", [])
            label = (
                label_buckets[0].get("key")
                if label_buckets
                else value
            )
            options.append({"value": value, "label": label})
        if (
            dataset_code == "mid_knowledge_space_content_stat"
            and field == "space_level"
        ):
            canonical_options = {}
            for option in options:
                canonical_value = (
                    "team"
                    if str(option["value"]) == "team_ks"
                    else str(option["value"])
                )
                canonical_options[canonical_value] = {
                    "value": canonical_value,
                    "label": self.FILE_SPACE_LEVEL_LABELS.get(
                        canonical_value,
                        option["label"],
                    ),
                }
            options = list(canonical_options.values())
            enums = [option["value"] for option in options]
            total = len(options)

        return {
            "total": total,
            "enums": enums,
            "options": options,
        }
