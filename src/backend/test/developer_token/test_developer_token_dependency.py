from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.developer_token import (
    DeveloperTokenDisabledError,
    DeveloperTokenInvalidError,
    DeveloperTokenLimiterUnavailableError,
    DeveloperTokenMissingError,
    DeveloperTokenRateLimitedError,
    DeveloperTokenRouteForbiddenError,
)
from bisheng.common.errcode.filelib_sync import FilelibSyncRuleNotConfiguredError
from bisheng.developer_token.api.dependencies import (
    _get_developer_token_endpoint_key,
    _get_developer_token_route,
    get_developer_token_principal,
    get_developer_token_user,
)
from bisheng.developer_token.domain.models import DeveloperToken
from bisheng.developer_token.domain.schemas import DeveloperTokenPrincipal
from bisheng.developer_token.domain.services.developer_token_service import DeveloperTokenService
from bisheng.open_endpoints.api.dependencies import get_filelib_sync_principal


def _active_token(**kwargs):
    data = {
        "id": 2,
        "tenant_id": 5,
        "user_id": 7,
        "name": "api",
        "token_hash": "hash",
        "token_ciphertext": "cipher",
        "token_prefix": "bst_abc",
        "enabled": True,
        "override_ip_whitelist": False,
        "ip_whitelist": "",
        "override_rate_limit": False,
        "rate_limit_per_minute": None,
        "route_whitelist": None,
        "logic_delete": 0,
    }
    data.update(kwargs)
    return DeveloperToken(**data)


class _Redis:
    def __init__(self, count=1, error: Exception | None = None):
        self.count = count
        self.error = error
        self.calls = []

    async def aincr(self, key, expiration=3600):
        if self.error:
            raise self.error
        self.calls.append((key, expiration))
        return self.count


class _CountingRedis:
    def __init__(self):
        self.counts = {}
        self.calls = []

    async def aincr(self, key, expiration=3600):
        self.counts[key] = self.counts.get(key, 0) + 1
        self.calls.append((key, expiration))
        return self.counts[key]


@pytest.mark.asyncio
async def test_missing_header_is_rejected():
    with pytest.raises(DeveloperTokenMissingError):
        await DeveloperTokenService.authenticate(None, request_ip="10.0.0.1")


@pytest.mark.asyncio
async def test_unknown_token_is_rejected(monkeypatch):
    class Repo:
        @staticmethod
        async def get_token_by_hash(token_hash):
            return None

    monkeypatch.setattr(DeveloperTokenService, "repository", Repo)

    with pytest.raises(DeveloperTokenInvalidError):
        await DeveloperTokenService.authenticate("bst_unknown", request_ip="10.0.0.1")


@pytest.mark.asyncio
async def test_disabled_token_is_rejected(monkeypatch):
    class Repo:
        @staticmethod
        async def get_token_by_hash(token_hash):
            return _active_token(enabled=False)

    monkeypatch.setattr(DeveloperTokenService, "repository", Repo)

    with pytest.raises(DeveloperTokenDisabledError):
        await DeveloperTokenService.authenticate("bst_disabled", request_ip="10.0.0.1")


def test_ip_whitelist_matching():
    assert DeveloperTokenService._ip_allowed("10.0.0.1", "10.0.0.1")
    assert DeveloperTokenService._ip_allowed("10.0.0.5", "10.0.0.0/24")
    assert not DeveloperTokenService._ip_allowed("10.0.1.5", "10.0.0.0/24")
    mixed_rules = "10.0.0.1\n10.0.0.2,192.168.1.0/24;172.16.0.1"
    assert DeveloperTokenService._ip_allowed("10.0.0.2", mixed_rules)
    assert DeveloperTokenService._ip_allowed("192.168.1.25", mixed_rules)
    assert DeveloperTokenService._ip_allowed("172.16.0.1", mixed_rules)
    assert not DeveloperTokenService._ip_allowed("172.16.0.2", mixed_rules)


@pytest.mark.asyncio
async def test_rate_limit_exceeded_is_rejected(monkeypatch):
    redis = _Redis(count=3)
    monkeypatch.setattr(
        "bisheng.developer_token.domain.services.developer_token_service.get_redis_client",
        AsyncMock(return_value=redis),
    )

    with pytest.raises(DeveloperTokenRateLimitedError):
        await DeveloperTokenService._check_rate_limit(
            2,
            2,
            endpoint_key="POST /api/v2/filelib/retrieve",
        )

    endpoint_hash = DeveloperTokenService._hash_rate_endpoint("POST /api/v2/filelib/retrieve")
    assert redis.calls[0][0].startswith(f"developer_token:rate:2:{endpoint_hash}:")
    assert redis.calls[0][1] == 70


