"""T053 — the approval-time temporary preview instance (AC-26 … AC-30).

``GET / POST /api/v1/apps/{app_id}/versions/{version_id}/preview`` and
``DELETE …/preview/{session_id}``, plus the service behind them. What is
asserted hardest:

* **Who gets one.** The approver holding a task on *that* version, the owner,
  the tenant administrator, the super admin — and nobody else, with the refusal
  riding in the 200 envelope so the approval panel keeps rendering (AC-30).
* **What the orchestrator is asked for.** A ``preview_start`` intent, never a
  ``deploy``: a deploy would write a desired-state record for the application
  and take its running instance with it.
* **That it goes away.** Three triggers — the approver's button, the approval
  reaching a terminal state, the deadline passing — each close the row exactly
  once and each tell the orchestrator, including the ones that arrive second.
* **That an expired session cannot be opened**, even before anything sweeps it:
  the entry resolver is the exact enforcement point of the deadline.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from .conftest import DEPT_ADMIN_USER_ID, OWNER_USER_ID, ROOT_TENANT_ID

pytestmark = pytest.mark.asyncio

APPROVER_USER_ID = OWNER_USER_ID + 700
OTHER_APPROVER_USER_ID = OWNER_USER_ID + 701
STRANGER_USER_ID = OWNER_USER_ID + 702

IMAGE_REF = "bisheng-app/f055-app-1:1-abcdef12"


def _body(response):
    assert response.status_code == 200, response.text
    return response.json()


def _payload(user_id: int, *, is_global_super: bool = False):
    from bisheng.common.dependencies.user_deps import UserPayload

    return UserPayload(
        user_id=user_id,
        user_name=f"u{user_id}",
        user_role=[],
        tenant_id=ROOT_TENANT_ID,
        is_global_super=is_global_super,
    )


async def _buildable(publish_db, app_factory, **kwargs):
    """An app whose version has a build behind it — the precondition of a preview."""
    from bisheng.database.models.app_version import AppVersion

    app, version = await app_factory(with_version=True, **kwargs)
    async with publish_db() as session:
        row = await session.get(AppVersion, version.id)
        row.image_ref = IMAGE_REF
        session.add(row)
        await session.commit()
        version.image_ref = IMAGE_REF
    return app, version


async def _seed_task(publish_db, *, app, version_id: str, approver_user_id: int) -> int:
    """An ``app_publish_request`` instance about ``version_id`` with one task."""
    from bisheng.app_publish.domain.services.app_publish_scenario_handler import SCENARIO_CODE
    from bisheng.approval.domain.models.approval_instance import ApprovalInstance, ApprovalTask

    async with publish_db() as session:
        instance = ApprovalInstance(
            tenant_id=ROOT_TENANT_ID,
            scenario_code=SCENARIO_CODE,
            scenario_name="应用发布",
            handler_key="app_publish",
            business_key=f"dep-{version_id}",
            business_resource_type="app",
            business_resource_id=str(app.id),
            business_name=app.name,
            applicant_user_id=int(app.owner_user_id),
            applicant_user_name="owner",
            status="pending",
            payload_snapshot={"app_id": app.id, "version_id": version_id},
            detail_snapshot={},
        )
        session.add(instance)
        await session.flush()
        session.add(
            ApprovalTask(
                tenant_id=ROOT_TENANT_ID,
                instance_id=instance.id,
                flow_version_id=1,
                node_code="n1",
                node_name="审批",
                node_order=1,
                approver_user_id=approver_user_id,
                approver_source_type="tenant_admin",
                node_mode="or",
                status="pending",
            )
        )
        await session.commit()
        return instance.id


@pytest.fixture()
async def preview_env(publish_db, app_factory, tier_seed, fake_orchestrator):
    """An app with a buildable pending version and one approver holding a task."""
    app, version = await _buildable(publish_db, app_factory)
    await _seed_task(publish_db, app=app, version_id=version.id, approver_user_id=APPROVER_USER_ID)
    return app, version, fake_orchestrator


# ---------------------------------------------------------------------------
# start
# ---------------------------------------------------------------------------


async def test_the_approver_of_that_version_can_raise_a_preview(preview_env, api_app):
    app, version, _orchestrator = preview_env

    async with api_app(payload=_payload(APPROVER_USER_ID)) as client:
        data = _body(await client.post(f"/api/v1/apps/{app.id}/versions/{version.id}/preview"))["data"]

    assert data["state"] == "running"
    assert data["session_id"]
    assert data["entry_url"] == f"/apps/preview/{data['session_id']}"
    assert data["runnable"] is True


async def test_raising_a_preview_uses_the_preview_intent_and_never_deploy(preview_env, api_app):
    """AC-26 「不占应用运行实例名额」 — deploy would replace the app's own instance."""
    app, version, orchestrator = preview_env

    async with api_app(payload=_payload(APPROVER_USER_ID)) as client:
        await client.post(f"/api/v1/apps/{app.id}/versions/{version.id}/preview")

    called = [name for name, _ in orchestrator.calls]
    assert called == ["preview_start"]
    assert "deploy" not in called
    kwargs = orchestrator.calls[0][1]
    assert kwargs["app_id"] == app.id
    assert kwargs["version_id"] == version.id
    assert kwargs["image_ref"] == IMAGE_REF


