import asyncio
import json
import os
import time
from typing import Any, Optional

from fastapi import BackgroundTasks, Request
from langchain_core.documents import Document
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
from bisheng.database.constants import MessageCategory
from bisheng.database.models.flow import Flow
from bisheng.database.models.message import ChatMessageDao
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.models.knowledge import KnowledgeCreate, KnowledgeDao, KnowledgeTypeEnum
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.llm.domain.schemas import WorkbenchModelConfig
from bisheng.llm.domain.services import LLMService
from bisheng.tool.domain.const import ToolPresetType
from bisheng.tool.domain.models.gpts_tools import GptsTools, GptsToolsDao, GptsToolsType
from ..models import TenantWorkstationConfigDao


class WorkStationService(BaseService):
    # Selected knowledge spaces are stored in independent Milvus collections
    # and ES indexes. Keep the fan-out bounded and use a two-stage search:
    # a cheap vector-only probe across every space, followed by hybrid retrieval
    # from only the most promising spaces.
    _KB_PROBE_K = 2
    _KB_PROBE_CONCURRENCY = 20
    _KB_PROBE_TIMEOUT_SECONDS = 10.0
    _KB_SELECTED_SPACE_LIMIT = 20
    _KB_DEEP_CONCURRENCY = 16
    _KB_DEEP_TIMEOUT_SECONDS = 5.0
    _KB_DEEP_TOP_SPACE_K = 20
    _KB_DEEP_OTHER_SPACE_K = 10
    _KB_CANDIDATE_LIMIT = 300
    _KB_RERANK_LIMIT = 200
    _KB_RERANK_BATCH_SIZE = 32
    _KB_RERANK_CONCURRENCY = 2
    _KB_RERANK_TIMEOUT_SECONDS = 3.0
    _KB_RRF_C = 60

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
    def query_knowledge_space_config_with_meta(
        cls,
    ) -> tuple[Optional[KnowledgeSpaceConfig], bool, int, bool]:
        value, inherited, source_tenant_id, has_override = cls._resolve_tenant_config(
            ConfigKeyEnum.WORKSTATION_KNOWLEDGE_SPACE
        )
        if not value:
            return None, inherited, source_tenant_id, has_override
        ret = KnowledgeSpaceConfig(**json.loads(value))
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
    async def _load_retrieval_knowledge_rows(
        cls,
        *,
        organization_ids: list[int],
        space_ids: list[int],
        login_user: UserPayload,
    ) -> list[Any]:
        """Load authorized KB rows without eagerly creating every vector store."""

        async def _load_organization_rows() -> list[Any]:
            if not organization_ids:
                return []
            return await KnowledgeDao.ajudge_knowledge_permission(
                login_user.user_name,
                organization_ids,
            )

        async def _load_space_rows() -> list[Any]:
            if not space_ids:
                return []
            # Space permissions are resolved by the caller before this path,
            # matching the previous check_auth=False behavior.
            return await KnowledgeDao.aget_list_by_ids(space_ids)

        organization_rows, space_rows = await asyncio.gather(
            _load_organization_rows(),
            _load_space_rows(),
        )
        row_by_id = {
            int(row.id): row
            for row in [*organization_rows, *space_rows]
            if getattr(row, 'id', None) is not None
        }
        ordered_ids = list(dict.fromkeys([*organization_ids, *space_ids]))
        return [row_by_id[kb_id] for kb_id in ordered_ids if kb_id in row_by_id]

    @classmethod
    def _knowledge_failure(cls, knowledge: Any, error: str) -> dict:
        kb_id = getattr(knowledge, 'id', None)
        return {
            'id': int(kb_id) if isinstance(kb_id, (int, str)) and str(kb_id).isdigit() else kb_id,
            'name': getattr(knowledge, 'name', '') or '',
            'error': str(error or '知识库检索失败'),
        }

    @classmethod
    def _annotate_scored_documents(
        cls,
        *,
        kb_id: int,
        docs_with_scores: list[tuple[Document, float]],
        source: str,
        allowed_file_ids: Optional[list[int]],
        probe_score: Optional[float] = None,
    ) -> list[Document]:
        allowed_set = set(allowed_file_ids) if allowed_file_ids is not None else None
        docs: list[Document] = []
        for doc, raw_score in docs_with_scores or []:
            if allowed_set is not None and not cls._doc_matches_file_filter(doc, kb_id, allowed_set):
                continue
            metadata = doc.metadata or {}
            doc.metadata = metadata
            # The selected row is authoritative. Older chunks may contain a
            # missing or stale knowledge_id after a collection migration.
            metadata['knowledge_id'] = kb_id
            metadata['retrieval_source'] = source
            try:
                metadata['retrieval_score'] = float(raw_score)
            except (TypeError, ValueError):
                metadata['retrieval_score'] = 0.0
            if probe_score is not None:
                metadata['knowledge_probe_score'] = float(probe_score)
            docs.append(doc)
        return docs

    @classmethod
    async def _probe_retrieval_knowledge_rows(
        cls,
        *,
        question: str,
        knowledge_rows: list[Any],
        login_user: UserPayload,
        file_ids_by_space: Optional[dict[int, list[int]]],
    ) -> tuple[list[dict], list[dict]]:
        """Probe every KB with vector top-k while reusing one query embedding per model."""
        semaphore = asyncio.Semaphore(cls._KB_PROBE_CONCURRENCY)
        embedding_futures: dict[int, asyncio.Task] = {}
        eligible_rows = [
            knowledge
            for knowledge in knowledge_rows
            if cls._get_allowed_file_ids_for_space(file_ids_by_space, int(knowledge.id)) != []
        ]
        eligible_ids = {int(knowledge.id) for knowledge in eligible_rows}
        for knowledge in knowledge_rows:
            if int(knowledge.id) not in eligible_ids:
                logger.info(
                    f'[queryChunksFromDB] kb={getattr(knowledge, "id", "")} '
                    'empty file filter, skip'
                )
        if not eligible_rows:
            return [], []

        async def _embedding_and_query_vector(model_id: int):
            embeddings = await LLMService.get_bisheng_knowledge_embedding(
                invoke_user_id=login_user.user_id,
                model_id=model_id,
            )
            query_vector = await embeddings.aembed_query(question)
            return embeddings, query_vector

        for knowledge in eligible_rows:
            try:
                model_id = int(getattr(knowledge, 'model', '') or 0)
            except (TypeError, ValueError):
                model_id = 0
            if model_id > 0 and model_id not in embedding_futures:
                embedding_futures[model_id] = asyncio.create_task(
                    _embedding_and_query_vector(model_id)
                )

        async def _probe_one(knowledge: Any) -> dict:
            kb_id = int(knowledge.id)
            allowed_file_ids = cls._get_allowed_file_ids_for_space(file_ids_by_space, kb_id)
            if allowed_file_ids == []:
                return {'status': 'skipped', 'knowledge': knowledge}

            milvus_error = ''
            milvus = None
            query_vector = None
            try:
                model_id = int(getattr(knowledge, 'model', '') or 0)
                collection_name = str(getattr(knowledge, 'collection_name', '') or '')
                if model_id <= 0 or not collection_name:
                    raise RuntimeError('知识库未配置向量模型或向量集合')
                embeddings, query_vector = await embedding_futures[model_id]
                async with semaphore:
                    milvus = await asyncio.to_thread(
                        KnowledgeRag.init_milvus_vectorstore,
                        collection_name,
                        embeddings,
                    )
                    search_kwargs: dict[str, Any] = {
                        'k': cls._KB_PROBE_K,
                        'param': {'ef': 110},
                        'timeout': cls._KB_PROBE_TIMEOUT_SECONDS,
                    }
                    if allowed_file_ids is not None:
                        search_kwargs['expr'] = f'document_id in {allowed_file_ids}'
                    scored_docs = await milvus.asimilarity_search_with_relevance_scores_by_vector(
                        query_vector,
                        **search_kwargs,
                    )
                docs = cls._annotate_scored_documents(
                    kb_id=kb_id,
                    docs_with_scores=scored_docs,
                    source='milvus',
                    allowed_file_ids=allowed_file_ids,
                )
                return {
                    'status': 'ok',
                    'knowledge': knowledge,
                    'milvus': milvus,
                    'es': None,
                    'query_vector': query_vector,
                    'probe_docs': docs,
                    'probe_score': max(
                        (float(doc.metadata.get('retrieval_score', 0.0)) for doc in docs),
                        default=-1.0,
                    ),
                }
            except Exception as exc:
                milvus_error = str(exc) or exc.__class__.__name__

            # An ES-only probe preserves availability for KBs whose embedding
            # model or Milvus collection is temporarily unavailable.
            try:
                index_name = str(getattr(knowledge, 'index_name', '') or '')
                if not index_name:
                    raise RuntimeError('知识库未配置全文索引')
                async with semaphore:
                    es = KnowledgeRag.init_es_vectorstore(index_name)
                    search_kwargs = {'k': cls._KB_PROBE_K}
                    if allowed_file_ids is not None:
                        search_kwargs['filter'] = [
                            {'terms': {'metadata.document_id': allowed_file_ids}}
                        ]
                    scored_docs = await es.asimilarity_search_with_relevance_scores(
                        question,
                        **search_kwargs,
                    )
                docs = cls._annotate_scored_documents(
                    kb_id=kb_id,
                    docs_with_scores=scored_docs,
                    source='elasticsearch',
                    allowed_file_ids=allowed_file_ids,
                )
                logger.warning(
                    f'[queryChunksFromDB] kb={kb_id} vector probe failed, used ES: {milvus_error}'
                )
                return {
                    'status': 'ok',
                    'knowledge': knowledge,
                    'milvus': milvus,
                    'es': es,
                    'query_vector': query_vector,
                    'probe_docs': docs,
                    'probe_score': max(
                        (float(doc.metadata.get('retrieval_score', 0.0)) for doc in docs),
                        default=-1.0,
                    ),
                }
            except Exception as exc:
                es_error = str(exc) or exc.__class__.__name__
                return {
                    'status': 'failed',
                    'knowledge': knowledge,
                    'error': f'Milvus: {milvus_error}; Elasticsearch: {es_error}',
                }

        task_by_id: dict[int, asyncio.Task] = {}
        for knowledge in eligible_rows:
            kb_id = int(knowledge.id)
            task_by_id[kb_id] = asyncio.create_task(_probe_one(knowledge))

        done, pending = await asyncio.wait(
            task_by_id.values(),
            timeout=cls._KB_PROBE_TIMEOUT_SECONDS,
        )
        pending_set = set(pending)
        for task in pending:
            task.cancel()

        infos: list[dict] = []
        failures: list[dict] = []
        task_id_by_object = {task: kb_id for kb_id, task in task_by_id.items()}
        row_by_id = {int(row.id): row for row in knowledge_rows}
        for task in sorted(done, key=lambda item: task_id_by_object[item]):
            try:
                result = task.result()
            except Exception as exc:
                kb_id = task_id_by_object[task]
                failures.append(cls._knowledge_failure(row_by_id[kb_id], str(exc)))
                continue
            if result.get('status') == 'ok':
                infos.append(result)
            elif result.get('status') == 'failed':
                failures.append(
                    cls._knowledge_failure(result['knowledge'], result.get('error', ''))
                )

        for task in sorted(pending_set, key=lambda item: task_id_by_object[item]):
            kb_id = task_id_by_object[task]
            failures.append(cls._knowledge_failure(row_by_id[kb_id], '知识库轻量探测超时'))
        if pending_set:
            await asyncio.gather(*pending_set, return_exceptions=True)

        for future in embedding_futures.values():
            if not future.done():
                future.cancel()
        if embedding_futures:
            await asyncio.gather(*embedding_futures.values(), return_exceptions=True)
        return infos, failures

    @classmethod
    async def _deep_retrieve_selected_knowledge(
        cls,
        *,
        question: str,
        selected_infos: list[dict],
        file_ids_by_space: Optional[dict[int, list[int]]],
    ) -> tuple[list[tuple[list[Document], float]], list[dict]]:
        semaphore = asyncio.Semaphore(cls._KB_DEEP_CONCURRENCY)

        async def _deep_one(info: dict, space_rank: int) -> dict:
            knowledge = info['knowledge']
            kb_id = int(knowledge.id)
            allowed_file_ids = cls._get_allowed_file_ids_for_space(file_ids_by_space, kb_id)
            deep_k = (
                cls._KB_DEEP_TOP_SPACE_K
                if space_rank < 5
                else cls._KB_DEEP_OTHER_SPACE_K
            )

            async def _search_milvus():
                milvus = info.get('milvus')
                query_vector = info.get('query_vector')
                if milvus is None or query_vector is None:
                    return []
                kwargs: dict[str, Any] = {
                    'k': deep_k,
                    'param': {'ef': 110},
                    'timeout': cls._KB_DEEP_TIMEOUT_SECONDS,
                }
                if allowed_file_ids is not None:
                    kwargs['expr'] = f'document_id in {allowed_file_ids}'
                scored = await milvus.asimilarity_search_with_relevance_scores_by_vector(
                    query_vector,
                    **kwargs,
                )
                return cls._annotate_scored_documents(
                    kb_id=kb_id,
                    docs_with_scores=scored,
                    source='milvus',
                    allowed_file_ids=allowed_file_ids,
                    probe_score=info.get('probe_score'),
                )

            async def _search_es():
                es = info.get('es')
                if es is None:
                    index_name = str(getattr(knowledge, 'index_name', '') or '')
                    if not index_name:
                        return []
                    es = KnowledgeRag.init_es_vectorstore(index_name)
                    info['es'] = es
                kwargs: dict[str, Any] = {'k': deep_k}
                if allowed_file_ids is not None:
                    kwargs['filter'] = [
                        {'terms': {'metadata.document_id': allowed_file_ids}}
                    ]
                scored = await es.asimilarity_search_with_relevance_scores(question, **kwargs)
                return cls._annotate_scored_documents(
                    kb_id=kb_id,
                    docs_with_scores=scored,
                    source='elasticsearch',
                    allowed_file_ids=allowed_file_ids,
                    probe_score=info.get('probe_score'),
                )

            async with semaphore:
                vector_result, es_result = await asyncio.gather(
                    _search_milvus(),
                    _search_es(),
                    return_exceptions=True,
                )

            errors = []
            if isinstance(vector_result, Exception):
                errors.append(f'Milvus: {str(vector_result) or vector_result.__class__.__name__}')
                vector_docs = list(info.get('probe_docs') or [])
            else:
                vector_docs = list(vector_result or info.get('probe_docs') or [])
            if isinstance(es_result, Exception):
                errors.append(f'Elasticsearch: {str(es_result) or es_result.__class__.__name__}')
                es_docs = []
            else:
                es_docs = list(es_result or [])

            return {
                'knowledge': knowledge,
                'space_rank': space_rank,
                'vector_docs': vector_docs,
                'es_docs': es_docs,
                'error': '; '.join(errors) if errors and not vector_docs and not es_docs else '',
            }

        task_by_rank = {
            rank: asyncio.create_task(_deep_one(info, rank))
            for rank, info in enumerate(selected_infos)
        }
        if not task_by_rank:
            return [], []

        done, pending = await asyncio.wait(
            task_by_rank.values(),
            timeout=cls._KB_DEEP_TIMEOUT_SECONDS,
        )
        pending_set = set(pending)
        for task in pending:
            task.cancel()

        rank_by_task = {task: rank for rank, task in task_by_rank.items()}
        rank_lists: list[tuple[list[Document], float]] = []
        failures: list[dict] = []
        selected_count = max(len(selected_infos), 1)
        for task in sorted(done, key=lambda item: rank_by_task[item]):
            rank = rank_by_task[task]
            info = selected_infos[rank]
            try:
                result = task.result()
            except Exception as exc:
                failures.append(cls._knowledge_failure(info['knowledge'], str(exc)))
                result = {
                    'vector_docs': list(info.get('probe_docs') or []),
                    'es_docs': [],
                    'error': '',
                }
            # Probe rank affects only the coarse fusion weight; RRF still
            # decides chunk order from the independent vector and ES lists.
            space_weight = 1.0 + 0.5 * (selected_count - rank) / selected_count
            if result.get('vector_docs'):
                rank_lists.append((list(result['vector_docs']), space_weight))
            if result.get('es_docs'):
                rank_lists.append((list(result['es_docs']), space_weight))
            if result.get('error'):
                failures.append(
                    cls._knowledge_failure(info['knowledge'], result['error'])
                )

        for task in sorted(pending_set, key=lambda item: rank_by_task[item]):
            rank = rank_by_task[task]
            info = selected_infos[rank]
            probe_docs = list(info.get('probe_docs') or [])
            if probe_docs:
                space_weight = 1.0 + 0.5 * (selected_count - rank) / selected_count
                rank_lists.append((probe_docs, space_weight))
            logger.warning(
                f'[queryChunksFromDB] kb={getattr(info["knowledge"], "id", "")} '
                'deep retrieval timed out, using probe documents'
            )
        if pending_set:
            await asyncio.gather(*pending_set, return_exceptions=True)
        return rank_lists, failures

    @classmethod
    def _retrieval_document_key(cls, doc: Document) -> tuple:
        metadata = doc.metadata or {}
        knowledge_id = metadata.get('knowledge_id') or metadata.get('kb_id') or ''
        document_id = metadata.get('document_id') or metadata.get('file_id') or ''
        chunk_index = metadata.get('chunk_index')
        if knowledge_id != '' and document_id != '' and chunk_index is not None:
            return 'chunk', str(knowledge_id), str(document_id), str(chunk_index)
        if knowledge_id != '' and document_id != '':
            return 'document-content', str(knowledge_id), str(document_id), doc.page_content
        source = metadata.get('source') or metadata.get('document_name') or metadata.get('file_name') or ''
        return 'content', str(knowledge_id), str(source), doc.page_content

    @classmethod
    def _global_rrf_merge(
        cls,
        rank_lists: list[tuple[list[Document], float]],
        *,
        limit: int,
    ) -> list[Document]:
        scores: dict[tuple, float] = {}
        first_seen: dict[tuple, int] = {}
        document_by_key: dict[tuple, Document] = {}
        seen_index = 0
        for docs, weight in rank_lists:
            seen_in_list: set[tuple] = set()
            for rank, doc in enumerate(docs, start=1):
                key = cls._retrieval_document_key(doc)
                if key in seen_in_list:
                    continue
                seen_in_list.add(key)
                if key not in document_by_key:
                    document_by_key[key] = doc
                    first_seen[key] = seen_index
                    seen_index += 1
                scores[key] = scores.get(key, 0.0) + float(weight) / (rank + cls._KB_RRF_C)

        ordered_keys = sorted(
            scores,
            key=lambda key: (
                scores[key],
                float((document_by_key[key].metadata or {}).get('knowledge_probe_score', -1.0)),
                float((document_by_key[key].metadata or {}).get('retrieval_score', -1.0)),
                -first_seen[key],
            ),
            reverse=True,
        )
        if limit > 0:
            ordered_keys = ordered_keys[:limit]
        documents = []
        for key in ordered_keys:
            doc = document_by_key[key]
            doc.metadata = doc.metadata or {}
            doc.metadata['rrf_score'] = scores[key]
            documents.append(doc)
        return documents

    @classmethod
    async def _resolve_workstation_rerank_model_id(cls) -> str:
        try:
            from bisheng.shougang_portal_config.domain.services.portal_config_service import (
                ShougangPortalConfigService,
            )

            config = await ShougangPortalConfigService.get_config()
            model_id = str(
                getattr(getattr(getattr(config, 'portal', None), 'search', None), 'rerank_model_id', '')
                or ''
            ).strip()
            if model_id:
                return model_id
        except Exception as exc:
            logger.warning(f'[queryChunksFromDB] unable to read rerank config: {exc}')
        return os.getenv('BISHENG_PORTAL_SEARCH_RERANK_MODEL_ID', '').strip()

    @classmethod
    async def _rerank_retrieval_candidates(
        cls,
        *,
        question: str,
        candidates: list[Document],
    ) -> list[Document]:
        if not candidates:
            return []

        async def _run() -> list[Document]:
            model_id = await cls._resolve_workstation_rerank_model_id()
            if not model_id:
                logger.info('[queryChunksFromDB] no rerank model configured, using global RRF')
                return candidates
            rerank_model = await LLMService.get_bisheng_rerank(model_id=int(model_id))
            rerank_head = candidates[:cls._KB_RERANK_LIMIT]
            batches = [
                rerank_head[index:index + cls._KB_RERANK_BATCH_SIZE]
                for index in range(0, len(rerank_head), cls._KB_RERANK_BATCH_SIZE)
            ]
            semaphore = asyncio.Semaphore(cls._KB_RERANK_CONCURRENCY)

            async def _rerank_batch(batch: list[Document]) -> list[Document]:
                async with semaphore:
                    return list(
                        await rerank_model.acompress_documents(
                            documents=batch,
                            query=question,
                        )
                    )

            reranked_batches = await asyncio.gather(
                *[_rerank_batch(batch) for batch in batches]
            )
            scored_docs: list[Document] = []
            for batch in reranked_batches:
                for doc in batch:
                    try:
                        float((doc.metadata or {}).get('relevance_score'))
                    except (TypeError, ValueError):
                        continue
                    scored_docs.append(doc)
            if not scored_docs:
                raise RuntimeError('rerank model returned no relevance scores')
            scored_docs.sort(
                key=lambda doc: float((doc.metadata or {}).get('relevance_score')),
                reverse=True,
            )
            scored_keys = {cls._retrieval_document_key(doc) for doc in scored_docs}
            missing_head = [
                doc for doc in rerank_head
                if cls._retrieval_document_key(doc) not in scored_keys
            ]
            logger.info(
                f'[queryChunksFromDB] semantic rerank model={model_id}'
                f' candidates={len(rerank_head)} batches={len(batches)}'
            )
            return [*scored_docs, *missing_head, *candidates[len(rerank_head):]]

        try:
            return await asyncio.wait_for(
                _run(),
                timeout=cls._KB_RERANK_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            logger.warning(
                f'[queryChunksFromDB] rerank unavailable, falling back to global RRF: {exc}'
            )
            return candidates

    @classmethod
    def _format_retrieval_document(cls, doc: Document) -> str:
        metadata = doc.metadata or {}
        file_name = (
            metadata.get('source')
            or metadata.get('document_name')
            or metadata.get('file_name')
            or ''
        )
        content = (doc.page_content or '').strip()
        return (
            f'[file name]:{file_name}\n'
            f'[file content begin]\n{content}\n[file content end]\n'
        )

    @classmethod
    def _truncate_ranked_documents_by_chars(
        cls,
        documents: list[Document],
        max_chars: int,
    ) -> tuple[list[str], list[Document]]:
        try:
            content_limit = max(int(max_chars), 0)
        except (TypeError, ValueError):
            content_limit = 0
        if content_limit <= 0:
            return [], []

        formatted_results: list[str] = []
        selected_docs: list[Document] = []
        used_chars = 0
        for doc in documents:
            if not (doc.page_content or '').strip():
                continue
            formatted = cls._format_retrieval_document(doc)
            separator_chars = 1 if formatted_results else 0
            if used_chars + separator_chars + len(formatted) <= content_limit:
                formatted_results.append(formatted)
                selected_docs.append(doc)
                used_chars += separator_chars + len(formatted)
                continue

            # Keep chunk boundaries intact. Only a single oversized top chunk
            # is shortened so a valid retrieval result can still be returned.
            if formatted_results:
                break
            metadata = doc.metadata or {}
            file_name = (
                metadata.get('source')
                or metadata.get('document_name')
                or metadata.get('file_name')
                or ''
            )
            prefix = f'[file name]:{file_name}\n[file content begin]\n'
            suffix = '\n[file content end]\n'
            available_content_chars = content_limit - len(prefix) - len(suffix)
            if available_content_chars <= 0:
                break
            page_content = (doc.page_content or '').strip()
            citation_key = metadata.get('citation_key')
            citation_suffix = f'\n\ncitation_key: {citation_key}' if citation_key else ''
            if citation_suffix and page_content.endswith(citation_suffix):
                content_without_citation = page_content[:-len(citation_suffix)].rstrip()
                available_body_chars = available_content_chars - len(citation_suffix)
                if available_body_chars >= 0:
                    page_content = (
                        content_without_citation[:available_body_chars].rstrip()
                        + citation_suffix
                    )
                else:
                    page_content = page_content[:available_content_chars]
            else:
                page_content = page_content[:available_content_chars]
            truncated_doc = Document(
                page_content=page_content,
                metadata={**metadata, 'content_truncated': True},
            )
            formatted_results.append(cls._format_retrieval_document(truncated_doc))
            selected_docs.append(truncated_doc)
            break
        return formatted_results, selected_docs

    @classmethod
    def _deduplicate_knowledge_failures(cls, failures: list[dict]) -> list[dict]:
        deduplicated: list[dict] = []
        seen: set[tuple] = set()
        for failure in failures:
            key = (failure.get('id'), failure.get('error'))
            if key in seen:
                continue
            seen.add(key)
            deduplicated.append(failure)
        return deduplicated

    @classmethod
    async def queryChunksFromDB(
        cls,
        question: str,
        use_knowledge_param: UseKnowledgeBaseParam,
        max_token: int,
        login_user: UserPayload,
        file_ids_by_space: Optional[dict[int, list[int]]] = None,
    ) -> tuple[list[str], Optional[list[Document]], list[dict]]:
        """Retrieve globally ranked chunks with bounded fan-out and graceful fallback."""
        failures: list[dict] = []
        started_at = time.monotonic()
        if not str(question or '').strip():
            return [], [], []
        try:
            organization_ids, space_ids = await cls._split_retrieval_knowledge_ids_by_type(
                organization_knowledge_ids=use_knowledge_param.organization_knowledge_ids or [],
                knowledge_space_ids=use_knowledge_param.knowledge_space_ids or [],
            )
            knowledge_rows = await cls._load_retrieval_knowledge_rows(
                organization_ids=organization_ids,
                space_ids=space_ids,
                login_user=login_user,
            )
            if not knowledge_rows:
                return [], [], []

            probe_started_at = time.monotonic()
            probe_infos, probe_failures = await cls._probe_retrieval_knowledge_rows(
                question=question,
                knowledge_rows=knowledge_rows,
                login_user=login_user,
                file_ids_by_space=file_ids_by_space,
            )
            failures.extend(probe_failures)
            selected_infos = sorted(
                (info for info in probe_infos if info.get('probe_docs')),
                key=lambda info: (
                    float(info.get('probe_score', -1.0)),
                    -int(getattr(info.get('knowledge'), 'id', 0) or 0),
                ),
                reverse=True,
            )[:cls._KB_SELECTED_SPACE_LIMIT]
            probe_ms = int((time.monotonic() - probe_started_at) * 1000)
            if not selected_infos:
                return [], [], cls._deduplicate_knowledge_failures(failures)

            deep_started_at = time.monotonic()
            rank_lists, deep_failures = await cls._deep_retrieve_selected_knowledge(
                question=question,
                selected_infos=selected_infos,
                file_ids_by_space=file_ids_by_space,
            )
            failures.extend(deep_failures)
            candidates = cls._global_rrf_merge(
                rank_lists,
                limit=cls._KB_CANDIDATE_LIMIT,
            )
            deep_ms = int((time.monotonic() - deep_started_at) * 1000)
            if not candidates:
                return [], [], cls._deduplicate_knowledge_failures(failures)

            rerank_started_at = time.monotonic()
            ranked_docs = await cls._rerank_retrieval_candidates(
                question=question,
                candidates=candidates,
            )
            rerank_ms = int((time.monotonic() - rerank_started_at) * 1000)
            formatted_results, finally_docs = cls._truncate_ranked_documents_by_chars(
                ranked_docs,
                max_token,
            )
            failures = cls._deduplicate_knowledge_failures(failures)
            total_ms = int((time.monotonic() - started_at) * 1000)
            selected_summary = [
                (
                    int(getattr(info.get('knowledge'), 'id', 0) or 0),
                    round(float(info.get('probe_score', -1.0)), 4),
                )
                for info in selected_infos
            ]
            logger.info(
                f'[queryChunksFromDB] two-stage retrieval requested={len(knowledge_rows)}'
                f' probed={len(probe_infos)} selected={len(selected_infos)}'
                f' selected_summary={selected_summary}'
                f' candidates={len(candidates)} final_docs={len(finally_docs)}'
                f' final_chars={len(chr(10).join(formatted_results))}'
                f' probe_ms={probe_ms} deep_ms={deep_ms}'
                f' rerank_ms={rerank_ms} total_ms={total_ms}'
                f' failures={len(failures)}'
            )
            return formatted_results, finally_docs, failures
        except Exception as exc:
            logger.exception(f'queryChunksFromDB error: {exc}')
            return [], None, cls._deduplicate_knowledge_failures(failures)

    @classmethod
    def _get_allowed_file_ids_for_space(
        cls,
        file_ids_by_space: Optional[dict[int, list[int]]],
        kb_id: Any,
    ) -> Optional[list[int]]:
        if file_ids_by_space is None:
            return None
        try:
            space_id = int(kb_id)
        except (TypeError, ValueError):
            return []
        try:
            raw_file_ids = file_ids_by_space[space_id]
        except KeyError:
            return []
        normalized: list[int] = []
        seen: set[int] = set()
        for raw_file_id in raw_file_ids or []:
            try:
                file_id = int(raw_file_id)
            except (TypeError, ValueError):
                continue
            if file_id <= 0 or file_id in seen:
                continue
            normalized.append(file_id)
            seen.add(file_id)
        return normalized

    @classmethod
    def _doc_matches_file_filter(cls, doc: Any, kb_id: int, allowed_file_ids: set[int]) -> bool:
        metadata = getattr(doc, 'metadata', {}) or {}
        raw_kb_id = metadata.get('knowledge_id') or metadata.get('kb_id')
        if raw_kb_id not in (None, ''):
            try:
                if int(raw_kb_id) != int(kb_id):
                    return False
            except (TypeError, ValueError):
                return False
        raw_file_id = metadata.get('document_id') or metadata.get('file_id')
        try:
            file_id = int(raw_file_id)
        except (TypeError, ValueError):
            return False
        return file_id in allowed_file_ids

    @classmethod
    async def _split_retrieval_knowledge_ids_by_type(
        cls,
        organization_knowledge_ids: list[int],
        knowledge_space_ids: list[int],
    ) -> tuple[list[int], list[int]]:
        """按数据库真实类型重新归类检索 ID。

        前端或旧本地缓存可能把知识空间 ID 放进 organization_knowledge_ids。
        后端必须以 knowledge.type 为准，避免公共知识空间误走普通知识库权限过滤，
        同时也避免普通知识库被传进 knowledge_space_ids 后绕过权限。
        """
        requested_ids: list[int] = []
        seen: set[int] = set()
        for raw_id in [*(organization_knowledge_ids or []), *(knowledge_space_ids or [])]:
            try:
                knowledge_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            if knowledge_id in seen:
                continue
            seen.add(knowledge_id)
            requested_ids.append(knowledge_id)

        if not requested_ids:
            return [], []

        knowledge_rows = await KnowledgeDao.aget_list_by_ids(requested_ids)
        knowledge_by_id = {int(row.id): row for row in knowledge_rows if row.id is not None}
        organization_ids: list[int] = []
        space_ids: list[int] = []
        missing_ids: list[int] = []
        for knowledge_id in requested_ids:
            knowledge = knowledge_by_id.get(knowledge_id)
            if knowledge is None:
                missing_ids.append(knowledge_id)
                continue
            knowledge_type = getattr(knowledge.type, 'value', knowledge.type)
            if int(knowledge_type) == KnowledgeTypeEnum.SPACE.value:
                space_ids.append(knowledge_id)
            else:
                organization_ids.append(knowledge_id)

        if missing_ids:
            logger.warning(f'[queryChunksFromDB] skip missing knowledge ids={missing_ids}')
        logger.info(
            f'[queryChunksFromDB] route ids organization={organization_ids} spaces={space_ids}'
        )
        return organization_ids, space_ids

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
