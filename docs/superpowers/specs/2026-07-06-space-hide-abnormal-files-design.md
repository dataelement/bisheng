# 知识空间文件列表隐藏异常文件（违规/解析失败/解析超时）设计

- 日期：2026-07-06
- 分支：`feat/2.5.0-sg-space-hide-abnormal-files`（基于 `feat/2.5.0-sg`）
- 仓库：bisheng_2（全部改动在此；portal/shougang 无需改动）
- 状态：已评审通过；方案在计划阶段据实精化为「单一可见性选点」实现（见 §4）

## 1. 背景与需求

client 门户「知识空间」文件列表界面中，**违规、上传失败、解析失败的文件不应出现在该界面**；
**仅有管理员和上传人本人可以看到上述状态的文件**。

即：这是一条**可见性 / 权限**规则，普通成员看不到他人的异常文件，但管理者和文件上传人本人能看到。

## 2. 术语与文件状态

文件状态枚举 `KnowledgeFileStatus`（`bisheng/knowledge/domain/models/knowledge_file.py:16`）：

| 值 | 名称 | 含义 |
|----|------|------|
| 1 | PROCESSING | 处理中 |
| 2 | SUCCESS | 成功 |
| 3 | FAILED | 解析失败 |
| 4 | REBUILDING | 重建中 |
| 5 | WAITING | 排队中 |
| 6 | TIMEOUT | 解析超时（超 24 小时未解析） |
| 7 | VIOLATION | 内容安全违规 |

**受限状态集**（评审确认）：`MEMBER_HIDDEN_FILE_STATUSES = {3 解析失败, 6 解析超时, 7 违规}`。

**关于「上传失败」**：后端**不存在**「上传失败」这一持久化文件状态。上传阶段失败的文件根本不会入库
（前端上传占位行在 `finally` 中被移除，错误经 toast 提示）。因此「上传失败」的文件天然不会出现在列表里，
**无需为其单独增加过滤逻辑**（评审确认）。

## 3. 可见性规则（权威定义）

作用范围：client 知识空间文件列表相关接口（见 §5 范围）。

对某个空间下的一个**文件**（`file_type=1`）：

- 若当前登录用户是该空间的**管理者** → 可见（维持现状，看全部）。
- 否则（普通成员 / 编辑者）：
  - `status ∈ {3,6,7}` 且 `user_id ≠ 当前用户` → **隐藏**；
  - 其余（`status ∉ {3,6,7}`，或该异常文件是本人上传）→ 可见。
- **文件夹**（`file_type=0`）本身 status 不属于受限集，本规则不隐藏文件夹。

「管理者」定义：当前用户对该空间的**有效权限集合**中包含 `manage_space_relation`
（权限模板 `bisheng/permission/domain/knowledge_space_permission_template.py:42`，`can_manage` 档）。
该权限天然涵盖：

- 全局管理员 `login_user.is_admin()`（权限计算里被当作 owner 档）；
- 空间创建者 `Knowledge.user_id == login_user.user_id`（owner fallback）；
- 空间管理员成员（成员角色 `admin` → `manager` 关系档）。

而普通成员（`member` → `viewer`）与仅有编辑权的用户（`editor`，如仅被授予 `upload_file`）
**不含** `manage_space_relation`，按普通成员处理——这与需求「仅管理员和上传人可见」一致。

`_get_effective_permission_ids("knowledge_space", space_id)` 是权威权限源（读权限校验
`_require_read_permission` 也用它判 `view_space`），因此管理者判定 = `"manage_space_relation" in` 该集合。

## 4. 方案选型（据实精化）

评审时确定的方向是「后端强制过滤 + 前端清理」（安全约束必须后端强制，纯前端过滤不安全）。
计划阶段读实代码后，后端强制的**注入点**精化为「单一可见性选点」，理由如下：

本分支（`feat/2.5.0-sg`）三条读路径**都汇聚到同一个 ReBAC 逐项可见性过滤方法**
`KnowledgeSpaceService._filter_visible_child_items`：

- `list_space_children` → `_scan_visible_child_items` → `_filter_visible_child_items`
- `search_space_children` → `_filter_visible_child_items`（搜索用的是 `KnowledgeFileDao.aget_file_by_filters`，
  **并非** `async_list_children`）
- `get_space_folder_stats` → `_count_folder_file_stats` → `_count_visible_success_files_under_folder`
  → `_filter_visible_child_items`（`visible_success_file_num`）

因此在这个**唯一选点**追加「受限状态可见性」规则，一处改动即覆盖 list / search / 文件夹可见计数，
天然三处一致；比在 `async_list_children`、`aget_file_by_filters`、folder-stats 三个不同 DAO 各穿一遍
SQL floor 更 DRY、更不易漏。安全性不变（仍是后端强制、纯内存判定、无法被前端绕过）。