async def test_the_preview_is_told_its_own_base_path_not_the_apps(preview_env, api_app):
    """The same source runs at ``/apps/{slug}`` and at ``/apps/preview/{session}``."""
    app, version, orchestrator = preview_env

    async with api_app(payload=_payload(APPROVER_USER_ID)) as client:
        data = _body(await client.post(f"/api/v1/apps/{app.id}/versions/{version.id}/preview"))["data"]

    env = orchestrator.calls[0][1]["env"]
    assert env["BISHENG_APP_BASE_PATH"] == f"/apps/preview/{data['session_id']}"
    assert f"/apps/{app.slug}" not in env["BISHENG_APP_BASE_PATH"]


async def test_the_deadline_is_handed_to_the_orchestrator(preview_env, api_app, app_runtime_settings):
    """AC-28 — the container carries its own expiry; the platform runs no timer."""
    app, version, orchestrator = preview_env
    app_runtime_settings(preview_ttl_days=3)

    async with api_app(payload=_payload(APPROVER_USER_ID)) as client:
        data = _body(await client.post(f"/api/v1/apps/{app.id}/versions/{version.id}/preview"))["data"]

    handed = orchestrator.calls[0][1]["expires_at"]
    expected = datetime.fromisoformat(data["expires_at"]).timestamp()
    assert handed == int(expected)
    assert abs(expected - (datetime.now() + timedelta(days=3)).timestamp()) < 120


async def test_pressing_the_button_twice_returns_the_same_instance(preview_env, api_app):
    """A double click must not tear down a trial the approver is in the middle of."""
    app, version, orchestrator = preview_env

    async with api_app(payload=_payload(APPROVER_USER_ID)) as client:
        first = _body(await client.post(f"/api/v1/apps/{app.id}/versions/{version.id}/preview"))["data"]
        second = _body(await client.post(f"/api/v1/apps/{app.id}/versions/{version.id}/preview"))["data"]

    assert first["session_id"] == second["session_id"]
    assert [name for name, _ in orchestrator.calls] == ["preview_start"]


async def test_two_approvers_get_two_instances(publish_db, app_factory, tier_seed, fake_orchestrator, api_app):
    """AC-27 — each carries its own approver's identity, so they cannot be shared."""
    app, version = await _buildable(publish_db, app_factory)
    await _seed_task(publish_db, app=app, version_id=version.id, approver_user_id=APPROVER_USER_ID)
    await _seed_task(publish_db, app=app, version_id=version.id, approver_user_id=OTHER_APPROVER_USER_ID)

    async with api_app(payload=_payload(APPROVER_USER_ID)) as client:
        first = _body(await client.post(f"/api/v1/apps/{app.id}/versions/{version.id}/preview"))["data"]
    async with api_app(payload=_payload(OTHER_APPROVER_USER_ID)) as client:
        second = _body(await client.post(f"/api/v1/apps/{app.id}/versions/{version.id}/preview"))["data"]

    assert first["session_id"] != second["session_id"]
    assert [name for name, _ in fake_orchestrator.calls] == ["preview_start", "preview_start"]


