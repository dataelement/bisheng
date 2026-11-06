"""T470: actual native model facts preserve source authority and SQL boundaries.

覆盖 AC: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-89, AC-91, AC-92
SQLite validates current-read ordering/rollback, not MySQL/DM8 lock scheduling.
"""

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, event, update
from sqlmodel import Session

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ResourceReferenceInvalidError
from bisheng.core.context.tenant import bypass_tenant_filter, get_current_tenant_id
from bisheng.knowledge.application.reference_read_legacy_evidence import KnowledgeReferenceReadLegacyEvidence
from bisheng.knowledge.domain.models.knowledge_unification_run import KnowledgeUnificationRun
from bisheng.llm.application import source_read_target_owner as owner_module
from bisheng.llm.application.model_default_read_identity import ModelDefaultReadIdentityPort
from bisheng.llm.application.model_default_source_owner import ModelDefaultSourceOwner
from bisheng.llm.application.source_read_target_owner import ModelSourceReadTargetOwner
from bisheng.llm.domain.models.llm_server import LLMModel, LLMServer
from bisheng.llm.domain.models.tenant_system_model_config import TenantSystemModelConfig
from bisheng.llm.domain.services.default_reference_extractor import (
    MODEL_DEFAULT_REFERENCE_EXTRACTOR_VERSION,
    extract_model_default_references,
)
from bisheng.resource_reference.application.contracts import reference_set_digest
from bisheng.resource_reference.application.source_contracts import SourceReadRequest
from bisheng.resource_reference.application.source_read import ReferenceSourceReadRuntime
from bisheng.resource_reference.application.source_verification import SourceReadVerifier
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone
from bisheng.resource_reference.domain.repositories.source_read_repository import SourceReadRepository
from test.knowledge_unification import test_model_reference_owner as models

model_owner_tenant = models.model_owner_tenant
TABLES = [*models.TABLES, BusinessReferenceSet.__table__, KnowledgeUnificationRun.__table__]


class NativeRelations:
    ids = ()
    error = None
    calls = []

    def list_resource_ids_sync(self, *, subject, relation, resource_type):
        self.calls.append((subject.subject_type, subject.subject_id, relation, resource_type))
        if self.error:
            raise self.error
        return self.ids


def seed_default(session, tenant_id=101, key="evaluation_llm", payload=None, *, legacy=False):
    payload = {"model_id": 11} if payload is None else payload
    references = extract_model_default_references(key, payload)
    session.add(TenantSystemModelConfig(tenant_id=tenant_id, key=key, value=json.dumps(payload)))
    common = dict(tenant_id=tenant_id, source_type="model_default", source_id=key)
    session.add(
        BusinessReferenceSet(
            **common,
            source_version="__root__",
            record_kind="root_guard",
            source_revision=1,
            ready=False,
            effective=False,
            extractor_version="root-guard-v1",
            digest=reference_set_digest(()),
        )
    )
    session.add(
        BusinessReferenceSet(
            **common,
            source_version="current",
            source_revision=2,
            ready=True,
            effective=True,
            extractor_version=MODEL_DEFAULT_REFERENCE_EXTRACTOR_VERSION,
            digest=reference_set_digest(references),
        )
    )
    for item in references:
        owner = {"11": 101, "22": 1, "33": 202}.get(item.target.target_id)
        session.add(
            BusinessResourceReference(
                **common,
                source_version="current",
                source_revision=2,
                slot_key=item.slot_key,
                target_type="model",
                target_id=item.target.target_id,
                target_tenant_id=owner,
                legacy_invalid_reason="target_missing" if legacy else None,
                legacy_run_id="legacy-run" if legacy else None,
                legacy_evidence_key="frozen-target" if legacy else None,
            )
        )


@pytest.fixture
def native_target(f118_engine, model_owner_tenant, monkeypatch):
    for table in TABLES:
        table.create(f118_engine)
    with Session(f118_engine) as session, session.begin():
        models.setup(session)
    identity_port = ModelDefaultReadIdentityPort()
    verifier = SourceReadVerifier(
        {"model_default": ModelDefaultSourceOwner(identity_port=identity_port)}, identity_port
    )
    legacy = KnowledgeReferenceReadLegacyEvidence(verifier)
    owner = ModelSourceReadTargetOwner(verifier, legacy_evidence=legacy)
    runtime = ReferenceSourceReadRuntime(verifier, SourceReadRepository(verifier), {"model": owner})
    relations = NativeRelations()
    relations.calls = []
    monkeypatch.setattr(owner_module, "get_permission_relation_api_sync", lambda: relations, raising=False)
    return SimpleNamespace(
        engine=f118_engine,
        identity_port=identity_port,
        verifier=verifier,
        owner=owner,
        runtime=runtime,
        relations=relations,
    )


def inspect(ctx, session, key="evaluation_llm"):
    identity = ctx.identity_port.issue_identity()
    request = SourceReadRequest("model_default", key, purpose="inspect")
    scope = ctx.verifier.issue_scope(session, request, identity)
    targets = tuple(item.target for item in scope.snapshot.references)
    return ctx.owner.inspect_source_targets(session, scope, targets, identity=identity)


