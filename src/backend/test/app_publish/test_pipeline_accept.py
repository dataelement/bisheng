"""T020 — the synchronous receive leg (AC-01 / AC-02 / AC-03 / AC-04 / AC-05).

What has to be true of ``accept()`` and why:

* **It issues no RPC.** Everything here is answerable locally, and design D1's
  whole reason for splitting the pipeline is that this leg answers in
  milliseconds even when runtime-manager is down.
* **It never writes the ``app`` table.** F054 owns application state (决议-8), so
  a first publish goes through ``AppProvisionService.create_draft``. Writing the
  row here would work today and quietly diverge from the state machine the
  moment F054 adds a step to creation.
* **Ownership is the credential's *resource owner*, not its subject.** The
  subject is a service account: it has no department, it must never appear as
  an approval applicant, and it is not who the app belongs to (INV-29 / 坑 28).
* **The two submission gates are checked before the approval gate is called.**
  ``ApprovalGate`` answers a duplicate submission by silently returning the
  existing instance — so a second ``deploy`` would come back 200 with somebody
  else's request attached and the CLI would print "submitted" (设计 K2 ① / 坑 8).
* **Metadata is not updated here.** AC-05 updates name / description / icon once
  precheck and the scan pass; doing it on receipt would let a package that never
  builds rename a running application.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from .conftest import OWNER_USER_ID, ROOT_TENANT_ID

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _runtime_layer_on(app_runtime_settings):
    """The factory runtime layer is off by default; every test here needs it on.

    Its own gate (16207) is asserted separately — a deployment that never
    enabled the layer must be told so, rather than timing out on a build.

    The tenant ContextVar is set for the same reason the request middleware sets
    it in production: ``app_deployment.tenant_id`` is filled by the before-flush
    hook from the context, never from a Python default, so that a child-tenant
    submission can never be written to Root.
    """
    from bisheng.core.context.tenant import set_current_tenant_id

    set_current_tenant_id(ROOT_TENANT_ID)
    app_runtime_settings(enabled=True)


@pytest.fixture(autouse=True)
def _no_celery(monkeypatch):
    """Capture the hand-off to Celery instead of touching a broker."""
    from bisheng.app_publish.domain.services import publish_pipeline_service

    enqueued: list[str] = []

    async def _capture(deployment_id: str) -> None:
        enqueued.append(deployment_id)

    monkeypatch.setattr(publish_pipeline_service, "enqueue_pipeline", _capture)
    return enqueued


@pytest.fixture()
def enqueued(_no_celery):
    return _no_celery


async def _accept(package: Path, principal, **kwargs):
    from bisheng.app_publish.domain.services.publish_pipeline_service import PublishPipelineService

    return await PublishPipelineService.accept(package_path=package, principal=principal, **kwargs)


# ---------------------------------------------------------------------------
# First publish and ownership (AC-01 / AC-04)
# ---------------------------------------------------------------------------


async def test_first_deploy_creates_draft_app_via_f054_create_app(
    publish_db, tier_seed, tarball_factory, fake_minio, service_account_principal, fake_f054_services,
    fake_publish_approval, audit_sink, enqueued,
):
    """F055 must not write ``app`` itself (决议-8); the owner is the credential's resource owner."""
    from bisheng.database.models.app import AppDao

    fake_f054_services.responses["create_draft"] = "app-created-by-f054"
    result = await _accept(tarball_factory(), service_account_principal())

    assert result.app_id == "app-created-by-f054"
    create = dict(next(payload for name, payload in fake_f054_services.calls if name == "create_draft"))
    assert create["owner_user_id"] == OWNER_USER_ID
    assert create["tenant_id"] == ROOT_TENANT_ID
    assert create["name"] == "minimal-app"
    async with publish_db() as session:
        assert await AppDao.aget(session, "app-created-by-f054") is None, "no app row is written by F055"


async def test_owner_read_from_resource_owner_user_id_not_subject_user_id(
    tier_seed, tarball_factory, fake_minio, service_account_principal, fake_f054_services, fake_publish_approval,
    audit_sink, enqueued,
):
    """坑 28 — the acting subject is a service account and is nobody's owner."""
    from .conftest import SERVICE_ACCOUNT_USER_ID

    fake_f054_services.responses["create_draft"] = "app-1"
    principal = service_account_principal(resource_owner_user_id=OWNER_USER_ID)
    assert principal.subject_user_id == SERVICE_ACCOUNT_USER_ID

    await _accept(tarball_factory(), principal)
    create = dict(next(payload for name, payload in fake_f054_services.calls if name == "create_draft"))
    assert create["owner_user_id"] == OWNER_USER_ID != SERVICE_ACCOUNT_USER_ID


