from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.user_deps import UserPayload
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
