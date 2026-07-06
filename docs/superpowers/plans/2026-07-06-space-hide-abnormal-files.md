# 知识空间文件列表隐藏异常文件 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 client 知识空间文件列表中，对普通成员隐藏他人上传的「违规(7)/解析失败(3)/解析超时(6)」文件；管理者与上传人本人仍可见。

**Architecture:** 后端在三条读路径共享的唯一 ReBAC 可见性选点 `KnowledgeSpaceService._filter_visible_child_items` 中追加「受限状态可见性」规则；管理者标志由 `_build_child_permission_context` 按空间预置一次（`manage_space_relation` 是否在有效权限内）。前端移除成员侧的状态强制排除，改由后端统一强制。

**Tech Stack:** Python 3 / FastAPI / SQLModel / pytest（后端）；React / TypeScript / Jest（client 前端）。

## Global Constraints

- 受限状态集：`MEMBER_HIDDEN_FILE_STATUSES = {3 FAILED, 6 TIMEOUT, 7 VIOLATION}`（逐字，来自 spec §2）。
- 管理者判定：`"manage_space_relation" in _get_effective_permission_ids("knowledge_space", space_id)`（涵盖全局管理员/创建者/空间 admin）。
- 「上传人」= `KnowledgeFile.user_id == login_user.user_id`。
- 文件夹（`file_type == FileType.DIR.value`）永不被本规则隐藏。
- 后端测试解释器：`src/backend/.venv/bin/python`；后端测试文件：`src/backend/test/test_knowledge_space_service.py`（单元 + mock 风格）。
- 全部改动在 bisheng_2 worktree `/Users/zhangguoqing/works/bisheng_2-space-hide-abnormal-files`（分支 `feat/2.5.0-sg-space-hide-abnormal-files`）；portal 不改。
- 范围外（勿改）：`my-uploaded-files`、platform 知识库列表、department 审批文件叠加、folder-stats 原始 `file_num` 的 SQL。

---

## Task 0: 环境准备与基线

**Files:** 无代码改动（环境）。

- [ ] **Step 1: 确认 worktree 后端虚拟环境可用**

新 worktree 无独立 `.venv`（gitignore）。建立可运行 worktree 代码的解释器：优先复用主 checkout 的 venv 但指向本 worktree 源码。

Run:
```bash
cd /Users/zhangguoqing/works/bisheng_2-space-hide-abnormal-files/src/backend
ls .venv/bin/python 2>/dev/null && echo "venv exists" || python3 -m venv .venv
# 若为新建 venv，安装依赖（按仓库既有方式）：
# .venv/bin/python -m pip install -e . 或 -r requirements（参考主 checkout）
```
Expected: 存在可执行 `src/backend/.venv/bin/python`。若依赖缺失导致导入失败，先补齐再继续。

- [ ] **Step 2: 跑目标测试文件确认基线通过**

Run:
```bash
cd /Users/zhangguoqing/works/bisheng_2-space-hide-abnormal-files/src/backend
.venv/bin/python -m pytest test/test_knowledge_space_service.py -q
```
Expected: 全部 PASS（0 failures）。若有预存失败，先记录并向用户确认再继续。

---

## Task 1: 常量 `MEMBER_HIDDEN_FILE_STATUSES` + 纯过滤 helper

**Files:**
- Modify: `src/backend/bisheng/knowledge/domain/models/knowledge_file.py`（在 `KnowledgeFileStatus` 定义后新增常量，约 `:24`）
- Modify: `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`（导入常量 `:102-108`；在 `_filter_visible_child_items` 前新增静态方法，约 `:5659`）
- Test: `src/backend/test/test_knowledge_space_service.py`

**Interfaces:**
- Produces: `MEMBER_HIDDEN_FILE_STATUSES: frozenset[int]`（模块 `knowledge_file`）；`KnowledgeSpaceService._hide_restricted_status_items(items, *, owner_user_id) -> list`。

- [ ] **Step 1: 写失败测试**

