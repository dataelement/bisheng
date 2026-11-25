"""AC-03/04/05/06/10: real SQL scope stays independent of auxiliary hints."""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, update

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.database.models.tenant import Tenant
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.resource_reference.application.contracts import TargetKey
from bisheng.resource_reference.domain.repositories.reference_hint_repository import ReferenceHintRepository
from test.knowledge_unification import test_kn_delete_plan as fixtures

application = fixtures.application
context, service, db, deletion_tenant = fixtures.context, fixtures.service, fixtures.db, fixtures.deletion_tenant


@pytest.fixture
async def hints(application, context):
    async with context.db.engine.begin() as connection:
        await connection.run_sync(lambda conn: Tenant.__table__.create(conn, checkfirst=True))
    async with context.db.sessions() as session, session.begin():
        for ident in (101, 202):
            if await session.get(Tenant, ident) is None:
                session.add(Tenant(id=ident, tenant_code=f"e2e-reference-{ident}", tenant_name="Test"))
    context.failure = "global"
    return application, context


async def test_existing_reference_is_advisory_and_ignores_global_ledger(hints):
    app, context = hints
    await fixtures.native.native.seed(context, (31, 101, "assistant", "configured", "current", "file"))
    plan = await app.aprecheck(
        identity=app.user, space_id=1, selections=fixtures.native.native.selections(("knowledge_file", 31))
    )
    assert plan.check_complete and plan.can_execute
    assert plan.impact["reference_check_complete"] is True
    assert plan.impact["source_counts"]["assistant"] == 1
    async with context.db.sessions() as session:
        stored = await session.get(fixtures.KnowledgeOperationPlan, plan.confirmation_id)
        assert stored.source_revisions.keys() == {"root"}
    assert context.ledgers == []


async def test_hint_failure_leaves_business_confirmation_available(hints, monkeypatch):
    app, _ = hints
    monkeypatch.setattr(
        app.references, "_inspect", AsyncMock(side_effect=ReferenceCoverageNotReadyError(reason="query_failed"))
    )
    plan = await app.aprecheck(identity=app.user, space_id=2, operation="knowledge_space_clear")
    assert plan.check_complete and plan.can_execute
    assert plan.impact["reference_check_complete"] is False
    assert plan.impact["source_counts"] == {}


async def test_failed_delete_authorization_is_not_swallowed(hints, monkeypatch):
    app, _ = hints
    from bisheng.knowledge.domain.services import knowledge_reference_service

    monkeypatch.setattr(
        knowledge_reference_service, "require_business_action", AsyncMock(side_effect=PermissionDeniedError())
    )
    with pytest.raises(PermissionDeniedError):
        await app.references.ainspect(identity=app.user, space_id=2, whole_space=True)


async def test_moved_file_hint_uses_current_membership_and_ignores_deleted_source_tenant(hints):
    _app, context = hints
    await fixtures.native.native.seed(
        context,
        (31, 101, "assistant", "visible", "current", "file"),
        (31, 202, "assistant", "foreign-secret", "current", "file"),
    )
    async with context.db.sessions() as session, session.begin():
        await session.execute(update(KnowledgeFile).where(KnowledgeFile.id == 31).values(knowledge_id=2))
        await session.execute(delete(Tenant).where(Tenant.id == 202))
    async with context.db.sessions() as session, session.begin():
        repo = ReferenceHintRepository()
        old = await repo.aread(session, (TargetKey("knowledge_space", "1"),), space_id=1)
        new = await repo.aread(session, (TargetKey("knowledge_space", "2"),), space_id=2)
    assert not old
    assert len(new) == 1 and new[0].source_id == "visible" and new[0].target_space_id == "1"