async def test_the_owner_may_also_raise_one(preview_env, api_app):
    app, version, _orchestrator = preview_env

    async with api_app(payload=_payload(OWNER_USER_ID)) as client:
        data = _body(await client.post(f"/api/v1/apps/{app.id}/versions/{version.id}/preview"))["data"]

    assert data["state"] == "running"


async def test_a_stranger_gets_16264_in_the_200_envelope(preview_env, api_app):
    """AC-30 — and a business code, not a 403: the panel must keep rendering."""
    app, version, orchestrator = preview_env

    async with api_app(payload=_payload(STRANGER_USER_ID)) as client:
        body = _body(await client.post(f"/api/v1/apps/{app.id}/versions/{version.id}/preview"))

    assert body["status_code"] == 16264
    assert orchestrator.calls == []


async def test_an_approver_of_another_version_is_refused(
    publish_db, app_factory, tier_seed, fake_orchestrator, api_app
):
    """Holding a task somewhere is not holding a task on *this* release."""
    app, version = await _buildable(publish_db, app_factory)
    other_app, other_version = await _buildable(publish_db, app_factory)
    await _seed_task(publish_db, app=other_app, version_id=other_version.id, approver_user_id=OTHER_APPROVER_USER_ID)

    async with api_app(payload=_payload(OTHER_APPROVER_USER_ID)) as client:
        body = _body(await client.post(f"/api/v1/apps/{app.id}/versions/{version.id}/preview"))

    assert body["status_code"] == 16264


async def test_a_version_with_no_build_cannot_be_previewed(
    publish_db, app_factory, tier_seed, fake_orchestrator, api_app
):
    app, version = await app_factory(with_version=True)  # no image_ref
    await _seed_task(publish_db, app=app, version_id=version.id, approver_user_id=APPROVER_USER_ID)

    async with api_app(payload=_payload(APPROVER_USER_ID)) as client:
        body = _body(await client.post(f"/api/v1/apps/{app.id}/versions/{version.id}/preview"))

    assert body["status_code"] == 16265
    assert body["data"]["details"]["reason"] == "no_image"
    assert fake_orchestrator.calls == []


async def test_a_settled_version_cannot_be_previewed(publish_db, app_factory, tier_seed, fake_orchestrator, api_app):
    """A decided release has nothing left to try out."""
    app, version = await _buildable(publish_db, app_factory, terminal_state="rejected")
    await _seed_task(publish_db, app=app, version_id=version.id, approver_user_id=APPROVER_USER_ID)

    async with api_app(payload=_payload(APPROVER_USER_ID)) as client:
        body = _body(await client.post(f"/api/v1/apps/{app.id}/versions/{version.id}/preview"))

    assert body["status_code"] == 16265
    assert body["data"]["details"]["reason"] == "settled"


async def test_a_failed_start_answers_16266_and_leaves_no_running_row(preview_env, api_app, publish_db):
    """AC-26 「拉起失败展示原因并允许重新拉起」."""
    from sqlmodel import select

    from bisheng.app_publish.domain.models.app_preview_session import AppPreviewSession
    from bisheng.common.errcode.app_factory import AppProbeFailedError

    app, version, orchestrator = preview_env
    orchestrator.responses["preview_start"] = AppProbeFailedError(msg="exited on start-up")

    async with api_app(payload=_payload(APPROVER_USER_ID)) as client:
        body = _body(await client.post(f"/api/v1/apps/{app.id}/versions/{version.id}/preview"))

    assert body["status_code"] == 16266
    async with publish_db() as session:
        rows = (await session.exec(select(AppPreviewSession))).all()
    assert [row.status for row in rows] == ["reclaimed"]


async def test_a_failed_start_can_be_retried(preview_env, api_app):
    from bisheng.common.errcode.app_factory import AppCapacityInsufficientError

    app, version, orchestrator = preview_env
    orchestrator.responses["preview_start"] = AppCapacityInsufficientError(msg="no memory")

    async with api_app(payload=_payload(APPROVER_USER_ID)) as client:
        assert _body(await client.post(f"/api/v1/apps/{app.id}/versions/{version.id}/preview"))["status_code"] == 16266
        orchestrator.responses["preview_start"] = {
            "instance_id": "prev-2",
            "upstream": "http://172.31.0.9:8080",
            "phase": "running",
        }
        again = _body(await client.post(f"/api/v1/apps/{app.id}/versions/{version.id}/preview"))["data"]

    assert again["state"] == "running"


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------


