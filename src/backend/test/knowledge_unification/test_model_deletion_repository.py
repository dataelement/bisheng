"""T653: model removal reads real ownership under one borrowed transaction."""

import pytest
from sqlalchemy import event, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.common.errcode.llm_tenant import LLMModelNotAccessibleError, LLMModelSharedReadonlyError
from bisheng.core.context.tenant import management_tenant_scope, tenant_execution_scope
from bisheng.llm.domain.models.llm_server import LLMModel, LLMServer
from bisheng.llm.domain.repositories.model_deletion_repository import ModelDeletionRepository
from test.knowledge_unification import test_model_reference_owner as models

model_owner_tenant = models.model_owner_tenant


@pytest.fixture
async def removal_session():
    engine = await models.async_database()
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add(LLMServer(id=4, tenant_id=101, name="another-own", type="openai"))
        session.add(LLMModel(id=44, server_id=4, tenant_id=101, model_name="another", model_type="llm"))
        session.add_all(
            LLMModel(id=12 + index, server_id=1, tenant_id=101, model_name=kind, model_type=kind)
            for index, kind in enumerate(("embedding", "rerank", "asr", "tts"))
        )
        await session.commit()
        yield session
    await engine.dispose()


async def inspect(session, retained=(), *, server=1, delete_server=False):
    return await ModelDeletionRepository().alock_removal_targets(
        session, server_id=server, retained_model_ids=retained, delete_server=delete_server
    )


async def test_all_five_model_kinds_and_exact_removed_set_are_frozen(removal_session):
    snapshot = await inspect(removal_session, (11, 13))
    assert snapshot.server_id == 1 and snapshot.owner_tenant_id == 101
    assert snapshot.all_model_ids == (11, 12, 13, 14, 15)
    assert snapshot.retained_model_ids == (11, 13)
    assert [target.target_id for target in snapshot.targets] == ["12", "14", "15"]
    assert len(snapshot.server_revision) == 64
    assert {target_id for target_id, _ in snapshot.model_revisions} == {"11", "12", "13", "14", "15"}
    assert len((await inspect(removal_session, delete_server=True)).targets) == 5
    assert not (await inspect(removal_session, server=4, retained=(44,))).targets


@pytest.mark.parametrize("retained", [(11, 11), (44,), (33,), (999,), (True,), (-1,)])
async def test_retained_ids_cannot_inject_duplicates_foreign_server_or_tenant(removal_session, retained):
    with pytest.raises((ResourceReferenceInvalidError, ValueError)):
        await inspect(removal_session, retained)


async def test_current_tenant_and_root_shared_readonly_are_not_bypassed(removal_session):
    with pytest.raises(LLMModelSharedReadonlyError):
        await inspect(removal_session, server=2)
    with pytest.raises(LLMModelNotAccessibleError):
        await inspect(removal_session, server=3)
    with tenant_execution_scope(202):
        with pytest.raises(LLMModelNotAccessibleError):
            await inspect(removal_session)
        assert (await inspect(removal_session, server=3)).all_model_ids == (33,)
    with management_tenant_scope(1):
        assert (await inspect(removal_session, server=2)).owner_tenant_id == 1


async def test_foreign_model_under_owned_server_is_inconsistent_not_silently_hidden(removal_session):
    removal_session.add(LLMModel(id=60, server_id=1, tenant_id=202, model_name="broken", model_type="llm"))
    await removal_session.flush()
    with pytest.raises(ResourceReferenceInvalidError):
        await inspect(removal_session)


async def test_service_lock_precedes_sorted_model_locks_without_cartesian_queries(removal_session):
    statements = []

    def record(state):
        if state.is_select and state.statement._for_update_arg is not None:
            statements.append(state.statement)

    event.listen(removal_session.sync_session, "do_orm_execute", record)
    await inspect(removal_session, (11,))
    assert [statement.get_final_froms()[0].name for statement in statements][:2] == ["llm_server", "llm_model"]
    assert all(len(statement.get_final_froms()) == 1 for statement in statements)


async def test_borrowed_transaction_is_never_committed_or_business_rows_changed(removal_session):
    row = await removal_session.get(LLMServer, 1)
    row.description = "caller draft"
    await removal_session.flush()
    first = await inspect(removal_session, (11,))
    assert row.description == "caller draft"
    await removal_session.rollback()
    second = await inspect(removal_session, (11,))
    assert second.server_revision != first.server_revision
    assert len((await removal_session.execute(select(LLMModel))).scalars().all()) == 6


async def test_provider_revision_also_binds_retained_model_configuration(removal_session):
    first = await inspect(removal_session, (11, 12))
    retained = await removal_session.get(LLMModel, 12)
    retained.model_name = "new-retained-configuration"
    await removal_session.flush()
    second = await inspect(removal_session, (11, 12))
    assert second.targets == first.targets
    assert second.server_revision != first.server_revision
