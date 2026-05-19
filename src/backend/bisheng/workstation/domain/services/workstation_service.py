import json
from typing import Any, Optional

from fastapi import BackgroundTasks, Request
from langchain_core.messages import AIMessage, HumanMessage
from loguru import logger
from sqlmodel import select, col

from bisheng.api.v1.schema.chat_schema import UseKnowledgeBaseParam
from bisheng.api.v1.schemas import (
    KnowledgeFileOne,
    KnowledgeFileProcess,
    KnowledgeSpaceConfig,
    LinsightConfig,
    SubscriptionConfig,
    ToolConfig,
    WorkstationConfig,
    WSPrompt,
)
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.server import EmbeddingModelStatusError
from bisheng.common.models.config import Config, ConfigDao, ConfigKeyEnum
from bisheng.common.services.base import BaseService
from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import DEFAULT_TENANT_ID, get_current_tenant_id, strict_tenant_filter, \
    bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.core.vectorstore.multi_retriever import MultiRetriever
from bisheng.database.constants import MessageCategory
from bisheng.database.models.flow import Flow
from bisheng.database.models.message import ChatMessageDao
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.models.knowledge import KnowledgeCreate, KnowledgeDao, KnowledgeTypeEnum
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.llm.domain.schemas import WorkbenchModelConfig
from bisheng.llm.domain.services import LLMService
from bisheng.tool.domain.const import ToolPresetType
from bisheng.tool.domain.langchain.knowledge import KnowledgeRetrieverTool
from bisheng.tool.domain.models.gpts_tools import GptsTools, GptsToolsDao, GptsToolsType
from ..models import TenantWorkstationConfigDao