- **采纳：选点方案（service 层 `_filter_visible_child_items` + `_build_child_permission_context` 预置管理者标志）。**
- 否决 A（DAO SQL floor 逐个方法穿参）：搜索走另一个 DAO，需改三处、易漏、且 `visible_success_file_num` 仍要单独处理。
- 否决 B（纯前端过滤）：不安全。

## 5. 范围（In / Out）

**In（按规则过滤）：**

- `GET /{space_id}/children` → `list_space_children`（列表主入口，含 `listKnowledgeFolders` 的 `file_type=0` 变体）
- `GET /{space_id}/search` → `search_space_children`（搜索）
- `POST /{space_id}/folder-stats` 的 `visible_success_file_num`（member 面向的可见文件计数，经选点自动修正）

**Out（本次不改）：**

- `GET /my-uploaded-files`（本就只列当前用户自己上传的文件，等价于「上传人看自己」，天然满足规则，无需改）
- folder-stats 的原始 `file_num` / `success_file_num` / `processing_file_num`（面向管理者的总数聚合，非 member 面向；
  `success`/`processing` 不含受限状态；`file_num` 原始总数可能含他人受限文件，属可接受的次要项，
  member 面向计数用 `visible_success_file_num` 且已被选点修正——见 §9）
- platform 管理后台「知识库」文件列表（`/file_list/{id}`）——不在需求范围
- 上传失败处理（见 §2，无需处理）
- department 空间「审批文件」客户端叠加过滤（`useFileManager` 中 `spaceKind==="department"` 的
  `listApprovalRequestsApi` 合并项）——独立子系统，不走后端 children 接口，本次不动（见 §9 限制）

## 6. 架构与数据流

```
client useFileManager.loadFiles()  (member 不再前端强制排除状态)
  → GET /{space_id}/children | /search
    → service.list_space_children / search_space_children
        → _build_child_permission_context(space_id)
             can_view_all_statuses = ("manage_space_relation"
                                       in await _get_effective_permission_ids("knowledge_space", space_id))
        → _filter_visible_child_items(items, context)
             1) 既有 ReBAC 逐项 view_file/view_folder 过滤
             2) 若 not can_view_all_statuses:
                  _hide_restricted_status_items(items, owner_user_id=login_user.user_id)
                    keep item iff  file_type==DIR
                                or status ∉ MEMBER_HIDDEN_FILE_STATUSES
                                or user_id == owner_user_id
```

list 的游标分页由 `_scan_visible_child_items` 循环补齐：选点多丢弃的条目会触发继续取下一批，分页正确。

## 7. 后端改动清单（bisheng_2，路径以 `src/backend/` 为根）

### 7.1 常量 + 纯过滤 helper
- `bisheng/knowledge/domain/models/knowledge_file.py`：新增模块级常量
  ```python
  MEMBER_HIDDEN_FILE_STATUSES = frozenset({
      KnowledgeFileStatus.FAILED.value,     # 3 解析失败
      KnowledgeFileStatus.TIMEOUT.value,    # 6 解析超时
      KnowledgeFileStatus.VIOLATION.value,  # 7 违规
  })
  ```
- `KnowledgeSpaceService` 新增纯函数 helper（无 IO，易单测）：
  ```python
  @staticmethod
  def _hide_restricted_status_items(items, *, owner_user_id):
      return [
          item for item in items
          if item.file_type == FileType.DIR.value
          or item.status not in MEMBER_HIDDEN_FILE_STATUSES
          or item.user_id == owner_user_id
      ]
  ```

### 7.2 管理者判定 + 预置到 context
- `KnowledgeSpaceService` 新增：
  ```python
  async def _space_user_can_view_all_statuses(self, space_id: int) -> bool:
      space_permissions = await self._get_effective_permission_ids("knowledge_space", space_id)
      return "manage_space_relation" in space_permissions
  ```
- `_build_child_permission_context`（`knowledge_space_service.py:1730`）返回的 dict 增加键
  `"can_view_all_statuses": await self._space_user_can_view_all_statuses(space_id)`。
  三条读路径共享此 context，管理者标志按 space 计算一次。

### 7.3 选点应用规则
- `_filter_visible_child_items`（`knowledge_space_service.py:5660`）在既有 ReBAC 过滤之后追加：
  ```python
  visible = [item for item, allowed in zip(items, visibility) if allowed]
  if not permission_context.get("can_view_all_statuses", False):
      visible = self._hide_restricted_status_items(
          visible, owner_user_id=self.login_user.user_id,
      )
  return visible
  ```
  - `search_space_children` 未显式传 context → `_filter_visible_child_items` 内部 `context or _build_child_permission_context(...)` 会补建，标志仍在。
  - 其余调用 `_filter_visible_child_items` 的路径（QA scope、`_count_visible_success_files_under_folder`）均已预筛 `SUCCESS`，floor 对其为 no-op，安全。

