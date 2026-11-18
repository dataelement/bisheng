"""T939: frozen move subjects are typed facts, separate from audit and live credentials."""

import importlib
import json
from copy import deepcopy
from dataclasses import FrozenInstanceError
from types import MappingProxyType
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.core.context.tenant import (
    get_admin_scope_tenant_id,
    get_current_tenant_id,
    management_tenant_scope,
)
from bisheng.knowledge.application import processing_identity as identity
from bisheng.permission.application.data_scope import DATA_SCOPE_ALL, DATA_SCOPE_PERSONAL
from bisheng.permission.application.identity import PermissionActor, get_current_permission_actor
from test.knowledge_unification.test_processing_identity import (
    api_ports as api_ports,
)
from test.knowledge_unification.test_processing_identity import (
    principal,
    request_context,
    web_user,
)


def subject_module():
    return importlib.import_module("bisheng.knowledge.domain.schemas.processing_actor_subject")


def reference(*, subject_type="service_account", subject_id=7, home=101):
    return {
        "schema_version": 1,
        "tenant_id": 101,
        "actor_user_id": 11,
        "space_id": 23,
        "required_action": "move",
        "entry_kind": "open_api",
        "actor": {
            "subject_type": subject_type,
            "subject_id": subject_id,
            "tenant_id": home,
            "super_admin": False,
            "tenant_admin_tenant_ids": [],
            "data_scope": DATA_SCOPE_ALL,
        },
        # Membership must not restore or expire a previously accepted credential.
        "credential_reference": {"kind": "historical", "expires_at": "2000-01-01T00:00:00"},
    }


def decode(value, **changes):
    return subject_module().processing_actor_subject(
        value, **{"tenant_id": 101, "actor_user_id": 11, "source_space_id": 23, **changes}
    )


@pytest.mark.parametrize("kind,identifier", [("user", 11), ("user", 7), ("service_account", 7)])
def test_typed_subject_neither_collapses_numeric_types_nor_becomes_audit_user(kind, identifier):
    value = reference(subject_type=kind, subject_id=identifier)
    before = deepcopy(value)
    actual = decode(MappingProxyType(value))
    assert (actual.subject_type, actual.subject_id) == (kind, identifier)
    assert value == before
    assert "credential" not in repr(actual) and "2000" not in repr(actual)
    with pytest.raises(FrozenInstanceError):
        actual.subject_id = 99


def test_selected_management_tenant_keeps_original_nested_actor_home():
    value = reference(subject_type="user", subject_id=11, home=1)
    value["entry_kind"] = "web"
    value["actor"].update(super_admin=True, tenant_admin_tenant_ids=[101, 202])
    assert decode(value).subject_id == 11
    assert value["actor"]["tenant_id"] == 1 and value["tenant_id"] == 101


@pytest.mark.parametrize("value", [True, 1.0, 0, -1, "1", None])
@pytest.mark.parametrize("field", ["tenant_id", "actor_user_id", "space_id"])
def test_outer_ids_are_strict_and_match_the_requested_frozen_origin(field, value):
    origin = reference()
    origin[field] = value
    with pytest.raises(ValueError):
        decode(origin)


@pytest.mark.parametrize(
    "changes",
    [
        {"tenant_id": 202},
        {"actor_user_id": 12},
        {"source_space_id": 24},
        {"tenant_id": True},
        {"actor_user_id": 11.0},
        {"source_space_id": 0},
    ],
)
def test_expected_origin_arguments_are_exact_not_coerced(changes):
    with pytest.raises(ValueError):
        decode(reference(), **changes)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("schema_version", 1.0),
        ("schema_version", 2),
        ("required_action", "edit"),
        ("entry_kind", "worker"),
        ("actor", None),
        ("credential_reference", None),
    ],
)
def test_outer_closed_shape_and_move_action_are_required(field, value):
    origin = reference()
    origin[field] = value
    with pytest.raises(ValueError):
        decode(origin)


@pytest.mark.parametrize("field", ["schema_version", "actor", "credential_reference"])
def test_missing_and_unknown_outer_fields_are_rejected(field):
    origin = reference()
    del origin[field]
    with pytest.raises(ValueError):
        decode(origin)
    origin = reference()
    origin["unknown"] = "ignored-authority"
    with pytest.raises(ValueError):
        decode(origin)


@pytest.mark.parametrize(
    "field,value",
    [
        ("subject_type", "department"),
        ("subject_type", []),
        ("subject_id", True),
        ("subject_id", 7.0),
        ("subject_id", 0),
        ("tenant_id", False),
        ("tenant_id", 1.0),
        ("tenant_id", -1),
        ("super_admin", 1),
        ("data_scope", "all"),
        ("tenant_admin_tenant_ids", (101,)),
        ("tenant_admin_tenant_ids", [True]),
        ("tenant_admin_tenant_ids", [101.0]),
        ("tenant_admin_tenant_ids", [0]),
    ],
)
def test_nested_actor_facts_are_closed_and_keep_original_strict_types(field, value):
    origin = reference()
    origin["actor"][field] = value
    with pytest.raises(ValueError):
        decode(origin)


