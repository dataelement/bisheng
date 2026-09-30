# F106 库与文件夹排序权限 · 技术方案

| 项 | 内容 |
|---|---|
| 关联 PRD | [prd.md](./prd.md) |
| 关联 spec | [spec.md](./spec.md) |
| 模块 | `bisheng/knowledge`，错误码 **180** |
| 契约源 | FastAPI OpenAPI `/docs` |
| 本文地位 | 存储 / 契约 / 流程 / 鉴权的实现权威 |

---

## 1. 目标、非目标、取舍

**目标**：把「谁能改库序 / 文件夹序」从「仅 `login_user.is_admin()`」换成已确认矩阵；系统管理员能力不回退；列表把可操作项一次算好给 Client 展示。

**非目标**：门户 BFF 第二套规则；未绑定团队库的组织推断；置顶；个人库排序；运营岗文件夹排序；DDL；改 midpoint 步进常数。

| 决策 | 采用 | 否决 | 原因 | 何时可推翻 |
|------|------|------|------|------------|
| 资格计算 | 服务端矩阵 + 写接口再检 | 前端 `role===admin` 唯一门禁 | 运营岗、绑定表无法从 Client `role` 得出 | 仅当 `/user/info` 能稳定表达全部身份且产品接受漏检 |
| 部门管理员工作集 | `department_knowledge_space` ∩ 管辖子树 ∩ 当前可见 | 「侧栏看见的团队库」 | 看见 ≠ 管辖 | 产品改口「看见就能拖」 |
| TEAM + TEAM_KS | 同一工作集、同一 `sort_weight` 序列 | 按存储 level 两条序 | 侧栏已合成一组；现网跨 level 邻居会 18041 | 产品改口「科室单独排」 |
| 文件夹 | 鉴权当前父目录 `can_manage` | 鉴权被拖动的子文件夹 | 需求是「目录内顺序」 | 产品改成按每个子文件夹 owner |
| 首次重铺 | 只重铺本次工作集 | 重铺整个 level | 部门管理员不得改别人权重（AC-23） | 证明工作集重铺会导致全站乱序且产品接受全量重铺 |
| 运营岗判定 | `has_platform_operator_role`（角色名精确「平台管理员」） | 写入 `is_admin()` | 现网硬约束：运营岗不得变超管 | 运营岗身份改判定源 |

输入 → 处理 → 输出：登录用户拖一条库或文件夹 → Service 算工作集并鉴权 → 只更新被拖动行的 `sort_weight`（间隙耗尽才重铺工作集）→ 列表按 `sort_weight` 读出。

---

## 2. 持久化

无新表、无新列、无迁移。回滚 = 回代码；已写下的权重不自动还原。

| 物理名 | 本需求角色 | 结构 | 关键已有列 |
|--------|------------|------|------------|
| `knowledge` | 写库序 | 无结构变更 | `id`, `type`, `sort_weight`, `update_time` |
| `knowledgefile` | 写文件夹序 | 无结构变更 | `id`, `knowledge_id`, `file_type`, `file_level_path`, `sort_weight` |
| `knowledge_space_scope` | 读 | 无结构变更 | `space_id`, `level` |
| `department_knowledge_space` | 读绑定 | 无结构变更 | `department_id`, `space_id` |
| `department` | 读子树 | 无结构变更 | `id`, `path` |
| `department_admin_grant` | 读谁是部门管理员 | 无结构变更 | `user_id`, `department_id` |
| `space_channel_member` | 读库角色（旁路） | 无结构变更 | `business_id`, `user_id`, `user_role` |
| OpenFGA | 读 `can_manage` | 不写新 tuple | `knowledge_space` / `folder` |

`sort_weight` 仍是租户内稀疏整数，越小越靠前；NULL 排在有权重的后面再按 `update_time`（现网 CASE）。不把绑定关系塞进 JSON。

---

## 3. 对外契约

**一份契约源**：毕昇 OpenAPI。门户不新增 BFF 字段。

### 3.1 写（路径不变）

`POST /api/v1/knowledge/space/{space_id}/sort`  
Body: `{ prev_space_id: int|null, next_space_id: int|null }`  
成功 `data: true`。

