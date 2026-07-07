# /space/grouped 性能优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `/api/v1/knowledge/space/grouped` 链路里 `_format_accessible_spaces` 的 per-space OpenFGA 扇出批量化并加 per-user 短 TTL 缓存，在不改变任何 space 最终权限取值的前提下降低延迟。

**Architecture:** 三项独立优化叠加在 `KnowledgeSpaceService._list_accessible_spaces` / `_format_accessible_spaces` 上：① 新增 `PermissionService.get_permission_levels` 把 N 次 OpenFGA `batch_check` 合并成 1 次；② 复用 `get_effective_permission_ids_async` 的 `tuple_cache` 并传入预算好的 permission_level 消除重复计算；③ 用 Redis 缓存 `_list_accessible_spaces` 结果。每一步用 mock 驱动的 characterization 测试锁住输出等价。

**Tech Stack:** Python 3.10 / asyncio / pytest（sqlite in-memory + AsyncMock）/ OpenFGA / Redis（`get_redis_client`）。

## Global Constraints

- 权限行为严格等价：①②③ 不改变任何 space 的最终 `permission_level` / `effective_permission_ids` / `user_role` / 是否入列 取值（不越权不漏权）。
- ③ 缓存为纯 TTL，默认 **15 秒**，模块常量可配置，不做主动失效。
- 验证用 mock 驱动单测（测试基线脏：`test_knowledge_space_service.py` 现状 **136 passed / 40 failed**，40 个为预存 SQLAlchemy DB-engine 环境失败，与本优化无关）。
- 每个 task 结束回归：`cd src/backend && ./.venv/bin/python -m pytest test/test_knowledge_space_service.py -q`，确认 **passed 数不减少、40 个预存失败不新增**。
- 运行单测统一：`cd /Users/zhangguoqing/works/bisheng_2-grouped-perf/src/backend && ./.venv/bin/python -m pytest <target> -q`
- 提交信息用英文 `type: subject` 前缀（贴合仓库风格）。

---

### Task 1: Characterization 基线 — 锁住 `_format_accessible_spaces` 现有输出

**Files:**
- Test: `src/backend/test/test_knowledge_space_service.py`（新增测试类 `TestFormatAccessibleSpacesCharacterization`）

**Interfaces:**
- Consumes: 现有 helper `_make_space(space_id, user_id, auth_type, ...)`、`_make_member(user_id, user_role, space_id)`、fixture `service`（含 `service.login_user.user_id`）、`UserRoleEnum`、`AuthTypeEnum`、`SpaceSubscriptionStatusEnum`；被测方法 `KnowledgeSpaceService._format_accessible_spaces(space_ids, order_by, *, memberships, exclude_created, required_permission_id)`。
- Produces: 一组 characterization 测试，后续每个 task 都必须保持它们全绿。

> 说明：characterization 测试描述**现有行为**，因此写完运行即应 PASS（不是先 FAIL）。它的作用是护栏——后续改动若破坏等价性，这里立刻变红。

- [ ] **Step 1: 写 characterization 测试（覆盖 4 条关键路径）**

在文件末尾新增（`_make_space`/`_make_member`/`service` 沿用文件内现有定义；若 `_make_space` 的参数名不同，按其真实签名微调）：

```python
class TestFormatAccessibleSpacesCharacterization:
    """锁住 _format_accessible_spaces 的输出，作为性能重构的等价性护栏。"""

    @pytest.mark.asyncio
    async def test_creator_space_maps_to_creator_role_and_subscribed(self, service):
        own = _make_space(space_id=1, user_id=service.login_user.user_id, auth_type=AuthTypeEnum.PRIVATE)
        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_get_spaces_by_ids',
            new_callable=AsyncMock, return_value=[own],
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.async_count_success_files_batch',
            new_callable=AsyncMock, return_value={1: 7},
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_space_ids',
            new_callable=AsyncMock, return_value=[],
        ):
            result = await service._format_accessible_spaces(
                [1], 'update_time', memberships=[], required_permission_id='view_space',
            )
        assert [s.id for s in result] == [1]
        assert result[0].user_role == UserRoleEnum.CREATOR
        assert result[0].subscription_status == SpaceSubscriptionStatusEnum.SUBSCRIBED
        assert result[0].file_num == 7

    @pytest.mark.asyncio
    async def test_direct_grant_without_membership_maps_to_admin(self, service):
        granted = _make_space(space_id=3, user_id=88, auth_type=AuthTypeEnum.PRIVATE)
        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_get_spaces_by_ids',
            new_callable=AsyncMock, return_value=[granted],
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.get_permission_level',
            new_callable=AsyncMock, return_value='can_manage',
        ), patch.object(
            service, '_get_effective_permission_ids',
            new_callable=AsyncMock, return_value={'view_space', 'manage_space_relation'},
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.async_count_success_files_batch',
            new_callable=AsyncMock, return_value={3: 0},
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_space_ids',
            new_callable=AsyncMock, return_value=[],
        ):
            result = await service._format_accessible_spaces(
                [3], 'update_time', memberships=[], required_permission_id='view_space',
            )
        assert [s.id for s in result] == [3]
        assert result[0].user_role == UserRoleEnum.ADMIN

    @pytest.mark.asyncio
    async def test_non_owner_space_without_view_space_is_excluded(self, service):
        other = _make_space(space_id=5, user_id=88, auth_type=AuthTypeEnum.PRIVATE)
        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_get_spaces_by_ids',
            new_callable=AsyncMock, return_value=[other],
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.get_permission_level',
            new_callable=AsyncMock, return_value=None,
        ), patch.object(
            service, '_get_effective_permission_ids',
            new_callable=AsyncMock, return_value=set(),
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_space_ids',
            new_callable=AsyncMock, return_value=[],
        ):
            result = await service._format_accessible_spaces(
                [5], 'update_time', memberships=[], required_permission_id='view_space',
            )
        assert result == []

    @pytest.mark.asyncio
    async def test_pinned_membership_space_sorts_first(self, service):
        s_pinned = _make_space(space_id=10, user_id=88, auth_type=AuthTypeEnum.PRIVATE)
        s_plain = _make_space(space_id=11, user_id=service.login_user.user_id, auth_type=AuthTypeEnum.PRIVATE)
        member = _make_member(user_id=service.login_user.user_id, user_role=UserRoleEnum.MEMBER, space_id=10)
        member.is_pinned = True
        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_get_spaces_by_ids',
            new_callable=AsyncMock, return_value=[s_plain, s_pinned],
        ), patch.object(
            service, '_get_effective_permission_ids',
            new_callable=AsyncMock, return_value={'view_space'},
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.async_count_success_files_batch',
            new_callable=AsyncMock, return_value={10: 1, 11: 2},
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_space_ids',
            new_callable=AsyncMock, return_value=[],
        ):
            result = await service._format_accessible_spaces(
                [10, 11], 'update_time', memberships=[member], required_permission_id='view_space',
            )
        assert result[0].id == 10 and result[0].is_pinned is True
```

