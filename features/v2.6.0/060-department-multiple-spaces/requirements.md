# 需求说明 Requirements: 一个部门绑定多个知识空间

## 阅读摘要
- 本文档说明：取消“一部门只能绑定一个知识空间”的限制，并消除原单值查询在权限同步与自动选库链路中的歧义。
- 当前状态：`implemented`
- 需要重点确认：一个知识空间仍只绑定一个部门；多候选自动选库必须明确失败，不得随机选择。

## 元信息 Metadata
- Feature ID: `060-department-multiple-spaces`
- Status: `implemented`
- Mode: `spec-then-implement`
- Created: `2026-07-16`
- Updated: `2026-07-16`
- Source request: `取消一个部门只能绑定一个知识空间的限制`

## 需求入口摘要 Intake Summary
- 问题 Problem: `department_knowledge_space.department_id` 唯一约束及多处单值读取使已绑定部门无法再接收其他知识空间。
- 当前状态 Current state: 部门 3 和子部门 18 已存在旧团队知识库绑定，编辑部门知识库到这些部门时返回 `18002`；管理员同步、自由库迁移和外部文件同步均假设每个部门只有一个绑定空间。
- 目标结果 Target outcome: 一个部门可绑定多个知识空间，所有读取链路返回或处理完整集合；必须自动选择目标时使用确定性优先级并对歧义显式报错。
- 影响对象 Affected users/systems: 系统管理员、部门管理员、部门知识库编辑、批量创建、旧团队库绑定、自由知识库删除迁移、外部文件库同步、MySQL/DM8 schema。
- 请求停止点 Requested stopping point: `implementation + verification`

## 范围 Scope

### 包含 Includes
- 移除 `department_knowledge_space.department_id` 唯一约束并保留普通查询索引。
- 保留 `department_knowledge_space.space_id` 唯一约束，一个知识空间仍只能绑定一个部门。
- 允许同一部门同时存在多个部门层级知识库以及旧团队知识库绑定。
- 修改创建、旧团队库绑定、编辑重新归属和列表查询的一对多语义。
- 部门管理员变化时同步该部门绑定的全部知识空间。
- 自由知识库迁移与外部文件同步共享确定性目标空间选择规则。
- 多候选歧义时返回明确业务冲突，不创建文件、不移动知识内容。
- 新增 MySQL 与 DM8 兼容的 Alembic 向前迁移及受保护 downgrade。
- 覆盖后端、Client 现有行为和迁移的定向回归测试。

### 不包含 Excludes
- 一个知识空间绑定多个部门。
- 自动解绑、删除、转换或覆盖现有绑定数据。
- 引入“主知识库”字段或管理员选择主知识库的配置页面。
- 修改知识库层级、创建者、文件、目录、标签、审批或敏感检测配置。
- 多候选时按 ID、创建时间、更新时间或数据库返回顺序随机选择。
- 未经单独确认直接对当前配置连接的数据库执行 Alembic upgrade。

## 需求列表 Requirements

### REQ-001: 一个部门允许多个知识空间绑定
作为系统管理员，我需要把多个知识空间绑定到同一部门，以便旧团队绑定不会阻止新的部门知识库归属。

#### 验收标准 Acceptance Criteria
- `AC-REQ-001-01`: WHEN 目标部门已经绑定其他知识空间且系统管理员重新归属一个不同知识空间 THEN 系统 SHALL 成功保存新绑定并保留原绑定。
- `AC-REQ-001-02`: WHEN 批量创建或旧团队库绑定对同一部门创建新的不同空间绑定 THEN 系统 SHALL 允许创建，不返回“该部门已有知识库”。
- `AC-REQ-001-03`: WHEN 同一知识空间尝试绑定第二个部门 THEN 系统 SHALL 继续拒绝或通过更新语义保持只有一个部门绑定。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-001-01 | V-AC-REQ-001-01 | automated integration test | `test/knowledge/test_department_space_rebind.py` 覆盖已占用部门重新归属成功及原绑定保留 |
| AC-REQ-001-02 | V-AC-REQ-001-02 | automated service test | `test/knowledge/test_department_multiple_spaces.py` 覆盖批量创建与旧绑定入口 |
| AC-REQ-001-03 | V-AC-REQ-001-03 | automated migration/model test | 保留 `uk_dks_space_id`，同一 `space_id` 重复写入失败 |

### REQ-002: 绑定读取必须完整且确定
作为知识库调用方，我需要按部门读取全部绑定，避免遗漏知识库或依赖无排序保证的第一条记录。

