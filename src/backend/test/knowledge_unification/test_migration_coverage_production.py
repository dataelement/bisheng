"""Real Run-backed Coverage facade; no fixture SqlLedger can certify production."""

import importlib

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError
from bisheng.core.context.tenant import current_tenant_id
from bisheng.knowledge.domain.models.knowledge_unification_run import KnowledgeUnificationRun as Run
from bisheng.knowledge.domain.services.unification_fingerprints import digest
from bisheng.resource_reference.application.contracts import SourceType, tenant_inventory_digest
from bisheng.resource_reference.domain.repositories.coverage_repository import CoverageRepository
from test.knowledge_unification.test_migration_ledger import ledger as ledger


@pytest.fixture
def module():
    return importlib.import_module("bisheng.knowledge.application.unification_coverage")


def certificate(tenant, *, epoch=1, run="coverage-native", superseded=()):
    proof = {
        "extractor_version": "native-v1",
        "root_count": 0,
        "source_count": 0,
        "zero_reference_count": 0,
        "reference_count": 0,
        "valid_count": 0,
        "invalid_legacy_count": 0,
        "invalid_deleted_count": 0,
        "source_digest": digest([]),
        "reference_digest": digest([]),
    }
    value = {
        "schema_version": 1,
        "tenant_id": tenant,
        "run_id": run,
        "writer_contract_version": "f118-v1",
        "origin": "migration",
        "coverage_epoch": epoch,
        "baseline_hash": "a" * 64,
        "plan_hash": "b" * 64,
        "source_types": [kind.value for kind in SourceType],
        "proofs": {kind.value: dict(proof) for kind in SourceType},
        "superseded_ledger_count": len(superseded),
        "superseded_ledger_digest": digest(list(superseded)),
    }
    value["certificate_digest"] = digest(value)
    return value


async def seed(engine, tenant, *, cert=None, **changes):
    cert = certificate(tenant) if cert is None else cert
    values = {
        "id": f"ready-{tenant}",
        "tenant_id": tenant,
        "run_id": cert["run_id"],
        "origin": "migration",
        "phase": "completed",
        "writer_contract_version": "f118-v1",
        "baseline_hash": "a" * 64,
        "plan_hash": "b" * 64,
        "baseline_ref": {"object_key": "native/baseline", "sha256": "a" * 64},
        "plan_ref": {"object_key": "native/plan", "sha256": "b" * 64},
        "source_coverage": {kind.value: True for kind in SourceType},
        "verification_report": {"reference_coverage": cert},
        "coverage_epoch": cert["coverage_epoch"],
    }
    values.update(changes)
    async with AsyncSession(engine) as session, session.begin():
        session.add(Run(**values))


def test_nullable_indexed_epoch_is_not_an_implicit_ready_default():
    column = Run.__table__.c.coverage_epoch
    assert isinstance(column.type, sa.BigInteger) and column.nullable and column.server_default is None
    assert any(
        tuple(part.name for part in index.columns) == ("writer_contract_version", "coverage_epoch", "tenant_id")
        for index in Run.__table__.indexes
    )


async def test_factory_is_real_same_session_facade_and_no_missing_row_fallback(module, ledger):
    async with AsyncSession(ledger) as session, session.begin():
        repository = module.production_coverage_factory(session)
        assert isinstance(repository, CoverageRepository)
        assert repository.port is repository.global_port
        assert repository.port.session is session
        with pytest.raises(ReferenceCoverageNotReadyError):
            await repository.arequire_ready()
        with pytest.raises(ReferenceCoverageNotReadyError):
            await repository.arequire_global_ready()
        assert not session.new and not session.dirty and session.in_transaction()


async def test_complete_actual_tenants_and_six_typed_proofs_are_required(module, ledger):
    await seed(ledger, 101)
    async with AsyncSession(ledger) as session, session.begin():
        with pytest.raises(ReferenceCoverageNotReadyError):
            await module.production_coverage_factory(session).arequire_global_ready()
    await seed(ledger, 202)
    async with AsyncSession(ledger) as session, session.begin():
        repository = module.production_coverage_factory(session)
        assert len(await repository.arequire_ready()) == 6
        value = await repository.arequire_global_ready()
        assert value.verified_tenant_ids == (101, 202) and value.coverage_epoch == 1
        assert value.tenant_inventory_hash == tenant_inventory_digest((101, 202))


