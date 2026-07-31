"""F048 exact-ID cross-tenant shared-resource boundary."""

from __future__ import annotations

import pytest

from bisheng.common.errcode.permission import (
    InvalidCatalogActionError,
    PermissionFGAUnavailableError,
    PermissionInvalidResourceError,
)
from bisheng.core.context.tenant import is_tenant_filter_bypassed
from bisheng.permission.domain.services.permission_action_service import (
    PermissionActor,
)
from bisheng.tenant.domain.repositories.resource_share_repository import (
    SharedResourceRecord,
    SharedResourceRepository,
)
from bisheng.tenant.domain.services.resource_share_service import (
    ResourceShareService,
)


class _Loader:
    def __init__(
        self,
        rows: tuple[SharedResourceRecord, ...],
        events: list[str] | None = None,
    ) -> None:
        self.rows = rows
        self.events = events if events is not None else []
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    async def load_by_ids(self, resource_type, resource_ids):
        assert is_tenant_filter_bypassed()
        self.events.append("load")
        self.calls.append((resource_type, resource_ids))
        return self.rows


class _SystemPermission:
    def __init__(
        self,
        *,
        allowed: bool = True,
        error: Exception | None = None,
        events: list[str] | None = None,
    ) -> None:
        self.allowed = allowed
        self.error = error
        self.events = events if events is not None else []
        self.calls: list[tuple[object, str, str, str]] = []

    async def check_system_action(
        self,
        actor,
        resource_type,
        resource_id,
        action,
    ):
        self.events.append("system-check")
        self.calls.append((actor, resource_type, resource_id, action))
        if self.error:
            raise self.error
        return self.allowed


class _Topology:
    def __init__(self, valid: bool = True) -> None:
        self.valid = valid
        self.calls: list[tuple[int, int]] = []

    async def is_root_to_child(self, owner_tenant_id, child_tenant_id):
        self.calls.append((owner_tenant_id, child_tenant_id))
        return self.valid


def _actor() -> PermissionActor:
    return PermissionActor(user_id=7, current_tenant_id=5)


def _record(
    *,
    resource_type: str = "knowledge_library",
    resource_id: str = "lib-1",
    owner_tenant_id: int = 1,
    status: str = "ACTIVE",
    shareable: bool = True,
) -> SharedResourceRecord:
    return SharedResourceRecord(
        owner_tenant_id=owner_tenant_id,
        resource_type=resource_type,
        resource_id=resource_id,
        status=status,
        shareable=shareable,
        permission_version=3,
        context_version=f"{resource_type}-{resource_id}-v3",
    )


@pytest.mark.asyncio
async def test_system_relation_is_checked_before_exact_id_cross_tenant_load() -> None:
    events: list[str] = []
    loader = _Loader((_record(),), events)
    service = ResourceShareService(
        repository=SharedResourceRepository(loader),
        system_permission=_SystemPermission(events=events),
        topology=_Topology(),
    )

    target = await service.resolve_shared_target(
        actor=_actor(),
        resource_type="knowledge_library",
        resource_id="lib-1",
        action="use",
    )

    assert events == ["system-check", "load"]
    assert loader.calls == [("knowledge_library", ("lib-1",))]
    assert target.tenant_id == 1
    assert target.resource_id == "lib-1"


@pytest.mark.asyncio
async def test_repository_discards_rows_outside_the_exact_authorized_id_set() -> None:
    loader = _Loader((_record(), _record(resource_id="lib-secret")))
    repository = SharedResourceRepository(loader)

    rows = await repository.get_authorized_by_ids(
        owner_tenant_id=1,
        resource_type="knowledge_library",
        resource_ids=("lib-1",),
    )

    assert tuple(row.resource_id for row in rows) == ("lib-1",)
    assert loader.calls == [("knowledge_library", ("lib-1",))]


@pytest.mark.asyncio
async def test_unshared_id_never_triggers_cross_tenant_business_load() -> None:
    loader = _Loader((_record(),))
    service = ResourceShareService(
        repository=SharedResourceRepository(loader),
        system_permission=_SystemPermission(allowed=False),
        topology=_Topology(),
    )

    with pytest.raises(PermissionInvalidResourceError):
        await service.resolve_shared_target(
            actor=_actor(),
            resource_type="knowledge_library",
            resource_id="lib-1",
            action="visible",
        )
    assert loader.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ("edit", "delete", "manage_permission"))
async def test_shared_resource_rejects_write_actions(action) -> None:
    service = ResourceShareService(
        repository=SharedResourceRepository(_Loader((_record(),))),
        system_permission=_SystemPermission(),
        topology=_Topology(),
    )

    with pytest.raises(InvalidCatalogActionError):
        await service.resolve_shared_target(
            actor=_actor(),
            resource_type="knowledge_library",
            resource_id="lib-1",
            action=action,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("record", "topology_valid"),
    (
        (_record(status="INACTIVE"), True),
        (_record(shareable=False), True),
        (_record(owner_tenant_id=5), True),
        (_record(owner_tenant_id=2), False),
    ),
)
async def test_inactive_wrong_owner_or_unshareable_rows_fail_closed(
    record,
    topology_valid,
) -> None:
    service = ResourceShareService(
        repository=SharedResourceRepository(_Loader((record,))),
        system_permission=_SystemPermission(),
        topology=_Topology(topology_valid),
    )

    with pytest.raises(PermissionInvalidResourceError):
        await service.resolve_shared_target(
            actor=_actor(),
            resource_type="knowledge_library",
            resource_id="lib-1",
            action="visible",
        )


@pytest.mark.asyncio
async def test_openfga_failure_is_not_converted_to_business_lookup_or_allow() -> None:
    loader = _Loader((_record(),))
    service = ResourceShareService(
        repository=SharedResourceRepository(loader),
        system_permission=_SystemPermission(error=PermissionFGAUnavailableError()),
        topology=_Topology(),
    )

    with pytest.raises(PermissionFGAUnavailableError):
        await service.resolve_shared_target(
            actor=_actor(),
            resource_type="knowledge_library",
            resource_id="lib-1",
            action="visible",
        )
    assert loader.calls == []
