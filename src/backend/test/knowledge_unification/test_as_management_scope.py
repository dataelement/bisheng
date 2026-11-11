"""T307: selected management tenant is distinct from the JWT home tenant.

覆盖 AC: AC-79, AC-83, AC-87
This is a regression for the existing correct AS path, not a fabricated red.
"""

import json
from contextlib import contextmanager
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from bisheng.api.services import assistant as assistant_module
from bisheng.api.services.assistant import AssistantService
from bisheng.api.v1.schemas import AssistantUpdateReq
from bisheng.assistant.domain.repositories.assistant_repository import AssistantRepository
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.open_api import PersonalTokenDataScopeError
from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    current_tenant_id,
    get_admin_scope_tenant_id,
    get_current_tenant_id,
    get_is_management_api,
    set_admin_scope_tenant_id,
    set_current_tenant_id,
    set_is_management_api,
)
from bisheng.core.database import tenant_filter
from bisheng.database.models.assistant import Assistant
from bisheng.database.models.tenant import Tenant
from bisheng.llm.application import model_default_read
from bisheng.llm.application.model_default_read_identity import ModelDefaultReadIdentityPort
from bisheng.llm.application.model_default_source_owner import ModelDefaultSourceOwner
from bisheng.llm.application.source_read_target_owner import ModelSourceReadTargetOwner
from bisheng.llm.domain.models.llm_server import LLMModel, LLMServer
from bisheng.llm.domain.models.tenant_system_model_config import TenantSystemModelConfig
from bisheng.llm.domain.services.default_reference_extractor import (
    MODEL_DEFAULT_REFERENCE_EXTRACTOR_VERSION,
    extract_model_default_references,
)
from bisheng.resource_reference.application.contracts import reference_set_digest
from bisheng.resource_reference.application.source_read import ReferenceSourceReadRuntime
from bisheng.resource_reference.application.source_verification import SourceReadVerifier
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from bisheng.resource_reference.domain.repositories.source_read_repository import SourceReadRepository
from test.knowledge_unification import test_as_bindings as bindings

assistant_tenant = bindings.assistant_tenant
assistant_business = bindings.assistant_business
ORIGINAL_ASSISTANT_DEFAULTS = assistant_module.LLMService.get_assistant_llm


@contextmanager
def selected_management_tenant():
    """Mirror the trusted F019 middleware pin; never mutate login identity."""
    previous_scope = get_admin_scope_tenant_id()
    previous_management = get_is_management_api()
    home_token = set_current_tenant_id(1)
    set_admin_scope_tenant_id(101)
    set_is_management_api(True)
    try:
        yield
    finally:
        set_is_management_api(previous_management)
        set_admin_scope_tenant_id(previous_scope)
        current_tenant_id.reset(home_token)


@pytest.fixture
async def management_assistant(assistant_business, monkeypatch):
    context = assistant_business
    context.user = UserPayload(user_id=7, user_name="Root operator", user_role=[], tenant_id=1, is_global_super=True)
    context.user._runtime_credential_reference = {"credential_id": "credential-7", "data_scope": "OWNED"}
    models = (Tenant, LLMServer, LLMModel, TenantSystemModelConfig)
    monkeypatch.setattr(
        tenant_filter,
        "_tenant_aware_tables",
        tenant_filter._tenant_aware_tables
        | {model.__tablename__ for model in models if "tenant_id" in model.__table__.columns},
    )
    tenant_filter.register_tenant_filter_events()
    async with context.engine.begin() as connection:
        for model in models:
            await connection.run_sync(lambda conn, model=model: model.__table__.create(conn))
    async with context.sessions() as session:
        with bypass_tenant_filter():
            session.add_all(
                [
                    Tenant(id=1, tenant_code="root", tenant_name="Root"),
                    Tenant(id=101, tenant_code="leaf", tenant_name="Leaf", parent_tenant_id=1),
                    LLMServer(id=1, tenant_id=1, name="Root provider", type="openai"),
                    LLMServer(id=2, tenant_id=101, name="Leaf provider", type="openai"),
                    LLMModel(id=1, tenant_id=1, server_id=1, model_name="Root model", model_type="llm"),
                    LLMModel(id=2, tenant_id=101, server_id=2, model_name="Leaf model", model_type="llm"),
                ]
            )
            for tenant, model in ((1, 1), (101, 2)):
                payload = {"llm_list": [{"model_id": model, "default": True}]}
                references = extract_model_default_references("assistant_llm", payload)
                source = {"tenant_id": tenant, "source_type": "model_default", "source_id": "assistant_llm"}
                session.add(TenantSystemModelConfig(tenant_id=tenant, key="assistant_llm", value=json.dumps(payload)))
                session.add_all(
                    [
                        BusinessReferenceSet(
                            **source,
                            source_version="__root__",
                            record_kind="root_guard",
                            source_revision=1,
                            ready=False,
                            effective=False,
                            extractor_version="root-guard-v1",
                            digest=reference_set_digest(()),
                        ),
                        BusinessReferenceSet(
                            **source,
                            source_version="current",
                            source_revision=1,
                            ready=True,
                            effective=True,
                            extractor_version=MODEL_DEFAULT_REFERENCE_EXTRACTOR_VERSION,
                            digest=reference_set_digest(references),
                        ),
                    ]
                )
                session.add_all(
                    BusinessResourceReference(
                        **source,
                        source_version="current",
                        source_revision=1,
                        slot_key=spec.slot_key,
                        target_type="model",
                        target_id=spec.target.target_id,
                        target_tenant_id=tenant,
                    )
                    for spec in references
                )
            await session.commit()
    # The selected ID now traverses the actual dedicated default source graph:
    # SQL own/Root resolution, complete indexed configuration and current model
    # facts. Only its Session factory points at this isolated database.
    identity_port = ModelDefaultReadIdentityPort()
    verifier = SourceReadVerifier(
        {"model_default": ModelDefaultSourceOwner(identity_port=identity_port)}, identity_port
    )
    target = ModelSourceReadTargetOwner(verifier)
    core = ReferenceSourceReadRuntime(verifier, SourceReadRepository(verifier), {"model": target})
    reads = model_default_read.ModelDefaultReadRuntime(core, identity_port)
    monkeypatch.setattr(model_default_read, "_runtime", reads)
    monkeypatch.setattr(model_default_read, "get_async_db_session", context.sessions)
    monkeypatch.setattr(assistant_module.LLMService, "get_assistant_llm", ORIGINAL_ASSISTANT_DEFAULTS)
    return context