- [ ] **Step 2: 运行 characterization，确认全绿（描述现有行为）**

Run: `cd /Users/zhangguoqing/works/bisheng_2-grouped-perf/src/backend && ./.venv/bin/python -m pytest test/test_knowledge_space_service.py::TestFormatAccessibleSpacesCharacterization -q`
Expected: PASS（4 passed）。若某条失败，说明我对现有行为的假设错误 —— **停下核对被测代码，把断言改成与现状一致**（不要改产品代码）。

- [ ] **Step 3: Commit**

```bash
cd /Users/zhangguoqing/works/bisheng_2-grouped-perf
git add src/backend/test/test_knowledge_space_service.py
git commit -m "test: add characterization tests locking _format_accessible_spaces output"
```

---

### Task 2: ① 新增 `PermissionService.get_permission_levels` 批量 API

**Files:**
- Modify: `src/backend/bisheng/permission/domain/services/permission_service.py`（新增 classmethod，紧邻 `get_permission_level` `:835` 之后）
- Test: `src/backend/test/test_permission_service_batch_levels.py`（新建）

**Interfaces:**
- Consumes: `PermissionService._evaluate_tenant_gate`、`_aget_fga`、`fga.batch_check(checks)`、`_legacy_alias_object_types`、`_get_implicit_permission_level_after_gate`、`PermissionLevel`（枚举，迭代顺序 = 从高到低）。
- Produces: `async PermissionService.get_permission_levels(user_id: int, object_type: str, object_ids: list[str | int], login_user=None) -> dict[str, str | None]`。返回 key 为 `str(object_id)`，value 为 permission level 值或 `None`，语义与逐个 `get_permission_level` 完全一致。

- [ ] **Step 1: 写单测（批量结果 == 逐个调用结果）**

新建 `src/backend/test/test_permission_service_batch_levels.py`：