## 8. 前端改动清单（client，`src/frontend/client`）

后端成为唯一可见性来源后，移除前端对成员的状态强制排除（现有实现对成员强制排除 `status=3`，
会导致**成员连自己上传的失败文件也看不到**，与需求相悖，一并修复）：

- `src/pages/knowledge/hooks/useFileManager.ts:222`（`loadFiles`）：`fileStatusNums` 去掉
  `: isMember ? SPACE_CHILDREN_STATUS_NUMS_EXCLUDE_FAILED : undefined`，改为无显式筛选时 `undefined`。
  保留同函数 `const isMember`（第 219 行，仍被第 282 行审批文件逻辑使用）。
- `src/pages/knowledge/hooks/useFileManager.ts:478-481`（`refreshLoadedStatuses` 轮询）：同样去掉成员分支；
  该处 `const isMember`（478）改后无其他用途，一并删除。
- `src/pages/knowledge/sidebar/KnowledgeSpaceItem.tsx:260-264`：文件夹树 `fileStatus` prop 去掉成员分支
  （`listKnowledgeFolders` 只取文件夹，后端选点不隐藏文件夹；成员与管理者一致看全部文件夹）。
- 删除不再被引用的常量 `SPACE_CHILDREN_STATUS_NUMS_EXCLUDE_FAILED`（`src/api/knowledge.ts:898`）及其两处 import
  （`useFileManager.ts:6`、`KnowledgeSpaceItem.tsx:4`）；清理引用它的注释
  （`knowledge.ts:1639`、`KnowledgeFolderTree.tsx:33`）。保留广场用的 `SPACE_CHILDREN_STATUS_SUCCESS_ONLY`。
- 状态筛选下拉 UI 保留：成员仍可主动筛出**自己的**失败 / 违规 / 超时文件（后端选点保证只返回本人）。

## 9. 边界与一致性

- list、search、`visible_success_file_num` 共用同一选点，三处一致。
- 成员显式筛选受限状态（如筛「违规」）→ 后端选点在 ReBAC 后再过滤 → 仅见本人对应文件。
- `my-uploaded-files` 不改，本就只列自己（含失败/违规），与「上传人看自己」一致。
- 管理者行为完全不变。
- **可接受的次要项**：folder-stats 原始 `file_num`（总数聚合）对成员可能仍含他人受限文件的计数；
  但 member 面向展示用 `visible_success_file_num`（已被选点修正），故一般不浮现。若后续确认前端某处向成员展示了
  原始 `file_num`，再补 `_count_folder_file_stats` 的 SQL floor（gated on `can_view_all_statuses`）。
- **已知限制**：department 空间「审批文件」客户端叠加（`useFileManager` 中 `spaceKind==="department"`）
  保留其既有客户端 `FAILED` 过滤，属独立审批子系统、不走后端 children 接口，本次不动。

## 10. 测试计划

**后端（pytest，`src/backend/.venv/bin/python`；测试文件 `src/backend/test/test_knowledge_space_service.py`，
单元 + mock 风格，工厂 `_make_file` / `_make_login_user`）：**

- `_hide_restricted_status_items`（纯函数）：混合状态 + 混合 user_id + 文件夹 → 断言隐藏他人 {3,6,7}、保留本人 {3,6,7}、
  保留非受限、保留文件夹。
- `_space_user_can_view_all_statuses`：patch `_get_effective_permission_ids` 返回含/不含 `manage_space_relation`
  → 断言 True / False。
- `_filter_visible_child_items`：patch `_get_child_item_effective_permission_ids` 使 ReBAC 全通过；
  传 `context={"can_view_all_statuses": False}` → 断言他人受限文件被去、本人受限文件与非受限文件与文件夹保留；
  传 `True` → 全保留。

**前端（client，jest / tsc）：**

- `npx tsc --noEmit`（或项目 typecheck）通过：确认删除常量后无悬挂引用。
- grep 断言 `useFileManager.ts` / `KnowledgeSpaceItem.tsx` 不再出现 `SPACE_CHILDREN_STATUS_NUMS_EXCLUDE_FAILED`。

## 11. 非目标 / YAGNI

- 不改 platform 知识库列表。
- 不新增「上传失败」状态或其过滤。
- 不改动文件状态徽标/文案展示。
- 不调整 `my-uploaded-files`。
- 不改 department 审批文件叠加、不改 folder-stats 原始 `file_num` SQL。

## 12. Worktree / 分支

- bisheng_2 worktree：`/Users/zhangguoqing/works/bisheng_2-space-hide-abnormal-files`，
  分支 `feat/2.5.0-sg-space-hide-abnormal-files`（基于 `feat/2.5.0-sg`）。
- portal/shougang：无需改动，未建 worktree（评审确认）。
