"""F026 transfer: caller-owned SQLite transactions, not a remote adapter test."""

from dataclasses import replace
from datetime import datetime

import pytest
from sqlalchemy import select

from bisheng.knowledge.domain.models.provider_control import (
    KnowledgeProviderBinding as Binding,
)
from bisheng.knowledge.domain.models.provider_control import (
    KnowledgeProviderGeneration as Gen,
)
from bisheng.knowledge.domain.models.provider_control import (
    KnowledgeProviderInstance as Instance,
)
from bisheng.knowledge.domain.models.provider_control import (
    KnowledgeProviderMapping as Mapping,
)
from bisheng.knowledge.domain.models.provider_control import (
    KnowledgeProviderOperation as Op,
)
from bisheng.knowledge.domain.models.provider_control import (
    KnowledgeProviderQuota as Quota,
)


@pytest.fixture(autouse=True)
def scope(tenant_context):
    tenant_context(17)


@pytest.fixture
async def seeded(async_db_session):
    s = async_db_session
    conn = await s.connection()
    for cls in (Instance, Gen, Binding, Mapping, Op, Quota):
        await conn.run_sync(cls.__table__.create, checkfirst=True)
    s.add(
        Instance(
            id=3,
            tenant_id=17,
            provider_key="weknora",
            endpoint="fixture",
            credential_ref="ref",
            remote_scope_id="org",
            state="ready",
            capability_revision=4,
        )
    )
    scope = {"tenant_id": 17, "space_id": 6}
    for n, state in [(1, "ready"), (2, "provisioning")]:
        s.add(
            Gen(
                **scope,
                generation=n,
                provider_instance_id=3,
                remote_scope_id="org",
                remote_kb_id=f"kb{n}",
                embedding_fingerprint=str(n) * 64,
                state=state,
                content_revision=1,
            )
        )
    s.add(Binding(**scope, provider_key="weknora", active_generation=1, state="ready"))
    s.add(
        Mapping(
            **scope,
            generation=1,
            resource_type="file",
            local_resource_id=33,
            version_id=45,
            logical_document_id=7,
            remote_object_id="old-file",
            ready_revision=1,
            lifecycle_state="active",
        )
    )
    s.add_all(
        [
            Quota(
                **scope,
                operation_id="ingest",
                version_id=45,
                subject_type=kind,
                subject_id=subject,
                accounting_kind="original_bytes",
                state="charged",
                byte_count=600,
                receipt_checksum="a" * 64,
            )
            for kind, subject in [("user", 9), ("tenant", 17)]
        ]
    )
    await s.commit()
    return s


async def frozen(s):
    from bisheng.knowledge.application.provider_transfer import freeze_transfer

    return await freeze_transfer(
        s, tenant_id=17, space_id=6, actor_user_id=9, request_key="move-1", target_generation=2, expected_revision=1
    )