async def test_iteration_deploy_requires_owner_match_else_16205(
    tier_seed, tarball_factory, fake_minio, app_factory, service_account_principal, fake_f054_services,
    fake_publish_approval, audit_sink, enqueued,
):
    """A key may publish, its resource owner decides *whose* apps (AC-04)."""
    from bisheng.common.errcode.app_publish import AppNotOwnedBySubjectError

    someone_else, _ = await app_factory(owner_user_id=OWNER_USER_ID + 99, with_version=False)
    with pytest.raises(AppNotOwnedBySubjectError) as excinfo:
        await _accept(tarball_factory(), service_account_principal(), app_id=someone_else.id)
    assert excinfo.value.code == 16205
    assert fake_f054_services.calls == [], "a rejected submission creates nothing"


async def test_retry_deploy_reuses_same_app_id_not_new_draft(
    publish_db, tier_seed, tarball_factory, fake_minio, app_factory, service_account_principal, fake_f054_services,
    fake_publish_approval, audit_sink, enqueued,
):
    """The CLI stores ``app_id`` with the project, so a retry is an iteration (design D2-B)."""
    app_row, _ = await app_factory(with_version=False)
    first = await _accept(tarball_factory(), service_account_principal(), app_id=app_row.id)
    second = await _accept(tarball_factory(), service_account_principal(), app_id=app_row.id)

    assert first.app_id == second.app_id == app_row.id
    assert first.deployment_id != second.deployment_id
    assert [name for name, _ in fake_f054_services.calls if name == "create_draft"] == []


# ---------------------------------------------------------------------------
# The two submission gates (AC-03)
# ---------------------------------------------------------------------------


async def test_active_approval_blocks_new_submit_16251(
    tier_seed, tarball_factory, fake_minio, app_factory, service_account_principal, fake_f054_services,
    fake_publish_approval, audit_sink, enqueued,
):
    """Checked *before* the gate — the gate's own answer to a duplicate is a silent 200 (坑 8)."""
    from bisheng.common.errcode.app_publish import AppApprovalInFlightError

    app_row, _ = await app_factory(with_version=False)
    fake_publish_approval.responses["assert_submittable"] = AppApprovalInFlightError(msg="in flight")

    with pytest.raises(AppApprovalInFlightError) as excinfo:
        await _accept(tarball_factory(), service_account_principal(), app_id=app_row.id)

    assert excinfo.value.code == 16251
    called = [name for name, _ in fake_publish_approval.calls]
    assert "assert_submittable" in called and "submit" not in called


async def test_pending_online_state_blocks_new_submit_16252(
    tier_seed, tarball_factory, fake_minio, app_factory, service_account_principal, fake_f054_services,
    fake_publish_approval, audit_sink, enqueued,
):
    from bisheng.common.errcode.app_publish import AppPendingOnlineError

    app_row, _ = await app_factory(with_version=False)
    fake_publish_approval.responses["assert_submittable"] = AppPendingOnlineError(msg="pending online")
    with pytest.raises(AppPendingOnlineError) as excinfo:
        await _accept(tarball_factory(), service_account_principal(), app_id=app_row.id)
    assert excinfo.value.code == 16252


# ---------------------------------------------------------------------------
# What the receive leg leaves behind (AC-01 / AC-02 / AC-05)
# ---------------------------------------------------------------------------


