"""New model grants share the provider write transaction and preserve explicit scopes."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import Session, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.dsh.domain.models.unified_policy import ModelVisibility, UnifiedPolicyAudit
from bisheng.dsh.domain.repositories.unified_policy import UnifiedPolicyRepository
from bisheng.dsh.domain.schemas.unified_policy import ModelVisibilityInput, PolicySubject
from bisheng.llm.domain.models.llm_server import LLMDao, LLMModel, LLMServer
from test.dsh.test_subject_policy import subject_store as subject_store
from test.dsh.test_unified_policy_repository import store as store


@pytest.mark.asyncio
async def test_provider_create_append_preserve_scope_and_tenant(store):
    LLMServer.__table__.create(store)
    LLMModel.__table__.create(store)
    engine = create_async_engine(str(store.url).replace("sqlite:", "sqlite+aiosqlite:"))

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    settings = SimpleNamespace(dsh=SimpleNamespace(enabled=True))
    try:
        with (
            patch("bisheng.llm.domain.models.llm_server.get_async_db_session", sessions),
            patch("bisheng.llm.domain.models.llm_server.settings", settings),
        ):
            provider = LLMServer(name="New provider", type="openai", user_id=20)
            model = LLMModel(model_name="dialogue", model_type="llm", user_id=20)
            embedding = LLMModel(model_name="embedding", model_type="embedding", user_id=20)
            await LLMDao.ainsert_server_with_models(provider, [model, embedding])
            with Session(store) as session, session.begin():
                repo = UnifiedPolicyRepository(session)
                assert repo.visibility(model.id)["everyone"] is True
                assert repo.effective(21).allowed_model_ids == [model.id]
                assert repo.visibility(embedding.id)["version"] == 0
                repo.save_visibility(
                    model.id, 20, ModelVisibilityInput(version=1, subjects=[PolicySubject(kind="USER", id=20)])
                )
            new_model = LLMModel(model_name="appended", model_type="llm", server_id=provider.id, user_id=20)
            await LLMDao.update_server_with_models(provider, [model, embedding, new_model])
            with Session(store) as session, session.begin():
                repo = UnifiedPolicyRepository(session)
                assert repo.effective(21).allowed_model_ids == [new_model.id]
                assert repo.effective(20).allowed_model_ids == [model.id, new_model.id]
                assert repo.visibility(model.id)["version"] == 2
                assert repo.initialize_model_visibility(model.id, 20)["everyone"] is False
                assert len(session.exec(select(UnifiedPolicyAudit)).all()) == 3
            token = set_current_tenant_id(3)
            try:
                with Session(store) as session:
                    assert UnifiedPolicyRepository(session).visibility(new_model.id)["version"] == 0
            finally:
                current_tenant_id.reset(token)

            # A failed policy write rolls the newly appended model back as well.
            failed = LLMModel(model_name="failed", model_type="llm", server_id=provider.id, user_id=20)
            with patch.object(
                UnifiedPolicyRepository, "initialize_model_visibility", side_effect=RuntimeError("policy failed")
            ):
                with pytest.raises(RuntimeError, match="policy failed"):
                    await LLMDao.update_server_with_models(provider, [model, embedding, new_model, failed])
            with Session(store) as session:
                assert session.exec(select(LLMModel).where(LLMModel.model_name == "failed")).first() is None
                assert len(session.exec(select(ModelVisibility)).all()) == 2
    finally:
        await engine.dispose()