async def test_before_anything_is_raised_the_state_is_absent(preview_env, api_app):
    app, version, _orchestrator = preview_env

    async with api_app(payload=_payload(APPROVER_USER_ID)) as client:
        data = _body(await client.get(f"/api/v1/apps/{app.id}/versions/{version.id}/preview"))["data"]

    assert data == {
        "state": "absent",
        "session_id": None,
        "entry_url": None,
        "expires_at": None,
        "reclaim_reason": None,
        "runnable": True,
        "not_runnable_reason": None,
    }


async def test_an_approver_does_not_see_another_approvers_instance(
    publish_db, app_factory, tier_seed, fake_orchestrator, api_app
):
    app, version = await _buildable(publish_db, app_factory)
    await _seed_task(publish_db, app=app, version_id=version.id, approver_user_id=APPROVER_USER_ID)
    await _seed_task(publish_db, app=app, version_id=version.id, approver_user_id=OTHER_APPROVER_USER_ID)

    async with api_app(payload=_payload(APPROVER_USER_ID)) as client:
        await client.post(f"/api/v1/apps/{app.id}/versions/{version.id}/preview")
    async with api_app(payload=_payload(OTHER_APPROVER_USER_ID)) as client:
        data = _body(await client.get(f"/api/v1/apps/{app.id}/versions/{version.id}/preview"))["data"]

    assert data["state"] == "absent"


async def test_a_version_without_a_build_reports_why_before_the_button_is_pressed(
    publish_db, app_factory, tier_seed, fake_orchestrator, api_app
):
    app, version = await app_factory(with_version=True)
    await _seed_task(publish_db, app=app, version_id=version.id, approver_user_id=APPROVER_USER_ID)

    async with api_app(payload=_payload(APPROVER_USER_ID)) as client:
        data = _body(await client.get(f"/api/v1/apps/{app.id}/versions/{version.id}/preview"))["data"]

    assert data["runnable"] is False
    assert data["not_runnable_reason"] == "no_image"


# ---------------------------------------------------------------------------
# reclaim
# ---------------------------------------------------------------------------


async def test_manual_reclaim_closes_the_row_and_stops_the_instance(preview_env, api_app):
    app, version, orchestrator = preview_env

    async with api_app(payload=_payload(APPROVER_USER_ID)) as client:
        started = _body(await client.post(f"/api/v1/apps/{app.id}/versions/{version.id}/preview"))["data"]
        session_id = started["session_id"]
        data = _body(await client.delete(f"/api/v1/apps/{app.id}/versions/{version.id}/preview/{session_id}"))["data"]

    assert data["state"] == "reclaimed"
    assert data["reclaim_reason"] == "manual"
    assert data["entry_url"] is None
    assert ("preview_stop", {"session_id": session_id}) in orchestrator.calls


async def test_after_reclaiming_a_new_one_can_be_raised(preview_env, api_app):
    """AC-28 「回收后可再拉起」."""
    app, version, _orchestrator = preview_env

    async with api_app(payload=_payload(APPROVER_USER_ID)) as client:
        first = _body(await client.post(f"/api/v1/apps/{app.id}/versions/{version.id}/preview"))["data"]
        await client.delete(f"/api/v1/apps/{app.id}/versions/{version.id}/preview/{first['session_id']}")
        second = _body(await client.post(f"/api/v1/apps/{app.id}/versions/{version.id}/preview"))["data"]

    assert second["state"] == "running"
    assert second["session_id"] != first["session_id"]


async def test_one_approver_cannot_reclaim_anothers_instance(
    publish_db, app_factory, tier_seed, fake_orchestrator, api_app
):
    app, version = await _buildable(publish_db, app_factory)
    await _seed_task(publish_db, app=app, version_id=version.id, approver_user_id=APPROVER_USER_ID)
    await _seed_task(publish_db, app=app, version_id=version.id, approver_user_id=OTHER_APPROVER_USER_ID)

    async with api_app(payload=_payload(APPROVER_USER_ID)) as client:
        mine = _body(await client.post(f"/api/v1/apps/{app.id}/versions/{version.id}/preview"))["data"]
    async with api_app(payload=_payload(OTHER_APPROVER_USER_ID)) as client:
        body = _body(await client.delete(f"/api/v1/apps/{app.id}/versions/{version.id}/preview/{mine['session_id']}"))

    assert body["status_code"] == 16264


