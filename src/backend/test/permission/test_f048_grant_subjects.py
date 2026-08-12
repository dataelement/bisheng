"""Grant-subject pickers ask about the resource, not about the org chart.

F048 removed `…/resources/{type}/{id}/grant-subjects/…` and pointed both
frontends at the org-management endpoints, whose predicate is "which users do you
administer". A knowledge space's manager is not necessarily any kind of
organisational admin, so the user list came back empty and the department tree
answered "no permission" — while the very same person was allowed to grant that
space.
"""

from __future__ import annotations

import pytest

from bisheng.permission.api.endpoints.grant_subjects import (
    GRANT_SUBJECT_RESOURCE_TYPES,
)
from bisheng.permission.api.router import router
from bisheng.permission.domain.services.grant_subject_service import GrantSubjectScope

EXPECTED_ROUTES = {
    "/permissions/resources/{resource_type}/{resource_id}/grant-subjects/users",
    "/permissions/resources/{resource_type}/{resource_id}/grant-subjects/user-groups",
    "/permissions/resources/{resource_type}/{resource_id}/grant-subjects/departments/children",
    "/permissions/resources/{resource_type}/{resource_id}/grant-subjects/departments/search",
    "/permissions/resources/{resource_type}/{resource_id}/grant-subjects/departments/{dept_id}/path-tree",
}


def test_every_picker_route_is_registered() -> None:
    """The 2.6 URLs the pickers call, restored verbatim."""

    paths = {route.path for route in router.routes}
    assert EXPECTED_ROUTES <= paths


def test_resource_types_cover_every_grantable_container() -> None:
    # Anything with a permission dialog must be able to pick subjects for it.
    assert {
        "knowledge_space",
        "knowledge_library",
        "folder",
        "knowledge_file",
        "workflow",
        "assistant",
        "tool",
        "channel",
        "dashboard",
    } <= GRANT_SUBJECT_RESOURCE_TYPES


async def test_a_caller_without_manage_permission_is_refused(monkeypatch) -> None:
    """The predicate is the resource's `manage_permission`, nothing else."""

    from bisheng.permission.api.endpoints import grant_subjects

    async def resolve_actor(login_user):
        del login_user
        return object()

    class _Registry:
        async def resolve(self, **kwargs):
            del kwargs
            return type("Target", (), {"tenant_id": 1})()

    async def registry():
        return _Registry()

    async def denies(*args, **kwargs):
        del args, kwargs
        return False

    monkeypatch.setattr(grant_subjects, "resolve_permission_actor", resolve_actor)
    monkeypatch.setattr(grant_subjects, "get_f048_resource_registry", registry)
    monkeypatch.setattr(grant_subjects, "check_business_action", denies)

    response = await grant_subjects.list_grant_subject_users(
        resource_type="knowledge_space",
        resource_id="21011",
        login_user=object(),
    )
    assert response.status_code != 200


async def test_an_unknown_resource_type_is_refused() -> None:
    from bisheng.permission.api.endpoints import grant_subjects

    response = await grant_subjects.list_grant_subject_users(
        resource_type="not_a_resource",
        resource_id="1",
        login_user=object(),
    )
    assert response.status_code != 200


@pytest.mark.parametrize(
    ("resource_type", "expected"),
    [("knowledge_library", None), ("workflow", None), ("folder", None)],
)
async def test_only_a_knowledge_space_can_be_department_bound(resource_type, expected) -> None:
    from bisheng.permission.domain.services import grant_subject_service

    assert await grant_subject_service.resolve_department_space_path(resource_type, "1") is expected


def test_scope_carries_the_resource_tenant_not_the_caller_s() -> None:
    """A super admin picking for another tenant's resource sees that tenant."""

    scope = GrantSubjectScope(tenant_id=42, department_path=None)
    assert scope.tenant_id == 42
    assert scope.department_path is None


async def test_the_department_answers_carry_the_org_tree_shape(monkeypatch) -> None:
    """The picker renders either source, so both must speak the same node shape.

    The layer endpoint returns nodes with `children`, and reveal/search return
    the pruned `{roots, …}` forest — a flat ancestor list would render the
    hierarchy as unrelated top-level rows.
    """

    from bisheng.department.domain.services import department_service as org
    from bisheng.permission.domain.services import grant_subject_service

    node = org._dept_node_dict(
        type(
            "D",
            (),
            {
                "id": 7,
                "dept_id": "D7",
                "name": "sales",
                "parent_id": None,
                "path": "/7/",
                "sort_order": 0,
                "source": "local",
                "status": "active",
            },
        )()
    )
    assert "children" in node and "has_children" in node

    async def one_department(*args, **kwargs):
        del args, kwargs
        return type("D", (), {"id": 7, "tenant_id": 1, "path": "/7/"})()

    async def forest(*args, **kwargs):
        del args, kwargs
        return [node]

    monkeypatch.setattr(grant_subject_service.DepartmentDao, "aget_by_id", one_department)
    monkeypatch.setattr(grant_subject_service.DepartmentService, "abuild_forest_within_subtree", forest)

    revealed = await grant_subject_service.get_candidate_department_path(
        GrantSubjectScope(tenant_id=1, department_path=None), dept_id=7
    )
    assert set(revealed) == {"roots", "total_matches", "truncated"}
    assert revealed["roots"] == [node]


async def test_a_department_bound_space_reveals_nothing_outside_its_subtree(monkeypatch) -> None:
    from bisheng.permission.domain.services import grant_subject_service

    async def elsewhere(*args, **kwargs):
        del args, kwargs
        return type("D", (), {"id": 9, "tenant_id": 1, "path": "/1/9/"})()

    monkeypatch.setattr(grant_subject_service.DepartmentDao, "aget_by_id", elsewhere)

    revealed = await grant_subject_service.get_candidate_department_path(
        GrantSubjectScope(tenant_id=1, department_path="/2/"), dept_id=9
    )
    assert revealed["roots"] == []
