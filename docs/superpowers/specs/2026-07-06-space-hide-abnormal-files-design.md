# 知识空间文件列表隐藏异常文件（违规/解析失败/解析超时）设计

- 日期：2026-07-06
- 分支：`feat/2.5.0-sg-space-hide-abnormal-files`（基于 `feat/2.5.0-sg`）
- 仓库：bisheng_2（全部改动在此；portal/shougang 无需改动）
- 状态：已评审通过，待编写实现计划

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

**受限状态集**（评审确认）：`{3 解析失败, 6 解析超时, 7 违规}`。

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

「管理者」定义：当前用户对该空间的**有效权限集合**中包含 `manage_space_relation`。
该权限（`can_manage` 档）天然涵盖：

- 全局管理员 `login_user.is_admin()`（权限计算里被当作 owner 档）；
- 空间创建者 `Knowledge.user_id == login_user.user_id`（owner fallback）；
- 空间管理员成员（成员角色 `admin` → `manager` 关系档）。

而普通成员（`member` → `viewer`）与仅有编辑权的用户（`editor`，如仅被授予 `upload_file`）
**不含** `manage_space_relation`，按普通成员处理——这与需求「仅管理员和上传人可见」一致。

## 4. 方案选型

- **方案 A（采纳）：后端 DB 层强制过滤 + 前端清理。** 后端在列表/搜索/计数接口按上文规则在 SQL 层追加过滤；
  前端移除成员侧的强制状态排除逻辑，交给后端。
- 方案 B（否决）：仅后端 service 层查后过滤——count / folder-stats 需另实现一套，列表与计数易不一致。
- 方案 C（否决）：纯前端过滤——**不安全**，接口仍会把他人违规文件返回给成员；前端也无法权威判断「是否管理者」。

权限约束必须由后端强制，故选方案 A。

## 5. 范围（In / Out）

**In（需按规则过滤的接口）：**

- `GET /{space_id}/children` → `list_space_children`（列表主入口）
- `GET /{space_id}/search` → `search_space_children`（搜索）
- 上述两者对应的 **count** 逻辑（游标分页 `has_more` / 计数）
- `POST /{space_id}/folder-stats` → `get_space_folder_stats`（文件夹内文件计数，须与列表一致）

**Out（本次不改）：**

- `GET /my-uploaded-files`（本就只列当前用户自己上传的文件，等价于「上传人看自己」，天然满足规则，无需改）
- platform 管理后台「知识库」文件列表（`/file_list/{id}`）——不在需求范围
- 上传失败处理（见 §2，无需处理）

## 6. 架构与数据流

```
client useFileManager.loadFiles()
  → GET /{space_id}/children (不再由前端按 member 角色强制排除状态)
    → service.list_space_children(login_user, ...)
        computes is_space_manager = ("manage_space_relation" in space_effective_permissions)
        if not is_space_manager:
            hidden_statuses = MEMBER_HIDDEN_FILE_STATUSES = (FAILED, TIMEOUT, VIOLATION)
            owner_user_id   = login_user.user_id
        → SpaceFileDao.async_list_children(..., hidden_statuses=?, owner_user_id=?)
            SQL floor: or_(~status.in_(hidden_statuses), user_id == owner_user_id)   # 与显式 file_status 过滤 AND 组合
```

## 7. 后端改动清单（bisheng_2）

文件路径以 `src/backend/` 为根。

### 7.1 常量
- `bisheng/knowledge/domain/models/knowledge_file.py`：新增模块级常量
  ```python
  MEMBER_HIDDEN_FILE_STATUSES = (
      KnowledgeFileStatus.FAILED.value,    # 3 解析失败
      KnowledgeFileStatus.TIMEOUT.value,   # 6 解析超时
      KnowledgeFileStatus.VIOLATION.value, # 7 违规
  )
  ```

### 7.2 DAO 层过滤（`bisheng/knowledge/domain/models/knowledge_space_file.py`，`SpaceFileDao`）
为下列方法新增可选参 `hidden_statuses: List[int] = None`、`owner_user_id: int = None`：

- `async_list_children`（约 :181）
- `async_count_children`（约 :348）
- 搜索对应的 DAO 查询（search 变体所用方法）

