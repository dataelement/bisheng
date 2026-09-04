from types import SimpleNamespace

import pytest
from starlette.datastructures import Headers

from bisheng.core.context.tenant import get_current_tenant_id, get_visible_tenant_ids
from bisheng.permission.application.identity import get_current_permission_actor
from bisheng.public_endpoints.domain.context import get_current_public_api_principal
from bisheng.public_endpoints.domain.services import guest_policy
from bisheng.public_endpoints.domain.services.guest_policy import PublicAccessError


def test_identity_headers_are_rejected() -> None:
    for name in ("X-On-Behalf-Of", "X-End-User"):
        with pytest.raises(PublicAccessError) as caught:
            guest_policy.reject_identity_headers(Headers({name: "value"}))
        assert caught.value.status_code == 403


@pytest.mark.asyncio
async def test_public_execution_sets_and_resets_strict_identity(monkeypatch) -> None:
    resource = SimpleNamespace(tenant_id=23)
    operator = SimpleNamespace(user_id=41, user_name="guest", tenant_id=23)

    async def load_resource(resource_type, resource_id):
        assert (resource_type, resource_id) == ("workflow", "flow-1")
        return resource

    async def load_operator(tenant_id):
        assert tenant_id == 23
        return operator

    monkeypatch.setattr(guest_policy, "_load_published_resource", load_resource)
    monkeypatch.setattr(guest_policy, "_load_default_operator", load_operator)

    assert get_current_tenant_id() is None
    async with guest_policy.public_execution("workflow", "flow-1") as execution:
        assert get_current_tenant_id() == 23
        assert get_visible_tenant_ids() == frozenset({23})
        assert execution.snapshot.channel == "public_v3"
        assert execution.snapshot.credential_id is None
        assert execution.session_subject.subject_type == "public_v3"
        assert get_current_permission_actor().fga_subject == "user:41"
        assert get_current_public_api_principal().resource_id == "flow-1"

    assert get_current_tenant_id() is None
    assert get_visible_tenant_ids() is None
    assert get_current_permission_actor() is None
    assert get_current_public_api_principal() is None


@pytest.mark.asyncio
async def test_guest_disabled_and_inactive_operator_fail_closed(monkeypatch) -> None:
    async def config(_key):
        return {"user": 41, "enable_guest_access": False}

    monkeypatch.setattr(guest_policy, "settings", SimpleNamespace(aget_from_db=config))
    with pytest.raises(PublicAccessError) as disabled:
        await guest_policy._load_default_operator(23)
    assert disabled.value.status_code == 403