def test_native_real_own_target_uses_same_session_and_no_async_or_orm_loads(native_target):
    ctx = native_target
    with Session(ctx.engine) as session, session.begin():
        seed_default(session)
    with Session(ctx.engine) as session:
        assert inspect(ctx, session)[0].is_valid
        assert get_current_tenant_id() == 101 and not session.identity_map
        assert session.in_transaction() and not ctx.relations.calls


def test_native_inherited_root_source_is_read_without_switching_current_tenant(native_target):
    ctx = native_target
    with Session(ctx.engine) as session, session.begin():
        seed_default(session, tenant_id=1, payload={"model_id": 22})
    with Session(ctx.engine) as session:
        identity = ctx.identity_port.issue_identity()
        scope = ctx.verifier.issue_scope(session, SourceReadRequest("model_default", "evaluation_llm"), identity)
        result = ctx.runtime.require_source_valid(session, scope, identity)
        assert result.snapshot.source_key.tenant_id == 1 and result.target_states[0].is_valid
        assert get_current_tenant_id() == 101 and not ctx.relations.calls and not session.identity_map


@pytest.mark.parametrize("inherited", [False, True])
def test_native_child_uses_explicit_or_real_inherited_server_evidence(native_target, inherited):
    ctx = native_target
    with Session(ctx.engine) as session, session.begin():
        seed_default(session, payload={"model_id": 22})
        if inherited:
            session.add(TenantSystemModelConfig(tenant_id=1, key="assistant_llm", value='{"auto_llm":{"model_id":22}}'))
    ctx.relations.ids = () if inherited else ("2",)
    with Session(ctx.engine) as session:
        assert inspect(ctx, session)[0].is_valid
        assert ctx.relations.calls == [("tenant", "101", "shared_with", "llm_server")]


@pytest.mark.parametrize("kind", ["revoked", "malformed", "error"])
def test_native_shared_facts_never_promote_revocation_or_backend_failure(native_target, kind):
    ctx = native_target
    with Session(ctx.engine) as session, session.begin():
        seed_default(session, payload={"model_id": 22})
    if kind == "malformed":
        ctx.relations.ids = (True,)
    elif kind == "error":
        ctx.relations.error = RuntimeError("native sharing unavailable")
    with Session(ctx.engine) as session:
        if kind == "revoked":
            fact = inspect(ctx, session)[0]
            assert fact.state == "valid" and not fact.is_valid
        else:
            with pytest.raises(RuntimeError if kind == "error" else ResourceReferenceInvalidError):
                inspect(ctx, session)


@pytest.mark.parametrize("stage", ["deleted", "deleting"])
def test_native_tombstones_are_read_from_original_owner_without_new_receipts(native_target, stage):
    ctx = native_target
    with Session(ctx.engine) as session, session.begin():
        seed_default(session)
        session.add(
            ResourceReferenceTombstone(
                tenant_id=101,
                target_tenant_id=101,
                target_type="model",
                target_id="11",
                operation_id="delete-model",
                operation_type="force_delete_model",
                actor_type="user",
                actor_id="7",
                stage=stage,
            )
        )
        if stage == "deleted":
            session.execute(delete(LLMModel).where(LLMModel.tenant_id == 101, LLMModel.id == 11))
    with Session(ctx.engine) as session:
        fact = inspect(ctx, session)[0]
        assert fact.state == ("invalid_deleted" if stage == "deleted" else "deleting") and not fact.is_valid


def test_native_legacy_reads_actual_frozen_ledger_and_preserves_unknown_target_tenant(native_target):
    ctx = native_target
    with Session(ctx.engine) as session, session.begin():
        seed_default(session, payload={"model_id": 99}, legacy=True)
        session.add(
            KnowledgeUnificationRun(
                tenant_id=101,
                run_id="legacy-run",
                phase="verified",
                baseline_hash="a" * 64,
                plan_hash="b" * 64,
                baseline_ref={"object_key": "101/baseline", "sha256": "a" * 64},
                plan_ref={"object_key": "101/plan", "sha256": "b" * 64},
            )
        )
    with Session(ctx.engine) as session:
        fact = inspect(ctx, session)[0]
        assert fact.state == "invalid_legacy" and fact.target_tenant_id is None and not fact.is_valid


def test_native_candidate_target_server_change_requires_whole_transaction_retry(native_target):
    ctx = native_target
    with Session(ctx.engine) as session, session.begin():
        seed_default(session)
        session.add(LLMServer(id=4, tenant_id=101, name="moved", type="openai"))
    changed = []
    with Session(ctx.engine) as session:

        def move(state):
            if (
                state.is_select
                and state.statement._for_update_arg is not None
                and not changed
                and "llm_model" in str(state.statement)
            ):
                changed.append(True)
                state.session.execute(
                    update(LLMModel).where(LLMModel.tenant_id == 101, LLMModel.id == 11).values(server_id=4)
                )

        event.listen(session, "do_orm_execute", move)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            inspect(ctx, session)
        session.rollback()
    with Session(ctx.engine) as session:
        assert changed and session.get(LLMModel, 11).server_id == 1