```python
import pytest
from unittest.mock import AsyncMock, patch

from bisheng.permission.domain.services.permission_service import PermissionService, PermissionLevel


def _fake_login_user(user_id=7, is_admin=False):
    class _U:
        def __init__(self):
            self.user_id = user_id
        def is_admin(self):
            return is_admin
    return _U()


@pytest.mark.asyncio
async def test_get_permission_levels_matches_single_calls():
    login_user = _fake_login_user()
    object_ids = ['1', '2', '3']

    # object 1 -> owner True; object 2 -> can_read True; object 3 -> all False
    def _single_batch_check(checks):
        # checks: 4 rows for one object (owner, can_manage, can_edit, can_read)
        obj = checks[0]['object']
        table = {
            'knowledge_space:1': [True, False, False, False],
            'knowledge_space:2': [False, False, False, True],
            'knowledge_space:3': [False, False, False, False],
        }
        return table[obj]

    fga = AsyncMock()
    fga.batch_check.side_effect = lambda checks: _single_batch_check(checks)

    with patch.object(PermissionService, '_aget_fga', new_callable=AsyncMock, return_value=fga), \
         patch.object(PermissionService, '_evaluate_tenant_gate', new_callable=AsyncMock, return_value=(False, None)), \
         patch.object(PermissionService, '_legacy_alias_object_types', new_callable=AsyncMock, return_value=[]), \
         patch.object(PermissionService, '_get_implicit_permission_level_after_gate', new_callable=AsyncMock, return_value=None):
        singles = {}
        for oid in object_ids:
            singles[oid] = await PermissionService.get_permission_level(
                user_id=login_user.user_id, object_type='knowledge_space', object_id=oid, login_user=login_user)

    # For the batch call, batch_check receives 4*N rows in one shot.
    def _merged_batch_check(checks):
        out = []
        # group by object, preserve level order per object
        by_obj = {}
        for c in checks:
            by_obj.setdefault(c['object'], []).append(c)
        for c in checks:
            table = {
                'knowledge_space:1': {'owner': True},
                'knowledge_space:2': {'can_read': True},
                'knowledge_space:3': {},
            }
            out.append(table[c['object']].get(c['relation'], False))
        return out

    fga2 = AsyncMock()
    fga2.batch_check.side_effect = lambda checks: _merged_batch_check(checks)
    with patch.object(PermissionService, '_aget_fga', new_callable=AsyncMock, return_value=fga2), \
         patch.object(PermissionService, '_evaluate_tenant_gate', new_callable=AsyncMock, return_value=(False, None)), \
         patch.object(PermissionService, '_legacy_alias_object_types', new_callable=AsyncMock, return_value=[]), \
         patch.object(PermissionService, '_get_implicit_permission_level_after_gate', new_callable=AsyncMock, return_value=None):
        batched = await PermissionService.get_permission_levels(
            user_id=login_user.user_id, object_type='knowledge_space', object_ids=object_ids, login_user=login_user)

    assert batched == singles
    assert batched == {'1': 'owner', '2': 'can_read', '3': None}
    # a single merged batch_check call, not one-per-object
    assert fga2.batch_check.await_count == 1


@pytest.mark.asyncio
async def test_get_permission_levels_admin_shortcut():
    login_user = _fake_login_user(is_admin=True)
    result = await PermissionService.get_permission_levels(
        user_id=login_user.user_id, object_type='knowledge_space', object_ids=['1', '2'], login_user=login_user)
    assert result == {'1': PermissionLevel.owner.value, '2': PermissionLevel.owner.value}


@pytest.mark.asyncio
async def test_get_permission_levels_tenant_gate_denied_and_shortcut():
    login_user = _fake_login_user()

    async def _gate(user_id, object_type, object_id, login_user=None):
        if object_id == '1':
            return True, None           # denied -> None
        if object_id == '2':
            return False, 'owner'       # shortcut -> owner
        return False, None

    fga = AsyncMock()
    fga.batch_check.side_effect = lambda checks: [False, False, False, False]
    with patch.object(PermissionService, '_evaluate_tenant_gate', side_effect=_gate), \
         patch.object(PermissionService, '_aget_fga', new_callable=AsyncMock, return_value=fga), \
         patch.object(PermissionService, '_legacy_alias_object_types', new_callable=AsyncMock, return_value=[]), \
         patch.object(PermissionService, '_get_implicit_permission_level_after_gate', new_callable=AsyncMock, return_value=None):
        result = await PermissionService.get_permission_levels(
            user_id=login_user.user_id, object_type='knowledge_space', object_ids=['1', '2', '3'], login_user=login_user)
    assert result == {'1': None, '2': 'owner', '3': None}
```

- [ ] **Step 2: 运行，确认 FAIL（方法未定义）**

Run: `cd /Users/zhangguoqing/works/bisheng_2-grouped-perf/src/backend && ./.venv/bin/python -m pytest test/test_permission_service_batch_levels.py -q`
Expected: FAIL（`AttributeError: ... has no attribute 'get_permission_levels'`）

- [ ] **Step 3: 实现 `get_permission_levels`**

在 `permission_service.py` 的 `get_permission_level`（`:835`-`:898`）之后新增：

```python
    @classmethod
    async def get_permission_levels(
        cls,
        user_id: int,
        object_type: str,
        object_ids: list[str | int],
        login_user=None,
    ) -> dict[str, str | None]:
        """Batched equivalent of get_permission_level over many objects.

        Merges the per-object 4-level batch_check into a single OpenFGA
        batch_check request. Semantics are identical to calling
        get_permission_level once per object.
        """
        ids = [str(o) for o in object_ids]
        if not ids:
            return {}
        if login_user and login_user.is_admin():
            return {oid: PermissionLevel.owner.value for oid in ids}

        results: dict[str, str | None] = {}
        gates = await asyncio.gather(*[
            cls._evaluate_tenant_gate(
                user_id=user_id, object_type=object_type, object_id=oid, login_user=login_user)
            for oid in ids
        ])
        pending: list[str] = []
        for oid, (denied, shortcut) in zip(ids, gates):
            if denied:
                results[oid] = None
            elif shortcut is not None:
                results[oid] = shortcut
            else:
                pending.append(oid)
        if not pending:
            return results

        try:
            fga = await cls._aget_fga()
            if fga is None:
                implicit = await asyncio.gather(*[
                    cls._get_implicit_permission_level_after_gate(user_id, object_type, oid)
                    for oid in pending
                ])
                results.update(dict(zip(pending, implicit)))
                return results

            levels = list(PermissionLevel)
            checks = [
                {'user': f'user:{user_id}', 'relation': level.value, 'object': f'{object_type}:{oid}'}
                for oid in pending
                for level in levels
            ]
            flat = await fga.batch_check(checks)
            unresolved: list[str] = []
            for i, oid in enumerate(pending):
                row = flat[i * len(levels):(i + 1) * len(levels)]
                chosen = next((level.value for level, allowed in zip(levels, row) if allowed), None)
                if chosen is not None:
                    results[oid] = chosen
                else:
                    unresolved.append(oid)

            # legacy alias fallback (per object, merged per object_type)
            still_unresolved: list[str] = []
            for oid in unresolved:
                resolved_level = None
                for legacy_type in await cls._legacy_alias_object_types(object_type, oid):
                    legacy_checks = [
                        {'user': f'user:{user_id}', 'relation': level.value, 'object': f'{legacy_type}:{oid}'}
                        for level in levels
                    ]
                    legacy_results = await fga.batch_check(legacy_checks)
                    resolved_level = next(
                        (level.value for level, allowed in zip(levels, legacy_results) if allowed), None)
                    if resolved_level is not None:
                        break
                if resolved_level is not None:
                    results[oid] = resolved_level
                else:
                    still_unresolved.append(oid)

            implicit = await asyncio.gather(*[
                cls._get_implicit_permission_level_after_gate(user_id, object_type, oid)
                for oid in still_unresolved
            ])
            results.update(dict(zip(still_unresolved, implicit)))
            return results
        except FGAConnectionError as e:
            logger.error('OpenFGA unreachable during get_permission_levels: %s', e)
            for oid in pending:
                results.setdefault(oid, None)
            return results
        except Exception as e:
            logger.error('Error getting permission levels: %s', e)
            for oid in pending:
                results.setdefault(oid, None)
            return results
```

