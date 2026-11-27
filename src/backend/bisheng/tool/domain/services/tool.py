import asyncio
import json
from dataclasses import replace
from hashlib import sha256
from time import perf_counter
from urllib.parse import urlsplit

from fastapi import Request
from langchain_core.tools import BaseTool
from loguru import logger
from pydantic import BaseModel, ConfigDict

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.http_error import NotFoundError, UnAuthorizedError
from bisheng.common.errcode.permission import PermissionEnumerationIncompleteError
from bisheng.common.errcode.tool import (
    ToolImageConfigError,
    ToolMcpSchemaError,
    ToolMcpStdioError,
    ToolSchemaDownloadError,
    ToolSchemaEmptyError,
    ToolSchemaParseError,
    ToolSchemaServerError,
    ToolTypeIsPresetError,
    ToolTypeNameError,
    ToolTypeNotExistsError,
    ToolTypeRepeatError,
)
from bisheng.core.context.tenant import DEFAULT_TENANT_ID, get_current_tenant_id
from bisheng.mcp_manage.constant import McpClientType
from bisheng.mcp_manage.manager import ClientManager
from bisheng.permission.application.access import get_f048_resource_adapter, get_f048_runtime
from bisheng.permission.application.business_authorization import (
    batch_check_business_actions,
    require_business_action,
)
from bisheng.permission.application.identity import resolve_permission_actor
from bisheng.tool.domain.const import ToolPresetType
from bisheng.tool.domain.langchain.linsight_knowledge import SearchKnowledgeBase
from bisheng.tool.domain.models.gpts_tools import GptsTools, GptsToolsDao, GptsToolsType, GptsToolsTypeRead
from bisheng.tool.domain.services.openapi import OpenApiSchema
from bisheng.tool.domain.services.read_projection import (
    merge_masked_configuration,
    preserved_api_key,
    restore_masked_configuration,
    tool_read_view,
)
from bisheng.utils import get_request_ip, md5_hash
from bisheng.utils.mask_data import JsonFieldMasker

from .f048_tool_permission import ToolPermissionRecord
from .mcp_errors import mcp_error_code

_TOOL_VISIBLE_MAX_RESULTS = 5_000
# Schema discovery is interactive; bound connection, initialization and listing together.
_MCP_SCHEMA_TIMEOUT_SECONDS = 30


def _flatten_mcp_error(exc: BaseException) -> str:
    """MCP SDK wraps transport failures in ExceptionGroup (BaseException, not Exception)."""
    nested = getattr(exc, "exceptions", None)
    if nested:
        parts = [_flatten_mcp_error(sub) for sub in nested]
        return "; ".join(part for part in parts if part) or str(exc)
    return str(exc).strip() or type(exc).__name__


class ToolResourceAuthorizationPort:
    """Bind the F048 tool adapter to the resource registry."""

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


