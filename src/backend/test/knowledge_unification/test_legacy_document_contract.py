"""Actual SPACE/R2 creation and bounded old document views; QA stays separate."""

from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.knowledge.application.legacy_documents import LegacyDocumentsApplication
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeCreate
from bisheng.open_api.domain.context import (
    OpenApiPrincipal,
    reset_current_open_api_principal,
    set_current_open_api_principal,
)
from test.knowledge_unification import test_kn_creation as creation
from test.knowledge_unification.test_kn_model_bindings import state

store = creation.store
tenant = creation.tenant
business = creation.business
consumer_base = creation.consumer
advanced = creation.advanced


@pytest.fixture
async def consumer(consumer_base, monkeypatch):
    from unittest.mock import Mock

    from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
    from bisheng.user.domain.models.user import UserDao

    # This fixture exercises creation/R2 with the original projection transport
    # isolated. Return no action grants at the new response enrichment seam;
    # real typed permission decisions are covered by the listing native tests.
    monkeypatch.setattr(
        KnowledgeService.permission_service, "get_knowledge_action_map_async", AsyncMock(return_value={})
    )
    monkeypatch.setattr(UserDao, "get_user_by_ids", Mock(return_value=[]))
    return consumer_base


async def test_old_create_persists_space_creator_and_real_model_source_with_old_dto_only(consumer):
    context, service, adapter = consumer
    result = await LegacyDocumentsApplication(space_service=service).acreate(
        request=None,
        identity=context.user,
        command=KnowledgeCreate(name="old document"),
    )
    assert result.type == 0
    async with context.sessions() as session:
        row = await session.get(Knowledge, result.id)
        assert row.type == 3 and row.model == "11" and row.user_id == 7
    refs = [row for row in state(context)["business_resource_reference"] if row["source_id"] == str(result.id)]
    assert [(row["slot_key"], row["target_id"]) for row in refs] == [("model", "11")]
    assert adapter.authorize_created.call_args.kwargs["record"].resource_type == "knowledge_space"


async def test_explicit_old_model_is_preserved_by_original_qualified_creation(advanced):
    context, service, _, qualification, policy = advanced
    result = await LegacyDocumentsApplication(space_service=service).acreate(
        request=None,
        identity=context.user,
        command=KnowledgeCreate(name="selected", model="12"),
        web_creation_context=qualification,
    )
    assert result.type == 0 and result.model == "12"
    policy.assert_awaited_with(qualification)


async def test_open_creation_uses_real_principal_scope_without_web_context_or_menu(consumer, monkeypatch):
    context, service, _ = consumer
    from bisheng.knowledge.domain.services.knowledge_creation_policy import KnowledgeCreationPolicy

    revalidate = AsyncMock(side_effect=AssertionError("machine creation must not fake a web session"))
    monkeypatch.setattr(KnowledgeCreationPolicy, "revalidate", revalidate)
    principal = OpenApiPrincipal(
        credential_id=3,
        actor_kind="service_account",
        actor_id=8,
        actor_name="svc",
        tenant_id=101,
        resource_owner_user_id=7,
        scopes=frozenset({"knowledge:write"}),
        authorization_subject_type="service_account",
        authorization_subject_id=8,
        effective_user_id=None,
    )
    token = set_current_open_api_principal(principal)
    try:
        result = await LegacyDocumentsApplication(space_service=service).acreate(
            request=None,
            identity=context.user,
            command=KnowledgeCreate(name="api", model="12"),
            entry_kind="open_api",
        )
    finally:
        reset_current_open_api_principal(token)
    assert result.type == 0 and result.model == "12"
    revalidate.assert_not_awaited()


async def test_machine_kind_without_real_principal_is_not_creation_authority(consumer):
    context, service, _ = consumer
    with pytest.raises(PermissionDeniedError):
        await LegacyDocumentsApplication(space_service=service).acreate(
            request=None,
            identity=context.user,
            command=KnowledgeCreate(name="forged", model="12"),
            entry_kind="open_api",
        )


