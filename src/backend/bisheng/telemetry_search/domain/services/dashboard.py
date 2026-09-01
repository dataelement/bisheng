from datetime import datetime
from typing import Any, ClassVar, Dict, List, Sequence

from fastapi import Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Row, RowMapping

from bisheng.api.services.audit_log import AuditLogService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import NotFoundError, UnAuthorizedError
from bisheng.common.errcode.telemetry import DashboardMaxError, DashBoardShareAuthError
from bisheng.core.database import get_async_db_session
from bisheng.core.search.elasticsearch.manager import get_es_connection
from bisheng.database.models.group_resource import GroupResource, GroupResourceDao, ResourceTypeEnum
from bisheng.database.models.role_access import AccessType, WebMenuResource
from bisheng.user.domain.services.user import UserService
from bisheng.utils import generate_uuid, get_request_ip

from bisheng.department.domain.services.department_service import DepartmentService
from bisheng.telemetry.domain.mid_table.knowledge_space_content_dimensions import ORG_LEVEL_FIELD_NAMES

from ..models.dashboard import Dashboard, DashboardComponent, DashboardDefault, DashboardStatus, DashboardType
from ..models.dashboard_dao import DashboardDao
from ..repositories.implementations.dataset_repository_impl import DashboardDatasetRepositoryImpl
from ..schemas.dashboard import DashboardCreate, DashboardRead
from ..services.component import ComponentDataConfig, DataQueryService, TimeFilter
from ..utils import is_commercial
from .department_label_resolver import resolve_short_name

# F058: dashboard org-hierarchy dimensions (both "所属"/belonging_* and "原始上传库"/uploader_*
# variants) are name-text snapshots of Department rows at ETL time, not a live join. Filter
# options for these fields must come from the live Department tree (AC-01: show org units with
# no data too), not from an ES terms aggregation over the dataset index.
_NAME_FIELD_TO_ORG_LEVEL: Dict[str, str] = {value: key for key, value in ORG_LEVEL_FIELD_NAMES.items()}
_ORG_FIELD_PREFIXES = ("belonging_", "uploader_")


def _org_level_for_field(field: str) -> str | None:
    for prefix in _ORG_FIELD_PREFIXES:
        if field.startswith(prefix):
            return _NAME_FIELD_TO_ORG_LEVEL.get(field[len(prefix):])
    return None


