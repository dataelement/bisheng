"""F115 AC-39 through AC-50 and AC-52: new creation is not copy permission."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def policy(monkeypatch):
    from bisheng.knowledge.domain.services import knowledge_creation_policy as module

    ref = {
        "kind": "web_session",
        "user_id": 9,
        "tenant_id": 60,
        "token_version": 1,
        "expires_at": (datetime.utcnow() + timedelta(minutes=2)).isoformat(),
    }
    viewer = SimpleNamespace(user_id=9, tenant_id=60, _runtime_credential_reference=ref)
    person = SimpleNamespace(user_id=9, tenant_id=60, is_global_super=False)
    monkeypatch.setattr(module, "resolve_web_creation_identity", AsyncMock(return_value=person))
    monkeypatch.setattr(module, "is_tenant_admin", AsyncMock(return_value=True))
    monkeypatch.setattr(
        module.UserPayload,
        "assert_effective_web_menu_contains",
        AsyncMock(side_effect=AssertionError("menu must not be required")),
    )
    return module, viewer


async def test_tenant_admin_can_create_without_a_menu(policy):
    module, viewer = policy
    context = await module.KnowledgeCreationPolicy.prepare(viewer, expected_tenant_id=60)
    assert context.tenant_id == 60 and context.user_id == 9


async def test_foreign_expected_tenant_does_not_select_a_write_target(policy):
    from bisheng.common.errcode.knowledge import KnowledgeCreationScopeChangedError

    module, viewer = policy
    with pytest.raises(KnowledgeCreationScopeChangedError):
        await module.KnowledgeCreationPolicy.prepare(viewer, expected_tenant_id=61)


async def test_revoked_admin_requires_the_original_menu_at_revalidation(policy, monkeypatch):
    from bisheng.common.errcode.permission import PermissionDeniedError

    module, viewer = policy
    context = await module.KnowledgeCreationPolicy.prepare(viewer, expected_tenant_id=60)
    monkeypatch.setattr(module, "is_tenant_admin", AsyncMock(return_value=False))
    monkeypatch.setattr(
        module.UserPayload, "assert_effective_web_menu_contains", AsyncMock(side_effect=PermissionDeniedError())
    )
    with pytest.raises(PermissionDeniedError):
        await module.KnowledgeCreationPolicy.revalidate(context)


async def test_ordinary_user_with_original_menu_remains_allowed(policy, monkeypatch):
    module, viewer = policy
    monkeypatch.setattr(module, "is_tenant_admin", AsyncMock(return_value=False))
    check = AsyncMock()
    monkeypatch.setattr(module.UserPayload, "assert_effective_web_menu_contains", check)
    await module.KnowledgeCreationPolicy.prepare(viewer, expected_tenant_id=60)
    check.assert_awaited_once()
