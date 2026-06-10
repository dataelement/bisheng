from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.developer_token import (
    DeveloperTokenAdminForbiddenError,
    DeveloperTokenBindingForbiddenError,
    DeveloperTokenInvalidIpRuleError,
    DeveloperTokenInvalidRateLimitError,
)
from bisheng.developer_token.domain.models import DeveloperToken
from bisheng.developer_token.domain.schemas import (
    DeveloperTokenCreate,
    DeveloperTokenGlobalConfig,
    DeveloperTokenRead,
    DeveloperTokenUpdate,
)
from bisheng.developer_token.domain.services.developer_token_service import DeveloperTokenService


class _Operator:
    user_id = 10
    user_name = "operator"
    tenant_id = 5
    is_global_super = False

    def __init__(self, tenant_admin: bool = True, global_super: bool = False):
        self.is_global_super = global_super
        self.tenant_admin = tenant_admin

    async def has_tenant_admin(self, tenant_id: int):
        return self.tenant_admin and tenant_id == 5


def _token(**kwargs):
    data = {
        "id": 1,
        "tenant_id": 5,
        "user_id": 7,
        "name": "api",
        "token_hash": "hash",
        "token_ciphertext": DeveloperTokenService._encrypt_plaintext("bst_secret"),
        "token_prefix": "bst_secret"[:12],
        "enabled": True,
        "override_ip_whitelist": False,
        "ip_whitelist": "",
        "override_rate_limit": False,
        "rate_limit_per_minute": None,
        "logic_delete": 0,
    }
    data.update(kwargs)
    return DeveloperToken(**data)


def _read(row: DeveloperToken):
    return DeveloperTokenRead(
        id=row.id,
        tenant_id=row.tenant_id,
        user_id=row.user_id,
        name=row.name,
        token_prefix=row.token_prefix,
        enabled=row.enabled,
        override_ip_whitelist=row.override_ip_whitelist,
        override_rate_limit=row.override_rate_limit,
        rate_limit_per_minute=row.rate_limit_per_minute,
    )


@pytest.mark.asyncio
async def test_create_token_returns_secret_once(monkeypatch):
    created = {}

    class Repo:
        @staticmethod
        async def create_token(row):
            row.id = 1
            created["row"] = row
            return row

    monkeypatch.setattr(DeveloperTokenService, "repository", Repo)
    monkeypatch.setattr(DeveloperTokenService, "_resolve_binding_tenant", AsyncMock(return_value=5))
    monkeypatch.setattr(DeveloperTokenService, "_to_read", AsyncMock(side_effect=_read))
    monkeypatch.setattr(
        "bisheng.developer_token.domain.services.developer_token_service.AuditLogDao",
        SimpleNamespace(ainsert_v2=AsyncMock()),
    )

    result = await DeveloperTokenService.create_token(
        _Operator(),
        DeveloperTokenCreate(name="api", user_id=7, department_id=20),
    )

    assert result.plaintext_token.startswith("bst_")
    assert result.token.token_prefix == result.plaintext_token[:12]
    assert created["row"].token_hash != result.plaintext_token
    assert created["row"].token_ciphertext != result.plaintext_token
    assert DeveloperTokenService._decrypt_plaintext(created["row"].token_ciphertext) == result.plaintext_token


@pytest.mark.asyncio
async def test_tenant_admin_cannot_bind_cross_tenant_user(monkeypatch):
    monkeypatch.setattr(DeveloperTokenService, "_resolve_binding_tenant", AsyncMock(return_value=8))

    with pytest.raises(DeveloperTokenAdminForbiddenError):
        await DeveloperTokenService.create_token(
            _Operator(tenant_admin=False),
            DeveloperTokenCreate(name="api", user_id=7, department_id=80),
        )


@pytest.mark.asyncio
async def test_selected_department_resolves_token_tenant(monkeypatch):
    monkeypatch.setattr(
        "bisheng.developer_token.domain.services.developer_token_service.DepartmentDao",
        SimpleNamespace(
            aget_by_id=AsyncMock(return_value=SimpleNamespace(id=20, status="active")),
            aget_ancestors_with_mount=AsyncMock(return_value=SimpleNamespace(mounted_tenant_id=5)),
        ),
    )
    monkeypatch.setattr(
        "bisheng.developer_token.domain.services.developer_token_service.UserDepartmentDao",
        SimpleNamespace(aget_membership=AsyncMock(return_value=SimpleNamespace(user_id=7, department_id=20))),
    )
    monkeypatch.setattr(
        "bisheng.developer_token.domain.services.developer_token_service.TenantDao",
        SimpleNamespace(aget_by_id=AsyncMock(return_value=SimpleNamespace(id=5, status="active"))),
    )
    monkeypatch.setattr(
        "bisheng.developer_token.domain.services.developer_token_service.UserDao",
        SimpleNamespace(aget_user=AsyncMock(return_value=SimpleNamespace(user_id=7, delete=0))),
    )
    monkeypatch.setattr(
        "bisheng.developer_token.domain.services.developer_token_service.UserTenantDao",
        SimpleNamespace(aget_user_tenant=AsyncMock(return_value=SimpleNamespace(status="active"))),
    )

    tenant_id = await DeveloperTokenService._resolve_binding_tenant(7, 20, None)

    assert tenant_id == 5


