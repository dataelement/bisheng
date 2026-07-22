from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import re
import secrets
from contextlib import contextmanager
from datetime import datetime, timezone

from pydantic import ValidationError

from bisheng.common.cursor import CursorDecodeError
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.developer_token import (
    DeveloperTokenAdminForbiddenError,
    DeveloperTokenBindingForbiddenError,
    DeveloperTokenDisabledError,
    DeveloperTokenInvalidError,
    DeveloperTokenInvalidFileSyncRuleError,
    DeveloperTokenInvalidFileSyncTargetCursorError,
    DeveloperTokenInvalidIpRuleError,
    DeveloperTokenInvalidRateLimitError,
    DeveloperTokenInvalidRouteRuleError,
    DeveloperTokenIpForbiddenError,
    DeveloperTokenLimiterUnavailableError,
    DeveloperTokenMissingError,
    DeveloperTokenRateLimitedError,
    DeveloperTokenRouteForbiddenError,
)
from bisheng.common.errcode.knowledge_space import (
    SpaceFolderNotFoundError,
    SpaceNotFoundError,
    SpacePermissionDeniedError,
)
from bisheng.common.models.config import ConfigDao
from bisheng.common.schemas.api import PageData
from bisheng.common.services.config_service import settings
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.config.settings import decrypt_token, encrypt_token
from bisheng.core.context.tenant import (
    DEFAULT_TENANT_ID,
    bypass_tenant_filter,
    current_tenant_id,
    get_current_tenant_id,
    set_admin_scope_tenant_id,
    set_current_tenant_id,
    set_visible_tenant_ids,
    visible_tenant_ids,
)
from bisheng.database.models.audit_log import AuditLogDao
from bisheng.database.models.department import DepartmentDao, UserDepartmentDao
from bisheng.database.models.tenant import ROOT_TENANT_ID, TenantDao, UserTenantDao
from bisheng.developer_token.domain.models import DeveloperToken
from bisheng.developer_token.domain.repositories import DeveloperTokenRepository
from bisheng.developer_token.domain.schemas import (
    DeveloperTokenCreate,
    DeveloperTokenCreateResponse,
    DeveloperTokenDetail,
    DeveloperTokenFileSyncOptions,
    DeveloperTokenFileSyncRule,
    DeveloperTokenFileSyncTargetChildren,
    DeveloperTokenGlobalConfig,
    DeveloperTokenListQuery,
    DeveloperTokenPrincipal,
    DeveloperTokenRead,
    DeveloperTokenSecretResponse,
    DeveloperTokenUpdate,
    FileSyncOptionBusinessDomain,
    FileSyncOptionCategory,
    FileSyncOptionChild,
    FileSyncTargetDisplay,
    FileSyncTargetFolderOption,
    FileSyncTargetPathItem,
    FileSyncTargetSpaceGroup,
    FileSyncTargetSpaceGroupsPage,
    FileSyncTargetSpaceOption,
)
from bisheng.knowledge.domain.constants import normalize_business_domain_code
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.shougang_portal_config.domain.services.portal_config_service import (
    ShougangPortalConfigService,
)
from bisheng.user.domain.models.user import UserDao
from bisheng.user.domain.models.user_role import UserRoleDao
from bisheng.utils.http_middleware import _check_is_global_super

logger = logging.getLogger(__name__)