async def test_verified_cutover_preserves_old_target_and_single_charge(seeded):
    from bisheng.knowledge.application.provider_transfer import FileProof, TransferProof, apply_transfer

    s = seeded
    from bisheng.knowledge.domain.repositories.provider_wiki_repository import WikiObservation, WikiScope

    binding = await s.scalar(select(Binding))
    binding.wiki_target_revision = binding.wiki_applied_revision = 12
    await s.commit()
    op = await frozen(s)
    wiki = WikiObservation(
        WikiScope(17, 6, 3, 2, "org", "kb2", op.expected_revision, 0, 0, op.operation_id, "provisioning"),
        {"success": True, "data": {"target_revision": 2, "applied_revision": 2, "ready": True, "empty": False}},
    )
    assert op.operation_id == (await frozen(s)).operation_id
    assert op.target_manifest[1]["version_id"] == 45
    s.add(
        Mapping(
            tenant_id=17,
            space_id=6,
            generation=2,
            resource_type="file",
            local_resource_id=33,
            version_id=45,
            logical_document_id=7,
            remote_object_id="new-file",
            ready_revision=1,
            lifecycle_state="active",
        )
    )
    await s.flush()
    proof = TransferProof(
        operation_id=op.operation_id,
        tenant_id=17,
        space_id=6,
        generation=2,
        instance_id=3,
        scope_id="org",
        kb_id="kb2",
        embedding_fingerprint="2" * 64,
        content_revision=1,
        wiki=wiki,
        files=(FileProof(33, 45, "new-file", 600, "a" * 64),),
    )
    from bisheng.knowledge.domain.repositories.provider_operation_repository import ProviderOperationRepository

    now = datetime.utcnow()
    op = await ProviderOperationRepository().claim(
        s, tenant_id=17, operation_id=op.operation_id, now=now, lease_seconds=120
    )
    args = {
        "tenant_id": 17,
        "operation_id": op.operation_id,
        "lease_token": op.lease_token,
        "expected_revision": op.revision,
        "now": now,
    }
    for bad in (
        replace(proof, wiki=None),
        replace(proof, wiki=replace(wiki, scope=replace(wiki.scope, remote_kb_id="kb1"))),
        replace(proof, wiki=replace(wiki, scope=replace(wiki.scope, generation=1))),
        replace(
            proof, wiki=replace(wiki, wire={"success": True, "data": {**wiki.wire["data"], "applied_revision": 1}})
        ),
        replace(proof, kb_id="kb1"),
        replace(proof, files=()),
        replace(proof, files=(replace(proof.files[0], checksum="b" * 64),)),
    ):
        assert not await apply_transfer(s, proof=bad, **args)
    # Unproved target Wiki keeps the barrier: the retired library's watermark (12)
    # must not be carried over, and it must not be zeroed as if it converged.
    kept = await s.scalar(select(Binding).execution_options(populate_existing=True))
    assert (kept.active_generation, kept.wiki_target_revision, kept.wiki_applied_revision) == (1, 12, 12)
    assert kept.pending_write_operation_id == op.operation_id
    assert await apply_transfer(s, proof=proof, **args)
    assert not await apply_transfer(s, proof=proof, **args)
    b = await s.scalar(select(Binding))
    assert (b.active_generation, b.wiki_target_revision, b.wiki_applied_revision, b.pending_write_operation_id) == (
        2,
        2,
        2,
        None,
    )
    assert (await s.scalar(select(Gen).where(Gen.generation == 1))).state == "retired"
    quota = (await s.scalars(select(Quota))).all()
    assert sorted((q.subject_type, q.version_id, q.byte_count, q.state) for q in quota) == [
        ("tenant", 45, 600, "charged"),
        ("user", 45, 600, "charged"),
    ]
    assert (await s.scalar(select(Mapping).where(Mapping.generation == 1))).remote_object_id == "old-file"


@pytest.mark.parametrize("transfer_first", [True, False])
async def test_tag_and_transfer_contend_for_committed_slot(seeded, async_db_engine, transfer_first):
    from unittest.mock import AsyncMock

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
    from bisheng.knowledge.application.provider_tags import ProviderTags, TagConflict, TagScope
    from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderTagRef
    from bisheng.knowledge.domain.repositories.provider_tag_repository import ProviderTagRepository

    s = seeded
    await (await s.connection()).run_sync(KnowledgeProviderTagRef.__table__.create, checkfirst=True)
    await s.commit()
    tags = ProviderTags(
        ProviderTagRepository(async_sessionmaker(async_db_engine)), AsyncMock(), authorize=AsyncMock(return_value=True)
    )
    scope = TagScope(17, 6, 1)
    if transfer_first:
        await frozen(s)
        await s.commit()
        with pytest.raises(TagConflict):
            await tags.edit(scope, 33, "clear", [], expected_revision=1)
        tags.port.edit_manual.assert_not_awaited()
    else:

        async def lost_ack(*args):
            b = await s.scalar(select(Binding))
            assert b.pending_write_operation_id
            from bisheng.knowledge.application.provider_transfer import freeze_transfer

            with pytest.raises(KnowledgeOperationPlanConflictError):
                await freeze_transfer(
                    s,
                    tenant_id=17,
                    space_id=6,
                    actor_user_id=9,
                    request_key="during-write",
                    target_generation=2,
                    expected_revision=b.revision,
                )
            await s.rollback()
            raise TimeoutError()

        tags.port.edit_manual.side_effect = lost_ack
        with pytest.raises(TimeoutError):
            await tags.edit(scope, 33, "clear", [], expected_revision=1)
        assert (await s.scalar(select(Binding))).pending_write_operation_id
        with pytest.raises(TagConflict):
            await tags.edit(scope, 33, "clear", [], expected_revision=1)
        assert tags.port.edit_manual.await_count == 1