@pytest.mark.asyncio
async def test_rate_limit_is_isolated_by_endpoint_for_same_token(monkeypatch):
    redis = _CountingRedis()
    monkeypatch.setattr(
        "bisheng.developer_token.domain.services.developer_token_service.get_redis_client",
        AsyncMock(return_value=redis),
    )

    await DeveloperTokenService._check_rate_limit(2, 1, endpoint_key="POST /api/v2/filelib/retrieve")
    await DeveloperTokenService._check_rate_limit(2, 1, endpoint_key="GET /api/v2/filelib/file/list")

    keys = [call[0] for call in redis.calls]
    assert len(keys) == 2
    assert len(set(keys)) == 2
    assert all(redis.counts[key] == 1 for key in keys)


@pytest.mark.asyncio
async def test_rate_limit_is_isolated_by_token_for_same_endpoint(monkeypatch):
    redis = _CountingRedis()
    monkeypatch.setattr(
        "bisheng.developer_token.domain.services.developer_token_service.get_redis_client",
        AsyncMock(return_value=redis),
    )

    await DeveloperTokenService._check_rate_limit(2, 1, endpoint_key="POST /api/v2/filelib/retrieve")
    await DeveloperTokenService._check_rate_limit(3, 1, endpoint_key="POST /api/v2/filelib/retrieve")

    keys = [call[0] for call in redis.calls]
    assert len(keys) == 2
    assert len(set(keys)) == 2
    assert keys[0].split(":")[2] == "2"
    assert keys[1].split(":")[2] == "3"


@pytest.mark.asyncio
async def test_unlimited_rate_limit_skips_redis(monkeypatch):
    get_redis = AsyncMock()
    monkeypatch.setattr(
        "bisheng.developer_token.domain.services.developer_token_service.get_redis_client",
        get_redis,
    )

    await DeveloperTokenService._check_rate_limit(2, None, endpoint_key="POST /api/v2/filelib/retrieve")
    await DeveloperTokenService._check_rate_limit(2, 0, endpoint_key="POST /api/v2/filelib/retrieve")

    get_redis.assert_not_awaited()


def test_endpoint_key_uses_route_template_instead_of_concrete_path():
    request = SimpleNamespace(
        method="get",
        scope={
            "route": SimpleNamespace(path="/api/v2/filelib/file/{file_id}"),
            "path": "/api/v2/filelib/file/345",
        },
        url=SimpleNamespace(path="/api/v2/filelib/file/345"),
    )

    assert _get_developer_token_endpoint_key(request) == "GET /api/v2/filelib/file/{file_id}"


def test_route_context_uses_fastapi_template_and_method():
    request = SimpleNamespace(
        method="post",
        scope={
            "route": SimpleNamespace(path="/api/v1/items/{item_id}"),
            "path": "/api/v1/items/42",
        },
    )

    assert _get_developer_token_route(request) == ("POST", "/api/v1/items/{item_id}")


def test_route_context_does_not_fallback_to_concrete_path():
    request = SimpleNamespace(method="GET", scope={"path": "/api/v1/items/42"})

    assert _get_developer_token_route(request) == ("GET", None)


def test_empty_route_whitelist_allows_all_opted_in_routes():
    assert DeveloperTokenService._route_allowed(None, "GET", "/api/v1/items")
    assert DeveloperTokenService._route_allowed([], "POST", "/api/v1/items")


def test_method_path_and_path_rules_match_route_templates():
    method_rule = [{"match_type": "METHOD_PATH", "method": "GET", "path": "/api/v1/items/{item_id}"}]
    path_rule = [{"match_type": "PATH", "method": None, "path": "/api/v1/health"}]

    assert DeveloperTokenService._route_allowed(method_rule, "GET", "/api/v1/items/{item_id}")
    assert not DeveloperTokenService._route_allowed(method_rule, "POST", "/api/v1/items/{item_id}")
    assert DeveloperTokenService._route_allowed(path_rule, "GET", "/api/v1/health")
    assert DeveloperTokenService._route_allowed(path_rule, "POST", "/api/v1/health")
    assert not DeveloperTokenService._route_allowed(method_rule, "GET", "/api/v1/items/42")