`POST /api/v1/knowledge/space/{space_id}/folders/{folder_id}/sort`  
Body: `{ prev_folder_id: int|null, next_folder_id: int|null }`  
成功 `data: true`。

鉴权在 Service，不在 Endpoint 复制。

### 3.2 读（资格一次算出）

| 响应 | 新字段 | 含义 | AC |
|------|--------|------|-----|
| 空间列表/详情 `KnowledgeSpaceInfoResp` | `can_reorder: bool` | 当前用户能否拖**这一条库** | AC-20 |
| `/children` 页 | `can_reorder_folders: bool` | 能否拖**当前 parent 目录**下的文件夹 | AC-20, AC-25 |

`/children` 用现有 `PageInfiniteCursorData` 的兼容扩展（增加可选字段，不删 `data`/`has_more`/`next_cursor`）。

Client 只展示。旧 Client 漏藏按钮时，写接口仍 18040。

### 3.3 错误码（不新开 180xx）

| 码 | 类 | 何时 | AC |
|----|-----|------|-----|
| 18040 | SpacePermissionDeniedError | 角色/绑定/目录无权 | AC-07..18 |
| 18041 | SpaceInvalidLevelError | 个人库；邻居不在本次工作集 | AC-19, AC-21 |
| 18000 | SpaceNotFoundError | 库不存在 | 沿用 |
| 18010 | SpaceFolderNotFoundError | 文件夹不存在或非同级邻居 | 沿用 |

无权响应不得带出无权库/文件夹正文。

成对：列表 `can_reorder*` ↔ 写接口；缺一侧视为没做完。

---

## 4. 流程、状态、权限矩阵

无新状态机。`sort_weight` 从 NULL → 整数，或整数 → 新中点。不可逆清理不涉及。

### 4.1 角色 → 代码身份

| 中文 | 代码判定 | 禁止当成 |
|------|----------|----------|
| 系统管理员 | `login_user.is_admin()`（AdminRole）；Client `user.role==="admin"` | 运营岗、门户「管理员」 |
| 运营岗 | `has_platform_operator_role`：`role_names` trim 后精确「平台管理员」 | `is_admin()` / `can_platform_operate` 里的超管支路单独当运营岗 |
| 部门管理员 | `DepartmentDao.aget_user_admin_departments` 非空；子树用现网 `_admin_department_ids()` | 库管理员 |
| 库所有者/管理员 | `PermissionService.check(can_manage, knowledge_space)` 或成员 CREATOR/ADMIN | 系统管理员 |
| 文件夹所有者/管理员 | `PermissionService.check(can_manage, folder, parent_id)` | 库内任意成员 |

`PermissionService.check` L1 已对 `is_admin()` 短路，文件夹路径系统管理员保持能拖。运营岗**不会**走该短路。

### 4.2 库排序主路径

1. 加载被拖库，拒绝非 SPACE / 个人库（18041）。
2. 计算 **工作集 IDs**（见下）。
3. 被拖库不在工作集 → 18040。
4. `prev`/`next` 若非空必须同在工作集，否则 18041。
5. 工作集内有 NULL 权重 → **只对该工作集** respread（AC-23）。
6. 中点写被拖动一行。`prev` 与 `next` 都空 → no-op 成功。
7. 间隙耗尽 → 再 respread 工作集后重算中点。

**工作集**

| 调用者 | PUBLIC | DEPARTMENT | TEAM + TEAM_KS |
|--------|--------|------------|----------------|
| 系统管理员 | 该 level 全部 | 该 level 全部 | 两 level 全部 ID，按 `sort_weight` 一条序 |
| 运营岗 | 同系统管理员 | 同系统管理员 | 空（拖则 18040） |
| 部门管理员 | 空 | 空 | 绑定部门 ∈ 管辖子树的 TEAM/TEAM_KS，再与当前用户可见 ID 求交 |
| 其他人 | 空 | 空 | 空 |

可见 ID 复用 `get_spaces_by_level` 已有可读集合，不另做可见性规则（不扩大被引用资源权限）。

### 4.3 文件夹排序主路径

1. 校验文件夹属于该 `space_id` 且为 DIR。
2. 父目录 = `file_level_path` 最后一段；空则库根。
3. 库根：`can_manage` on `knowledge_space`（含系统管理员短路）。
4. 非根：`can_manage` on `folder:{parent_id}`。
5. 邻居必须是同目录兄弟文件夹。
6. midpoint / 仅工作集（该目录下文件夹）respread。不改文件行权重。

