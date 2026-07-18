"""Integration test: add_file must create a KnowledgeDocument + V1 KnowledgeDocumentVersion.

Strategy:
- Use the conftest async_db_session (SQLite in-memory) as the backing session
  for both the document/version writes AND the post-call assertion queries.
- Patch get_async_db_session (as used by the service module) with a context
  manager that yields the same in-memory session.
- Patch all other heavy machinery (process_one_file, Celery, QuotaService,
  permission checks, DAO update calls) so we only exercise the doc+V1 path.
"""
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from test.knowledge.test_knowledge_space_service import (
    _load_service_class,
    _make_file,
    _make_login_user,
    _make_space,
)
from bisheng.knowledge.domain.models.knowledge import AuthTypeEnum
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session_context_manager(session: AsyncSession):
    """Return an asynccontextmanager that yields the given session.

    This replaces get_async_db_session inside knowledge_space_service so that
    the service's `async with get_async_db_session() as v_session:` block uses
    our in-memory SQLite session.

    NOTE: We must NOT call session.commit() on the real session here because
    commit() in SQLite disposes the current transaction and can close rows.
    Instead we let the service call commit() — the session will handle it.
    """
    @asynccontextmanager
    async def _ctx():
        yield session

    return _ctx


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def service():
    return _load_service_class()(None, _make_login_user())


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_file_creates_document_and_v1(service, async_db_session: AsyncSession):
    """After add_file returns, exactly one KnowledgeDocument and one V1
    KnowledgeDocumentVersion (is_primary=True) should exist in the DB.
    """
    knowledge_id = 1
    space = _make_space(auth_type=AuthTypeEnum.PUBLIC)
    # fake file returned by process_one_file — already "committed" by that call
    added_file = _make_file(
        file_id=42,
        knowledge_id=knowledge_id,
        file_name="report.pdf",
        file_level_path="",
        level=0,
    )
    added_file.file_size = 100

    session_ctx = _make_session_context_manager(async_db_session)

    with patch.object(
        service, "_require_permission_id", new_callable=AsyncMock,
    ), patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
        new_callable=AsyncMock,
        return_value=space,
    ), patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.SpaceFileDao.get_user_total_file_size",
        new_callable=AsyncMock,
        return_value=0,
    ), patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.QuotaService.get_knowledge_space_upload_limit_bytes",
        new_callable=AsyncMock,
        return_value=None,
    ), patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.QuotaService.get_tenant_storage_remaining_bytes",
        new_callable=AsyncMock,
        return_value=None,
    ), patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeService.process_one_file",
        return_value=added_file,
    ), patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.batch_write_tuples",
        new_callable=AsyncMock,
    ), patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.OwnerService.write_owner_tuple",
        new_callable=AsyncMock,
    ), patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_knowledge_update_time_by_id",
        new_callable=AsyncMock,
    ), patch.object(
        service, "update_folder_update_time", new_callable=AsyncMock,
    ), patch.object(
        service, "_initialize_child_resource_permissions", new_callable=AsyncMock,
    ), patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.get_async_db_session",
        new=session_ctx,
    ), patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.file_worker"
        ".parse_knowledge_file_celery",
        new_callable=MagicMock,
    ) as mock_celery:
        mock_celery.delay = MagicMock()

        result = await service.add_file(knowledge_id, ["/tmp/report.pdf"])

    # --- Assert: service returned the fake file ---
    assert len(result) >= 1
    assert result[0].id == 42

    # --- Assert: KnowledgeDocument row was created ---
    doc_rows = (await async_db_session.execute(
        select(KnowledgeDocument).where(KnowledgeDocument.knowledge_id == knowledge_id)
    )).scalars().all()
    assert len(doc_rows) == 1, f"Expected 1 KnowledgeDocument, got {len(doc_rows)}"
    doc = doc_rows[0]
    assert doc.knowledge_id == knowledge_id

    # --- Assert: KnowledgeDocumentVersion V1 row was created ---
    ver_rows = (await async_db_session.execute(
        select(KnowledgeDocumentVersion).where(
            KnowledgeDocumentVersion.document_id == doc.id
        )
    )).scalars().all()
    assert len(ver_rows) == 1, f"Expected 1 KnowledgeDocumentVersion, got {len(ver_rows)}"
    ver = ver_rows[0]
    assert ver.knowledge_file_id == 42
    assert ver.version_no == 1
    assert ver.is_primary is True

    # --- Assert: doc.primary_version_id was back-filled ---
    # Re-fetch doc to see updated primary_version_id
    refreshed_doc = (await async_db_session.execute(
        select(KnowledgeDocument).where(KnowledgeDocument.id == doc.id)
    )).scalar_one()
    assert refreshed_doc.primary_version_id == ver.id
