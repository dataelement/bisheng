"""T346: immutable source read DTOs are values, never authorizing receipts."""

import dataclasses
import hashlib
import json

import pytest

from bisheng.resource_reference.application.contracts import ReferenceSpec, SourceKey, TargetKey
from bisheng.resource_reference.application.source_contracts import (
    AuthorizedSourceSnapshot,
    AuthorizedTransientSnapshot,
    ReadIdentityFacts,
    ReferenceTargetReadFact,
    SourceReadRequest,
    TransientTargetRequest,
    canonical_payload_json,
    payload_digest,
)


def test_canonical_json_and_utf8_digest_have_one_definition():
    encoded = canonical_payload_json({"z": [2, 1], "中文": "值", "a": True})
    assert encoded == '{"a":true,"z":[2,1],"中文":"值"}'
    assert payload_digest(encoded) == hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    with pytest.raises(ValueError):
        canonical_payload_json({"x": float("nan")})


@pytest.mark.parametrize("purpose, token", [("execute", "secret-link"), ("preview", None)])
def test_source_request_does_not_promote_inspection_evidence(purpose, token):
    with pytest.raises(ValueError):
        SourceReadRequest("assistant", "a", purpose=purpose, inspect_token=token)


def test_inspect_token_is_not_in_repr_and_request_has_no_tenant_claim():
    request = SourceReadRequest("assistant", "a", purpose="inspect", inspect_token="secret-link")
    assert "secret-link" not in repr(request)
    assert "tenant_id" not in {field.name for field in dataclasses.fields(request)}


def test_snapshot_uses_only_canonical_immutable_payload_and_exact_references():
    key = SourceKey(101, "assistant", "a", "current")
    ref = ReferenceSpec("model_name", TargetKey("model", 3))
    text = canonical_payload_json({"model_name": "3"})
    snapshot = AuthorizedSourceSnapshot(key, (ref, ref), "assistant-v1", payload_digest(text), text)
    assert snapshot.references == (ref,)
    value = json.loads(snapshot.payload_json)
    value["model_name"] = "4"
    assert json.loads(snapshot.payload_json)["model_name"] == "3"
    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.payload_json = "{}"
    with pytest.raises(ValueError):
        dataclasses.replace(snapshot, configuration_digest="0" * 64)
    with pytest.raises(ValueError):
        dataclasses.replace(snapshot, payload_json='{ "model_name": "3" }')


def test_transient_payload_has_no_source_or_version_identity():
    text = canonical_payload_json({"nodes": [], "edges": []})
    request = TransientTargetRequest("workflow", "w", text)
    snapshot = AuthorizedTransientSnapshot("workflow", "w", 101, (), "wf-v1", payload_digest(text), text)
    assert request.resource_id == snapshot.resource_id
    assert not hasattr(snapshot, "source_key")
    with pytest.raises(ValueError):
        TransientTargetRequest("assistant", "a", text)


def test_live_revoked_model_read_fact_is_not_an_extra_persistent_state():
    fact = ReferenceTargetReadFact(TargetKey("model", 3), "valid", False, 1)
    assert fact.state.value == "valid" and fact.is_valid is False
    with pytest.raises(ValueError):
        ReferenceTargetReadFact(TargetKey("knowledge_space", 4), "valid", False, 101)
    with pytest.raises(ValueError):
        ReferenceTargetReadFact(TargetKey("model", 3), "invalid_deleted", True, 1)


def test_identity_facts_need_real_tenant_and_hashable_fingerprint():
    assert ReadIdentityFacts(101, ("user", 7)).request_tenant_id == 101
    with pytest.raises(ValueError):
        ReadIdentityFacts(True, "x")
    with pytest.raises(TypeError):
        ReadIdentityFacts(101, [])
