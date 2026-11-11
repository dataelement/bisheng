"""Unified SPACE creation uses the real SQL/R2 chain and existing web policy."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlmodel import select

from bisheng.common.errcode.knowledge import KnowledgeNoEmbeddingError, ResourceReferenceInvalidError
from bisheng.common.errcode.knowledge_space import SpaceCreationRequestConflictError
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.services.knowledge_creation_policy import (
    KnowledgeCreationContext,
    KnowledgeCreationPolicy,
)
from test.knowledge_unification import test_kn_space_reference_lifecycle as fixtures
from test.knowledge_unification import test_settings_repo as settings_fixtures

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business
consumer = fixtures.consumer
system_defaults = settings_fixtures.system_defaults


@pytest.fixture
def advanced(consumer, monkeypatch):
    business, service, adapter = consumer
    policy = AsyncMock()
    monkeypatch.setattr(KnowledgeCreationPolicy, "revalidate", policy)
    context = KnowledgeCreationContext(7, 101, {"entry_kind": "web", "session_id": "current-session"})
    return business, service, adapter, context, policy


def created(context, ident):
    return next(row for row in fixtures.state(context)["knowledge"] if row["id"] == ident)


async def test_ordinary_creation_keeps_workbench_model_and_does_not_snapshot_system_defaults(consumer):
    context, service, _ = consumer
    first = await service.create_knowledge_space(name="ordinary")
    row = created(context, first.id)
    assert row["model"] == "11" and row["processing_defaults"] is None
    assert row["processing_config_version"] == 0
    fixtures.module.LLMService.get_workbench_llm.return_value = SimpleNamespace(embedding_model=SimpleNamespace(id=12))
    second = await service.create_knowledge_space(name="later")
    assert created(context, first.id)["model"] == "11"
    assert created(context, second.id)["model"] == "12"


@pytest.mark.parametrize("model", [12, 22])
async def test_explicit_model_and_full_defaults_commit_with_actual_creator_and_reference(
    advanced, system_defaults, model
):
    context, service, adapter, qualification, policy = advanced
    before = fixtures.state(context)
    result = await service.create_knowledge_space(
        name="advanced",
        embedding_model_id=model,
        processing_defaults=system_defaults,
        web_creation_context=qualification,
    )
    policy.assert_awaited_with(qualification)
    row = created(context, result.id)
    assert row["model"] == str(model) and row["processing_defaults"] == system_defaults.model_dump(mode="json")
    assert row["processing_config_version"] == 0 and row["tenant_id"] == 101
    after = fixtures.state(context)
    assert len(after["space_channel_member"]) == len(before["space_channel_member"]) + 1
    refs = [item for item in after["business_resource_reference"] if item["source_id"] == str(result.id)]
    assert [(item["slot_key"], item["target_id"]) for item in refs] == [("model", str(model))]
    adapter.authorize_created.assert_awaited_once()


async def test_selected_management_tenant_does_not_rewrite_original_web_identity(advanced, system_defaults):
    context, service, _, qualification, policy = advanced
    context.user.tenant_id = 1
    qualification = replace(qualification, tenant_id=1)
    result = await service.create_knowledge_space(
        name="selected", embedding_model_id=12, processing_defaults=system_defaults, web_creation_context=qualification
    )
    assert result.tenant_id == 101 and context.user.tenant_id == 1
    policy.assert_awaited_with(qualification)


@pytest.mark.parametrize("options", [{"embedding_model_id": 12}, {"processing_defaults": True}])
async def test_advanced_values_require_original_web_qualification(advanced, system_defaults, options):
    context, service, _, _, _ = advanced
    if "processing_defaults" in options:
        options = {"processing_defaults": system_defaults}
    before = fixtures.state(context)
    with pytest.raises(PermissionDeniedError):
        await service.create_knowledge_space(name="forged", **options)
    assert fixtures.state(context) == before


@pytest.mark.parametrize("failure", ["policy", "other_actor", "projection", "unshared", "missing_model", "wrong_kind"])
async def test_failed_advanced_creation_leaves_no_space_creator_defaults_or_references(
    advanced, system_defaults, failure
):
    context, service, adapter, qualification, policy = advanced
    before = fixtures.state(context)
    model = 12
    error = PermissionDeniedError
    if failure == "policy":
        policy.side_effect = PermissionDeniedError()
    elif failure == "other_actor":
        qualification = replace(qualification, user_id=99)
    elif failure == "projection":
        adapter.authorize_created.side_effect = RuntimeError("projection unavailable")
        error = RuntimeError
    elif failure == "unshared":
        context.sharing.allowed = frozenset()
        model, error = 22, ResourceReferenceInvalidError
    elif failure == "missing_model":
        model, error = 999, ResourceReferenceInvalidError
    else:
        model, error = 33, KnowledgeNoEmbeddingError
    with pytest.raises(error):
        await service.create_knowledge_space(
            name="must rollback",
            embedding_model_id=model,
            processing_defaults=system_defaults,
            web_creation_context=qualification,
        )
    assert fixtures.state(context) == before


async def test_invalid_internal_defaults_are_revalidated_before_any_sql(advanced, system_defaults):
    context, service, _, qualification, _ = advanced
    invalid = system_defaults.model_copy(
        update={"document": system_defaults.document.model_copy(update={"chunk_size": -1})}
    )
    before = fixtures.state(context)
    with pytest.raises(ValidationError):
        await service.create_knowledge_space(
            name="invalid", processing_defaults=invalid, web_creation_context=qualification
        )
    assert fixtures.state(context) == before


async def test_explicit_model_does_not_require_a_workbench_default(advanced):
    context, service, _, qualification, _ = advanced
    fixtures.module.LLMService.get_workbench_llm.return_value = None
    result = await service.create_knowledge_space(
        name="explicit", embedding_model_id=12, web_creation_context=qualification
    )
    assert created(context, result.id)["model"] == "12"


@pytest.mark.parametrize("changed", ["model", "defaults"])
async def test_idempotency_hash_binds_explicit_model_and_canonical_defaults(advanced, system_defaults, changed):
    context, service, _, qualification, _ = advanced
    kwargs = {
        "name": "durable",
        "creation_request_id": "create-1",
        "embedding_model_id": 12,
        "processing_defaults": system_defaults,
        "web_creation_context": qualification,
    }
    result = await service.create_knowledge_space(**kwargs)
    async with context.sessions() as session:
        row = (await session.exec(select(Knowledge).where(Knowledge.id == result.id))).one()
    service._existing_creation.return_value = row
    before = fixtures.state(context)
    if changed == "model":
        kwargs["embedding_model_id"] = 11
    else:
        kwargs["processing_defaults"] = system_defaults.model_copy(
            update={"table": system_defaults.table.model_copy(update={"slice_length": 20})}
        )
    with pytest.raises(SpaceCreationRequestConflictError):
        await service.create_knowledge_space(**kwargs)
    assert fixtures.state(context) == before