class DeveloperTokenService:
    CONFIG_KEY = "developer_token_global_config"
    RATE_KEY_TEMPLATE = "developer_token:rate:{token_id}:{endpoint_hash}:{minute}"
    RATE_ENDPOINT_HASH_LENGTH = 16
    RATE_ENDPOINT_FALLBACK = "UNKNOWN"
    TOKEN_PREFIX = "bst_"
    TOKEN_PREFIX_DISPLAY_LENGTH = 12
    MAX_ROUTE_RULES = 200
    ROUTE_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"})
    ROUTE_MATCH_TYPES = frozenset({"METHOD_PATH", "PATH", "PREFIX"})

    repository = DeveloperTokenRepository

    @classmethod
    async def list_tokens(cls, operator: UserPayload, query: DeveloperTokenListQuery) -> PageData[DeveloperTokenRead]:
        tenant_id = await cls._resolve_list_tenant(operator, query.tenant_id)
        rows, total = await cls.repository.list_tokens(
            page=query.page,
            limit=query.limit,
            keyword=query.keyword,
            tenant_id=tenant_id,
            user_id=query.user_id,
            enabled=query.enabled,
        )
        display_map = await cls._build_file_sync_target_displays(rows)
        return PageData(
            data=[
                await cls._to_read(
                    row,
                    file_sync_target_display=display_map.get(int(row.id)),
                )
                for row in rows
            ],
            total=total,
        )

    @classmethod
    async def get_token_detail(cls, token_id: int, operator: UserPayload) -> DeveloperTokenDetail:
        token = await cls._get_existing_token(token_id)
        await cls._assert_admin_scope(operator, token.tenant_id)
        display_map = await cls._build_file_sync_target_displays([token])
        return await cls._to_detail(
            token,
            file_sync_target_display=display_map.get(int(token.id)),
        )

    @classmethod
    async def create_token(
        cls,
        operator: UserPayload,
        payload: DeveloperTokenCreate,
        *,
        request_ip: str | None = None,
        user_agent: str | None = None,
    ) -> DeveloperTokenCreateResponse:
        tenant_id = await cls._resolve_binding_tenant(
            payload.user_id,
            payload.department_id,
            payload.dept_id,
        )
        await cls._assert_admin_scope(operator, tenant_id)
        cls._validate_ip_whitelist(payload.ip_whitelist)
        cls._validate_rate_limit(payload.rate_limit_per_minute)
        route_whitelist = cls._normalize_route_whitelist(payload.route_whitelist)
        file_sync_rule = await cls._validate_file_sync_rule(
            tenant_id,
            payload.user_id,
            payload.file_sync_rule,
        )

        plaintext = cls._generate_plaintext_token()
        token = DeveloperToken(
            tenant_id=tenant_id,
            user_id=payload.user_id,
            name=payload.name.strip(),
            token_hash=cls._hash_token(plaintext),
            token_ciphertext=cls._encrypt_plaintext(plaintext),
            token_prefix=plaintext[: cls.TOKEN_PREFIX_DISPLAY_LENGTH],
            enabled=payload.enabled,
            override_ip_whitelist=payload.override_ip_whitelist,
            ip_whitelist=payload.ip_whitelist or "",
            override_rate_limit=payload.override_rate_limit,
            rate_limit_per_minute=cls._normalize_rate_limit(payload.rate_limit_per_minute),
            route_whitelist=route_whitelist,
            file_sync_rule=file_sync_rule,
            created_by=operator.user_id,
            updated_by=operator.user_id,
        )
        token = await cls.repository.create_token(token)
        await cls._audit(
            "developer_token.create",
            operator,
            token,
            request_ip=request_ip,
            user_agent=user_agent,
            metadata={"token_id": token.id, "prefix": token.token_prefix},
        )
        return DeveloperTokenCreateResponse(
            token=await cls._to_read(token),
            plaintext_token=plaintext,
        )

    @classmethod
    async def update_token(
        cls,
        token_id: int,
        operator: UserPayload,
        payload: DeveloperTokenUpdate,
        *,
        request_ip: str | None = None,
        user_agent: str | None = None,
    ) -> DeveloperTokenRead:
        token = await cls._get_existing_token(token_id)
        await cls._assert_admin_scope(operator, token.tenant_id)

        update_data = payload.model_dump(exclude_unset=True)
        target_user_id = token.user_id
        binding_keys = {"user_id", "department_id", "dept_id"}
        if binding_keys.intersection(update_data):
            target_user_id = int(update_data.get("user_id", token.user_id))
            target_tenant_id = await cls._resolve_binding_tenant(
                target_user_id,
                update_data.get("department_id"),
                update_data.get("dept_id"),
            )
            await cls._assert_admin_scope(operator, target_tenant_id)
            update_data["tenant_id"] = target_tenant_id
            update_data["user_id"] = target_user_id
        update_data.pop("department_id", None)
        update_data.pop("dept_id", None)

        target_tenant_id = int(update_data.get("tenant_id", token.tenant_id))
        final_file_sync_rule = update_data.get("file_sync_rule", token.file_sync_rule)
        normalized_file_sync_rule = await cls._validate_file_sync_rule(
            target_tenant_id,
            target_user_id,
            final_file_sync_rule,
        )
        if "file_sync_rule" in update_data:
            update_data["file_sync_rule"] = normalized_file_sync_rule

        if "ip_whitelist" in update_data:
            cls._validate_ip_whitelist(update_data.get("ip_whitelist"))
        if "rate_limit_per_minute" in update_data:
            cls._validate_rate_limit(update_data.get("rate_limit_per_minute"))
            update_data["rate_limit_per_minute"] = cls._normalize_rate_limit(update_data.get("rate_limit_per_minute"))
        if "route_whitelist" in update_data:
            update_data["route_whitelist"] = cls._normalize_route_whitelist(update_data.get("route_whitelist"))
        if "name" in update_data and update_data["name"] is not None:
            update_data["name"] = update_data["name"].strip()
        update_data["updated_by"] = operator.user_id
        update_data["update_time"] = datetime.now()

        before = cls._non_secret_snapshot(token)
        updated = await cls.repository.update_token(token_id, **update_data)
        if updated is None:
            raise DeveloperTokenInvalidError()

        await cls._audit(
            "developer_token.update",
            operator,
            updated,
            request_ip=request_ip,
            user_agent=user_agent,
            metadata={
                "token_id": updated.id,
                "prefix": updated.token_prefix,
                "before": before,
                "after": cls._non_secret_snapshot(updated),
            },
        )
        return await cls._to_read(updated)

    @classmethod
    async def delete_token(
        cls,
        token_id: int,
        operator: UserPayload,
        *,
        request_ip: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        token = await cls._get_existing_token(token_id)
        await cls._assert_admin_scope(operator, token.tenant_id)
        deleted = await cls.repository.logic_delete_token(token_id, operator.user_id)
        if not deleted:
            raise DeveloperTokenInvalidError()
        await cls._audit(
            "developer_token.delete",
            operator,
            token,
            request_ip=request_ip,
            user_agent=user_agent,
            metadata={"token_id": token.id, "prefix": token.token_prefix},
        )

    @classmethod
    async def view_secret(
        cls,
        token_id: int,
        operator: UserPayload,
        *,
        request_ip: str | None = None,
        user_agent: str | None = None,
    ) -> DeveloperTokenSecretResponse:
        token = await cls._get_existing_token(token_id)
        await cls._assert_admin_scope(operator, token.tenant_id)
        plaintext = cls._decrypt_plaintext(token.token_ciphertext)
        await cls._audit(
            "developer_token.secret_view",
            operator,
            token,
            request_ip=request_ip,
            user_agent=user_agent,
            metadata={"token_id": token.id, "prefix": token.token_prefix},
        )
        return DeveloperTokenSecretResponse(
            id=token.id,
            token_prefix=token.token_prefix,
            plaintext_token=plaintext,
        )

    @classmethod
    async def get_global_config(cls, operator: UserPayload) -> DeveloperTokenGlobalConfig:
        await cls._assert_global_super(operator)
        return await cls._read_global_config()

    @classmethod
    async def get_file_sync_options(
        cls,
        operator: UserPayload,
        *,
        tenant_id: int,
        user_id: int,
        space_cursor: str | None = None,
        space_page_size: int = 50,
        space_keyword: str | None = None,
    ) -> DeveloperTokenFileSyncOptions:
        await cls._assert_admin_scope(operator, tenant_id)
        keyword = (space_keyword or "").strip() or None
        with cls._target_tenant_context(tenant_id):
            config = await cls._get_file_sync_portal_config(tenant_id)
            if config is None:
                raise DeveloperTokenInvalidFileSyncRuleError(
                    msg="portal categories and business domains must be configured first"
                )
            bound_user = await cls._get_bound_user_payload(tenant_id, user_id)
            try:
                spaces = await KnowledgeSpaceService.list_file_sync_target_spaces(
                    login_user=bound_user,
                    cursor=space_cursor,
                    page_size=space_page_size,
                    keyword=keyword,
                )
            except CursorDecodeError as exc:
                raise DeveloperTokenInvalidFileSyncTargetCursorError() from exc

        categories: list[FileSyncOptionCategory] = []
        for item in config.portal.document_types:
            code = str(getattr(item, "code", "") or "").strip().upper()
            if re.fullmatch(r"[A-Z0-9_]{1,16}", code) is None:
                continue
            children: list[FileSyncOptionChild] = []
            for child in getattr(item, "children", None) or []:
                child_code = str(getattr(child, "code", "") or "").strip().upper()
                if re.fullmatch(r"[A-Z0-9_-]{1,16}", child_code) is None:
                    continue
                children.append(
                    FileSyncOptionChild(
                        code=child_code,
                        label=str(getattr(child, "label", "") or "").strip(),
                    )
                )
            if children:
                categories.append(
                    FileSyncOptionCategory(
                        code=code,
                        label=str(getattr(item, "label", "") or "").strip(),
                        children=children,
                    )
                )

        domains: list[FileSyncOptionBusinessDomain] = []
        seen_domain_codes: set[str] = set()
        for item in config.portal.domains:
            code = normalize_business_domain_code(getattr(item, "code", None))
            if not bool(getattr(item, "enabled", False)) or code is None or code in seen_domain_codes:
                continue
            seen_domain_codes.add(code)
            domains.append(
                FileSyncOptionBusinessDomain(
                    code=code,
                    name=str(getattr(item, "name", "") or "").strip(),
                )
            )

        grouped_spaces: dict[str, list[FileSyncTargetSpaceOption]] = {
            "public": [],
            "department": [],
        }
        for space in spaces.items:
            if space.space_type not in grouped_spaces:
                continue
            grouped_spaces[space.space_type].append(
                FileSyncTargetSpaceOption(
                    id=space.id,
                    name=space.name,
                    selectable=space.selectable,
                    has_children=space.has_children,
                )
            )

        return DeveloperTokenFileSyncOptions(
            tenant_id=tenant_id,
            user_id=user_id,
            categories=categories,
            business_domains=domains,
            target_space_groups=FileSyncTargetSpaceGroupsPage(
                data=[
                    FileSyncTargetSpaceGroup(
                        space_type=space_type,
                        spaces=grouped_spaces[space_type],
                    )
                    for space_type in ("public", "department")
                    if grouped_spaces[space_type]
                ],
                has_more=spaces.has_more,
                next_cursor=spaces.next_cursor,
                page_size=space_page_size,
            ),
        )

    @classmethod
    async def get_file_sync_target_children(
        cls,
        operator: UserPayload,
        *,
        tenant_id: int,
        user_id: int,
        knowledge_id: int,
        parent_id: int | None,
        cursor: str | None,
        page_size: int,
    ) -> DeveloperTokenFileSyncTargetChildren:
        await cls._assert_admin_scope(operator, tenant_id)
        with cls._target_tenant_context(tenant_id):
            bound_user = await cls._get_bound_user_payload(tenant_id, user_id)
            try:
                page = await KnowledgeSpaceService.list_file_sync_target_folders(
                    login_user=bound_user,
                    knowledge_id=knowledge_id,
                    parent_id=parent_id,
                    cursor=cursor,
                    page_size=page_size,
                )
            except CursorDecodeError as exc:
                raise DeveloperTokenInvalidFileSyncTargetCursorError() from exc
            except (SpaceNotFoundError, SpaceFolderNotFoundError) as exc:
                raise DeveloperTokenInvalidFileSyncRuleError(msg="file sync target is unavailable") from exc

        return DeveloperTokenFileSyncTargetChildren(
            data=[
                FileSyncTargetFolderOption(
                    id=item.id,
                    name=item.name,
                    selectable=item.selectable,
                    navigation_only=not item.selectable,
                    has_children=item.has_children,
                )
                for item in page.items
            ],
            has_more=page.has_more,
            next_cursor=page.next_cursor,
            page_size=page_size,
        )

    @classmethod
    async def update_global_config(
        cls,
        operator: UserPayload,
        payload: DeveloperTokenGlobalConfig,
        *,
        request_ip: str | None = None,
        user_agent: str | None = None,
    ) -> DeveloperTokenGlobalConfig:
        await cls._assert_global_super(operator)
        cls._validate_ip_whitelist(payload.ip_whitelist)
        cls._validate_rate_limit(payload.rate_limit_per_minute)
        normalized = DeveloperTokenGlobalConfig(
            ip_whitelist=payload.ip_whitelist or "",
            rate_limit_per_minute=cls._normalize_rate_limit(payload.rate_limit_per_minute),
        )
        before = await cls._read_global_config()
        await ConfigDao.insert_or_update_config(
            cls.CONFIG_KEY,
            json.dumps(normalized.model_dump(), ensure_ascii=False),
        )
        await AuditLogDao.ainsert_v2(
            tenant_id=ROOT_TENANT_ID,
            operator_id=operator.user_id,
            operator_tenant_id=get_current_tenant_id() or ROOT_TENANT_ID,
            action="developer_token.global_config.update",
            target_type="developer_token_config",
            target_id=cls.CONFIG_KEY,
            metadata={
                "before": before.model_dump(),
                "after": normalized.model_dump(),
                "ip": request_ip,
                "user_agent": user_agent,
            },
            ip_address=request_ip,
        )
        return normalized

    @classmethod
    def _normalize_file_sync_rule(
        cls,
        rule: DeveloperTokenFileSyncRule | dict | None,
    ) -> DeveloperTokenFileSyncRule | None:
        if rule is None:
            return None
        try:
            normalized = (
                rule
                if isinstance(rule, DeveloperTokenFileSyncRule)
                else DeveloperTokenFileSyncRule.model_validate(rule)
            )
        except (TypeError, ValidationError) as exc:
            raise DeveloperTokenInvalidFileSyncRuleError(msg="file sync rule structure is invalid") from exc

        domain_fixed = normalized.business_domain.mode == "fixed"
        space_fixed = normalized.target_space.mode == "fixed"
        if domain_fixed != bool(normalized.business_domain.code):
            raise DeveloperTokenInvalidFileSyncRuleError(msg="business domain mode and code do not match")
        if space_fixed != (normalized.target_space.knowledge_id is not None):
            raise DeveloperTokenInvalidFileSyncRuleError(msg="target space mode and knowledge id do not match")
        if not space_fixed and normalized.target_space.folder_id is not None:
            raise DeveloperTokenInvalidFileSyncRuleError(msg="dynamic target cannot specify a folder id")

        has_dynamic_dimension = not domain_fixed or not space_fixed
        if has_dynamic_dimension != (normalized.dynamic_source is not None):
            raise DeveloperTokenInvalidFileSyncRuleError(msg="dynamic source does not match rule modes")
        return normalized

    @classmethod
    async def _validate_file_sync_rule(
        cls,
        tenant_id: int,
        user_id: int,
        rule: DeveloperTokenFileSyncRule | dict | None,
    ) -> dict | None:
        normalized = cls._normalize_file_sync_rule(rule)
        if normalized is None:
            return None

        with cls._target_tenant_context(tenant_id):
            config = await cls._get_file_sync_portal_config(tenant_id)
            if config is None:
                raise DeveloperTokenInvalidFileSyncRuleError(
                    msg="portal categories and business domains must be configured first"
                )

            parent_matches = [
                item
                for item in config.portal.document_types
                if str(getattr(item, "code", "") or "").strip().upper() == normalized.category.code
            ]
            if len(parent_matches) != 1:
                raise DeveloperTokenInvalidFileSyncRuleError(msg="file category is unavailable")
            child_matches = [
                item
                for item in (getattr(parent_matches[0], "children", None) or [])
                if str(getattr(item, "code", "") or "").strip().upper() == normalized.category.subcategory_code
            ]
            if len(child_matches) != 1:
                raise DeveloperTokenInvalidFileSyncRuleError(msg="file subcategory is unavailable")

            fixed_domain = None
            if normalized.business_domain.mode == "fixed":
                fixed_domain_matches = [
                    item
                    for item in config.portal.domains
                    if bool(getattr(item, "enabled", False))
                    and normalize_business_domain_code(getattr(item, "code", None)) == normalized.business_domain.code
                ]
                if len(fixed_domain_matches) != 1:
                    raise DeveloperTokenInvalidFileSyncRuleError(msg="business domain is unavailable")
                fixed_domain = fixed_domain_matches[0]

            fixed_space = None
            if normalized.target_space.mode == "fixed":
                fixed_space = await cls._validate_file_sync_target(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    knowledge_id=int(normalized.target_space.knowledge_id),
                    folder_id=normalized.target_space.folder_id,
                )
                if fixed_space is None:
                    raise DeveloperTokenInvalidFileSyncRuleError(msg="target knowledge space is unavailable")

            if fixed_domain is not None and fixed_space is not None:
                domain_space_ids = {
                    int(space_id) for space_id in (getattr(fixed_domain, "space_ids", None) or []) if int(space_id) > 0
                }
                space_domain_codes = {
                    code
                    for value in (getattr(fixed_space, "business_domain_codes", None) or [])
                    if (code := normalize_business_domain_code(value)) is not None
                }
                if (
                    int(fixed_space.id) not in domain_space_ids
                    or normalized.business_domain.code not in space_domain_codes
                ):
                    raise DeveloperTokenInvalidFileSyncRuleError(
                        msg="business domain and target knowledge space are not bound"
                    )

        return normalized.model_dump(mode="json")

    @classmethod
    async def _get_file_sync_portal_config(cls, tenant_id: int):
        return await ShougangPortalConfigService.get_config(tenant_id=tenant_id)

    @classmethod
    async def _get_file_sync_space(cls, knowledge_id: int):
        return await cls.repository.get_file_sync_space(knowledge_id)

    @classmethod
    async def _get_bound_user_payload(cls, tenant_id: int, user_id: int) -> UserPayload:
        await cls._validate_token_binding(tenant_id, user_id)
        with bypass_tenant_filter():
            user = await UserDao.aget_user(user_id)
            roles = [role.role_id for role in UserRoleDao.get_user_roles(user_id)]
        return UserPayload(
            user_id=user_id,
            user_name=str(getattr(user, "user_name", "") or ""),
            user_role=roles or [0],
            tenant_id=tenant_id,
            token_version=int(getattr(user, "token_version", 0) or 0),
            is_global_super=False,
        )

    @classmethod
    async def _validate_file_sync_target(
        cls,
        *,
        tenant_id: int,
        user_id: int,
        knowledge_id: int,
        folder_id: int | None,
    ):
        with cls._target_tenant_context(tenant_id):
            bound_user = await cls._get_bound_user_payload(tenant_id, user_id)
            try:
                return await KnowledgeSpaceService.validate_file_sync_target(
                    login_user=bound_user,
                    knowledge_id=knowledge_id,
                    folder_id=folder_id,
                )
            except (SpaceNotFoundError, SpaceFolderNotFoundError) as exc:
                raise DeveloperTokenInvalidFileSyncRuleError(msg="file sync target is unavailable") from exc
            except SpacePermissionDeniedError as exc:
                raise DeveloperTokenInvalidFileSyncRuleError(
                    msg="bound user cannot upload to the file sync target"
                ) from exc

    @staticmethod
    @contextmanager
    def _target_tenant_context(tenant_id: int):
        tenant_context_token = set_current_tenant_id(int(tenant_id))
        visible_context_token = set_visible_tenant_ids(frozenset({int(tenant_id)}))
        admin_context_token = set_admin_scope_tenant_id(int(tenant_id))
        try:
            yield
        finally:
            admin_context_token.var.reset(admin_context_token)
            visible_tenant_ids.reset(visible_context_token)
            current_tenant_id.reset(tenant_context_token)

    @classmethod
    async def authenticate(
        cls,
        raw_token: str | None,
        *,
        request_ip: str | None = None,
        user_agent: str | None = None,
        endpoint_key: str | None = None,
        request_method: str | None = None,
        route_path: str | None = None,
    ) -> UserPayload:
        principal = await cls.authenticate_principal(
            raw_token,
            request_ip=request_ip,
            user_agent=user_agent,
            endpoint_key=endpoint_key,
            request_method=request_method,
            route_path=route_path,
        )
        return principal.user

    @classmethod
    async def authenticate_principal(
        cls,
        raw_token: str | None,
        *,
        request_ip: str | None = None,
        user_agent: str | None = None,
        endpoint_key: str | None = None,
        request_method: str | None = None,
        route_path: str | None = None,
    ) -> DeveloperTokenPrincipal:
        if not raw_token:
            raise DeveloperTokenMissingError()

        token = await cls.repository.get_token_by_hash(cls._hash_token(raw_token))
        if token is None:
            raise DeveloperTokenInvalidError()
        if not token.enabled:
            raise DeveloperTokenDisabledError()

        with bypass_tenant_filter():
            tenant = await TenantDao.aget_by_id(token.tenant_id)
            if tenant is None or getattr(tenant, "status", "active") != "active":
                raise DeveloperTokenInvalidError()
            user = await UserDao.aget_user(token.user_id)
            if user is None or int(getattr(user, "delete", 0) or 0) != 0:
                raise DeveloperTokenInvalidError()
            user_tenant = await UserTenantDao.aget_user_tenant(token.user_id, token.tenant_id)
            if user_tenant is None or getattr(user_tenant, "status", "active") != "active":
                raise DeveloperTokenInvalidError()

        effective_ip_whitelist, effective_rate_limit = await cls._effective_controls(token)
        if not cls._ip_allowed(request_ip, effective_ip_whitelist):
            raise DeveloperTokenIpForbiddenError()
        cls._check_route_access(token.route_whitelist, request_method, route_path)
        await cls._check_rate_limit(token.id, effective_rate_limit, endpoint_key=endpoint_key)

        tenant_context_token = set_current_tenant_id(token.tenant_id)
        visible_context_token = set_visible_tenant_ids(frozenset({token.tenant_id}))
        try:
            try:
                await cls.repository.update_last_used(token.id, request_ip)
            except Exception:
                logger.exception("developer token last-used update failed token_id=%s", token.id)

            roles = [role.role_id for role in UserRoleDao.get_user_roles(user.user_id)]
            user_payload = UserPayload(
                user_id=user.user_id,
                user_name=user.user_name,
                user_role=roles or [0],
                tenant_id=token.tenant_id,
                token_version=getattr(user, "token_version", 0) or 0,
                is_global_super=False,
            )
            object.__setattr__(
                user_payload,
                "_developer_token_context_tokens",
                (tenant_context_token, visible_context_token),
            )
            raw_file_sync_rule = (
                dict(token.file_sync_rule)
                if isinstance(token.file_sync_rule, dict)
                else ({"_invalid_stored_rule": True} if token.file_sync_rule is not None else None)
            )
            return DeveloperTokenPrincipal(
                token_id=int(token.id),
                tenant_id=int(token.tenant_id),
                user=user_payload,
                raw_file_sync_rule=raw_file_sync_rule,
            )
        except BaseException:
            visible_tenant_ids.reset(visible_context_token)
            current_tenant_id.reset(tenant_context_token)
            raise

    @staticmethod
    def reset_auth_context(user_payload: UserPayload) -> None:
        tokens = getattr(user_payload, "_developer_token_context_tokens", None)
        if not tokens:
            return
        tenant_context_token, visible_context_token = tokens
        visible_tenant_ids.reset(visible_context_token)
        current_tenant_id.reset(tenant_context_token)

    @classmethod
    async def _resolve_list_tenant(cls, operator: UserPayload, requested_tenant_id: int | None) -> int | None:
        if await cls._is_global_super(operator):
            return requested_tenant_id
        tenant_id = requested_tenant_id or get_current_tenant_id() or operator.tenant_id
        await cls._assert_tenant_admin(operator, tenant_id)
        return tenant_id

    @classmethod
    async def _assert_admin_scope(cls, operator: UserPayload, tenant_id: int) -> None:
        if await cls._is_global_super(operator):
            return
        await cls._assert_tenant_admin(operator, tenant_id)

    @classmethod
    async def _assert_tenant_admin(cls, operator: UserPayload, tenant_id: int) -> None:
        if tenant_id == DEFAULT_TENANT_ID:
            raise DeveloperTokenAdminForbiddenError()
        if await operator.has_tenant_admin(tenant_id):
            return
        raise DeveloperTokenAdminForbiddenError()

    @classmethod
    async def _assert_global_super(cls, operator: UserPayload) -> None:
        if not await cls._is_global_super(operator):
            raise DeveloperTokenAdminForbiddenError()

    @classmethod
    async def _is_global_super(cls, operator: UserPayload) -> bool:
        if getattr(operator, "is_global_super", False):
            return True
        return await _check_is_global_super(operator.user_id)

    @classmethod
    async def _validate_token_binding(cls, tenant_id: int, user_id: int) -> None:
        with bypass_tenant_filter():
            tenant = await TenantDao.aget_by_id(tenant_id)
            if tenant is None or getattr(tenant, "status", "active") != "active":
                raise DeveloperTokenBindingForbiddenError()
            user = await UserDao.aget_user(user_id)
            if user is None or int(getattr(user, "delete", 0) or 0) != 0:
                raise DeveloperTokenBindingForbiddenError()
            user_tenant = await UserTenantDao.aget_user_tenant(user_id, tenant_id)
            if user_tenant is None or getattr(user_tenant, "status", "active") != "active":
                raise DeveloperTokenBindingForbiddenError()

    @classmethod
    async def _resolve_binding_tenant(
        cls,
        user_id: int,
        department_id: int | None,
        dept_id: str | None,
    ) -> int:
        if not user_id or (department_id is None and not (dept_id or "").strip()):
            raise DeveloperTokenBindingForbiddenError()
        with bypass_tenant_filter():
            department = None
            if department_id is not None:
                department = await DepartmentDao.aget_by_id(int(department_id))
            else:
                department = await DepartmentDao.aget_by_dept_id((dept_id or "").strip())
            if department is None or getattr(department, "status", "active") != "active":
                raise DeveloperTokenBindingForbiddenError()

            membership = await UserDepartmentDao.aget_membership(user_id, int(department.id))
            if membership is None:
                raise DeveloperTokenBindingForbiddenError()

            mount_department = await DepartmentDao.aget_ancestors_with_mount(int(department.id))
            tenant_id = int(getattr(mount_department, "mounted_tenant_id", ROOT_TENANT_ID) or ROOT_TENANT_ID)
            if tenant_id <= 0:
                raise DeveloperTokenBindingForbiddenError()

        await cls._validate_token_binding(tenant_id, user_id)
        return tenant_id

    @classmethod
    async def _get_existing_token(cls, token_id: int) -> DeveloperToken:
        token = await cls.repository.get_token_by_id(token_id)
        if token is None:
            raise DeveloperTokenInvalidError()
        return token

    @classmethod
    def _generate_plaintext_token(cls) -> str:
        return f"{cls.TOKEN_PREFIX}{secrets.token_urlsafe(32)}"

    @classmethod
    def _hash_token(cls, plaintext: str) -> str:
        secret = getattr(settings, "jwt_secret", None) or "developer-token"
        return hmac.new(secret.encode("utf-8"), plaintext.encode("utf-8"), hashlib.sha256).hexdigest()

    @staticmethod
    def _encrypt_plaintext(plaintext: str) -> str:
        encrypted = encrypt_token(plaintext)
        return encrypted.decode("utf-8") if isinstance(encrypted, bytes) else encrypted

    @staticmethod
    def _decrypt_plaintext(ciphertext: str) -> str:
        return decrypt_token(ciphertext)

    @classmethod
    async def _read_global_config(cls) -> DeveloperTokenGlobalConfig:
        row = await ConfigDao.aget_config_by_key(cls.CONFIG_KEY)
        if row is None or not row.value:
            return DeveloperTokenGlobalConfig()
        try:
            data = json.loads(row.value)
        except (TypeError, ValueError) as exc:
            logger.exception("developer token global config is invalid JSON")
            raise DeveloperTokenInvalidError() from exc
        return DeveloperTokenGlobalConfig(
            ip_whitelist=data.get("ip_whitelist") or "",
            rate_limit_per_minute=cls._normalize_rate_limit(data.get("rate_limit_per_minute")),
        )

    @classmethod
    async def _effective_controls(cls, token: DeveloperToken) -> tuple[str, int | None]:
        config = await cls._read_global_config()
        ip_whitelist = token.ip_whitelist or "" if token.override_ip_whitelist else config.ip_whitelist
        rate_limit = token.rate_limit_per_minute if token.override_rate_limit else config.rate_limit_per_minute
        return ip_whitelist or "", cls._normalize_rate_limit(rate_limit)

    @classmethod
    async def _check_rate_limit(
        cls,
        token_id: int,
        rate_limit: int | None,
        *,
        endpoint_key: str | None = None,
    ) -> None:
        limit = cls._normalize_rate_limit(rate_limit)
        if limit is None:
            return
        key = cls.RATE_KEY_TEMPLATE.format(
            token_id=token_id,
            endpoint_hash=cls._hash_rate_endpoint(endpoint_key),
            minute=datetime.now(timezone.utc).strftime("%Y%m%d%H%M"),
        )
        try:
            redis = await get_redis_client()
            count = await redis.aincr(key, expiration=70)
        except Exception as exc:
            logger.exception("developer token limiter unavailable token_id=%s", token_id)
            raise DeveloperTokenLimiterUnavailableError() from exc
        if count > limit:
            raise DeveloperTokenRateLimitedError()

    @classmethod
    def _hash_rate_endpoint(cls, endpoint_key: str | None) -> str:
        value = endpoint_key.strip() if isinstance(endpoint_key, str) else ""
        value = value or cls.RATE_ENDPOINT_FALLBACK
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[: cls.RATE_ENDPOINT_HASH_LENGTH]

    @classmethod
    def _validate_rate_limit(cls, value: int | None) -> None:
        if value is not None and value < 0:
            raise DeveloperTokenInvalidRateLimitError()

    @classmethod
    def _normalize_rate_limit(cls, value: int | None) -> int | None:
        if value is None:
            return None
        value = int(value)
        return value if value > 0 else None

    @classmethod
    def _validate_ip_whitelist(cls, value: str | None) -> None:
        for rule in cls._split_ip_rules(value):
            try:
                if "/" in rule:
                    ipaddress.ip_network(rule, strict=False)
                else:
                    ipaddress.ip_address(rule)
            except ValueError as exc:
                raise DeveloperTokenInvalidIpRuleError(msg=f"invalid ip rule: {rule}") from exc

    @classmethod
    def _ip_allowed(cls, request_ip: str | None, whitelist: str | None) -> bool:
        rules = cls._split_ip_rules(whitelist)
        if not rules:
            return True
        if not request_ip:
            return False
        try:
            ip = ipaddress.ip_address(request_ip)
        except ValueError:
            return False
        for rule in rules:
            try:
                if "/" in rule and ip in ipaddress.ip_network(rule, strict=False):
                    return True
                if "/" not in rule and ip == ipaddress.ip_address(rule):
                    return True
            except ValueError:
                return False
        return False

    @staticmethod
    def _split_ip_rules(value: str | None) -> list[str]:
        if not value:
            return []
        return [part.strip() for part in re.split(r"[\s,;]+", value) if part.strip()]

    @classmethod
    def _normalize_route_whitelist(cls, rules: list | None) -> list[dict]:
        if not rules:
            return []
        if len(rules) > cls.MAX_ROUTE_RULES:
            raise DeveloperTokenInvalidRouteRuleError()

        normalized: list[dict] = []
        seen: set[tuple[str, str | None, str]] = set()
        for rule in rules:
            if hasattr(rule, "model_dump"):
                data = rule.model_dump()
            elif isinstance(rule, dict):
                data = rule
            else:
                raise DeveloperTokenInvalidRouteRuleError()

            match_type = str(data.get("match_type") or "").strip().upper()
            path = str(data.get("path") or "").strip()
            raw_method = data.get("method")
            method = str(raw_method).strip().upper() if raw_method is not None else None
            method = method or None

            if match_type not in cls.ROUTE_MATCH_TYPES or not cls._valid_route_path(path):
                raise DeveloperTokenInvalidRouteRuleError()
            if match_type == "METHOD_PATH":
                if method not in cls.ROUTE_METHODS or "*" in path:
                    raise DeveloperTokenInvalidRouteRuleError()
            elif method is not None:
                raise DeveloperTokenInvalidRouteRuleError()
            elif match_type == "PATH" and "*" in path:
                raise DeveloperTokenInvalidRouteRuleError()
            elif match_type == "PREFIX" and (not path.endswith("/*") or path.count("*") != 1):
                raise DeveloperTokenInvalidRouteRuleError()

            key = (match_type, method, path)
            if key in seen:
                raise DeveloperTokenInvalidRouteRuleError()
            seen.add(key)
            normalized.append({"match_type": match_type, "method": method, "path": path})
        return normalized

    @staticmethod
    def _valid_route_path(path: str) -> bool:
        return bool(
            path.startswith("/") and "?" not in path and "#" not in path and not any(char.isspace() for char in path)
        )

    @classmethod
    def _route_allowed(
        cls,
        rules: list[dict] | None,
        request_method: str | None,
        route_path: str | None,
    ) -> bool:
        if not rules:
            return True
        if not request_method or not route_path:
            return False

        method = request_method.upper()
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            match_type = rule.get("match_type")
            rule_path = rule.get("path")
            if match_type == "METHOD_PATH" and rule.get("method") == method and rule_path == route_path:
                return True
            if match_type == "PATH" and rule_path == route_path:
                return True
            if match_type == "PREFIX" and isinstance(rule_path, str):
                prefix = rule_path[:-1]
                if rule_path.endswith("/*") and route_path.startswith(prefix):
                    return True
        return False

    @classmethod
    def _check_route_access(
        cls,
        rules: list[dict] | None,
        request_method: str | None,
        route_path: str | None,
    ) -> None:
        if not cls._route_allowed(rules, request_method, route_path):
            raise DeveloperTokenRouteForbiddenError()

    @classmethod
    async def _build_file_sync_target_displays(
        cls,
        tokens: list[DeveloperToken],
    ) -> dict[int, FileSyncTargetDisplay]:
        targets_by_tenant: dict[int, dict[int, tuple[int, int | None]]] = {}
        for token in tokens:
            if token.id is None or token.file_sync_rule is None:
                continue
            try:
                rule = cls._normalize_file_sync_rule(token.file_sync_rule)
            except DeveloperTokenInvalidFileSyncRuleError:
                continue
            if rule is None or rule.target_space.mode != "fixed":
                continue
            targets_by_tenant.setdefault(int(token.tenant_id), {})[int(token.id)] = (
                int(rule.target_space.knowledge_id),
                rule.target_space.folder_id,
            )

        result: dict[int, FileSyncTargetDisplay] = {}
        for tenant_id, targets in targets_by_tenant.items():
            with cls._target_tenant_context(tenant_id):
                displays = await KnowledgeSpaceService.resolve_file_sync_target_displays(targets)
            for token_id, display in displays.items():
                result[token_id] = FileSyncTargetDisplay(
                    knowledge_id=display.knowledge_id,
                    knowledge_name=display.knowledge_name,
                    target_type="folder" if display.folder_id is not None else "root",
                    folder_id=display.folder_id,
                    folder_path=[
                        FileSyncTargetPathItem(id=folder_id, name=name) for folder_id, name in display.folder_path
                    ],
                    stale=display.stale,
                )
        return result

    @classmethod
    async def _to_read(
        cls,
        token: DeveloperToken,
        *,
        file_sync_target_display: FileSyncTargetDisplay | None = None,
    ) -> DeveloperTokenRead:
        tenant_name = None
        user_name = None
        try:
            tenant = await TenantDao.aget_by_id(token.tenant_id)
            tenant_name = getattr(tenant, "tenant_name", None) if tenant else None
        except Exception:
            logger.exception("developer token tenant enrichment failed token_id=%s", token.id)
        try:
            user = await UserDao.aget_user(token.user_id)
            user_name = getattr(user, "user_name", None) if user else None
        except Exception:
            logger.exception("developer token user enrichment failed token_id=%s", token.id)
        file_sync_rule = None
        if token.file_sync_rule is not None:
            try:
                file_sync_rule = cls._normalize_file_sync_rule(token.file_sync_rule)
            except DeveloperTokenInvalidFileSyncRuleError:
                logger.warning("developer token has invalid file sync rule token_id=%s", token.id)
        return DeveloperTokenRead(
            id=token.id,
            tenant_id=token.tenant_id,
            tenant_name=tenant_name,
            user_id=token.user_id,
            user_name=user_name,
            name=token.name,
            token_prefix=token.token_prefix,
            enabled=bool(token.enabled),
            override_ip_whitelist=bool(token.override_ip_whitelist),
            override_rate_limit=bool(token.override_rate_limit),
            rate_limit_per_minute=token.rate_limit_per_minute,
            route_rule_count=len(token.route_whitelist or []),
            file_sync_rule=file_sync_rule,
            file_sync_target_display=file_sync_target_display,
            last_used_time=token.last_used_time,
            last_used_ip=token.last_used_ip,
            created_by=token.created_by,
            updated_by=token.updated_by,
            create_time=token.create_time,
            update_time=token.update_time,
        )

    @classmethod
    async def _to_detail(
        cls,
        token: DeveloperToken,
        *,
        file_sync_target_display: FileSyncTargetDisplay | None = None,
    ) -> DeveloperTokenDetail:
        data = (
            await cls._to_read(
                token,
                file_sync_target_display=file_sync_target_display,
            )
        ).model_dump()
        data["ip_whitelist"] = token.ip_whitelist
        data["route_whitelist"] = token.route_whitelist or []
        return DeveloperTokenDetail(**data)

    @staticmethod
    def _non_secret_snapshot(token: DeveloperToken) -> dict:
        rule_summary = DeveloperTokenService._file_sync_rule_summary(token.file_sync_rule)
        return {
            "id": token.id,
            "tenant_id": token.tenant_id,
            "user_id": token.user_id,
            "name": token.name,
            "token_prefix": token.token_prefix,
            "enabled": bool(token.enabled),
            "override_ip_whitelist": bool(token.override_ip_whitelist),
            "ip_whitelist_rule_count": len(DeveloperTokenService._split_ip_rules(token.ip_whitelist)),
            "override_rate_limit": bool(token.override_rate_limit),
            "rate_limit_per_minute": token.rate_limit_per_minute,
            "route_rule_count": len(token.route_whitelist or []),
            "file_sync_rule_configured": token.file_sync_rule is not None,
            "file_sync_rule_summary": rule_summary,
            "logic_delete": token.logic_delete,
        }

    @staticmethod
    def _file_sync_rule_summary(rule: dict | DeveloperTokenFileSyncRule | None) -> dict | None:
        if rule is None:
            return None
        try:
            normalized = DeveloperTokenService._normalize_file_sync_rule(rule)
        except DeveloperTokenInvalidFileSyncRuleError:
            return {"invalid": True}
        return {
            "category_code": normalized.category.code,
            "subcategory_code": normalized.category.subcategory_code,
            "business_domain_mode": normalized.business_domain.mode,
            "target_space_mode": normalized.target_space.mode,
            "dynamic_source": normalized.dynamic_source,
        }

    @classmethod
    async def _audit(
        cls,
        action: str,
        operator: UserPayload,
        token: DeveloperToken,
        *,
        request_ip: str | None,
        user_agent: str | None,
        metadata: dict | None = None,
    ) -> None:
        payload = dict(metadata or {})
        payload.update(
            {
                "token_id": token.id,
                "prefix": token.token_prefix,
                "tenant_id": token.tenant_id,
                "user_id": token.user_id,
                "operator_id": operator.user_id,
                "ip": request_ip,
                "user_agent": user_agent,
            }
        )
        await AuditLogDao.ainsert_v2(
            tenant_id=token.tenant_id,
            operator_id=operator.user_id,
            operator_tenant_id=get_current_tenant_id() or ROOT_TENANT_ID,
            action=action,
            target_type="developer_token",
            target_id=str(token.id),
            metadata=payload,
            ip_address=request_ip,
            object_name=token.name,
        )
