"""F112: the actual authenticated v2 endpoints and the old optional form contract."""

from functools import partial
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


async def test_limits_advertise_versioned_release_notes(api_app, service_account_principal):
    async with api_app(principal=service_account_principal()) as client:
        response = await client.get("/api/v2/apps/deploy-limits")
    assert response.status_code == 200
    assert response.json()["data"]["features"]["release_notes"] == {"version": 1, "max_codepoints": 2000}


@pytest.mark.parametrize("notes", [None, "New feature\nFixed issue"])
async def test_form_passes_optional_text_without_changing_response(
    notes,
    api_app,
    service_account_principal,
    monkeypatch,
):
    from bisheng.app_publish.domain.services.publish_pipeline_service import PublishPipelineService

    accept = AsyncMock(return_value=SimpleNamespace(deployment_id="d", app_id="a", version_id="v"))
    monkeypatch.setattr(PublishPipelineService, "accept", accept)
    async with api_app(principal=service_account_principal()) as client:
        response = await client.post(
            "/api/v2/apps/deploy",
            files={"package": ("app.tar.gz", b"package")},
            data={"release_notes": notes} if notes is not None else {},
        )
    assert response.json()["data"] == {"deployment_id": "d", "app_id": "a", "version_id": "v"}
    assert accept.await_args.kwargs["release_notes"] == notes


async def test_direct_http_rejects_too_long_and_preserves_scope_guard(api_app, service_account_principal):
    principal = service_account_principal()
    async with api_app(principal=principal) as client:
        response = await client.post(
            "/api/v2/apps/deploy", files={"package": ("app.tar.gz", b"not a tar")}, data={"release_notes": "x" * 2001}
        )
    assert response.status_code == 400
    assert response.json()["status_code"] == 16233
    async with api_app(principal=service_account_principal(scopes=[])) as client:
        denied = await client.get("/api/v2/apps/deploy-limits")
    assert denied.status_code == 403
    assert denied.json()["status_code"] == 26003