在 `test/test_knowledge_space_service.py` 末尾追加（顶部已导入 `FileType, KnowledgeFile, KnowledgeFileStatus`；`_make_file`、`_load_service_class` 已存在）：

```python
def test_hide_restricted_status_items_member_view():
    KnowledgeSpaceService = _load_service_class()
    owner_id = 7
    items = [
        _make_file(file_id=1, user_id=7, status=KnowledgeFileStatus.SUCCESS.value),      # 本人成功 -> 保留
        _make_file(file_id=2, user_id=7, status=KnowledgeFileStatus.FAILED.value),       # 本人失败 -> 保留
        _make_file(file_id=3, user_id=99, status=KnowledgeFileStatus.SUCCESS.value),     # 他人成功 -> 保留
        _make_file(file_id=4, user_id=99, status=KnowledgeFileStatus.FAILED.value),      # 他人失败 -> 去除
        _make_file(file_id=5, user_id=99, status=KnowledgeFileStatus.TIMEOUT.value),     # 他人超时 -> 去除
        _make_file(file_id=6, user_id=99, status=KnowledgeFileStatus.VIOLATION.value),   # 他人违规 -> 去除
        _make_file(file_id=7, user_id=99, status=KnowledgeFileStatus.VIOLATION.value,
                   file_type=FileType.DIR.value),                                        # 文件夹 -> 保留
    ]

    kept = KnowledgeSpaceService._hide_restricted_status_items(items, owner_user_id=owner_id)
    kept_ids = {f.id for f in kept}

    assert kept_ids == {1, 2, 3, 7}
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd /Users/zhangguoqing/works/bisheng_2-space-hide-abnormal-files/src/backend
.venv/bin/python -m pytest test/test_knowledge_space_service.py::test_hide_restricted_status_items_member_view -q
```
Expected: FAIL（`AttributeError: ... has no attribute '_hide_restricted_status_items'`）。

- [ ] **Step 3: 加常量**

在 `bisheng/knowledge/domain/models/knowledge_file.py` 的 `KnowledgeFileStatus` 类定义之后（第 23 行 `VIOLATION = 7` 之后、第 25 行 `class QAStatus` 之前）插入：

```python

MEMBER_HIDDEN_FILE_STATUSES = frozenset({
    KnowledgeFileStatus.FAILED.value,     # 3 解析失败
    KnowledgeFileStatus.TIMEOUT.value,    # 6 解析超时
    KnowledgeFileStatus.VIOLATION.value,  # 7 违规
})
```

- [ ] **Step 4: 导入常量并加静态 helper**

在 `bisheng/knowledge/domain/services/knowledge_space_service.py` 的导入块（第 102-108 行）加入常量：

```python
from bisheng.knowledge.domain.models.knowledge_file import (
    KnowledgeFile,
    KnowledgeFileDao,
    KnowledgeFileStatus,
    FileType,
    FileSource,
    MEMBER_HIDDEN_FILE_STATUSES,
)
```

在 `_filter_visible_child_items`（第 5660 行 `async def _filter_visible_child_items`）**之前**插入静态方法：

```python
    @staticmethod
    def _hide_restricted_status_items(
        items: List[KnowledgeFile],
        *,
        owner_user_id: Optional[int],
    ) -> List[KnowledgeFile]:
        """Drop files whose status is restricted (parse-failed / timeout / violation)
        unless the current user uploaded them. Folders are never dropped here.
        Callers gate this on the viewer NOT being a space manager."""
        return [
            item
            for item in items
            if item.file_type == FileType.DIR.value
            or item.status not in MEMBER_HIDDEN_FILE_STATUSES
            or item.user_id == owner_user_id
        ]
```

- [ ] **Step 5: 跑测试确认通过**

Run:
```bash
cd /Users/zhangguoqing/works/bisheng_2-space-hide-abnormal-files/src/backend
.venv/bin/python -m pytest test/test_knowledge_space_service.py::test_hide_restricted_status_items_member_view -q
```
Expected: PASS。

