"""T703: physical model/server identity is not callable or sharing authority."""

import importlib
from dataclasses import FrozenInstanceError, fields
from datetime import datetime

import pytest
from sqlalchemy import event, update
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import bypass_tenant_filter, get_current_tenant_id, is_tenant_filter_bypassed
from bisheng.llm.domain.models.llm_server import LLMModel, LLMServer
from bisheng.resource_reference.application.contracts import SourceKey, TargetKey
from test.knowledge_unification import test_migration_knowledge_targets as fixtures

storage = fixtures.storage
SOURCE = fixtures.SOURCE


@pytest.fixture
def repo():
    return importlib.import_module(
        "bisheng.llm.domain.repositories.migration_target_repository"
    ).ModelMigrationTargetRepository()


async def test_offline_foreign_root_wrong_parent_and_global_absence_are_distinct_physical_facts(repo, storage):
    async with AsyncSession(storage) as session, session.begin():
        for ident, tenant in ((1, 101), (2, 1), (3, 202)):
            session.add(
                LLMServer(
                    id=ident, tenant_id=tenant, name="private-provider", type="openai", config={"api_key": "never-read"}
                )
            )
        for ident, tenant, parent, online in (
            (10, 101, 1, True),
            (11, 101, 1, False),
            (12, 1, 2, False),
            (13, 202, 3, True),
            (14, 101, 999, True),
            (15, 101, 3, True),
        ):
            session.add(
                LLMModel(
                    id=ident,
                    tenant_id=tenant,
                    server_id=parent,
                    model_name=f"private-{ident}",
                    model_type="embedding" if ident == 11 else "llm",
                    online=online,
                    config={"api_key": "never-read"},
                )
            )
        await session.flush()
        targets = tuple(TargetKey("model", value) for value in (10, 11, 12, 13, 14, 15, 999))
        observed = fixtures.queries(session)
        facts = await repo.ainspect(session, source_key=SOURCE, targets=targets)
        assert tuple(row.key for row in facts) == targets
        assert facts[1].exists and facts[1].is_online is False and facts[1].model_type == "embedding"
        assert facts[2].exists and facts[2].target_tenant_id == facts[2].server_tenant_id == 1
        assert facts[3].exists and facts[3].target_tenant_id == facts[3].server_tenant_id == 202
        assert facts[4].exists and facts[4].server_id == 999 and not facts[4].server_exists
        assert facts[5].target_tenant_id == 101 and facts[5].server_tenant_id == 202
        assert not facts[6].exists and facts[6].target_tenant_id is facts[6].server_id is facts[6].model_type is None
        assert len(observed) == 1 and all(current == 101 and cross and strict for _, current, cross, strict in observed)
        assert "config" not in str(observed[0][0]) and "name" not in str(observed[0][0])
        assert all("private" not in repr(row) and "never-read" not in repr(row) for row in facts)
        assert not is_tenant_filter_bypassed()


async def test_200_pk_batch_is_one_join_preserves_first_seen_order_and_digest_changes_for_provider_revision(
    repo, storage
):
    async with AsyncSession(storage) as session, session.begin():
        session.add(LLMServer(id=1, tenant_id=101, name="provider", type="openai"))
        session.add(LLMModel(id=1, tenant_id=101, server_id=1, model_name="model", model_type="llm"))
        await session.flush()
        targets = tuple(TargetKey("model", i) for i in range(200, 0, -1))
        observed = fixtures.queries(session)
        facts = await repo.ainspect(session, source_key=SOURCE, targets=(*targets, targets[0], targets[-1]))
        assert tuple(row.key for row in facts) == targets and len(observed) == 1
        query = observed[0][0]
        assert query._offset_clause is None and len(query.get_final_froms()) == 1 and " IN " in str(query)
        assert len(next(value for value in query.compile().params.values() if isinstance(value, list))) == 200
        before = facts[-1].revision_digest
        await session.execute(update(LLMServer).where(LLMServer.id == 1).values(update_time=datetime(2026, 1, 1)))
        actual = (await repo.ainspect(session, source_key=SOURCE, targets=(targets[-1],)))[0]
        assert actual.revision_digest != before
        assert [item.name for item in fields(actual)] == [
            "key",
            "exists",
            "target_tenant_id",
            "model_type",
            "is_online",
            "server_id",
            "server_exists",
            "server_tenant_id",
            "revision_digest",
        ]
        assert not hasattr(actual, "__dict__")
        with pytest.raises(FrozenInstanceError):
            actual.is_online = False


async def test_empty_and_pending_writes_do_not_change_session_or_scope(repo, storage):
    async with AsyncSession(storage) as session, session.begin():
        pending = LLMServer(name="pending", type="openai")
        session.add(pending)
        observed = fixtures.queries(session)
        flushes = []
        event.listen(session.sync_session, "before_flush", lambda *args: flushes.append(True))
        assert await repo.ainspect(session, source_key=SOURCE, targets=()) == () and not observed
        assert not (await repo.ainspect(session, source_key=SOURCE, targets=(TargetKey("model", 999),)))[0].exists
        assert pending in session.new and pending.tenant_id is None and not flushes
        assert get_current_tenant_id() == 101 and not is_tenant_filter_bypassed()


@pytest.mark.parametrize(
    "change", ["source", "source_type", "container", "target_type", "bool_id", "negative_id", "batch"]
)
async def test_invalid_input_is_zero_sql_and_does_not_enter_bypass(repo, storage, change):
    source, targets = SOURCE, (TargetKey("model", 1),)
    if change == "source":
        source = SourceKey(202, "assistant", "outside", "current")
    elif change == "source_type":
        source = {"tenant_id": 101}
    elif change == "container":
        targets = list(targets)
    elif change == "target_type":
        targets = (TargetKey("knowledge_space", 1),)
    elif change == "bool_id":
        targets = (fixtures.corrupt_target("model", True),)
    elif change == "negative_id":
        targets = (fixtures.corrupt_target("model", "-1"),)
    else:
        targets = tuple(TargetKey("model", i + 1) for i in range(201))
    async with AsyncSession(storage) as session, session.begin():
        observed = fixtures.queries(session)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.ainspect(session, source_key=source, targets=targets)
        assert not observed and not is_tenant_filter_bypassed()


async def test_bypass_or_missing_native_transaction_cannot_use_empty_batch_to_skip_scope(repo, storage):
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await repo.ainspect(object(), source_key=SOURCE, targets=())
    async with AsyncSession(storage) as session:
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.ainspect(session, source_key=SOURCE, targets=())
        async with session.begin():
            with bypass_tenant_filter(), pytest.raises(KnowledgeOperationPlanConflictError):
                await repo.ainspect(session, source_key=SOURCE, targets=())


async def test_real_sql_failure_never_becomes_a_missing_model_and_restores_scope(repo, storage):
    async with storage.begin() as connection:
        await connection.run_sync(lambda conn: LLMModel.__table__.drop(conn))
    async with AsyncSession(storage) as session, session.begin():
        with pytest.raises(SQLAlchemyError):
            await repo.ainspect(session, source_key=SOURCE, targets=(TargetKey("model", 1),))
        assert get_current_tenant_id() == 101 and not is_tenant_filter_bypassed()
        await session.rollback()
