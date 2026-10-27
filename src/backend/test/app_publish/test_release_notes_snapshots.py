"""F112: real DB reloads feed immutable version and approval snapshots."""

from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("notes", [None, "新增功能\n  Fixed <script>alert(1)</script>"])
@pytest.mark.parametrize("terminal", ["rejected", "withdrawn", "online"])
async def test_deployment_snapshot_drives_approval_and_version_after_reload(
    notes,
    terminal,
    publish_db,
    app_factory,
    deployment_factory,
    tier_seed,
    owner_user,
    audit_sink,
    monkeypatch,
):
    from bisheng.app_publish.domain.models.app_deployment import AppDeploymentDao
    from bisheng.app_publish.domain.services import publish_approval_service
    from bisheng.app_publish.domain.services.app_publish_scenario_handler import AppPublishScenarioHandler
    from bisheng.app_publish.domain.services.version_service import VersionService
    from bisheng.app_runtime.domain.services import app_query_service
    from bisheng.database.models.app_version import AppVersionDao

    from .test_version_service import _FakeApproval

    app, _ = await app_factory(with_version=False)
    attempt = await deployment_factory(
        app_id=app.id,
        version_id="v-notes",
        tier_code="light",
        manifest={"name": app.name, "runtime": "python3.11", "tier": "light", "port": 8080},
    )
    async with publish_db() as session:
        saved = await AppDeploymentDao.aget(session, attempt.id)
        saved.release_notes = notes
        session.add(saved)
        await session.commit()
    async with publish_db() as worker_session:
        reloaded = await AppDeploymentDao.aget(worker_session, attempt.id)
    payload = await publish_approval_service._build_payload(
        reloaded,
        app=app,
        owner_user_id=owner_user.user_id,
        owner_user_name=owner_user.user_name,
        version_no=1,
        release_kind="initial",
        has_department=True,
    )
    assert payload["release_notes"] == notes
    detail = await AppPublishScenarioHandler().build_detail(
        SimpleNamespace(payload_snapshot=payload, business_name=app.name, business_resource_id=app.id)
    )
    assert detail["release_notes"] == notes
    version = await VersionService.record_version(reloaded, approval=_FakeApproval())
    assert version.release_notes == notes

    monkeypatch.setattr(app_query_service, "get_async_db_session", publish_db)
    rows = await app_query_service.AppQueryService.list_versions_page(app.id, actor=owner_user.payload, page_size=1)
    assert rows["total"] == 1
    assert rows["data"][0]["release_notes"] == notes
    await VersionService.mark_terminal_state(app.id, version.id, terminal)
    async with publish_db() as session:
        stored = await AppVersionDao.aget(session, app.id, version.id)
        assert stored.terminal_state == terminal
        assert stored.release_notes == notes
    assert payload["release_notes"] == detail["release_notes"] == notes


async def test_later_version_does_not_overwrite_earlier_notes(publish_db, app_factory, deployment_factory):
    from bisheng.app_publish.domain.services.version_service import VersionService
    from bisheng.database.models.app_version import AppVersionDao

    app, _ = await app_factory(with_version=False)
    for idx, notes in enumerate(["First", "Second"], start=1):
        attempt = await deployment_factory(app_id=app.id, version_id=f"v-{idx}", tier_code="light")
        attempt.release_notes = notes
        await VersionService._insert_version(attempt)
    async with publish_db() as session:
        rows = await AppVersionDao.alist_by_app(session, app.id)
    assert [(row.version_no, row.release_notes) for row in rows] == [(2, "Second"), (1, "First")]


@pytest.mark.parametrize(("foreign", "expected_code"), [(False, 16106), (True, 16101)])
async def test_notes_do_not_bypass_version_read_permissions(
    foreign,
    expected_code,
    publish_db,
    app_factory,
    owner_user,
    monkeypatch,
):
    from unittest.mock import AsyncMock

    from bisheng.app_runtime.domain.services import app_query_service
    from bisheng.common.errcode.base import BaseErrorCode

    app, _ = await app_factory()
    monkeypatch.setattr(app_query_service, "get_async_db_session", publish_db)
    monkeypatch.setattr(app_query_service, "check_tenant_admin", AsyncMock(return_value=False))
    actor = SimpleNamespace(
        user_id=owner_user.user_id if foreign else owner_user.user_id + 17,
        tenant_id=2 if foreign else 1,
        is_global_super=False,
    )
    with pytest.raises(BaseErrorCode) as caught:
        await app_query_service.AppQueryService.list_versions_page(app.id, actor=actor)
    assert caught.value.code == expected_code
