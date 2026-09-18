from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.permission.domain.services.fine_grained_permission_service import (
    FineGrainedPermissionService,
)
from bisheng.permission.domain.services.permission_service import PermissionService


@pytest.mark.parametrize("resource_type", ["knowledge_space", "folder", "knowledge_file"])
async def test_empty_custom_model_does_not_inherit_viewer_permissions(resource_type):
    user = SimpleNamespace(user_id=7, is_admin=lambda: False)
    models = {"custom_empty": {
        "id": "custom_empty", "relation": "viewer", "is_system": False,
        "permissions": [], "permissions_explicit": True,
    }}
    binding = {
        "resource_type": resource_type, "resource_id": "9", "subject_type": "user",
        "subject_id": 7, "relation": "viewer", "model_id": "custom_empty",
    }
    fga = SimpleNamespace(read_tuples=AsyncMock(return_value=[{
        "user": "user:7", "relation": "viewer", "object": f"{resource_type}:9",
    }]))
    with (
        patch.object(PermissionService, "_get_fga", return_value=fga),
        patch.object(PermissionService, "get_implicit_permission_level", AsyncMock(return_value=None)),
        patch.object(PermissionService, "get_permission_level", AsyncMock(return_value="can_read")) as fallback,
        patch.object(FineGrainedPermissionService, "_public_knowledge_space_viewer_permission_ids",
                     AsyncMock(return_value=set())),
    ):
        permissions = await FineGrainedPermissionService.get_effective_permission_ids_async(
            user, resource_type, "9", models=models, bindings=[binding],
            binding_department_paths={}, user_subject_strings={"user:7"},
            lineage=[(resource_type, "9")],
        )
    assert permissions == set()
    fallback.assert_not_awaited()
