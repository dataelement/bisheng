"""§119: native K1/ready and derived direct File reference ownership."""

import asyncio
from copy import copy
from types import SimpleNamespace

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ResourceReferenceInvalidError
from bisheng.core.context.tenant import bypass_tenant_filter, tenant_execution_scope
from bisheng.knowledge.application.reference_target_owner import KnowledgeReferenceTargetOwner
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile as File
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob as Job
from bisheng.knowledge.domain.repositories.move_cutover_repository import MoveCutoverRepository
from bisheng.resource_reference.application.contracts import ReferenceSpec, TargetKey, reference_set_digest
from bisheng.resource_reference.application.target_verification import ReferenceTargetVerifier
from bisheng.resource_reference.application.write_runtime import ReferenceBindingRuntime
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet as Source
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference as BRR
from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository
from test.knowledge_unification import test_move_execution_repository as fixtures
from test.knowledge_unification.test_move_execution_fixtures import logical, mark, pipeline

store, tenant, moving, accepted = fixtures.store, fixtures.tenant, fixtures.moving, fixtures.accepted


def compose(built, *, cutover=None):
    owner = KnowledgeReferenceTargetOwner(move_cutover=cutover or built.cutover)
    verifier = ReferenceTargetVerifier({"knowledge_file": owner, "knowledge_space": owner})
    repository = ReferenceRepository(verifier=verifier)
    return SimpleNamespace(owner=owner, runtime=ReferenceBindingRuntime(repository, verifier), repo=repository)


def binding(ident, file_id=81, **changes):
    return {
        **{
            "id": ident,
            "tenant_id": 101,
            "source_type": "assistant",
            "source_id": "actual-source",
            "source_version": "current",
            "slot_key": f"files[{ident}]",
            "target_type": "knowledge_file",
            "target_id": str(file_id),
            "target_tenant_id": 101,
            "target_space_id": "10",
            "source_revision": 4,
            "legacy_invalid_reason": None,
            "legacy_run_id": None,
            "legacy_evidence_key": None,
        },
        **changes,
    }


async def seed(built, *, rows=None):
    rows = rows or [binding(ident, file_id) for ident, file_id in enumerate((50, 81, 82), 1)]
    async with built.sessions() as session, session.begin():
        for model in (BRR, Source, ResourceReferenceTombstone):
            await session.run_sync(
                lambda native, model=model: model.__table__.create(native.connection(), checkfirst=True)
            )
        await session.execute(sa.insert(BRR.__table__), rows)
        sources = {}
        for row in rows:
            key = row["tenant_id"], row["source_type"], row["source_id"], row["source_version"]
            sources.setdefault(key, []).append(
                ReferenceSpec(row["slot_key"], TargetKey(row["target_type"], row["target_id"]))
            )
        await session.execute(
            sa.insert(Source.__table__),
            [
                {
                    "tenant_id": key[0],
                    "source_type": key[1],
                    "source_id": key[2],
                    "source_version": key[3],
                    "source_revision": 4,
                    "extractor_version": "native-original",
                    "digest": reference_set_digest(tuple(specs)),
                    "effective": True,
                    "ready": True,
                    "record_kind": "source",
                }
                for key, specs in sources.items()
            ],
        )


async def facts(built):
    async with built.sessions() as session:
        with bypass_tenant_filter():
            refs = (await session.execute(sa.select(BRR.__table__).order_by(BRR.id))).mappings().all()
            sources = (await session.execute(sa.select(Source.__table__).order_by(Source.id))).mappings().all()
            files = (
                await session.execute(sa.select(File.id, File.knowledge_id).where(File.id.in_((50, 81, 82))))
            ).all()
            marker = (
                await session.execute(sa.select(Job.move_logical_marker).where(Job.id == built.job_id))
            ).scalar_one()
        return [dict(row) for row in refs], [dict(row) for row in sources], files, marker


@pytest.fixture
async def built(moving, accepted, monkeypatch):
    result = await pipeline(moving, accepted, monkeypatch)
    await seed(result)
    return result


async def test_real_k1_ready_updates_dir_history_nonparticipating_and_only_derived_column(built):
    async with built.sessions() as session, session.begin():
        await session.execute(
            sa.insert(BRR.__table__),
            [
                binding(4, 51),
                binding(5, 10, target_type="knowledge_space"),
                binding(6, 1, target_type="model", target_space_id=None),
                binding(
                    7,
                    999,
                    target_tenant_id=None,
                    target_space_id=None,
                    legacy_invalid_reason="target_missing",
                    legacy_run_id="old-run",
                    legacy_evidence_key="old-key",
                ),
            ],
        )
    before, sources, _, _ = await facts(built)
    rt = compose(built)
    async with built.sessions() as session, session.begin():
        async with session.begin_nested():
            receipt = await logical(session, built)
            assert await rt.owner.amove_file_ownership(session, logical=receipt, reference_runtime=rt.runtime) == 3
            assert len(await rt.repo.alist_inbound_space(session, "11")) == 3
            assert [row.id for row in await rt.repo.alist_inbound_space(session, "10")] == [4, 5]
            await mark(session, built, receipt)
    after, current_sources, files, marker = await facts(built)
    assert current_sources == sources and marker is not None and all(row.knowledge_id == 11 for row in files)
    assert after == [{**row, "target_space_id": "11"} if row["id"] <= 3 else row for row in before]


