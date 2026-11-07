"""Original SPACE entry point, native chain and request-independent application DI."""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.requests import Request

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge_space import SpaceFileSizeLimitError
from bisheng.knowledge.api import dependencies
from bisheng.knowledge.domain.services import knowledge_space_service as module
from bisheng.permission.application import access
from test.knowledge_unification import test_kn_upload as fixtures

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business
admission = fixtures.admission
processing = fixtures.processing
application = fixtures.application
files = fixtures.files
legacy = fixtures.legacy
upload = fixtures.upload


async def test_actual_di_supplies_fresh_upload_app_without_borrowing_request_session(monkeypatch):
    monkeypatch.setattr(access, "get_f048_runtime", AsyncMock(return_value=object()))
    engine = create_async_engine("sqlite+aiosqlite://")
    try:
        async with AsyncSession(engine) as session:
            versions = await dependencies.get_knowledge_document_version_repository(session)
            documents = await dependencies.get_knowledge_document_repository(session)
            files = await dependencies.get_knowledge_file_repository(session)
            user = UserPayload(user_id=7, tenant_id=101, user_role=[])
            service = await dependencies.get_knowledge_space_service(
                Request({"type": "http", "headers": []}), session, user, versions, documents, files
            )
            first, second = service.upload_application_factory(), service.upload_application_factory()
            assert first is not second and first.repository is not second.repository
            assert first.user is user and first.sessions is dependencies.get_async_db_session
            assert first.admit == service._require_action
            assert first.make_record == service._new_file_permission_record
            assert first.actor_provider == service._permission_actor
            assert service.version_repo is versions and service.doc_repo is documents
            assert service.knowledge_file_repo is files
            assert not session.in_transaction()
    finally:
        await engine.dispose()


async def test_actual_size_over_role_limit_rejected_before_chain_and_permanent_blob(upload, monkeypatch):
    monkeypatch.setattr(module.QuotaService, "get_knowledge_space_upload_limit_bytes", AsyncMock(return_value=1))
    upload.legacy.storage.reset_mock()
    with pytest.raises(SpaceFileSizeLimitError):
        await upload.service.add_file(40, ["opaque-document"])
    upload.legacy.storage.put_object_sync.assert_not_called()
    upload.publish.assert_not_called()