- [ ] **Step 6: 提交**

```bash
cd /Users/zhangguoqing/works/bisheng_2-space-hide-abnormal-files
git add src/backend/bisheng/knowledge/domain/models/knowledge_file.py \
        src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py \
        src/backend/test/test_knowledge_space_service.py
git commit -m "feat(knowledge): add MEMBER_HIDDEN_FILE_STATUSES + restricted-status filter helper"
```

---

## Task 2: 管理者判定 `_space_user_can_view_all_statuses` + 预置到 context

**Files:**
- Modify: `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`（新增方法；在 `_build_child_permission_context` 返回 dict 增加键，约 `:1730-1746`）
- Test: `src/backend/test/test_knowledge_space_service.py`

**Interfaces:**
- Consumes: `_get_effective_permission_ids("knowledge_space", space_id) -> set[str]`（已存在，`:1687`）。
- Produces: `KnowledgeSpaceService._space_user_can_view_all_statuses(space_id) -> bool`；`_build_child_permission_context` 返回 dict 新增键 `"can_view_all_statuses": bool`。

- [ ] **Step 1: 写失败测试**

在 `test/test_knowledge_space_service.py` 末尾追加（`service` fixture、`AsyncMock`、`patch.object` 已可用）：

```python
@pytest.mark.asyncio
async def test_space_user_can_view_all_statuses_true_for_manager(service):
    with patch.object(
        service, '_get_effective_permission_ids', new_callable=AsyncMock,
        return_value={'view_space', 'manage_space_relation'},
    ):
        assert await service._space_user_can_view_all_statuses(1) is True


@pytest.mark.asyncio
async def test_space_user_can_view_all_statuses_false_for_member(service):
    with patch.object(
        service, '_get_effective_permission_ids', new_callable=AsyncMock,
        return_value={'view_space', 'upload_file'},
    ):
        assert await service._space_user_can_view_all_statuses(1) is False
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd /Users/zhangguoqing/works/bisheng_2-space-hide-abnormal-files/src/backend
.venv/bin/python -m pytest test/test_knowledge_space_service.py -k space_user_can_view_all_statuses -q
```
Expected: FAIL（`AttributeError: ... '_space_user_can_view_all_statuses'`）。

- [ ] **Step 3: 实现方法**

在 `knowledge_space_service.py` 的 `_get_effective_permission_ids` 之后（第 1728 行 `return effective_permissions` 之后、第 1730 行 `_build_child_permission_context` 之前）插入：

```python
    async def _space_user_can_view_all_statuses(self, space_id: int) -> bool:
        """Managers (owner / can_manage, incl. global admin & space creator) see
        files in any status; regular members only see restricted-status files
        (parse-failed / timeout / violation) they uploaded themselves."""
        space_permissions = await self._get_effective_permission_ids("knowledge_space", space_id)
        return "manage_space_relation" in space_permissions
```

- [ ] **Step 4: 预置到 context**

修改 `_build_child_permission_context`（第 1730 行）。在其 `return {...}`（第 1737-1746 行）之前先计算标志，并把键加入返回 dict：

将
```python
        membership_permission_ids = await self._membership_permission_ids(space_id)
        public_space_permission_ids = await self._public_space_viewer_permission_ids([("knowledge_space", space_id)])
        return {
            "models": models,
            "bindings": bindings,
            "binding_department_paths": binding_department_paths,
            "user_subject_strings": user_subject_strings,
            "membership_permission_ids": membership_permission_ids,
            "public_space_permission_ids": public_space_permission_ids,
            "tuple_cache": {},
            "tuple_department_paths": {},
        }
```
改为
```python
        membership_permission_ids = await self._membership_permission_ids(space_id)
        public_space_permission_ids = await self._public_space_viewer_permission_ids([("knowledge_space", space_id)])
        can_view_all_statuses = await self._space_user_can_view_all_statuses(space_id)
        return {
            "models": models,
            "bindings": bindings,
            "binding_department_paths": binding_department_paths,
            "user_subject_strings": user_subject_strings,
            "membership_permission_ids": membership_permission_ids,
            "public_space_permission_ids": public_space_permission_ids,
            "can_view_all_statuses": can_view_all_statuses,
            "tuple_cache": {},
            "tuple_department_paths": {},
        }
```