@pytest.mark.parametrize(
    "bad", ["legacy", "space_null", "space_other", "source_foreign", "target_foreign", "target_null"]
)
async def test_bad_late_page_zero_update_and_common_sp_outer_catch_commit(built, bad):
    async with built.sessions() as session, session.begin():
        await session.execute(sa.insert(BRR.__table__), [binding(10 + n) for n in range(401)])
        values = {"target_space_id": None if bad == "space_null" else "30"}
        if bad == "legacy":
            values = {
                "legacy_invalid_reason": "target_missing",
                "legacy_run_id": "original-run",
                "legacy_evidence_key": "original-key",
            }
        elif bad == "source_foreign":
            values = {"tenant_id": 202}
            await session.execute(
                sa.insert(Source.__table__),
                {
                    "tenant_id": 202,
                    "source_type": "assistant",
                    "source_id": "actual-source",
                    "source_version": "current",
                    "source_revision": 4,
                    "extractor_version": "original",
                    "digest": "a" * 64,
                    "effective": True,
                    "ready": True,
                    "record_kind": "source",
                },
            )
        elif bad == "target_foreign":
            values = {"target_tenant_id": 202}
        elif bad == "target_null":
            values = {
                "target_tenant_id": None,
                "legacy_invalid_reason": "target_missing",
                "legacy_run_id": "old",
                "legacy_evidence_key": "old",
            }
        await session.execute(sa.update(BRR.__table__).where(BRR.id == 410).values(**values))
    before = await facts(built)
    rt, writes = compose(built), []

    def capture(connection, cursor, statement, parameters, context, many):
        if statement.lstrip().upper().startswith("UPDATE BUSINESS_RESOURCE_REFERENCE"):
            writes.append(statement)

    async with built.sessions() as session:
        engine = session.bind.sync_engine
    sa.event.listen(engine, "before_cursor_execute", capture)
    try:
        async with built.sessions() as session, session.begin():
            with pytest.raises((ResourceReferenceInvalidError, KnowledgeOperationPlanConflictError, ValueError)):
                async with session.begin_nested():
                    receipt = await logical(session, built)
                    await rt.owner.amove_file_ownership(session, logical=receipt, reference_runtime=rt.runtime)
                    await mark(session, built, receipt)
        assert not writes
        assert await facts(built) == before
    finally:
        sa.event.remove(engine, "before_cursor_execute", capture)


@pytest.mark.parametrize(
    "bad", ["missing_issuer", "wrong_issuer", "bare", "copied", "nested", "wrong_tenant", "bypass", "wrong_runtime"]
)
async def test_original_logical_issuer_tx_tenant_and_registered_runtime_required(built, bad):
    rt = compose(built)
    async with built.sessions() as session, session.begin():
        receipt = await logical(session, built)
        if bad == "missing_issuer":
            rt.owner = KnowledgeReferenceTargetOwner()
        elif bad == "wrong_issuer":
            rt = compose(built, cutover=MoveCutoverRepository())
        elif bad == "bare":
            receipt = {"job_id": built.job_id}
        elif bad == "copied":
            receipt = copy(receipt)
        elif bad == "wrong_runtime":
            rt.runtime.repository.verifier = None

        async def call():
            await rt.owner.amove_file_ownership(session, logical=receipt, reference_runtime=rt.runtime)

        if bad == "nested":
            async with session.begin_nested():
                with pytest.raises((ResourceReferenceInvalidError, KnowledgeOperationPlanConflictError, ValueError)):
                    await call()
        elif bad == "wrong_tenant":
            with (
                tenant_execution_scope(202),
                pytest.raises((ResourceReferenceInvalidError, KnowledgeOperationPlanConflictError, ValueError)),
            ):
                await call()
        elif bad == "bypass":
            with (
                bypass_tenant_filter(),
                pytest.raises((ResourceReferenceInvalidError, KnowledgeOperationPlanConflictError, ValueError)),
            ):
                await call()
        else:
            with pytest.raises((ResourceReferenceInvalidError, KnowledgeOperationPlanConflictError, ValueError)):
                await call()


@pytest.mark.parametrize("failure", ["ready", "late_cancel"])
async def test_r2_then_ready_failure_common_sp_cannot_outer_commit_partial(built, monkeypatch, failure):
    rt = compose(built)
    before = await facts(built)

    class LateCancel(Exception):
        pass

    async with built.sessions() as session, session.begin():
        with pytest.raises(asyncio.CancelledError if failure == "late_cancel" else LateCancel):
            async with session.begin_nested():
                receipt = await logical(session, built)
                assert await rt.owner.amove_file_ownership(session, logical=receipt, reference_runtime=rt.runtime) == 3
                if failure == "late_cancel":
                    raise asyncio.CancelledError()

                # A real ready call updates Item then fails its final Job UPDATE.
                def fail(connection, cursor, statement, parameters, context, many):
                    if statement.startswith("UPDATE knowledge_processing_job SET move_logical_marker"):
                        raise LateCancel()

                sa.event.listen(session.bind.sync_engine, "before_cursor_execute", fail)
                try:
                    await mark(session, built, receipt)
                finally:
                    sa.event.remove(session.bind.sync_engine, "before_cursor_execute", fail)
                raise AssertionError("expected the real Job marker write to fail")
    assert await facts(built) == before


async def test_replay_actual_after_no_update_and_old_tx_reject(built):
    rt = compose(built)
    async with built.sessions() as session, session.begin():
        receipt = await logical(session, built)
        assert await rt.owner.amove_file_ownership(session, logical=receipt, reference_runtime=rt.runtime) == 3
        assert await rt.owner.amove_file_ownership(session, logical=receipt, reference_runtime=rt.runtime) == 0
    async with built.sessions() as session, session.begin():
        with pytest.raises((ResourceReferenceInvalidError, KnowledgeOperationPlanConflictError, ValueError)):
            await rt.owner.amove_file_ownership(session, logical=receipt, reference_runtime=rt.runtime)