@pytest.mark.parametrize(
    "bad", ["epoch_null", "epoch_bool", "phase", "writer", "missing_type", "extra", "count", "digest", "descriptor"]
)
async def test_tampered_or_incomplete_real_certificate_never_becomes_ready(module, ledger, bad):
    cert = certificate(101)
    changes = {}
    if bad == "epoch_null":
        changes["coverage_epoch"] = None
    elif bad == "epoch_bool":
        cert["coverage_epoch"] = True
    elif bad == "phase":
        changes["phase"] = "verifying"
    elif bad == "writer":
        changes["writer_contract_version"] = "other"
    elif bad == "missing_type":
        del cert["proofs"][SourceType.ASSISTANT.value]
    elif bad == "extra":
        cert["unknown"] = True
    elif bad == "count":
        cert["proofs"][SourceType.ASSISTANT.value]["reference_count"] = 1
    elif bad == "digest":
        cert["certificate_digest"] = "0" * 64
    else:
        changes["baseline_ref"] = {"object_key": "native/baseline", "sha256": "0" * 64}
    await seed(ledger, 101, cert=cert, **changes)
    async with AsyncSession(ledger) as session, session.begin():
        with pytest.raises(ReferenceCoverageNotReadyError):
            await module.production_coverage_factory(session).arequire_ready()


async def test_new_unregistered_tenant_and_new_pending_run_invalidate_tail(module, ledger):
    await seed(ledger, 101)
    await seed(ledger, 202)
    async with AsyncSession(ledger) as session, session.begin():
        repository = module.production_coverage_factory(session)
        before = await repository.arequire_global_ready()
        await session.execute(
            sa.insert(Run.__table__).values(
                id="new",
                tenant_id=101,
                run_id="new-run",
                phase="preparing",
                writer_contract_version="f118-v1",
                baseline_ref={},
                plan_ref={},
                checkpoints={},
                source_coverage={},
                verification_report={},
            )
        )
        with pytest.raises(ReferenceCoverageNotReadyError):
            await repository.arequire_global_ready(
                expected_epoch=before.coverage_epoch, expected_inventory_hash=before.tenant_inventory_hash
            )


async def test_native_tenant_and_transaction_drift_never_leaks_a_partial_status(module, ledger, monkeypatch):
    await seed(ledger, 101)
    async with AsyncSession(ledger) as session, session.begin():
        original = session.execute
        token = None

        async def changed(*args, **kwargs):
            nonlocal token
            value = await original(*args, **kwargs)
            token = current_tenant_id.set(202)
            return value

        monkeypatch.setattr(session, "execute", changed)
        try:
            with pytest.raises(ReferenceCoverageNotReadyError):
                await module.production_coverage_factory(session).arequire_ready()
        finally:
            if token is not None:
                current_tenant_id.reset(token)


async def test_trusted_success_covers_old_failed_run_but_later_mutation_is_not_covered(module, ledger):
    async with AsyncSession(ledger) as session, session.begin():
        session.add(
            Run(
                id="old-failed",
                tenant_id=101,
                run_id="old",
                phase="failed",
                error_code=10994,
                error_reason="old_failure",
                checkpoints={"_failed_from_phase": "preparing"},
            )
        )
    async with AsyncSession(ledger) as session, session.begin():
        rows = (await session.execute(sa.select(Run.__table__))).mappings().all()
        count, fingerprint = module.ledger_inventory(rows)
    cert = certificate(101)
    cert["superseded_ledger_count"], cert["superseded_ledger_digest"] = count, fingerprint
    cert["certificate_digest"] = digest({key: value for key, value in cert.items() if key != "certificate_digest"})
    await seed(ledger, 101, cert=cert)
    async with AsyncSession(ledger) as session, session.begin():
        repository = module.production_coverage_factory(session)
        assert len(await repository.arequire_ready()) == 6
        await session.execute(
            sa.update(Run.__table__).where(Run.__table__.c.id == "old-failed").values(error_reason="changed")
        )
        with pytest.raises(ReferenceCoverageNotReadyError):
            await repository.arequire_ready()


async def test_new_tenant_without_creation_certificate_invalidates_global_inventory(module, ledger):
    from bisheng.database.models.tenant import Tenant

    await seed(ledger, 101)
    await seed(ledger, 202)
    async with AsyncSession(ledger) as session, session.begin():
        repository = module.production_coverage_factory(session)
        before = await repository.arequire_global_ready()
        await session.execute(sa.insert(Tenant.__table__).values(id=303, tenant_code="third", tenant_name="Third"))
        with pytest.raises(ReferenceCoverageNotReadyError):
            await repository.arequire_global_ready(
                expected_epoch=before.coverage_epoch, expected_inventory_hash=before.tenant_inventory_hash
            )
