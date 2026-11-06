"""The APP bridge keeps the actual authenticated principal. 覆盖 AC: AC-37, AC-68, AC-87, AC-89."""

import pytest

from bisheng.app_publish.application.reference_read_identity import AppSourceReadIdentity
from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.core.context.tenant import bypass_tenant_filter, current_tenant_id, set_current_tenant_id
from bisheng.core.logger import trace_id_var
from bisheng.open_api.domain.context import (
    OpenApiPrincipal,
    reset_current_open_api_principal,
    set_current_open_api_principal,
)
from bisheng.permission.application.identity import (
    PermissionActor,
    reset_current_permission_actor,
    set_current_permission_actor,
)


def principal(**changes):
    values = {
        "credential_id": 9,
        "actor_kind": "hosted_app",
        "actor_id": 7,
        "actor_name": "application",
        "tenant_id": 101,
        "subject_ref": "actual-app",
        "resource_owner_user_id": 4,
        "scopes": frozenset({"model:invoke"}),
        "authorization_subject_type": "user",
        "authorization_subject_id": 4,
        "effective_user_id": None,
    }
    return OpenApiPrincipal(**{**values, **changes})


@pytest.fixture
def authenticated():
    identity = principal()
    tenant_token = set_current_tenant_id(101)
    principal_token = set_current_open_api_principal(identity)
    actor_token = set_current_permission_actor(PermissionActor(subject_type="user", subject_id=4, tenant_id=101))
    try:
        yield identity
    finally:
        reset_current_permission_actor(actor_token)
        reset_current_open_api_principal(principal_token)
        current_tenant_id.reset(tenant_token)


async def test_original_principal_fingerprint_does_not_replace_owner_or_visitor(authenticated):
    facts = await AppSourceReadIdentity().acapture(authenticated)
    assert facts.request_tenant_id == 101
    assert authenticated.effective_user_id is None
    assert facts == await AppSourceReadIdentity().acapture(authenticated)


async def test_equal_principal_clone_is_not_authenticated_original(authenticated):
    with pytest.raises(ResourceReferenceInvalidError):
        await AppSourceReadIdentity().acapture(authenticated.model_copy())


@pytest.mark.parametrize("change", ["tenant", "actor", "ambient", "bypass"])
async def test_context_conflict_is_not_rebuilt_as_owner(authenticated, change):
    if change == "tenant":
        token = set_current_tenant_id(202)
        try:
            with pytest.raises(ResourceReferenceInvalidError):
                await AppSourceReadIdentity().acapture(authenticated)
        finally:
            current_tenant_id.reset(token)
    elif change == "actor":
        token = set_current_permission_actor(PermissionActor(subject_type="user", subject_id=99, tenant_id=101))
        try:
            with pytest.raises(ResourceReferenceInvalidError):
                await AppSourceReadIdentity().acapture(authenticated)
        finally:
            reset_current_permission_actor(token)
    elif change == "ambient":
        token = set_current_open_api_principal(None)
        try:
            with pytest.raises(ResourceReferenceInvalidError):
                await AppSourceReadIdentity().acapture(authenticated)
        finally:
            reset_current_open_api_principal(token)
    else:
        with bypass_tenant_filter(), pytest.raises(ResourceReferenceInvalidError):
            await AppSourceReadIdentity().acapture(authenticated)


async def test_trace_and_credential_scope_are_bound_without_mutation(authenticated):
    adapter = AppSourceReadIdentity()
    before = await adapter.acapture(authenticated)
    token = trace_id_var.set("different-request")
    try:
        assert (await adapter.acapture(authenticated)).fingerprint != before.fingerprint
    finally:
        trace_id_var.reset(token)
    narrowed = principal(scopes=frozenset({"knowledge:read"}))
    token = set_current_open_api_principal(narrowed)
    try:
        assert (await adapter.acapture(narrowed)).fingerprint != before.fingerprint
    finally:
        reset_current_open_api_principal(token)
