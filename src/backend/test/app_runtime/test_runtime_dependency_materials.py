"""覆盖 AC: AC-15、AC-25、AC-28、AC-29、AC-46、AC-47. Selected dependency cache is durable authority."""

from datetime import timedelta

import pytest

from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeArtifact, RuntimeDependencyPlan, RuntimeOperation
from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict
from bisheng.app_runtime.domain.services.runtime_profile_service import RuntimeDependencyService
from test.app_runtime.test_runtime_kubernetes_repository import repo as repo
from test.app_runtime.test_runtime_kubernetes_service import MANAGER
from test.app_runtime.test_runtime_kubernetes_service import control as control
from test.app_runtime.test_runtime_material_service import create, reframe
from test.app_runtime.test_runtime_material_service import materials as materials

KEY = "a" * 64


@pytest.fixture
async def dependencies(materials):
    m = materials
    await reframe(m, "prepare", "prepare-download")
    source = await m.repo.save(
        RuntimeArtifact(
            tenant_id=1,
            app_id=m.op.app_id,
            scope_key="1/" + m.op.app_id,
            kind="source",
            sha256="b" * 64,
            state="verified",
            platform="",
            confirmed_at=m.clock["now"],
        )
    )
    m.op.payload = {
        **m.op.payload,
        "source_artifact_id": source.id,
        "profile": {"profile_id": "profile-a", "profile_digest": "c" * 64, "platform": "linux/amd64"},
    }
    await m.repo.save(m.op)
    artifact = await m.repo.save(
        RuntimeArtifact(
            tenant_id=1,
            app_id=m.op.app_id,
            scope_key="1/" + m.op.app_id,
            kind="dependencies",
            sha256="d" * 64,
            platform="linux/amd64",
            state="verified",
            confirmed_at=m.clock["now"],
            metadata_={"input_key": KEY, "profile_id": "profile-a"},
        )
    )
    plan = await m.repo.save(
        RuntimeDependencyPlan(
            tenant_id=1,
            app_id=m.op.app_id,
            scope_key="1/" + m.op.app_id,
            operation_id="previous-operation",
            input_key=KEY,
            artifact_id=artifact.id,
            state="verified",
        )
    )
    return m, RuntimeDependencyService(m.repo, clock=lambda: m.clock["now"]), artifact, plan


async def test_selected_cache_is_recorded_in_operation_before_grant_can_download_it(dependencies):
    m, svc, artifact, _ = dependencies
    first = await create(m)
    from bisheng.app_runtime.domain.models.runtime_kubernetes import RuntimeMaterialDelegation

    before = await m.repo.get(RuntimeMaterialDelegation, first["delegation_id"])
    assert artifact.id not in before.allowed_artifacts
    result = await svc.resolve(m.op, KEY)
    persisted = await m.repo.get(RuntimeOperation, m.op.id)
    assert result["artifact_id"] == artifact.id
    assert persisted.payload["dependency_resolution"] == {
        "input_key": KEY,
        "artifact_id": artifact.id,
        "state": "verified",
    }
    second = await m.svc.create_delegation(
        MANAGER,
        {**m.body, "key_id": "second-fetch"},
    )
    after = await m.repo.get(RuntimeMaterialDelegation, second["delegation_id"])
    assert artifact.id in after.allowed_artifacts


async def test_selection_is_immutable_for_one_frozen_prepare_operation(dependencies):
    m, svc, _, _ = dependencies
    await svc.resolve(m.op, KEY)
    with pytest.raises(RuntimeConflict):
        await svc.resolve(m.op, "e" * 64)


@pytest.mark.parametrize("change", ["foreign-app", "wrong-profile", "wrong-platform", "not-verified"])
async def test_cache_selection_checks_owned_verified_profile_material(dependencies, change):
    m, svc, artifact, _ = dependencies
    if change == "foreign-app":
        artifact.app_id = "other-app"
    elif change == "wrong-profile":
        artifact.metadata_ = {"input_key": KEY, "profile_id": "other-profile"}
    elif change == "wrong-platform":
        artifact.platform = "linux/arm64"
    else:
        artifact.state = "uploading"
    await m.repo.save(artifact)
    with pytest.raises(RuntimeConflict):
        await svc.resolve(m.op, KEY)
    assert "dependency_resolution" not in (await m.repo.get(RuntimeOperation, m.op.id)).payload


@pytest.mark.parametrize("change", ["terminal", "expired", "cancelled"])
async def test_expired_prepare_cannot_select_or_confirm_material(dependencies, change):
    m, svc, artifact, _ = dependencies
    if change == "terminal":
        m.op.status = "completed"
    elif change == "expired":
        m.op.deadline = m.clock["now"] - timedelta(seconds=1)
    else:
        m.op.payload = {**m.op.payload, "cancel_requested": True}
    await m.repo.save(m.op)
    with pytest.raises(RuntimeConflict):
        await svc.resolve(m.op, KEY)
    with pytest.raises(RuntimeConflict):
        await svc.confirm(m.op, KEY, artifact.id)


async def test_confirmation_records_selected_material_and_repeated_result_is_stable(dependencies):
    m, svc, artifact, plan = dependencies
    plan.artifact_id = ""
    plan.state = "claimed"
    plan.operation_id = m.op.id
    await m.repo.save(plan)
    await svc.resolve(m.op, KEY)
    first = await svc.confirm(m.op, KEY, artifact.id)
    assert first == await svc.confirm(m.op, KEY, artifact.id)
    op = await m.repo.get(RuntimeOperation, m.op.id)
    assert op.payload["dependency_resolution"]["artifact_id"] == artifact.id
    assert (await svc.confirm(m.op, KEY, artifact.id, verified=True))["state"] == "verified"


async def test_forged_operation_payload_without_matching_plan_does_not_expand_grant(dependencies):
    m, _, artifact, _ = dependencies
    m.op.payload = {
        **m.op.payload,
        "dependency_resolution": {"input_key": "e" * 64, "artifact_id": artifact.id, "state": "verified"},
    }
    await m.repo.save(m.op)
    with pytest.raises(RuntimeConflict):
        await create(m)


async def test_identical_dependency_bytes_support_a_new_verified_resolution_alias(dependencies):
    from datetime import datetime
    from uuid import uuid4

    from bisheng.app_runtime.domain.services.runtime_artifact_service import RuntimeArtifactService
    from test.app_runtime.test_runtime_artifacts import MemoryObjects

    m, svc, artifact, _ = dependencies
    values = m.op.model_dump(exclude={"id", "create_time", "update_time"})
    values.update(
        id=uuid4().hex,
        idempotency_key="new-input",
        request_digest="f" * 64,
        payload={**m.op.payload},
        deadline=datetime.utcnow() + timedelta(hours=1),
    )
    op = await m.repo.save(RuntimeOperation(**values))
    key = "e" * 64
    await svc.resolve(op, key)
    upload = await RuntimeArtifactService(m.repo, MemoryObjects()).create_upload(
        op.id,
        kind="dependencies",
        sha256=artifact.sha256,
        size_bytes=artifact.size_bytes,
        platform=artifact.platform,
        metadata={"input_key": key, "profile_id": "profile-a"},
    )
    assert upload["artifact_id"] == artifact.id
    result = await svc.confirm(op, key, artifact.id, verified=True)
    assert result["artifact_id"] == artifact.id and result["state"] == "verified"
    assert (await svc.resolve(op, key))["artifact_id"] == artifact.id
