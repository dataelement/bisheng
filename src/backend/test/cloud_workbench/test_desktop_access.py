"""F113 access uses real tenant scopes and Redis semantics with fake peers."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fakeredis.aioredis import FakeRedis

from bisheng.app_runtime.domain.repositories.desktop_app_sessions import DesktopAppSessions
from bisheng.app_runtime.domain.services import desktop_apps_service as module
from bisheng.app_runtime.domain.services.desktop_apps_service import DesktopAppsService
from bisheng.common.errcode.app_factory import AppNotFoundError
from bisheng.common.errcode.dsh import DshInvalidGrantError, DshSessionRevokedError
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.dsh.domain.services.access import DshPrincipal

pytestmark = pytest.mark.asyncio


@pytest.fixture
def principal():
    return DshPrincipal(tenant_id="2", user_id="10", session_id="device-one")


@pytest.fixture
def service(principal, monkeypatch):
    identity = SimpleNamespace(active=True, tenant_id="2", user_id="10", user=SimpleNamespace(username="alice"))
    runtime = SimpleNamespace(
        sessions=SimpleNamespace(validate=AsyncMock()), identity=SimpleNamespace(check=AsyncMock(return_value=identity))
    )
    app = SimpleNamespace(
        id="a" * 32,
        tenant_id=2,
        state="online",
        name="Shared tasks",
        slug="shared-tasks",
        description="",
        current_version_id="b" * 32,
    )
    repository = SimpleNamespace(get=AsyncMock(return_value=app), page=AsyncMock(return_value=([app], None)))
    sessions = SimpleNamespace(issue=AsyncMock(return_value="t" * 43))
    monkeypatch.setattr(module, "current_global_super", AsyncMock(return_value=False))
    monkeypatch.setattr(module, "require_action", AsyncMock())
    monkeypatch.setattr(module, "check_action", AsyncMock(return_value=True))
    return DesktopAppsService(runtime, repository, sessions)


async def test_ac02_launch_checks_current_person_and_use(service, principal):
    before = get_current_tenant_id()
    result = await service.launch(principal, "a" * 32)
    module.require_action.assert_awaited_once()
    assert module.require_action.await_args.kwargs["action"] == "use"
    assert result["entry_path"] == "/apps/shared-tasks/"
    assert get_current_tenant_id() == before
    service.sessions.issue.assert_awaited_once_with(principal, app_id="a" * 32, slug="shared-tasks")


async def test_ac03_parent_session_revocation_denies_launch(service, principal):
    service.runtime.sessions.validate.side_effect = DshSessionRevokedError()
    with pytest.raises(DshSessionRevokedError):
        await service.launch(principal, "a" * 32)
    service.sessions.issue.assert_not_called()


async def test_ac03_cross_tenant_is_denied_before_permission_shortcuts(service, principal):
    service.repository.get.return_value.tenant_id = 1
    with pytest.raises(AppNotFoundError):
        await service.launch(principal, "a" * 32)
    module.require_action.assert_not_called()
    service.sessions.issue.assert_not_called()


async def test_ac02_consumer_list_hides_stopped_and_denied(service, principal):
    service.repository.page.return_value[0][0].state = "stopped"
    assert (await service.page(principal))["items"] == []
    service.repository.page.return_value[0][0].state = "online"
    module.check_action.return_value = False
    assert (await service.page(principal))["items"] == []


async def test_ac04_use_does_not_grant_source_edit(service, principal):
    module.require_action.side_effect = PermissionError("edit denied")
    with pytest.raises(PermissionError):
        await service.require(principal, "a" * 32, "edit")
    assert module.require_action.await_args.kwargs["action"] == "edit"


async def test_ac03_ticket_is_one_use_and_bound_to_one_app(principal):
    redis = FakeRedis()
    store = DesktopAppSessions(redis)
    ticket = await store.issue(principal, app_id="a" * 32, slug="first")
    with pytest.raises(DshInvalidGrantError):
        await store.redeem(ticket, "other")
    token = await store.redeem(ticket, "first")
    with pytest.raises(DshInvalidGrantError):
        await store.redeem(ticket, "first")
    assert (await store.resolve(token, "first"))["principal"] == principal.model_dump()
    with pytest.raises(DshInvalidGrantError):
        await store.resolve(token, "other")
    await redis.aclose()


async def test_ac03_expired_ticket_and_missing_session_fail_closed(principal):
    redis = FakeRedis()
    store = DesktopAppSessions(redis)
    ticket = await store.issue(principal, app_id="a" * 32, slug="first")
    await redis.delete(store.key("ticket", ticket))
    with pytest.raises(DshInvalidGrantError):
        await store.redeem(ticket, "first")
    with pytest.raises(DshInvalidGrantError):
        await store.resolve("bs-view-" + "n" * 43, "first")
    await redis.aclose()
