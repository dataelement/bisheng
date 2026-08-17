"""Contracts for configuring ordinary Grants before a resource exists."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.permission.application.prospective_grant import (
    ProspectiveGrantApplication,
)
from bisheng.permission.domain.services.grant_source_service import (
    GrantModelSnapshot,
)
from bisheng.permission.domain.services.permission_action_service import (
    PermissionActor,
)


def _model(key: str, level: int, *, active: bool = True):
    return SimpleNamespace(
        snapshot=GrantModelSnapshot(
            model_key=key,
            active=active,
            action_codes=("visible",),
            derived_level=level,
        ),
        name=key.title(),
    )


class _Runtime:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.catalog = SimpleNamespace(
            release_id=42,
            models=(
                _model("viewer", 1),
                _model("editor", 2),
                _model("retired", 3, active=False),
                SimpleNamespace(
                    snapshot=GrantModelSnapshot(
                        model_key="owner",
                        active=True,
                        action_codes=("visible", "manage_permission"),
                        derived_level=4,
                        allow_same_level=False,
                    ),
                    name="Owner",
                ),
            ),
        )

    async def prospective_owner_grantable_models(self):
        self.calls.append("prospective_owner_grantable_models")
        return self.catalog, self.catalog.models[:2]

    def __getattr__(self, name: str):
        if name in {
            "allocate_source_ids",
            "authorize_created",
            "check_action",
            "mutate_grants",
            "require_manage_permission",
        }:
            raise AssertionError(f"prospective flow must not call {name}")
        raise AttributeError(name)


class _Directory:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def list_users(self, **kwargs):
        self.calls.append(("users", kwargs))
        return {"data": [{"user_id": 8, "user_name": "Ada"}], "total": 1}

    async def list_user_groups(self, **kwargs):
        self.calls.append(("user_groups", kwargs))
        return {"data": [{"id": 3, "name": "Reviewers"}], "total": 1}

    async def list_department_children(self, **kwargs):
        self.calls.append(("department_children", kwargs))
        return [{"id": 5, "name": "Research"}]

    async def search_departments(self, **kwargs):
        self.calls.append(("department_search", kwargs))
        return {"roots": [], "total_matches": 0, "truncated": False}

    async def get_department_path(self, **kwargs):
        self.calls.append(("department_path", kwargs))
        return {"roots": [{"id": 5}], "total_matches": 1, "truncated": False}


def _actor(tenant_id: int = 7) -> PermissionActor:
    return PermissionActor(user_id=11, current_tenant_id=tenant_id)


@pytest.fixture
def prospective():
    runtime = _Runtime()
    directory = _Directory()
    return ProspectiveGrantApplication(runtime=runtime, subjects=directory), runtime, directory


async def test_context_uses_owner_policy_without_a_resource_target(prospective) -> None:
    service, runtime, directory = prospective

    result = await service.get_context(
        actor=_actor(),
        tenant_id=7,
        resource_type="knowledge_space",
    )

    assert result == {
        "catalog_release_id": 42,
        "can_configure_initial_permissions": True,
        "grantable_models": [
            {"key": "viewer", "name": "Viewer", "level": 1, "active": True},
            {"key": "editor", "name": "Editor", "level": 2, "active": True},
        ],
    }
    assert runtime.calls == ["prospective_owner_grantable_models"]
    assert directory.calls == []


async def test_candidates_are_scoped_to_the_verified_tenant(prospective) -> None:
    service, runtime, directory = prospective

    users = await service.list_users(
        actor=_actor(),
        tenant_id=7,
        resource_type="channel",
        keyword="Ad",
        page=2,
        page_size=25,
    )
    groups = await service.list_user_groups(
        actor=_actor(),
        tenant_id=7,
        resource_type="channel",
        keyword="Rev",
        page=1,
        page_size=50,
    )
    children = await service.list_department_children(
        actor=_actor(),
        tenant_id=7,
        resource_type="channel",
        parent_id=5,
    )
    search = await service.search_departments(
        actor=_actor(),
        tenant_id=7,
        resource_type="channel",
        keyword="Res",
        limit=20,
    )
    path = await service.get_department_path(
        actor=_actor(),
        tenant_id=7,
        resource_type="channel",
        department_id=5,
    )

    assert users["total"] == groups["total"] == 1
    assert children == [{"id": 5, "name": "Research"}]
    assert search["total_matches"] == 0
    assert path["total_matches"] == 1
    assert [name for name, _ in directory.calls] == [
        "users",
        "user_groups",
        "department_children",
        "department_search",
        "department_path",
    ]
    assert all(call["tenant_id"] == 7 for _, call in directory.calls)
    assert all(call["resource_type"] == "channel" for _, call in directory.calls)
    assert runtime.calls == []


async def test_cross_tenant_scope_fails_before_catalog_or_directory_access(prospective) -> None:
    service, runtime, directory = prospective

    with pytest.raises(PermissionDeniedError):
        await service.get_context(
            actor=_actor(tenant_id=7),
            tenant_id=8,
            resource_type="knowledge_space",
        )

    assert runtime.calls == []
    assert directory.calls == []


async def test_super_admin_may_use_a_business_verified_cross_tenant_scope(prospective) -> None:
    service, _, directory = prospective
    actor = PermissionActor(user_id=1, current_tenant_id=1, super_admin=True)

    await service.list_users(
        actor=actor,
        tenant_id=8,
        resource_type="knowledge_space",
        keyword="",
        page=1,
        page_size=50,
    )

    assert directory.calls[0][1]["tenant_id"] == 8