def test_prefix_rule_matches_descendants_only():
    rules = [{"match_type": "PREFIX", "method": None, "path": "/api/v1/files/*"}]

    assert DeveloperTokenService._route_allowed(rules, "GET", "/api/v1/files/42")
    assert DeveloperTokenService._route_allowed(rules, "POST", "/api/v1/files/{file_id}/content")
    assert not DeveloperTokenService._route_allowed(rules, "GET", "/api/v1/files")
    assert not DeveloperTokenService._route_allowed(rules, "GET", "/api/v1/files-extra")


def test_multiple_route_rules_are_or_composed():
    rules = [
        {"match_type": "METHOD_PATH", "method": "POST", "path": "/api/v1/items"},
        {"match_type": "PATH", "method": None, "path": "/api/v1/health"},
    ]

    assert DeveloperTokenService._route_allowed(rules, "GET", "/api/v1/health")
    assert not DeveloperTokenService._route_allowed(rules, "GET", "/api/v1/items")


def test_nonempty_route_whitelist_fails_closed_without_route_template():
    rules = [{"match_type": "PATH", "method": None, "path": "/api/v1/items"}]

    assert not DeveloperTokenService._route_allowed(rules, "GET", None)
    with pytest.raises(DeveloperTokenRouteForbiddenError):
        DeveloperTokenService._check_route_access(rules, "GET", None)


@pytest.mark.asyncio
async def test_route_miss_is_rejected_before_rate_limit(monkeypatch):
    raw = "bst_route_miss"
    token = _active_token(
        token_hash=DeveloperTokenService._hash_token(raw),
        route_whitelist=[{"match_type": "METHOD_PATH", "method": "GET", "path": "/api/v1/items"}],
    )

    class Repo:
        @staticmethod
        async def get_token_by_hash(token_hash):
            return token

    limiter = AsyncMock()
    monkeypatch.setattr(DeveloperTokenService, "repository", Repo)
    monkeypatch.setattr(DeveloperTokenService, "_effective_controls", AsyncMock(return_value=("", 10)))
    monkeypatch.setattr(DeveloperTokenService, "_check_rate_limit", limiter)
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

    with pytest.raises(DeveloperTokenRouteForbiddenError):
        await DeveloperTokenService.authenticate(
            raw,
            request_ip="10.0.0.1",
            request_method="POST",
            route_path="/api/v1/items",
        )

    limiter.assert_not_awaited()


@pytest.mark.asyncio
async def test_redis_error_fails_closed(monkeypatch):
    monkeypatch.setattr(
        "bisheng.developer_token.domain.services.developer_token_service.get_redis_client",
        AsyncMock(return_value=_Redis(error=RuntimeError("down"))),
    )

    with pytest.raises(DeveloperTokenLimiterUnavailableError):
        await DeveloperTokenService._check_rate_limit(
            2,
            2,
            endpoint_key="POST /api/v2/filelib/retrieve",
        )


@pytest.mark.asyncio
async def test_auth_sets_constrained_tenant_context(monkeypatch):
    raw = "bst_success"
    token = _active_token(token_hash=DeveloperTokenService._hash_token(raw))

    class Repo:
        @staticmethod
        async def get_token_by_hash(token_hash):
            return token

        @staticmethod
        async def update_last_used(token_id, ip_address):
            return True

    monkeypatch.setattr(DeveloperTokenService, "repository", Repo)
    monkeypatch.setattr(
        DeveloperTokenService,
        "_read_global_config",
        AsyncMock(
            return_value=SimpleNamespace(
                ip_whitelist="",
                rate_limit_per_minute=None,
            )
        ),
    )
    monkeypatch.setattr(
        "bisheng.developer_token.domain.services.developer_token_service.TenantDao",
        SimpleNamespace(aget_by_id=AsyncMock(return_value=SimpleNamespace(id=5, status="active"))),
    )
    monkeypatch.setattr(
        "bisheng.developer_token.domain.services.developer_token_service.UserDao",
        SimpleNamespace(
            aget_user=AsyncMock(
                return_value=SimpleNamespace(
                    user_id=7,
                    user_name="bound",
                    delete=0,
                    token_version=1,
                )
            )
        ),
    )
    monkeypatch.setattr(
        "bisheng.developer_token.domain.services.developer_token_service.UserTenantDao",
        SimpleNamespace(aget_user_tenant=AsyncMock(return_value=SimpleNamespace(status="active"))),
    )
    monkeypatch.setattr(
        "bisheng.developer_token.domain.services.developer_token_service.UserRoleDao",
        SimpleNamespace(get_user_roles=lambda user_id: [SimpleNamespace(role_id=2)]),
    )

    user = await DeveloperTokenService.authenticate(raw, request_ip="10.0.0.1")

    from bisheng.core.context.tenant import get_current_tenant_id, get_visible_tenant_ids

    assert user.user_id == 7
    assert user.tenant_id == 5
    assert user.is_global_super is False
    assert get_current_tenant_id() == 5
    assert get_visible_tenant_ids() == frozenset({5})
    DeveloperTokenService.reset_auth_context(user)
    assert get_current_tenant_id() is None
    assert get_visible_tenant_ids() is None


