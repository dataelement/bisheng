"""F115 current-person eligibility for summaries and Web creation."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


async def test_person_facts_do_not_use_request_actor(monkeypatch):
    from bisheng.user.application import runtime_identity as module

    user = SimpleNamespace(user_id=9, user_name="owner", delete=0, token_version=2)
    monkeypatch.setattr(module, "current_person_rows", AsyncMock(return_value=[(user, 60), (user, 61)]))
    monkeypatch.setattr(module.settings.multi_tenant, "enabled", True)
    facts = await module.read_current_person_facts([9])
    assert facts[9]["state"] == "ambiguous"


async def test_disabled_or_missing_person_is_ineligible(monkeypatch):
    from bisheng.user.application import runtime_identity as module

    user = SimpleNamespace(user_id=9, user_name="owner", delete=1, token_version=2)
    monkeypatch.setattr(module, "current_person_rows", AsyncMock(return_value=[(user, None)]))
    monkeypatch.setattr(module.settings.multi_tenant, "enabled", True)
    facts = await module.read_current_person_facts([9, 10])
    assert facts[9]["state"] == facts[10]["state"] == "inactive"


async def test_single_tenant_person_needs_no_membership_row(monkeypatch):
    from bisheng.user.application import runtime_identity as module

    user = SimpleNamespace(user_id=9, user_name="owner", delete=0, token_version=2)
    monkeypatch.setattr(module, "current_person_rows", AsyncMock(return_value=[(user, None)]))
    monkeypatch.setattr(module.settings.multi_tenant, "enabled", False)
    facts = await module.read_current_person_facts([9])
    assert facts[9]["state"] == "active" and facts[9]["tenant_id"] == 1


@pytest.mark.parametrize("tenant,version", [(61, 2), (60, 1)])
async def test_creation_refuses_changed_tenant_or_session(monkeypatch, tenant, version):
    from bisheng.common.errcode.permission import PermissionDeniedError
    from bisheng.user.application import runtime_identity as module

    monkeypatch.setattr(
        module,
        "read_current_person_facts",
        AsyncMock(
            return_value={
                9: {
                    "state": "active",
                    "tenant_id": 60,
                    "token_version": 2,
                    "name": "owner",
                    "id": 9,
                }
            }
        ),
    )
    ref = {
        "kind": "web_session",
        "user_id": 9,
        "tenant_id": tenant,
        "token_version": version,
        "expires_at": (datetime.utcnow() + timedelta(minutes=2)).isoformat(),
    }
    with pytest.raises(PermissionDeniedError):
        await module.resolve_web_creation_identity(ref)
