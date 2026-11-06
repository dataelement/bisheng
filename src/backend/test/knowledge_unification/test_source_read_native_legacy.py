"""T427: native legacy proof is exact-source and frozen, not a guessed target.

覆盖 AC: AC-89, AC-91, AC-93
"""

from copy import copy

import pytest
from sqlalchemy import update
from sqlmodel import Session

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError, ResourceReferenceInvalidError
from bisheng.knowledge.application.reference_read_legacy_evidence import KnowledgeReferenceReadLegacyEvidence
from bisheng.knowledge.domain.models.knowledge_unification_run import KnowledgeUnificationRun
from bisheng.resource_reference.application.contracts import TargetKey
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from test.knowledge_unification import test_source_read_native as natives
from test.knowledge_unification import test_source_read_scope as scopes

source_tenant = scopes.source_tenant
native = natives.native


@pytest.fixture
def legacy(native):
    KnowledgeUnificationRun.__table__.create(native.engine)
    with Session(native.engine) as session:
        session.execute(
            update(BusinessResourceReference).values(
                target_tenant_id=None,
                legacy_invalid_reason="target_missing",
                legacy_run_id="r",
                legacy_evidence_key="proof",
            )
        )
        session.add(
            KnowledgeUnificationRun(
                tenant_id=101,
                run_id="r",
                phase="verified",
                baseline_hash="a" * 64,
                plan_hash="b" * 64,
                baseline_ref={"object_key": "101/baseline", "sha256": "a" * 64},
                plan_ref={"object_key": "101/plan", "sha256": "b" * 64},
            )
        )
        session.commit()
    native.legacy = KnowledgeReferenceReadLegacyEvidence(native.verifier)
    return native


def proof(ctx, session, scope, *, identity=None, target=None, run_id="r", evidence_key="proof"):
    return ctx.legacy.resolve(
        session,
        scope,
        target or TargetKey("model", "11"),
        run_id=run_id,
        evidence_key=evidence_key,
        identity=identity or ctx.identity,
    )


def test_native_legacy_reads_original_provenance_without_orm_or_mutation(legacy):
    with Session(legacy.engine) as session:
        scope = legacy.verifier.issue_scope(session, scopes.REQUEST, legacy.identity)
        result = proof(legacy, session, scope)
        assert result.run_id == "r" and result.baseline_hash == "a" * 64 and result.evidence_key == "proof"
        assert not session.identity_map and not session.new and not session.dirty


@pytest.mark.parametrize("case", ["scope", "identity", "target", "run", "key", "unmarked"])
def test_native_legacy_is_not_transferable_to_another_source_claim(legacy, case):
    with Session(legacy.engine) as session:
        if case == "unmarked":
            session.execute(update(BusinessResourceReference).values(legacy_invalid_reason=None))
            session.commit()
        scope = legacy.verifier.issue_scope(session, scopes.REQUEST, legacy.identity)
        args = {}
        if case == "scope":
            scope = copy(scope)
        elif case == "identity":
            args["identity"] = copy(legacy.identity)
        elif case == "target":
            args["target"] = TargetKey("model", "12")
        elif case == "run":
            args["run_id"] = "other"
        elif case == "key":
            args["evidence_key"] = "other"
        with pytest.raises(ResourceReferenceInvalidError):
            proof(legacy, session, scope, **args)


@pytest.mark.parametrize(
    "values",
    [
        {"phase": "preparing"},
        {"phase": "failed"},
        {"origin": "empty_tenant"},
        {"baseline_ref": {"object_key": "/tmp/local", "sha256": "a" * 64}},
        {"plan_ref": {"object_key": "101/plan", "sha256": "c" * 64}},
    ],
)
def test_native_legacy_requires_original_frozen_durable_artifacts(legacy, values):
    with Session(legacy.engine) as session:
        session.execute(update(KnowledgeUnificationRun).values(**values))
        session.commit()
        scope = legacy.verifier.issue_scope(session, scopes.REQUEST, legacy.identity)
        with pytest.raises(ReferenceCoverageNotReadyError):
            proof(legacy, session, scope)
