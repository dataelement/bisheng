"""SQL reservation, unique worker claim, failure and matching publication."""

import pytest

from bisheng.common.errcode.knowledge import KnowledgeCPError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.repositories.copy_repository import CopyRepository
from test.fixtures.managed_tenant import managed_db as managed_db
from test.fixtures.managed_tenant import management_scope


@pytest.fixture
async def copy_db(managed_db, monkeypatch):
    from bisheng.knowledge.domain.repositories import copy_repository

    await managed_db.create(Knowledge)
    monkeypatch.setattr(copy_repository, "get_async_db_session", managed_db.sessions)
    monkeypatch.setattr(copy_repository, "get_sync_db_session", managed_db.sync_sessions)
    with bypass_tenant_filter():
        async with managed_db.sessions() as session:
            source = Knowledge(id=10, name="source", tenant_id=2, user_id=8, state=1)
            session.add(source)
            await session.commit()
    return managed_db, source


async def test_pair_stays_in_source_t_with_current_actor_owner(copy_db):
    db, source = copy_db
    with management_scope(1, 2):
        target = await CopyRepository.reserve(source, Knowledge(name="target", tenant_id=2, user_id=7))
    source2, target2 = CopyRepository.inspect(2, 10, target.id)
    assert target2.tenant_id == 2 and target2.user_id == 7 and target2.copy_source_id == 10
    assert source2.copy_target_id == target.id and source2.state == 2
    with pytest.raises(KnowledgeCPError):
        await CopyRepository.reserve(source, Knowledge(name="duplicate", tenant_id=2, user_id=7))
    assert CopyRepository.claim(2, 10, target.id, 7) is not None
    assert CopyRepository.claim(2, 10, target.id, 7) is None
    CopyRepository.finish(2, 10, target.id, succeeded=True)
    with bypass_tenant_filter(), db.sync_sessions() as session:
        assert session.get(Knowledge, target.id).state == 1
        assert session.get(Knowledge, 10).state == 1
        assert session.get(Knowledge, 10).copy_target_id is None


async def test_failed_worker_is_not_adopted_or_published(copy_db):
    db, source = copy_db
    target = await CopyRepository.reserve(source, Knowledge(name="target", tenant_id=2, user_id=7))
    CopyRepository.claim(2, 10, target.id, 7)
    CopyRepository.finish(2, 10, target.id, succeeded=False)
    assert CopyRepository.claim(2, 10, target.id, 7) is None
    with bypass_tenant_filter(), db.sync_sessions() as session:
        assert session.get(Knowledge, target.id).state == 4
        assert session.get(Knowledge, 10).copy_target_id == target.id


async def test_wrong_actor_or_foreign_t_cannot_claim(copy_db):
    _db, source = copy_db
    target = await CopyRepository.reserve(source, Knowledge(name="target", tenant_id=2, user_id=7))
    with pytest.raises(KnowledgeCPError):
        CopyRepository.claim(2, 10, target.id, 8)
    with pytest.raises(KnowledgeCPError):
        CopyRepository.claim(3, 10, target.id, 7)


async def test_commit_ack_lost_inspects_original_target_instead_of_reserving_twice(copy_db, monkeypatch):
    from sqlmodel import select
    from sqlmodel.ext.asyncio.session import AsyncSession

    db, source = copy_db
    original = AsyncSession.commit
    commits = []

    async def uncertain(session):
        await original(session)
        commits.append(1)
        raise RuntimeError("commit acknowledgement lost")

    monkeypatch.setattr(AsyncSession, "commit", uncertain)
    target = await CopyRepository.reserve(source, Knowledge(name="fixed target", tenant_id=2, user_id=7))
    assert len(commits) == 1
    with bypass_tenant_filter(), db.sync_sessions() as session:
        assert len(session.exec(select(Knowledge)).all()) == 2
        assert session.get(Knowledge, 10).copy_target_id == target.id


def test_copy_worker_requires_matching_trusted_header():
    from types import SimpleNamespace

    from bisheng.core.context.tenant import tenant_execution_scope
    from bisheng.knowledge.application.copy_execution import copy_execution_scope
    from bisheng.worker.tenant_context import reset_tenant_context, restore_tenant_context

    task = SimpleNamespace(
        name="bisheng.worker.knowledge.file_worker.file_copy_celery", request=SimpleNamespace(headers={"tenant_id": 2})
    )
    with tenant_execution_scope(1):
        restore_tenant_context(sender=task)
        try:
            with copy_execution_scope(2):
                pass
            with pytest.raises(KnowledgeCPError), copy_execution_scope(3):
                pass
        finally:
            reset_tenant_context(sender=task)
    with pytest.raises(KnowledgeCPError), copy_execution_scope(2):
        pass


async def test_published_copy_can_become_source_of_another_copy(copy_db):
    from bisheng.knowledge.domain.models.knowledge import assert_copy_ready

    db, source = copy_db
    first = await CopyRepository.reserve(source, Knowledge(name="first", tenant_id=2, user_id=7))
    CopyRepository.claim(2, 10, first.id, 7)
    CopyRepository.finish(2, 10, first.id, succeeded=True)
    with bypass_tenant_filter(), db.sync_sessions() as session:
        published = session.get(Knowledge, first.id)
    second = await CopyRepository.reserve(published, Knowledge(name="second", tenant_id=2, user_id=7))
    chained_source, chained_target = CopyRepository.inspect(2, first.id, second.id)
    assert await CopyRepository.pending_targets([first.id, second.id]) == [second.id]
    assert assert_copy_ready(chained_source).id == first.id
    with pytest.raises(KnowledgeCPError):
        assert_copy_ready(chained_target)
