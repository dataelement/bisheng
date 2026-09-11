from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bisheng.permission.application.resource_api import F048ResourcePermissionApi
from bisheng.permission.domain.models import (
    PermissionGrant,
    PermissionGrantAssignee,
    ResourcePermissionMode,
)
from bisheng.permission.domain.repositories.grant_repository import (
    GrantRepository,
    ResourcePermissionModeRepository,
)


class Subjects:
    async def resource_display_names(self, resources):
        return {resource: f"name-{resource[1]}" for resource in resources}


async def test_subject_grants_are_aggregated_with_resource_and_model_names(monkeypatch):
    granted_at = datetime(2026, 9, 1, 10, 22)
    assignee = PermissionGrantAssignee(
        id=31,
        tenant_id=1,
        grant_id=21,
        subject_type="service_account",
        subject_id="7",
        source_type="DIRECT",
        source_ref="admin",
        source_locator="admin",
        source_fingerprint="a" * 64,
        projected_subject="service_account:7",
        state="ACTIVE",
        version=2,
        create_time=granted_at,
    )
    grant = PermissionGrant(
        id=21,
        tenant_id=1,
        resource_type="knowledge_space",
        resource_id="9",
        model_key="manager",
        state="ACTIVE",
    )

    async def rows(_self, *, tenant_id, subject_type, subject_id):
        assert tenant_id == 1
        assert (subject_type, subject_id) == ("service_account", "7")
        return [(assignee, grant)]

    monkeypatch.setattr(GrantRepository, "alist_active_subject_grants", rows)
    runtime = SimpleNamespace(
        current_catalog=lambda: _catalog(),
    )
    api = F048ResourcePermissionApi(
        resources=SimpleNamespace(),
        runtime=runtime,
        subjects=Subjects(),
    )

    result = await api.list_service_account_grants(tenant_id=1, service_account_id=7)

    assert result == [{
        "resource_type": "knowledge_space",
        "resource_id": "9",
        "resource_name": "name-9",
        "model_key": "manager",
        "model_name": "Manager",
        "assignee_id": "31",
        "assignee_version": 2,
        "source_type": "DIRECT",
        "granted_at": granted_at,
        "protected": False,
        "editable": True,
    }]


async def _catalog():
    return SimpleNamespace(models=[SimpleNamespace(snapshot=SimpleNamespace(model_key="manager"), name="Manager")])


async def test_resource_candidates_exclude_children_and_support_name_search(monkeypatch):
    async def rows(_self, *, tenant_id, resource_type, limit=500):
        assert tenant_id == 1
        assert resource_type is None
        assert limit == 500
        return [
            ResourcePermissionMode(
                tenant_id=1,
                resource_type="knowledge_space",
                resource_id="9",
                mode="CUSTOM",
                version=3,
                projection_state="CURRENT",
            ),
            ResourcePermissionMode(
                tenant_id=1,
                resource_type="folder",
                resource_id="10",
                mode="INHERIT",
                version=1,
                projection_state="CURRENT",
            ),
        ]

    monkeypatch.setattr(ResourcePermissionModeRepository, "alist_current_resources", rows)
    api = F048ResourcePermissionApi(
        resources=SimpleNamespace(),
        runtime=SimpleNamespace(),
        subjects=Subjects(),
    )

    result = await api.list_grantable_resources(
        tenant_id=1,
        resource_type=None,
        keyword="name-9",
    )

    assert result == [{
        "resource_type": "knowledge_space",
        "resource_id": "9",
        "resource_name": "name-9",
        "mode": "CUSTOM",
        "resource_version": 3,
    }]


async def test_service_account_delete_revokes_all_grants_in_bounded_batches(monkeypatch):
    api = F048ResourcePermissionApi(
        resources=SimpleNamespace(),
        runtime=SimpleNamespace(),
        subjects=Subjects(),
    )
    grants = [
        {
            "resource_type": "knowledge_space",
            "resource_id": "9",
            "assignee_id": str(index + 1),
            "assignee_version": 2,
        }
        for index in range(51)
    ]
    list_grants = AsyncMock(return_value=grants)
    contexts = AsyncMock(
        side_effect=[
            {"resource_version": 3, "catalog_release_id": 5},
            {"resource_version": 4, "catalog_release_id": 5},
        ]
    )
    mutate = AsyncMock(return_value={})
    monkeypatch.setattr(api, "list_service_account_grants", list_grants)
    monkeypatch.setattr(api, "get_context", contexts)
    monkeypatch.setattr(api, "mutate_grants", mutate)

    result = await api.revoke_service_account_grants(
        tenant_id=1,
        service_account_id=7,
        actor=SimpleNamespace(),
    )

    assert result == grants
    assert [len(call.kwargs["request"].changes) for call in mutate.await_args_list] == [50, 1]
    assert [
        call.kwargs["request"].expected_resource_version for call in mutate.await_args_list
    ] == [3, 4]
