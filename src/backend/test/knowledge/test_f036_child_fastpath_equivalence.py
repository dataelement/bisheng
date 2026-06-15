"""F036-① child-listing fast-path dispatch equivalence.

覆盖 AC: AC-01 / AC-02 / AC-05 (spec 2.1/2.2). 验证 `_filter_visible_child_items_fast` 的
分发逻辑与 `_filter_visible_child_items_full` 在一致权限世界下结果逐位相等:
  - 叶级 binding 命中 -> 走完整逐项评估;
  - 当前用户是 owner -> 必可见(加性 owner 授权);
  - 其余 -> 继承"父链决策".
两个底层评估函数由同一 oracle 驱动,保证"无更近 binding 的非 owner 项,完整评估的 view 布尔
== 父链评估的 view 布尔"(即被验证过的不变量),从而对一致场景断言 fast == full;同时构造
owner 链不可见的用例,确保漏掉 owner 短路时测试会失败.

深层 OpenFGA 语义等价由 109 实跑 diff(flag off vs on,真实数据)兜底,见 design §7.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.knowledge.domain.models.knowledge_file import FileType
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

SPACE_ID = 57
USER_ID = 7
VIEW_FILE = "view_file"
VIEW_FOLDER = "view_folder"


def _svc():
    login_user = MagicMock()
    login_user.user_id = USER_ID
    return KnowledgeSpaceService(request=MagicMock(), login_user=login_user)


def _item(item_id, *, file_type=FileType.FILE.value, level_path="", owner=999):
    return SimpleNamespace(id=item_id, file_type=file_type, file_level_path=level_path, user_id=owner)


def _perm_for(item):
    return VIEW_FOLDER if item.file_type == FileType.DIR.value else VIEW_FILE


def _ctx(bound_keys):
    # binding_index only needs the (resource_type, str(resource_id)) keys for fast-path routing.
    return {"binding_index": {k: [] for k in bound_keys}}


async def _run_both(svc, items, context, *, item_visible, chain_visible):
    """Drive both filter paths from a single consistent oracle and return (fast, full) id lists."""

    async def fake_item_eff(item, *, space_id, context):  # full per-item eval + leaf-bound branch
        return {_perm_for(item)} if item_visible(item) else set()

    async def fake_chain_eff(ancestor_ids, *, space_id, context):
        return {VIEW_FILE, VIEW_FOLDER} if chain_visible(tuple(ancestor_ids)) else set()

    svc._get_child_item_effective_permission_ids = AsyncMock(side_effect=fake_item_eff)
    svc._chain_effective_permission_ids = AsyncMock(side_effect=fake_chain_eff)

    fast = await svc._filter_visible_child_items_fast(items, space_id=SPACE_ID, context=context)
    full = await svc._filter_visible_child_items_full(items, space_id=SPACE_ID, context=context)
    return [i.id for i in fast], [i.id for i in full]


@pytest.mark.parametrize("flag_owner_visible", [True, False])
async def test_fast_equals_full_consistent_world(flag_owner_visible):
    svc = _svc()
    # items:
    #  1 owner item (chain says NOT visible -> owner short-circuit must still show it)
    #  2 inherit-visible (no binding, not owner, chain visible)
    #  3 inherit-hidden (no binding, not owner, chain hidden)
    #  4 leaf-bound visible
    #  5 leaf-bound hidden
    #  6 under bound ancestor folder (no leaf binding) -> chain decides
    items = [
        _item(1, owner=USER_ID, level_path="200"),
        _item(2, owner=999, level_path="200"),
        _item(3, owner=999, level_path="201"),
        _item(4, owner=999, level_path="200"),
        _item(5, owner=999, level_path="200"),
        _item(6, owner=999, level_path="300"),  # 300 is a bound ancestor folder
    ]
    context = _ctx({("knowledge_file", "4"), ("knowledge_file", "5"), ("folder", "300")})

    # fast-path parses file_level_path into INT ancestor ids -> chain keys are int tuples.
    chain_vis = {(200,): True, (201,): False, (300,): True}
    leaf_vis = {4: True, 5: False}

    def item_visible(it):
        # full path's per-item oracle, kept consistent with chain for non-bound non-owner items
        if it.id in leaf_vis:  # leaf-bound
            return leaf_vis[it.id]
        if it.user_id == USER_ID:  # owner: full path sees own item
            return True
        return chain_vis[tuple(int(p) for p in it.file_level_path.split("/") if p)]

    def chain_visible(anc):
        return chain_vis[anc]

    fast, full = await _run_both(svc, items, context, item_visible=item_visible, chain_visible=chain_visible)
    assert fast == full
    # explicit expected set: owner(1) + inherit-visible(2) + leaf-bound-visible(4) + bound-ancestor-visible(6)
    assert fast == [1, 2, 4, 6]


async def test_owner_shortcircuit_required():
    """If owner item's chain is hidden, fast-path must still show it (regression guard)."""
    svc = _svc()
    items = [_item(1, owner=USER_ID, level_path="201")]  # chain 201 hidden, but owner
    context = _ctx(set())

    async def fake_item_eff(item, *, space_id, context):
        return set()  # pretend full-eval also yields nothing via this fake...

    async def fake_chain_eff(ancestor_ids, *, space_id, context):
        return set()  # chain hidden

    svc._get_child_item_effective_permission_ids = AsyncMock(side_effect=fake_item_eff)
    svc._chain_effective_permission_ids = AsyncMock(side_effect=fake_chain_eff)

    fast = await svc._filter_visible_child_items_fast(items, space_id=SPACE_ID, context=context)
    # owner short-circuit returns True regardless of chain/eval mocks
    assert [i.id for i in fast] == [1]


async def test_leaf_bound_uses_full_eval_not_chain():
    """A leaf with its own binding must be decided by per-item eval, never by the chain."""
    svc = _svc()
    items = [_item(9, owner=999, level_path="200")]
    context = _ctx({("knowledge_file", "9")})

    item_eff = AsyncMock(return_value={VIEW_FILE})  # per-item eval says visible
    chain_eff = AsyncMock(return_value=set())  # chain says hidden — must be ignored for leaf-bound
    svc._get_child_item_effective_permission_ids = item_eff
    svc._chain_effective_permission_ids = chain_eff

    fast = await svc._filter_visible_child_items_fast(items, space_id=SPACE_ID, context=context)
    assert [i.id for i in fast] == [9]
    item_eff.assert_awaited()  # leaf-bound went through per-item eval
    chain_eff.assert_not_awaited()  # and NOT through the chain
