"""T926: actual plan/native TX cutover; P1 positive evidence follows its fixed prefix."""

from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanChangedError, KnowledgeOperationPlanConflictError
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.knowledge.domain.repositories.move_cutover_repository import MoveCutoverRepository
from bisheng.knowledge.domain.repositories.operation_plan_repository import OperationPlanRepository
from test.knowledge_unification import test_move_scope_repository as fixtures

store, tenant, moving = fixtures.store, fixtures.tenant, fixtures.moving
ACTOR = {"tenant_id": 101, "actor_user_id": 7, "entry_kind": "web", "required_action": "move", "space_id": 10}


async def confirmation(session, scope):
    return await OperationPlanRepository().acreate(
        session,
        operation="move",
        space_id=10,
        actor_reference=ACTOR,
        targets=[leaf.target for leaf in scope.leaves],
        target_revisions={"scope_digest": scope.scope_digest},
        source_revisions={"source": scope.source, "destination": scope.destination},
        parameters=scope.to_parameters(),
        impact={"logical_count": len(scope.files)},
        expires_at=datetime.now() + timedelta(hours=1),
    )


@pytest.mark.parametrize("tamper", ["metadata", "destination", "actor", "plan"])
async def test_reservation_reloads_real_scope_and_confirmation_before_issuing(moving, tamper):
    async with AsyncSession(moving.engine, expire_on_commit=False) as session:
        scope = await fixtures.load(moving, session)
        plan = await confirmation(session, scope)
        await session.commit()
        if tamper == "metadata":
            scope.files[1].after["user_metadata"]["keep"]["field_value"] = "changed"
        elif tamper == "destination":
            scope = replace(scope, destination_space_id=20, destination={**scope.destination, "id": 20})
        actor = {**ACTOR, "actor_user_id": 8} if tamper == "actor" else ACTOR
        digest = "f" * 64 if tamper == "plan" else plan.plan_digest
        repo = MoveCutoverRepository(scope_repository=moving.repo)
        with pytest.raises((KnowledgeOperationPlanConflictError, KnowledgeOperationPlanChangedError)):
            await repo.aprepare_reservation(
                session,
                scope=scope,
                confirmation_id=plan.confirmation_id,
                plan_digest=digest,
                actor_user_id=actor["actor_user_id"],
                actor_reference=actor,
            )
        assert (await session.get(KnowledgeFile, 81)).knowledge_id == 10


async def test_reservation_has_actual_native_tx_identity_and_never_moves_or_commits(moving):
    repo = MoveCutoverRepository(scope_repository=moving.repo)
    async with AsyncSession(moving.engine, expire_on_commit=False) as session:
        scope = await fixtures.load(moving, session)
        plan = await confirmation(session, scope)
        await session.commit()
        receipt = await repo.aprepare_reservation(
            session,
            scope=scope,
            confirmation_id=plan.confirmation_id,
            plan_digest=plan.plan_digest,
            actor_user_id=7,
            actor_reference=ACTOR,
        )
        assert len(receipt.job_id) == 36 and receipt.plan_id == plan.confirmation_id
        assert receipt.scope_digest == scope.scope_digest
        repo.assert_reservation_current(receipt, session)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            repo.assert_reservation_current(replace(receipt), session)
        assert (await session.get(KnowledgeFile, 81)).knowledge_id == 10
        await session.rollback()
        await session.execute(select(KnowledgeFile.id).limit(1))
        with pytest.raises(KnowledgeOperationPlanConflictError):
            repo.assert_reservation_current(receipt, session)
    async with AsyncSession(moving.engine) as session:
        stored = await session.get(KnowledgeOperationPlan, plan.confirmation_id)
        assert stored.operation_id is None


async def test_native_mutator_rejects_caller_pending_before_savepoint_autoflush(moving):
    async with AsyncSession(moving.engine) as session:
        scope = await fixtures.load(moving, session)
        plan = await confirmation(session, scope)
        await session.commit()
        other = await session.get(KnowledgeFile, 81)
        other.remark = "caller-owned-pending"
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await MoveCutoverRepository(scope_repository=moving.repo).aprepare_reservation(
                session,
                scope=scope,
                confirmation_id=plan.confirmation_id,
                plan_digest=plan.plan_digest,
                actor_user_id=7,
                actor_reference=ACTOR,
            )
        assert other in session.dirty and other.remark == "caller-owned-pending"


