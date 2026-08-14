"""F048 concrete-action decision facade contracts.

覆盖 AC: AC-28, AC-29, AC-30, AC-31, AC-32, AC-33, AC-34, AC-35,
AC-63, AC-65, AC-69, AC-155, AC-160, AC-161, AC-162, AC-163,
AC-168, AC-169, AC-170, AC-171
"""

from __future__ import annotations

import pytest

from bisheng.common.errcode.permission import (
    InvalidCatalogActionError,
    PermissionEnumerationIncompleteError,
    PermissionFGAUnavailableError,
    PermissionProjectionFailedError,
    PermissionPublishNotReadyError,
)
from bisheng.permission.domain.schemas import (
    VerifiedPermissionTarget,
    VisibilityEnumerationStatus,
)
from bisheng.permission.domain.services.permission_service import (
    F048PermissionService,
    PermissionActor,
)


class FakeCatalog:
    def __init__(self) -> None:
        self.available = {
            ("workflow", "edit"),
            ("workflow", "delete"),
            ("knowledge_file", "download"),
        }
        self.ready = True
        self.calls = []

    async def ensure_runtime_ready(self) -> None:
        self.calls.append("ready")
        if not self.ready:
            raise PermissionPublishNotReadyError()

    async def is_action_effective(
        self,
        resource_type: str,
        action: str,
    ) -> bool:
        self.calls.append(("action", resource_type, action))
        return (resource_type, action) in self.available


class FakeScopeFence:
    def __init__(self) -> None:
        self.readable = True
        self.calls = []

    async def ensure_readable(self, target: VerifiedPermissionTarget) -> None:
        self.calls.append(target.resource_id)
        if not self.readable:
            raise PermissionPublishNotReadyError()


class FakeMarker:
    def __init__(self) -> None:
        self.higher = False
        self.fail = False
        self.calls = []

    async def consistency_for(
        self,
        *,
        tenant_id: int,
        resource_type: str,
        resource_id: str | None,
    ) -> str | None:
        self.calls.append((tenant_id, resource_type, resource_id))
        if self.fail:
            raise RuntimeError("redis unavailable")
        return "HIGHER_CONSISTENCY" if self.higher else None


class FakeFGA:
    def __init__(self) -> None:
        self.allowed = False
        self.fail = False
        self.checks = []
        self.batches = []
        self.lists = []
        self.objects = []

    async def check(self, *, user, relation, object, consistency=None):
        self.checks.append((user, relation, object, consistency))
        if self.fail:
            raise RuntimeError("openfga down")
        if relation == "visible" and self.objects:
            return object in self.objects
        return self.allowed

    async def batch_check(self, checks, consistency=None):
        self.batches.append((checks, consistency))
        if self.fail:
            raise RuntimeError("openfga down")
        return [
            row["object"] in self.objects
            if row["relation"] == "visible" and self.objects
            else row["object"].endswith(":allow")
            for row in checks
        ]

    async def list_objects(
        self,
        *,
        user,
        relation,
        type,
        consistency=None,
    ):
        self.lists.append((user, relation, type, consistency))
        if self.fail:
            raise RuntimeError("openfga down")
        return self.objects

    async def stream_list_objects(
        self,
        *,
        user,
        relation,
        type,
        consistency=None,
    ):
        self.lists.append((user, relation, type, consistency))
        if self.fail:
            raise RuntimeError("openfga stream failed")
        return tuple(self.objects)


class FakeListPolicy:
    def __init__(self) -> None:
        self.allowed = {("knowledge_file", "download")}

    async def allows(
        self,
        resource_type: str,
        action: str,
        max_results: int,
    ) -> bool:
        return (resource_type, action) in self.allowed and max_results <= 100


class FakeEvents:
    def __init__(self) -> None:
        self.rows = []

    async def emit(self, name: str, fields: dict) -> None:
        self.rows.append((name, fields))


def _target(
    resource_id: str = "42",
    *,
    tenant_id: int = 7,
    resource_type: str = "workflow",
) -> VerifiedPermissionTarget:
    return VerifiedPermissionTarget.from_business_service(
        tenant_id=tenant_id,
        resource_type=resource_type,
        resource_id=resource_id,
        resource_version=3,
        context_version="ctx-3",
    )