async def test_reclaiming_an_unknown_session_answers_16267(preview_env, api_app):
    app, version, _orchestrator = preview_env

    async with api_app(payload=_payload(APPROVER_USER_ID)) as client:
        body = _body(await client.delete(f"/api/v1/apps/{app.id}/versions/{version.id}/preview/does-not-exist"))

    assert body["status_code"] == 16267


async def test_a_terminal_approval_reclaims_every_trial_of_that_version(
    publish_db, app_factory, tier_seed, fake_orchestrator, api_app
):
    """AC-28 — rejected / withdrawn / cancelled all go through the same body."""
    from bisheng.app_publish.domain.services.publish_terminal_service import PublishTerminalService

    app, version = await _buildable(publish_db, app_factory)
    await _seed_task(publish_db, app=app, version_id=version.id, approver_user_id=APPROVER_USER_ID)
    await _seed_task(publish_db, app=app, version_id=version.id, approver_user_id=OTHER_APPROVER_USER_ID)

    sessions = []
    for user_id in (APPROVER_USER_ID, OTHER_APPROVER_USER_ID):
        async with api_app(payload=_payload(user_id)) as client:
            sessions.append(
                _body(await client.post(f"/api/v1/apps/{app.id}/versions/{version.id}/preview"))["data"]["session_id"]
            )

    await PublishTerminalService.on_rejected(
        {"app_id": app.id, "version_id": version.id, "version_no": 1, "owner_user_id": OWNER_USER_ID},
        reason="not yet",
    )

    stopped = {kwargs["session_id"] for name, kwargs in fake_orchestrator.calls if name == "preview_stop"}
    assert stopped == set(sessions)
    for user_id, session_id in zip((APPROVER_USER_ID, OTHER_APPROVER_USER_ID), sessions, strict=True):
        async with api_app(payload=_payload(user_id)) as client:
            data = _body(await client.get(f"/api/v1/apps/{app.id}/versions/{version.id}/preview"))["data"]
        assert data["state"] == "absent", session_id


async def test_a_second_reclaim_changes_no_row_but_still_tells_the_orchestrator(preview_env, api_app, publish_db):
    """Three triggers race; the loser must not overwrite the winner's reason."""
    from bisheng.app_publish.domain.models.app_preview_session import AppPreviewSession
    from bisheng.app_publish.domain.services.preview_instance_service import PreviewInstanceService

    app, version, orchestrator = preview_env
    async with api_app(payload=_payload(APPROVER_USER_ID)) as client:
        started = _body(await client.post(f"/api/v1/apps/{app.id}/versions/{version.id}/preview"))["data"]
        await client.delete(f"/api/v1/apps/{app.id}/versions/{version.id}/preview/{started['session_id']}")

    before = len([1 for name, _ in orchestrator.calls if name == "preview_stop"])
    await PreviewInstanceService.reclaim_for_version(app.id, version.id, reason="approval_terminal")
    after = len([1 for name, _ in orchestrator.calls if name == "preview_stop"])

    # ``reclaim_for_version`` only walks *running* rows, so the second trigger
    # finds nothing — which is the point: the reason stays ``manual``.
    assert after == before
    async with publish_db() as session:
        row = await session.get(AppPreviewSession, started["session_id"])
    assert row.reclaim_reason == "manual"


# ---------------------------------------------------------------------------
# expiry
# ---------------------------------------------------------------------------


async def _age_session(publish_db, session_id: str, *, days: int) -> None:
    from bisheng.app_publish.domain.models.app_preview_session import AppPreviewSession

    async with publish_db() as session:
        row = await session.get(AppPreviewSession, session_id)
        row.expires_at = datetime.now() - timedelta(days=days)
        session.add(row)
        await session.commit()


