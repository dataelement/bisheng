"""Real-session regression for partial workbench POSTs preserving model lists.

覆盖 AC: AC-71, AC-87, AC-88, AC-89, AC-92
None keeps the saved list; [] clears; an explicit list replaces. Typed business
errors remain 10810/10811. Provider/rebuild IO is never reached by these cases.
"""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import BackgroundTasks
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.llm import WorkbenchChatDefaultModelError, WorkbenchEmbeddingError
from bisheng.llm.domain.models.llm_server import LLMModel
from bisheng.llm.domain.repositories.model_default_repository import ModelDefaultRepository
from bisheng.llm.domain.schemas import WorkbenchModelConfig, WSModel
from bisheng.llm.domain.services import llm as module
from bisheng.llm.domain.services.default_reference_extractor import (
    MODEL_DEFAULT_REFERENCE_EXTRACTOR_VERSION,
    extract_model_default_references,
)
from bisheng.resource_reference.application.contracts import SourceKey
from bisheng.resource_reference.application.source_contracts import canonical_payload_json
from test.knowledge_unification import test_llm_defaults as writing

business = writing.business
model_owner_tenant = writing.model_owner_tenant
_OLD = WorkbenchModelConfig(
    models=[WSModel(id="727", name="deepseek"), WSModel(id="774", name="qwen")],
    embedding_model=WSModel(id="729", name="embed"),
)


@pytest.fixture
async def merge_store(business, monkeypatch):
    repo = ModelDefaultRepository()
    key = SourceKey(101, "model_default", "linsight_llm", "current")
    async with AsyncSession(business.engine) as session, session.begin():
        session.add_all(
            LLMModel(id=ident, tenant_id=101, server_id=1, model_name=str(ident), model_type=kind)
            for ident, kind in ((727, "llm"), (774, "llm"), (729, "embedding"), (840, "llm"), (841, "llm"))
        )
        await session.flush()

        async def lock_root(active):
            await repo.alock_root(active, "linsight_llm")

        prepared = await business.runtime.aprepare_source_bindings(
            session,
            key,
            extract_model_default_references("linsight_llm", _OLD),
            extractor_version=MODEL_DEFAULT_REFERENCE_EXTRACTOR_VERSION,
            lock_source_root=lock_root,
            new_source=True,
        )
        await repo.aput(session, "linsight_llm", canonical_payload_json(_OLD.model_dump(mode="json")))
        await business.runtime.aapply_source_bindings(session, prepared)

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(business.engine) as session:
            yield session

    monkeypatch.setattr(module, "get_async_db_session", sessions)
    provider = AsyncMock(side_effect=AssertionError("cleared/invalid embedding must not initialize a provider"))
    monkeypatch.setattr(module.LLMService, "get_bisheng_embedding", provider)
    return SimpleNamespace(**vars(business), repository=repo, provider=provider)


async def _run_and_capture(context, config_obj):
    result = await module.LLMService.update_workbench_llm(
        7, config_obj, BackgroundTasks(), tenant_id=101, login_user=context.user
    )
    assert isinstance(result, WorkbenchModelConfig)
    context.provider.assert_not_awaited()
    async with AsyncSession(context.engine) as session:
        saved = await context.repository.aget_own(session, "linsight_llm")
        assert saved.tenant_id == 101
        return json.loads(saved.value)


async def test_omitted_models_preserves_existing(merge_store):
    incoming = WorkbenchModelConfig(embedding_model=None)
    assert incoming.models is None
    persisted = await _run_and_capture(merge_store, incoming)
    assert [model["id"] for model in persisted["models"]] == ["727", "774"]


async def test_explicit_empty_models_clears(merge_store):
    persisted = await _run_and_capture(merge_store, WorkbenchModelConfig(models=[], embedding_model=None))
    assert persisted["models"] == []


async def test_provided_models_replace_normally(merge_store):
    incoming = WorkbenchModelConfig(models=[WSModel(id="840", name="qwen3.7-max")], embedding_model=None)
    persisted = await _run_and_capture(merge_store, incoming)
    assert [model["id"] for model in persisted["models"]] == ["840"]


@pytest.mark.parametrize("invalid_model_id", ["", "null", "undefined", "0", "-1"])
async def test_invalid_embedding_model_id_returns_business_error(merge_store, invalid_model_id):
    incoming = WorkbenchModelConfig(
        models=[WSModel(id="840", name="new")], embedding_model=WSModel(id=invalid_model_id)
    )
    with pytest.raises(WorkbenchEmbeddingError) as raised:
        await _run_and_capture(merge_store, incoming)
    assert raised.value.code == 10810
    merge_store.provider.assert_not_awaited()


async def test_chat_default_model_id_persists_alongside_linsight_default(merge_store):
    incoming = WorkbenchModelConfig(
        models=[WSModel(id="840", name="qwen3.7-max"), WSModel(id="841", name="deepseek-v4")],
        linsight_default_model_id="840",
        chat_default_model_id="841",
        embedding_model=None,
    )
    persisted = await _run_and_capture(merge_store, incoming)
    assert persisted["linsight_default_model_id"] == "840" and persisted["chat_default_model_id"] == "841"


async def test_chat_default_model_id_none_is_allowed(merge_store):
    incoming = WorkbenchModelConfig(
        models=[WSModel(id="840", name="new")], chat_default_model_id=None, embedding_model=None
    )
    persisted = await _run_and_capture(merge_store, incoming)
    assert persisted["chat_default_model_id"] is None


async def test_chat_default_model_id_must_come_from_models_list(merge_store):
    incoming = WorkbenchModelConfig(
        models=[WSModel(id="840", name="new")], chat_default_model_id="999", embedding_model=None
    )
    with pytest.raises(WorkbenchChatDefaultModelError) as raised:
        await _run_and_capture(merge_store, incoming)
    assert raised.value.code == 10811
    merge_store.provider.assert_not_awaited()


@pytest.mark.parametrize("invalid_model_id", ["", "null", "undefined", "0", "-1", "abc"])
async def test_chat_default_model_id_rejects_non_model_values(merge_store, invalid_model_id):
    incoming = WorkbenchModelConfig(
        models=[WSModel(id="840", name="new")], chat_default_model_id=invalid_model_id, embedding_model=None
    )
    with pytest.raises(WorkbenchChatDefaultModelError) as raised:
        await _run_and_capture(merge_store, incoming)
    assert raised.value.code == 10811
    assert isinstance(raised.value.__cause__, ValueError)
    merge_store.provider.assert_not_awaited()


async def test_chat_default_model_id_validated_against_merged_old_models(merge_store):
    persisted = await _run_and_capture(
        merge_store, WorkbenchModelConfig(chat_default_model_id="727", embedding_model=None)
    )
    assert persisted["chat_default_model_id"] == "727"
    assert [model["id"] for model in persisted["models"]] == ["727", "774"]
    with pytest.raises(WorkbenchChatDefaultModelError):
        await _run_and_capture(merge_store, WorkbenchModelConfig(chat_default_model_id="840", embedding_model=None))


@pytest.mark.parametrize("chat_default", [None, "840"])
async def test_invalid_other_model_slot_is_rejected_without_filtering(merge_store, chat_default):
    from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError

    incoming = WorkbenchModelConfig(
        models=[WSModel(id="840", name="valid"), WSModel(id="abc", name="invalid")],
        chat_default_model_id=chat_default,
        embedding_model=None,
    )
    with pytest.raises(ResourceReferenceInvalidError) as raised:
        await _run_and_capture(merge_store, incoming)
    assert raised.value.code == 10996
    merge_store.provider.assert_not_awaited()
