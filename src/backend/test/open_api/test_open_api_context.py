import pytest
from pydantic import ValidationError

from bisheng.open_api.domain.context import (
    OpenApiExecutionSnapshot,
    OpenApiPrincipal,
    get_current_open_api_principal,
    reset_current_open_api_principal,
    set_current_open_api_principal,
)


def make_principal() -> OpenApiPrincipal:
    return OpenApiPrincipal(
        credential_id=7,
        actor_kind="service_account",
        actor_id=9,
        actor_name="integration",
        tenant_id=2,
        resource_owner_user_id=11,
        scopes=frozenset({"knowledge:read"}),
        authorization_subject_type="service_account",
        authorization_subject_id=9,
        effective_user_id=None,
    )


def test_principal_is_immutable_and_context_is_resettable():
    principal = make_principal()
    with pytest.raises(ValidationError):
        principal.mode = "D"
    token = set_current_open_api_principal(principal)
    assert get_current_open_api_principal() is principal
    reset_current_open_api_principal(token)
    assert get_current_open_api_principal() is None


def test_execution_snapshot_is_minimal_and_round_trips():
    snapshot = OpenApiExecutionSnapshot.from_principal(make_principal(), trace_id="trace-1")
    payload = snapshot.model_dump(mode="json")
    assert OpenApiExecutionSnapshot.model_validate(payload) == snapshot
    assert payload["channel"] == "open_api_v2"
    assert "scopes" not in payload
    assert all("key" not in name and "token" not in name and "secret" not in name for name in payload)


def test_execution_snapshot_rejects_unknown_channel_and_fields():
    payload = OpenApiExecutionSnapshot.from_principal(make_principal(), trace_id="trace-1").model_dump()
    payload["channel"] = "v1"
    with pytest.raises(ValidationError):
        OpenApiExecutionSnapshot.model_validate(payload)
    payload["channel"] = "open_api_v2"
    payload["plaintext"] = "forbidden"
    with pytest.raises(ValidationError):
        OpenApiExecutionSnapshot.model_validate(payload)