def test_legacy_view_does_not_mutate_an_actual_source_owner_row():
    row = Knowledge(id=13, tenant_id=101, user_id=7, name="space", type=3)
    result = LegacyDocumentsApplication.view(row)
    assert result.type == 0 and row.type == 3
    assert LegacyDocumentsApplication.view(row, legacy=False).type == 3
    qa = Knowledge(id=12, tenant_id=101, user_id=7, name="qa", type=1)
    assert LegacyDocumentsApplication.view(qa).type == 1


async def test_actual_v1_v2_and_mcp_old_create_entries_share_space_r2_and_keep_outer_type(advanced, monkeypatch):
    from bisheng.knowledge.api.endpoints import knowledge as v1
    from bisheng.knowledge.application import legacy_documents
    from bisheng.knowledge.domain.services.knowledge_creation_policy import KnowledgeCreationPolicy
    from bisheng.open_endpoints.api.endpoints import filelib as v2
    from bisheng.open_mcp import application as mcp
    from bisheng.open_mcp.contracts import KnowledgeCreateInput

    context, service, adapter, qualification, _ = advanced
    actual = legacy_documents.LegacyDocumentsApplication

    class Bound(actual):
        def __init__(self, **kwargs):
            super().__init__(space_service=service, **kwargs)

    monkeypatch.setattr(legacy_documents, "LegacyDocumentsApplication", Bound)
    monkeypatch.setattr(KnowledgeCreationPolicy, "prepare", AsyncMock(return_value=qualification))
    web = await v1.create_knowledge(
        request=None, login_user=context.user, knowledge=v1.KnowledgeWebCreate(name="web-old", type=0)
    )
    assert web.data.type == 0 and web.data.model == "11"
    new = await v1.create_knowledge(
        request=None, login_user=context.user, knowledge=v1.KnowledgeWebCreate(name="web-space", type=3)
    )
    assert new.data.type == 3 and new.data.model == "11"
    principal = OpenApiPrincipal(
        credential_id=3,
        actor_kind="service_account",
        actor_id=8,
        actor_name="svc",
        tenant_id=101,
        resource_owner_user_id=7,
        scopes=frozenset({"knowledge:write"}),
        authorization_subject_type="service_account",
        authorization_subject_id=8,
        effective_user_id=None,
    )
    token = set_current_open_api_principal(principal)
    monkeypatch.setattr(v2, "get_open_api_operator_async", AsyncMock(return_value=context.user))
    monkeypatch.setattr(mcp, "get_open_api_operator_async", AsyncMock(return_value=context.user))
    try:
        api = await v2.create(request=None, knowledge=KnowledgeCreate(name="api-old", type=0, model="12"))
        assert api.data.type == 0 and api.data.model == "12"
        tool = await mcp.create_knowledge(
            request=None,
            command=KnowledgeCreateInput(name="mcp-old", type=0, model="12"),
            version_repo=None,
            doc_repo=None,
        )
        assert tool.type == 0 and tool.model == "12"
    finally:
        reset_current_open_api_principal(token)
    snapshots = state(context)
    ids = {web.data.id, new.data.id, api.data.id, tool.id}
    assert {row["type"] for row in snapshots["knowledge"] if row["id"] in ids} == {3}
    refs = [row for row in snapshots["business_resource_reference"] if row["source_id"] in {str(i) for i in ids}]
    assert len(refs) == 4
    assert adapter.authorize_created.await_count == 4


@pytest.mark.parametrize("kind,code", [(0, 10901), (3, 10810)])
async def test_missing_workbench_default_keeps_legacy_error_without_changing_new_space_error(consumer, kind, code):
    from bisheng.common.errcode.base import BaseErrorCode
    from test.knowledge_unification import test_kn_space_reference_lifecycle as native

    context, service, _ = consumer
    native.module.LLMService.get_workbench_llm.return_value = None
    with pytest.raises(BaseErrorCode) as error:
        await LegacyDocumentsApplication(space_service=service).acreate(
            request=None,
            identity=context.user,
            command=KnowledgeCreate(name="missing default", type=kind),
        )
    assert error.value.Code == code
