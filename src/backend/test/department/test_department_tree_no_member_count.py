"""T014 — Department tree ``member_count`` removal (AC-13, AC-14, AC-15, AC-16).

Static-source checks via AST (consistent with T010/T012 pattern; avoids the
pytest pre-mock chain breakage that affects ``DepartmentService`` instantiation).

Covers:
- AC-13: ``DepartmentService.aget_tree`` no longer queries ``UserDepartment``
  count and no longer writes ``member_count`` to its node dicts/objects.
- AC-14 (schema side): ``DepartmentTreeNode`` no longer declares
  ``member_count``.
- AC-15 (boundary protection): ``aget_department`` (single dept GET) still
  populates ``member_count`` per spec §1.
- AC-16 (boundary protection): ``resource_permission`` endpoint still emits
  ``member_count`` per spec §1.
"""
from __future__ import annotations

import ast
from pathlib import Path


def _read(rel: str) -> str:
    return (
        Path(__file__).resolve().parents[2] / "bisheng" / rel
    ).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# AC-13: aget_tree no longer counts members or attaches member_count
# ---------------------------------------------------------------------------


def test_aget_tree_no_userdepartment_count_query():
    src = _read("department/domain/services/department_service.py")
    tree = ast.parse(src)
    cls = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "DepartmentService")
    func = next(
        n for n in cls.body
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == "aget_tree"
    )
    func_src = ast.get_source_segment(src, func)

    # No COUNT(UserDepartment.id) query at all
    assert "func.count(UserDepartment.id)" not in func_src
    assert "count_map" not in func_src
    assert "count_result" not in func_src


def test_aget_tree_no_member_count_attribute_on_nodes():
    src = _read("department/domain/services/department_service.py")
    tree = ast.parse(src)
    cls = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "DepartmentService")
    func = next(
        n for n in cls.body
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == "aget_tree"
    )
    func_src = ast.get_source_segment(src, func)
    assert "member_count" not in func_src, "aget_tree must not pass `member_count` into tree nodes"


# ---------------------------------------------------------------------------
# AC-14: DepartmentTreeNode schema drops `member_count`
# ---------------------------------------------------------------------------


def test_department_tree_node_schema_no_member_count():
    src = _read("department/domain/schemas/department_schema.py")
    tree = ast.parse(src)
    cls = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "DepartmentTreeNode")
    field_names = set()
    for stmt in cls.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            field_names.add(stmt.target.id)
    assert "member_count" not in field_names


# ---------------------------------------------------------------------------
# AC-15: single-department GET still has member_count (boundary protection)
# ---------------------------------------------------------------------------


def test_aget_department_still_populates_member_count():
    src = _read("department/domain/services/department_service.py")
    tree = ast.parse(src)
    cls = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "DepartmentService")
    func = next(
        n for n in cls.body
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == "aget_department"
    )
    func_src = ast.get_source_segment(src, func)
    # Still references member_count somewhere in the single-dept GET
    assert "member_count" in func_src, (
        "aget_department must retain member_count per spec §1 (AC-15)"
    )


# ---------------------------------------------------------------------------
# AC-16: resource_permission dept tree still emits member_count (boundary)
# ---------------------------------------------------------------------------


def test_resource_permission_endpoint_still_emits_member_count():
    src = _read("permission/api/endpoints/resource_permission.py")
    assert "member_count" in src, (
        "resource_permission.py must retain member_count emission per spec §1 (AC-16)"
    )
