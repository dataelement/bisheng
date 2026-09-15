import pytest
from pydantic import ValidationError

from bisheng.core.context.tenant import get_current_tenant_id, get_visible_tenant_ids
from bisheng.open_api.domain.context import OpenApiExecutionSnapshot, OpenApiPrincipal
from bisheng.open_api.domain.services.execution_context import restore_execution_context
from bisheng.open_api.domain.services.tenant_setting_service import TenantPatPolicy, TenantSettingService
from bisheng.permission.application.data_scope import DATA_SCOPE_ALL, DATA_SCOPE_PERSONAL
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


def guest_snapshot(**overrides) -> OpenApiExecutionSnapshot:
    """A public v3 snapshot: a natural person carrying resolved privilege."""

    values = {
        "tenant_id": 3,
        "actor_kind": "natural_person",
        "actor_id": 41,
        "authorization_subject_type": "user",
        "authorization_subject_id": 41,
        "resource_owner_user_id": 41,
        "effective_user_id": 41,
        "mode": "S",
        "credential_id": None,
        "trace_id": "public-v3",
        "channel": "public_v3",
        "super_admin": True,
        "tenant_admin_tenant_ids": frozenset({3}),
    }
    values.update(overrides)
    return OpenApiExecutionSnapshot(**values)


def test_public_v3_snapshot_carries_operator_privileges(monkeypatch):
    """The async leg must authorize against the same facts as the handshake."""

    monkeypatch.setattr(
        "bisheng.open_api.domain.services.execution_context.validate_execution_snapshot",
        lambda _snapshot: None,
    )
    payload = guest_snapshot().model_dump(mode="json")
    with restore_execution_context(payload):
        actor = get_current_permission_actor()
        assert actor.fga_subject == "user:41"
        assert actor.super_admin is True
        assert actor.tenant_admin_tenant_ids == frozenset({3})


def test_service_account_snapshot_cannot_gain_super_admin(monkeypatch):
    """A forged snapshot must not buy privilege on the service-account path."""

    monkeypatch.setattr(
        "bisheng.open_api.domain.services.execution_context.validate_execution_snapshot",
        lambda _snapshot: None,
    )
    payload = guest_snapshot(
        actor_kind="service_account",
        authorization_subject_type="service_account",
        authorization_subject_id=7,
    ).model_dump(mode="json")
    with restore_execution_context(payload):
        actor = get_current_permission_actor()
        assert actor.super_admin is False
        assert actor.tenant_admin_tenant_ids == frozenset()


def test_legacy_snapshot_without_privilege_fields_still_validates(monkeypatch):
    """Covers messages already queued when the new fields shipped."""

    monkeypatch.setattr(
        "bisheng.open_api.domain.services.execution_context.validate_execution_snapshot",
        lambda _snapshot: None,
    )
    payload = guest_snapshot().model_dump(mode="json")
    payload.pop("super_admin")
    payload.pop("tenant_admin_tenant_ids")
    restored = OpenApiExecutionSnapshot.model_validate(payload)
    assert restored.super_admin is False
    assert restored.tenant_admin_tenant_ids == frozenset()
    with restore_execution_context(payload):
        assert get_current_permission_actor().super_admin is False


def test_v2_snapshot_shape_is_unchanged_by_the_new_fields():
    """``from_principal`` must keep producing a non-privileged v2 snapshot."""

    snapshot = OpenApiExecutionSnapshot.from_principal(principal(), trace_id="trace-1")
    assert snapshot.super_admin is False
    assert snapshot.tenant_admin_tenant_ids == frozenset()


def narrowed_pat_policy(_tenant_id: int) -> TenantPatPolicy:
    return TenantPatPolicy(enabled=True, ttl_days=30, data_scope=DATA_SCOPE_PERSONAL)


def test_public_v3_snapshot_ignores_the_pat_data_scope(monkeypatch):
    """The PAT narrowing must not reach a guest run the handshake admitted."""

    monkeypatch.setattr(
        "bisheng.open_api.domain.services.execution_context.validate_execution_snapshot",
        lambda _snapshot: None,
    )
    monkeypatch.setattr(TenantSettingService, "get_policy_sync", staticmethod(narrowed_pat_policy))
    payload = guest_snapshot().model_dump(mode="json")
    with restore_execution_context(payload):
        assert get_current_permission_actor().data_scope == DATA_SCOPE_ALL


def test_v2_pat_snapshot_rereads_the_data_scope(monkeypatch):
    """F066: a narrowing applied after enqueue still binds the queued v2 run."""

    monkeypatch.setattr(
        "bisheng.open_api.domain.services.execution_context.validate_execution_snapshot",
        lambda _snapshot: None,
    )
    monkeypatch.setattr(TenantSettingService, "get_policy_sync", staticmethod(narrowed_pat_policy))
    payload = guest_snapshot(
        channel="open_api_v2",
        credential_id=18,
        super_admin=False,
        tenant_admin_tenant_ids=frozenset(),
    ).model_dump(mode="json")
    with restore_execution_context(payload):
        assert get_current_permission_actor().data_scope == DATA_SCOPE_PERSONAL