class ToolServices(BaseModel):
    """Tool service class"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    request: Request | None = None
    login_user: UserPayload | None = None

    async def get_tool_list(
        self,
        is_preset: int | None = None,
        action: str = "visible",
    ) -> list[GptsToolsTypeRead]:
        """Get a list of tools visible to users"""
        total_start = perf_counter()
        current_tid = get_current_tenant_id() or DEFAULT_TENANT_ID
        preset_filter = ToolPresetType(is_preset) if is_preset is not None else None
        permission_elapsed_ms = 0.0
        type_db_elapsed_ms = 0.0
        if action == "visible":
            if preset_filter == ToolPresetType.PRESET:
                candidate_count = 0
                type_db_start = perf_counter()
                all_tool_type = await GptsToolsDao.aget_tenant_tool_type(
                    current_tid,
                    include_preset=True,
                    is_preset=preset_filter,
                )
                type_db_elapsed_ms = (perf_counter() - type_db_start) * 1000
                permission_strategy = "preset_visible_all"
            else:
                permission_start = perf_counter()
                actor = await resolve_permission_actor(self.login_user)
                if actor.current_tenant_id != current_tid:
                    actor = replace(actor, tenant_id=current_tid)
                visible = await (await get_f048_runtime()).list_visible_objects(
                    actor,
                    resource_type="tool",
                    max_results=_TOOL_VISIBLE_MAX_RESULTS,
                )
                try:
                    candidate_ids = [int(resource_id) for resource_id in visible.object_ids]
                except (TypeError, ValueError) as exc:
                    raise PermissionEnumerationIncompleteError(
                        msg="Tool visibility enumeration returned a non-numeric resource ID",
                    ) from exc
                permission_elapsed_ms = (perf_counter() - permission_start) * 1000
                candidate_count = len(candidate_ids)
                type_db_start = perf_counter()
                all_tool_type = await GptsToolsDao.aget_tenant_tool_type(
                    current_tid,
                    include_preset=is_preset is None,
                    is_preset=preset_filter,
                    tool_type_ids=candidate_ids,
                    include_preset_without_id_filter=is_preset is None,
                )
                type_db_elapsed_ms = (perf_counter() - type_db_start) * 1000
                permission_strategy = "visible_ids_first"
        else:
            type_db_start = perf_counter()
            all_tool_type = await GptsToolsDao.aget_tenant_tool_type(
                current_tid,
                include_preset=is_preset is None,
                is_preset=preset_filter,
            )
            type_db_elapsed_ms = (perf_counter() - type_db_start) * 1000
            candidate_count = len(all_tool_type)
            permission_start = perf_counter()
            action_map = await batch_check_business_actions(
                self.login_user,
                resource_type="tool",
                resource_ids=(one.id for one in all_tool_type),
                actions=(action,),
            )
            all_tool_type = [one for one in all_tool_type if action in action_map.get(str(one.id), frozenset())]
            permission_elapsed_ms = (perf_counter() - permission_start) * 1000
            permission_strategy = "candidate_action_check"
        if action == "visible":
            action_map = await batch_check_business_actions(
                self.login_user,
                resource_type="tool",
                resource_ids=(one.id for one in all_tool_type),
                actions=("visible",),
            )
            all_tool_type = [one for one in all_tool_type if "visible" in action_map.get(str(one.id), ())]
        logger.info(
            "[perf][tool.list.permission] user_id={} tenant_id={} is_preset={} action={} strategy={} "
            "candidates={} kept={} took_ms={:.2f}",
            self.login_user.user_id,
            current_tid,
            is_preset,
            action,
            permission_strategy,
            candidate_count,
            len(all_tool_type),
            permission_elapsed_ms,
        )
        logger.info(
            "[perf][tool.list.dao] user_id={} tenant_id={} is_preset={} action={} phase=tool_types "
            "candidates={} rows={} took_ms={:.2f}",
            self.login_user.user_id,
            current_tid,
            is_preset,
            action,
            candidate_count,
            len(all_tool_type),
            type_db_elapsed_ms,
        )
        tool_type_id = [one.id for one in all_tool_type]
        res: list[GptsToolsTypeRead] = []
        tool_type_children = {}
        for one in all_tool_type:
            tool_type_children[one.id] = []
            res.append(GptsToolsTypeRead.model_validate(one))

        # Get the list of tools under the corresponding category
        children_db_start = perf_counter()
        tool_list = await GptsToolsDao.aget_list_by_type(tool_type_id)
        children_db_elapsed_ms = (perf_counter() - children_db_start) * 1000
        for one in tool_list:
            tool_type_children[one.type].append(one)

        # Include deleted children for identity: the visible-child query filters them out.
        preset_ids = [one.id for one in res if one.is_preset == ToolPresetType.PRESET.value]
        preset_child_keys = await GptsToolsDao.aget_preset_child_keys(preset_ids, current_tid)
        enrich_start = perf_counter()
        edit_map = {}
        if action == "visible":
            edit_map = await batch_check_business_actions(
                self.login_user,
                resource_type="tool",
                resource_ids=(one.id for one in res),
                actions=("edit",),
            )
        for index, one in enumerate(res):
            one.children = tool_type_children.get(one.id, [])

            # Data desensitization
            keys = preset_child_keys.get(one.id, set())
            one.mask_sensitive_data(
                search_category=one.is_preset == ToolPresetType.PRESET.value and "web_search" in keys,
                ambiguous=one.is_preset == ToolPresetType.PRESET.value and not keys,
            )
            include_configuration = action == "visible" and (
                self.login_user.is_global_super or "edit" in edit_map.get(str(one.id), ())
            )
            res[index] = tool_read_view(one, include_configuration=include_configuration)
        enrich_elapsed_ms = (perf_counter() - enrich_start) * 1000

        logger.info(
            "[perf][tool.list.dao] user_id={} tenant_id={} is_preset={} action={} phase=children "
            "parent_ids={} rows={} took_ms={:.2f}",
            self.login_user.user_id,
            current_tid,
            is_preset,
            action,
            len(tool_type_id),
            len(tool_list),
            children_db_elapsed_ms,
        )

        logger.info(
            "[perf][tool.list.total] user_id={} tenant_id={} is_preset={} action={} tool_types={} "
            "children={} permission_ms={:.2f} type_db_ms={:.2f} children_db_ms={:.2f} "
            "enrich_ms={:.2f} took_ms={:.2f}",
            self.login_user.user_id,
            current_tid,
            is_preset,
            action,
            len(res),
            len(tool_list),
            permission_elapsed_ms,
            type_db_elapsed_ms,
            children_db_elapsed_ms,
            enrich_elapsed_ms,
            (perf_counter() - total_start) * 1000,
        )
        return res

    async def add_tools(
        self,
        req: GptsToolsTypeRead,
    ) -> GptsToolsTypeRead:
        """Add custom tool."""
        if req.is_preset == ToolPresetType.PRESET.value:
            raise ToolTypeIsPresetError()
        # Try to parse theopenapi schemaSee if it can be parsed normally, Save if not possible Do not allow to save
        if req.is_preset == ToolPresetType.API.value:
            await self.parse_openapi_schema("", req.openapi_schema)
        elif req.is_preset == ToolPresetType.MCP.value:
            await self.parse_mcp_schema(req.openapi_schema)

        req.id = None
        if req.name.__len__() > 1000 or req.name.__len__() == 0:
            raise ToolTypeNameError()
        # Determine if the category already exists
        tool_type = await GptsToolsDao.get_one_tool_type_by_name(self.login_user.user_id, req.name)
        if tool_type:
            raise ToolTypeRepeatError()
        req.user_id = self.login_user.user_id
        from bisheng.core.context.tenant import get_current_tenant_id

        req.tenant_id = get_current_tenant_id()
        if not req.tenant_id:
            raise UnAuthorizedError()

        for one in req.children:
            one.id = None
            one.tenant_id = req.tenant_id
            one.user_id = self.login_user.user_id
            one.is_delete = 0
            one.is_preset = req.is_preset

        tool_extra = {"api_location": req.api_location, "parameter_name": req.parameter_name}
        req.extra = json.dumps(tool_extra, ensure_ascii=False)
        # Add Tool Category and Corresponding Tools List
        res = await GptsToolsDao.insert_tool_type(req)

        from bisheng.common.errcode.tool import ToolCreationPendingError
        from bisheng.tool.domain.repositories.creation_repository import CreationRepository

        try:
            await self.add_gpts_tools_hook(self.request, self.login_user, res)
        except Exception as exc:
            current = await CreationRepository.load(req.tenant_id, res.id)
            if current is not None and current.creation_state == "READY":
                raise
            logger.exception("Tool creation pending: tenant={} id={}", req.tenant_id, res.id)
            raise ToolCreationPendingError(resource_id=res.id) from exc
        await CreationRepository.ready(req.tenant_id, res.id)

        return res

    @classmethod
    async def add_gpts_tools_hook(cls, request: Request, user: UserPayload, gpts_tool_type: GptsToolsTypeRead) -> bool:
        """After adding custom toolshookFunction"""
        adapter = await get_f048_resource_adapter("tool")
        await adapter.authorize_created(
            record=cls._new_permission_record(gpts_tool_type),
            actor=await resolve_permission_actor(user),
        )

        from bisheng.tool.domain.repositories.creation_repository import CreationRepository

        await CreationRepository.ready(gpts_tool_type.tenant_id, gpts_tool_type.id)
        from bisheng.api.services.audit_log import AuditLogService

        await asyncio.to_thread(AuditLogService.create_tool, user, get_request_ip(request), [], gpts_tool_type)
        return True

    async def require_preset_tool_edit(self, tool_type_id: int) -> GptsToolsType:
        """Validate the preset category before authorizing its concrete edit action."""
        tenant_id = get_current_tenant_id()
        tool_type = await GptsToolsDao.aget_one_tool_type(tool_type_id)
        if not tool_type or tool_type.is_preset != ToolPresetType.PRESET.value:
            raise NotFoundError()
        if tool_type.is_delete or tool_type.tenant_id != tenant_id:
            raise UnAuthorizedError()

        await require_business_action(
            self.login_user,
            resource_type="tool",
            resource_id=tool_type_id,
            action="edit",
        )
        return tool_type

    async def update_tool_config(self, tool_type_id: int, extra: dict) -> bool:
        tool_type = await self.require_preset_tool_edit(tool_type_id)
        if tool_type.extra is None:
            tool_type.extra = "{}"

        json_masker = JsonFieldMasker()

        old_config = json.loads(tool_type.extra)
        if not isinstance(old_config, dict) or not isinstance(extra, dict):
            raise ValueError("Tool configuration must be an object")
        child_keys = await GptsToolsDao.aget_preset_child_keys([tool_type_id], tool_type.tenant_id)
        if child_keys.get(tool_type_id, set()) & {"image_generation", "dalle_image_generator"}:
            from bisheng_langchain.gpts.tools.image_generation.tool import ImageGenerationError, normalize_image_config

            if tool_type.is_delete or tool_type.tenant_id != get_current_tenant_id():
                raise UnAuthorizedError()
            try:
                if extra.get("provider") not in (None, "", "openai") or extra.get("azure_endpoint"):
                    raise ImageGenerationError("Unsupported image protocol")
                old_azure = old_config.get("azure_endpoint") or old_config.get("provider") == "azure"
                if old_azure and extra.get("provider") != "openai":
                    raise ImageGenerationError("Reconfigure the image service")
                merged = merge_masked_configuration(old_config, extra)
                candidate = {
                    key: merged[key]
                    for key in ("openai_api_base", "openai_api_key", "openai_proxy", "model")
                    if key in merged
                }
                normalized = normalize_image_config(candidate, legacy=bool(old_config) and not old_azure)
                old_host = urlsplit(old_config.get("openai_api_base") or "https://api.openai.com/v1").hostname
                new_host = urlsplit(normalized["openai_api_base"]).hostname
                supplied_key = extra.get("openai_api_key")
                if (old_azure or old_host != new_host) and (
                    not supplied_key or json_masker.is_masked_value(supplied_key, "openai_api_key")
                ):
                    raise ImageGenerationError("Enter a key for the new image service")
                merge_extra = json.dumps(normalized, ensure_ascii=False)
            except (ImageGenerationError, ValueError, TypeError):
                raise ToolImageConfigError() from None
        else:
            merge_extra = json.dumps(merge_masked_configuration(old_config, extra), ensure_ascii=False)
        await GptsToolsDao.update_tools_extra(tool_type_id, merge_extra)
        return True

    @staticmethod
    async def load_openapi_schema(download_url: str | None, file_content: str | None, *, download=None):
        """Share content input and parsing while letting each caller select its download policy."""
        if download_url:
            if download is None:
                from bisheng.api.utils import get_url_content

                download = get_url_content
            try:
                file_content = await download(download_url)
            except Exception as exc:
                # URLs and transport exceptions can contain query credentials.
                logger.warning("Tool schema download failed ({})", type(exc).__name__)
                raise ToolSchemaDownloadError() from None
        if not file_content:
            raise ToolSchemaEmptyError()
        try:
            return OpenApiSchema.from_content(file_content), file_content
        except Exception:
            raise ToolSchemaParseError(exception=ValueError("Invalid OpenAPI document")) from None

    @staticmethod
    async def parse_openapi_schema(download_url: str, file_content: str) -> GptsToolsTypeRead:
        schema, file_content = await ToolServices.load_openapi_schema(download_url, file_content)
        #  analyzingopenapi schemaConvert to Helper Tool Format
        try:
            schema.parse_server()
            if not schema.default_server.startswith(("http", "https")):
                raise ToolSchemaServerError(data={"url": schema.default_server})
            tool_type = GptsToolsTypeRead(
                name=schema.title,
                description=schema.description,
                is_preset=ToolPresetType.API.value,
                server_host=schema.default_server,
                openapi_schema=file_content,
                api_location=schema.api_location,
                parameter_name=schema.parameter_name,
                auth_type=schema.auth_type,
                auth_method=schema.auth_method,
                children=[],
            )
            # Parsing to get all theapi
            schema.parse_paths()
            for one in schema.apis:
                tool_type.children.append(
                    GptsTools(
                        name=one["operationId"],
                        desc=one["description"],
                        tool_key=md5_hash(one["operationId"]),
                        is_preset=0,
                        is_delete=0,
                        api_params=one["parameters"],
                        extra=json.dumps(one, ensure_ascii=False),
                    )
                )
            return tool_type
        except BaseErrorCode as e:
            raise e
        except Exception as e:
            logger.exception(f"openapi schema parse error {e}")
            raise ToolSchemaParseError(exception=e)

    @staticmethod
    async def parse_mcp_schema(file_content: str) -> GptsToolsTypeRead:
        try:
            result = json.loads(file_content)
            mcp_servers = result["mcpServers"]
        except Exception as e:
            logger.exception(f"mcp tool schema parse error {e}")
            raise ToolMcpSchemaError(exception=e)
        tool_type = None
        for _key, value in mcp_servers.items():
            # analyzingmcpService Config
            tool_type = GptsToolsTypeRead(
                name=value.get("name", ""),
                server_host=value.get("url", ""),
                description=value.get("description", ""),
                is_preset=ToolPresetType.MCP.value,
                openapi_schema=file_content,
                children=[],
            )
            client_type, _ = ClientManager.parse_mcp_client_type(tool_type.openapi_schema)
            if client_type == McpClientType.STDIO.value:
                raise ToolMcpStdioError()
            try:
                async with asyncio.timeout(_MCP_SCHEMA_TIMEOUT_SECONDS):
                    client = await ClientManager.connect_mcp_from_json(result)
                    tools = await client.list_tools()
            except BaseErrorCode:
                raise
            except BaseException as e:
                if isinstance(e, KeyboardInterrupt | SystemExit | asyncio.CancelledError):
                    raise
                logger.exception("mcp tool connect/list error")
                raise mcp_error_code(e)() from e

            for one in tools:
                tool_type.children.append(
                    GptsTools(
                        name=one.name,
                        desc=one.description,
                        tool_key=md5_hash(one.name),
                        is_preset=ToolPresetType.MCP.value,
                        api_params=ToolServices.convert_input_schema(one.inputSchema),
                        extra=one.model_dump_json(),
                    )
                )
            break
        if tool_type is None:
            raise ToolMcpSchemaError()

        return tool_type

    @classmethod
    async def _update_gpts_tools(
        cls, exist_tool_type: GptsToolsType, req: GptsToolsTypeRead, login_user=None
    ) -> GptsToolsTypeRead:
        exist_tool_type.name = req.name
        exist_tool_type.logo = req.logo
        exist_tool_type.description = req.description
        exist_tool_type.server_host = req.server_host
        exist_tool_type.auth_method = req.auth_method
        exist_tool_type.api_key = preserved_api_key(req.api_key, exist_tool_type.api_key)
        exist_tool_type.auth_type = req.auth_type
        exist_tool_type.openapi_schema = restore_masked_configuration(
            req.openapi_schema, exist_tool_type.openapi_schema
        )
        tool_extra = {"api_location": req.api_location, "parameter_name": req.parameter_name}
        exist_tool_type.extra = json.dumps(tool_extra, ensure_ascii=False)

        children_map = {}
        for one in req.children:
            children_map[one.name] = one

        # Get old under this categoryAPIVertical
        from bisheng.core.context.tenant import strict_tenant_filter, tenant_execution_scope

        with tenant_execution_scope(int(exist_tool_type.tenant_id)), strict_tenant_filter():
            old_tool_list = await GptsToolsDao.aget_list_by_type([exist_tool_type.id])
        # List of tools that need to be removed
        delete_tool_id_list = []
        # List of tools that need to be updated
        update_tool_list = []
        for one in old_tool_list:
            # Explain this tool Removal required
            if children_map.get(one.name) is None:
                delete_tool_id_list.append(one.id)
            else:
                # Explain that this tool needs to be updated
                new_tool_info = children_map.pop(one.name)
                one.name = new_tool_info.name
                one.desc = new_tool_info.desc
                one.extra = restore_masked_configuration(new_tool_info.extra, one.extra)
                one.api_params = new_tool_info.api_params
                update_tool_list.append(one)

        add_children = []
        for one in children_map.values():
            one.id = None
            one.user_id = exist_tool_type.user_id
            one.tenant_id = exist_tool_type.tenant_id
            one.is_preset = exist_tool_type.is_preset
            one.is_delete = 0
            add_children.append(one)

        deleted = [row for row in old_tool_list if row.id in delete_tool_id_list]
        owner_delta = len(add_children) - sum(row.user_id == exist_tool_type.user_id for row in deleted)
        tenant_delta = len(add_children) - len(deleted)
        await cls._assert_tool_delta_quota(exist_tool_type, max(owner_delta, 0), max(tenant_delta, 0), login_user)
        await GptsToolsDao.update_tool_type(exist_tool_type, delete_tool_id_list, add_children, update_tool_list)

        with tenant_execution_scope(int(exist_tool_type.tenant_id)), strict_tenant_filter():
            children = await GptsToolsDao.aget_list_by_type([exist_tool_type.id])
        return GptsToolsTypeRead(**exist_tool_type.model_dump(), children=children)

    @staticmethod
    async def _assert_tool_delta_quota(parent, owner_delta, tenant_delta, login_user=None):
        if owner_delta == 0 or parent.is_preset == ToolPresetType.PRESET.value:
            return
        from bisheng.common.errcode.tenant_quota import QuotaResponsibilityChangedError, QuotaUsageUnavailableError
        from bisheng.role.application.effective_roles import load_effective_roles
        from bisheng.role.domain.services.quota_service import QuotaService

        if not parent.user_id or not parent.tenant_id:
            raise QuotaUsageUnavailableError()
        policy = await load_effective_roles(parent.user_id)
        if policy.is_identity_admin:
            return
        if policy.home_tenant_id != parent.tenant_id:
            raise QuotaResponsibilityChangedError()
        await QuotaService.check_quota(
            parent.user_id, "tool", parent.tenant_id, login_user, delta=owner_delta, tenant_delta=tenant_delta
        )

    async def update_tools(self, req: GptsToolsTypeRead) -> GptsToolsTypeRead:
        """
        Updating tool categories, including updating tool category names and deletions, adding tool categoryAPI
        """
        exist_tool_type = await GptsToolsDao.aget_one_tool_type(req.id)
        if not exist_tool_type:
            raise ToolTypeNotExistsError()
        if exist_tool_type.is_preset == ToolPresetType.PRESET.value:
            child_keys = await GptsToolsDao.aget_preset_child_keys([exist_tool_type.id], exist_tool_type.tenant_id)
            keys = child_keys.get(exist_tool_type.id, set())
            if not keys or "web_search" in keys:
                raise ToolTypeIsPresetError()
        if req.name.__len__() > 1000 or req.name.__len__() == 0:
            raise ToolTypeNameError()

        #  Determine if the tool category name is a duplicate
        tool_type = await GptsToolsDao.get_one_tool_type_by_name(self.login_user.user_id, req.name)
        if tool_type and tool_type.id != exist_tool_type.id:
            raise ToolTypeRepeatError()
        await require_business_action(
            self.login_user,
            resource_type="tool",
            resource_id=exist_tool_type.id,
            action="edit",
        )

        # Restore response masks only after authorizing the saved resource, and
        # before discovery so a masked MCP header is never sent as a credential.
        req = req.model_copy(deep=True)
        req.openapi_schema = restore_masked_configuration(req.openapi_schema, exist_tool_type.openapi_schema)
        if req.is_preset == ToolPresetType.API.value:
            await self.parse_openapi_schema("", req.openapi_schema)
        elif req.is_preset == ToolPresetType.MCP.value:
            await self.parse_mcp_schema(req.openapi_schema)
        res = await self._update_gpts_tools(exist_tool_type, req, self.login_user)
        await self.update_tool_hook(self.request, self.login_user, exist_tool_type)
        return tool_read_view(res, include_configuration=True)

    @classmethod
    async def update_tool_hook(cls, request: Request, user: UserPayload, exist_tool_type):
        # F008: removed GroupResourceDao for audit (AC-08)
        from bisheng.api.services.audit_log import AuditLogService

        await asyncio.to_thread(AuditLogService.update_tool, user, get_request_ip(request), [], exist_tool_type)

    async def delete_tools(self, tool_type_id: int) -> bool:
        """Delete Tool Category"""
        exist_tool_type = await GptsToolsDao.aget_one_tool_type(tool_type_id)
        if not exist_tool_type:
            return True
        if exist_tool_type.is_preset == ToolPresetType.PRESET.value:
            raise ToolTypeIsPresetError()
        await require_business_action(
            self.login_user,
            resource_type="tool",
            resource_id=exist_tool_type.id,
            action="delete",
        )
        adapter = await get_f048_resource_adapter("tool")
        record = await adapter.load_permission_record(resource_id=str(exist_tool_type.id))
        if record is None:
            raise ToolTypeNotExistsError()
        await adapter.project_delete(
            record=record,
            actor=await resolve_permission_actor(self.login_user),
        )

        await GptsToolsDao.delete_tool_type(tool_type_id, tenant_id=exist_tool_type.tenant_id)
        await adapter.cleanup_deleted(record=record, actor=await resolve_permission_actor(self.login_user))
        await self.delete_tool_hook(self.request, self.login_user, exist_tool_type)
        return True

    @classmethod
    async def delete_tool_hook(cls, request, user: UserPayload, gpts_tool_type) -> bool:
        """After deleting the customizerhookFunction"""
        logger.info(f"delete_gpts_tool_hook id: {gpts_tool_type.id}, user: {user.user_id}")

        from bisheng.api.services.audit_log import AuditLogService

        await asyncio.to_thread(AuditLogService.delete_tool, user, get_request_ip(request), [], gpts_tool_type)
        return True

    @classmethod
    async def resume_creation(cls, resource_id, login_user):
        from bisheng.common.errcode.permission import PermissionInvalidResourceError
        from bisheng.core.context.tenant import get_current_tenant_id
        from bisheng.permission.application.creation_recovery import resume_created_permission
        from bisheng.permission.domain.schemas import VerifiedPermissionTarget
        from bisheng.role.application.effective_roles import load_effective_roles
        from bisheng.tool.domain.repositories.creation_repository import CreationRepository
        from bisheng.user.domain.services.auth import LoginUser

        tenant_id = get_current_tenant_id()
        row = await CreationRepository.load(tenant_id, resource_id)
        policy = await load_effective_roles(login_user.user_id)
        if (
            row is None
            or row.user_id != login_user.user_id
            or (policy.home_tenant_id != tenant_id and not policy.is_identity_admin)
        ):
            raise PermissionInvalidResourceError()
        if row.creation_state == "READY":
            return row
        if not policy.is_identity_admin:
            await LoginUser.assert_effective_web_menu_contains(login_user.user_id, "tool")
        fresh_user = await LoginUser.init_login_user(login_user.user_id, login_user.user_name)
        actor = await resolve_permission_actor(fresh_user)
        await resume_created_permission(
            actor=actor,
            target=VerifiedPermissionTarget(
                tenant_id=tenant_id,
                resource_type="tool",
                resource_id=str(row.id),
                resource_version=0,
                context_version=cls._new_permission_record(row).context_version,
            ),
            owner_user_id=row.user_id,
        )
        await CreationRepository.ready(tenant_id, row.id)
        return await CreationRepository.load(tenant_id, row.id)

    @staticmethod
    def _new_permission_record(
        tool_type: GptsToolsType | GptsToolsTypeRead,
    ) -> ToolPermissionRecord:
        preset = tool_type.is_preset == ToolPresetType.PRESET.value
        context_version = sha256(
            (f"tool|{tool_type.id}|{tool_type.tenant_id}|{tool_type.user_id}|{tool_type.is_preset}").encode()
        ).hexdigest()
        return ToolPermissionRecord(
            tenant_id=int(tool_type.tenant_id or 0),
            resource_id=str(tool_type.id),
            status="ACTIVE",
            owner_user_id=tool_type.user_id,
            permission_version=0,
            context_version=context_version,
            preset=preset,
        )

    async def refresh_all_mcp(self) -> list[dict[str, str | int]]:
        """return mcp server error msg"""
        # get user all mcp tool
        tool_types = await GptsToolsDao.aget_user_tool_type(self.login_user.user_id, is_preset=ToolPresetType.MCP)
        if not tool_types:
            return []

        tools = await GptsToolsDao.aget_list_by_type(tool_type_ids=[one.id for one in tool_types])
        tools_map = {}
        for one in tools:
            if one.type not in tools_map:
                tools_map[one.type] = []
            tools_map[one.type].append(one)
        error_name = []
        for one in tool_types:
            try:
                await require_business_action(
                    self.login_user,
                    resource_type="tool",
                    resource_id=one.id,
                    action="edit",
                )
                await self.refresh_mcp_tools(one, tools_map.get(one.id, []))
            except Exception as error:
                logger.exception(f"{one.name} tool refresh failed")
                error_name.append({"name": one.name, "code": mcp_error_code(error).Code})
        return error_name

    async def refresh_mcp_tools(self, tool_type: GptsToolsType, old_tools: list[GptsTools]):
        """refresh mcp tools"""
        # 1. get all new tools
        # Instantiatemcpservice object, getting a list of tools
        client = await ClientManager.connect_mcp_from_json(tool_type.openapi_schema)
        tools = await client.list_tools()
        children = []
        for one in tools:
            children.append(
                GptsTools(
                    name=one.name,
                    desc=one.description,
                    is_preset=ToolPresetType.MCP.value,
                    api_params=self.convert_input_schema(one.inputSchema),
                    extra=one.model_dump_json(),
                    type=tool_type.id,
                )
            )

        req = GptsToolsTypeRead(**tool_type.model_dump(), children=children)
        await self._update_gpts_tools(tool_type, req)

    @classmethod
    def convert_input_schema(cls, input_schema: dict):
        """TukarmcpInput parameters for the tool Formatting for custom tools"""
        required = input_schema.get("required", [])
        properties = input_schema.get("properties", {})
        res = []
        for filed, field_info in properties.items():
            res.append(
                {
                    "in": "query",
                    "name": filed,
                    "description": field_info.get("description"),
                    "required": filed in required,
                    "schema": {
                        "type": field_info.get("type"),
                    },
                }
            )
        return res

    @classmethod
    async def init_linsight_tools(
        cls, root_path: str, allowed_knowledge_ids: set[str] | None = None, login_user=None
    ) -> list[BaseTool]:
        """Initialize Linsight task-mode built-in tools.

        Only the knowledge-retrieval tool is injected here. The legacy local_file
        tools (list_files / read_text_file / add_text_to_file / ...) are retired:
        deepagents' FilesystemMiddleware already ships ls/read_file/write_file/
        edit_file over the SAME WorkspaceBackend the agent is built with, so the
        old tools duplicated the file toolset and made the model pick between two
        equivalent file APIs. ``root_path`` is kept in the signature for callers
        but no longer needed by the (now file-tool-free) built-in set.

        ``allowed_knowledge_ids`` is the C4 permission whitelist (user-visible KB
        ids + this session's uploaded file ids) handed to ``SearchKnowledgeBase``;
        the tool refuses any id outside it. ``None`` leaves the tool ungated.

        When the caller passes an EMPTY set (no knowledge base selected and no
        uploaded files), there is nothing to search, so the tool is NOT injected
        at all — otherwise the model would still see it and call it with a missing
        knowledge_id ("Field required"). ``None`` (back-compat) keeps the tool.

        ``login_user`` is the user the tool searches as (daily-chat retrieval and
        its file permissions); a tool without it answers every search with a failure.
        """
        if allowed_knowledge_ids is not None and not allowed_knowledge_ids:
            return []
        return [SearchKnowledgeBase(allowed_knowledge_ids=allowed_knowledge_ids, login_user=login_user)]

    @classmethod
    async def get_linsight_tools(cls) -> list[GptsToolsTypeRead]:
        return [
            GptsToolsTypeRead(
                id=100000,
                name="知识库和知识空间检索",
                description="检索组织知识库、个人知识库以及知识空间的内容",
                children=[
                    GptsTools(
                        id=100001,
                        name="知识库和知识空间检索",
                        desc="检索组织知识库、个人知识库以及知识空间的内容。",
                        tool_key="search_knowledge_base",
                    )
                ],
            ),
            # Legacy "文件操作" group (list_files / read_text_file / add_text_to_file
            # / ...) removed: task mode runs on deepagents, whose FilesystemMiddleware
            # provides ls/read_file/write_file/edit_file transparently. They are not
            # user-configurable, so they no longer belong in the advertised tree.
        ]