> 注意：`asyncio` 已在 `permission_service.py` 顶部导入则无需再加；若未导入，在文件顶部加 `import asyncio`。`FGAConnectionError`、`PermissionLevel`、`logger` 与 `get_permission_level` 用的是同一批符号。

- [ ] **Step 4: 运行单测，确认 PASS**

Run: `cd /Users/zhangguoqing/works/bisheng_2-grouped-perf/src/backend && ./.venv/bin/python -m pytest test/test_permission_service_batch_levels.py -q`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
cd /Users/zhangguoqing/works/bisheng_2-grouped-perf
git add src/backend/bisheng/permission/domain/services/permission_service.py src/backend/test/test_permission_service_batch_levels.py
git commit -m "feat: add PermissionService.get_permission_levels batched OpenFGA check"
```

---

### Task 3: ① 接入 `_format_accessible_spaces`（用批量 API 替换 gather）

**Files:**
- Modify: `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py:992-1004`

**Interfaces:**
- Consumes: `PermissionService.get_permission_levels`（Task 2）。
- Produces: `permission_levels` dict 语义不变（key = space id `int`，value = level），供 `_format_accessible_spaces` 后续 `_permission_level_to_space_user_role` 使用。

- [ ] **Step 1: 替换实现**

把 `:992-1004` 的：

```python
        if permission_space_ids:
            levels = await asyncio.gather(
                *[
                    PermissionService.get_permission_level(
                        user_id=self.login_user.user_id,
                        object_type="knowledge_space",
                        object_id=str(space_id),
                        login_user=self.login_user,
                    )
                    for space_id in permission_space_ids
                ]
            )
            permission_levels = {space_id: level for space_id, level in zip(permission_space_ids, levels)}
```

改为：

```python
        if permission_space_ids:
            level_map = await PermissionService.get_permission_levels(
                user_id=self.login_user.user_id,
                object_type="knowledge_space",
                object_ids=permission_space_ids,
                login_user=self.login_user,
            )
            permission_levels = {space_id: level_map.get(str(space_id)) for space_id in permission_space_ids}
```

- [ ] **Step 2: 运行 characterization + 直接测试，确认 PASS**

Run: `cd /Users/zhangguoqing/works/bisheng_2-grouped-perf/src/backend && ./.venv/bin/python -m pytest test/test_knowledge_space_service.py::TestFormatAccessibleSpacesCharacterization -q`
Expected: PASS（4 passed）

> characterization 里 `test_direct_grant_without_membership_maps_to_admin` mock 的是 `PermissionService.get_permission_level`。改用批量后该 patch 不再被调用，但断言仍应通过（该用例只有 1 个 space，走的是 `get_permission_levels`）。**若失败**：为该用例补 patch `PermissionService.get_permission_levels`（返回 `{'3': 'can_manage'}`），因为它现在是被调用方——这是测试适配，不改产品行为。

- [ ] **Step 3: 全文件回归**

Run: `cd /Users/zhangguoqing/works/bisheng_2-grouped-perf/src/backend && ./.venv/bin/python -m pytest test/test_knowledge_space_service.py -q`
Expected: passed 数 ≥ 136（40 个预存失败不新增）。若有新失败，多半是别处测试 patch 了 `get_permission_level` 而现在走批量 —— 逐个把这些测试的 patch 目标同步为 `get_permission_levels`（仅测试适配）。

- [ ] **Step 4: Commit**

```bash
cd /Users/zhangguoqing/works/bisheng_2-grouped-perf
git add -A
git commit -m "perf: batch grouped-space permission levels via get_permission_levels"
```

---

### Task 4: ② 共享 tuple_cache + precomputed permission level

**Files:**
- Modify: `src/backend/bisheng/permission/domain/services/fine_grained_permission_service.py:396-529`（加 `precomputed_permission_level` 参数）
- Modify: `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py:1811-1843`（`_get_effective_permission_ids` 透传 `tuple_cache` + `precomputed_permission_level`）
- Modify: `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py:1005-1015`（建 shared tuple_cache，把已算 level 传入）
- Test: `src/backend/test/test_effective_permission_precomputed_level.py`（新建）

**Interfaces:**
- Consumes: `get_effective_permission_ids_async` 现有参数（`tuple_cache` `:410`、`use_permission_level_fallback` `:409`）、`_PERMISSION_LEVEL_TO_RELATION`、`default_permission_ids_for_relation`。
- Produces: `get_effective_permission_ids_async(..., precomputed_permission_level=_LEVEL_UNSET)` — 当传入（含值为 `None`）时，`:518` 的 fallback 用它替代调用 `get_permission_level`；`_get_effective_permission_ids(object_type, object_id, *, space_id=None, tuple_cache=None, precomputed_permission_level=_LEVEL_UNSET)`。

- [ ] **Step 1: 写单测（precomputed level 时不调用 get_permission_level）**

新建 `src/backend/test/test_effective_permission_precomputed_level.py`：

```python
import pytest
from unittest.mock import AsyncMock, patch