async def pipeline(moving, monkeypatch, *, zero=None, count=2):
    """Actual P1 runtime + SQL finalizer; only Catalog result/FGA transport isolated."""
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    import sqlalchemy as sa

    from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem
    from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
    from bisheng.knowledge.domain.repositories.processing_job_repository import JobLease
    from bisheng.permission.application.identity import PermissionActor
    from bisheng.permission.domain.models import AuthorizationModelRelease, PermissionCatalogRelease
    from bisheng.permission.domain.repositories.move_projection_repository import MoveProjectionExpectation
    from bisheng.permission.domain.schemas import VerifiedPermissionTarget
    from test.knowledge_unification.test_move_projection import compose

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(moving.engine, expire_on_commit=False) as session:
            yield session

    from bisheng.database.models.tag import TagLink
    from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
    from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
    from bisheng.knowledge.domain.models.knowledge_processing_job import processing_now

    async with sessions() as session:
        if zero == "empty":
            for model in (TagLink, KnowledgeDocumentVersion, KnowledgeDocument):
                await session.execute(sa.delete(model.__table__))
            await session.execute(
                sa.delete(KnowledgeFile).where(KnowledgeFile.id.in_((81, 82)), KnowledgeFile.tenant_id == 101)
            )
        elif zero == "all-skipped":
            await session.execute(
                sa.update(KnowledgeFile).where(KnowledgeFile.id == 81, KnowledgeFile.tenant_id == 101).values(status=3)
            )
        for n in range(3, count + 1):
            session.add(
                KnowledgeFile(
                    id=1000 + n,
                    tenant_id=101,
                    knowledge_id=10,
                    file_name=str(n),
                    file_level_path="/50",
                    level=1,
                    status=2,
                )
            )
            session.add(
                KnowledgeDocumentVersion(id=20000 + n, document_id=80, knowledge_file_id=1000 + n, version_no=n)
            )
        await session.commit()
    repo = MoveCutoverRepository(scope_repository=moving.repo)
    async with sessions() as session:
        scope = await fixtures.load(moving, session)
        plan = await confirmation(session, scope)
        await session.commit()
        receipt = await repo.aprepare_reservation(
            session,
            scope=scope,
            confirmation_id=plan.confirmation_id,
            plan_digest=plan.plan_digest,
            actor_user_id=7,
            actor_reference=ACTOR,
        )
        job_id = receipt.job_id
        await repo.aconsume_reservation(session, receipt)
        until = processing_now() + timedelta(minutes=10)
        session.add(
            KnowledgeProcessingJob(
                id=job_id,
                tenant_id=101,
                space_id=11,
                kind="move_index",
                state="running",
                actor_user_id=7,
                actor_reference=ACTOR,
                idempotency_key="native-" + job_id,
                request_hash="c" * 64,
                expected_model_config_revision=4,
                accepted_model_config_revision=4,
                expected_index_generation="generation-4",
                claim_generation=1,
                lease_token="lease-token",
                lease_until=until,
                total_count=sum(leaf.participates for leaf in scope.leaves),
            )
        )
        session.add_all(
            [
                KnowledgeProcessingItem(
                    id=f"item-{leaf.target.file_id:08d}",
                    tenant_id=101,
                    job_id=job_id,
                    file_id=leaf.target.file_id,
                    document_id=leaf.target.document_id,
                    version_id=leaf.target.version_id,
                    expected_space_id=11,
                    expected_parent_id=leaf.destination_parent_id,
                )
                for leaf in scope.leaves
                if leaf.participates
            ]
        )
        await session.commit()
    expectations = []
    for change in scope.parent_changes:
        common = {
            "tenant_id": 101,
            "resource_type": change.resource_type,
            "resource_id": str(change.resource_id),
            "resource_version": change.expected_permission_version,
        }
        before = VerifiedPermissionTarget.from_business_service(
            **common,
            parent_type=change.old_parent_type,
            parent_id=str(change.old_parent_id),
            context_version=scope.scope_digest,
        )
        after = VerifiedPermissionTarget.from_business_service(
            **common,
            parent_type=change.new_parent_type,
            parent_id=str(change.new_parent_id),
            context_version=scope.scope_digest,
        )
        expectations.append(
            MoveProjectionExpectation(
                job_id,
                101,
                change.resource_type,
                str(change.resource_id),
                before,
                after,
                change.mode,
                change.expected_permission_version,
                scope.changes_digest,
                (7,),
            )
        )
    built = await compose(SimpleNamespace(engine=moving.engine, sessions=sessions), monkeypatch, tuple(expectations))
    async with moving.engine.begin() as conn:
        await conn.execute(
            sa.insert(AuthorizationModelRelease),
            {
                "id": 1,
                "environment": "test",
                "store_id": "actual-store",
                "model_id": "actual-model",
                "model_version": "f048",
                "model_checksum": "a" * 64,
                "required_relations_checksum": "b" * 64,
                "openfga_version": "1",
                "status": "ACTIVE",
            },
        )
        await conn.execute(
            sa.insert(PermissionCatalogRelease),
            {
                "id": 1,
                "release_key": "current",
                "version": 1,
                "status": "CURRENT",
                "write_fenced": False,
                "required_authorization_model_release_id": 1,
                "draft_owner_id": 7,
                "idempotency_key": "catalog",
                "checksum": "c" * 64,
            },
        )
    assert (
        await built.bridge.aexecute_or_resume(
            job_id=job_id, changes=tuple(expectations), actor=PermissionActor(user_id=7, current_tenant_id=101)
        )
    ).complete
    repo.projection_verifier = built.bridge
    return SimpleNamespace(
        repo=repo,
        bridge=built.bridge,
        scope=scope,
        expectations=tuple(expectations),
        job_id=job_id,
        lease=JobLease(job_id, "lease-token", 1, until),
        sessions=sessions,
    )