async def inspect_assistant(context):
    async with context.sessions() as session:
        repository = AssistantRepository()
        assistant = await repository.aget(session, "assistant-a")
        links = await repository.alist_links(session, "assistant-a") if assistant else ()
        references = (
            (
                await session.execute(
                    select(BusinessResourceReference).where(BusinessResourceReference.source_type == "assistant")
                )
            )
            .scalars()
            .all()
        )
        source = await context.repository.aget_source_set(session, bindings.source_key())
        return assistant, links, references, source


async def create(context):
    await AssistantService.create_assistant(
        context.request, context.user, Assistant(id="assistant-a", name="selected tenant", user_id=context.user.user_id)
    )


async def test_super_home_root_selected_leaf_keeps_crud_and_sources_in_selected_tenant(management_assistant):
    context = management_assistant
    identity_before = context.user.model_dump()
    credential_before = dict(context.user._runtime_credential_reference)
    with selected_management_tenant():
        assert context.user.tenant_id == 1 and get_current_tenant_id() == 101
        await create(context)
        assistant, _, references, source = await inspect_assistant(context)
        assert assistant.tenant_id == source.tenant_id == 101
        assert assistant.model_name == "2"  # Leaf default, not JWT home's model 1.
        assert {(row.tenant_id, row.target_id) for row in references} == {(101, "2")}
        await AssistantService.update_assistant(
            context.request,
            context.user,
            AssistantUpdateReq(id="assistant-a", model_name="1", knowledge_list=[10], temperature=1),
        )
        assistant, links, references, source = await inspect_assistant(context)
        assert assistant.tenant_id == source.tenant_id == 101 and assistant.model_name == "1"
        assert [(row.tenant_id, row.knowledge_id) for row in links] == [(101, 10)]
        assert {(row.tenant_id, row.target_id) for row in references} == {(101, "1"), (101, "10")}
        await AssistantService.delete_assistant(context.request, context.user, assistant.id)
        assistant, _, references, source = await inspect_assistant(context)
        assert assistant.is_delete == 1 and source.tenant_id == 101 and not source.effective and not references
        # A connection read has no ORM tenant filter that could hide an accidental
        # Root-owned source/guard row from this assertion.
        async with context.engine.connect() as connection:
            rows = (
                await connection.execute(
                    select(BusinessReferenceSet.__table__).where(BusinessReferenceSet.source_type == "assistant")
                )
            ).all()
            assert len(rows) == 2 and {row.tenant_id for row in rows} == {101}
    assert context.user.model_dump() == identity_before
    assert context.user._runtime_credential_reference == credential_before


async def test_selected_tenant_does_not_replace_or_discard_credential_narrowing(management_assistant, monkeypatch):
    context = management_assistant
    with selected_management_tenant():
        await create(context)
        deny = AsyncMock(side_effect=PersonalTokenDataScopeError())
        monkeypatch.setattr(assistant_module, "require_business_action", deny)
        with pytest.raises(PersonalTokenDataScopeError):
            await AssistantService.update_prompt("assistant-a", "denied change", context.user)
        assert deny.call_args.args[0] is context.user
        assistant, _, references, source = await inspect_assistant(context)
        assert assistant.prompt == "" and assistant.tenant_id == source.tenant_id == 101
        assert {row.target_id for row in references} == {"2"}
        assert context.user.tenant_id == 1
        assert context.user._runtime_credential_reference == {"credential_id": "credential-7", "data_scope": "OWNED"}