from bisheng.permission.domain.services.fine_grained_permission_service import (
    FineGrainedPermissionService as FGS,
)
from bisheng.permission.domain.services.permission_service import PermissionService


@pytest.mark.asyncio
async def test_precomputed_level_skips_get_permission_level():
    login_user = type('U', (), {'user_id': 7, 'is_admin': lambda self: False})()

    # Force the fallback branch: no tuples, no bindings -> empty effective set.
    with patch.object(FGS, 'get_relation_models_map', new_callable=AsyncMock, return_value={}), \
         patch('bisheng.permission.domain.services.fine_grained_permission_service._get_bindings',
               new_callable=AsyncMock, return_value=[]), \
         patch.object(FGS, 'get_current_user_subject_strings', new_callable=AsyncMock, return_value=set()), \
         patch.object(FGS, 'get_binding_department_paths', new_callable=AsyncMock, return_value={}), \
         patch.object(FGS, 'build_resource_lineage', new_callable=AsyncMock,
                      return_value=[('knowledge_space', '9')]), \
         patch.object(PermissionService, '_get_fga', return_value=None), \
         patch.object(PermissionService, 'get_implicit_permission_level',
                      new_callable=AsyncMock, return_value=None), \
         patch.object(FGS, '_public_knowledge_space_viewer_permission_ids',
                      new_callable=AsyncMock, return_value=set()), \
         patch.object(PermissionService, 'get_permission_level',
                      new_callable=AsyncMock) as spy_level:
        result = await FGS.get_effective_permission_ids_async(
            login_user, 'knowledge_space', '9',
            precomputed_permission_level='can_read',
        )
    # get_permission_level must NOT be called when a precomputed level is supplied.
    spy_level.assert_not_awaited()
    # 'can_read' maps to view_space default permissions -> non-empty
    assert 'view_space' in result


@pytest.mark.asyncio
async def test_without_precomputed_falls_back_to_get_permission_level():
    login_user = type('U', (), {'user_id': 7, 'is_admin': lambda self: False})()
    with patch.object(FGS, 'get_relation_models_map', new_callable=AsyncMock, return_value={}), \
         patch('bisheng.permission.domain.services.fine_grained_permission_service._get_bindings',
               new_callable=AsyncMock, return_value=[]), \
         patch.object(FGS, 'get_current_user_subject_strings', new_callable=AsyncMock, return_value=set()), \
         patch.object(FGS, 'get_binding_department_paths', new_callable=AsyncMock, return_value={}), \
         patch.object(FGS, 'build_resource_lineage', new_callable=AsyncMock,
                      return_value=[('knowledge_space', '9')]), \
         patch.object(PermissionService, '_get_fga', return_value=None), \
         patch.object(PermissionService, 'get_implicit_permission_level',
                      new_callable=AsyncMock, return_value=None), \
         patch.object(FGS, '_public_knowledge_space_viewer_permission_ids',
                      new_callable=AsyncMock, return_value=set()), \
         patch.object(PermissionService, 'get_permission_level',
                      new_callable=AsyncMock, return_value='can_read') as spy_level:
        result = await FGS.get_effective_permission_ids_async(login_user, 'knowledge_space', '9')
    spy_level.assert_awaited_once()
    assert 'view_space' in result
```

> `'can_read' → view_space` 的具体权限 id 依赖 `default_permission_ids_for_relation` 的实际映射；若断言的权限 id 名不符，运行一次看实际返回值再把断言改成真实值（这是读取现状，不是改行为）。

- [ ] **Step 2: 运行，确认 FAIL（未知参数 / fallback 仍被调用）**

Run: `cd /Users/zhangguoqing/works/bisheng_2-grouped-perf/src/backend && ./.venv/bin/python -m pytest test/test_effective_permission_precomputed_level.py -q`
Expected: FAIL（`TypeError: unexpected keyword argument 'precomputed_permission_level'`）

- [ ] **Step 3: 加 `precomputed_permission_level` 参数**

在 `fine_grained_permission_service.py` 模块级（靠近其它常量处）加哨兵：

```python
_LEVEL_UNSET = object()
```

修改 `get_effective_permission_ids_async` 签名（`:409` 附近）新增参数：

```python
        use_permission_level_fallback: bool = True,
        tuple_cache: dict[str, list[dict]] | None = None,
        precomputed_permission_level=_LEVEL_UNSET,
