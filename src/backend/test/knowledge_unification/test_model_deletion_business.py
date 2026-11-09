"""Public legacy deletion must fail closed before any native business write.

Coverage: AC-70, AC-73, AC-76, AC-77.  These first native counterexamples
exercise the original Service and DAO, rather than an unimplemented import.
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError
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
async def test_original_public_delete_never_mutates_when_formal_coverage_is_unconfigured(
    ready, monkeypatch, server_id
):
    session, _, _ = ready
    await session.commit()

    @asynccontextmanager
    async def sessions():
        yield session

    monkeypatch.setattr(model_module, "get_async_db_session", sessions)
    monkeypatch.setattr(service_module, "_write_llm_audit", AsyncMock())
    monkeypatch.setattr(access, "_runtime", None)
    before_server = (await session.execute(select(LLMServer.id).order_by(LLMServer.id))).scalars().all()
    before_models = (await session.execute(select(LLMModel.id).order_by(LLMModel.id))).scalars().all()
    with actual.native.actor() as identity:
        actual.web(identity)
        with pytest.raises(ReferenceCoverageNotReadyError):
            await LLMService.delete_llm_server(None, identity, server_id)
    assert (await session.execute(select(LLMServer.id).order_by(LLMServer.id))).scalars().all() == before_server
    assert (await session.execute(select(LLMModel.id).order_by(LLMModel.id))).scalars().all() == before_models


async def test_actual_core_still_inspects_an_empty_owned_provider_under_ready_native_coverage(ready):
    session, references, _ = ready
    with actual.native.actor() as identity:
        actual.web(identity)
        facts = await references.ainspect_removed_models(
            session, identity=identity, server_id=5, retained_model_ids=(), delete_server=True
        )
    assert facts.check_complete and not facts.blocked and facts.targets == ()
