"""T022 — the asynchronous stage machine (AC-01 / AC-02 / AC-05 / AC-10 / AC-11 / AC-48 / AC-55).

Read together with ``test_pipeline_accept.py``: that file covers the leg that
answers in milliseconds, this one the leg that takes minutes.

What each assertion here is protecting:

* **One row update and one audit row per stage.** "Where is my publish" has to
  be answerable from ``app_deployment`` alone (the CLI polls it) *and* from the
  audit page (AC-01). The audit family carries ``target_type='app_version'`` and
  ``app_id`` / ``version_no`` in metadata, because the approval module's own
  audit rows are keyed on ``approval_instance`` and filtering them by
  application finds nothing (design 坑 20).
* **A blocked scan and a failed precheck terminate identically**: five-tuple
  persisted, no version row, no approval request. AC-02 / AC-07 both hinge on
  the version list staying free of attempts that never passed.
* **Metadata lands before approval, not after.** AC-05 is explicit that name /
  description / icon are not part of what gets approved.
* **The icon is stored as an object name.** The upload helper's ``file_path`` is
  a presigned URL that expires in seven days, so storing it makes every hosted
  app's icon 403 a week after release (design 坑 16). The package-relative path
  would be equally wrong in a different way.
* **The worker's tenant comes from the row, loudly.** ``worker/tenant_context.py``
  falls back to the default tenant when the Celery header is missing; publishing
  a child tenant's app into Root silently is the worst possible shape.
"""

from __future__ import annotations

import pytest

from .conftest import ROOT_TENANT_ID, SUB_TENANT_ID

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _runtime_layer_on(app_runtime_settings):
    from bisheng.core.context.tenant import set_current_tenant_id

    set_current_tenant_id(ROOT_TENANT_ID)
    app_runtime_settings(enabled=True)


@pytest.fixture(autouse=True)
def _no_celery(monkeypatch):
    from bisheng.app_publish.domain.services import publish_pipeline_service

    async def _capture(deployment_id: str) -> None:
        return None

    monkeypatch.setattr(publish_pipeline_service, "enqueue_pipeline", _capture)


@pytest.fixture()
async def accepted(
    publish_db, tier_seed, tarball_factory, fake_minio, app_factory, service_account_principal,
    fake_f054_services, fake_publish_approval,
):
    """``accept()`` already ran; return a factory so a test can vary the package."""
    from bisheng.app_publish.domain.services.publish_pipeline_service import PublishPipelineService

    app_row, _ = await app_factory(with_version=False)

    async def _accept(**tar_kwargs):
        result = await PublishPipelineService.accept(
            package_path=tarball_factory(**tar_kwargs),
            principal=service_account_principal(),
            app_id=app_row.id,
        )
        return app_row, result

    return _accept


async def _run(deployment_id: str) -> None:
    from bisheng.app_publish.domain.services.publish_pipeline_service import PublishPipelineService

    await PublishPipelineService.run_pipeline(deployment_id)


async def _deployment(publish_db, deployment_id: str):
    from bisheng.app_publish.domain.models.app_deployment import AppDeploymentDao

    async with publish_db() as session:
        return await AppDeploymentDao.aget(session, deployment_id)


def _actions(audit_sink) -> list[str]:
    return [call["action"] for call in audit_sink]


# ---------------------------------------------------------------------------
# Happy path: stage advance + audit (AC-01)
# ---------------------------------------------------------------------------


async def test_stage_advances_one_row_update_per_stage(publish_db, accepted, fake_orchestrator, audit_sink):
    from bisheng.app_publish.domain.models.app_deployment import (
        STAGE_APPROVAL_CREATED,
        STATUS_WAITING_APPROVAL,
    )

    _, result = await accepted()
    await _run(result.deployment_id)

    row = await _deployment(publish_db, result.deployment_id)
    assert (row.stage, row.status) == (STAGE_APPROVAL_CREATED, STATUS_WAITING_APPROVAL)
    assert row.failure is None
    assert row.scan_result["blocked"] is False
    assert [name for name, _ in fake_orchestrator.calls] == ["runtime_status", "build", "build_status", "probe"]

    # Every write to app_deployment is pinned to one primary key. The tenant
    # filter rewrites SELECTs and nothing else, so a bulk UPDATE would escape
    # isolation without leaving a trace (repo memory
    # ``reference_tenant_filter_in_list_trap``) — the DAO's shape is what
    # prevents one from ever being written.
    import inspect

    from bisheng.app_publish.domain.models.app_deployment import AppDeploymentDao

    for name in ("aadvance_stage", "aset_failed"):
        params = inspect.signature(getattr(AppDeploymentDao, name)).parameters
        assert "deployment_id" in params, f"{name} must be pinned to a single row"