def _actor(
    *,
    tenant_id: int = 7,
    super_admin: bool = False,
    tenant_admin_ids: frozenset[int] = frozenset(),
) -> PermissionActor:
    return PermissionActor(
        user_id=100,
        current_tenant_id=tenant_id,
        super_admin=super_admin,
        tenant_admin_tenant_ids=tenant_admin_ids,
    )


def _service():
    catalog = FakeCatalog()
    fence = FakeScopeFence()
    marker = FakeMarker()
    fga = FakeFGA()
    list_policy = FakeListPolicy()
    events = FakeEvents()
    service = F048PermissionService(
        catalog=catalog,
        scope_fence=fence,
        marker=marker,
        fga=fga,
        list_policy=list_policy,
        events=events,
    )
    return (
        service,
        catalog,
        fence,
        marker,
        fga,
        list_policy,
        events,
    )


@pytest.mark.asyncio
async def test_c4_shortcuts_and_tenant_gate_run_before_openfga() -> None:
    service, catalog, fence, _, fga, _, events = _service()
    assert await service.check_action(
        _actor(super_admin=True),
        _target(),
        "edit",
    )
    assert catalog.calls == []
    assert fence.calls == []
    assert fga.checks == []

    assert await service.check_action(
        _actor(tenant_admin_ids=frozenset({7})),
        _target(),
        "edit",
    )
    assert fga.checks == []

    assert not await service.check_action(
        _actor(tenant_id=8),
        _target(tenant_id=7),
        "edit",
    )
    assert fga.checks == []
    assert events.rows[-1][1]["reason"] == "TENANT_MISMATCH"


@pytest.mark.asyncio
async def test_concrete_action_relation_is_final_and_visible_is_separate() -> None:
    service, _, _, _, fga, _, _ = _service()
    fga.allowed = False
    assert not await service.check_action(_actor(), _target(), "edit")
    assert fga.checks[-1][1] == "can_edit"
    with pytest.raises(InvalidCatalogActionError):
        await service.check_action(_actor(), _target(), "visible")

    fga.allowed = True
    assert await service.check_visible(_actor(), _target())
    assert fga.checks[-1][1] == "visible"


@pytest.mark.asyncio
async def test_unknown_or_wrong_scope_action_is_rejected() -> None:
    service, _, _, _, fga, _, _ = _service()
    with pytest.raises(InvalidCatalogActionError):
        await service.check_action(_actor(), _target(), "not_registered")
    with pytest.raises(InvalidCatalogActionError):
        await service.check_action(
            _actor(),
            _target(resource_type="workflow"),
            "download",
        )
    assert fga.checks == []


@pytest.mark.asyncio
async def test_openfga_failure_is_explicit_and_has_no_fallback() -> None:
    service, _, _, _, fga, _, events = _service()
    fga.fail = True
    with pytest.raises(PermissionFGAUnavailableError):
        await service.check_action(_actor(), _target(), "edit")
    assert events.rows[-1][1]["outcome"] == "ERROR"


@pytest.mark.asyncio
async def test_recent_marker_selects_higher_consistency_and_failure_is_safe() -> None:
    service, _, _, marker, fga, _, _ = _service()
    marker.higher = True
    await service.check_action(_actor(), _target(), "edit")
    assert fga.checks[-1][-1] == "HIGHER_CONSISTENCY"

    marker.higher = False
    marker.fail = True
    await service.check_action(_actor(), _target(), "edit")
    assert fga.checks[-1][-1] == "HIGHER_CONSISTENCY"


@pytest.mark.asyncio
async def test_batch_check_is_bounded_and_preserves_short_circuits() -> None:
    service, _, _, _, fga, _, _ = _service()
    targets = (
        _target("allow"),
        _target("deny"),
        _target("cross", tenant_id=8),
    )
    results = await service.batch_check_actions(_actor(), targets, "edit")
    assert results == (True, False, False)
    checks, _ = fga.batches[0]
    assert len(checks) == 2
    assert all(row["relation"] == "can_edit" for row in checks)

    with pytest.raises(ValueError, match="100"):
        await service.batch_check_actions(
            _actor(),
            tuple(_target(str(index)) for index in range(101)),
            "edit",
        )


@pytest.mark.asyncio
async def test_visible_batch_uses_one_openfga_batch_without_action_alias() -> None:
    service, _, _, _, fga, _, _ = _service()
    results = await service.batch_check_visible(
        _actor(),
        (
            _target("allow"),
            _target("deny"),
            _target("cross", tenant_id=8),
        ),
    )

    assert results == (True, False, False)
    checks, _ = fga.batches[0]
    assert len(checks) == 2
    assert all(row["relation"] == "visible" for row in checks)


