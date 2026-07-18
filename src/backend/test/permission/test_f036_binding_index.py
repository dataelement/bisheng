"""F036-③ binding-index equivalence tests.

覆盖 AC: AC-07 / AC-09(spec §2.2 / §2.3:`_resolve_binding_for_tuple` 改用按 key 索引,
结果必须与线性扫描逐位等价,且"首个匹配 wins"顺序不变).

策略:以**线性路径本身**为 oracle -- 对同一组输入分别用 `binding_index=None`(线性)
与传入 `build_binding_index(bindings)`(索引)调用,断言返回完全一致.这样无需复刻内部
逻辑即可证明索引化是行为保持的重构.
"""

from bisheng.permission.domain.services.fine_grained_permission_service import (
    FineGrainedPermissionService as FGPS,
)


def _binding(rt, rid, relation, subject_type, subject_id, *, include_children=False, model_id="m1"):
    return {
        "resource_type": rt,
        "resource_id": rid,
        "relation": relation,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "include_children": include_children,
        "model_id": model_id,
    }


# 多资源,多关系,多主体;同一 (resource, relation, user) 故意放两条以验证"首个匹配 wins"
BINDINGS = [
    _binding("knowledge_space", 57, "viewer", "user", 1),
    _binding("knowledge_file", 100, "viewer", "user", 1, model_id="first"),
    _binding("knowledge_file", 100, "viewer", "user", 1, model_id="second"),  # 同键第二条
    _binding("folder", 200, "editor", "department", 5, include_children=True),
    _binding("folder", 200, "viewer", "department", 9, include_children=True),
    _binding("knowledge_file", 101, "viewer", "user_group", 3),
    _binding("knowledge_space", 58, "manager", "user", 2),
]


def test_build_binding_index_groups_and_preserves_order():
    idx = FGPS.build_binding_index(BINDINGS)
    # 分组键 (resource_type, str(resource_id))
    assert set(idx.keys()) == {
        ("knowledge_space", "57"),
        ("knowledge_file", "100"),
        ("folder", "200"),
        ("knowledge_file", "101"),
        ("knowledge_space", "58"),
    }
    # 同键内顺序与原列表一致(first/second 不能颠倒)
    kf100 = idx[("knowledge_file", "100")]
    assert [b["model_id"] for b in kf100] == ["first", "second"]


async def _assert_resolve_equiv(rt, rid, tuple_user, relation, *, dept_paths=None, tuple_dept_paths=None):
    idx = FGPS.build_binding_index(BINDINGS)
    dept_paths = dept_paths or {}
    # 线性 vs 索引,分别传各自的 tuple_department_paths 副本,避免互相污染缓存
    linear = await FGPS._resolve_binding_for_tuple(
        rt,
        rid,
        tuple_user,
        relation,
        BINDINGS,
        dept_paths,
        dict(tuple_dept_paths or {}),
    )
    indexed = await FGPS._resolve_binding_for_tuple(
        rt,
        rid,
        tuple_user,
        relation,
        BINDINGS,
        dept_paths,
        dict(tuple_dept_paths or {}),
        binding_index=idx,
    )
    assert linear == indexed, f"linear={linear} indexed={indexed}"
    return linear


async def test_resolve_user_match_equiv_and_first_wins():
    # 命中:user:1 viewer on knowledge_file:100 -- 首个匹配(model_id=first)
    res = await _assert_resolve_equiv("knowledge_file", 100, "user:1", "viewer")
    assert res is not None and res["model_id"] == "first"


async def test_resolve_user_no_match_equiv():
    # 不命中:user:1 不持有 manager
    res = await _assert_resolve_equiv("knowledge_space", 58, "user:1", "manager")
    assert res is None


async def test_resolve_wrong_resource_equiv():
    # 资源不在索引中
    res = await _assert_resolve_equiv("knowledge_file", 999, "user:1", "viewer")
    assert res is None


async def test_resolve_department_include_children_equiv():
    # 部门子树匹配:tuple 部门 5 的 path 落在 binding 部门 5 的 path 前缀下
    dept_paths = {5: "/root/5", 9: "/root/9"}
    tuple_dept_paths = {5: "/root/5/leaf"}
    res = await _assert_resolve_equiv(
        "folder",
        200,
        "department:5#member",
        "editor",
        dept_paths=dept_paths,
        tuple_dept_paths=tuple_dept_paths,
    )
    assert res is not None and res["subject_id"] == 5


async def test_resolve_department_no_prefix_equiv():
    # 部门 path 不在任何 binding 部门前缀下 → 不命中
    dept_paths = {5: "/root/5", 9: "/root/9"}
    tuple_dept_paths = {7: "/root/7"}
    res = await _assert_resolve_equiv(
        "folder",
        200,
        "department:7#member",
        "editor",
        dept_paths=dept_paths,
        tuple_dept_paths=tuple_dept_paths,
    )
    assert res is None
