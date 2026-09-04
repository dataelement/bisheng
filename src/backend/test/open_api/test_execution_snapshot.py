import pytest
from pydantic import ValidationError

from bisheng.core.context.tenant import get_current_tenant_id, get_visible_tenant_ids
from bisheng.open_api.domain.context import OpenApiExecutionSnapshot, OpenApiPrincipal
from bisheng.open_api.domain.services.execution_context import restore_execution_context
from bisheng.permission.application.identity import get_current_permission_actor


def principal() -> OpenApiPrincipal:
    return OpenApiPrincipal(
        credential_id=18,
        actor_kind="service_account",
        actor_id=7,
        actor_name="automation",
        tenant_id=3,
        resource_owner_user_id=11,
        scopes=frozenset({"workflow:invoke"}),
        mode="S",
        authorization_subject_type="service_account",
        authorization_subject_id=7,
        effective_user_id=None,
    )


def test_snapshot_is_minimal_and_contains_no_credential_material():
    snapshot = OpenApiExecutionSnapshot.from_principal(principal(), trace_id="trace-1")
    payload = snapshot.model_dump(mode="json")
    assert payload["channel"] == "open_api_v2"
    assert payload["authorization_subject_type"] == "service_account"
    assert "scopes" not in payload
    assert "plaintext" not in repr(payload)
    assert "token" not in repr(payload)


def test_snapshot_channel_is_closed_enum():
    payload = OpenApiExecutionSnapshot.from_principal(principal(), trace_id="trace-1").model_dump()
    payload["channel"] = "platform"
    with pytest.raises(ValidationError):
        OpenApiExecutionSnapshot.model_validate(payload)


def test_worker_context_is_restored_and_reset(monkeypatch):
    monkeypatch.setattr(
        "bisheng.open_api.domain.services.execution_context.validate_execution_snapshot",
        lambda _snapshot: None,
    )
    payload = OpenApiExecutionSnapshot.from_principal(principal(), trace_id="trace-1").model_dump()
    with restore_execution_context(payload):
        actor = get_current_permission_actor()
        assert get_current_tenant_id() == 3
        assert get_visible_tenant_ids() == frozenset({1, 3})
        assert actor.fga_subject == "service_account:7"
        assert actor.super_admin is False
    assert get_current_permission_actor() is None
    assert get_current_tenant_id() is None
