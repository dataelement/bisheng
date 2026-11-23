"""AC-43/44: a folder uploader may read rules without editing the space.

Actual route/service/repository and SQL rows; only the permission transport is
isolated by the existing native upload fixture. Reading rules never saves them.
"""

import httpx
import pytest
import sqlalchemy as sa
from fastapi import FastAPI

from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.knowledge.api.endpoints import upload_settings as endpoint
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile
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


@pytest.mark.parametrize("folder", [False, True])
async def test_actual_upload_rules_read_same_saved_defaults_under_exact_upload_action(upload, monkeypatch, folder):
    monkeypatch.setattr(endpoint, "get_async_db_session", upload.context.sessions)
    async with upload.context.sessions() as session:
        before = dict(
            (await session.execute(sa.select(Knowledge.__table__).where(Knowledge.id == 40))).mappings().one()
        )
        if folder:
            session.add(
                KnowledgeFile(id=950, tenant_id=101, knowledge_id=40, file_name="folder", file_type=FileType.DIR)
            )
            await session.commit()
    app = FastAPI()
    app.include_router(endpoint.router, prefix="/api/v1/knowledge/space")
    app.dependency_overrides[endpoint.get_knowledge_space_service] = lambda: upload.service
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
        response = await client.get(
            "/api/v1/knowledge/space/40/files/upload-settings", params={"parent_id": 950} if folder else {}
        )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["effective_defaults"] == before["processing_defaults"]
    assert data["config_version"] == before["processing_config_version"]
    upload.service._require_action.assert_awaited_once_with(
        "folder" if folder else "knowledge_space", 950 if folder else 40, "upload_file"
    )
    async with upload.context.sessions() as session:
        after = dict((await session.execute(sa.select(Knowledge.__table__).where(Knowledge.id == 40))).mappings().one())
        assert after == before


async def test_upload_rule_denial_does_not_open_settings_transaction(upload, monkeypatch):
    upload.service._require_action.side_effect = PermissionDeniedError()
    monkeypatch.setattr(endpoint, "get_async_db_session", lambda: pytest.fail("denied uploader must not read settings"))
    with pytest.raises(PermissionDeniedError):
        await endpoint.get_upload_settings(40, 950, upload.service)


async def test_folder_from_another_space_cannot_read_this_spaces_rules(upload, monkeypatch):
    from bisheng.common.errcode.knowledge_space import SpaceFolderNotFoundError

    async with upload.context.sessions() as session:
        session.add(
            KnowledgeFile(id=950, tenant_id=101, knowledge_id=999, file_name="foreign-folder", file_type=FileType.DIR)
        )
        await session.commit()
    monkeypatch.setattr(endpoint, "get_async_db_session", lambda: pytest.fail("wrong container must not read rules"))
    with pytest.raises(SpaceFolderNotFoundError):
        await endpoint.get_upload_settings(40, 950, upload.service)
