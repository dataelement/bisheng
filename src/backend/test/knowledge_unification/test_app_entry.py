"""APP entry uses visibility while retaining session and OBO boundaries. 覆盖 AC: AC-35, AC-68, AC-79, AC-82, AC-83."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from bisheng.app_runtime.domain.services import entry_authz_service as module
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.core.context.tenant import current_tenant_id


@pytest.fixture
def entry(monkeypatch):
    user = UserPayload(user_id=4, user_name="visitor", tenant_id=101, user_role=[])
    app = SimpleNamespace(id="actual-app", name="app", owner_user_id=5, tenant_id=101, state="online")
    subject = {"user_id": 4, "user_name": "visitor", "tenant_id": 101, "token_version": 3}
    monkeypatch.setattr(module.settings.app_runtime, "enabled", True)
    monkeypatch.setattr(module.settings.app_runtime, "runtime_protocol_version", 1)
    monkeypatch.setattr(module, "_decode_jwt_subject", Mock(return_value=subject))
    session = AsyncMock(return_value=None)
    load = AsyncMock(return_value=app)
    action = AsyncMock(side_effect=lambda identity, **kw: identity is user and kw["action"] == "visible")
    monkeypatch.setattr(module, "_session_invalid_reason", session)
    monkeypatch.setattr(module, "_load_app_by_slug", load)
    monkeypatch.setattr(module, "_build_actor", AsyncMock(return_value=user))
    monkeypatch.setattr(module, "check_business_action", action)
    monkeypatch.setattr(module, "_owner_name", AsyncMock(return_value="owner"))
    monkeypatch.setattr(module, "_user_facts", AsyncMock(return_value=("visitor", "human")))
    monkeypatch.setattr(module, "_obo_signing_snapshot", Mock(return_value=object()))
    monkeypatch.setattr(module, "obo_configuration_status", Mock(return_value=None))
    material = AsyncMock(return_value={"X-BiSheng-Subject-Kind": "human"})
    monkeypatch.setattr(module, "_identity_material", material)
    token = Mock(return_value=("signed-original-obo", 5000))
    monkeypatch.setattr(module, "_issue_obo_token", token)
    monkeypatch.setattr(module, "schedule_access_record", Mock())
    tenant_token = current_tenant_id.set(101)
    try:
        yield SimpleNamespace(
            user=user,
            app=app,
            subject=subject,
            session=session,
            load=load,
            action=action,
            token=token,
            material=material,
        )
    finally:
        current_tenant_id.reset(tenant_token)


async def test_visible_only_visitor_enters_without_use_or_edit(entry):
    verdict = await module.authorize_entry(slug="actual", access_token="original-jwt")
    assert verdict["decision"] == "allow"
    entry.action.assert_awaited_once_with(entry.user, resource_type="app", resource_id="actual-app", action="visible")
    entry.session.assert_awaited_once_with(4, 101, entry.subject, "original-jwt")
    assert entry.token.call_args.kwargs["user_id"] == 4
    assert entry.token.call_args.kwargs["app_id"] == "actual-app"
    assert verdict["headers"]["X-BiSheng-Access-Token"] == "signed-original-obo"


async def test_invisible_visitor_never_gets_obo_identity(entry):
    entry.action.side_effect = None
    entry.action.return_value = False
    verdict = await module.authorize_entry(slug="actual", access_token="original-jwt")
    assert verdict["decision"] == "forbidden" and "headers" not in verdict
    entry.token.assert_not_called()
    entry.material.assert_not_awaited()


async def test_invalid_session_stops_before_application_or_action(entry):
    entry.session.return_value = "session_superseded"
    assert await module.authorize_entry(slug="actual", access_token="original-jwt") == {
        "decision": "login",
        "reason": "session_superseded",
    }
    entry.load.assert_not_awaited()
    entry.action.assert_not_awaited()
    entry.token.assert_not_called()