```

把 `:518-524` 的 fallback：

```python
        if use_permission_level_fallback:
            level = await PermissionService.get_permission_level(
                user_id=login_user.user_id,
                object_type=object_type,
                object_id=str(object_id),
                login_user=login_user,
            )
            relation = _PERMISSION_LEVEL_TO_RELATION.get(level or '')
            effective_permissions = cls.default_permission_ids_for_relation(object_type, relation or '')
```

改为：

```python
        if use_permission_level_fallback:
            if precomputed_permission_level is not _LEVEL_UNSET:
                level = precomputed_permission_level
            else:
                level = await PermissionService.get_permission_level(
                    user_id=login_user.user_id,
                    object_type=object_type,
                    object_id=str(object_id),
                    login_user=login_user,
                )
            relation = _PERMISSION_LEVEL_TO_RELATION.get(level or '')
            effective_permissions = cls.default_permission_ids_for_relation(object_type, relation or '')
```

- [ ] **Step 4: 运行单测，确认 PASS**

Run: `cd /Users/zhangguoqing/works/bisheng_2-grouped-perf/src/backend && ./.venv/bin/python -m pytest test/test_effective_permission_precomputed_level.py -q`
Expected: PASS（2 passed）

- [ ] **Step 5: `_get_effective_permission_ids` 透传参数**

修改 `knowledge_space_service.py:1811-1843`。签名加参数：

```python
    async def _get_effective_permission_ids(
        self,
        object_type: str,
        object_id: int,
        *,
        space_id: int | None = None,
        tuple_cache: dict[str, list[dict]] | None = None,
        precomputed_permission_level=_LEVEL_UNSET,
    ) -> set[str]:
```

在该文件顶部 import 段加：`from bisheng.permission.domain.services.fine_grained_permission_service import _LEVEL_UNSET`（与现有 `FineGrainedPermissionService` 同源导入）。

把对 `get_effective_permission_ids_async(...)` 的调用（`:1831-1843`）补上两个参数：

```python
        ) = await FineGrainedPermissionService.get_effective_permission_ids_async(
            self.login_user,
            object_type,
            object_id,
            models=models,
            bindings=bindings,
            binding_department_paths=binding_department_paths,
            user_subject_strings=user_subject_strings,
            lineage=lineage,
            nearest_binding_wins=lineage_binding_can_override,
            return_match_metadata=True,
            use_permission_level_fallback=not lineage_binding_can_override,
            tuple_cache=tuple_cache,
            precomputed_permission_level=precomputed_permission_level,
        )
```

- [ ] **Step 6: `_format_accessible_spaces` 建 shared tuple_cache + 传 precomputed level**

修改 `knowledge_space_service.py:1005-1015`（`permission_id_space_ids` 的 gather）为：

```python
        if required_permission_id and permission_id_space_ids:
            shared_tuple_cache: dict[str, list[dict]] = {}
            permission_ids = await asyncio.gather(
                *[
                    self._get_effective_permission_ids(
                        "knowledge_space",
                        space_id,
                        tuple_cache=shared_tuple_cache,
                        precomputed_permission_level=permission_levels.get(space_id, _LEVEL_UNSET),
                    )
                    for space_id in permission_id_space_ids
                ]
            )
            permission_ids_map = {space_id: ids for space_id, ids in zip(permission_id_space_ids, permission_ids)}
```

> 等价性要点：`permission_levels` 由 Task 3 的 `get_permission_levels` 算出，key 为 `int` space id。`permission_space_ids`（进入 level 计算的）= 非本人且非 member；`permission_id_space_ids`（进入 effective 计算的）= 全部非本人。对「非本人但是 member」的 space，`permission_levels.get(space_id)` 缺失 → 传 `_LEVEL_UNSET` → 保持原 fallback 行为（原本这些 space 也未预算 level）。因此语义不变。

- [ ] **Step 7: characterization + 全文件回归**

Run: `cd /Users/zhangguoqing/works/bisheng_2-grouped-perf/src/backend && ./.venv/bin/python -m pytest test/test_knowledge_space_service.py::TestFormatAccessibleSpacesCharacterization test/test_effective_permission_precomputed_level.py -q`
Expected: PASS
Run: `cd /Users/zhangguoqing/works/bisheng_2-grouped-perf/src/backend && ./.venv/bin/python -m pytest test/test_knowledge_space_service.py -q`
Expected: passed ≥ 136，预存 40 失败不新增

- [ ] **Step 8: Commit**

```bash
cd /Users/zhangguoqing/works/bisheng_2-grouped-perf
git add -A
git commit -m "perf: share tuple_cache and reuse precomputed level in grouped spaces"
```

---

### Task 5: ③ per-user 短 TTL 缓存 `_list_accessible_spaces`

**Files:**
- Create: `src/backend/bisheng/knowledge/domain/services/space_list_cache.py`
- Modify: `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py:5631-5663`（`_list_accessible_spaces` 读写缓存）
- Test: `src/backend/test/test_space_list_cache.py`（新建）

**Interfaces:**
- Consumes: `get_redis_client`（`bisheng.core.cache.redis_manager`）、`KnowledgeSpaceInfoResp`（`_format_accessible_spaces` 实际返回类型）。
- Produces: `SpaceListCache.get(user_id: int, order_by: str) -> list | None`、`SpaceListCache.set(user_id: int, order_by: str, spaces: list) -> None`、模块常量 `SPACE_LIST_CACHE_TTL = 15`。

- [ ] **Step 1: 写缓存 helper 单测**

新建 `src/backend/test/test_space_list_cache.py`：

```python
import pytest
from unittest.mock import AsyncMock, patch