async def prepared(session, built):
    from sqlalchemy import text

    # SQLite's legacy driver otherwise RELEASEs a first SAVEPOINT durably.
    await session.execute(text("BEGIN"))
    value = await built.repo.aprepare_cutover(session, job_id=built.job_id, lease=built.lease)
    evidence = await built.bridge.arequire_finalized(session, job_id=built.job_id, expectations=built.expectations)
    return value, evidence


async def test_actual_p1_native_evidence_applies_all_history_and_rolls_back_with_caller(moving, monkeypatch):
    from bisheng.database.models.tag import TagLink
    from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument

    built = await pipeline(moving, monkeypatch)
    async with built.sessions() as session:
        current, evidence = await prepared(session, built)
        receipt = await built.repo.aapply_logical(session, prepared=current, projection_evidence=evidence)
        built.repo.assert_logical_current(receipt, session)
        assert receipt.index_item_count == 1
        files = (
            (await session.execute(select(KnowledgeFile.__table__).where(KnowledgeFile.id.in_((50, 81, 82)))))
            .mappings()
            .all()
        )
        assert all(row["knowledge_id"] == 11 for row in files)
        assert {row["id"]: row["status"] for row in files} == {50: 5, 81: 4, 82: 7}
        assert (
            await session.execute(select(KnowledgeDocument.knowledge_id).where(KnowledgeDocument.id == 80))
        ).scalar_one() == 11
        assert (await session.execute(select(TagLink.id))).all() == []
        built.repo.consume_logical(receipt, session)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            built.repo.consume_logical(receipt, session)
        await session.rollback()
    async with built.sessions() as session:
        assert (await session.get(KnowledgeFile, 81)).knowledge_id == 10
        assert (await session.execute(select(TagLink.id))).all() == [(1,)]


async def test_committed_logical_after_is_idempotent_with_fresh_native_proof(moving, monkeypatch):
    import sqlalchemy as sa

    built = await pipeline(moving, monkeypatch)
    async with built.sessions() as session:
        current, evidence = await prepared(session, built)
        await built.repo.aapply_logical(session, prepared=current, projection_evidence=evidence)
        await session.commit()
    writes = []

    def record(conn, cursor, sql, params, context, many):
        if sql.lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE")):
            writes.append(sql)

    sa.event.listen(moving.engine.sync_engine, "before_cursor_execute", record)
    try:
        async with built.sessions() as session:
            current, evidence = await prepared(session, built)
            assert current.position == "after"
            await built.repo.aapply_logical(session, prepared=current, projection_evidence=evidence)
            await session.commit()
        assert not writes
    finally:
        sa.event.remove(moving.engine.sync_engine, "before_cursor_execute", record)


