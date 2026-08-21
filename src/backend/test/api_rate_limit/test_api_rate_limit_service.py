from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.api_rate_limit.domain.schemas import ApiRateLimitConfig, ApiRateLimitConfigUpdate
from bisheng.api_rate_limit.domain.services import ApiRateLimitService
from bisheng.common.errcode.server import (
    ApiRateLimitConfigSyncError,
    ApiRateLimitForbiddenError,
)


def test_default_config_is_stable_across_replicas():
    first = ApiRateLimitService._default_config()
    second = ApiRateLimitService._default_config()

    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_rule_selection_precedence_and_longest_prefix():
    config = ApiRateLimitConfig.model_validate(
        {
            "global": {"limits": {"minute": 100}, "message": "global"},
            "routes": [
                {
                    "match_type": "PREFIX",
                    "path": "/api/v1",
                    "limits": {"minute": 80},
                    "message": "short",
                },
                {
                    "match_type": "PREFIX",
                    "path": "/api/v1/items",
                    "limits": {"minute": 60},
                    "message": "long",
                },
                {
                    "match_type": "PATH",
                    "path": "/api/v1/items/{item_id}",
                    "limits": {"minute": 40},
                    "message": "path",
                },
                {
                    "match_type": "METHOD_PATH",
                    "method": "GET",
                    "path": "/api/v1/items/{item_id}",
                    "limits": {"minute": 20},
                    "message": "method",
                },
            ],
        }
    )

    get_policy = ApiRateLimitService.resolve_policy(
        config,
        method="GET",
        route_template="/api/v1/items/{item_id}",
    )
    post_policy = ApiRateLimitService.resolve_policy(
        config,
        method="POST",
        route_template="/api/v1/items/{item_id}",
    )
    child_policy = ApiRateLimitService.resolve_policy(
        config,
        method="POST",
        route_template="/api/v1/items/search",
    )

    assert get_policy.policy.limits.minute == 20
    assert post_policy.policy.limits.minute == 40
    assert child_policy.policy.limits.minute == 60


async def test_update_never_persists_when_redis_staging_fails(monkeypatch):
    user = SimpleNamespace(user_id=7)
    payload = ApiRateLimitConfigUpdate(expected_revision=0)
    redis_repository = AsyncMock()
    redis_repository.stage.side_effect = RuntimeError("redis down")
    persist = AsyncMock()

    monkeypatch.setattr(ApiRateLimitService, "_assert_global_super", AsyncMock())
    monkeypatch.setattr(ApiRateLimitService, "_redis_repository", AsyncMock(return_value=redis_repository))
    monkeypatch.setattr(ApiRateLimitService, "_persist_db_config", persist)

    with pytest.raises(ApiRateLimitConfigSyncError):
        await ApiRateLimitService.update_config(user, payload)
    persist.assert_not_awaited()


async def test_update_reports_failure_when_db_commits_but_activation_fails(monkeypatch):
    user = SimpleNamespace(user_id=7)
    payload = ApiRateLimitConfigUpdate(expected_revision=0)
    redis_repository = AsyncMock()
    redis_repository.stage.return_value = "candidate"
    redis_repository.activate.return_value = False
    persist = AsyncMock()

    monkeypatch.setattr(ApiRateLimitService, "_assert_global_super", AsyncMock())
    monkeypatch.setattr(ApiRateLimitService, "_redis_repository", AsyncMock(return_value=redis_repository))
    monkeypatch.setattr(ApiRateLimitService, "_persist_db_config", persist)

    with pytest.raises(ApiRateLimitConfigSyncError):
        await ApiRateLimitService.update_config(user, payload)
    persist.assert_awaited_once()


async def test_update_does_not_activate_when_database_persistence_fails(monkeypatch):
    user = SimpleNamespace(user_id=7)
    payload = ApiRateLimitConfigUpdate(expected_revision=0)
    redis_repository = AsyncMock()
    redis_repository.stage.return_value = "candidate"
    persist = AsyncMock(side_effect=RuntimeError("database down"))

    monkeypatch.setattr(ApiRateLimitService, "_assert_global_super", AsyncMock())
    monkeypatch.setattr(
        ApiRateLimitService,
        "_redis_repository",
        AsyncMock(return_value=redis_repository),
    )
    monkeypatch.setattr(ApiRateLimitService, "_persist_db_config", persist)

    with pytest.raises(ApiRateLimitConfigSyncError):
        await ApiRateLimitService.update_config(user, payload)
    redis_repository.activate.assert_not_awaited()


async def test_non_global_super_is_rejected_before_configuration_access(monkeypatch):
    import bisheng.api_rate_limit.domain.services.api_rate_limit_service as service_module

    monkeypatch.setattr(service_module, "_check_is_global_super", AsyncMock(return_value=False))

    with pytest.raises(ApiRateLimitForbiddenError):
        await ApiRateLimitService.get_config(SimpleNamespace(user_id=8))


async def test_non_global_super_is_rejected_before_route_catalog_access(monkeypatch):
    import bisheng.api_rate_limit.domain.services.api_rate_limit_service as service_module

    monkeypatch.setattr(service_module, "_check_is_global_super", AsyncMock(return_value=False))

    with pytest.raises(ApiRateLimitForbiddenError):
        await ApiRateLimitService.get_route_catalog(SimpleNamespace(user_id=8), [])


async def test_runtime_active_snapshot_does_not_fall_back_to_database(monkeypatch):
    config = ApiRateLimitConfig.model_validate({"revision": 4})
    redis_repository = AsyncMock()
    redis_repository.get_active.return_value = config
    load_db_config = AsyncMock()

    monkeypatch.setattr(
        ApiRateLimitService,
        "_redis_repository",
        AsyncMock(return_value=redis_repository),
    )
    monkeypatch.setattr(ApiRateLimitService, "_load_db_config", load_db_config)

    assert await ApiRateLimitService.get_runtime_config() is config
    load_db_config.assert_not_awaited()


async def test_runtime_missing_snapshot_recovers_under_redis_lock(monkeypatch):
    config = ApiRateLimitConfig.model_validate({"revision": 5})
    redis_repository = AsyncMock()
    redis_repository.get_active.return_value = None
    redis_repository.acquire_recovery_lock.return_value = "recovery-token"
    ensure_active = AsyncMock()

    monkeypatch.setattr(
        ApiRateLimitService,
        "_redis_repository",
        AsyncMock(return_value=redis_repository),
    )
    monkeypatch.setattr(
        ApiRateLimitService,
        "_load_db_config",
        AsyncMock(return_value=config),
    )
    monkeypatch.setattr(ApiRateLimitService, "_ensure_active", ensure_active)

    assert await ApiRateLimitService.get_runtime_config() is config
    ensure_active.assert_awaited_once_with(config, redis_repository)
    redis_repository.release_recovery_lock.assert_awaited_once_with("recovery-token")
