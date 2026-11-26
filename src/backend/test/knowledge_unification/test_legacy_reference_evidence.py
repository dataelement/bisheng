"""T288: migration proof belongs to the original source and frozen run.

覆盖 AC: AC-89, AC-91, AC-93
No object-storage I/O occurs in an online reference transaction.
"""

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import Session, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError, ResourceReferenceInvalidError
from bisheng.core.database import tenant_filter
from bisheng.knowledge.application.reference_legacy_evidence import KnowledgeLegacyReferenceEvidence
from bisheng.knowledge.domain.models.knowledge_unification_run import KnowledgeUnificationRun
from bisheng.resource_reference.application.contracts import SourceKey, TargetKey
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from test.knowledge_unification import test_ref_repo as refs

tenant_events = refs.tenant_events
KEY = SourceKey(101, "assistant", "a1", "current")
TARGET = TargetKey("model", "7")
TABLES = [KnowledgeUnificationRun.__table__, BusinessResourceReference.__table__]


def records(**run_changes):
    run = KnowledgeUnificationRun(
        tenant_id=101,
        run_id="run-1",
        origin="migration",
        phase="verified",
        baseline_hash="a" * 64,
        plan_hash="b" * 64,
        baseline_ref={"object_key": "runs/run-1/baseline.json", "sha256": "a" * 64},
        plan_ref={"object_key": "runs/run-1/plan.json", "sha256": "b" * 64},
    )
    for key, value in run_changes.items():
        setattr(run, key, value)
    row = BusinessResourceReference(
        tenant_id=101,
        source_type="assistant",
        source_id="a1",
        source_version="current",
        slot_key="model",
        target_type="model",
        target_id="7",
        target_tenant_id=None,
        source_revision=1,
        legacy_invalid_reason="target_missing",
        legacy_run_id="run-1",
        legacy_evidence_key="ev-1",
    )
    return run, row


@pytest.fixture
def evidence_engine(f118_engine, monkeypatch):
    monkeypatch.setattr(
        tenant_filter, "_tenant_aware_tables", tenant_filter._tenant_aware_tables | {t.name for t in TABLES}
    )
    SQLModel.metadata.create_all(f118_engine, tables=TABLES)
    return f118_engine


def test_frozen_run_and_exact_original_slot_produce_proof(evidence_engine):
    with Session(evidence_engine) as session:
        session.add_all(records())
        session.commit()
        proof = KnowledgeLegacyReferenceEvidence().resolve(session, KEY, TARGET, run_id="run-1", evidence_key="ev-1")
        assert (proof.run_id, proof.baseline_hash, proof.evidence_key) == ("run-1", "a" * 64, "ev-1")


@pytest.mark.parametrize(
    "changes",
    [
        {"phase": "preparing"},
        {"phase": "failed"},
        {"origin": "empty_tenant"},
        {"baseline_ref": {}},
        {"baseline_ref": {"object_key": "runs/baseline", "sha256": "c" * 64}},
        {"plan_ref": {}},
        {"baseline_hash": None},
    ],
)
def test_unfrozen_or_inconsistent_ledger_cannot_certify_legacy(evidence_engine, changes):
    with Session(evidence_engine) as session:
        session.add_all(records(**changes))
        session.commit()
        with pytest.raises(ReferenceCoverageNotReadyError):
            KnowledgeLegacyReferenceEvidence().resolve(session, KEY, TARGET, run_id="run-1", evidence_key="ev-1")


@pytest.mark.parametrize(
    "source,target,key",
    [
        (KEY, TARGET, "wrong"),
        (KEY, TargetKey("model", "8"), "ev-1"),
        (SourceKey(101, "assistant", "copy", "current"), TARGET, "ev-1"),
    ],
)
def test_proof_cannot_be_borrowed_by_another_source_target_or_key(evidence_engine, source, target, key):
    with Session(evidence_engine) as session:
        session.add_all(records())
        session.commit()
        with pytest.raises(ResourceReferenceInvalidError):
            KnowledgeLegacyReferenceEvidence().resolve(session, source, target, run_id="run-1", evidence_key=key)


async def test_native_async_proof_uses_callers_transaction(monkeypatch):
    monkeypatch.setattr(
        tenant_filter, "_tenant_aware_tables", tenant_filter._tenant_aware_tables | {t.name for t in TABLES}
    )
    engine = create_async_engine("sqlite+aiosqlite://")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(lambda c: SQLModel.metadata.create_all(c, tables=TABLES))
        with refs.tenant(101):
            async with AsyncSession(engine) as session:
                session.add_all(records())
                await session.flush()
                proof = await KnowledgeLegacyReferenceEvidence().aresolve(
                    session, KEY, TARGET, run_id="run-1", evidence_key="ev-1"
                )
                assert proof.baseline_hash == "a" * 64
                await session.rollback()
                with pytest.raises(ResourceReferenceInvalidError):
                    await KnowledgeLegacyReferenceEvidence().aresolve(
                        session, KEY, TARGET, run_id="run-1", evidence_key="ev-1"
                    )
    finally:
        await engine.dispose()