@pytest.mark.asyncio
async def test_disabled_bound_user_is_rejected(monkeypatch):
    raw = "bst_disabled_user"
    token = _active_token(token_hash=DeveloperTokenService._hash_token(raw))

    class Repo:
        @staticmethod
        async def get_token_by_hash(token_hash):
            return token

    monkeypatch.setattr(DeveloperTokenService, "repository", Repo)
    monkeypatch.setattr(
        "bisheng.developer_token.domain.services.developer_token_service.TenantDao",
        SimpleNamespace(aget_by_id=AsyncMock(return_value=SimpleNamespace(id=5, status="active"))),
    )
    monkeypatch.setattr(
        "bisheng.developer_token.domain.services.developer_token_service.UserDao",
        SimpleNamespace(aget_user=AsyncMock(return_value=SimpleNamespace(user_id=7, delete=1))),
    )

    with pytest.raises(DeveloperTokenInvalidError):
        await DeveloperTokenService.authenticate(raw, request_ip="10.0.0.1")


@pytest.mark.asyncio
async def test_invalid_bound_tenant_is_rejected(monkeypatch):
    raw = "bst_invalid_tenant"
    token = _active_token(token_hash=DeveloperTokenService._hash_token(raw))

    class Repo:
        @staticmethod
        async def get_token_by_hash(token_hash):
            return token

    monkeypatch.setattr(DeveloperTokenService, "repository", Repo)
    monkeypatch.setattr(
        "bisheng.developer_token.domain.services.developer_token_service.TenantDao",
        SimpleNamespace(aget_by_id=AsyncMock(return_value=SimpleNamespace(id=5, status="disabled"))),
    )

    with pytest.raises(DeveloperTokenInvalidError):
        await DeveloperTokenService.authenticate(raw, request_ip="10.0.0.1")


@pytest.mark.asyncio
async def test_inactive_user_tenant_binding_is_rejected(monkeypatch):
    raw = "bst_inactive_binding"
    token = _active_token(token_hash=DeveloperTokenService._hash_token(raw))

    class Repo:
        @staticmethod
        async def get_token_by_hash(token_hash):
            return token

    monkeypatch.setattr(DeveloperTokenService, "repository", Repo)
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
        SimpleNamespace(aget_user_tenant=AsyncMock(return_value=SimpleNamespace(status="disabled"))),
    )

    with pytest.raises(DeveloperTokenInvalidError):
        await DeveloperTokenService.authenticate(raw, request_ip="10.0.0.1")


