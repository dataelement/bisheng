"""F036 safety-invariant guard.

优化后的子项可见性快速通道(`_filter_visible_child_items`)默认启用,其等价性依赖一条不变量:

    **每一个对 file/folder 的"非 owner 授权"都必须写入一条 binding.**

(`owner` 是创建者的加性裸 tuple,`parent` 是结构边,二者都不改变可见集,由 owner 短路 / 评估时
跳过非用户主体处理;109 实测裸非 owner 授权 = 0.)

授权写路径(`resource_permission.authorize_resource`)对带 model_id 的 grant 会同时写 tuple 与
binding -- 这一点由 `test_permission_relation_bindings` / `test_permission_api_integration` 覆盖.
本测试锁定**另一半**:fast-path 的 `bound_ff`(取自 `build_binding_index` 的 file/folder 键)一定
覆盖这些 binding,从而被授权的资源永远走完整逐项评估,绝不会被当作"无更近授权"而继承.

若未来有人绕过 binding 直接写非 owner 授权 tuple(破坏不变量),该资源不会进入 bound_ff ->
快速通道会把它当继承处理 -> 本测试无法直接捕获,但 design §5 坑 7 / §6.2 已声明该依赖,
authorize 写路径须保持 binding 与 tuple 同写.
"""

from bisheng.permission.domain.services.fine_grained_permission_service import (
    FineGrainedPermissionService,
)


def _authorize_binding(resource_type, resource_id, relation="viewer", model_id="m1"):
    """Binding shape as written by resource_permission.authorize_resource for a non-owner grant."""
    return {
        "key": f"{resource_type}:{resource_id}:user:7:{relation}",
        "resource_type": resource_type,
        "resource_id": str(resource_id),
        "subject_type": "user",
        "subject_id": 7,
        "relation": relation,
        "include_children": None,
        "model_id": model_id,
    }


def _bound_ff(bindings):
    """Reproduce the fast-path's bound_ff set (see _filter_visible_child_items)."""
    index = FineGrainedPermissionService.build_binding_index(bindings)
    return {key for key in index if key[0] in ("knowledge_file", "folder")}


def test_nonowner_file_grant_lands_in_bound_ff():
    bindings = [_authorize_binding("knowledge_file", 1001, "viewer")]
    assert ("knowledge_file", "1001") in _bound_ff(bindings)


def test_nonowner_folder_grant_lands_in_bound_ff():
    bindings = [_authorize_binding("folder", 300, "editor")]
    assert ("folder", "300") in _bound_ff(bindings)


def test_mixed_grants_all_file_folder_bindings_covered():
    bindings = [
        _authorize_binding("knowledge_space", 57, "viewer"),  # space-level: handled by chain, not bound_ff
        _authorize_binding("knowledge_file", 1001, "viewer"),
        _authorize_binding("knowledge_file", 1002, "manager"),
        _authorize_binding("folder", 300, "editor"),
    ]
    bound = _bound_ff(bindings)
    # every file/folder binding -> in bound_ff (routed to full per-item eval)
    assert ("knowledge_file", "1001") in bound
    assert ("knowledge_file", "1002") in bound
    assert ("folder", "300") in bound
    # space binding is NOT a leaf -> not in bound_ff (its restriction is applied via the chain eval)
    assert ("knowledge_space", "57") not in bound


def test_resource_id_key_is_stringified():
    """bound_ff keys stringify resource_id so int item.id lookups (str(item.id)) match."""
    bindings = [_authorize_binding("knowledge_file", 1001)]
    bound = _bound_ff(bindings)
    # fast-path looks up (object_type, str(item.id)); ensure the index key is the str form
    assert ("knowledge_file", "1001") in bound
    assert ("knowledge_file", 1001) not in bound
