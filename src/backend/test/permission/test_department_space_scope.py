"""F033 T-01: unit tests for ``_resolve_department_space_scope`` (design B1).

The resolver is the single source of truth for "is this resource a department
knowledge space, and which department path/ids may be authorized". It always
resolves the binding and bound department, while callers can skip the active
subtree-id expansion when a path predicate is sufficient. Returning ``None`` is
how the grant/authorize call sites fall back to the unchanged behavior for
normal spaces and non-space resources.

These tests mock the DB boundary (the DAO classmethods) and assert the
orchestration: the resource_type gate, the no-binding fallback, the subtree
composition, and the archived-department degradation.
"""

from bisheng.database.models.department import Department, DepartmentDao
from bisheng.knowledge.domain.models.department_knowledge_space import (
    DepartmentKnowledgeSpace,
    DepartmentKnowledgeSpaceDao,
)
from bisheng.permission.api.endpoints import resource_permission


def _patch_binding(monkeypatch, binding):
    async def _aget_by_space_id(cls, space_id):
        return binding

    monkeypatch.setattr(DepartmentKnowledgeSpaceDao, "aget_by_space_id", classmethod(_aget_by_space_id))


def _patch_department(monkeypatch, dept, subtree_ids):
    async def _aget_by_id(cls, dept_id):
        return dept

    async def _aget_subtree_ids(cls, path_prefix):
        return list(subtree_ids)

    monkeypatch.setattr(DepartmentDao, "aget_by_id", classmethod(_aget_by_id))
    monkeypatch.setattr(DepartmentDao, "aget_subtree_ids", classmethod(_aget_subtree_ids))


async def test_non_knowledge_space_resource_resolves_none():
    # Non knowledge_space resources must short-circuit before any binding query.
    scope = await resource_permission._resolve_department_space_scope("workflow", "1")
    assert scope is None


async def test_normal_space_without_binding_resolves_none(monkeypatch):
    _patch_binding(monkeypatch, None)
    scope = await resource_permission._resolve_department_space_scope("knowledge_space", "42")
    assert scope is None


async def test_department_space_resolves_bound_subtree(monkeypatch):
    binding = DepartmentKnowledgeSpace(department_id=10, space_id=42)
    dept = Department(id=10, dept_id="d10", name="研发", path="/10/", status="active")
    _patch_binding(monkeypatch, binding)
    _patch_department(monkeypatch, dept, [10, 11, 12])

    scope = await resource_permission._resolve_department_space_scope("knowledge_space", "42")

    assert scope is not None
    assert scope.department_id == 10
    assert scope.department_path == "/10/"
    assert scope.subtree_dept_ids == frozenset({10, 11, 12})


async def test_department_space_scope_can_skip_subtree_expansion(monkeypatch):
    binding = DepartmentKnowledgeSpace(department_id=10, space_id=42)
    dept = Department(id=10, dept_id="d10", name="研发", path="/10/", status="active")
    _patch_binding(monkeypatch, binding)

    async def _aget_by_id(cls, dept_id):
        return dept

    async def _unexpected_subtree_query(cls, path_prefix):
        raise AssertionError("subtree ids must not be loaded for path-scoped reads")

    monkeypatch.setattr(DepartmentDao, "aget_by_id", classmethod(_aget_by_id))
    monkeypatch.setattr(DepartmentDao, "aget_subtree_ids", classmethod(_unexpected_subtree_query))

    scope = await resource_permission._resolve_department_space_scope(
        "knowledge_space",
        "42",
        load_subtree_ids=False,
    )

    assert scope is not None
    assert scope.department_id == 10
    assert scope.department_path == "/10/"
    assert scope.subtree_dept_ids == frozenset()


async def test_archived_bound_department_yields_empty_subtree(monkeypatch):
    binding = DepartmentKnowledgeSpace(department_id=10, space_id=42)
    dept = Department(id=10, dept_id="d10", name="研发", path="/10/", status="archived")
    _patch_binding(monkeypatch, binding)
    # aget_subtree_ids filters status='active', so an archived bound department
    # yields an empty subtree -> scope present but no authorizable departments.
    _patch_department(monkeypatch, dept, [])

    scope = await resource_permission._resolve_department_space_scope("knowledge_space", "42")

    assert scope is not None
    assert scope.department_id == 10
    assert scope.department_path is None
    assert scope.subtree_dept_ids == frozenset()
