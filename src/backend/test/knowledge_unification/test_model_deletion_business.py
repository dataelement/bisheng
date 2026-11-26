"""Public legacy deletion must fail closed before any native business write.

Coverage: AC-70, AC-73, AC-76, AC-77.  These first native counterexamples
exercise the original Service and DAO, rather than an unimplemented import.
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.llm.domain.models import llm_server as model_module
from bisheng.llm.domain.models.llm_server import LLMModel, LLMServer
from bisheng.llm.domain.services import llm as service_module
from bisheng.llm.domain.services.llm import LLMService
from bisheng.resource_reference.application import access
from test.knowledge_unification import test_model_delete_plan_application as actual

model_owner_tenant = actual.model_owner_tenant
removal_session = actual.removal_session
impact = actual.impact
ready = actual.ready


@pytest.mark.parametrize("server_id", [1, 5])
async def test_original_public_delete_succeeds_without_formal_coverage(ready, monkeypatch, server_id):
    session, _, _ = ready
    await session.commit()

    @asynccontextmanager
    async def sessions():
        yield session

    monkeypatch.setattr(model_module, "get_async_db_session", sessions)
    monkeypatch.setattr(service_module, "_write_llm_audit", AsyncMock())
    monkeypatch.setattr(access, "_runtime", None)
    # The new composition owns fresh native sessions on the same real engine.
    # No ready/Core decision is replaced to keep this old-path regression green.
    from bisheng.llm.application import model_deletion

    @asynccontextmanager
    async def native_sessions():
        async with AsyncSession(session.bind, expire_on_commit=False) as current:
            yield current

    async def application():
        return model_deletion.ModelDeletionApplication(session_factory=native_sessions)

    monkeypatch.setattr(model_deletion, "get_model_deletion_application", application)
    before_server = (await session.execute(select(LLMServer.id).order_by(LLMServer.id))).scalars().all()
    before_models = (await session.execute(select(LLMModel.id).order_by(LLMModel.id))).scalars().all()
    with actual.native.actor() as identity:
        actual.web(identity)
        assert await LLMService.delete_llm_server(None, identity, server_id)
    assert (await session.execute(select(LLMServer.id).order_by(LLMServer.id))).scalars().all() == [
        ident for ident in before_server if ident != server_id
    ]
    assert set((await session.execute(select(LLMModel.id))).scalars()) <= set(before_models)
    assert not (await session.execute(select(LLMModel.id).where(LLMModel.server_id == server_id))).all()


async def test_actual_core_still_inspects_an_empty_owned_provider_under_ready_native_coverage(ready):
    session, references, _ = ready
    with actual.native.actor() as identity:
        actual.web(identity)
        facts = await references.ainspect_removed_models(
            session, identity=identity, server_id=5, retained_model_ids=(), delete_server=True
        )
    assert facts.check_complete and not facts.blocked and facts.targets == ()
