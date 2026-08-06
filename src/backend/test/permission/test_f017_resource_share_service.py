"""F017 unit tests for the ResourceShareService permission boundary.

Mocks the permission application protocol and TenantDao. Business tests must
not mock or assert the underlying authorization backend client.

v2.6.0-beta2: business resources retired from SUPPORTED_SHAREABLE_TYPES.
Only ``llm_server`` retains the write path (F020); the legacy types remain in
``LEGACY_SHAREABLE_TYPES`` so the revoke script can clean them up without
re-enabling the write surface.

Covered behaviors:
- ``enable_sharing`` writes one shared_with tuple per active Child (llm_server)
- ``enable_sharing`` returns empty + does not call FGA when no active Children
- ``enable_sharing`` rejects legacy business types with ValueError
- ``disable_sharing`` accepts legacy types so cleanup can purge stale tuples
- ``distribute_to_child`` / ``revoke_from_child`` write / delete Tenant-level
  ``shared_to`` tuple with correct (user, relation, object)
- ``list_sharing_children`` returns the Child ids parsed from read_tuples
"""

from __future__ import annotations

from typing import List
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.permission import PermissionServiceUnavailableError
from bisheng.permission.application import (
    PermissionObject,
    PermissionRelation,
    PermissionSubject,
)
from bisheng.tenant.domain.services.resource_share_service import (
    LEGACY_SHAREABLE_TYPES,
    SUPPORTED_SHAREABLE_TYPES,
    ResourceShareService,
)

# ── Helpers ──────────────────────────────────────────────────────


def _make_permissions(subject_ids: tuple[str, ...] = ()):
    permissions = AsyncMock()
    permissions.list_subject_ids = AsyncMock(return_value=subject_ids)
    permissions.grant = AsyncMock(return_value=None)
    permissions.revoke = AsyncMock(return_value=None)
    return permissions


def _patch_permissions(permissions):
    return patch(
        "bisheng.tenant.domain.services.resource_share_service.get_permission_relation_api",
        AsyncMock(return_value=permissions),
    )


def _patch_children(child_ids: List[int]):
    return patch(
        "bisheng.tenant.domain.services.resource_share_service.TenantDao.aget_children_ids_active",
        AsyncMock(return_value=child_ids),
    )


# ── enable_sharing ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_enable_sharing_writes_shared_with_tuples_per_child():
    permissions = _make_permissions()
    with _patch_permissions(permissions), _patch_children([5, 7, 9]):
        result = await ResourceShareService.enable_sharing(
            "llm_server",
            "42",
            root_tenant_id=1,
        )

    assert result == [5, 7, 9]
    grants = permissions.grant.await_args.args[0]
    assert grants == tuple(
        PermissionRelation(
            subject=PermissionSubject("tenant", str(child_id)),
            relation="shared_with",
            resource=PermissionObject("llm_server", "42"),
        )
        for child_id in (5, 7, 9)
    )


@pytest.mark.asyncio
async def test_enable_sharing_no_active_children_returns_empty():
    """No FGA write when there are no active Children; return empty list."""
    permissions = _make_permissions()
    with _patch_permissions(permissions), _patch_children([]):
        result = await ResourceShareService.enable_sharing(
            "llm_server",
            "abc-123",
            root_tenant_id=1,
        )
    assert result == []
    permissions.grant.assert_not_awaited()


@pytest.mark.parametrize(
    "retired_type",
    [
        "knowledge_space",
        "workflow",
        "assistant",
        "channel",
        "tool",
    ],
)
@pytest.mark.asyncio
async def test_enable_sharing_rejects_retired_business_types(retired_type):
    """v2.6.0-beta2: enable_sharing must reject business types so callers
    can't re-introduce default Root→Child fan-out by mistake."""
    with pytest.raises(ValueError, match="Unsupported resource type"):
        await ResourceShareService.enable_sharing(retired_type, "1")


# ── disable_sharing ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_disable_sharing_deletes_only_shared_with_tenant_tuples():
    """disable_sharing must ignore non-shared_with relations and non-tenant users."""
    permissions = _make_permissions(("5", "7"))
    with _patch_permissions(permissions):
        result = await ResourceShareService.disable_sharing("assistant", "x")

    assert result == [5, 7]
    permissions.list_subject_ids.assert_awaited_once_with(
        resource=PermissionObject("assistant", "x"),
        relation="shared_with",
        subject_type="tenant",
    )
    assert {relation.subject.subject_id for relation in permissions.revoke.await_args.args[0]} == {"5", "7"}


@pytest.mark.asyncio
async def test_disable_sharing_no_shared_tuples_is_noop():
    """When object has no shared_with tuples, no delete call is made."""
    permissions = _make_permissions()
    with _patch_permissions(permissions):
        result = await ResourceShareService.disable_sharing("channel", "c1")
    assert result == []
    permissions.revoke.assert_not_awaited()


