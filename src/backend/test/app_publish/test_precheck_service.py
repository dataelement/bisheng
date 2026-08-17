"""T018 — hosted precheck: linear fail-fast, and one failure shape everywhere (AC-07 / AC-08 / AC-11).

The two properties that are easy to lose and expensive to lose:

* **The synchronous leg issues no RPC.** Manifest validation runs inside the
  ``POST /api/v2/apps/deploy`` request. One call to an unreachable
  runtime-manager there turns "you forgot ``port``" from a 200 ms answer into a
  request hanging on a socket timeout — which is precisely the failure design
  D1 chose its shape to avoid. The re-check of ``runtime`` against the manager's
  own list therefore happens at the *start of the build stage*, not in the
  manifest stage.
* **Every failure is the same five-tuple.** ``{stage, code, message, details,
  hints}`` — the CLI, the publish face and ``app_deployment.failure`` all read
  the same dict. Two shapes for the same failure diverge within one release.

One error-code trap has already been fallen into upstream and is asserted
explicitly: capacity shortage during build is **16226**. ``16225`` means "this
deployment never seeded the approval scenario" and nothing else — the remedies
are "wait for memory" versus "ask an administrator to seed a scenario".
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


@pytest.fixture()
async def prepared(publish_db, tier_seed, app_factory, deployment_factory, fake_minio, tarball_factory):
    """An accepted deployment whose snapshot is stored — the state the async leg starts from."""
    from types import SimpleNamespace

    from bisheng.app_publish.domain.services.manifest_validator import validate_manifest
    from bisheng.app_publish.domain.services.package_service import store_package

    app_row, _ = await app_factory(with_version=False)
    package = tarball_factory()
    key = await store_package(package, app_id=app_row.id, version_id="ver-pc")
    validated = await validate_manifest(_manifest_yaml())
    deployment = await deployment_factory(
        app_id=app_row.id,
        version_id="ver-pc",
        code_object_key=key,
        manifest=validated.manifest.model_dump(),
        tier_code=validated.tier.code,
    )
    return SimpleNamespace(app=app_row, deployment=deployment, manifest=validated.manifest, tier=validated.tier)


def _manifest_yaml() -> str:
    return "name: minimal-app\nruntime: python3.11\nport: 8080\n"


async def _build(prepared, **kwargs):
    from bisheng.app_publish.domain.services.precheck_service import precheck_build

    return await precheck_build(prepared.deployment, manifest=prepared.manifest, tier=prepared.tier, **kwargs)


async def _probe(prepared, image_ref: str = "img:1"):
    from bisheng.app_publish.domain.services.precheck_service import precheck_probe

    return await precheck_probe(prepared.deployment, manifest=prepared.manifest, image_ref=image_ref)


# ---------------------------------------------------------------------------
# Stage order and the synchronous / asynchronous split (AC-07)
# ---------------------------------------------------------------------------


async def test_stage_order_manifest_build_probe_then_scan(prepared, fake_orchestrator):
    """manifest (sync) → build → probe; the secret scan is the pipeline's next step, not precheck's."""
    from bisheng.app_publish.domain.services import precheck_service

    image_ref = await _build(prepared)
    await _probe(prepared, image_ref)

    assert [name for name, _ in fake_orchestrator.calls] == ["runtime_status", "build", "build_status", "probe"]
    assert not hasattr(precheck_service, "scan_package"), (
        "the scan is a pipeline stage of its own (design D5); precheck must not reach into the scanner"
    )


async def test_manifest_stage_makes_no_rpc(tier_seed, fake_orchestrator):
    """The receive leg must stay local — see the module docstring."""
    from bisheng.app_publish.domain.services.manifest_validator import validate_manifest

    await validate_manifest(_manifest_yaml())
    assert fake_orchestrator.calls == []


async def test_runtime_rechecked_against_manager_in_async_stage_16222(prepared, fake_orchestrator):
    """The local enum is a copy; the manager's list is the truth, consulted at the start of the build."""
    from bisheng.common.errcode.app_publish import AppRuntimeUnsupportedError

    fake_orchestrator.responses["runtime_status"] = {
        "backend_available": True,
        "supported_runtimes": ["python3.12"],
        "capacity": {},
        "preflight": [],
    }
    with pytest.raises(AppRuntimeUnsupportedError) as excinfo:
        await _build(prepared)
    assert excinfo.value.code == 16222
    assert [name for name, _ in fake_orchestrator.calls] == ["runtime_status"], "no build is started for a dead runtime"
    assert excinfo.value.kwargs["details"]["supported_runtimes"] == ["python3.12"]


async def test_build_intent_carries_presigned_code_url_and_tier(prepared, fake_orchestrator, fake_minio):
    """The manager has no MinIO credentials: ``code_url`` is a presigned link (contract §2)."""
    await _build(prepared)
    _, payload = next(call for call in fake_orchestrator.calls if call[0] == "build")

    assert payload["code_url"].startswith("http")
    assert payload["code_object_key"] == prepared.deployment.code_object_key
    assert payload["runtime"] == "python3.11"
    # ``tier`` speaks vCPU / MiB — the table's millicores are converted exactly once.
    assert payload["tier"] == {"cpu": 1.0, "mem": 2048}


# ---------------------------------------------------------------------------
# Failure mapping (AC-07 / AC-11)
# ---------------------------------------------------------------------------


