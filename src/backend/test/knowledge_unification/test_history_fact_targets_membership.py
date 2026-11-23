"""Native bounded after reads retain global diagnostics without deployment writes."""

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.common.models.space_channel_member import SpaceChannelMember as Member
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.repositories.unification_history_view_repository import HistoryFactView
from bisheng.knowledge.domain.repositories.unification_space_membership_repository import (
    UnificationSpaceMembershipRepository,
)
from bisheng.knowledge.domain.repositories.unification_target_repository import KnowledgeMigrationTargetRepository
from bisheng.resource_reference.application.contracts import SourceKey, TargetKey
from test.knowledge_unification.test_migration_space_membership_global import control_native as control_native
from test.knowledge_unification.test_migration_space_membership_global import native as membership_native  # noqa: F401
from test.knowledge_unification.test_migration_space_membership_inventory import member


@pytest.fixture
async def native(membership_native):  # noqa: F811
    async with membership_native.engine.begin() as connection:
        await connection.run_sync(lambda conn: KnowledgeFile.__table__.create(conn, checkfirst=True))
    return membership_native


@pytest.mark.parametrize("scope", [101, 202])
async def test_exact_targets_use_after_file_owner_parent_and_deletion_without_hiding_foreign_root(native, scope):
    await native.insert(
        KnowledgeFile,
        [
            {"id": 31, "tenant_id": 202, "knowledge_id": 1, "file_type": 1, "file_name": "owner-repair"},
            {"id": 32, "tenant_id": 101, "knowledge_id": 2, "file_type": 1, "file_name": "parent-repair"},
            {"id": 33, "tenant_id": 101, "knowledge_id": 999, "file_type": 1, "file_name": "orphan"},
        ],
    )
    async with native.engine.connect() as connection:
        rows = {
            row["id"]: dict(row) for row in (await connection.execute(sa.select(KnowledgeFile.__table__))).mappings()
        }
    view = HistoryFactView()
    try:
        view.replace("knowledgefile", rows[31], {**rows[31], "tenant_id": 101})
        view.replace("knowledgefile", rows[32], {**rows[32], "knowledge_id": 1})
        view.replace("knowledgefile", rows[33], None)
        native.writes.clear()
        with tenant_execution_scope(scope):
            async with AsyncSession(native.engine) as session, session.begin():
                facts = await KnowledgeMigrationTargetRepository(fact_view=view).ainspect(
                    session,
                    source_key=SourceKey(scope, "assistant", "native-source", "current"),
                    targets=(
                        TargetKey("knowledge_file", 31),
                        TargetKey("knowledge_file", 32),
                        TargetKey("knowledge_file", 33),
                        TargetKey("knowledge_space", 2),
                    ),
                )
        assert (facts[0].target_tenant_id, facts[0].space_tenant_id) == (101, 101)
        assert (facts[1].knowledge_id, facts[1].space_tenant_id, facts[1].knowledge_type) == (1, 101, 0)
        assert not facts[2].exists and facts[3].exists and facts[3].target_tenant_id == 202
        assert not native.writes
    finally:
        view.close()


async def test_after_member_counts_and_paging_do_not_stop_on_deleted_first_page(native):
    await native.insert(Member, [member(index) for index in range(1, 204)])
    async with native.engine.connect() as connection:
        rows = tuple((await connection.execute(sa.select(Member.__table__).where(Member.id <= 201))).mappings())
    view = HistoryFactView()
    try:
        for row in rows:
            view.replace("space_channel_member", dict(row), None)
        native.writes.clear()
        repo = UnificationSpaceMembershipRepository(fact_view=view)
        async with AsyncSession(native.engine) as session, session.begin():
            headers = await repo.apage_headers(session)
            assert [(row.knowledge_id, row.member_count) for row in headers.items] == [(1, 2)]
            first = await repo.apage_members(session, knowledge_ids=(1,), limit=1)
            last = await repo.apage_members(session, knowledge_ids=(1,), after_id=first.next_after, limit=1)
        assert [row.id for row in first.items] == [202] and first.next_after == 202
        assert [row.id for row in last.items] == [203] and last.next_after is None
        assert not native.writes
    finally:
        view.close()


async def test_deleted_global_orphan_prefix_does_not_hide_unknown_tail(native):
    await native.insert(
        Member, [member(index, "999") for index in range(1, 202)] + [member(202, "1"), member(203, "bad-id")]
    )
    async with native.engine.connect() as connection:
        rows = tuple((await connection.execute(sa.select(Member.__table__).where(Member.id <= 201))).mappings())
    view = HistoryFactView()
    try:
        for row in rows:
            view.replace("space_channel_member", dict(row), None)
        native.writes.clear()
        async with AsyncSession(native.engine) as session, session.begin():
            with pytest.raises(KnowledgeOperationPlanConflictError):
                await UnificationSpaceMembershipRepository(fact_view=view).avalidate_global_integrity(session)
        assert not native.writes
    finally:
        view.close()