当 `hidden_statuses` 且 `owner_user_id is not None` 时，向 `filters` 追加：
```python
filters.append(
    or_(
        ~KnowledgeFile.status.in_(hidden_statuses),
        KnowledgeFile.user_id == owner_user_id,
    )
)
```
- 对文件行（`file_type=1`）：直接生效（隐藏他人异常文件、保留本人）。
- 对文件夹行（`file_type=0`）：`~status.in_(hidden)` 一般为真，文件夹不被此 floor 隐藏。
- 对文件夹的 `descendant_exists` 子查询（用于「文件夹含匹配后代则显示」）：同样追加
  `or_(~Descendant.status.in_(hidden), Descendant.user_id == owner_user_id)`，
  保证成员显式筛选「违规」等状态时，文件夹的展示/计数只依据其**可见**后代，避免出现「文件夹显示但打开为空」。

该 floor 与既有的显式 `file_status`（用户在 UI 主动选状态）过滤是 **AND** 关系：
成员显式筛「违规」时，最终只会看到**自己**的违规文件。

### 7.3 Service 层（`bisheng/knowledge/domain/services/knowledge_space_service.py`）
- `list_space_children`（约 :6506）、`search_space_children`（约 :6683）、`get_space_folder_stats`（约 :6258）：
  - 计算 `is_space_manager`：复用已有的空间有效权限计算（`_get_effective_permission_ids(object_type=space, object_id=space_id)`
    或等价路径），判断 `"manage_space_relation" in effective`。若已有更直接的 helper（如 permission level →
    `_permission_level_to_space_user_role`，owner/can_manage → 管理者）优先复用，避免重复计算权限。
  - 非管理者时，把 `hidden_statuses=MEMBER_HIDDEN_FILE_STATUSES`、`owner_user_id=self.login_user.user_id`
    透传给 DAO；管理者时两者传 `None`（行为不变）。
  - 注意：该权限已在读权限校验（`_require_read_permission`）过程中计算过一次，尽量复用其结果，避免二次查询。

## 8. 前端改动清单（client，`src/frontend/client`）

- `src/pages/knowledge/hooks/useFileManager.ts`（约 :219、:478 两处）：
  移除 member 分支的 `SPACE_CHILDREN_STATUS_NUMS_EXCLUDE_FAILED` 自动过滤。
  member 与 admin/creator 一致：无显式状态筛选时 `file_status` 传 `undefined`，由后端 floor 决定可见性。
  - 附带修复既有缺陷：当前实现对 member 强制排除 `status=3`，导致**成员连自己上传的失败文件也看不到**；
    改后成员可看到自己的异常文件。
- 清理：若 `SPACE_CHILDREN_STATUS_NUMS_EXCLUDE_FAILED`（`src/api/knowledge.ts:1020` 附近）不再被引用则删除；
  保留广场预览用的 `SPACE_CHILDREN_STATUS_SUCCESS_ONLY`（不同场景，不动）。
- 状态筛选下拉 UI 保留：成员仍可主动筛出**自己的**失败 / 违规 / 超时文件（后端 floor 保证只返回本人）。

## 9. 边界与一致性

- 列表、count、folder-stats 共用同一 floor，保证「列表条数」与「文件夹计数」一致。
- 成员显式筛选受限状态 → 仅见本人对应文件（floor 与显式过滤 AND）。
- `my-uploaded-files` 不改，本就只列自己（含失败/违规），与「上传人看自己」一致。
- 管理者行为完全不变。

## 10. 测试计划

**后端（pytest，使用 `src/backend/.venv/bin/python`）：**
- 管理者（全局 admin / 创建者 / 空间 admin 成员）→ 列表含 status 3/6/7 文件（他人上传亦可见）。
- 普通成员 → 列表**不含**他人的 status 3/6/7 文件；含他人的 status 1/2/4/5 文件。
- 普通成员 → 列表**含**自己上传的 status 3/6/7 文件。
- count / folder-stats 与列表口径一致（同一场景条数相符）。
- 显式 `file_status=[7]` + 成员 → 仅返回本人违规文件。
- 搜索接口同上关键用例。

**前端（client 单测）：**
- `useFileManager`：member 角色不再向 `getSpaceChildrenApi` 传 `SPACE_CHILDREN_STATUS_NUMS_EXCLUDE_FAILED`；
  无显式筛选时 `file_status` 为 `undefined`。

## 11. 非目标 / YAGNI

- 不改 platform 知识库列表。
- 不新增「上传失败」状态或其过滤。
- 不改动文件状态徽标/文案展示。
- 不调整 `my-uploaded-files`。

## 12. Worktree / 分支

- bisheng_2 worktree：`/Users/zhangguoqing/works/bisheng_2-space-hide-abnormal-files`，
  分支 `feat/2.5.0-sg-space-hide-abnormal-files`（基于 `feat/2.5.0-sg`）。
- portal/shougang：无需改动，未建 worktree（评审确认）。