async def test_build_capacity_shortage_is_16226_not_16225(prepared, fake_orchestrator):
    """16225 is only "the approval scenario is not enabled" — a hard rule, already broken once upstream."""
    from bisheng.common.errcode.app_factory import AppCapacityInsufficientError as UpstreamCapacity
    from bisheng.common.errcode.app_publish import AppCapacityInsufficientError

    fake_orchestrator.responses["build"] = UpstreamCapacity(msg="not enough memory")
    with pytest.raises(AppCapacityInsufficientError) as excinfo:
        await _build(prepared)
    assert excinfo.value.code == 16226
    assert excinfo.value.kwargs["details"]["upstream_code"] == 16125


async def test_build_failure_16227_carries_manager_stage_message_tail(prepared, fake_orchestrator):
    """The manager's own ``stage`` / ``message`` / ``tail`` is what makes a build failure actionable."""
    from bisheng.common.errcode.app_publish import AppDependencyBuildFailedError

    fake_orchestrator.responses["build_status"] = {
        "status": "failed",
        "stage": "docker_build",
        "message": "pip install failed",
        "tail": ["ERROR: No matching distribution found for pandas==99.0"],
        "image_ref": None,
    }
    with pytest.raises(AppDependencyBuildFailedError) as excinfo:
        await _build(prepared)
    details = excinfo.value.kwargs["details"]
    assert (excinfo.value.code, details["build_stage"]) == (16227, "docker_build")
    assert "pandas" in " ".join(details["tail"])


async def test_manager_unreachable_during_build_is_16227_with_upstream_reason(prepared, fake_orchestrator):
    """The async leg is allowed to depend on the manager; it just has to say so in ``details``."""
    from bisheng.common.errcode.app_factory import AppOrchestratorUnavailableError
    from bisheng.common.errcode.app_publish import AppDependencyBuildFailedError

    fake_orchestrator.responses["runtime_status"] = AppOrchestratorUnavailableError(msg="connection refused")
    with pytest.raises(AppDependencyBuildFailedError) as excinfo:
        await _build(prepared)
    assert excinfo.value.kwargs["details"]["upstream_code"] == 16121


async def test_probe_failure_16228_with_hosting_contract_hints(prepared, fake_orchestrator):
    """AC-08's judgement is a failed start, not static dependency analysis (design D4)."""
    from bisheng.common.errcode.app_publish import AppStartupProbeFailedError

    fake_orchestrator.responses["probe"] = {"ready": False, "reason": "connection refused on 8080"}
    with pytest.raises(AppStartupProbeFailedError) as excinfo:
        await _probe(prepared)
    assert excinfo.value.code == 16228
    hints = " ".join(excinfo.value.kwargs["hints"])
    assert "BISHENG_APP_DB_URL" in hints
    assert "数据库" in hints or "database" in hints.lower()


async def test_probe_is_temporary_and_takes_no_instance_slot(prepared, fake_orchestrator):
    """``probe`` is called with ``image_ref`` + port + health, not with an ``app_id`` (contract §2)."""
    await _probe(prepared, "img:7")
    _, payload = next(call for call in fake_orchestrator.calls if call[0] == "probe")
    assert payload["image_ref"] == "img:7"
    assert payload["port"] == 8080
    assert "app_id" not in payload, "a probe that names the app would occupy the real instance"


async def test_egress_domains_format_only_this_round(tier_seed):
    """Enforcement is F054 D12's, deferred; this round only the format is checked (AC-08)."""
    from bisheng.app_publish.domain.services.manifest_validator import validate_manifest

    outcome = await validate_manifest(_manifest_yaml() + "egress:\n  domains:\n    - api.example.com\n")
    assert outcome.manifest.egress.domains == ["api.example.com"]


async def test_failure_shape_is_five_tuple_in_all_stages(prepared, fake_orchestrator):
    """One shape, every stage — this is what AC-11 actually promises."""
    from bisheng.app_publish.domain.models.app_deployment import STAGE_PRECHECK_BUILD, STAGE_PRECHECK_PROBE
    from bisheng.app_publish.domain.schemas.failure import failure_from_error
    from bisheng.common.errcode.app_factory import AppCapacityInsufficientError as UpstreamCapacity
    from bisheng.common.errcode.base import BaseErrorCode

    failures = []
    fake_orchestrator.responses["build"] = UpstreamCapacity(msg="no memory")
    try:
        await _build(prepared)
    except BaseErrorCode as exc:
        failures.append(failure_from_error(exc, stage=STAGE_PRECHECK_BUILD))

    fake_orchestrator.responses["probe"] = {"ready": False, "reason": "timeout"}
    try:
        await _probe(prepared)
    except BaseErrorCode as exc:
        failures.append(failure_from_error(exc, stage=STAGE_PRECHECK_PROBE))

    assert len(failures) == 2
    for failure in failures:
        assert set(failure) == {"stage", "code", "message", "details", "hints"}
        assert failure["stage"].startswith("precheck_")
        assert isinstance(failure["details"], dict) and isinstance(failure["hints"], list)


async def test_precheck_failure_produces_no_approval_and_no_version(publish_db, prepared, fake_orchestrator):
    """AC-07's hard promise, asserted at the storage layer rather than taken on trust."""
    from bisheng.common.errcode.base import BaseErrorCode
    from bisheng.database.models.app_version import AppVersionDao

    fake_orchestrator.responses["probe"] = {"ready": False, "reason": "timeout"}
    with pytest.raises(BaseErrorCode):
        await _probe(prepared)

    async with publish_db() as session:
        assert await AppVersionDao.alist_by_app(session, prepared.app.id) == []
    assert prepared.deployment.approval_instance_id is None