#### 验收标准 Acceptance Criteria
- `AC-REQ-002-01`: WHEN 查询一个部门或多个部门的知识空间 THEN 系统 SHALL 返回全部绑定空间并按空间 ID 去重。
- `AC-REQ-002-02`: WHEN 用户拥有多个部门或手工成员关系 THEN 部门知识库列表 SHALL 返回其可访问的全部绑定空间且不重复。
- `AC-REQ-002-03`: WHEN 实现完成后执行代码检索 THEN 关键业务链路 SHALL 不再调用按部门返回单个绑定或单个空间 ID 的方法。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-002-01 | V-AC-REQ-002-01 | automated DAO/service test | 多绑定 fixture 返回完整集合 |
| AC-REQ-002-02 | V-AC-REQ-002-02 | automated service test | `test_department_knowledge_space_service.py` 多绑定及去重用例 |
| AC-REQ-002-03 | V-AC-REQ-002-03 | static inspection | `rg` 不再发现目标单值方法的生产调用 |

### REQ-003: 部门管理员同步全部绑定空间
作为部门管理员，我需要在管理员身份变化时自动同步该部门的全部绑定知识空间，以免只有某一个空间更新权限。

#### 验收标准 Acceptance Criteria
- `AC-REQ-003-01`: WHEN 用户被新增为部门管理员 THEN 系统 SHALL 为该部门全部绑定空间同步管理员成员与 `manager` 权限。
- `AC-REQ-003-02`: WHEN 用户被移除部门管理员 THEN 系统 SHALL 对全部绑定空间执行既有自动成员撤销或手工角色恢复规则。
- `AC-REQ-003-03`: IF 任一空间权限同步出现不可恢复错误 THEN 系统 SHALL 记录并传播错误，不得静默声称全部成功。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-003-01 | V-AC-REQ-003-01 | automated service test | 断言新增管理员同步所有 `space_id` |
| AC-REQ-003-02 | V-AC-REQ-003-02 | automated service test | 断言移除管理员遍历所有 `space_id` 并保留手工成员 |
| AC-REQ-003-03 | V-AC-REQ-003-03 | automated failure-path test | 中途失败被记录并向调用方传播 |

### REQ-004: 自动目标空间选择必须统一且安全
作为自由库迁移和外部文件同步调用方，我需要确定、可解释的目标空间解析，避免多绑定后把内容写入随机知识库。

#### 验收标准 Acceptance Criteria
- `AC-REQ-004-01`: WHEN 当前部门只有一个部门层级候选 THEN 系统 SHALL 选择该候选，即使同时存在旧团队绑定。
- `AC-REQ-004-02`: WHEN 当前部门没有任何候选 THEN 系统 SHALL 按部门路径从近到远继续查找父部门。
- `AC-REQ-004-03`: WHEN 当前部门存在多个部门层级候选 THEN 系统 SHALL 立即返回明确歧义冲突，不继续父级回退。
- `AC-REQ-004-04`: WHEN 当前部门没有部门层级候选但只有一个旧团队候选 THEN 系统 SHALL 选择该候选；旧团队候选超过一个时 SHALL 返回歧义冲突。
- `AC-REQ-004-05`: WHEN 解析结果为歧义 THEN 自由库删除迁移 SHALL 被阻止，外部文件同步 SHALL 不创建文件且返回 `FilelibSyncConflictError`。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-004-01 | V-AC-REQ-004-01 | automated resolver test | 新旧绑定共存时选择唯一部门层级空间 |
| AC-REQ-004-02 | V-AC-REQ-004-02 | automated resolver test | 当前部门无候选时命中最近父部门 |
| AC-REQ-004-03 | V-AC-REQ-004-03 | automated resolver test | 多部门层级候选抛出稳定业务错误 |
| AC-REQ-004-04 | V-AC-REQ-004-04 | automated resolver test | 单旧绑定成功、多旧绑定冲突 |
| AC-REQ-004-05 | V-AC-REQ-004-05 | integration/service test | 自由库 guard 与 filelib sync 不产生写入副作用 |

### REQ-005: API 与前端保持可理解行为
作为系统管理员，我需要现有编辑流程在目标部门已有其他空间时正常保存，并在真正歧义时看到明确提示。

#### 验收标准 Acceptance Criteria
- `AC-REQ-005-01`: WHEN 管理员在 Client 编辑部门知识库并选择已有其他绑定的部门 THEN 页面 SHALL 保存成功并刷新详情、侧边栏及列表缓存。
- `AC-REQ-005-02`: WHEN 自动选库存在歧义 THEN API SHALL 返回稳定业务错误与可读提示，前端不得显示为保存成功或同步成功。
- `AC-REQ-005-03`: WHEN 非系统管理员尝试修改部门归属 THEN 既有权限拒绝行为 SHALL 保持不变。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-005-01 | V-AC-REQ-005-01 | Client component test + backend service test | 更新旧冲突预期并断言缓存刷新 |
| AC-REQ-005-02 | V-AC-REQ-005-02 | API/service test | `18004`/`19904` 冲突响应与无副作用断言 |
| AC-REQ-005-03 | V-AC-REQ-005-03 | regression test | 既有非管理员拒绝用例继续通过 |

