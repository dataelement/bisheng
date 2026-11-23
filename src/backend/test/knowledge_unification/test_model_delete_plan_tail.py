"""Root §120 probe: the last actor await cannot leak ORM DML at SP release."""

import importlib

import pytest
from sqlalchemy import event, select

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from test.knowledge_unification import test_model_delete_plan_application as native

model_owner_tenant = native.model_owner_tenant
removal_session = native.removal_session
impact = native.impact
ready = native.ready


@pytest.mark.parametrize("pending", ["dirty", "new", "deleted"])
async def test_last_actor_await_cannot_flush_business_pending_on_owned_savepoint_release(ready, monkeypatch, pending):
    session, references, plans = ready
    module = importlib.import_module("bisheng.llm.application.model_delete_plan")
    app = native.application(references, plans)
    table = native.LLMModel.__table__
    original = dict((await session.execute(select(table).where(table.c.id == 11))).mappings().one())
    resolve, calls, statements = module.resolve_permission_actor, [], []

    async def mutate(identity):
        actor = await resolve(identity)
        calls.append(1)
        if len(calls) == 3:
            if pending == "new":
                session.add(
                    native.LLMModel(id=77, tenant_id=101, server_id=1, model_name="must-not-flush", model_type="llm")
                )
                assert session.new
            else:
                row = await session.get(native.LLMModel, 11)
                if pending == "dirty":
                    row.name = "must-not-flush-business-change"
                    assert session.dirty
                else:
                    await session.delete(row)
                    assert session.deleted
        return actor

    def capture(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)

    monkeypatch.setattr(module, "resolve_permission_actor", mutate)
    event.listen(session.bind.sync_engine, "before_cursor_execute", capture)
    try:
        with native.native.actor() as user, pytest.raises(KnowledgeOperationPlanConflictError):
            await app.aplan_server_delete(session, identity=native.web(user), server_id=1)
    finally:
        event.remove(session.bind.sync_engine, "before_cursor_execute", capture)
    assert len(calls) == 3
    assert any(sql.startswith("ROLLBACK TO SAVEPOINT") for sql in statements)
    assert not any(sql.startswith("RELEASE SAVEPOINT") for sql in statements)
    assert not any(sql.lstrip().upper().startswith(("UPDATE", "DELETE", "INSERT INTO LLM_MODEL")) for sql in statements)
    await session.commit()
    assert await native.plan_count(session) == 0
    actual = dict((await session.execute(select(table).where(table.c.id == 11))).mappings().one())
    assert actual == original
    assert (await session.execute(select(table.c.id).where(table.c.id == 77))).scalar_one_or_none() is None
    assert (
        await session.execute(select(native.Tenant.tenant_name).where(native.Tenant.id == 101))
    ).scalar_one() == "unrelated caller write"


async def test_actual_savepoint_release_has_no_pending_orm_after_all_actor_awaits(ready, monkeypatch):
    session, references, plans = ready
    module = importlib.import_module("bisheng.llm.application.model_delete_plan")
    app = native.application(references, plans)
    resolve, actor_calls, releases, business = module.resolve_permission_actor, [], [], []

    async def counted(identity):
        actor = await resolve(identity)
        actor_calls.append(1)
        return actor

    def capture(_conn, _cursor, statement, _params, _context, _many):
        if statement.startswith("RELEASE SAVEPOINT"):
            releases.append(1)
            assert len(actor_calls) == 3
            assert not session.new and not session.dirty and not session.deleted
        if statement.lstrip().upper().startswith(("UPDATE", "DELETE", "INSERT INTO LLM_MODEL")):
            business.append(statement)

    monkeypatch.setattr(module, "resolve_permission_actor", counted)
    event.listen(session.bind.sync_engine, "before_cursor_execute", capture)
    try:
        with native.native.actor() as user:
            result = await app.aplan_server_delete(session, identity=native.web(user), server_id=1)
    finally:
        event.remove(session.bind.sync_engine, "before_cursor_execute", capture)
    assert releases == [1] and actor_calls == [1, 1, 1] and business == []
    assert result.inspection.check_complete and await native.plan_count(session) == 1
