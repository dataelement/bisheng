"""F113 uses a natural-person adapter without changing the CLI credential contract."""

import io
import tarfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.dsh.domain.services.access import DshPrincipal

pytestmark = pytest.mark.asyncio


def app_service():
    actor = SimpleNamespace(user_id=31, tenant_id=2, user_name="editor")
    app = SimpleNamespace(owner_user_id=10, current_version_id="v1")
    return SimpleNamespace(require=AsyncMock(return_value=(actor, app)), actor=AsyncMock(return_value=actor))


async def test_ac01_desktop_submit_records_person_without_issuing_key(monkeypatch, tmp_path):
    from bisheng.app_publish.domain.services import desktop_publish_service as module

    accepted = AsyncMock(return_value=SimpleNamespace(app_id="app", version_id="v2", deployment_id="deploy"))
    monkeypatch.setattr(module.PublishPipelineService, "accept", accepted)
    service = app_service()
    principal = DshPrincipal(tenant_id="2", user_id="31", session_id="device")
    result = await module.DesktopPublishService(service).accept(
        principal, tmp_path / "package.tgz", app_id="app", base_version_id="v1"
    )
    assert result.deployment_id == "deploy"
    identity = accepted.await_args.kwargs["principal"]
    assert identity.actor_kind == "natural_person"
    assert identity.effective_user_id == 31
    assert identity.resource_owner_user_id == 10
    assert identity.credential_id is None and identity.source == "desktop"
    service.require.assert_awaited_once_with(principal, "app", "edit", "publish")
    assert accepted.await_args.kwargs["check_base_version"] is True


async def test_ac05_stale_source_never_enters_publish_pipeline(monkeypatch, tmp_path):
    from bisheng.app_publish.domain.services import desktop_publish_service as module
    from bisheng.common.errcode.app_factory import AppStateConflictError

    accepted = AsyncMock()
    monkeypatch.setattr(module.PublishPipelineService, "accept", accepted)
    with pytest.raises(AppStateConflictError):
        await module.DesktopPublishService(app_service()).accept(
            DshPrincipal(tenant_id="2", user_id="31", session_id="device"),
            tmp_path / "package.tgz",
            app_id="app",
            base_version_id="older",
        )
    accepted.assert_not_called()


def tar_bytes(files):
    result = io.BytesIO()
    with tarfile.open(fileobj=result, mode="w:gz") as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return result.getvalue()


async def test_ac04_source_export_strips_runtime_files_and_preserves_original_code(app_runtime_settings):
    from bisheng.app_publish.domain.services.source_export import export_archive

    app_runtime_settings()
    data = export_archive(
        tar_bytes(
            {
                "bisheng-app.yaml": b"name: Demo",
                "main.py": b"print('editable')",
                ".env": b"private",
                "app.db-wal": b"records",
                ".bisheng/session.json": b"local",
            }
        )
    )
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        assert archive.getnames() == ["bisheng-app.yaml", "main.py"]
        assert archive.extractfile("main.py").read() == b"print('editable')"


async def test_ac04_source_export_rejects_escape_paths(app_runtime_settings):
    from bisheng.app_publish.domain.services.source_export import export_archive
    from bisheng.common.errcode.app_publish import AppPackageInvalidError

    app_runtime_settings()
    with pytest.raises(AppPackageInvalidError):
        export_archive(tar_bytes({"../escape.py": b"escape"}))


async def test_ac01_unauthenticated_upload_is_denied_before_body_read(monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from bisheng.common.errcode.dsh import DshInvalidAccessTokenError
    from bisheng.dsh.api import dependencies
    from bisheng.dsh.api.endpoints import apps

    runtime = SimpleNamespace(access=SimpleNamespace(authenticate=AsyncMock(side_effect=DshInvalidAccessTokenError())))
    monkeypatch.setattr(apps, "get_runtime", AsyncMock(return_value=runtime))
    monkeypatch.setattr(dependencies, "get_settings", lambda: SimpleNamespace(enabled=True))
    app = FastAPI()
    app.include_router(apps.router, prefix="/api/v1")
    body_read = False

    async def body():
        nonlocal body_read
        body_read = True
        yield b"this body must never be parsed"

    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/dsh/apps/deploy", content=body(), headers={"Content-Type": "multipart/form-data; boundary=invalid"}
        )
    assert response.status_code == 401
    assert not body_read


async def test_ac04_source_endpoint_requires_edit_before_reading_archive(monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from bisheng.common.errcode.app_factory import AppManageForbiddenError
    from bisheng.dsh.api.endpoints import apps

    app = FastAPI()
    app.include_router(apps.router, prefix="/api/v1")
    principal = DshPrincipal(tenant_id="2", user_id="31", session_id="device")
    service = SimpleNamespace(require=AsyncMock(side_effect=AppManageForbiddenError()))
    app.dependency_overrides[apps.desktop_principal] = lambda: principal
    app.dependency_overrides[apps.app_service] = lambda: service
    exported = AsyncMock(return_value=(b"archive", "digest"))
    monkeypatch.setattr(apps, "source_export", exported)
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        denied = await client.get("/api/v1/dsh/apps/app/versions/version/source")
        assert denied.status_code == 400
        exported.assert_not_called()
        service.require.side_effect = None
        allowed = await client.get("/api/v1/dsh/apps/app/versions/version/source")
        assert allowed.status_code == 200 and allowed.content == b"archive"
        assert allowed.headers["x-base-version-id"] == "version"
        assert allowed.headers["cache-control"] == "no-store"
        service.require.assert_awaited_with(principal, "app", "edit")


async def test_ac03_app_cookie_rechecks_parent_session_and_app_binding(monkeypatch):
    from bisheng.app_runtime.domain.services import desktop_entry_service as module
    from bisheng.common.errcode.dsh import DshSessionRevokedError

    principal = DshPrincipal(tenant_id="2", user_id="31", session_id="device")
    sessions = SimpleNamespace(resolve=AsyncMock(return_value={"principal": principal.model_dump(), "app_id": "first"}))
    actor = AsyncMock(side_effect=DshSessionRevokedError())
    monkeypatch.setattr(module, "desktop_app_sessions", AsyncMock(return_value=sessions))
    monkeypatch.setattr(module, "DesktopAppsService", lambda *args: SimpleNamespace(actor=actor))
    entry = AsyncMock(return_value={"decision": "allow", "app_id": "different"})
    monkeypatch.setattr(module, "authorize_entry", entry)
    verdict = await module.authorize_desktop_entry(slug="reused-slug", access_token="bs-view-test", runtime=object())
    assert verdict["decision"] == "login"
    entry.assert_not_called()
    actor.side_effect = None
    actor.return_value = SimpleNamespace(user_id=31, tenant_id=2)
    verdict = await module.authorize_desktop_entry(slug="reused-slug", access_token="bs-view-test", runtime=object())
    assert verdict == {"decision": "forbidden", "reason": "application_identity_changed"}