@pytest.mark.asyncio
async def test_selected_department_must_contain_selected_user(monkeypatch):
    monkeypatch.setattr(
        "bisheng.developer_token.domain.services.developer_token_service.DepartmentDao",
        SimpleNamespace(aget_by_id=AsyncMock(return_value=SimpleNamespace(id=20, status="active"))),
    )
    monkeypatch.setattr(
        "bisheng.developer_token.domain.services.developer_token_service.UserDepartmentDao",
        SimpleNamespace(aget_membership=AsyncMock(return_value=None)),
    )

    with pytest.raises(DeveloperTokenBindingForbiddenError):
        await DeveloperTokenService._resolve_binding_tenant(7, 20, None)


@pytest.mark.asyncio
async def test_selected_department_requires_active_tenant(monkeypatch):
    monkeypatch.setattr(
        "bisheng.developer_token.domain.services.developer_token_service.DepartmentDao",
        SimpleNamespace(
            aget_by_id=AsyncMock(return_value=SimpleNamespace(id=20, status="active")),
            aget_ancestors_with_mount=AsyncMock(return_value=SimpleNamespace(mounted_tenant_id=5)),
        ),
    )
    monkeypatch.setattr(
        "bisheng.developer_token.domain.services.developer_token_service.UserDepartmentDao",
        SimpleNamespace(aget_membership=AsyncMock(return_value=SimpleNamespace(user_id=7, department_id=20))),
    )
    monkeypatch.setattr(
        "bisheng.developer_token.domain.services.developer_token_service.TenantDao",
        SimpleNamespace(aget_by_id=AsyncMock(return_value=SimpleNamespace(id=5, status="disabled"))),
    )

    with pytest.raises(DeveloperTokenBindingForbiddenError):
        await DeveloperTokenService._resolve_binding_tenant(7, 20, None)


@pytest.mark.asyncio
async def test_update_token_rebinds_from_selected_department(monkeypatch):
    existing = _token()
    updated_fields = {}

    class Repo:
        @staticmethod
        async def get_token_by_id(token_id):
            return existing

        @staticmethod
        async def update_token(token_id, **fields):
            updated_fields.update(fields)
            return _token(tenant_id=fields["tenant_id"], user_id=fields["user_id"])

    monkeypatch.setattr(DeveloperTokenService, "repository", Repo)
    monkeypatch.setattr(DeveloperTokenService, "_resolve_binding_tenant", AsyncMock(return_value=5))
    monkeypatch.setattr(DeveloperTokenService, "_to_read", AsyncMock(side_effect=_read))
    monkeypatch.setattr(
        "bisheng.developer_token.domain.services.developer_token_service.AuditLogDao",
        SimpleNamespace(ainsert_v2=AsyncMock()),
    )

    await DeveloperTokenService.update_token(
        1,
        _Operator(),
        DeveloperTokenUpdate(user_id=8, department_id=22),
    )

    assert updated_fields["tenant_id"] == 5
    assert updated_fields["user_id"] == 8
    assert "department_id" not in updated_fields


def test_invalid_ip_rule_is_rejected():
    with pytest.raises(DeveloperTokenInvalidIpRuleError):
        DeveloperTokenService._validate_ip_whitelist("10.0.0.1\nnot-an-ip")


def test_negative_rate_limit_has_dedicated_error():
    with pytest.raises(DeveloperTokenInvalidRateLimitError):
        DeveloperTokenService._validate_rate_limit(-1)


@pytest.mark.asyncio
async def test_missing_global_config_returns_defaults(monkeypatch):
    monkeypatch.setattr(
        "bisheng.developer_token.domain.services.developer_token_service.ConfigDao",
        SimpleNamespace(aget_config_by_key=AsyncMock(return_value=None)),
    )

    result = await DeveloperTokenService._read_global_config()

    assert result.ip_whitelist == ""
    assert result.rate_limit_per_minute is None


@pytest.mark.asyncio
async def test_token_override_rules_take_precedence(monkeypatch):
    monkeypatch.setattr(
        DeveloperTokenService,
        "_read_global_config",
        AsyncMock(return_value=DeveloperTokenGlobalConfig(ip_whitelist="10.0.0.1", rate_limit_per_minute=30)),
    )

    ip_rules, rate = await DeveloperTokenService._effective_controls(
        _token(
            override_ip_whitelist=True,
            ip_whitelist="192.168.1.0/24",
            override_rate_limit=True,
            rate_limit_per_minute=0,
        )
    )

    assert ip_rules == "192.168.1.0/24"
    assert rate is None


@pytest.mark.asyncio
async def test_global_config_update_writes_audit_log(monkeypatch):
    audit = SimpleNamespace(ainsert_v2=AsyncMock())
    saved = {}

    async def _save(key, value):
        saved["key"] = key
        saved["value"] = value
        return SimpleNamespace(key=key, value=value)

    monkeypatch.setattr(
        "bisheng.developer_token.domain.services.developer_token_service.ConfigDao",
        SimpleNamespace(
            aget_config_by_key=AsyncMock(return_value=None),
            insert_or_update_config=AsyncMock(side_effect=_save),
        ),
    )
    monkeypatch.setattr(
        "bisheng.developer_token.domain.services.developer_token_service.AuditLogDao",
        audit,
    )

    result = await DeveloperTokenService.update_global_config(
        _Operator(global_super=True),
        DeveloperTokenGlobalConfig(ip_whitelist="10.0.0.0/24", rate_limit_per_minute=10),
    )

    assert result.rate_limit_per_minute == 10
    assert json.loads(saved["value"])["ip_whitelist"] == "10.0.0.0/24"
    audit.ainsert_v2.assert_awaited_once()