@pytest.mark.asyncio
async def test_last_used_update_is_best_effort(monkeypatch):
    raw = "bst_last_used"
    token = _active_token(token_hash=DeveloperTokenService._hash_token(raw))

    class Repo:
        @staticmethod
        async def get_token_by_hash(token_hash):
            return token

        @staticmethod
        async def update_last_used(token_id, ip_address):
            raise RuntimeError("write failed")

    monkeypatch.setattr(DeveloperTokenService, "repository", Repo)
    monkeypatch.setattr(
        DeveloperTokenService,
        "_read_global_config",
        AsyncMock(
            return_value=SimpleNamespace(
                ip_whitelist="",
                rate_limit_per_minute=None,
            )
        ),
    )
    monkeypatch.setattr(
        "bisheng.developer_token.domain.services.developer_token_service.TenantDao",
        SimpleNamespace(aget_by_id=AsyncMock(return_value=SimpleNamespace(id=5, status="active"))),
    )
    monkeypatch.setattr(
        "bisheng.developer_token.domain.services.developer_token_service.UserDao",
        SimpleNamespace(
            aget_user=AsyncMock(
                return_value=SimpleNamespace(
                    user_id=7,
                    user_name="bound",
                    delete=0,
                    token_version=1,
                )
            )
        ),
    )
    monkeypatch.setattr(
        "bisheng.developer_token.domain.services.developer_token_service.UserTenantDao",
        SimpleNamespace(aget_user_tenant=AsyncMock(return_value=SimpleNamespace(status="active"))),
    )
    monkeypatch.setattr(
        "bisheng.developer_token.domain.services.developer_token_service.UserRoleDao",
        SimpleNamespace(get_user_roles=lambda user_id: [SimpleNamespace(role_id=2)]),
    )

    user = await DeveloperTokenService.authenticate(raw, request_ip="10.0.0.1")

    assert user.user_id == 7


def _prepare_principal_auth(monkeypatch, raw: str, *, file_sync_rule: dict | None):
    token = _active_token(
        token_hash=DeveloperTokenService._hash_token(raw),
        file_sync_rule=file_sync_rule,
    )
    calls = {"lookup": 0, "last_used": 0}

    class Repo:
        @staticmethod
        async def get_token_by_hash(token_hash):
            calls["lookup"] += 1
            return token

        @staticmethod
        async def update_last_used(token_id, ip_address):
            calls["last_used"] += 1
            return True

    monkeypatch.setattr(DeveloperTokenService, "repository", Repo)
    monkeypatch.setattr(
        DeveloperTokenService,
        "_read_global_config",
        AsyncMock(return_value=SimpleNamespace(ip_whitelist="", rate_limit_per_minute=None)),
    )
    monkeypatch.setattr(
        "bisheng.developer_token.domain.services.developer_token_service.TenantDao",
        SimpleNamespace(aget_by_id=AsyncMock(return_value=SimpleNamespace(id=5, status="active"))),
    )
    monkeypatch.setattr(
        "bisheng.developer_token.domain.services.developer_token_service.UserDao",
        SimpleNamespace(
            aget_user=AsyncMock(
                return_value=SimpleNamespace(
                    user_id=7,
                    user_name="bound",
                    delete=0,
                    token_version=1,
                )
            )
        ),
    )
    monkeypatch.setattr(
        "bisheng.developer_token.domain.services.developer_token_service.UserTenantDao",
        SimpleNamespace(aget_user_tenant=AsyncMock(return_value=SimpleNamespace(status="active"))),
    )
    monkeypatch.setattr(
        "bisheng.developer_token.domain.services.developer_token_service.UserRoleDao",
        SimpleNamespace(get_user_roles=lambda user_id: [SimpleNamespace(role_id=2)]),
    )
    return calls


@pytest.mark.asyncio
async def test_authenticate_principal_returns_token_context_without_second_lookup(monkeypatch):
    raw = "bst_principal"
    damaged_rule = {"unexpected": "stored-value"}
    calls = _prepare_principal_auth(monkeypatch, raw, file_sync_rule=damaged_rule)

    principal = await DeveloperTokenService.authenticate_principal(
        raw,
        request_ip="10.0.0.1",
        request_method="POST",
        route_path="/api/v2/filelib/file/sync",
    )

    assert principal.token_id == 2
    assert principal.tenant_id == 5
    assert principal.user.user_id == 7
    assert principal.raw_file_sync_rule == damaged_rule
    assert calls == {"lookup": 1, "last_used": 1}
    DeveloperTokenService.reset_auth_context(principal.user)


@pytest.mark.asyncio
async def test_compatibility_authenticate_returns_principal_user(monkeypatch):
    raw = "bst_compat"
    _prepare_principal_auth(monkeypatch, raw, file_sync_rule=None)

    user = await DeveloperTokenService.authenticate(raw, request_ip="10.0.0.1")

    assert user.user_id == 7
    assert user.tenant_id == 5
    DeveloperTokenService.reset_auth_context(user)


