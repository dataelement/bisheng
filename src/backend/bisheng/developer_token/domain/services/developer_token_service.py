from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import re
import secrets
from datetime import datetime, timezone

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.developer_token import (
    DeveloperTokenAdminForbiddenError,
    DeveloperTokenBindingForbiddenError,
    DeveloperTokenDisabledError,
    DeveloperTokenInvalidError,
    DeveloperTokenInvalidIpRuleError,
    DeveloperTokenInvalidRateLimitError,
    DeveloperTokenIpForbiddenError,
    DeveloperTokenLimiterUnavailableError,
    DeveloperTokenMissingError,
    DeveloperTokenRateLimitedError,
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
    DeveloperTokenGlobalConfig,
    DeveloperTokenListQuery,
    DeveloperTokenRead,
    DeveloperTokenSecretResponse,
    DeveloperTokenUpdate,
)
from bisheng.user.domain.models.user import UserDao
from bisheng.user.domain.models.user_role import UserRoleDao
from bisheng.utils.http_middleware import _check_is_global_super

logger = logging.getLogger(__name__)


class DeveloperTokenService:
    CONFIG_KEY = "developer_token_global_config"
    RATE_KEY_TEMPLATE = "developer_token:rate:{token_id}:{minute}"
    TOKEN_PREFIX = "bst_"
    TOKEN_PREFIX_DISPLAY_LENGTH = 12

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
        return PageData(data=[await cls._to_read(row) for row in rows], total=total)

    @classmethod
    async def get_token_detail(cls, token_id: int, operator: UserPayload) -> DeveloperTokenDetail:
        token = await cls._get_existing_token(token_id)
        await cls._assert_admin_scope(operator, token.tenant_id)
        return await cls._to_detail(token)

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

        if "ip_whitelist" in update_data:
            cls._validate_ip_whitelist(update_data.get("ip_whitelist"))
        if "rate_limit_per_minute" in update_data:
            cls._validate_rate_limit(update_data.get("rate_limit_per_minute"))
            update_data["rate_limit_per_minute"] = cls._normalize_rate_limit(update_data.get("rate_limit_per_minute"))
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
    async def authenticate(
        cls,
        raw_token: str | None,
        *,
        request_ip: str | None = None,
        user_agent: str | None = None,
    ) -> UserPayload:
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
        await cls._check_rate_limit(token.id, effective_rate_limit)

        tenant_context_token = set_current_tenant_id(token.tenant_id)
        visible_context_token = set_visible_tenant_ids(frozenset({token.tenant_id}))

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
        return user_payload

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
    async def _check_rate_limit(cls, token_id: int, rate_limit: int | None) -> None:
        limit = cls._normalize_rate_limit(rate_limit)
        if limit is None:
            return
        key = cls.RATE_KEY_TEMPLATE.format(
            token_id=token_id,
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
    async def _to_read(cls, token: DeveloperToken) -> DeveloperTokenRead:
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
            last_used_time=token.last_used_time,
            last_used_ip=token.last_used_ip,
            created_by=token.created_by,
            updated_by=token.updated_by,
            create_time=token.create_time,
            update_time=token.update_time,
        )

    @classmethod
    async def _to_detail(cls, token: DeveloperToken) -> DeveloperTokenDetail:
        data = (await cls._to_read(token)).model_dump()
        data["ip_whitelist"] = token.ip_whitelist
        return DeveloperTokenDetail(**data)

    @staticmethod
    def _non_secret_snapshot(token: DeveloperToken) -> dict:
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
            "logic_delete": token.logic_delete,
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