@pytest.mark.parametrize("bad", ["fake-proof", "stale-lease", "changed-root", "changed-prepared"])
async def test_bad_proof_lease_or_same_transaction_change_cannot_write(moving, monkeypatch, bad):
    import sqlalchemy as sa

    from bisheng.common.errcode.permission import PermissionPublishNotReadyError
    from bisheng.knowledge.domain.models.knowledge import Knowledge

    built = await pipeline(moving, monkeypatch)
    async with built.sessions() as session:
        current, evidence = await prepared(session, built)
        if bad == "fake-proof":
            evidence = {"ready": True}
        elif bad == "stale-lease":
            object.__setattr__(current, "claim_generation", 0)
        elif bad == "changed-root":
            await session.execute(
                sa.update(Knowledge)
                .where(Knowledge.id == 10, Knowledge.tenant_id == 101)
                .values(model_config_revision=99)
            )
        else:
            current.scope.files[1].after["knowledge_id"] = 999
        with pytest.raises(
            (KnowledgeOperationPlanConflictError, KnowledgeOperationPlanChangedError, PermissionPublishNotReadyError)
        ):
            await built.repo.aapply_logical(session, prepared=current, projection_evidence=evidence)
        assert (await session.get(KnowledgeFile, 81)).knowledge_id == 10


async def test_partial_sql_error_rolls_back_own_savepoint_even_if_caller_commits(moving, monkeypatch):
    import sqlalchemy as sa

    built = await pipeline(moving, monkeypatch)
    hit = []

    def inject(conn, cursor, sql, params, context, many):
        if not hit and sql.lstrip().upper().startswith("UPDATE KNOWLEDGEFILE"):
            hit.append(1)
            raise RuntimeError("after first real SQL write")

    async with built.sessions() as session:
        current, evidence = await prepared(session, built)
        sa.event.listen(moving.engine.sync_engine, "after_cursor_execute", inject)
        try:
            with pytest.raises(RuntimeError, match="first real SQL"):
                await built.repo.aapply_logical(session, prepared=current, projection_evidence=evidence)
        finally:
            sa.event.remove(moving.engine.sync_engine, "after_cursor_execute", inject)
        await session.commit()
    async with built.sessions() as session:
        assert hit and (await session.get(KnowledgeFile, 81)).knowledge_id == 10
        assert (await session.get(KnowledgeFile, 50)).knowledge_id == 10


@pytest.mark.parametrize("change", ["new-child", "new-tag"])
async def test_accepted_before_scope_cannot_quietly_lose_new_children_or_tags(moving, monkeypatch, change):
    import sqlalchemy as sa

    from bisheng.database.models.tag import TagLink

    built = await pipeline(moving, monkeypatch)
    async with built.sessions() as session:
        current, evidence = await prepared(session, built)
        if change == "new-child":
            await session.execute(
                sa.insert(KnowledgeFile).values(
                    id=83, tenant_id=101, knowledge_id=10, file_name="arrived", file_level_path="/50", level=1, status=3
                )
            )
        else:
            await session.execute(
                sa.insert(TagLink).values(id=2, tenant_id=101, tag_id=1, resource_id="82", resource_type=8)
            )
        with pytest.raises(KnowledgeOperationPlanChangedError):
            await built.repo.aapply_logical(session, prepared=current, projection_evidence=evidence)
        assert (await session.get(KnowledgeFile, 50)).knowledge_id == 10


@pytest.mark.parametrize("zero", ["empty", "all-skipped"])
async def test_real_zero_index_items_keep_real_logical_cutover_and_no_fake_file(moving, monkeypatch, zero):
    from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem

    built = await pipeline(moving, monkeypatch, zero=zero)
    async with built.sessions() as session:
        current, evidence = await prepared(session, built)
        receipt = await built.repo.aapply_logical(session, prepared=current, projection_evidence=evidence)
        assert receipt.index_item_count == 0
        assert (await session.execute(select(KnowledgeProcessingItem.id))).all() == []
        built.repo.assert_logical_current(receipt, session)
        await session.commit()
    async with built.sessions() as session:
        assert (await session.get(KnowledgeFile, 50)).knowledge_id == 11


async def test_native_item_projection_is_seek_paged_without_manifest_or_snapshot(moving, monkeypatch):
    import sqlalchemy as sa

    built = await pipeline(moving, monkeypatch, count=401)
    reads = []

    def record(conn, cursor, sql, params, context, many):
        if sql.lstrip().upper().startswith("SELECT") and "knowledge_processing_item" in sql:
            reads.append((sql, params))

    sa.event.listen(moving.engine.sync_engine, "before_cursor_execute", record)
    try:
        async with built.sessions() as session:
            await prepared(session, built)
        assert len(reads) >= 2
        assert all(
            "LIMIT" in sql.upper() and "processing_snapshot" not in sql and "scope_manifest" not in sql
            for sql, _ in reads
        )
        assert all(
            any(type(value) is str and (value == "" or value.startswith("item-")) for value in params)
            for _, params in reads
        )
    finally:
        sa.event.remove(moving.engine.sync_engine, "before_cursor_execute", record)
