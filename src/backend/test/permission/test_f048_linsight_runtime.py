"""F048 Linsight tenant, runtime-pin, and durable-owner contracts."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from bisheng.core.context.tenant import (
    current_tenant_id,
    get_current_tenant_id,
)
from bisheng.linsight.domain import task_exec
from bisheng.linsight.domain.models.linsight_skill import LinsightSkill
from bisheng.linsight.domain.schemas.skill_schema import SkillCreateForm
from bisheng.linsight.domain.services import skill_service as skill_module
from bisheng.linsight.domain.services.skill_service import SkillService
from bisheng.linsight.domain.services.skill_store import SkillStore
from bisheng.linsight.worker import encode_queue_item, parse_queue_item


class _RuntimeManager:
    def __init__(self, *, role: str = "linsight", healthy: bool = True):
        self.role = role
        self.healthy = healthy
        self.initialized = 0
        self.heartbeats = 0

    async def async_get_instance(self):
        self.initialized += 1
        return object()

    async def heartbeat(self):
        self.heartbeats += 1
        return self.healthy

    def readiness(self):
        return {
            "ready": True,
            "store_id": "store-live",
            "model_id": "model-f048",
            "model_checksum": "a" * 64,
            "catalog_release_id": 11,
            "catalog_checksum": "b" * 64,
            "instance_role": self.role,
        }


class _SkillDao:
    row: LinsightSkill | None = None

    @classmethod
    async def get_by_name(cls, name):
        if cls.row and cls.row.name == name:
            return cls.row
        return None

    @classmethod
    async def get_by_display_name(cls, display_name):
        if cls.row and cls.row.display_name == display_name:
            return cls.row
        return None

    @classmethod
    async def create(cls, skill):
        skill.id = 41
        cls.row = skill
        return skill


class _OwnerProjection:
    def __init__(self, error: Exception | None = None):
        self.calls = []
        self.error = error

    async def authorize_created(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return {"status": "FINALIZED"}


def _skill_form() -> SkillCreateForm:
    return SkillCreateForm(
        name="runtime-audit",
        display_name="Runtime Audit",
        description="Verify the Linsight permission runtime.",
        content="# Runtime Audit",
    )


@pytest.mark.asyncio
async def test_linsight_requires_complete_single_model_runtime_pin() -> None:
    manager = _RuntimeManager()

    readiness = await task_exec.ensure_linsight_permission_runtime(manager)

    assert readiness["store_id"] == "store-live"
    assert readiness["model_id"] == "model-f048"
    assert manager.initialized == manager.heartbeats == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "manager",
    (
        _RuntimeManager(role="api"),
        _RuntimeManager(healthy=False),
    ),
)
async def test_linsight_rejects_old_role_or_unhealthy_runtime(manager) -> None:
    with pytest.raises(RuntimeError, match="linsight F048 OpenFGA runtime"):
        await task_exec.ensure_linsight_permission_runtime(manager)


@pytest.mark.asyncio
async def test_task_payload_tenant_is_verified_and_context_is_reset(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        task_exec.LinsightSessionVersionDao,
        "get_by_id",
        classmethod(lambda cls, session_version_id: _async_value(SimpleNamespace(id=session_version_id, tenant_id=7))),
    )
    workflow = task_exec.LinsightWorkflowTask()

    token = await workflow._restore_tenant_context(
        "session-1",
        task_tenant_id=7,
    )
    try:
        assert get_current_tenant_id() == 7
    finally:
        current_tenant_id.reset(token)

    assert get_current_tenant_id() is None


def test_queue_payload_carries_explicit_tenant() -> None:
    payload = encode_queue_item(
        "session-1",
        resume=True,
        tenant_id=7,
    )

    assert parse_queue_item(payload)["tenant_id"] == 7


@pytest.mark.asyncio
@pytest.mark.parametrize("task_tenant_id", (None, 0, -1, True, "bad", 8))
async def test_task_payload_missing_invalid_or_mismatched_tenant_fails_closed(
    monkeypatch,
    task_tenant_id,
) -> None:
    monkeypatch.setattr(
        task_exec.LinsightSessionVersionDao,
        "get_by_id",
        classmethod(lambda cls, session_version_id: _async_value(SimpleNamespace(id=session_version_id, tenant_id=7))),
    )

    with pytest.raises(task_exec.TaskExecutionError, match="tenant"):
        await task_exec.LinsightWorkflowTask()._restore_tenant_context(
            "session-1",
            task_tenant_id=task_tenant_id,
        )
    assert get_current_tenant_id() is None


@pytest.mark.asyncio
async def test_skill_creation_waits_for_durable_owner_projection(
    tmp_path,
    monkeypatch,
) -> None:
    _SkillDao.row = None
    monkeypatch.setattr(skill_module, "LinsightSkillDao", _SkillDao)
    owner = _OwnerProjection()
    service = SkillService(
        store=SkillStore(root=tmp_path),
        owner_projection=owner,
    )

    detail = await service.create_from_form(7, 21, _skill_form())

    assert detail.name == "runtime-audit"
    assert owner.calls == [
        {
            "tenant_id": 7,
            "resource_type": "linsight_skill",
            "resource_id": "41",
            "owner_user_id": 21,
            "resource_version": 0,
            "context_version": "linsight_skill:41:v0",
            "idempotency_key": "linsight_skill:create:7:41",
        }
    ]


@pytest.mark.asyncio
async def test_skill_owner_projection_failure_is_not_best_effort(
    tmp_path,
    monkeypatch,
) -> None:
    _SkillDao.row = None
    monkeypatch.setattr(skill_module, "LinsightSkillDao", _SkillDao)
    service = SkillService(
        store=SkillStore(root=tmp_path),
        owner_projection=_OwnerProjection(RuntimeError("projection failed")),
    )

    with pytest.raises(RuntimeError, match="projection failed"):
        await service.create_from_form(7, 21, _skill_form())


def test_linsight_runtime_has_no_legacy_owner_tuple_fallback() -> None:
    source = Path(skill_module.__file__).read_text(encoding="utf-8")
    assert "PermissionService.authorize" not in source
    assert 'relation="owner"' not in source
    assert "best-effort owner tuple" not in source


async def _async_value(value):
    return value
