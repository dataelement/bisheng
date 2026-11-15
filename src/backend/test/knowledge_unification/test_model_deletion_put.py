"""Real public PUT, generated PKs, and interrupted native business resume."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa

from bisheng.core.context.tenant import management_tenant_scope
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.llm.application import model_deletion
from bisheng.llm.domain.models import llm_server as model_module
from bisheng.llm.domain.models.llm_server import LLMModel, LLMServer
from bisheng.llm.domain.services import llm as service_module
from bisheng.llm.domain.services.llm import LLMService
from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone
from test.knowledge_unification import test_model_delete_plan_application as actual
from test.knowledge_unification import test_model_deletion_application as native_business

business = native_business.business
impact = actual.impact
model_owner_tenant = actual.model_owner_tenant
ready = actual.ready
removal_session = actual.removal_session
confirmation = native_business.confirmation
records = native_business.records


async def install(monkeypatch, business):
    factory, application, *_ = business

    async def get_application():
        return application

    monkeypatch.setattr(model_deletion, "get_model_deletion_application", get_application)
    monkeypatch.setattr(model_module, "get_async_db_session", factory)
    monkeypatch.setattr(service_module, "_check_is_global_super", AsyncMock(return_value=False))


async def test_original_public_put_removes_exact_difference_and_replays_generated_ids_once(business, monkeypatch):
    factory, _, _, _, _ = business
    await install(monkeypatch, business)
    request = actual.request()
    request.models[0].online = True
    with actual.native.actor() as user:
        actual.web(user)
        result = await LLMService.update_llm_server(None, user, request)
        replay = await LLMService.update_llm_server(None, user, request)
    assert sorted(model.id for model in result.models) == sorted(model.id for model in replay.models)
    assert len(result.models) == 3 and 11 in {model.id for model in result.models}
    async with factory() as session:
        models = (await session.execute(sa.select(LLMModel).where(LLMModel.server_id == 1))).scalars().all()
        assert len(models) == 3 and all(row.tenant_id == 101 for row in models)
        generated = [row for row in models if row.id != 11]
        assert len(generated) == 2 and all(row.user_id == 7 and row.model_type == "asr_rt" for row in generated)
        retained = next(row for row in models if row.id == 11)
        assert retained.online is False  # The original DAO never edits this field through PUT.
        rows = (await session.execute(sa.select(KnowledgeOperationPlan))).scalars().all()
        assert len(rows) == 2 and all(row.model_execution_state == "COMPLETED" for row in rows)
        serialized = json.dumps([row.model_execution_metadata for row in rows])
        assert actual.SECRET not in serialized and "api_key" not in serialized
        tombstones = (await session.execute(sa.select(ResourceReferenceTombstone))).scalars().all()
        assert len(tombstones) == 4 and all(row.stage == "deleted" for row in tombstones)


@pytest.mark.parametrize("failure", [ValueError, asyncio.CancelledError])
async def test_projection_completed_but_late_business_failure_keeps_native_before_and_retries_once(
    business, monkeypatch, failure
):
    factory, app, references, plans, client = business
    request = actual.request((), server_id=2)
    client.rows = {(f"tenant:{value}", "shared_with", "llm_server:2") for value in range(100, 151)}
    original = app.writer.aupdate_server

    async def late(*args, **kwargs):
        await original(*args, **kwargs)
        raise failure("after actual native SQL")

    with management_tenant_scope(1), actual.native.actor(super_admin=True) as user:
        actual.web(user)
        before_models, before_servers = await records(factory, LLMModel), await records(factory, LLMServer)
        control = await confirmation(factory, references, plans, user, server_id=2, request=request)
        monkeypatch.setattr(app.writer, "aupdate_server", late)
        with pytest.raises(failure):
            await app.aupdate_server(identity=user, server=request, **control)
        assert await records(factory, LLMModel) == before_models
        assert await records(factory, LLMServer) == before_servers
        assert not client.rows and len(client.writes) == 2
        async with factory() as session:
            row = await session.get(KnowledgeOperationPlan, control["confirmation_id"])
            assert row.model_execution_state == "RESERVED"
            tombstones = (await session.execute(sa.select(ResourceReferenceTombstone))).scalars().all()
            assert len(tombstones) == 1 and tombstones[0].stage == "deleting"
        monkeypatch.setattr(app.writer, "aupdate_server", original)
        user.token_version = 4
        user._runtime_credential_reference = {**user._runtime_credential_reference, "token_version": 4}
        result = await app.aupdate_server(identity=user, server=request, **control)
        assert len(result.models) == 2 and all(model.id != 22 for model in result.models)
        assert len(client.writes) == 2


async def test_unknown_sharing_commit_is_classified_after_and_does_not_repeat_transport(business):
    _, app, _, _, client = business
    client.rows = {("tenant:202", "shared_with", "llm_server:2")}
    client.unknown = True
    with management_tenant_scope(1), actual.native.actor(super_admin=True) as user:
        actual.web(user)
        result = await app.adelete_server(identity=user, server_id=2)
    assert result["deleted_server"] and not client.rows and len(client.writes) == 1