- [ ] **Step 5: 跑测试确认通过**

Run:
```bash
cd /Users/zhangguoqing/works/bisheng_2-space-hide-abnormal-files/src/backend
.venv/bin/python -m pytest test/test_knowledge_space_service.py -k space_user_can_view_all_statuses -q
```
Expected: PASS（2 passed）。

- [ ] **Step 6: 提交**

```bash
cd /Users/zhangguoqing/works/bisheng_2-space-hide-abnormal-files
git add src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py \
        src/backend/test/test_knowledge_space_service.py
git commit -m "feat(knowledge): compute space-manager flag into child permission context"
```

---

## Task 3: 在 `_filter_visible_child_items` 应用受限状态规则

**Files:**
- Modify: `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`（`_filter_visible_child_items`，第 5660-5682 行）
- Test: `src/backend/test/test_knowledge_space_service.py`

**Interfaces:**
- Consumes: `_hide_restricted_status_items`（Task 1）、context 键 `"can_view_all_statuses"`（Task 2）、`self.login_user.user_id`。
- Produces: `_filter_visible_child_items` 在 ReBAC 过滤后，对非管理者再按受限状态过滤。覆盖 list / search / `visible_success_file_num`。

- [ ] **Step 1: 写失败测试**

在 `test/test_knowledge_space_service.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_filter_visible_child_items_hides_restricted_for_member(service):
    items = [
        _make_file(file_id=1, user_id=7, status=KnowledgeFileStatus.SUCCESS.value),
        _make_file(file_id=2, user_id=7, status=KnowledgeFileStatus.VIOLATION.value),    # 本人违规 -> 保留
        _make_file(file_id=3, user_id=99, status=KnowledgeFileStatus.SUCCESS.value),
        _make_file(file_id=4, user_id=99, status=KnowledgeFileStatus.VIOLATION.value),   # 他人违规 -> 去除
        _make_file(file_id=5, user_id=99, status=KnowledgeFileStatus.FAILED.value),      # 他人失败 -> 去除
    ]
    # login_user.user_id == 7（见 _make_login_user 默认）
    with patch.object(
        service, '_get_child_item_effective_permission_ids', new_callable=AsyncMock,
        return_value={'view_file', 'view_folder'},
    ):
        kept = await service._filter_visible_child_items(
            items, space_id=1, context={"can_view_all_statuses": False},
        )
    assert {f.id for f in kept} == {1, 2, 3}


@pytest.mark.asyncio
async def test_filter_visible_child_items_manager_sees_all(service):
    items = [
        _make_file(file_id=4, user_id=99, status=KnowledgeFileStatus.VIOLATION.value),
        _make_file(file_id=5, user_id=99, status=KnowledgeFileStatus.FAILED.value),
    ]
    with patch.object(
        service, '_get_child_item_effective_permission_ids', new_callable=AsyncMock,
        return_value={'view_file', 'view_folder'},
    ):
        kept = await service._filter_visible_child_items(
            items, space_id=1, context={"can_view_all_statuses": True},
        )
    assert {f.id for f in kept} == {4, 5}
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd /Users/zhangguoqing/works/bisheng_2-space-hide-abnormal-files/src/backend
.venv/bin/python -m pytest test/test_knowledge_space_service.py -k filter_visible_child_items -q
```
Expected: FAIL（`test_..._hides_restricted_for_member` 断言失败：当前返回含 4、5）。

- [ ] **Step 3: 实现**