# ── distribute_to_child / revoke_from_child ──────────────────────


@pytest.mark.asyncio
async def test_distribute_to_child_writes_shared_to_tuple():
    """Tenant-level shared_to tuple: user=tenant:{child}, relation=shared_to, object=tenant:{root}."""
    permissions = _make_permissions()
    with _patch_permissions(permissions):
        await ResourceShareService.distribute_to_child(child_id=5, root_tenant_id=1)
    permissions.grant.assert_awaited_once_with(
        (
            PermissionRelation(
                subject=PermissionSubject("tenant", "5"),
                relation="shared_to",
                resource=PermissionObject("tenant", "1"),
            ),
        )
    )


@pytest.mark.asyncio
async def test_revoke_from_child_deletes_shared_to_tuple():
    """Symmetric delete of the shared_to tuple."""
    permissions = _make_permissions()
    with _patch_permissions(permissions):
        await ResourceShareService.revoke_from_child(child_id=5, root_tenant_id=1)
    permissions.revoke.assert_awaited_once_with(
        (
            PermissionRelation(
                subject=PermissionSubject("tenant", "5"),
                relation="shared_to",
                resource=PermissionObject("tenant", "1"),
            ),
        )
    )


# ── list_sharing_children ────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_sharing_children_parses_child_ids():
    """Return child ids parsed from shared_with tuples; ignore other relations."""
    permissions = _make_permissions(("5", "7"))
    with _patch_permissions(permissions):
        result = await ResourceShareService.list_sharing_children("tool", "t1")
    assert sorted(result) == [5, 7]


# ── Validation ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unsupported_resource_type_raises_on_enable():
    with pytest.raises(ValueError, match="Unsupported resource type"):
        await ResourceShareService.enable_sharing("dashboard", "1")


@pytest.mark.asyncio
async def test_unsupported_resource_type_raises_on_disable():
    with pytest.raises(ValueError, match="Unsupported resource type"):
        await ResourceShareService.disable_sharing("dashboard", "1")


def test_supported_types_only_llm_server():
    """v2.6.0-beta2: business resources retired; only llm_server writes tuples."""
    assert SUPPORTED_SHAREABLE_TYPES == {"llm_server"}


def test_legacy_types_cover_all_historic_targets():
    """LEGACY must include every type the revoke script needs to clean up."""
    assert LEGACY_SHAREABLE_TYPES == {
        "knowledge_space",
        "workflow",
        "assistant",
        "channel",
        "tool",
        "llm_server",
    }


@pytest.mark.parametrize(
    "retired_type",
    [
        "knowledge_space",
        "workflow",
        "assistant",
        "channel",
        "tool",
    ],
)
@pytest.mark.asyncio
async def test_disable_sharing_accepts_retired_types_for_cleanup(retired_type):
    """Cleanup path must reach the historic types even though their write
    surface is retired — otherwise the revoke script can't purge stale tuples.
    """
    permissions = _make_permissions()
    with _patch_permissions(permissions):
        result = await ResourceShareService.disable_sharing(retired_type, "1")
    assert result == []
    permissions.list_subject_ids.assert_awaited_once_with(
        resource=PermissionObject(retired_type, "1"),
        relation="shared_with",
        subject_type="tenant",
    )


# ── OpenFGA-disabled degradation ─────────────────────────────────


@pytest.mark.asyncio
async def test_enable_sharing_fails_when_permission_service_is_unavailable():
    with (
        patch(
            "bisheng.tenant.domain.services.resource_share_service.get_permission_relation_api",
            AsyncMock(side_effect=PermissionServiceUnavailableError()),
        ),
        pytest.raises(PermissionServiceUnavailableError),
    ):
        await ResourceShareService.enable_sharing("llm_server", "1")


@pytest.mark.asyncio
async def test_distribute_to_child_fails_when_permission_service_is_unavailable():
    with (
        patch(
            "bisheng.tenant.domain.services.resource_share_service.get_permission_relation_api",
            AsyncMock(side_effect=PermissionServiceUnavailableError()),
        ),
        pytest.raises(PermissionServiceUnavailableError),
    ):
        await ResourceShareService.distribute_to_child(child_id=5)


@pytest.mark.asyncio
async def test_enable_sharing_uses_permission_application_protocol():
    permissions = _make_permissions()
    with _patch_permissions(permissions) as get_permissions, _patch_children([5]):
        result = await ResourceShareService.enable_sharing("llm_server", "1")

    assert result == [5]
    get_permissions.assert_awaited_once()
    permissions.grant.assert_awaited_once()