async def test_pipeline_stage_order_is_build_probe_scan(publish_db, accepted, fake_orchestrator, audit_sink):
    """spec AC-01 / F053 AC-31a spell this order out verbatim (design D5's open question)."""
    from bisheng.app_publish.domain.services.publish_pipeline_service import PIPELINE_STAGES

    assert [stage for stage, _ in PIPELINE_STAGES] == ["secret_scan", "precheck_build", "precheck_probe"], (
        "the scan runs first (design D5, ruled 2026-08-17): a hit ends the attempt, so building first "
        "burns a build and a capacity slot for every hit"
    )


async def test_each_stage_writes_one_app_release_audit_with_app_id_and_version_no(
    publish_db, accepted, fake_orchestrator, audit_sink
):
    app_row, result = await accepted()
    await _run(result.deployment_id)

    actions = _actions(audit_sink)
    assert "app.release.version_created" in actions
    assert "app.release.approval_created" in actions
    for call in audit_sink:
        if not call["action"].startswith("app.release."):
            continue
        assert call["target_type"] == "app_version", "filtering the audit page by application depends on this"
        assert call["metadata"]["app_id"] == app_row.id
        assert call["metadata"]["deployment_id"] == result.deployment_id
    created = next(call for call in audit_sink if call["action"] == "app.release.version_created")
    assert created["metadata"]["version_no"] == 1
    assert created["target_id"] == result.version_id


async def test_status_becomes_waiting_approval_after_approval_created(
    publish_db, accepted, fake_orchestrator, audit_sink, fake_publish_approval
):
    """The CLI stops here by default (F053 AC-31b); ``--wait`` keeps polling."""
    from bisheng.app_publish.domain.models.app_deployment import STATUS_WAITING_APPROVAL

    _, result = await accepted()
    await _run(result.deployment_id)

    row = await _deployment(publish_db, result.deployment_id)
    assert row.status == STATUS_WAITING_APPROVAL
    assert row.approval_instance_id == 9001
    assert [name for name, _ in fake_publish_approval.calls if name == "submit"] == ["submit"]


# ---------------------------------------------------------------------------
# Termination paths (AC-02 / AC-10 / AC-11)
# ---------------------------------------------------------------------------


async def test_scan_hit_terminates_pipeline_16241_no_version_no_approval(
    publish_db, accepted, fake_orchestrator, audit_sink, fake_publish_approval
):
    from bisheng.app_publish.domain.models.app_deployment import STATUS_FAILED
    from bisheng.database.models.app_version import AppVersionDao

    app_row, result = await accepted(extra_files={"settings.py": 'AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"\n'})
    await _run(result.deployment_id)

    row = await _deployment(publish_db, result.deployment_id)
    assert (row.status, row.failure["code"]) == (STATUS_FAILED, 16241)
    assert row.failure["stage"] == "secret_scan"
    assert row.failure["details"]["hits"][0]["rule_id"] == "aws_akid"
    assert "AKIAIOSFODNN7EXAMPLE" not in str(row.failure), "the value never leaves the scanner (AC-10)"
    async with publish_db() as session:
        assert await AppVersionDao.alist_by_app(session, app_row.id) == []
    assert [name for name, _ in fake_publish_approval.calls if name == "submit"] == []
    assert "app.release.scan_blocked" in _actions(audit_sink)


async def test_precheck_failure_terminates_and_persists_failure_tuple(
    publish_db, accepted, fake_orchestrator, audit_sink, fake_publish_approval
):
    from bisheng.app_publish.domain.models.app_deployment import STATUS_FAILED
    from bisheng.database.models.app_version import AppVersionDao

    app_row, result = await accepted()
    fake_orchestrator.responses["probe"] = {"ready": False, "reason": "connection refused"}
    await _run(result.deployment_id)

    row = await _deployment(publish_db, result.deployment_id)
    assert (row.status, row.stage) == (STATUS_FAILED, "precheck_probe")
    assert set(row.failure) == {"stage", "code", "message", "details", "hints"}
    assert row.failure["code"] == 16228
    assert any("BISHENG_APP_DB_URL" in hint for hint in row.failure["hints"])
    async with publish_db() as session:
        assert await AppVersionDao.alist_by_app(session, app_row.id) == []
    assert "app.release.precheck_failed" in _actions(audit_sink)
    assert [name for name, _ in fake_publish_approval.calls if name == "submit"] == []


# ---------------------------------------------------------------------------
# Metadata, icon, snapshot (AC-05 / AC-48 / AC-55)
# ---------------------------------------------------------------------------


async def test_meta_updated_after_precheck_and_scan_pass_not_awaiting_approval(
    publish_db, accepted, fake_orchestrator, audit_sink, fake_f054_services
):
    """AC-05 — through F054's ``AppMetaService``; F055 does not keep a second copy of that logic."""
    app_row, result = await accepted()
    await _run(result.deployment_id)

    meta = dict(next(payload for name, payload in fake_f054_services.calls if name == "update_meta"))
    assert meta["app_id"] == app_row.id
    assert meta["name"] == "minimal-app"