修改 `_filter_visible_child_items`（第 5680-5682 行结尾）。将
```python
        visibility = await asyncio.gather(*(can_view(item) for item in items))
        return [item for item, allowed in zip(items, visibility) if allowed]
```
改为
```python
        visibility = await asyncio.gather(*(can_view(item) for item in items))
        visible = [item for item, allowed in zip(items, visibility) if allowed]
        if not permission_context.get("can_view_all_statuses", False):
            visible = self._hide_restricted_status_items(
                visible, owner_user_id=self.login_user.user_id,
            )
        return visible
```

- [ ] **Step 4: 跑测试确认通过**

Run:
```bash
cd /Users/zhangguoqing/works/bisheng_2-space-hide-abnormal-files/src/backend
.venv/bin/python -m pytest test/test_knowledge_space_service.py -k filter_visible_child_items -q
```
Expected: PASS（2 passed）。

- [ ] **Step 5: 跑整文件回归**

Run:
```bash
cd /Users/zhangguoqing/works/bisheng_2-space-hide-abnormal-files/src/backend
.venv/bin/python -m pytest test/test_knowledge_space_service.py -q
```
Expected: 全部 PASS（含既有用例）。若既有依赖 `_filter_visible_child_items` 的用例受影响，检查其是否传入 `can_view_all_statuses`——默认 `.get(..., False)` 对未含该键的旧 context 视为「非管理者」；如既有测试用管理者语义但缺该键导致回归，按需在其 context 补键或改用管理者标志。

- [ ] **Step 6: 提交**

```bash
cd /Users/zhangguoqing/works/bisheng_2-space-hide-abnormal-files
git add src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py \
        src/backend/test/test_knowledge_space_service.py
git commit -m "feat(knowledge): hide restricted-status files from non-manager viewers in space list/search"
```

---

## Task 4: 前端移除成员侧状态强制排除 + 删除常量

**Files:**
- Modify: `src/frontend/client/src/pages/knowledge/hooks/useFileManager.ts`（`:6` import、`:220-222` loadFiles、`:478-481` 轮询）
- Modify: `src/frontend/client/src/pages/knowledge/sidebar/KnowledgeSpaceItem.tsx`（`:4` import、`:260-264` 文件夹树 prop）
- Modify: `src/frontend/client/src/api/knowledge.ts`（`:898` 删除常量、`:1639` 注释）
- Modify: `src/frontend/client/src/pages/knowledge/sidebar/KnowledgeFolderTree.tsx`（`:33` 注释）

**Interfaces:**
- Consumes: 后端选点（Task 3）已强制受限状态可见性。前端不再传成员专用的 `file_status`。

- [ ] **Step 1: 改 `useFileManager.ts` loadFiles（约 :219-222）**

将
```ts
                const isMember = activeSpace.role === SpaceRole.MEMBER;
                const fileStatusNums = statusFilter.length > 0
                    ? statusFilter.map(fileStatusToNumber)
                    : isMember ? SPACE_CHILDREN_STATUS_NUMS_EXCLUDE_FAILED : undefined;
```
改为
```ts
                const isMember = activeSpace.role === SpaceRole.MEMBER;
                const fileStatusNums = statusFilter.length > 0
                    ? statusFilter.map(fileStatusToNumber)
                    : undefined;
```
（保留 `const isMember`：第 282 行审批文件逻辑仍使用它。）

- [ ] **Step 2: 改 `useFileManager.ts` refreshLoadedStatuses（约 :478-481）**

将
```ts
            const isMember = activeSpace.role === SpaceRole.MEMBER;
            const fileStatusNums = statusFilter.length > 0
                ? statusFilter.map(fileStatusToNumber)
                : isMember ? SPACE_CHILDREN_STATUS_NUMS_EXCLUDE_FAILED : undefined;
```
改为
```ts
            const fileStatusNums = statusFilter.length > 0
                ? statusFilter.map(fileStatusToNumber)
                : undefined;
```
（此处 `isMember` 改后无其他用途，随删除声明。）

- [ ] **Step 3: 改 `useFileManager.ts` import（:6）**

