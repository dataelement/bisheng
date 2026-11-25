"""Old multipart staging routes must not write native state for external targets."""

from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.knowledge.api.endpoints import knowledge, upload_preview
from bisheng.knowledge.application import provider_v1_runtime as runtime
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderBinding as Binding
from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderGeneration as Generation
from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderInstance as Instance
from bisheng.knowledge.domain.repositories.provider_retrieval_repository import ProviderRetrievalRepository
from bisheng.role.domain.services.quota_service import QuotaService


@pytest.fixture
async def routes(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://")
    try:
        async with engine.begin() as conn:
            for cls in (Instance, Generation, Binding):
                await conn.run_sync(cls.__table__.create)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions.begin() as db:
            db.add(
                Instance(
                    id=1,
                    tenant_id=3,
                    provider_key="weknora",
                    state="ready",
                    capability_revision=2,
                    endpoint="test",
                    credential_ref="ref",
                    remote_scope_id="scope",
                )
            )
            db.add(
                Generation(
                    tenant_id=3,
                    space_id=14,
                    generation=1,
                    provider_instance_id=1,
                    remote_scope_id="scope",
                    remote_kb_id="kb",
                    state="ready",
                )
            )
            db.add_all(
                [
                    Binding(tenant_id=3, space_id=14, provider_key="weknora", active_generation=1, state="ready"),
                    Binding(tenant_id=3, space_id=15, provider_key="weknora", state="provisioning"),
                ]
            )

        async def load(kid):
            return NS(
                id=kid, tenant_id=3, type=(KnowledgeTypeEnum.NORMAL if kid == 13 else KnowledgeTypeEnum.SPACE).value
            )

        monkeypatch.setattr(runtime.KnowledgeDao, "aquery_by_id", load)
        monkeypatch.setattr(runtime, "get_current_tenant_id", lambda: 3)
        from bisheng.core.context.tenant import tenant_execution_scope

        monkeypatch.setattr(runtime, "ProviderRetrievalRepository", lambda: ProviderRetrievalRepository(sessions))
        monkeypatch.setattr(QuotaService, "check_quota", AsyncMock())
        monkeypatch.setattr("bisheng.knowledge.domain.upload_file_size.get_upload_size_limits_mb", lambda: (10, 10))
        monkeypatch.setattr(
            knowledge.KnowledgeService, "save_upload_file_original_name", AsyncMock(return_value="native.txt")
        )
        save = AsyncMock(return_value="tmp/native.txt")
        monkeypatch.setattr(knowledge, "save_uploaded_file", save)
        monkeypatch.setattr(knowledge.KnowledgeFileDao, "get_repeat_file", AsyncMock(return_value=None))
        app = FastAPI()
        app.include_router(knowledge.router, prefix="/api/v1")
        app.include_router(upload_preview.router, prefix="/api/v1/knowledge/space")
        user = NS(tenant_id=3, user_id=11)
        app.dependency_overrides[UserPayload.get_login_user] = lambda: user
        app.dependency_overrides[upload_preview.get_knowledge_space_service] = lambda: NS(login_user=user)
        with tenant_execution_scope(3):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
                yield client, save
    finally:
        await engine.dispose()


@pytest.mark.parametrize("kid", [13, 14, 15, 16])
async def test_legacy_stage_checks_real_binding_before_saving_and_keeps_normal_and_native(routes, kid):
    client, save = routes

    async def send():
        return await client.post(f"/api/v1/knowledge/upload/{kid}", files={"file": ("test.txt", b"abc")})

    if kid in (14, 15):
        with pytest.raises(runtime.ProviderFeatureUnavailable):
            await send()
        save.assert_not_awaited()
        knowledge.KnowledgeService.save_upload_file_original_name.assert_not_awaited()
        knowledge.KnowledgeFileDao.get_repeat_file.assert_not_awaited()
    else:
        assert (await send()).json()["data"]["file_path"] == "tmp/native.txt"
        save.assert_awaited_once()
        assert knowledge.KnowledgeFileDao.get_repeat_file.await_args.kwargs["knowledge_id"] == kid


@pytest.mark.parametrize("kid", [14, 15])
async def test_external_and_unknown_reject_all_native_preview_routes(routes, monkeypatch, kid):
    client, _ = routes
    factory = Mock(side_effect=AssertionError("must not stage, read, parse or edit native previews"))
    monkeypatch.setattr(upload_preview, "UploadPreviewService", factory)
    base = f"/api/v1/knowledge/space/{kid}/uploads"
    item = f"{base}/{'a' * 32}"
    preview = f"{item}/previews/{'b' * 32}"
    for method, url, kwargs in [
        ("POST", base, {"files": {"file": ("test.txt", b"abc")}}),
        ("GET", item, {}),
        ("POST", item + "/previews", {"json": {"overrides": {}}}),
        ("GET", preview, {}),
        ("PUT", preview + "/chunks/0", {"json": {"expected_revision": 0, "text": "test"}}),
        ("DELETE", preview + "/chunks/0", {"params": {"expected_revision": 0}}),
    ]:
        with pytest.raises(runtime.ProviderFeatureUnavailable):
            await client.request(method, url, **kwargs)
    factory.assert_not_called()


async def test_native_space_still_uses_owned_stage(routes, monkeypatch):
    client, _ = routes
    stage = AsyncMock(return_value={"file_path": "native/path"})
    monkeypatch.setattr(upload_preview, "UploadPreviewService", lambda svc: NS(stage=stage))
    result = await client.post(
        "/api/v1/knowledge/space/16/uploads", params={"parent_id": 3}, files={"file": ("test.txt", b"abc")}
    )
    assert result.json()["data"]["file_path"] == "native/path" and stage.await_args.args[:2] == (16, 3)
