"""F118 prospective permissions must equal post-create target models."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.permission.application.control_state import RuntimeCatalogSnapshot, RuntimeModelSnapshot
from bisheng.permission.application.prospective_grant import ProspectiveGrantApplication
from bisheng.permission.application.runtime import F048PermissionRuntime
from bisheng.permission.domain.services.grant_service import GrantService
from bisheng.permission.domain.services.grant_source_service import GrantModelSnapshot
from bisheng.permission.domain.services.permission_action_service import PermissionActor


def runtime():
    current = RuntimeCatalogSnapshot(
        1,
        "r1",
        1,
        "a" * 64,
        "s1",
        "m1",
        "b" * 64,
        (
            RuntimeModelSnapshot(
                GrantModelSnapshot("owner", True, ("manage_permission",), 4, True), "Owner", "STANDARD", 1
            ),
            RuntimeModelSnapshot(
                GrantModelSnapshot(
                    "mixed", True, ("download",), 1, visibility_only_resource_types=("tool",), visibility_level=3
                ),
                "Mixed",
                "CUSTOM",
                1,
            ),
        ),
        action_resource_scopes=(("download", ("knowledge_file",)), ("manage_permission", ("tool", "knowledge_file"))),
    )
    result = object.__new__(F048PermissionRuntime)
    result._runtime_catalog = AsyncMock(return_value=current)
    result._grants = GrantService(source_service=object(), projection=object(), state=object())
    return result, current


@pytest.mark.parametrize("resource_type,level,pure", [("tool", 3, True), ("knowledge_file", 1, False)])
async def test_real_prospective_context_matches_post_create_target_snapshot(resource_type, level, pure):
    service, current = runtime()
    application = ProspectiveGrantApplication(runtime=service, subjects=SimpleNamespace())
    context = await application.get_context(
        actor=PermissionActor(user_id=42, current_tenant_id=101), tenant_id=101, resource_type=resource_type
    )
    mixed = next(row for row in context["grantable_models"] if row["key"] == "mixed")
    post_create = current.model_for_target(current.models[1].snapshot, resource_type=resource_type)
    assert mixed["level"] == post_create.derived_level == level
    assert mixed["visibility_only"] == post_create.visibility_only == pure
    _, snapshots = await service.prospective_owner_grantable_models(resource_type=resource_type)
    returned = next(row.snapshot for row in snapshots if row.snapshot.model_key == "mixed")
    assert returned == post_create
