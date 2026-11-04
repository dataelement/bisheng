"""Built-in retrieval uses trusted execution identity and the shared API contract."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError

from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.core.context.tenant import current_tenant_id
from bisheng.tool.domain.langchain import work_knowledge as module
from bisheng.tool.domain.services.executor import ToolExecutor


@pytest.fixture
def runtime(monkeypatch):
    token = current_tenant_id.set(5)
    user = SimpleNamespace(user_id=42, tenant_id=5, is_global_super=False)
    identity = AsyncMock(return_value=user)
    monkeypatch.setattr(module, "abuild_scoped_login_user", identity)
    session = object()

    @asynccontextmanager
    async def get_session():
        yield session

    monkeypatch.setattr(module, "get_async_db_session", get_session)
    service = SimpleNamespace(aretrieve_chunks=AsyncMock(return_value=[]))
    service_factory = Mock(return_value=service)
    monkeypatch.setattr(module, "KnowledgeSpaceChatService", service_factory)
    version_repo = object()
    monkeypatch.setattr(module, "KnowledgeDocumentVersionRepositoryImpl", Mock(return_value=version_repo))
    yield SimpleNamespace(
        tool=module.WorkKnowledgeSearch(user_id=42, tenant_id=5),
        user=user,
        identity=identity,
        service=service,
        factory=service_factory,
        version_repo=version_repo,
    )
    current_tenant_id.reset(token)


def test_schema_exposes_only_retrieval_inputs(runtime):
    assert set(runtime.tool.get_input_schema().model_fields) == {"query", "space_ids"}
    assert "user_id" not in runtime.tool.model_dump()
    assert "tenant_id" not in runtime.tool.model_dump()


@pytest.mark.parametrize("extra", [{"user_id": 1}, {"tenant_id": 1}, {"is_global_super": True}])
async def test_model_identity_injection_is_rejected(runtime, extra):
    with pytest.raises(ValidationError):
        await runtime.tool.ainvoke({"query": "q", "space_ids": [7], **extra})
    runtime.identity.assert_not_awaited()


async def test_ordinary_user_and_sources_are_preserved(runtime):
    runtime.service.aretrieve_chunks.return_value = [
        (
            7,
            SimpleNamespace(
                page_content="Allowed passage",
                metadata={
                    "document_id": 12,
                    "document_name": "Policy.pdf",
                    "chunk_index": 3,
                },
            ),
        )
    ]
    result = await runtime.tool.ainvoke({"query": " leave policy ", "space_ids": [7, 7, 9]})
    runtime.identity.assert_awaited_once_with(42, 5)
    runtime.factory.assert_called_once_with(request=None, login_user=runtime.user)
    assert runtime.service.version_repo is runtime.version_repo
    runtime.service.aretrieve_chunks.assert_awaited_once_with(
        query="leave policy", knowledge_base_ids=[7, 9], top_k=10, max_content=12000
    )
    assert result == {
        "chunks": [
            {
                "content": "Allowed passage",
                "space_id": 7,
                "document_id": 12,
                "document_name": "Policy.pdf",
                "chunk_index": 3,
            }
        ]
    }


async def test_permission_revocation_propagates(runtime):
    runtime.service.aretrieve_chunks.side_effect = PermissionError("view_file denied")
    with pytest.raises(PermissionError, match="view_file denied"):
        await runtime.tool.ainvoke({"query": "q", "space_ids": [7]})


async def test_deleted_execution_user_is_rejected(runtime):
    runtime.identity.return_value = None
    with pytest.raises(PermissionError, match="execution user"):
        await runtime.tool.ainvoke({"query": "q", "space_ids": [7]})
    runtime.factory.assert_not_called()


async def test_tenant_context_change_is_rejected_before_retrieval(runtime):
    token = current_tenant_id.set(6)
    try:
        with pytest.raises(PermissionError, match="tenant context"):
            await runtime.tool.ainvoke({"query": "q", "space_ids": [7]})
        runtime.identity.assert_not_awaited()
    finally:
        current_tenant_id.reset(token)


def test_sync_invocation_preserves_context_and_empty_result(runtime):
    assert runtime.tool.invoke({"query": "q", "space_ids": [7]}) == {"chunks": []}
    runtime.identity.assert_awaited_once_with(42, 5)


def test_executor_binds_caller_instead_of_shared_catalog_identity(runtime, monkeypatch):
    tool = SimpleNamespace(tool_key="bisheng_knowledge_search", is_preset=1)
    category = SimpleNamespace(tenant_id=1, user_id=None, extra='{"user_id":1,"tenant_id":1}')
    wrapper = Mock(side_effect=lambda **kwargs: kwargs["base_tool"])
    monkeypatch.setattr(ToolExecutor, "init_by_tool_instance", wrapper)
    result = ToolExecutor._init_by_tool_and_type(
        tool,
        category,
        app_id="cloud-work",
        app_name="Work",
        app_type=ApplicationTypeEnum.ASSISTANT,
        user_id=42,
        tenant_id=1,
    )
    assert (result.user_id, result.tenant_id) == (42, 5)
    assert wrapper.call_args.kwargs["user_id"] == 42


def test_executor_requires_explicit_tenant_context(runtime, monkeypatch):
    token = current_tenant_id.set(None)
    try:
        with pytest.raises(PermissionError, match="tenant context"):
            ToolExecutor._init_by_tool_and_type(
                SimpleNamespace(tool_key="bisheng_knowledge_search", is_preset=1),
                SimpleNamespace(),
                app_id="cloud-work",
                app_name="Work",
                app_type=ApplicationTypeEnum.ASSISTANT,
                user_id=42,
            )
    finally:
        current_tenant_id.reset(token)