from bisheng.knowledge.domain.services.space_list_cache import SpaceListCache, SPACE_LIST_CACHE_TTL


class _FakeRedis:
    def __init__(self):
        self.store = {}
    async def aget(self, key):
        return self.store.get(key)
    async def aset(self, key, value, expiration=None):
        self.store[key] = value


@pytest.mark.asyncio
async def test_set_then_get_roundtrip_preserves_fields():
    from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceInfoResp
    fake = _FakeRedis()
    space = KnowledgeSpaceInfoResp(id=3, name='n', user_id=88)  # 按 KnowledgeSpaceInfoResp 真实必填字段补齐
    with patch('bisheng.knowledge.domain.services.space_list_cache.get_redis_client',
               new_callable=AsyncMock, return_value=fake):
        await SpaceListCache.set(7, 'update_time', [space])
        got = await SpaceListCache.get(7, 'update_time')
    assert got is not None
    assert [s.id for s in got] == [3]
    assert got[0].name == 'n'


@pytest.mark.asyncio
async def test_get_miss_returns_none():
    fake = _FakeRedis()
    with patch('bisheng.knowledge.domain.services.space_list_cache.get_redis_client',
               new_callable=AsyncMock, return_value=fake):
        assert await SpaceListCache.get(7, 'update_time') is None


@pytest.mark.asyncio
async def test_redis_unavailable_degrades_gracefully():
    with patch('bisheng.knowledge.domain.services.space_list_cache.get_redis_client',
               new_callable=AsyncMock, return_value=None):
        assert await SpaceListCache.get(7, 'update_time') is None
        await SpaceListCache.set(7, 'update_time', [])  # must not raise