### REQ-006: Schema 迁移安全且兼容
作为运维人员，我需要通过可审查的迁移安全放宽约束，同时保留查询性能和明确的回退前置条件。

#### 验收标准 Acceptance Criteria
- `AC-REQ-006-01`: WHEN 执行 upgrade THEN schema SHALL 删除 `uk_dks_department_id`、保留 `idx_dks_department_id` 和 `uk_dks_space_id`，且不修改现有行。
- `AC-REQ-006-02`: WHEN downgrade 且不存在重复 `department_id` THEN schema SHALL 恢复 `uk_dks_department_id`。
- `AC-REQ-006-03`: WHEN downgrade 且已存在重复 `department_id` THEN migration SHALL 明确终止，不删除或合并业务数据。
- `AC-REQ-006-04`: WHEN 在 MySQL 与 DM8 检查迁移实现 THEN SHALL 使用项目 dialect helpers/SQLAlchemy inspect，禁止依赖 `information_schema` 或 MySQL 专有 SQL。
- `AC-REQ-006-05`: WHEN 检查最终工作区 THEN 用户已有 `celerybeat-schedule.db` 修改 SHALL 保持原样，且不得自动执行配置数据库 upgrade。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-006-01 | V-AC-REQ-006-01 | migration test/static inspection | upgrade 约束与索引断言，迁移无 DML |
| AC-REQ-006-02 | V-AC-REQ-006-02 | migration test | 无重复数据时 downgrade 恢复唯一约束 |
| AC-REQ-006-03 | V-AC-REQ-006-03 | migration failure-path test | 重复数据下 downgrade 明确失败且数据未改 |
| AC-REQ-006-04 | V-AC-REQ-006-04 | static review + CI | MySQL 定向验证；DM8 由 Linux CI 验证 |
| AC-REQ-006-05 | V-AC-REQ-006-05 | git/status evidence | `git status`、分段 diff、未执行 live upgrade 记录 |

## 非功能需求 Non-Functional Requirements
- `NFR-001`: 按部门批量读取必须保留 `department_id` 普通索引，避免一对多后退化为全表扫描。
- `NFR-002`: 多空间管理员同步不得为每个用户重复查询绑定集合；单次管理员变更先取得空间集合再遍历。
- `NFR-003`: 所有查询继续遵守自动租户过滤和现有权限入口，不手写跨租户条件。
- `NFR-004`: 多候选解析必须确定且与数据库自然顺序无关。
- `NFR-005`: 不新增第三方依赖，不执行无关重构或大范围格式化。

## 澄清记录 Clarifications

### Session 2026-07-16
- Q: 多绑定范围？ -> A: `1A`，一个部门可绑定多个部门知识库，旧团队知识库绑定可以共存；一个知识空间仍只绑定一个部门。
- Q: 部门管理员变化时同步范围？ -> A: `2A`，同步该部门全部绑定知识空间。
- Q: 自由知识库迁移存在多个候选时如何处理？ -> A: `3A`，优先部门层级知识库；同一优先级仍有多个时阻止自动迁移并提示选择。
- Q: 外部文件库同步存在多个候选时如何处理？ -> A: `A`，使用同一优先级规则；歧义时拒绝同步并返回明确冲突。

## 假设 Assumptions
- 现有 `department_knowledge_space.space_id` 唯一关系属于已确认业务边界，继续作为数据库并发兜底。
- 当前前端部门选择器已经展示全部有效部门，本特性无需新增多选交互。

## 风险 Risks
- 约束删除后产生的一对多数据会使直接 downgrade 无法恢复唯一约束；必须先业务清理，迁移不得擅自删除数据。
- MySQL/DM8 的 DDL 锁表特性不同，生产执行窗口需由运维按实际表规模评估。
- 历史上依赖 `.first()` 的外部同步可能从“随机成功”变为明确冲突，这是为避免错误写入而接受的行为变化。

## 需求质量门 Requirements Quality Gate
- [x] Every requirement has a stable `REQ-*` ID.
- [x] Every requirement has at least one `AC-*` acceptance criterion.
- [x] Every acceptance criterion has a stable `AC-*` ID.
- [x] Every acceptance criterion has at least one `V-*` verification ID.
- [x] Every acceptance criterion has a verification method.
- [x] No orphan `AC-*` or `V-*` entries exist.
- [x] Scope includes and excludes are explicit.
- [x] No critical ambiguity remains.
- [x] Requirements avoid implementation details unless explicitly required.