@pytest.mark.asyncio
async def test_principal_dependency_resets_context_when_consumer_closes(monkeypatch):
    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.core.context.tenant import (
        current_tenant_id,
        get_current_tenant_id,
        get_visible_tenant_ids,
        set_current_tenant_id,
        set_visible_tenant_ids,
        visible_tenant_ids,
    )

    outer_tenant = set_current_tenant_id(99)
    outer_visible = set_visible_tenant_ids(frozenset({99}))
    inner_tenant = set_current_tenant_id(5)
    inner_visible = set_visible_tenant_ids(frozenset({5}))
    user = UserPayload(
        user_id=7,
        user_name="bound",
        user_role=[2],
        tenant_id=5,
        token_version=1,
        is_global_super=False,
    )
    object.__setattr__(user, "_developer_token_context_tokens", (inner_tenant, inner_visible))
    principal = DeveloperTokenPrincipal(
        token_id=2,
        tenant_id=5,
        user=user,
        raw_file_sync_rule=None,
    )
    authenticate = AsyncMock(return_value=principal)
    monkeypatch.setattr(DeveloperTokenService, "authenticate_principal", authenticate)
    request = SimpleNamespace(
        headers={"X-Developer-Token": "bst_test"},
        client=SimpleNamespace(host="10.0.0.1"),
        method="POST",
        scope={"route": SimpleNamespace(path="/api/v2/filelib/file/sync")},
        url=SimpleNamespace(path="/api/v2/filelib/file/sync"),
    )

    dependency = get_developer_token_principal(request)
    yielded = await dependency.__anext__()
    assert yielded is principal
    await dependency.aclose()

    try:
        assert get_current_tenant_id() == 99
        assert get_visible_tenant_ids() == frozenset({99})
    finally:
        visible_tenant_ids.reset(outer_visible)
        current_tenant_id.reset(outer_tenant)


@pytest.mark.asyncio
async def test_compatibility_user_dependency_returns_principal_user() -> None:
    from bisheng.common.dependencies.user_deps import UserPayload

    user = UserPayload(
        user_id=7,
        user_name="bound",
        user_role=[2],
        tenant_id=5,
        token_version=1,
        is_global_super=False,
    )
    principal = DeveloperTokenPrincipal(
        token_id=2,
        tenant_id=5,
        user=user,
        raw_file_sync_rule=None,
    )

    assert await get_developer_token_user(principal) is user


@pytest.mark.asyncio
@pytest.mark.parametrize("raw_rule", [None, {"unexpected": "value"}])
async def test_file_sync_adapter_rejects_missing_or_damaged_rule(raw_rule) -> None:
    from bisheng.common.dependencies.user_deps import UserPayload

    principal = DeveloperTokenPrincipal(
        token_id=2,
        tenant_id=5,
        user=UserPayload(
            user_id=7,
            user_name="bound",
            user_role=[2],
            tenant_id=5,
            token_version=1,
            is_global_super=False,
        ),
        raw_file_sync_rule=raw_rule,
    )

    with pytest.raises(FilelibSyncRuleNotConfiguredError) as exc_info:
        await get_filelib_sync_principal(principal)

    assert exc_info.value.code == 19906
    assert exc_info.value.http_status == 403


@pytest.mark.asyncio
async def test_file_sync_adapter_returns_normalized_rule() -> None:
    from bisheng.common.dependencies.user_deps import UserPayload

    principal = DeveloperTokenPrincipal(
        token_id=2,
        tenant_id=5,
        user=UserPayload(
            user_id=7,
            user_name="bound",
            user_role=[2],
            tenant_id=5,
            token_version=1,
            is_global_super=False,
        ),
        raw_file_sync_rule={
            "category": {"code": " policy ", "subcategory_code": " mgmt_policy "},
            "business_domain": {"mode": "dynamic", "code": None},
            "target_space": {"mode": "dynamic", "knowledge_id": None},
            "dynamic_source": "department_id",
        },
    )

    result = await get_filelib_sync_principal(principal)

    assert result.raw_file_sync_rule["category"] == {
        "code": "POLICY",
        "subcategory_code": "MGMT_POLICY",
    }


def test_file_sync_dependency_error_keeps_actual_http_status() -> None:
    from pathlib import Path

    error = FilelibSyncRuleNotConfiguredError()
    assert error.http_status == 403
    assert error.http_response_payload() == {
        "status_code": 403,
        "status_message": "filelib_sync_rule_not_configured",
        "data": {"error_code": 19906},
    }
    main_source = Path("bisheng/main.py").read_text()
    assert "isinstance(exc, FilelibSyncError)" in main_source
