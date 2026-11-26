"""Accepted uploads must be promoted once the provider finished processing."""

import pytest

from bisheng.knowledge.application import provider_processing_proof
from bisheng.knowledge.application.provider_processing_readiness import ProcessingProof
from bisheng.knowledge.domain.repositories.provider_processing_readiness_repository import ProcessingTarget


def _target(**overrides):
    values = {
        "tenant_id": 1,
        "space_id": 16,
        "instance_id": 1,
        "remote_scope_id": "10000",
        "remote_kb_id": "kb-1",
        "generation": 1,
        "operation_id": "op-1",
        "epoch": 1,
        "file_id": 50,
        "document_id": 39,
        "version_id": 39,
        "remote_id": "doc-1",
        "checksum": "a" * 64,
        "byte_count": 10,
    }
    return ProcessingTarget(**(values | overrides))


def _envelope(**overrides):
    row = {"id": "doc-1", "knowledge_base_id": "kb-1", "tenant_id": 10000, "parse_status": "completed"}
    return {"success": True, "data": row | overrides}


def _install(monkeypatch, *, payload=None, status=200, revision=2, current_tenant=1):
    seen = []

    class _Response:
        status_code = status

        def json(self):
            return payload

    class _Client:
        async def get(self, path):
            seen.append(path)
            return _Response()

    class _Context:
        async def __aenter__(self):
            return _Client()

        async def __aexit__(self, *exc):
            return False

    contexts = []

    def client(context):
        contexts.append(context)
        return _Context()

    async def next_revision(target):
        return revision

    monkeypatch.setattr(provider_processing_proof, "instance_client", client)
    monkeypatch.setattr(provider_processing_proof, "_next_content_revision", next_revision)
    monkeypatch.setattr(provider_processing_proof, "get_current_tenant_id", lambda: current_tenant)
    return contexts, seen


async def test_a_completed_remote_document_yields_a_succeeded_proof(monkeypatch):
    contexts, seen = _install(monkeypatch, payload=_envelope())
    proof = await provider_processing_proof.read_weknora_processing_proof(_target(), actor_user_id=1)
    assert proof == ProcessingProof(_target(), "succeeded", 2)
    assert contexts[0].space_id == 16 and contexts[0].remote_kb_id == "kb-1"
    assert seen == ["knowledge/doc-1"]


async def test_an_in_flight_remote_document_yields_no_proof(monkeypatch):
    for state in ("pending", "processing", "finalizing"):
        _install(monkeypatch, payload=_envelope(parse_status=state))
        assert await provider_processing_proof.read_weknora_processing_proof(_target(), actor_user_id=1) is None


async def test_a_failed_remote_document_is_reported_as_rejected(monkeypatch):
    for state in ("failed", "cancelled"):
        _install(monkeypatch, payload=_envelope(parse_status=state))
        proof = await provider_processing_proof.read_weknora_processing_proof(_target(), actor_user_id=1)
        assert proof is not None and proof.state == "failed" and proof.target == _target()


async def test_a_foreign_document_identity_is_not_proof(monkeypatch):
    for overrides in ({"id": "other"}, {"knowledge_base_id": "other-kb"}, {"tenant_id": 20000}):
        _install(monkeypatch, payload=_envelope(**overrides))
        assert await provider_processing_proof.read_weknora_processing_proof(_target(), actor_user_id=1) is None


async def test_a_missing_remote_document_is_not_a_terminal_verdict(monkeypatch):
    _install(monkeypatch, payload=None, status=404)
    assert await provider_processing_proof.read_weknora_processing_proof(_target(), actor_user_id=1) is None


async def test_an_unknown_remote_state_never_activates(monkeypatch):
    _install(monkeypatch, payload=_envelope(parse_status="something_new"))
    assert await provider_processing_proof.read_weknora_processing_proof(_target(), actor_user_id=1) is None


async def test_the_tenant_scope_is_enforced(monkeypatch):
    from bisheng.knowledge.application.provider_v1_runtime import ProviderFeatureUnavailable

    _install(monkeypatch, payload=_envelope(), current_tenant=2)
    with pytest.raises(ProviderFeatureUnavailable):
        await provider_processing_proof.read_weknora_processing_proof(_target(), actor_user_id=1)