async def test_deployment_row_created_with_stage_received(
    publish_db, tier_seed, tarball_factory, fake_minio, app_factory, service_account_principal, fake_f054_services,
    fake_publish_approval, audit_sink, enqueued,
):
    from bisheng.app_publish.domain.models.app_deployment import (
        STAGE_RECEIVED,
        STATUS_RUNNING,
        AppDeploymentDao,
    )

    from .conftest import SERVICE_ACCOUNT_USER_ID

    app_row, _ = await app_factory(with_version=False)
    result = await _accept(tarball_factory(), service_account_principal(), app_id=app_row.id)

    async with publish_db() as session:
        row = await AppDeploymentDao.aget(session, result.deployment_id)
    assert (row.stage, row.status) == (STAGE_RECEIVED, STATUS_RUNNING)
    assert (row.owner_user_id, row.submitted_by_user_id) == (OWNER_USER_ID, SERVICE_ACCOUNT_USER_ID)
    assert row.manifest["runtime"] == "python3.11"
    assert row.tier_code == "light", "an undeclared tier resolves to 轻量 at receive time (AC-46)"
    assert enqueued == [result.deployment_id], "the async leg is handed off exactly once"
    assert "app.release.submit" in {call["action"] for call in audit_sink}


async def test_version_id_generated_at_accept_and_reused_by_version_row(
    publish_db, tier_seed, tarball_factory, fake_minio, app_factory, service_account_principal, fake_f054_services,
    fake_publish_approval, audit_sink, enqueued,
):
    """The object key is minted with the version id; there is no staging key and no copy (design D2)."""
    from bisheng.app_publish.domain.models.app_deployment import AppDeploymentDao

    app_row, _ = await app_factory(with_version=False)
    result = await _accept(tarball_factory(), service_account_principal(), app_id=app_row.id)

    async with publish_db() as session:
        row = await AppDeploymentDao.aget(session, result.deployment_id)
    assert row.version_id == result.version_id
    assert row.code_object_key == f"apps/{app_row.id}/versions/{result.version_id}/code.tar.gz"
    assert await fake_minio.get_object(bucket_name="bisheng-apps", object_name=row.code_object_key) is not None


async def test_meta_not_updated_at_accept(
    tier_seed, tarball_factory, fake_minio, app_factory, service_account_principal, fake_f054_services,
    fake_publish_approval, audit_sink, enqueued,
):
    """AC-05 updates metadata after precheck and the scan pass — never on receipt."""
    app_row, _ = await app_factory(with_version=False)
    await _accept(tarball_factory(), service_account_principal(), app_id=app_row.id)
    assert [name for name, _ in fake_f054_services.calls if name == "update_meta"] == []


async def test_accept_returns_deployment_id_within_seconds_no_rpc(
    tier_seed, tarball_factory, fake_minio, app_factory, service_account_principal, fake_f054_services,
    fake_publish_approval, fake_orchestrator, audit_sink, enqueued,
):
    """Design D1's choice C, asserted: an unreachable manager cannot slow this leg down."""
    app_row, _ = await app_factory(with_version=False)
    result = await _accept(tarball_factory(), service_account_principal(), app_id=app_row.id)

    assert result.deployment_id
    assert fake_orchestrator.calls == [], "the receive leg must not touch runtime-manager"


async def test_illegal_package_rejected_before_anything_is_created(
    publish_db, tier_seed, tarball_factory, fake_minio, app_factory, service_account_principal, fake_f054_services,
    fake_publish_approval, audit_sink, enqueued,
):
    """A hostile package leaves no deployment row, no object and no draft app."""
    from bisheng.app_publish.domain.models.app_deployment import AppDeploymentDao
    from bisheng.common.errcode.app_publish import AppPackageInvalidError

    app_row, _ = await app_factory(with_version=False)
    with pytest.raises(AppPackageInvalidError):
        await _accept(tarball_factory(symlink=True), service_account_principal(), app_id=app_row.id)

    async with publish_db() as session:
        assert await AppDeploymentDao.alist_by_app(session, app_row.id) == []
    assert fake_minio.list_object_names("bisheng-apps") == []
    assert enqueued == []


async def test_runtime_layer_disabled_is_16207(
    tier_seed, tarball_factory, fake_minio, app_factory, service_account_principal, app_runtime_settings,
    fake_f054_services, fake_publish_approval, audit_sink, enqueued,
):
    """A deployment without the app factory says so on the first call, not after a build times out."""
    from bisheng.common.errcode.app_publish import AppPublishRuntimeLayerDisabledError

    app_row, _ = await app_factory(with_version=False)
    app_runtime_settings(enabled=False)
    with pytest.raises(AppPublishRuntimeLayerDisabledError) as excinfo:
        await _accept(tarball_factory(), service_account_principal(), app_id=app_row.id)
    assert excinfo.value.code == 16207
