"""AC-48: resource-scoped connections retain real identity and restore context."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.admin.application.tenant_scope import EffectiveManagementScope
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.core.context.tenant import get_admin_scope_tenant_id, get_current_tenant_id, tenant_execution_scope
from bisheng.database.models.flow import FlowType
from bisheng.workflow.application import browser_scope


@pytest.fixture
def connection_facts(monkeypatch):
    actor = SimpleNamespace(user_id=191, user_name="admin", tenant_id=1, token_version=4, is_global_super=True)
    identity = AsyncMock(return_value=actor)
    selection = AsyncMock(return_value=EffectiveManagementScope(60, "selected", None))
    resource = AsyncMock(
        return_value=SimpleNamespace(id="flow-a", flow_type=FlowType.WORKFLOW.value, creation_state="READY")
    )
    monkeypatch.setattr(browser_scope.UserPayload, "init_login_user", identity)
    monkeypatch.setattr(browser_scope, "resolve_management_scope", selection)
    monkeypatch.setattr(browser_scope.CreationRepository, "load", resource)
    return actor, identity, selection, resource


@pytest.mark.parametrize("disconnect", [False, True])
async def test_connection_pins_target_and_restores_after_disconnect(connection_facts, disconnect):
    actor, identity, selection, resource = connection_facts
    with tenant_execution_scope(1):
        try:
            async with browser_scope.browser_workflow_scope(actor, "flow-a") as current:
                assert current.tenant_id == 1
                assert get_current_tenant_id() == get_admin_scope_tenant_id() == 60
                # A later switch cannot change this already-admitted context.
                selection.return_value = EffectiveManagementScope(65, "selected", None)
                assert get_current_tenant_id() == 60
                if disconnect:
                    raise ConnectionError("disconnected")
        except ConnectionError:
            assert disconnect
        assert get_current_tenant_id() == 1
        assert get_admin_scope_tenant_id() is None
    resource.assert_awaited_once_with(60, "flow-a")
    identity.assert_awaited_once_with(
        user_id=191, user_name="admin", tenant_id=1, token_version=4, require_current_super=True
    )


async def test_super_shortcut_cannot_skip_resource_target(connection_facts):
    actor, _, _, resource = connection_facts
    resource.return_value = None
    with tenant_execution_scope(1), pytest.raises(UnAuthorizedError):
        async with browser_scope.browser_workflow_scope(actor, "foreign-flow"):
            pytest.fail("wrong-target resource must not reach dispatch")
    assert get_admin_scope_tenant_id() is None


async def test_verified_desktop_web_session_never_reads_browser_selection(connection_facts):
    """AC-48: the existing independent device grant retains its exact target."""
    from bisheng.core.context.tenant import management_tenant_scope

    actor, identity, selection, resource = connection_facts
    actor._dsh_web_session_tenant_id = 1
    with tenant_execution_scope(1), management_tenant_scope(65):
        async with browser_scope.browser_workflow_scope(actor, "flow-a"):
            assert get_current_tenant_id() == 1
            assert get_admin_scope_tenant_id() is None
        assert get_current_tenant_id() == get_admin_scope_tenant_id() == 65
    selection.assert_not_awaited()
    identity.assert_not_awaited()
    resource.assert_awaited_once_with(1, "flow-a")


async def test_desktop_scope_marker_is_issued_only_after_credential_validation(monkeypatch):
    from bisheng.dsh.domain.services import web_session

    actor = browser_scope.UserPayload(user_id=191, user_name="admin", user_role=[], tenant_id=1)
    subject = {"user_id": 191, "user_name": "admin", "tenant_id": 1, "dsh_web_session": "verified-session"}
    auth = SimpleNamespace(get_subject=lambda **kwargs: subject)
    validate = AsyncMock()
    monkeypatch.setattr(web_session, "validate_web_session", validate)
    monkeypatch.setattr(browser_scope.UserPayload, "init_login_user", AsyncMock(return_value=actor))
    connection = object()
    result = await browser_scope.UserPayload.get_login_user_from_ws(connection, auth)
    validate.assert_awaited_once_with(connection, subject)
    assert result._dsh_web_session_tenant_id == 1
    assert "_dsh_web_session_tenant_id" not in result.model_dump()