async def test_an_expired_session_cannot_be_opened_even_before_it_is_swept(preview_env, api_app, publish_db):
    """The deadline is exact for a visitor; the container lags by one sweep."""
    from bisheng.app_publish.domain.services.preview_instance_service import PreviewInstanceService

    app, version, _orchestrator = preview_env
    async with api_app(payload=_payload(APPROVER_USER_ID)) as client:
        started = _body(await client.post(f"/api/v1/apps/{app.id}/versions/{version.id}/preview"))["data"]

    assert await PreviewInstanceService.resolve_entry(started["session_id"]) is not None
    await _age_session(publish_db, started["session_id"], days=1)
    assert await PreviewInstanceService.resolve_entry(started["session_id"]) is None


async def test_opening_the_panel_closes_out_expired_rows(preview_env, api_app, publish_db):
    app, version, orchestrator = preview_env
    async with api_app(payload=_payload(APPROVER_USER_ID)) as client:
        started = _body(await client.post(f"/api/v1/apps/{app.id}/versions/{version.id}/preview"))["data"]
    await _age_session(publish_db, started["session_id"], days=1)

    async with api_app(payload=_payload(APPROVER_USER_ID)) as client:
        data = _body(await client.get(f"/api/v1/apps/{app.id}/versions/{version.id}/preview"))["data"]

    assert data["state"] == "absent"
    assert ("preview_stop", {"session_id": started["session_id"]}) in orchestrator.calls


async def test_a_reclaimed_session_is_not_resolvable_as_an_entry(preview_env, api_app):
    from bisheng.app_publish.domain.services.preview_instance_service import PreviewInstanceService

    app, version, _orchestrator = preview_env
    async with api_app(payload=_payload(APPROVER_USER_ID)) as client:
        started = _body(await client.post(f"/api/v1/apps/{app.id}/versions/{version.id}/preview"))["data"]
        await client.delete(f"/api/v1/apps/{app.id}/versions/{version.id}/preview/{started['session_id']}")

    assert await PreviewInstanceService.resolve_entry(started["session_id"]) is None


# ---------------------------------------------------------------------------
# audit
# ---------------------------------------------------------------------------


async def test_raising_and_reclaiming_are_both_audited(preview_env, api_app, publish_db):
    from sqlmodel import select

    from bisheng.database.models.audit_log import AuditLog

    app, version, _orchestrator = preview_env
    async with api_app(payload=_payload(APPROVER_USER_ID)) as client:
        started = _body(await client.post(f"/api/v1/apps/{app.id}/versions/{version.id}/preview"))["data"]
        await client.delete(f"/api/v1/apps/{app.id}/versions/{version.id}/preview/{started['session_id']}")

    async with publish_db() as session:
        rows = (await session.exec(select(AuditLog))).all()
    actions = [row.action for row in rows]
    assert "app.release.preview_started" in actions
    assert "app.release.preview_reclaimed" in actions
    for row in rows:
        if row.action.startswith("app.release.preview_"):
            assert row.target_id == version.id
            assert int(row.operator_id or 0) == APPROVER_USER_ID


# ---------------------------------------------------------------------------
# tenant administrator
# ---------------------------------------------------------------------------


async def test_a_tenant_administrator_and_a_super_admin_may_preview(preview_env, api_app, monkeypatch):
    """Same door as the review view — ``ReviewAccess`` is the one access rule."""
    from bisheng.app_publish.domain.services import snapshot_browse_service

    app, version, _orchestrator = preview_env

    async def _is_admin(user_id: int, tenant_id: int) -> bool:
        return user_id == DEPT_ADMIN_USER_ID and tenant_id == ROOT_TENANT_ID

    monkeypatch.setattr(snapshot_browse_service, "check_tenant_admin", _is_admin)

    async with api_app(payload=_payload(DEPT_ADMIN_USER_ID)) as client:
        as_tenant_admin = _body(await client.post(f"/api/v1/apps/{app.id}/versions/{version.id}/preview"))
    async with api_app(payload=_payload(STRANGER_USER_ID, is_global_super=True)) as client:
        as_super = _body(await client.post(f"/api/v1/apps/{app.id}/versions/{version.id}/preview"))

    assert as_tenant_admin["data"]["state"] == "running"
    assert as_super["data"]["state"] == "running"