async def test_committed_tag_edit_advances_the_revision_freeze_requires(seeded, async_db_engine):
    """Tag writes and the migration freeze share one binding write slot.

    A manual edit that committed (slot released, binding revision advanced) makes a
    freeze planned on the older revision fail its CAS, so the plan is re-read instead
    of retiring a library that was edited after the plan was formed.
    """
    from unittest.mock import AsyncMock

    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
    from bisheng.knowledge.application.provider_tags import ProviderTags, TagScope
    from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderTagRef
    from bisheng.knowledge.domain.repositories.provider_tag_repository import ProviderTagRepository

    s = seeded
    await (await s.connection()).run_sync(KnowledgeProviderTagRef.__table__.create, checkfirst=True)
    await s.commit()
    tags = ProviderTags(
        ProviderTagRepository(async_sessionmaker(async_db_engine)), AsyncMock(), authorize=AsyncMock(return_value=True)
    )
    scope = TagScope(17, 6, 1)
    stale_revision = await s.scalar(select(Binding.revision).where(Binding.tenant_id == 17, Binding.space_id == 6))
    await s.rollback()
    await tags.edit(scope, 33, "clear", [], expected_revision=1)
    tags.port.edit_manual.assert_awaited_once_with(scope, 33, "clear", (), 1)
    sessions = async_sessionmaker(async_db_engine)
    async with sessions() as db, db.begin():
        after = await db.scalar(
            select(Binding)
            .where(Binding.tenant_id == 17, Binding.space_id == 6)
            .execution_options(populate_existing=True)
        )
        assert after.pending_write_operation_id is None
        assert after.revision > stale_revision
        # A slot that is never released would block both cutover and every later edit.
        assert (
            await db.execute(
                update(Binding)
                .where(Binding.tenant_id == 17, Binding.space_id == 6, Binding.pending_write_operation_id.is_(None))
                .values(revision=Binding.revision)
            )
        ).rowcount == 1
    from bisheng.knowledge.application.provider_transfer import freeze_transfer

    with pytest.raises(KnowledgeOperationPlanConflictError):
        await freeze_transfer(
            s,
            tenant_id=17,
            space_id=6,
            actor_user_id=9,
            request_key="stale-plan",
            target_generation=2,
            expected_revision=stale_revision,
        )
    assert not (await s.scalars(select(Op))).all()


async def test_send_and_reconcile_only_against_frozen_targets(seeded):
    from datetime import timedelta
    from unittest.mock import AsyncMock

    from bisheng.knowledge.application.provider_transfer import execute_frozen_transfer
    from bisheng.knowledge.domain.repositories.provider_operation_repository import ProviderOperationRepository

    s = seeded
    op = await frozen(s)
    repository = ProviderOperationRepository()
    now = datetime.utcnow()
    op = await repository.claim(s, tenant_id=17, operation_id=op.operation_id, now=now, lease_seconds=10)
    await s.commit()
    port = AsyncMock()
    await execute_frozen_transfer(op, port=port, now=now)
    plan = port.reingest.await_args.args[0]
    assert (plan.source.kb_id, plan.target.kb_id, plan.files[0].remote_object_id) == ("kb1", "kb2", "old-file")
    op = await repository.claim(
        s, tenant_id=17, operation_id=op.operation_id, now=now + timedelta(seconds=12), lease_seconds=10
    )
    await s.commit()
    await execute_frozen_transfer(op, port=port, now=now + timedelta(seconds=12))
    assert port.reingest.await_count == 1 and port.readback.await_args.args == (plan,)


async def test_quarantine_cas_and_native_only_preflight(seeded):
    from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
    from bisheng.knowledge.application.provider_transfer import quarantine_generation, require_native_mutation

    s = seeded
    for operation in ("move", "copy", "link", "merge", "primary"):
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await require_native_mutation(s, tenant_id=17, space_id=6, operation=operation)
    assert not (await s.scalars(select(Op))).all()
    for ten, gen, rev in [(18, 1, 1), (17, 2, 1), (17, 1, 2)]:
        assert not await quarantine_generation(s, tenant_id=ten, space_id=6, generation=gen, expected_revision=rev)
    assert await quarantine_generation(s, tenant_id=17, space_id=6, generation=1, expected_revision=1)
    assert (await s.scalar(select(Binding))).state == "quarantined"
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await frozen(s)