async def test_meta_not_updated_when_scan_blocks(publish_db, accepted, fake_orchestrator, audit_sink, fake_f054_services):
    """A package that never passes must not be able to rename a running application."""
    _, result = await accepted(extra_files={"leak.py": 'AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"\n'})
    await _run(result.deployment_id)
    assert [name for name, _ in fake_f054_services.calls if name == "update_meta"] == []


async def test_icon_extracted_from_package_and_stored_as_minio_object_name(
    publish_db, accepted, fake_orchestrator, audit_sink, fake_f054_services, fake_minio
):
    """An object name — not a presigned URL (坑 16), not the package-relative path."""
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    _, result = await accepted(
        manifest="name: minimal-app\nruntime: python3.11\nport: 8080\nicon: assets/logo.png\n",
        extra_files={"assets/logo.png": png.decode("latin-1")},
    )
    await _run(result.deployment_id)

    meta = dict(next(payload for name, payload in fake_f054_services.calls if name == "update_meta"))
    logo = meta["logo"]
    assert logo.startswith("icon/") and logo.endswith(".png")
    assert "http" not in logo and "X-Amz" not in logo, "a presigned URL expires in 7 days (坑 16)"
    assert "assets/logo.png" != logo, "the package-relative path means nothing outside the tarball"
    assert fake_minio.object_exists_sync(None, logo)


@pytest.mark.parametrize(
    ("icon", "extra"),
    [
        ("assets/logo.svg", {"assets/logo.svg": "<svg/>"}),
        ("assets/missing.png", {}),
    ],
)
async def test_bad_icon_is_skipped_not_fatal(
    publish_db, accepted, fake_orchestrator, audit_sink, fake_f054_services, icon, extra
):
    """An icon is metadata; refusing the publish over it would be out of proportion (design D12)."""
    from bisheng.app_publish.domain.models.app_deployment import STATUS_WAITING_APPROVAL

    _, result = await accepted(
        manifest=f"name: minimal-app\nruntime: python3.11\nport: 8080\nicon: {icon}\n", extra_files=extra
    )
    await _run(result.deployment_id)

    row = await _deployment(publish_db, result.deployment_id)
    assert row.status == STATUS_WAITING_APPROVAL
    meta = dict(next(payload for name, payload in fake_f054_services.calls if name == "update_meta"))
    assert meta["logo"] is None


async def test_tier_and_capabilities_enter_snapshot(publish_db, accepted, fake_orchestrator, audit_sink):
    """AC-48 / F054 AC-02 — code, capabilities, injections and tier are one frozen snapshot."""
    from bisheng.database.models.app_version import AppVersionDao

    app_row, result = await accepted()
    await _run(result.deployment_id)

    async with publish_db() as session:
        version = await AppVersionDao.aget(session, app_row.id, result.version_id)
    assert version.tier_id == "light"
    assert version.runtime == "python3.11"
    assert version.code_object_key == f"apps/{app_row.id}/versions/{result.version_id}/code.tar.gz"
    assert version.manifest["port"] == 8080
    assert version.capabilities == {"models": [], "knowledge_bases": []}


async def test_capability_declaration_change_audited_each_release(publish_db, accepted, fake_orchestrator, audit_sink):
    """AC-55's second half: every release records what it declared, even when that is nothing."""
    _, result = await accepted()
    await _run(result.deployment_id)

    declared = next(call for call in audit_sink if call["action"] == "app.release.capability_declared")
    assert declared["metadata"]["tier_code"] == "light"
    assert declared["metadata"]["capabilities"] == {"models": [], "knowledge_bases": []}


# ---------------------------------------------------------------------------
# Worker context (AC-01)
# ---------------------------------------------------------------------------


async def test_worker_tenant_context_restored_from_celery_header(
    publish_db, tier_seed, tarball_factory, fake_minio, app_factory, service_account_principal,
    fake_f054_services, fake_publish_approval, fake_orchestrator, audit_sink,
):
    """A child tenant's publish must not be able to land in Root because a header went missing."""
    from bisheng.app_publish.domain.services.publish_pipeline_service import PublishPipelineService
    from bisheng.core.context.tenant import get_current_tenant_id, set_current_tenant_id

    set_current_tenant_id(SUB_TENANT_ID)
    app_row, _ = await app_factory(tenant_id=SUB_TENANT_ID, with_version=False)
    result = await PublishPipelineService.accept(
        package_path=tarball_factory(), principal=service_account_principal(), app_id=app_row.id
    )

    # The header is gone: the worker starts on the default tenant.
    set_current_tenant_id(ROOT_TENANT_ID)
    await _run(result.deployment_id)

    assert get_current_tenant_id() == SUB_TENANT_ID, "the row's tenant wins over a wrong context"
    for call in audit_sink:
        if call["action"].startswith("app.release."):
            assert call["tenant_id"] == SUB_TENANT_ID