### 4.4 失败停在哪

| 失败 | 存储 | 能否重试 |
|------|------|----------|
| 18040 / 18041 | 不写 | 换合法邻居或换有权限账号 |
| 资源 18000 / 18010 | 不写 | 刷新列表 |
| 并发两次 midpoint | 后一次覆盖同一行 | 可再拖 |
| 列表标志与写不一致 | 视为缺陷；以写接口为准 | 修下发逻辑 |

锁：现网单行 UPDATE，无 `FOR UPDATE` 工作集锁。本版不升级行锁；AC-24 用真库两次串行写验收。内存 SQLite 不算本条门。

### 4.5 通知 / 身份表面 / 时间

本需求无通知、无脱敏、无用户可见墙钟。排序不改变库/文件的公开范围。

---

## 5. 模块所有权与分层

| 仓 / 模块 | 职责 | 不准做 |
|-----------|------|--------|
| `knowledge` Service | 唯一写 `sort_weight` 的业务入口；算工作集 | Endpoint 写 DAO |
| `space_reorder_auth.py`（新小文件） | 纯鉴权 + 工作集 | midpoint 算法复制第二份 |
| `permission` | 只 `check(can_manage)` | 本需求不改 FGA model |
| `user.platform_operator` | 只读运营岗判定 | 不把运营岗写进 `is_admin()` |
| Client 知识门户 | 按标志显示拖拽 | 不本地发明绑定规则 |
| 门户 BFF | 不改 | 不代理出第二套 sort |

调用链：Router → Endpoint → `KnowledgeSpaceService` → `space_reorder_auth` + 现有 DAO。巨石 Service 只留薄调用。

---

## 6. 跨边界影响

- **不变量**：手动库序/文件夹序仍落在已有 `sort_weight`；谁能写改为矩阵；系统管理员不回退。
- **波及**：侧栏库列表、库内文件夹表/卡片、两个 sort POST、`/level/{level}` 与 `/children` JSON；置顶、检索、计数、Celery、门户搜索 **不改语义**。
- **例外**：个人库仍不能排；未绑定团队库部门管理员不能排；无权用户列表可看见库但不能拖。
- **可行性**：中等（约 1～2 天）。无 DDL。需 Client 同步改开关，否则运营岗/部门管理员有权却看不见拖拽。
- **风险**：**高**（权限）。漏改前端 → 按钮错误；漏改工作集 → 部门管理员重铺打乱全租户团队序；TEAM/KS 未合并 → AC-03 失败。
- **建议验证**：171 MySQL 流转（身份 → HTTP → SELECT `sort_weight` → 再拖/再拒绝）。Client 单测侧栏/目录按标志显隐。
- **建议延后**：行锁/乐观版本；把 `can_reorder` 做成通用 capabilities 袋。

已核实调用方：`reorder_space` / `reorder_folder` 仅上述 Endpoint + Client `reorderSpaceApi` / `reorderFolderApi` + 门户工作台 / SpaceDetail。Platform 标签库排序是另一套，不动。

---

## 7. 迁移、坑、后续

- **存量**：已有 `sort_weight` 继续有效。部门管理员第一次拖只重铺自己工作集，可能让其库在「能看见多部门的人」的列表里相对聚拢——接受并写进测试说明。
- **回滚**：回代码后鉴权回到仅系统管理员；已改权重保留。
- **坑**：
  1. `can_platform_operate` 含超管，**库序 PUBLIC/DEPARTMENT 可用它；TEAM 不能用它**（否则运营岗能排团队库）。
  2. 库 `user_role=admin` 含部门 overlay，**不能**用来判断「能排库」——库管不能排库。
  3. 现网 `reorder_space` 按单一 level 载邻居，TEAM 旁 TEAM_KS 会 18041；本版必须合并工作集。
  4. Client `TUser` 现无 `role_names`，故必须下发 `can_reorder`，不要先改用户模型。
- **短板**：不修全租户一条 `sort_weight` 与多部门列表交织的展示（系统管理员仍看全局一条序）。产品已接受绑定工作集。
- **这版不做**：未绑定库推断、运营岗文件夹、门户 BFF。