class DashboardService(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    request: Request = None
    login_user: UserPayload = None

    REALTIME_DATASETS: ClassVar[set[str]] = {
        "mid_knowledge_space_content_stat",
        "mid_realtime_qa_question_fact",
        "mid_user_daily_participation",
    }
    FILE_SPACE_LEVEL_LABELS: ClassVar[dict[str, str]] = {
        "public": "公共库",
        "department": "部门库",
        "team": "团队库",
        "team_ks": "科室库",
        "personal": "个人库",
    }
    APPLICATION_TYPE_LABELS: ClassVar[dict[str, str]] = {
        "workflow": "工作流",
        "assistant": "助手",
        "linsight": "Linsight",
        "daily_chat": "日常对话",
        "knowledge_base": "知识库",
        "knowledge_space": "知识空间",
        "rag_traceability": "RAG溯源",
        "evaluation": "模型评测",
        "model_test": "模型连通性测试",
        "asr": "语音识别",
        "tts": "语音合成",
        "unknown": "未知",
    }
    STATUS_LABELS: ClassVar[dict[str, str]] = {
        "success": "成功",
        "failed": "失败",
        "parse_failed": "解析失败",
    }
    DASHBOARD_ENUM_LABELS: ClassVar[
        dict[str, dict[str, dict[str, str]]]
    ] = {
        "mid_knowledge_space_content_stat": {
            "space_level": FILE_SPACE_LEVEL_LABELS,
        },
        "mid_app_increment": {
            "app_type": APPLICATION_TYPE_LABELS,
        },
        "mid_sessions_increment": {
            "source": {
                "platform": "平台端",
                "api": "API调用",
            },
            "app_id": APPLICATION_TYPE_LABELS,
        },
        "mid_session_run_dtl": {
            "app_id": APPLICATION_TYPE_LABELS,
        },
        "mid_tool_call_dtl": {
            "tool_type": {
                "0": "API工具",
                "1": "内置工具",
                "2": "MCP工具",
            },
            "app_type": APPLICATION_TYPE_LABELS,
            "app_id": APPLICATION_TYPE_LABELS,
        },
        "mid_doc_parse_dtl": {
            "parse_type": {
                "local": "本地解析",
                "uns": "UNS解析",
                "etl4lm": "ETL4LM解析",
                "un_etl4lm": "非ETL4LM解析",
                "mineru": "MinerU解析",
                "paddle_ocr": "PaddleOCR解析",
            },
            "status": STATUS_LABELS,
            "app_type": APPLICATION_TYPE_LABELS,
        },
        "mid_model_call_dtl": {
            "model_type": {
                "llm": "大语言模型",
                "embedding": "嵌入模型",
                "rerank": "重排模型",
                "asr": "语音识别",
                "tts": "语音合成",
            },
            "app_id": APPLICATION_TYPE_LABELS,
        },
        "mid_realtime_qa_question_fact": {
            "department_source": {
                "event_time": "提问时所属主部门",
                "current_primary_backfill": "当前主部门（历史回填）",
            },
            "scene": {
                "expert_question": "专家问答",
                "smart_qa": "智能问答",
                "document_qa": "知识门户·文档问答",
                "my_knowledge_document_qa": "我的知识·文档问答",
            },
            "source_app": {
                "bisheng_my_knowledge": "毕昇·我的知识",
                "expert_qa": "专家问答",
                "shougang_portal": "首钢知识门户",
            },
        },
        "mid_user_daily_participation": {
            "department_source": {
                "event_time": "登录时所属主部门",
                "current_roster": "当前在职名册",
                "current_roster_backfill": "当前名册（历史回填）",
                "current_primary_backfill": "当前主部门（历史登录回填）",
            },
        },
    }

    @staticmethod
    def _format_date_enum_label(value: Any) -> Any:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return value
        return datetime.fromtimestamp(value / 1000).strftime("%Y-%m-%d %H:%M:%S")

    @classmethod
    def _get_enum_labels(
        cls,
        dataset_code: str,
        field: str,
    ) -> dict[str, str]:
        return cls.DASHBOARD_ENUM_LABELS.get(dataset_code, {}).get(field, {})

    @classmethod
    def _uses_realtime_dataset(
        cls,
        components: Sequence[DashboardComponent],
    ) -> bool:
        return any(
            component.dataset_code in cls.REALTIME_DATASETS
            for component in components
        )

    def _can_operate_dashboards(self) -> bool:
        """超管或运营岗: 看板列表/实时写与超管同一口径."""
        from bisheng.user.domain.services.platform_operator import can_platform_operate

        return can_platform_operate(self.login_user)

    async def _is_department_admin(self) -> bool:
        if self._can_operate_dashboards():
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
        if self._can_operate_dashboards():
            return
        existing_components = await DashboardDao.get_components(dashboard_id)
        if self._uses_realtime_dataset(
            [*existing_components, *incoming_components]
        ):
            raise UnAuthorizedError()

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
        if self._can_operate_dashboards():
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
            if uses_realtime and not self._can_operate_dashboards():
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
            ) or self._can_operate_dashboards():
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
        can_operate = self._can_operate_dashboards()
        write_flag = await self.login_user.async_access_check(dashboard.user_id, target_id=str(dashboard.id),
                                                              access_type=AccessType.DASHBOARD_WRITE)
        read_flag = write_flag or await self.login_user.async_access_check(
            dashboard.user_id,
            target_id=str(dashboard.id),
            access_type=AccessType.DASHBOARD,
        )
        # 运营岗/超管列表已走 admin 口径; 详情与组件查询不能再卡 ReBAC 读 tuple.
        if can_operate:
            read_flag = True
            write_flag = True
        components = await DashboardDao.get_components(dashboard_id)
        uses_realtime = self._uses_realtime_dataset(components)
        department_realtime_view = (
            uses_realtime
            and dashboard.status == DashboardStatus.PUBLISHED.value
            and not self._can_operate_dashboards()
            and await self._is_department_admin()
        )
        if not read_flag and not department_realtime_view:
            if from_share:
                raise DashBoardShareAuthError()

            raise UnAuthorizedError()

        if uses_realtime and not self._can_operate_dashboards():
            if (
                dashboard.status != DashboardStatus.PUBLISHED.value
                or not await self._is_department_admin()
            ):
                raise UnAuthorizedError()
        result = DashboardRead.model_validate(dashboard)
        result.write = write_flag and (
            self._can_operate_dashboards() or not uses_realtime
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
        _dashboard, component = await self._authorize_component_access(
            dashboard_id, component_id, component,
        )
        data_config = ComponentDataConfig(**component.data_config)
        res = await DataQueryService(
            dataset_code=component.dataset_code,
            data_config=data_config,
            time_filters=time_filters,
            dimension_filters=dimension_filters or [],
        ).query_telemetry_data()
        return res

    async def _authorize_component_access(
        self,
        dashboard_id: int,
        component_id: str = None,
        component: DashboardComponent = None,
    ) -> "tuple[Dashboard, DashboardComponent]":
        """Shared access + component-ownership check for anything that reads one
        dashboard component's telemetry data (chart query, F058 detail/all export).
        Do not duplicate this logic elsewhere — extend it here instead."""
        dashboard = await DashboardDao.get_one(dashboard_id)
        if not dashboard:
            raise NotFoundError()
        read_flag = True if self._can_operate_dashboards() else await self.login_user.async_access_check(
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
            component.dataset_code in self.REALTIME_DATASETS
            and not self._can_operate_dashboards()
            and dashboard.status != DashboardStatus.PUBLISHED.value
        ):
            raise UnAuthorizedError()
        return dashboard, component

    @staticmethod
    async def get_dataset_options() -> Sequence[Row[Any] | RowMapping | Any]:
        """
        Can get all available datasets for dashboards
        :return:
        """

        async with get_async_db_session() as session:
            dashboard_dataset_repository = DashboardDatasetRepositoryImpl(session)
            if is_commercial():
                datasets = await dashboard_dataset_repository.find_all(is_visible=True)
            else:
                datasets = await dashboard_dataset_repository.find_all(
                    is_commercial_only=False, is_visible=True,
                )

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
        dimension_by_field = {
            dimension.get("field"): dimension
            for dimension in schema_config.get("dimensions", [])
            if dimension.get("field")
        }
        allowed_fields = set(dimension_by_field)
        if field not in allowed_fields or (
            label_field and label_field not in allowed_fields
        ):
            raise UnAuthorizedError()
        org_level = _org_level_for_field(field)
        if org_level is not None:
            return await self._get_org_unit_field_enums(
                org_level=org_level, keyword=keyword, size=size, page=page,
            )

        label_dimension = dimension_by_field[label_field or field]
        label_field_type = label_dimension.get("field_type") or label_dimension.get("type")

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

        enum_labels = self._get_enum_labels(dataset_code, field)
        if keyword:
            search_field = label_field or field
            text_filter = {"match_phrase": {f"{search_field}.text": keyword}}
            if enum_labels:
                normalized_keyword = keyword.casefold()
                matched_values = [
                    value
                    for value, label in enum_labels.items()
                    if normalized_keyword in value.casefold()
                    or normalized_keyword in label.casefold()
                ]
                search_filters = [text_filter]
                if matched_values:
                    search_filters.append({"terms": {field: matched_values}})
                filter_query = {
                    "bool": {
                        "should": search_filters,
                        "minimum_should_match": 1,
                    }
                }
            else:
                filter_query = text_filter

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
        query_filters = []
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
            if label_field_type == "date":
                label = self._format_date_enum_label(label)
            else:
                label = enum_labels.get(str(value), label)
            options.append({"value": value, "label": label})
        return {
            "total": total,
            "enums": enums,
            "options": options,
        }

    async def _get_org_unit_field_enums(
        self, org_level: str, keyword: str | None, size: int, page: int,
    ) -> Dict[str, Any]:
        """F058 AC-01/AC-02/AC-03: full Department roster for one org tier, independent of
        whether the tier has any data in the current dataset's ES index."""
        roots = await DepartmentService.aget_tree(self.login_user)

        matches = []

        def _walk(nodes) -> None:
            for node in nodes:
                if node.status == "active" and node.org_level == org_level:
                    matches.append(node)
                _walk(node.children)

        _walk(roots)

        if keyword:
            normalized_keyword = keyword.casefold()
            matches = [
                node
                for node in matches
                if normalized_keyword in node.name.casefold()
                or (node.short_name and normalized_keyword in node.short_name.casefold())
            ]

        matches.sort(key=lambda node: (node.sort_order, node.name))

        total = len(matches)
        skip = (page - 1) * size
        page_matches = matches[skip: skip + size]

        options = []
        for node in page_matches:
            label = await resolve_short_name(department_id=node.id, name_text=node.name)
            options.append({"value": node.name, "label": label})

        return {
            "total": total,
            "enums": [option["value"] for option in options],
            "options": options,
        }
