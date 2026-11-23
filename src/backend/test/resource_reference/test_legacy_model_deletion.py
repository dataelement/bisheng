"""AC-11/12: old real deletion operations resume without trusting coverage."""

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.llm.domain.models.llm_server import LLMModel, LLMServer
from bisheng.llm.domain.repositories.model_delete_plan_repository import _hash
from bisheng.llm.domain.repositories.reference_target_repository import _revision
from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone
from test.knowledge_unification import test_model_deletion_application as fixtures

business, impact, model_owner_tenant = fixtures.business, fixtures.impact, fixtures.model_owner_tenant
ready, removal_session = fixtures.ready, fixtures.removal_session


async def test_old_reserved_operation_reuses_its_actual_tombstone_and_finishes_it(business, monkeypatch):
    factory, app, references, plans, _ = business
    original = app.writer.adelete_server
    monkeypatch.setattr(app.writer, "adelete_server", AsyncMock(side_effect=OSError("interrupted SQL phase")))
    with fixtures.actual.native.actor() as user:
        fixtures.actual.web(user)
        control = await fixtures.confirmation(factory, references, plans, user, server_id=1)
        with pytest.raises(OSError):
            await app.adelete_server(identity=user, server_id=1, **control)
        async with factory() as session, session.begin():
            plan = await session.get(KnowledgeOperationPlan, control["confirmation_id"])
            assert plan.model_execution_state == "RESERVED"
            plan.impact = {"inbound_digest": "a" * 64, "coverage_epoch": 1, "inventory_hash": "b" * 64}
            server = await session.get(LLMServer, 1)
            models = (await session.execute(select(LLMModel).where(LLMModel.server_id == 1))).scalars().all()
            revisions = {}
            for model in models:
                marker = ResourceReferenceTombstone(
                    tenant_id=101,
                    target_type="model",
                    target_id=str(model.id),
                    target_tenant_id=101,
                    operation_id=plan.operation_id,
                    operation_type=plan.operation,
                    stage="deleting",
                    actor_type="user",
                    actor_id=str(user.user_id),
                )
                session.add(marker)
                await session.flush()
                await session.refresh(marker)
                revisions[f"model:{model.id}"] = _revision(model, server, marker)
            metadata = deepcopy(plan.model_execution_metadata)
            metadata["reserved_target_revisions"] = revisions
            plan.model_execution_metadata = metadata
            plan.request_hash = _hash(plans._payload(plan))
            plan.plan_digest = plans._plan_digest(plan)
            control["plan_digest"] = plan.plan_digest
        monkeypatch.setattr(app.writer, "adelete_server", original)
        result = await app.adelete_server(identity=user, server_id=1, **control)
        assert result["deleted_server"]
    async with factory() as session:
        markers = (await session.execute(select(ResourceReferenceTombstone))).scalars().all()
        assert markers and all(row.stage == "deleted" and row.deleted_at is not None for row in markers)