def test_nested_actor_unknown_or_missing_facts_are_not_silently_discarded():
    origin = reference()
    origin["actor"]["management_tenant_id"] = 101
    with pytest.raises(ValueError):
        decode(origin)
    del origin["actor"]["management_tenant_id"]
    del origin["actor"]["super_admin"]
    with pytest.raises(ValueError):
        decode(origin)


@pytest.mark.parametrize("delegated", [False, True])
async def test_real_api_move_payload_bytes_preserve_original_subject_credential_and_audit(api_ports, delegated):
    original = principal(delegated=delegated, scopes={"knowledge:write", "delegate"})
    actor = PermissionActor(
        subject_type=original.authorization_subject_type, subject_id=original.authorization_subject_id, tenant_id=101
    )
    with request_context(actor, original):
        captured = await identity.capture_processing_actor(
            original, space_id=23, required_action="move", entry_kind="open_api"
        )
        credential = identity.capture_knowledge_processing_reference(original)
    expected = reference(subject_type=actor.subject_type, subject_id=actor.subject_id)
    expected["credential_reference"] = credential
    assert captured.payload_json == json.dumps(expected, sort_keys=True, separators=(",", ":"), allow_nan=False)
    assert captured.actor_user_id == 11
    assert captured.reference["actor"]["subject_id"] == (11 if delegated else 7)


async def test_real_web_move_preserves_home_and_selected_scope_through_current_restore(monkeypatch):
    user = web_user()
    user.tenant_id = 1
    user._runtime_credential_reference["tenant_id"] = 1
    actor = PermissionActor(user_id=11, tenant_id=1, super_admin=True)
    monkeypatch.setattr(identity, "resolve_permission_actor", AsyncMock(return_value=actor))
    monkeypatch.setattr(identity, "resolve_web_runtime_identity", AsyncMock(return_value=user))
    with request_context(actor, tenant=101), management_tenant_scope(101):
        captured = await identity.capture_processing_actor(user, space_id=23, required_action="move", entry_kind="web")
    expected = reference(subject_type="user", subject_id=11, home=1)
    expected.update(entry_kind="web", credential_reference=user._runtime_credential_reference)
    expected["actor"]["super_admin"] = True
    assert captured.payload_json == json.dumps(expected, sort_keys=True, separators=(",", ":"), allow_nan=False)
    with request_context(None, tenant=202):
        async with identity.restore_processing_actor(captured.reference, tenant_id=101) as restored:
            assert restored is user and restored.tenant_id == 1
            assert get_current_tenant_id() == get_admin_scope_tenant_id() == 101
            assert get_current_permission_actor() == actor
        assert get_current_tenant_id() == 202


async def test_move_capture_and_restore_both_delegate_subject_parsing_to_the_same_pure_decoder(monkeypatch):
    user = web_user()
    actor = PermissionActor(user_id=11, tenant_id=101, data_scope=DATA_SCOPE_PERSONAL)
    calls = []

    def record(value, **expectations):
        calls.append((deepcopy(value), expectations))

    monkeypatch.setattr(identity, "processing_actor_subject", record, raising=False)
    monkeypatch.setattr(identity, "resolve_permission_actor", AsyncMock(return_value=actor))
    monkeypatch.setattr(identity, "resolve_web_runtime_identity", AsyncMock(return_value=user))
    with request_context(actor):
        captured = await identity.capture_processing_actor(user, space_id=23, required_action="move", entry_kind="web")
    async with identity.restore_processing_actor(captured.reference, tenant_id=101):
        pass
    assert len(calls) == 2
    for value, expectations in calls:
        assert value == captured.reference
        assert expectations == {"tenant_id": 101, "actor_user_id": 11, "source_space_id": 23}


@pytest.mark.parametrize("action", ["edit", "rename", "upload_file"])
async def test_other_processing_actions_keep_original_capture_restore_without_a_new_subject_gate(monkeypatch, action):
    user = web_user()
    actor = PermissionActor(user_id=11, tenant_id=101)

    def forbidden(*args, **kwargs):
        pytest.fail("the move-only decoder gated a different processing action")

    monkeypatch.setattr(identity, "processing_actor_subject", forbidden, raising=False)
    monkeypatch.setattr(identity, "resolve_permission_actor", AsyncMock(return_value=actor))
    monkeypatch.setattr(identity, "resolve_web_runtime_identity", AsyncMock(return_value=user))
    with request_context(actor):
        captured = await identity.capture_processing_actor(user, space_id=23, required_action=action, entry_kind="web")
    async with identity.restore_processing_actor(captured.reference, tenant_id=101) as restored:
        assert restored is user


async def test_live_restore_still_rejects_expired_credential_but_historical_subject_remains_readable(monkeypatch):
    user = web_user()
    actor = PermissionActor(user_id=11, tenant_id=101)
    with request_context(actor):
        captured = await identity.capture_processing_actor(user, space_id=23, required_action="move", entry_kind="web")
    origin = captured.reference
    origin["credential_reference"]["expires_at"] = "2000-01-01T00:00:00"
    assert decode(origin).subject_id == 11
    resolve = AsyncMock()
    monkeypatch.setattr(identity, "resolve_web_runtime_identity", resolve)
    with pytest.raises(PermissionDeniedError):
        async with identity.restore_processing_actor(origin, tenant_id=101):
            pytest.fail("expired current credential was restored")
    resolve.assert_not_awaited()
