from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.core.context.tenant import is_tenant_filter_bypassed
from bisheng.developer_token.domain.schemas import DeveloperTokenPrincipal
from bisheng.mcp_server.domain.services import factory


@pytest.mark.parametrize("fail", [False, True])
async def test_production_factory_binds_and_closes_one_session(monkeypatch, fail):
    """AC-10: production dependency wiring closes the same per-call repository session."""
    session = AsyncSession()
    closed = []

    @asynccontextmanager
    async def session_scope():
        try:
            yield session
        finally:
            await session.close()
            closed.append(session)

    monkeypatch.setattr(factory, "get_async_db_session", session_scope)
    runtime = SimpleNamespace(config=SimpleNamespace(max_source_link_concurrency=2, total_timeout_seconds=1))
    monkeypatch.setattr(factory, "get_async_retrieval_runtime", AsyncMock(return_value=runtime))
    monkeypatch.setattr(factory, "get_minio_storage", AsyncMock(return_value=object()))
    user = UserPayload(user_id=7, user_name="bound", user_role=[2], tenant_id=7)
    try:
        async with factory.build_search_service(None, user) as service:
            assert service.chat_service.login_user is user
            assert service.chat_service.file_repo.session is session
            assert service.chat_service.doc_repo.session is session
            assert service.chat_service.version_repo.session is session
            assert service.source_service.file_repository is service.chat_service.file_repo
            assert service.chat_service.retrieval_runtime is runtime
            if fail:
                raise RuntimeError("test interruption")
    except RuntimeError:
        assert fail
    assert closed == [session]


async def test_identity_factory_uses_bound_principal_without_lookup_session(monkeypatch):
    """F084 AC-02: 身份完全来自认证 Token, 不读取账号或当前关系。"""
    lookup = AsyncMock(side_effect=AssertionError("identity must not query database"))
    monkeypatch.setattr(factory, "get_async_db_session", lookup)
    bound = UserPayload(user_id=8, user_name="bound", user_role=[2], tenant_id=7)
    principal = DeveloperTokenPrincipal(token_id=10, tenant_id=7, user=bound)
    identity = await factory.resolve_execution_identity(principal)
    assert identity.user is bound and identity.tenant_id == 7
    lookup.assert_not_called()
    assert not is_tenant_filter_bypassed()


async def test_tool_factory_uses_one_request_session_for_all_domain_services(monkeypatch):
    """AC-16: production tool wiring never shares a mutable owner across requests."""
    session = AsyncSession()
    closed = []

    @asynccontextmanager
    async def session_scope():
        try:
            yield session
        finally:
            await session.close()
            closed.append(session)

    monkeypatch.setattr(factory, "get_async_db_session", session_scope)
    monkeypatch.setattr(factory, "get_minio_storage", AsyncMock(return_value=object()))
    user = UserPayload(user_id=7, user_name="bound", user_role=[2], tenant_id=7)
    async with factory.build_tool_services(None, user) as services:
        query = services.list_files.__self__
        content = services.get_file_detail.__self__
        ingestion = services.upload_file.__self__
        assert query.repository.session is session
        assert content.repository is query.repository
        assert ingestion.query is query
        assert query.owner.document_entry_resolver is content.resolver
        assert query.owner.login_user is user
    assert closed == [session]