async def test_api_worker_approval_and_version_roundtrip(
    publish_db,
    tier_seed,
    tarball_factory,
    fake_minio,
    app_factory,
    service_account_principal,
    fake_f054_services,
    fake_orchestrator,
    approval_env,
    approval_notifications,
    audit_sink,
    super_admin_user,
    owner_user,
    api_app,
    monkeypatch,
):
    """AC-08, AC-09, AC-12, AC-13: isolated API journey; external storage/runtime are doubles."""
    from bisheng.app_publish.domain.models.app_deployment import AppDeploymentDao
    from bisheng.app_publish.domain.services import publish_pipeline_service as pipeline
    from bisheng.app_runtime.api.endpoints.apps import router as app_router
    from bisheng.app_runtime.domain.services import app_query_service
    from bisheng.approval.api.endpoints.approval_user import router as approval_router
    from test.e2e.helpers.api import assert_resp_200

    app, _ = await app_factory(slug="e2e-f112-api", name="e2e-f112-api")
    monkeypatch.setattr(pipeline, "enqueue_pipeline", AsyncMock())
    monkeypatch.setattr(app_query_service, "get_async_db_session", publish_db)
    package = tarball_factory()
    original = "  新增功能\r\n  Fix <script>plain text</script>\r\n" + "LongLine" * 120 + "  "
    expected = "新增功能\n  Fix <script>plain text</script>\n" + "LongLine" * 120
    async with api_app(principal=service_account_principal(), payload=owner_user.payload) as client:
        client._transport.app.include_router(app_router, prefix="/api/v1")
        client._transport.app.include_router(approval_router, prefix="/api/v1")
        with package.open("rb") as stream:
            accepted = assert_resp_200(
                await client.post(
                    "/api/v2/apps/deploy",
                    files={"package": ("app.tar.gz", stream)},
                    data={"app_id": app.id, "release_notes": original},
                )
            )
        await pipeline.PublishPipelineService.run_pipeline(accepted["deployment_id"])
        async with publish_db() as session:
            attempt = await AppDeploymentDao.aget(session, accepted["deployment_id"])
        assert attempt.failure is None
        assert attempt.approval_instance_id is not None
        approval = assert_resp_200(await client.get(f"/api/v1/approval/instances/{attempt.approval_instance_id}"))
        assert approval["detail_snapshot"]["release_notes"] == expected
        versions = assert_resp_200(await client.get(f"/api/v1/apps/{app.id}/versions"))
        assert versions["data"][0]["version_id"] == accepted["version_id"]
        assert versions["data"][0]["release_notes"] == expected
        assert versions["data"][1]["release_notes"] is None

        from bisheng.common.dependencies.user_deps import UserPayload
        from test.e2e.helpers.api import assert_resp_error

        monkeypatch.setattr(app_query_service, "check_tenant_admin", AsyncMock(return_value=False))
        for foreign in (False, True):
            denied_actor = UserPayload(
                user_id=owner_user.user_id + 17,
                user_name="e2e-f112-denied",
                user_role=[],
                tenant_id=2 if foreign else 1,
            )
            client._transport.app.dependency_overrides[UserPayload.get_login_user] = partial(
                lambda actor: actor, denied_actor
            )
            assert_resp_error(await client.get(f"/api/v1/apps/{app.id}/versions"), 16101 if foreign else 16106)
            assert_resp_error(await client.get(f"/api/v1/approval/instances/{attempt.approval_instance_id}"), 18101)
        client._transport.app.dependency_overrides[UserPayload.get_login_user] = lambda: super_admin_user.payload
        task_id = approval["tasks"][0]["task_id"]
        reviewed = assert_resp_200(await client.get(f"/api/v1/approval/my-tasks/{task_id}"))
        assert reviewed["detail_snapshot"]["release_notes"] == expected
        assert_resp_200(
            await client.post(
                f"/api/v1/approval/tasks/{task_id}/decision",
                json={"action": "reject", "comment": "e2e-f112 verification"},
            )
        )
        versions = assert_resp_200(await client.get(f"/api/v1/apps/{app.id}/versions"))
        assert versions["data"][0]["terminal_state"] == "rejected"
        assert versions["data"][0]["release_notes"] == expected
        final_approval = assert_resp_200(await client.get(f"/api/v1/approval/instances/{attempt.approval_instance_id}"))
        assert final_approval["detail_snapshot"]["release_notes"] == expected

        import json
        import os
        from pathlib import Path

        if destination := os.environ.get("F112_PREVIEW_DATA"):
            Path(destination).write_text(
                json.dumps({"approval": final_approval, "versions": versions}, ensure_ascii=False), encoding="utf-8"
            )


async def test_platform_serves_the_actual_release_notes_cli_wheel(api_app):
    """AC-20: the real anonymous download endpoint serves the committed post-release."""
    import hashlib
    import io
    import json
    import zipfile

    from bisheng.dev_toolkit.api.router import router as distribution_router
    from bisheng.dev_toolkit.domain.services.artifact_service import ARTIFACTS_DIR
    from test.e2e.helpers.api import assert_resp_200

    async with api_app() as client:
        client._transport.app.include_router(distribution_router, prefix="/api/v1")
        versions = assert_resp_200(await client.get("/api/v1/dev-toolkit/versions"))
        manifest = json.loads((ARTIFACTS_DIR / "manifest.json").read_text())
        assert all(
            versions["cli"][key] == manifest["cli"][key] for key in ("version", "min_compatible", "filename", "sha256")
        )
        assert versions["platform"]["version"] == manifest["platform"]["version"]
        response = await client.get(versions["cli"]["download_path"])
        assert response.status_code == 200
        assert hashlib.sha256(response.content).hexdigest() == versions["cli"]["sha256"]
        assert versions["cli"]["filename"] in response.headers["content-disposition"]
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            assert b"--release-notes-file" in archive.read("bisheng_cli/cli.py")