从第 6 行导入中删除 `SPACE_CHILDREN_STATUS_NUMS_EXCLUDE_FAILED,`（保留同块其余导入）。

- [ ] **Step 4: 改 `KnowledgeSpaceItem.tsx` 文件夹树 prop（约 :260-264）**

将
```tsx
                        fileStatus={
                            space.role === SpaceRole.MEMBER
                                ? SPACE_CHILDREN_STATUS_NUMS_EXCLUDE_FAILED
                                : undefined
                        }
```
整段删除（`KnowledgeFolderTree` 的 `fileStatus?` 为可选，不传即 `undefined`，成员与管理者一致看全部文件夹）。同时从第 4 行 import 删除 `SPACE_CHILDREN_STATUS_NUMS_EXCLUDE_FAILED`。

- [ ] **Step 5: 删除常量与清理注释**

- `src/api/knowledge.ts:898`：删除 `export const SPACE_CHILDREN_STATUS_NUMS_EXCLUDE_FAILED: number[] = [1, 2, 4, 5, 6, 7];`（保留第 901 行 `SPACE_CHILDREN_STATUS_SUCCESS_ONLY`）。
- `src/api/knowledge.ts:1639`、`src/pages/knowledge/sidebar/KnowledgeFolderTree.tsx:33`：删除/改写引用了该常量名的注释（避免留下指向已删常量的说明）。

- [ ] **Step 6: 类型检查 + 悬挂引用断言**

Run:
```bash
cd /Users/zhangguoqing/works/bisheng_2-space-hide-abnormal-files/src/frontend/client
npx tsc --noEmit
grep -rn "SPACE_CHILDREN_STATUS_NUMS_EXCLUDE_FAILED" src
```
Expected: `tsc` 无错误；grep 无任何输出（常量与所有引用已清除）。

- [ ] **Step 7: 提交**

```bash
cd /Users/zhangguoqing/works/bisheng_2-space-hide-abnormal-files
git add src/frontend/client/src/pages/knowledge/hooks/useFileManager.ts \
        src/frontend/client/src/pages/knowledge/sidebar/KnowledgeSpaceItem.tsx \
        src/frontend/client/src/pages/knowledge/sidebar/KnowledgeFolderTree.tsx \
        src/frontend/client/src/api/knowledge.ts
git commit -m "feat(client): rely on backend for restricted-status visibility in space file list"
```

---

## Task 5: 端到端人工验证（可选但推荐）

**Files:** 无。

- [ ] **Step 1: 起后端 + client，用三类账号验证**

用普通成员账号打开某知识空间文件列表：确认看不到「他人」上传的 违规/解析失败/解析超时 文件，但能看到「自己」上传的同类文件与所有正常文件。用空间管理员/创建者账号：确认看到全部。搜索与文件夹进入同样表现。

Expected: 行为符合 spec §3；成员显式筛「违规」时只看到自己的违规文件。

---

## Self-Review（作者自检）

- **Spec 覆盖**：§3 规则 → Task 1(helper)+Task 3(应用)；§4/§7.2 管理者判定 → Task 2；§7.1 常量+helper → Task 1；§7.3 选点 → Task 3；§8 前端 → Task 4；§10 测试 → 各任务 TDD + Task 4 typecheck + Task 5 e2e。范围外项（`my-uploaded-files`/platform/审批叠加/`file_num` SQL）未建任务，符合 §5/§11。
- **占位符**：无 TBD/TODO；所有代码步骤含完整前后代码。
- **类型一致**：`_hide_restricted_status_items(items, *, owner_user_id)`、`_space_user_can_view_all_statuses(space_id) -> bool`、context 键 `"can_view_all_statuses"`、常量 `MEMBER_HIDDEN_FILE_STATUSES` 在 Task 1/2/3 间命名一致；测试对 `_make_file`/`_make_login_user`（默认 `user_id=7`, `is_admin=False`）引用与源码一致。