class WorkStationService(BaseService):
    _TENANT_KEYS = {
        ConfigKeyEnum.WORKSTATION.value,
        ConfigKeyEnum.WORKSTATION_LINSIGHT.value,
        ConfigKeyEnum.WORKSTATION_SUBSCRIPTION.value,
        ConfigKeyEnum.WORKSTATION_KNOWLEDGE_SPACE.value,
    }

    @classmethod
    def _multi_tenant_enabled(cls) -> bool:
        return bool(getattr(getattr(settings, 'multi_tenant', None), 'enabled', False))

    @classmethod
    def _current_tenant_id(cls) -> int:
        return get_current_tenant_id() or DEFAULT_TENANT_ID

    @classmethod
    def _serialize_json(cls, value: Any) -> str:
        return json.dumps(value, ensure_ascii=True)

    @classmethod
    def _make_envelope(
        cls,
        data: Any,
        inherited_from_root: bool,
        source_tenant_id: int,
        has_override: bool,
    ) -> dict:
        if hasattr(data, 'model_dump'):
            payload = data.model_dump(exclude_unset=True)
        else:
            payload = data
        return {
            'data': payload,
            'inherited_from_root': inherited_from_root,
            'source_tenant_id': source_tenant_id,
            'has_override': has_override,
        }

    @classmethod
    def _apply_workbench_models(
        cls,
        config: Optional[WorkstationConfig],
        workbench_config: Optional[WorkbenchModelConfig],
    ) -> Optional[WorkstationConfig]:
        models = getattr(workbench_config, 'models', None)
        if config is None:
            if models is None:
                return None
            return WorkstationConfig(models=models)
        if models is not None:
            config.models = models
        return config

    @classmethod
    async def _abuild_default_daily_config(cls) -> WorkstationConfig:
        """Return the historical daily-chat defaults when no workstation config exists."""
        current_tenant_id = cls._current_tenant_id()
        web_search_db = None
        parent = None

        try:
            with strict_tenant_filter():
                web_search_db = GptsToolsDao.get_tool_by_tool_key('web_search')
        except Exception:
            web_search_db = None

        if web_search_db is None and cls._multi_tenant_enabled() and current_tenant_id != DEFAULT_TENANT_ID:
            try:
                await cls.acopy_root_builtin_tools_to_tenant(current_tenant_id)
                with strict_tenant_filter():
                    web_search_db = GptsToolsDao.get_tool_by_tool_key('web_search')
            except Exception:
                web_search_db = None

        if web_search_db is not None:
            try:
                parent_types = GptsToolsDao.get_all_tool_type([web_search_db.type])
                parent = parent_types[0] if parent_types else None
            except Exception:
                parent = None

        tools = None
        if web_search_db is not None:
            tools = [ToolConfig(
                id=web_search_db.type,
                name=parent.name if parent else '联网搜索',
                is_preset=parent.is_preset if parent else 1,
                description=parent.description if parent else 'Search the internet for real-time information',
                default_checked=True,
                children=[{
                    'id': web_search_db.id,
                    'name': web_search_db.name,
                    'tool_key': web_search_db.tool_key,
                    'desc': web_search_db.desc,
                }],
            )]

        return WorkstationConfig(
            knowledgeBase=WSPrompt(enabled=True, prompt=''),
            fileUpload=WSPrompt(enabled=True, prompt=''),
            webSearch=WSPrompt(enabled=True, prompt=''),
            tools=tools,
            orgKbs=[],
        )

    @classmethod
    def update_config(
        cls,
        request: Request,
        login_user: UserPayload,
        data: WorkstationConfig,
    ) -> WorkstationConfig:
        """Update workstation default configuration."""
        config = ConfigDao.get_config(ConfigKeyEnum.WORKSTATION)
        if config:
            config.value = data.model_dump_json()
        else:
            config = Config(key=ConfigKeyEnum.WORKSTATION.value, value=json.dumps(data.dict()))
        ConfigDao.insert_config(config)
        return data

    @classmethod
    async def _aresolve_tenant_config(
        cls, key: ConfigKeyEnum,
    ) -> tuple[Optional[str], bool, int, bool]:
        if not cls._multi_tenant_enabled():
            legacy = await ConfigDao.aget_config(key)
            return (
                legacy.value if legacy and legacy.value else None,
                False,
                DEFAULT_TENANT_ID,
                bool(legacy and legacy.value),
            )
        return await TenantWorkstationConfigDao.aresolve(cls._current_tenant_id(), key.value)

    @classmethod
    def _resolve_tenant_config(
        cls, key: ConfigKeyEnum,
    ) -> tuple[Optional[str], bool, int, bool]:
        if not cls._multi_tenant_enabled():
            legacy = ConfigDao.get_config(key)
            return (
                legacy.value if legacy and legacy.value else None,
                False,
                DEFAULT_TENANT_ID,
                bool(legacy and legacy.value),
            )
        return TenantWorkstationConfigDao.resolve(cls._current_tenant_id(), key.value)

    @classmethod
    async def _aupsert_tenant_config(cls, key: ConfigKeyEnum, payload: str) -> None:
        if not cls._multi_tenant_enabled():
            await ConfigDao.insert_or_update_config(key.value, value=payload)
            return
        await TenantWorkstationConfigDao.aupsert(cls._current_tenant_id(), key.value, payload)

    @classmethod
    def sync_tool_info(cls, tools: list[dict]) -> list[dict]:
        """Synchronize tool metadata from persistent storage."""
        if not tools:
            return []
        normalized_tools = [cls._to_plain_dict(tool) for tool in tools]
        tool_type_ids = [tool.get('id') for tool in normalized_tools if tool]
        tool_type_info = GptsToolsDao.get_all_tool_type(tool_type_ids)
        exists_tool_type = {tool.id: tool for tool in tool_type_info}
        tool_info = GptsToolsDao.get_list_by_type(list(exists_tool_type.keys()))
        exists_tool_info = {tool.id: tool for tool in tool_info}
        new_tools = []
        for tool in normalized_tools:
            if not tool:
                continue
            new_tool = exists_tool_type.get(tool.get('id'))
            if not new_tool:
                continue
            tool['name'] = new_tool.name
            tool['description'] = new_tool.description
            new_children = []
            for item in tool.get('children', []):
                item = cls._to_plain_dict(item)
                if not item:
                    continue
                child = exists_tool_info.get(item.get('id'))
                if not child:
                    continue
                item['name'] = child.name
                item['description'] = child.desc
                item['tool_key'] = child.tool_key
                new_children.append(item)
            tool['children'] = new_children
            new_tools.append(tool)
        return new_tools

    @classmethod
    def _group_tool_rows(cls, tool_rows: list[GptsTools], type_rows: list[GptsToolsType]) -> list[dict]:
        type_map = {row.id: row for row in type_rows}
        grouped: dict[int, dict] = {}
        order: list[int] = []
        for row in tool_rows:
            parent = type_map.get(row.type)
            if parent is None:
                continue
            if parent.id not in grouped:
                grouped[parent.id] = {
                    'id': parent.id,
                    'name': parent.name,
                    'is_preset': parent.is_preset,
                    'description': parent.description,
                    'default_checked': False,
                    'children': [],
                }
                order.append(parent.id)
            grouped[parent.id]['children'].append({
                'id': row.id,
                'name': row.name,
                'tool_key': row.tool_key,
                'desc': row.desc,
            })
        return [grouped[type_id] for type_id in order]

    @classmethod
    def _to_plain_dict(cls, value: Any) -> dict:
        if isinstance(value, dict):
            return value
        if hasattr(value, 'model_dump'):
            return value.model_dump(exclude_unset=True)
        return {}

    @classmethod
    async def _ahydrate_tools_from_source_tenant(
        cls,
        tools: Optional[list],
        source_tenant_id: int,
    ) -> list[dict]:
        if not tools:
            return []
        source_child_ids: list[int] = []
        for group in tools:
            group = cls._to_plain_dict(group)
            if not group:
                continue
            for child in group.get('children', []) or []:
                child = cls._to_plain_dict(child)
                if not child:
                    continue
                child_id = child.get('id')
                if child_id:
                    source_child_ids.append(int(child_id))
        if not source_child_ids:
            return tools

        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                source_tool_rows = (await session.exec(
                    select(GptsTools).where(
                        GptsTools.tenant_id == source_tenant_id,
                        col(GptsTools.id).in_(source_child_ids),
                        GptsTools.is_delete == 0,
                    )
                )).all()
                type_ids = list({row.type for row in source_tool_rows if row.type is not None})
                source_type_rows: list[GptsToolsType] = []
                if type_ids:
                    source_type_rows = (await session.exec(
                        select(GptsToolsType).where(
                            GptsToolsType.tenant_id == source_tenant_id,
                            col(GptsToolsType.id).in_(type_ids),
                            GptsToolsType.is_delete == 0,
                        )
                    )).all()

        tool_by_id = {row.id: row for row in source_tool_rows}
        type_by_id = {row.id: row for row in source_type_rows}
        hydrated: list[dict] = []
        for group in tools:
            group = cls._to_plain_dict(group)
            if not group:
                continue
            group_children: list[dict] = []
            parent_row = type_by_id.get(group.get('id'))
            for child in group.get('children', []) or []:
                child = cls._to_plain_dict(child)
                if not child:
                    continue
                child_row = tool_by_id.get(child.get('id'))
                if child_row is not None:
                    group_children.append({
                        'id': child_row.id,
                        'name': child_row.name,
                        'tool_key': child_row.tool_key,
                        'desc': child_row.desc,
                    })
                    if parent_row is None:
                        parent_row = type_by_id.get(child_row.type)
                    continue
                if child.get('tool_key'):
                    group_children.append(child)
            if not group_children:
                continue
            hydrated.append({
                'id': parent_row.id if parent_row else group.get('id'),
                'name': parent_row.name if parent_row else group.get('name', ''),
                'is_preset': parent_row.is_preset if parent_row else group.get('is_preset'),
                'description': parent_row.description if parent_row else group.get('description'),
                'default_checked': bool(group.get('default_checked')),
                'children': group_children,
            })
        return hydrated

    @classmethod
    async def _aproject_tools_for_current_tenant(
        cls,
        tools: Optional[list],
        source_tenant_id: int = DEFAULT_TENANT_ID,
    ) -> list[dict]:
        if not tools:
            return []
        current_tenant_id = cls._current_tenant_id()
        tools = await cls._ahydrate_tools_from_source_tenant(tools, source_tenant_id)
        raw_children: list[dict] = []
        for group in tools:
            group = cls._to_plain_dict(group)
            if not group:
                continue
            default_checked = bool(group.get('default_checked'))
            for child in group.get('children', []) or []:
                child = cls._to_plain_dict(child)
                if not child:
                    continue
                raw_children.append({
                    'tool_key': child.get('tool_key'),
                    'default_checked': default_checked,
                })
        tool_keys = [item['tool_key'] for item in raw_children if item.get('tool_key')]
        if not tool_keys:
            return []

        async def _load_rows() -> tuple[list[GptsTools], list[GptsToolsType]]:
            with strict_tenant_filter():
                async with get_async_db_session() as session:
                    rows = await session.exec(
                        select(GptsTools).where(
                            col(GptsTools.tool_key).in_(tool_keys),
                            GptsTools.is_delete == 0,
                        )
                    )
                    loaded_tool_rows = rows.all()
                    type_ids = list({row.type for row in loaded_tool_rows if row.type is not None})
                    loaded_type_rows: list[GptsToolsType] = []
                    if type_ids:
                        loaded_type_rows = (await session.exec(
                            select(GptsToolsType).where(
                                col(GptsToolsType.id).in_(type_ids),
                                GptsToolsType.is_delete == 0,
                            )
                        )).all()
            return loaded_tool_rows, loaded_type_rows

        tool_rows, type_rows = await _load_rows()
        if current_tenant_id != DEFAULT_TENANT_ID:
            existing_keys = {row.tool_key for row in tool_rows}
            if any(key not in existing_keys for key in tool_keys):
                await cls.acopy_root_builtin_tools_to_tenant(current_tenant_id)
                tool_rows, type_rows = await _load_rows()
        tool_by_key = {row.tool_key: row for row in tool_rows}
        projected_rows: list[GptsTools] = []
        default_checked_types: set[int] = set()
        seen_tool_ids: set[int] = set()
        for item in raw_children:
            row = tool_by_key.get(item.get('tool_key'))
            if row is None or row.id in seen_tool_ids:
                continue
            seen_tool_ids.add(row.id)
            projected_rows.append(row)
            if item.get('default_checked'):
                default_checked_types.add(row.type)
        grouped = cls._group_tool_rows(projected_rows, type_rows)
        for group in grouped:
            if group['id'] in default_checked_types:
                group['default_checked'] = True
        return grouped

    @classmethod
    async def _afilter_org_kbs_for_current_tenant(cls, org_kbs: Optional[list]) -> list[dict]:
        if not org_kbs:
            return []
        normalized_items = [cls._to_plain_dict(item) for item in org_kbs]
        desired_ids = [int(item.get('id')) for item in normalized_items if item and item.get('id')]
        if not desired_ids:
            return []
        with strict_tenant_filter():
            rows = await KnowledgeDao.aget_list_by_ids(desired_ids)
        keep_ids = {row.id for row in rows}
        return [item for item in normalized_items if item and item.get('id') in keep_ids]

    @classmethod
    async def _afilter_recommended_apps_for_current_tenant(
        cls, recommended_apps: Optional[list[str]],
    ) -> list[str]:
        if not recommended_apps:
            return []
        with strict_tenant_filter():
            async with get_async_db_session() as session:
                rows = await session.exec(
                    select(Flow.id).where(col(Flow.id).in_(recommended_apps))
                )
                existing_ids = rows.all()
        normalized: list[str] = []
        for row in existing_ids:
            normalized.append(row[0] if isinstance(row, tuple) else row)
        keep = set(normalized)
        return [app_id for app_id in recommended_apps if app_id in keep]

    @classmethod
    async def _aproject_daily_config_for_current_tenant(
        cls, config: Optional[WorkstationConfig],
        source_tenant_id: int = DEFAULT_TENANT_ID,
    ) -> Optional[WorkstationConfig]:
        if config is None:
            return None
        updates = {
            'tools': await cls._aproject_tools_for_current_tenant(config.tools, source_tenant_id),
            'orgKbs': await cls._afilter_org_kbs_for_current_tenant(config.orgKbs),
            'recommendedApps': await cls._afilter_recommended_apps_for_current_tenant(config.recommendedApps),
        }
        return config.model_copy(update=updates)

    @classmethod
    async def _aproject_linsight_config_for_current_tenant(
        cls, config: Optional[LinsightConfig],
        source_tenant_id: int = DEFAULT_TENANT_ID,
    ) -> Optional[LinsightConfig]:
        if config is None:
            return None
        tools = await cls._aproject_tools_for_current_tenant(config.tools, source_tenant_id)
        return config.model_copy(update={'tools': tools})

    @classmethod
    async def _aproject_subscription_config_for_current_tenant(
        cls, config: Optional[SubscriptionConfig],
    ) -> Optional[SubscriptionConfig]:
        return config

    @classmethod
    async def _aproject_knowledge_space_config_for_current_tenant(
        cls, config: Optional[KnowledgeSpaceConfig],
    ) -> Optional[KnowledgeSpaceConfig]:
        return config

    @classmethod
    def parse_config(cls, config: Any) -> Optional[WorkstationConfig]:
        if not config:
            return None
        raw = json.loads(config.value)

        # Rollout from beta1 flat-leaf shape -> hierarchical LinSight shape:
        # flat entries carry `tool_key`; group them under their parent type_id
        # so Pydantic can load them into the new schema without data loss.
        raw_tools = raw.get('tools')
        if isinstance(raw_tools, list) and any(isinstance(t, dict) and 'tool_key' in t for t in raw_tools):
            try:
                type_ids = list({t.get('type_id') for t in raw_tools if isinstance(t, dict) and t.get('type_id')})
                parents = {p.id: p for p in GptsToolsDao.get_all_tool_type(type_ids)} if type_ids else {}
                grouped: dict = {}
                order: list = []
                for t in raw_tools:
                    if not isinstance(t, dict):
                        continue
                    parent_id = t.get('type_id') or t.get('id')
                    if parent_id not in grouped:
                        parent = parents.get(parent_id)
                        grouped[parent_id] = {
                            'id': parent_id,
                            'name': parent.name if parent else t.get('name', ''),
                            'is_preset': parent.is_preset if parent else None,
                            'description': parent.description if parent else t.get('description'),
                            'default_checked': bool(t.get('default_checked')),
                            'children': [],
                        }
                        order.append(parent_id)
                    # Prefer default_checked=True if any legacy leaf had it on.
                    if t.get('default_checked'):
                        grouped[parent_id]['default_checked'] = True
                    grouped[parent_id]['children'].append({
                        'id': t.get('id'),
                        'name': t.get('name'),
                        'tool_key': t.get('tool_key'),
                        'desc': t.get('description') or t.get('desc'),
                    })
                raw['tools'] = [grouped[pid] for pid in order]
            except Exception:
                # Best-effort; fall through and let Pydantic drop unknown keys.
                pass

        ret = WorkstationConfig(**raw)

        # Platform default: the built-in web_search tool must always appear in
        # `tools`. Fresh configs (tools is None) get it auto-seeded with
        # default_checked=True. Legacy rollout migrates from webSearch.enabled:
        # if admin had explicitly turned it off, preserve that by seeding with
        # default_checked=False instead of silently flipping it back on.
        if ret.tools is None:
            try:
                with strict_tenant_filter():
                    web_search_db = GptsToolsDao.get_tool_by_tool_key('web_search')
                    if web_search_db:
                        parent_types = GptsToolsDao.get_all_tool_type([web_search_db.type])
                        parent = parent_types[0] if parent_types else None
                        legacy_disabled = ret.webSearch is not None and not ret.webSearch.enabled
                        ret.tools = [ToolConfig(
                            id=web_search_db.type,
                            name=parent.name if parent else '联网搜索',
                            is_preset=parent.is_preset if parent else 1,
                            description=parent.description if parent else 'Search the internet for real-time information',
                            default_checked=not legacy_disabled,
                            children=[{
                                'id': web_search_db.id,
                                'name': web_search_db.name,
                                'tool_key': web_search_db.tool_key,
                                'desc': web_search_db.desc,
                            }],
                        )]
            except Exception:
                # Best-effort migration; absence of the tool shouldn't break config load.
                pass
        if ret.orgKbs is None:
            ret.orgKbs = []

        if ret.assistantIcon and ret.assistantIcon.relative_path:
            ret.assistantIcon.image = cls.get_logo_share_link(ret.assistantIcon.relative_path)
        if ret.sidebarIcon and ret.sidebarIcon.relative_path:
            ret.sidebarIcon.image = cls.get_logo_share_link(ret.sidebarIcon.relative_path)
        return ret

    @classmethod
    def get_config(cls) -> WorkstationConfig | None:
        """Get the default workstation configuration."""
        value, _, _, _ = cls._resolve_tenant_config(ConfigKeyEnum.WORKSTATION)
        config = type('TenantConfigValue', (), {'value': value}) if value else None
        ret = cls.parse_config(config)
        return cls._apply_workbench_models(ret, LLMService.get_workbench_llm_sync())

    @classmethod
    async def aget_config(cls) -> WorkstationConfig | None:
        """Get the default workstation configuration asynchronously."""
        value, inherited, _, _ = await cls._aresolve_tenant_config(ConfigKeyEnum.WORKSTATION)
        config = type('TenantConfigValue', (), {'value': value}) if value else None
        ret = cls.parse_config(config)
        if ret is None:
            ret = await cls._abuild_default_daily_config()
        if ret and not inherited:
            ret.tools = cls.sync_tool_info(ret.tools)
        if inherited:
            ret = await cls._aproject_daily_config_for_current_tenant(ret, DEFAULT_TENANT_ID)
        return cls._apply_workbench_models(ret, await LLMService.get_workbench_llm())

    @classmethod
    async def get_daily_chat_config(cls) -> WorkstationConfig | None:
        """Get the default workstation configuration for daily chat."""
        value, inherited, _, _ = await cls._aresolve_tenant_config(ConfigKeyEnum.WORKSTATION)
        config = type('TenantConfigValue', (), {'value': value}) if value else None
        ret = cls.parse_config(config)
        if ret is None:
            ret = await cls._abuild_default_daily_config()
        if ret and not inherited:
            ret.tools = cls.sync_tool_info(ret.tools)
        if inherited:
            ret = await cls._aproject_daily_config_for_current_tenant(ret, DEFAULT_TENANT_ID)
        return cls._apply_workbench_models(ret, await LLMService.get_workbench_llm())

    @classmethod
    async def update_daily_chat_config(cls, data: WorkstationConfig) -> WorkstationConfig:
        """Update the default workstation configuration for daily chat."""
        workstation_payload = data.model_copy(update={'models': None})
        await cls._aupsert_tenant_config(
            ConfigKeyEnum.WORKSTATION,
            payload=json.dumps(workstation_payload.model_dump(mode='json'), ensure_ascii=True),
        )
        return await cls.get_daily_chat_config()

    @classmethod
    async def get_daily_chat_config_with_meta(cls) -> tuple[Optional[WorkstationConfig], bool, int, bool]:
        value, inherited, source_tenant_id, has_override = await cls._aresolve_tenant_config(ConfigKeyEnum.WORKSTATION)
        config = type('TenantConfigValue', (), {'value': value}) if value else None
        ret = cls.parse_config(config)
        if ret is None:
            ret = await cls._abuild_default_daily_config()
        if ret and not inherited:
            ret.tools = cls.sync_tool_info(ret.tools)
        if inherited:
            ret = await cls._aproject_daily_config_for_current_tenant(ret, source_tenant_id)
        ret = cls._apply_workbench_models(ret, await LLMService.get_workbench_llm())
        return ret, inherited, source_tenant_id, has_override

    @classmethod
    async def get_linsight_config(cls) -> Optional[LinsightConfig]:
        """Get Linsight configuration."""
        value, inherited, _, _ = await cls._aresolve_tenant_config(ConfigKeyEnum.WORKSTATION_LINSIGHT)
        if not value:
            return None
        ret = LinsightConfig(**json.loads(value))
        if inherited:
            ret = await cls._aproject_linsight_config_for_current_tenant(ret, DEFAULT_TENANT_ID)
        else:
            ret.tools = cls.sync_tool_info(ret.tools)
        return ret

    @classmethod
    async def update_linsight_config(cls, data: LinsightConfig) -> LinsightConfig:
        """Update Linsight configuration."""
        await cls._aupsert_tenant_config(
            ConfigKeyEnum.WORKSTATION_LINSIGHT,
            payload=json.dumps(data.model_dump(mode='json'), ensure_ascii=True),
        )
        return data

    @classmethod
    async def get_linsight_config_with_meta(cls) -> tuple[Optional[LinsightConfig], bool, int, bool]:
        value, inherited, source_tenant_id, has_override = await cls._aresolve_tenant_config(
            ConfigKeyEnum.WORKSTATION_LINSIGHT
        )
        if not value:
            return None, inherited, source_tenant_id, has_override
        ret = LinsightConfig(**json.loads(value))
        if inherited:
            ret = await cls._aproject_linsight_config_for_current_tenant(ret, source_tenant_id)
        else:
            ret.tools = cls.sync_tool_info(ret.tools)
        return ret, inherited, source_tenant_id, has_override

    @classmethod
    async def get_subscription_config(cls) -> Optional[SubscriptionConfig]:
        """Get subscription configuration."""
        value, inherited, _, _ = await cls._aresolve_tenant_config(ConfigKeyEnum.WORKSTATION_SUBSCRIPTION)
        if not value:
            return None
        ret = SubscriptionConfig(**json.loads(value))
        if inherited:
            ret = await cls._aproject_subscription_config_for_current_tenant(ret)
        return ret

    @classmethod
    async def update_subscription_config(cls, data: SubscriptionConfig) -> SubscriptionConfig:
        """Update subscription configuration."""
        await cls._aupsert_tenant_config(
            ConfigKeyEnum.WORKSTATION_SUBSCRIPTION,
            payload=json.dumps(data.model_dump(mode='json'), ensure_ascii=True),
        )
        return data

    @classmethod
    async def get_subscription_config_with_meta(cls) -> tuple[Optional[SubscriptionConfig], bool, int, bool]:
        value, inherited, source_tenant_id, has_override = await cls._aresolve_tenant_config(
            ConfigKeyEnum.WORKSTATION_SUBSCRIPTION
        )
        if not value:
            return None, inherited, source_tenant_id, has_override
        ret = SubscriptionConfig(**json.loads(value))
        if inherited:
            ret = await cls._aproject_subscription_config_for_current_tenant(ret)
        return ret, inherited, source_tenant_id, has_override

    @classmethod
    async def get_knowledge_space_config(cls) -> Optional[KnowledgeSpaceConfig]:
        """Get knowledge space configuration."""
        value, inherited, _, _ = await cls._aresolve_tenant_config(ConfigKeyEnum.WORKSTATION_KNOWLEDGE_SPACE)
        if not value:
            return None
        ret = KnowledgeSpaceConfig(**json.loads(value))
        if inherited:
            ret = await cls._aproject_knowledge_space_config_for_current_tenant(ret)
        return ret

    @classmethod
    async def update_knowledge_space_config(cls, data: KnowledgeSpaceConfig) -> KnowledgeSpaceConfig:
        """Update knowledge space configuration."""
        await cls._aupsert_tenant_config(
            ConfigKeyEnum.WORKSTATION_KNOWLEDGE_SPACE,
            payload=json.dumps(data.model_dump(mode='json'), ensure_ascii=True),
        )
        return data

    @classmethod
    async def get_knowledge_space_config_with_meta(
        cls,
    ) -> tuple[Optional[KnowledgeSpaceConfig], bool, int, bool]:
        value, inherited, source_tenant_id, has_override = await cls._aresolve_tenant_config(
            ConfigKeyEnum.WORKSTATION_KNOWLEDGE_SPACE
        )
        if not value:
            return None, inherited, source_tenant_id, has_override
        ret = KnowledgeSpaceConfig(**json.loads(value))
        if inherited:
            ret = await cls._aproject_knowledge_space_config_for_current_tenant(ret)
        return ret, inherited, source_tenant_id, has_override

    @classmethod
    async def acopy_root_builtin_tools_to_tenant(cls, tenant_id: int) -> dict:
        result = {
            'tenant_id': tenant_id,
            'created_types': 0,
            'created_tools': 0,
            'skipped_tools': 0,
        }
        if tenant_id == DEFAULT_TENANT_ID:
            return result
        async with get_async_db_session() as session:
            with bypass_tenant_filter():
                root_types = (await session.exec(
                    select(GptsToolsType).where(
                        GptsToolsType.tenant_id == DEFAULT_TENANT_ID,
                        GptsToolsType.is_preset == ToolPresetType.PRESET.value,
                        GptsToolsType.is_delete == 0,
                    ).order_by(GptsToolsType.id.asc())
                )).all()
                if not root_types:
                    return result
                root_tools = (await session.exec(
                    select(GptsTools).where(
                        col(GptsTools.type).in_([row.id for row in root_types]),
                        GptsTools.is_delete == 0,
                    ).order_by(GptsTools.id.asc())
                )).all()
                child_types = (await session.exec(
                    select(GptsToolsType).where(
                        GptsToolsType.tenant_id == tenant_id,
                        GptsToolsType.is_preset == ToolPresetType.PRESET.value,
                        GptsToolsType.is_delete == 0,
                    )
                )).all()
                child_tools = (await session.exec(
                    select(GptsTools).where(
                        GptsTools.tenant_id == tenant_id,
                        GptsTools.is_delete == 0,
                    )
                )).all()
            child_type_by_name = {row.name: row for row in child_types}
            child_tool_by_key = {row.tool_key: row for row in child_tools}
            type_map: dict[int, GptsToolsType] = {}
            for root_type in root_types:
                child_type = child_type_by_name.get(root_type.name)
                if child_type is None:
                    child_type = GptsToolsType(
                        name=root_type.name,
                        logo=root_type.logo,
                        extra=root_type.extra,
                        description=root_type.description,
                        server_host=root_type.server_host,
                        auth_method=root_type.auth_method,
                        api_key=root_type.api_key,
                        auth_type=root_type.auth_type,
                        is_preset=root_type.is_preset,
                        user_id=root_type.user_id,
                        tenant_id=tenant_id,
                        openapi_schema=root_type.openapi_schema,
                        is_shared=root_type.is_shared,
                    )
                    session.add(child_type)
                    await session.flush()
                    result['created_types'] += 1
                    child_type_by_name[child_type.name] = child_type
                type_map[root_type.id] = child_type
            for root_tool in root_tools:
                if root_tool.tool_key in child_tool_by_key:
                    result['skipped_tools'] += 1
                    continue
                child_type = type_map.get(root_tool.type)
                if child_type is None:
                    result['skipped_tools'] += 1
                    continue
                new_tool = GptsTools(
                    name=root_tool.name,
                    logo=root_tool.logo,
                    desc=root_tool.desc,
                    tool_key=root_tool.tool_key,
                    type=child_type.id,
                    is_preset=root_tool.is_preset,
                    is_delete=root_tool.is_delete,
                    api_params=root_tool.api_params,
                    user_id=root_tool.user_id,
                    tenant_id=tenant_id,
                    extra=root_tool.extra,
                )
                session.add(new_tool)
                result['created_tools'] += 1
            await session.commit()
        return result

    @classmethod
    async def uploadPersonalKnowledge(
        cls,
        request: Request,
        login_user: UserPayload,
        file_path,
        background_tasks: BackgroundTasks,
        *,
        upload_limit_bytes: Optional[int] = None,
    ):
        knowledge = await KnowledgeDao.aget_user_knowledge(
            login_user.user_id,
            None,
            KnowledgeTypeEnum.PRIVATE,
        )
        if not knowledge:
            model = await LLMService.aget_knowledge_llm()
            knowledge_create = KnowledgeCreate(
                name='Personal Knowledge Base',
                type=KnowledgeTypeEnum.PRIVATE.value,
                user_id=login_user.user_id,
                model=model.embedding_model_id,
            )
            knowledge = await KnowledgeService.acreate_knowledge(request, login_user, knowledge_create)
        else:
            knowledge = knowledge[0]
        req_data = KnowledgeFileProcess(
            knowledge_id=knowledge.id,
            file_list=[KnowledgeFileOne(file_path=file_path)],
        )
        try:
            _ = await LLMService.get_bisheng_knowledge_embedding(
                login_user.user_id, int(knowledge.model)
            )
        except Exception as exc:
            raise EmbeddingModelStatusError(exception=exc)
        return await KnowledgeService.aprocess_knowledge_file(
            request, login_user, background_tasks, req_data,
            upload_limit_bytes=upload_limit_bytes,
        )

    @classmethod
    async def queryKnowledgeList(
        cls,
        request: Request,
        login_user: UserPayload,
        page: int,
        size: int,
    ):
        knowledge = KnowledgeDao.get_user_knowledge(
            login_user.user_id,
            None,
            KnowledgeTypeEnum.PRIVATE,
        )
        if not knowledge:
            return [], 0
        res, total, _ = await KnowledgeService.aget_knowledge_files(
            request,
            login_user,
            knowledge[0].id,
            page=page,
            page_size=size,
        )
        return res, total

    @classmethod
    async def queryChunksFromDB(
        cls,
        question: str,
        use_knowledge_param: UseKnowledgeBaseParam,
        max_token: int,
        login_user: UserPayload,
    ) -> tuple[list[str], Optional[list[dict]], list[dict]]:
        """Query relevant knowledge blocks from the database.

        Returns (formatted_results, finally_docs, failures) where `failures`
        is a list of per-KB error descriptors:
            {'id': int, 'name': str, 'error': str}
        Caller (search_knowledge_bases) surfaces these to the UI as failed
        KB chips with the error message.
        """
        failures: list[dict] = []
        try:
            knowledge_ids = []
            if use_knowledge_param.organization_knowledge_ids:
                knowledge_ids.extend(use_knowledge_param.organization_knowledge_ids)

            knowledge_vector_list = await KnowledgeRag.get_multi_knowledge_vectorstore(
                invoke_user_id=login_user.user_id,
                knowledge_ids=knowledge_ids,
                user_name=login_user.user_name,
            )
            knowledge_space_list = await KnowledgeRag.get_multi_knowledge_vectorstore(
                invoke_user_id=login_user.user_id,
                knowledge_ids=use_knowledge_param.knowledge_space_ids,
                check_auth=False,
            )
            knowledge_vector_list.update(knowledge_space_list)

            # Per-KB failure isolation — a single KB whose embedding model is
            # broken (e.g. expired Volcengine key → 403) must not poison the
            # whole batch. Run each KB's retriever independently; record
            # failures so the caller can render them in the UI as failed KB
            # chips instead of silently dropping them.
            finally_docs: list = []
            kb_succeed: list = []
            max_total_docs = 100  # parity with old MultiRetriever finally_k

            for kb_id, vectorstore_info in knowledge_vector_list.items():
                if len(finally_docs) >= max_total_docs:
                    break
                milvus_vectorstore = vectorstore_info.get('milvus')
                es_vectorstore = vectorstore_info.get('es')
                kb_row = vectorstore_info.get('knowledge')
                kb_name = getattr(kb_row, 'name', '') or ''
                if milvus_vectorstore is None and es_vectorstore is None:
                    logger.info(
                        f'[queryChunksFromDB] kb={kb_id} no vectorstore, skip'
                    )
                    failures.append({
                        'id': int(kb_id) if isinstance(kb_id, (int, str)) and str(kb_id).isdigit() else kb_id,
                        'name': kb_name,
                        'error': '知识库未初始化向量存储',
                    })
                    continue

                try:
                    per_kb_milvus = (
                        MultiRetriever(
                            vectors=[milvus_vectorstore],
                            search_kwargs=[{'k': 100, 'param': {'ef': 110}}],
                            finally_k=100,
                        )
                        if milvus_vectorstore is not None else None
                    )
                    per_kb_es = (
                        MultiRetriever(
                            vectors=[es_vectorstore],
                            search_kwargs=[{'k': 100}],
                            finally_k=100,
                        )
                        if es_vectorstore is not None else None
                    )
                    per_kb_tool = KnowledgeRetrieverTool(
                        vector_retriever=per_kb_milvus,
                        elastic_retriever=per_kb_es,
                        max_content=max_token,
                        rrf_remove_zero_score=True,
                        sort_by_source_and_index=True,
                    )
                    kb_docs = await per_kb_tool.ainvoke({'query': question})
                    docs_count = len(kb_docs) if kb_docs else 0
                    if kb_docs:
                        finally_docs.extend(kb_docs)
                    kb_succeed.append(kb_id)
                    logger.info(
                        f'[queryChunksFromDB] kb={kb_id} ok docs={docs_count}'
                    )
                except Exception as exc:
                    err_msg = str(exc) or exc.__class__.__name__
                    failures.append({
                        'id': int(kb_id) if isinstance(kb_id, (int, str)) and str(kb_id).isdigit() else kb_id,
                        'name': kb_name,
                        'error': err_msg,
                    })
                    logger.warning(
                        f'[queryChunksFromDB] kb={kb_id} failed: {err_msg}'
                    )
                    continue

            if failures:
                logger.warning(
                    f'[queryChunksFromDB] partial failure:'
                    f' succeed={kb_succeed}'
                    f' failed={[f["id"] for f in failures]}'
                )

            if not finally_docs:
                return [], [], failures

            # Cap to match old MultiRetriever finally_k=100 ceiling.
            if len(finally_docs) > max_total_docs:
                finally_docs = finally_docs[:max_total_docs]

            formatted_results = []
            for doc in finally_docs:
                file_name = doc.metadata.get('source') or doc.metadata.get('document_name')
                content = doc.page_content.strip()
                formatted_results.append(
                    f'[file name]:{file_name}\n[file content begin]\n{content}\n[file content end]\n'
                )
            return formatted_results, finally_docs, failures
        except Exception as exc:
            logger.exception(f'queryChunksFromDB error: {exc}')
            return [], None, failures

    @classmethod
    async def get_chat_history(cls, chat_id: str, size: int = 4,
                               max_tokens: Optional[int] = None):
        """Build LLM-consumable chat history, backward compatible with both
        legacy plain-text messages and v2.5 JSON-formatted messages.

        Two-stage trimming:
          1. DB returns the MOST RECENT ``size`` rows in chronological order
             (see aget_messages_by_chat_id — fixed to DESC LIMIT + reverse).
          2. If the combined token count exceeds ``max_tokens``, drop oldest
             entries one at a time until the remainder fits. Token counting
             uses tiktoken (cl100k_base) with a char-based fallback — see
             chat_service._count_tokens. We always drop from the FRONT
             (oldest) of the list so the latest user/AI turn is preserved.

        ``max_tokens`` is resolved by the caller (typically from
        ``daily_chat.history_max_tokens`` in the DB config). If ``None`` the
        token-cap stage is skipped — keep this for callers that only want
        row-count trimming or that manage budgeting themselves.
        """
        import re as _re

        chat_history = []
        categories = [
            MessageCategory.QUESTION.value,
            MessageCategory.ANSWER.value,
            MessageCategory.AGENT_ANSWER.value,
        ]
        messages = await ChatMessageDao.aget_messages_by_chat_id(chat_id, categories, size)

        for one in messages:
            raw = one.message or ''
            if one.category == MessageCategory.QUESTION.value:
                # Try new JSON format: {"query": "..."}
                try:
                    parsed = json.loads(raw)
                    content = parsed.get('query', raw) if isinstance(parsed, dict) else raw
                except (json.JSONDecodeError, TypeError):
                    content = raw
                # Legacy rows may carry a rewritten prompt in `extra.prompt`.
                try:
                    extra = json.loads(one.extra) if one.extra else {}
                    if isinstance(extra, dict) and extra.get('prompt'):
                        content = extra['prompt']
                except (json.JSONDecodeError, TypeError):
                    pass
                chat_history.append(HumanMessage(content=content))

            elif one.category == MessageCategory.AGENT_ANSWER.value:
                # New JSON format: {"msg":"...", ...}
                try:
                    parsed = json.loads(raw)
                    content = parsed.get('msg', '') if isinstance(parsed, dict) else raw
                except (json.JSONDecodeError, TypeError):
                    content = raw
                chat_history.append(AIMessage(content=content))

            elif one.category == MessageCategory.ANSWER.value:
                # Legacy plain-text: strip :::thinking / :::web markup so the
                # model sees only the visible answer.
                content = _re.sub(r':::thinking\n[\s\S]*?\n:::', '', raw)
                content = _re.sub(r':::web\n[\s\S]*?\n:::', '', content).strip()
                chat_history.append(AIMessage(content=content))

        # Token-count cap: drop oldest until total tokens ≤ max_tokens.
        # Keep at least one message (the most recent) so the model still
        # sees some context; if that single message alone exceeds the cap,
        # leave it untouched — the LLM layer will raise, which is more
        # actionable than silently chopping the latest turn.
        if max_tokens is not None and max_tokens > 0 and chat_history:
            from .chat_service import _count_tokens  # local import avoids cycle

            def _msg_tokens(m) -> int:
                c = getattr(m, 'content', '')
                if isinstance(c, str):
                    return _count_tokens(c)
                try:
                    return _count_tokens(str(c))
                except Exception:
                    return 0

            per_msg = [_msg_tokens(m) for m in chat_history]
            total = sum(per_msg)
            dropped = 0
            while total > max_tokens and len(chat_history) > 1:
                chat_history.pop(0)
                total -= per_msg.pop(0)
                dropped += 1
            if dropped:
                logger.info(
                    f'history token-cap trimmed {dropped} oldest messages '
                    f'(final_tokens={total} cap={max_tokens})'
                )

        logger.info(f'loaded {len(chat_history)} chat history for chat_id {chat_id}')
        return chat_history