@pytest.mark.asyncio
async def test_visible_checks_never_expand_super_or_tenant_admin_scope() -> None:
    service, _, _, _, fga, _, _ = _service()
    fga.allowed = False

    assert not await service.check_visible(_actor(super_admin=True), _target())
    assert not await service.check_visible(
        _actor(tenant_admin_ids=frozenset({7})),
        _target(),
    )
    assert [row[1] for row in fga.checks] == ["visible", "visible"]

    results = await service.batch_check_visible(
        _actor(super_admin=True),
        (_target("allow"), _target("deny")),
    )
    assert results == (True, False)
    assert len(fga.batches) == 1


@pytest.mark.asyncio
async def test_complete_visible_enumeration_is_deduplicated_and_consistent() -> None:
    service, _, _, marker, fga, _, _ = _service()
    marker.higher = True
    fga.objects = ["workflow:allow", "workflow:allow", "workflow:second"]

    result = await service.list_visible_objects(
        _actor(super_admin=True),
        resource_type="workflow",
        max_results=5_000,
    )

    assert result.status is VisibilityEnumerationStatus.NORMAL
    assert result.object_ids == ("allow", "second")
    assert fga.lists[-1] == (
        "user:100",
        "visible",
        "workflow",
        "HIGHER_CONSISTENCY",
    )
    candidate_ids = ("allow", "second", "deny")
    single = tuple(
        [await service.check_visible(_actor(), _target(resource_id)) for resource_id in candidate_ids]
    )
    batch = await service.batch_check_visible(
        _actor(),
        tuple(_target(resource_id) for resource_id in candidate_ids),
    )
    assert single == batch == (True, True, False)
    assert tuple(resource_id for resource_id, allowed in zip(candidate_ids, batch, strict=True) if allowed) == (
        result.object_ids
    )


@pytest.mark.asyncio
async def test_visible_enumeration_capacity_error_and_no_sql_allow_fallback() -> None:
    service, _, _, _, fga, _, _ = _service()
    fga.objects = [f"workflow:{index}" for index in range(5_000)]
    accepted = await service.list_visible_objects(
        _actor(),
        resource_type="workflow",
        max_results=5_000,
    )
    assert len(accepted.object_ids) == 5_000

    fga.objects.append("workflow:5000")
    with pytest.raises(PermissionEnumerationIncompleteError):
        await service.list_visible_objects(
            _actor(),
            resource_type="workflow",
            max_results=5_000,
        )

    fga.objects = []
    denied = await service.list_visible_objects(
        _actor(),
        resource_type="workflow",
        max_results=5_000,
    )
    assert denied.object_ids == ()


@pytest.mark.asyncio
async def test_visible_enumeration_tenant_fence_and_stream_error_are_explicit() -> None:
    service, _, _, _, fga, _, _ = _service()
    with pytest.raises(PermissionEnumerationIncompleteError):
        await service.list_visible_objects(
            _actor(tenant_id=0),
            resource_type="workflow",
            max_results=5_000,
        )
    assert fga.lists == []

    fga.fail = True
    with pytest.raises(PermissionEnumerationIncompleteError):
        await service.list_visible_objects(
            _actor(),
            resource_type="workflow",
            max_results=5_000,
        )


@pytest.mark.asyncio
async def test_list_objects_is_allowlisted_bounded_and_never_generic_paging() -> None:
    service, _, _, _, fga, list_policy, _ = _service()
    fga.objects = ["knowledge_file:1", "knowledge_file:2"]
    assert await service.list_action_objects(
        _actor(),
        resource_type="knowledge_file",
        action="download",
        max_results=100,
    ) == ("1", "2")
    assert fga.lists[-1][1] == "can_download"

    with pytest.raises(PermissionPublishNotReadyError):
        await service.list_action_objects(
            _actor(),
            resource_type="workflow",
            action="edit",
            max_results=100,
        )
    list_policy.allowed.add(("workflow", "edit"))
    fga.objects = [f"workflow:{index}" for index in range(101)]
    with pytest.raises(PermissionProjectionFailedError):
        await service.list_action_objects(
            _actor(),
            resource_type="workflow",
            action="edit",
            max_results=100,
        )
