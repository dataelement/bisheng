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
from bisheng.database.models.assistant import Assistant
from bisheng.llm.domain.models import tenant_system_model_config as defaults_module
from bisheng.llm.domain.models.tenant_system_model_config import TenantSystemModelConfig
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
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
    async with context.engine.begin() as connection:
        await connection.run_sync(lambda conn: TenantSystemModelConfig.__table__.create(conn))
    async with context.sessions() as session:
        with bypass_tenant_filter():
            session.add_all(
                [
                    TenantSystemModelConfig(
                        tenant_id=tenant,
                        key="assistant_llm",
                        value=json.dumps({"llm_list": [{"model_id": model, "default": True}]}),
                    )
                    for tenant, model in ((1, 1), (101, 2))
                ]
            )
            await session.commit()
    # Use the real typed business default resolver and real per-tenant SQL rows.
    # Only its database boundary is redirected to this isolated test database.
    monkeypatch.setattr(defaults_module, "get_async_db_session", context.sessions)
    monkeypatch.setattr(assistant_module.LLMService, "get_assistant_llm", ORIGINAL_ASSISTANT_DEFAULTS)
    return context


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
        assistant, _, references, source = await bindings.inspect_business(context)
        assert assistant.tenant_id == source.tenant_id == 101
        assert assistant.model_name == "2"  # Leaf default, not JWT home's model 1.
        assert {(row.tenant_id, row.target_id) for row in references} == {(101, "2")}
        await AssistantService.update_assistant(
            context.request,
            context.user,
            AssistantUpdateReq(id="assistant-a", model_name="1", knowledge_list=[10], temperature=1),
        )
        assistant, links, references, source = await bindings.inspect_business(context)
        assert assistant.tenant_id == source.tenant_id == 101 and assistant.model_name == "1"
        assert [(row.tenant_id, row.knowledge_id) for row in links] == [(101, 10)]
        assert {(row.tenant_id, row.target_id) for row in references} == {(101, "1"), (101, "10")}
        await AssistantService.delete_assistant(context.request, context.user, assistant.id)
        assistant, _, references, source = await bindings.inspect_business(context)
        assert assistant.is_delete == 1 and source.tenant_id == 101 and not source.effective and not references
        # A connection read has no ORM tenant filter that could hide an accidental
        # Root-owned source/guard row from this assertion.
        async with context.engine.connect() as connection:
            rows = (await connection.execute(select(BusinessReferenceSet.__table__))).all()
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
        assistant, _, references, source = await bindings.inspect_business(context)
        assert assistant.prompt == "" and assistant.tenant_id == source.tenant_id == 101
        assert {row.target_id for row in references} == {"2"}
        assert context.user.tenant_id == 1
        assert context.user._runtime_credential_reference == {"credential_id": "credential-7", "data_scope": "OWNED"}