```

> 说明：`KnowledgeSpaceInfoResp` 的真实导入路径与必填字段，执行时从 `knowledge_space_service.py` 顶部 import 段查得（它在那里被使用），把测试里的 import 和构造参数改成真实值。

- [ ] **Step 2: 运行，确认 FAIL（模块不存在）**

Run: `cd /Users/zhangguoqing/works/bisheng_2-grouped-perf/src/backend && ./.venv/bin/python -m pytest test/test_space_list_cache.py -q`
Expected: FAIL（`ModuleNotFoundError: ...space_list_cache`）

- [ ] **Step 3: 实现缓存 helper**

新建 `src/backend/bisheng/knowledge/domain/services/space_list_cache.py`：

```python
"""Per-user short-TTL cache for a user's accessible knowledge-space list.

Pure TTL, no active invalidation (grouped/visible-space list tolerates a
few seconds of staleness). Degrades to no-op when Redis is unavailable.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

KEY_PREFIX = 'ksp:accessible:'
SPACE_LIST_CACHE_TTL = 15  # seconds


def _tenant_id() -> int:
    from bisheng.core.context.tenant import get_current_tenant_id
    return get_current_tenant_id() or 1


def _key(user_id: int, order_by: str) -> str:
    return f'{KEY_PREFIX}{_tenant_id()}:{user_id}:{order_by}'


class SpaceListCache:
    @classmethod
    async def get(cls, user_id: int, order_by: str):
        try:
            redis = await _get_redis()
            if redis is None:
                return None
            raw = await redis.aget(_key(user_id, order_by))
            if not raw:
                return None
            from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceInfoResp
            return [KnowledgeSpaceInfoResp.model_validate(item) for item in raw]
        except Exception as e:
            logger.debug('SpaceListCache.get error: %s', e)
            return None

    @classmethod
    async def set(cls, user_id: int, order_by: str, spaces: list) -> None:
        try:
            redis = await _get_redis()
            if redis is None:
                return
            payload = [s.model_dump(mode='json') for s in spaces]
            await redis.aset(_key(user_id, order_by), payload, expiration=SPACE_LIST_CACHE_TTL)
        except Exception as e:
            logger.debug('SpaceListCache.set error: %s', e)


async def _get_redis():
    try:
        from bisheng.core.cache.redis_manager import get_redis_client
        return await get_redis_client()
    except Exception:
        return None
```

> `KnowledgeSpaceInfoResp` 的真实导入路径：若它不是从 `knowledge_space_service` 直接导出，改成其定义模块。`model_validate`/`model_dump` 为 Pydantic v2 API（本仓库已用）。

- [ ] **Step 4: 运行 helper 单测，确认 PASS**

Run: `cd /Users/zhangguoqing/works/bisheng_2-grouped-perf/src/backend && ./.venv/bin/python -m pytest test/test_space_list_cache.py -q`
Expected: PASS（3 passed）

- [ ] **Step 5: 接入 `_list_accessible_spaces`**

修改 `knowledge_space_service.py:5631-5663`，在方法开头读缓存、结尾写缓存：

```python
    async def _list_accessible_spaces(
        self,
        order_by: str = "update_time",
    ) -> list[KnowledgeRead]:
        cached = await SpaceListCache.get(self.login_user.user_id, order_by)
        if cached is not None:
            return cached

        members = await SpaceChannelMemberDao.async_get_user_space_members(self.login_user.user_id)
        # ... 原有逻辑不变 ...
        formatted = await self._format_accessible_spaces(
            list(space_ids),
            order_by,
            memberships=members,
            required_permission_id="view_space",
        )
        await SpaceListCache.set(self.login_user.user_id, order_by, formatted)
        return formatted
```

在文件顶部 import 段加：`from bisheng.knowledge.domain.services.space_list_cache import SpaceListCache`。

- [ ] **Step 6: characterization + 全文件回归**

Run: `cd /Users/zhangguoqing/works/bisheng_2-grouped-perf/src/backend && ./.venv/bin/python -m pytest test/test_knowledge_space_service.py -q`
Expected: passed ≥ 136（预存 40 不新增）。缓存 helper 在测试环境（无 Redis）降级为 no-op，不影响现有测试。

- [ ] **Step 7: Commit**

```bash
cd /Users/zhangguoqing/works/bisheng_2-grouped-perf
git add -A
git commit -m "perf: cache per-user accessible spaces list with 15s TTL"
```

---

### Task 6: ④ 分段耗时日志（+⑤ batch_check 日志降级）

**Files:**
- Modify: `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`（`_list_accessible_spaces` / `_format_accessible_spaces` 埋点）
- Modify: `src/backend/bisheng/core/openfga/client.py:152`（INFO → DEBUG）

**Interfaces:**
- Consumes: `time.perf_counter`（`time` 已在该文件导入则复用）、模块 `logger`。
- Produces: 无对外接口变化，仅日志。

- [ ] **Step 1: `_format_accessible_spaces` 分段埋点**

在 `_format_accessible_spaces` 内用 `time.perf_counter()` 记录各段，方法返回前输出一行 summary（放在 `return await self._decorate_department_metadata(...)` 之前，先算好 decorate 再记；或包裹计时）。最小侵入示例——在方法开头 `t0 = time.perf_counter()`，在关键点记录差值，末尾：

```python
        logger.info(
            "grouped_spaces_perf user_id=%s n_spaces=%s levels_ms=%.1f effective_ms=%.1f "
            "file_count_ms=%.1f decorate_ms=%.1f total_ms=%.1f",
            self.login_user.user_id, len(spaces),
            levels_ms, effective_ms, file_count_ms, decorate_ms,
            (time.perf_counter() - t0) * 1000,
        )
```

各 `*_ms` 用围绕对应 `await` 的 `perf_counter` 差值算出（`levels_ms` 围绕 Task 3 的 `get_permission_levels`；`effective_ms` 围绕 Task 4 的 gather；`file_count_ms` 围绕 `async_count_success_files_batch`；`decorate_ms` 围绕 `_decorate_department_metadata`）。若 `time` 未导入，在文件顶部加 `import time`。

- [ ] **Step 2: `_list_accessible_spaces` 记 cache_hit + stage1**

在 `_list_accessible_spaces` 缓存命中分支记 `cache_hit=1`、未命中记 `cache_hit=0` 并计 stage1 收集耗时：

```python
        cached = await SpaceListCache.get(self.login_user.user_id, order_by)
        if cached is not None:
            logger.info("list_accessible_spaces cache_hit=1 user_id=%s n=%s", self.login_user.user_id, len(cached))
            return cached
        _t = time.perf_counter()
        members = await SpaceChannelMemberDao.async_get_user_space_members(self.login_user.user_id)
        # ... collect space_ids ...
        collect_ms = (time.perf_counter() - _t) * 1000
        logger.info("list_accessible_spaces cache_hit=0 user_id=%s collect_ms=%.1f", self.login_user.user_id, collect_ms)
```

- [ ] **Step 3: ⑤ batch_check 日志降级**

`core/openfga/client.py:152` 把 `logger.info(` 改为 `logger.debug(`（`[openfga-debug] batch_check ...` 那条），其余不动。

- [ ] **Step 4: 冒烟 —— 确认不报错、日志可见**

Run: `cd /Users/zhangguoqing/works/bisheng_2-grouped-perf/src/backend && ./.venv/bin/python -m pytest test/test_knowledge_space_service.py::TestFormatAccessibleSpacesCharacterization -q -o log_cli=true --log-cli-level=INFO`
Expected: PASS（4 passed），并能在输出看到 `grouped_spaces_perf ...` 行。

- [ ] **Step 5: 全文件回归 + Commit**

Run: `cd /Users/zhangguoqing/works/bisheng_2-grouped-perf/src/backend && ./.venv/bin/python -m pytest test/test_knowledge_space_service.py -q`
Expected: passed ≥ 136（预存 40 不新增）

```bash
cd /Users/zhangguoqing/works/bisheng_2-grouped-perf
git add -A
git commit -m "chore: add grouped-spaces perf logging and demote batch_check log to debug"
```

---

## 完成标准
- characterization（Task 1）自始至终全绿 → 权限行为等价
- `get_permission_levels`、`precomputed_permission_level`、`SpaceListCache` 三组新单测全绿
- `test_knowledge_space_service.py` 回归 passed 数 ≥ 136，预存 40 失败不新增
- 日志可观测各段耗时与 cache 命中

## 后续（非本计划范围）
`get_permission_levels` 与 shared tuple_cache 可平移到 feat/2.5.0-sg 上其它 per-space 扇出点（`:3287`/`:3388`、`:4936`、`:5917`/`:5940`）；portal 侧 P0/P1/P2 另议。
