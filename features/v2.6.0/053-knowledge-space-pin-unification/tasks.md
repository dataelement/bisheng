# Tasks: 知识库置顶偏好统一

**Feature ID**: `053-knowledge-space-pin-unification`  
**关联规格**: [spec.md](./spec.md)  
**版本**: v2.6.0  
**Mode**: Spec Then Implement  
**Updated**: 2026-07-14

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已确认 | 2026-07-14 用户确认；任务拆解前完成文件路径与非目标校正 |
| tasks.md | ✅ 已拆解 | 20 个原子任务；本地 SDD 等价评审通过，等待执行确认 |
| 实现 | ✅ 已完成 | 20 / 20 已执行；环境验证限制见 verification.md |
| verification.md | ✅ 已创建 | 2026-07-14；记录自动化证据、既有失败与人工验证项 |

---

## 开发原则

- 后端行为变更采用 Test-First：测试任务先失败，再由相邻实现任务转绿。
- 数据迁移必须先完成只读审计；未确认实际 DDL 和重复数据规模前不得执行目标环境迁移。
- 新代码遵守 `Endpoint → Service → Repository → DB`，Service 不直接导入 `database.models.user_link`，不新增旧 DAO 入口。
- 所有数据库改动同时考虑 MySQL 与 DM8；macOS 不声明真实 DM8 验证通过。
- 前端只修改 BiSheng Client；不修改 `shougang-group-knowledge-portal` iframe 宿主代码。
- 每个任务只修改列出的文件；发现范围外依赖时先更新 `spec.md/tasks.md`，不得顺手扩展。
- 当前工作树中的 `shougang_portal_config` 和 `celerybeat-schedule.db` 修改不属于本特性，必须保留且不得纳入提交。

---

## 执行顺序

```text
T001
  ↓
T002 → T003
  ↓
T004 → T005
  ↓
T006 → T007
  ↓
T008 → T009
  ↓
T010 → T011 → T012
               ├→ T013 → T014
               └→ T015 → T016
                         ↓
                       T017 → T018
```

---

## Tasks

### 阶段 1：数据库预检与迁移

- [x] **T001**: `user_link` 实际 DDL 与历史数据只读审计 ✅ 2026-07-14

  _Requirements: REQ-005, REQ-009_  
  _Acceptance: AC-07_  
  _Verification: V-T001-DDL-AUDIT_  
  _Depends: None_  
  _Boundary: 只读查询；禁止建约束、去重、回填或修改任何数据_

  **文件**:
  - `features/v2.6.0/053-knowledge-space-pin-unification/tasks.md`（仅在“实际偏差记录”写入审计结果）

  **操作**:
  - 使用 SQLAlchemy `inspect()` 获取配置数据库中 `user_link` 的列、索引、唯一约束；不得查询 `information_schema`。
  - 只读统计 `(user_id, type, type_detail)` 重复组数量、重复行数量，并按 `type` 汇总。
  - 只读统计 ACTIVE SPACE 历史置顶总数、其中个人库数量、预期回填数量。
  - 如果无法连接目标数据库，记录 `MANUAL_REQUIRED`，给出目标环境执行步骤；不得假设生产 DDL 与 ORM 一致。

  **完成证据**:
  - 审计命令、数据库方言、约束状态和三项统计值记录在“实际偏差记录 §T001”。

- [x] **T002**: Alembic 数据迁移测试（先红）

  _Requirements: REQ-005, REQ-006, REQ-009_  
  _Acceptance: AC-07, AC-08, AC-12_  
  _Verification: V-T002-MIGRATION-TESTS_  
  _Depends: T001_  
  _Boundary: 仅新增迁移测试，不创建迁移、不修改 ORM 模型_

  **文件**:
  - `src/backend/test/knowledge/test_knowledge_space_pin_migration.py`（新建）

  **测试场景**:
  - 重复三元组保留 `create_time` 最新、相同时间下 `id` 最大的记录。
  - 去重覆盖所有 `user_link.type`，但不删除每组三元组之外的合法记录。
  - 仅回填 `business_type=SPACE`、`status=ACTIVE`、`is_pinned=true` 且 scope 非 `PERSONAL` 的记录。
  - 已存在相同 `knowledge_space_pin` 时回填幂等。
  - `business_type=CHANNEL` 记录和成员表原 `is_pinned` 值不被修改。
  - 唯一约束建立后重复三元组写入失败。
  - downgrade 不删除已生成的 `knowledge_space_pin` 数据。

  **验证命令**:
  ```bash
  cd src/backend
  uv run pytest test/knowledge/test_knowledge_space_pin_migration.py -q
  ```

- [x] **T003**: ORM 唯一约束与 F057 迁移实现

  _Requirements: REQ-005, REQ-006, REQ-009_  
  _Acceptance: AC-07, AC-08, AC-12_  
  _Verification: V-T002-MIGRATION-TESTS_  
  _Depends: T002_  
  _Boundary: 只修改 `user_link` ORM 声明和新增 F057；不改变频道模型、不执行目标环境迁移_

  **文件**:
  - `src/backend/bisheng/database/models/user_link.py`
  - `src/backend/bisheng/core/database/alembic/versions/v2_6_0_f057_knowledge_space_user_link_pin.py`（新建）

  **实现**:
  - 在 `UserLink.__table_args__` 声明命名唯一约束 `uk_user_link_user_type_detail`。
  - F057 `down_revision` 指向当前唯一 Alembic head；如实施时 head 已变化，先重新检索并更新。
  - upgrade 按 spec §6.2 完成去重、建约束和历史 SPACE 置顶回填。
  - 使用 SQLAlchemy/Alembic 可移植表达式和 `inspect()` 守卫，不使用 MySQL 专用 upsert、JSON 或 `information_schema`。
  - downgrade 只回退本迁移创建的约束；不删除无法区分来源的偏好数据，也不修改成员表。

  **完成条件**:
  - T002 全绿。
  - `alembic heads` 只有预期 head，迁移脚本通过静态导入。

### 阶段 2：Repository 与错误码

- [x] **T004**: KnowledgeSpacePinRepository 契约测试（先红）

  _Requirements: REQ-001, REQ-007, REQ-009_  
  _Acceptance: AC-09, AC-12_  
  _Verification: V-T004-REPOSITORY-TESTS_  
  _Depends: T003_  
  _Boundary: 仅新增 Repository 测试，不在 Service 中直接访问 ORM_

  **文件**:
  - `src/backend/test/knowledge/test_knowledge_space_pin_repository.py`（新建）

  **测试场景**:
  - 批量读取指定用户的 `knowledge_space_pin`，忽略其他 `type` 和其他用户。
  - 新增已有三元组幂等且不产生第二行。
  - 删除不存在记录幂等。
  - `delete_by_space_id` 只删除目标空间的 `knowledge_space_pin`，保留其他空间和其他 `user_link.type`。
  - 同一用户写入锁/事务上下文可串行化“计数 + 写入”，异常时回滚。

  **验证命令**:
  ```bash
  cd src/backend
  uv run pytest test/knowledge/test_knowledge_space_pin_repository.py -q
  ```

- [x] **T005**: KnowledgeSpacePinRepository 与置顶常量实现

  _Requirements: REQ-001, REQ-007, REQ-009_  
  _Acceptance: AC-09, AC-12_  
  _Verification: V-T004-REPOSITORY-TESTS_  
  _Depends: T004_  
  _Boundary: Repository 实现是唯一允许访问 `UserLink` ORM 的新增知识库代码；不修改旧 `UserLinkDao` 调用方_

  **文件**:
  - `src/backend/bisheng/knowledge/domain/repositories/interfaces/knowledge_space_pin_repository.py`（新建）
  - `src/backend/bisheng/knowledge/domain/repositories/implementations/knowledge_space_pin_repository_impl.py`（新建）
  - `src/backend/bisheng/knowledge/domain/services/knowledge_space_pin_service.py`（仅先定义 `KNOWLEDGE_SPACE_PIN_TYPE`、`MAX_PINS_PER_LEVEL` 和 Service 骨架）
  - 对应 `__init__.py`（仅必要导出）

  **实现**:
  - Repository interface 遵循项目 BaseRepository 约定，并增加置顶领域所需的批量查询、幂等写入、按空间清理和用户写入锁接口。
  - implementation 接收注入的 AsyncSession，不自行创建非托管 session。
  - 常量固定为 `knowledge_space_pin` 和 `5`，禁止把分类编码进 `type`。

  **完成条件**:
  - T004 全绿。
  - Service 与 Endpoint 不出现 `from bisheng.database.models.user_link import ...`。

- [x] **T006**: 置顶业务错误码测试（先红）

  _Requirements: REQ-002, REQ-003_  
  _Acceptance: AC-03, AC-05_  
  _Verification: V-T006-ERRCODE-TESTS_  
  _Depends: T003_  
  _Boundary: 仅测试错误码定义和全模块唯一性_

  **文件**:
  - `src/backend/test/knowledge/test_knowledge_space_pin_errcode.py`（新建）

  **测试场景**:
  - `SpacePersonalPinForbiddenError.Code == 18078`。
  - `SpacePinLimitError.Code == 18079`。
  - 两者继承 `BaseErrorCode`，消息明确且 180 模块内无重复编码。

- [x] **T007**: 置顶业务错误码实现

  _Requirements: REQ-002, REQ-003_  
  _Acceptance: AC-03, AC-05_  
  _Verification: V-T006-ERRCODE-TESTS_  
  _Depends: T006_  
  _Boundary: 仅新增 18078/18079，不改已有错误码语义_

  **文件**:
  - `src/backend/bisheng/common/errcode/knowledge_space.py`

  **实现**:
  - `SpacePersonalPinForbiddenError`: “个人知识库不支持置顶”。
  - `SpacePinLimitError`: “每类最多置顶 5 个知识库”。

  **完成条件**:
  - T006 全绿。

### 阶段 3：Domain Service、列表与缓存

- [x] **T008**: KnowledgeSpacePinService 行为测试（先红）

  _Requirements: REQ-001, REQ-002, REQ-003, REQ-007, REQ-009_  
  _Acceptance: AC-01, AC-02, AC-03, AC-05, AC-06, AC-09, AC-12_  
  _Verification: V-T008-PIN-SERVICE-TESTS_  
  _Depends: T005, T007_  
  _Boundary: mock Repository、scope 和权限服务；不测试 HTTP 或 React_

  **文件**:
  - `src/backend/test/knowledge/test_knowledge_space_pin_service.py`（新建）

  **测试场景**:
  - 未订阅但当前可见的 PUBLIC 空间可置顶。
  - DEPARTMENT/TEAM 必须满足现有查看权限或有效成员关系。
  - PERSONAL 置顶和取消置顶请求均返回 `SpacePersonalPinForbiddenError`，不访问写 Repository。
  - 不存在空间返回 `SpaceNotFoundError`；不可见空间返回 `SpacePermissionDeniedError`。
  - 每级别第 5 个成功，第 6 个返回 `SpacePinLimitError`。
  - 已置顶记录重复置顶不受上限影响且幂等；重复取消幂等。
  - 两个并发的第 5/第 6个写入不能同时成功，最终有效记录不超过 5。
  - 权限丢失的记录不计入当前可见上限，恢复后重新出现在 `get_pinned_space_ids`。
  - `apply_pins` 与可见 ID 求交集、PERSONAL 强制 false、稳定保持 pinned/normal 各自原顺序。
  - `delete_space_pins` 委托 Repository 清理目标知识库。

  **验证命令**:
  ```bash
  cd src/backend
  uv run pytest test/knowledge/test_knowledge_space_pin_service.py -q
  ```

- [x] **T009**: KnowledgeSpacePinService 实现

  _Requirements: REQ-001, REQ-002, REQ-003, REQ-007, REQ-009_  
  _Acceptance: AC-01, AC-02, AC-03, AC-05, AC-06, AC-09, AC-12_  
  _Verification: V-T008-PIN-SERVICE-TESTS_  
  _Depends: T008_  
  _Boundary: 只实现置顶领域规则；不在本任务改列表、Endpoint 或 React_

  **文件**:
  - `src/backend/bisheng/knowledge/domain/services/knowledge_space_pin_service.py`

  **实现**:
  - 实现 spec §8.1 的四个核心方法。
  - 公共空间按公共列表口径判定可见，不要求成员记录；部门/团队复用现有有效权限/成员关系判断。
  - 通过 Repository 的同用户事务边界串行化“重新计数 + 插入”，唯一约束作为幂等兜底。
  - 上限统计只基于当前租户、当前分类、当前用户可见知识库；`user_link` 不手写 `tenant_id` 条件。
  - 装饰列表时一次批量查询，禁止 N+1；兼容 schema 对象和公共列表 dict 的调用边界应通过明确适配器完成。

  **完成条件**:
  - T008 全绿。
  - 架构 guard 无新增 VIOLATION。

- [x] **T010**: 所有知识库列表与缓存行为测试（先红）

  _Requirements: REQ-001, REQ-002, REQ-004, REQ-005_  
  _Acceptance: AC-01, AC-02, AC-05, AC-06, AC-10_  
  _Verification: V-T010-LIST-CACHE-TESTS_  
  _Depends: T009_  
  _Boundary: 只新增/更新后端列表与缓存测试，不改 Service 实现_

  **文件**:
  - `src/backend/test/knowledge/test_knowledge_space_pin_lists.py`（新建）
  - `src/backend/test/knowledge/test_public_space_level_list.py`

  **测试场景**:
  - PUBLIC 列表返回 `is_pinned` 并稳定置顶优先。
  - DEPARTMENT/TEAM 的 `_format_accessible_spaces` 不再读取成员 `is_pinned`。
  - 我的创建、管理、关注列表使用相同 `user_link` 状态。
  - PERSONAL 列表及 grouped 中个人项始终 `is_pinned=false`，即使存在残留 link。
  - grouped 缓存只保存/还原基础列表；缓存命中后重新叠加最新 pin，旧缓存中的 `is_pinned=true` 不污染结果。
  - 单次列表最多调用一次批量置顶查询。

  **验证命令**:
  ```bash
  cd src/backend
  uv run pytest test/knowledge/test_knowledge_space_pin_lists.py test/knowledge/test_public_space_level_list.py -q
  ```

- [x] **T011**: 列表与缓存统一接入 UserLink 置顶

  _Requirements: REQ-001, REQ-002, REQ-004, REQ-005_  
  _Acceptance: AC-01, AC-02, AC-05, AC-06, AC-10_  
  _Verification: V-T010-LIST-CACHE-TESTS_  
  _Depends: T010_  
  _Boundary: 只改知识库列表格式化和 `SpaceListCache`；不改频道列表_

  **文件**:
  - `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`
  - `src/backend/bisheng/knowledge/domain/services/space_list_cache.py`

  **实现**:
  - `_format_accessible_spaces`、`_format_member_spaces`、`get_public_spaces` 统一叠加 `KnowledgeSpacePinService`。
  - 删除知识库列表对 `member_conf.is_pinned` 的读取；成员记录仍用于角色、订阅和权限。
  - `_list_accessible_spaces` 缓存权限过滤后的基础列表，缓存命中/未命中都在返回前重新叠加 pin。
  - 为直接调用 `_format_accessible_spaces` 的 DEPARTMENT/TEAM 路径提供明确参数，避免重复装饰或把用户 pin 写入基础缓存。
  - 兼容发布前 Redis 中可能存在的旧完整缓存：叠加前先重置旧 `is_pinned`。

  **完成条件**:
  - T010 全绿。
  - grep 确认知识库列表不再用 `member_conf.is_pinned` 判断 SPACE 置顶。

### 阶段 4：API、删除清理与频道回归

- [x] **T012**: 置顶 API 与删除清理测试（先红）

  _Requirements: REQ-002, REQ-003, REQ-007, REQ-008_  
  _Acceptance: AC-03, AC-05, AC-09, AC-11, AC-12_  
  _Verification: V-T012-API-LIFECYCLE-TESTS_  
  _Depends: T011_  
  _Boundary: 只新增 API/生命周期测试，不修改 Endpoint 或删除流程_

  **文件**:
  - `src/backend/test/knowledge/test_knowledge_space_pin_api.py`（新建）

  **测试场景**:
  - `POST /{space_id}/set-pin` 继续接收 `{ "is_pined": true|false }` 并返回 `data=true`。
  - Endpoint 只委托 Service，不直接访问 ORM/Repository。
  - 个人库、超限、无权限、不存在分别返回规格定义的业务错误。
  - 删除知识库调用 `delete_space_pins`；清理仅针对 `knowledge_space_pin`。
  - 删除失败或进入异步迁移分支时不提前误删置顶记录；仅在实际删除主记录的路径执行清理。

  **验证命令**:
  ```bash
  cd src/backend
  uv run pytest test/knowledge/test_knowledge_space_pin_api.py -q
  ```

- [x] **T013**: 置顶 Endpoint、删除清理与旧 SPACE 写路径移除

  _Requirements: REQ-002, REQ-003, REQ-005, REQ-007, REQ-008_  
  _Acceptance: AC-03, AC-05, AC-09, AC-11, AC-12_  
  _Verification: V-T012-API-LIFECYCLE-TESTS_  
  _Depends: T012_  
  _Boundary: 不删除 `space_channel_member.is_pinned` 字段或 `pin_space_id`，只停止知识库调用它_

  **文件**:
  - `src/backend/bisheng/knowledge/api/endpoints/knowledge_space.py`
  - `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`

  **实现**:
  - 将误名 `set_channel_pin` 修正为知识库语义命名，保留 URL 和 `is_pined` 请求字段。
  - `KnowledgeSpaceService.pin_space` 委托 `KnowledgeSpacePinService.set_pin`。
  - 实际删除 `Knowledge` 主记录后清理该空间的 `knowledge_space_pin`；异步迁移提前返回路径不清理。
  - 不再调用 `SpaceChannelMemberDao.pin_space_id` 处理知识库置顶。

  **完成条件**:
  - T012 全绿。
  - `rg "pin_space_id" knowledge/` 不再出现知识库调用点。

- [x] **T014**: 频道置顶回归测试与架构静态检查

  _Requirements: REQ-005, REQ-006_  
  _Acceptance: AC-08_  
  _Verification: V-T014-CHANNEL-REGRESSION_  
  _Depends: T013_  
  _Boundary: 原则上只新增/运行频道测试；发现频道回归时停止并报告，不顺手重构频道_

  **文件**:
  - `src/backend/test/channel/test_channel_pin_regression.py`（缺少覆盖时新建）

  **测试与检查**:
  - 频道 set-pin 继续更新 `business_type=CHANNEL` 成员的 `is_pinned`。
  - 频道列表继续输出并按 `membership.is_pinned` 排序。
  - `space_channel_member.is_pinned` ORM 字段仍存在。
  - 知识库模块不读取/写入 SPACE 成员的 `is_pinned`。

  **验证命令**:
  ```bash
  cd src/backend
  uv run pytest test/channel/test_channel_pin_regression.py -q
  bash scripts/arch-guard.sh
  ```

### 阶段 5：BiSheng Client 前端

- [x] **T015**: 门户内嵌工作台个人库置顶门控测试（先红）

  _Requirements: REQ-002, REQ-003_  
  _Acceptance: AC-03, AC-04_  
  _Verification: V-T015-PORTAL-CLIENT-TESTS_  
  _Depends: T013_  
  _Boundary: 只修改门户工作台现有测试，不改生产组件_

  **文件**:
  - `src/frontend/client/src/pages/knowledge/portal/components/SpaceSidebar.test.tsx`
  - `src/frontend/client/src/pages/knowledge/portal/PortalKnowledgeWorkbench.test.tsx`

  **测试场景**:
  - 普通个人库和“我的收藏”菜单均不显示置顶/取消置顶。
  - PUBLIC、DEPARTMENT、TEAM 菜单仍显示置顶操作。
  - handler 收到 PERSONAL 时不调用 `pinSpaceApi`。
  - 非个人分组已有 5 个置顶时保留提示且不调用 API。
  - 非个人置顶成功后刷新 `knowledgeSpaces` 查询。

- [x] **T016**: 门户内嵌工作台隐藏个人库置顶

  _Requirements: REQ-002, REQ-003_  
  _Acceptance: AC-03, AC-04_  
  _Verification: V-T015-PORTAL-CLIENT-TESTS_  
  _Depends: T015_  
  _Boundary: 不修改门户宿主仓库、不改变个人库其他菜单权限_

  **文件**:
  - `src/frontend/client/src/pages/knowledge/portal/components/SpaceSidebar.tsx`
  - `src/frontend/client/src/pages/knowledge/portal/PortalKnowledgeWorkbench.tsx`

  **实现**:
  - `group.level === SpaceLevel.PERSONAL` 时不渲染置顶菜单项。
  - `handlePinSpace` 对 PERSONAL 防御性返回。
  - 保留公共、部门、团队的 5 个前端预检、Toast 和 query invalidation。

  **完成条件**:
  - T015 全绿。

- [x] **T017**: 普通知识库侧边栏个人库置顶门控测试（先红）

  _Requirements: REQ-002, REQ-003_  
  _Acceptance: AC-03, AC-04_  
  _Verification: V-T017-SIDEBAR-TESTS_  
  _Depends: T013_  
  _Boundary: 只修改普通知识库侧边栏现有测试，不改生产组件_

  **文件**:
  - `src/frontend/client/src/pages/knowledge/sidebar/KnowledgeSpaceItem.test.tsx`
  - `src/frontend/client/src/pages/knowledge/sidebar/KnowledgeSpaceSidebar.personal.test.ts`
  - `src/frontend/client/src/pages/knowledge/hooks/useSpaceActions.test.ts`（新建）

  **测试场景**:
  - PERSONAL 普通库和“我的收藏”不显示置顶菜单。
  - PUBLIC、DEPARTMENT、TEAM 保留置顶菜单。
  - `useSpaceActions.handlePinSpace` 收到 PERSONAL 时不乐观更新、不调用 API。
  - 非个人分组仍保留 5 个上限、乐观更新、失败回滚和 query invalidation。

- [x] **T018**: 普通知识库侧边栏隐藏个人库置顶

  _Requirements: REQ-002, REQ-003_  
  _Acceptance: AC-03, AC-04_  
  _Verification: V-T017-SIDEBAR-TESTS_  
  _Depends: T017_  
  _Boundary: 不改变设置、成员管理、删除、退出或收藏库重命名门控_

  **文件**:
  - `src/frontend/client/src/pages/knowledge/sidebar/KnowledgeSpaceItem.tsx`
  - `src/frontend/client/src/pages/knowledge/sidebar/KnowledgeSpaceSidebar.tsx`（仅必要 prop/level 传递）
  - `src/frontend/client/src/pages/knowledge/hooks/useSpaceActions.ts`

  **实现**:
  - PERSONAL 列表项不渲染置顶/取消置顶菜单。
  - `useSpaceActions.handlePinSpace` 对 PERSONAL 防御性返回。
  - 非个人置顶行为和错误回滚保持不变。

  **完成条件**:
  - T017 全绿。

### 阶段 6：全量验证与交付

- [x] **T019**: 后端格式化、静态检查、定向回归与迁移演练

  _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008, REQ-009_  
  _Acceptance: AC-01, AC-02, AC-03, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12_  
  _Verification: V-T019-BACKEND-GATE_  
  _Depends: T014, T016, T018_  
  _Boundary: 只修复本特性引入的失败；既有失败记录证据，不扩大范围_

  **验证命令**:
  ```bash
  cd src/backend
  uv run ruff format \
    bisheng/database/models/user_link.py \
    bisheng/common/errcode/knowledge_space.py \
    bisheng/knowledge/domain/repositories \
    bisheng/knowledge/domain/services/knowledge_space_pin_service.py \
    bisheng/knowledge/domain/services/knowledge_space_service.py \
    bisheng/knowledge/domain/services/space_list_cache.py \
    bisheng/knowledge/api/endpoints/knowledge_space.py \
    test/knowledge/test_knowledge_space_pin_*.py
  uv run ruff check \
    bisheng/database/models/user_link.py \
    bisheng/common/errcode/knowledge_space.py \
    bisheng/knowledge/domain/repositories \
    bisheng/knowledge/domain/services/knowledge_space_pin_service.py \
    bisheng/knowledge/domain/services/knowledge_space_service.py \
    bisheng/knowledge/domain/services/space_list_cache.py \
    bisheng/knowledge/api/endpoints/knowledge_space.py \
    test/knowledge/test_knowledge_space_pin_*.py
  uv run pytest test/knowledge/test_knowledge_space_pin_*.py test/knowledge/test_public_space_level_list.py -q
  uv run pytest test/channel/test_channel_pin_regression.py -q
  uv run alembic heads
  uv run alembic upgrade head
  bash scripts/arch-guard.sh
  ```

  **迁移验证**:
  - 在可回滚的 MySQL 测试库执行 upgrade，核对 T001 统计与迁移后统计。
  - 执行 downgrade/upgrade 循环，确认约束回退策略与数据保留策略一致。
  - DM8 标记为 CI 验证；没有 CI 证据时 AC-07 状态只能是 `MANUAL_REQUIRED`。

- [x] **T020**: 前端自动化测试、构建、人工 E2E 与 verification.md

  _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-008_  
  _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-10, AC-11_  
  _Verification: V-T020-FINAL-VERIFICATION_  
  _Depends: T019_  
  _Boundary: 验证和记录，不修改门户宿主生产代码；实现偏差必须先回写 spec/tasks_

  **验证命令**:
  ```bash
  cd src/frontend/client
  npm test -- --runInBand SpaceSidebar KnowledgeSpaceItem useSpaceActions PortalKnowledgeWorkbench
  npm run build
  ```

  **人工 E2E**:
  - 在 `/workspace/knowledge-portal?portal_embed=1` 展开四个分组。
  - 验证个人库菜单无置顶；公共、部门、团队可置顶、取消并立即排序。
  - 验证未订阅公共库可置顶，部门/团队无权限请求被拒绝。
  - 验证每分类第 6 个被前端提示和后端共同阻止。
  - 刷新页面、命中缓存后置顶状态保持一致。
  - 验证频道置顶回归。

  **交付文件**:
  - `features/v2.6.0/053-knowledge-space-pin-unification/verification.md`（新建）

  **完成条件**:
  - 每个 AC 标记 `PASS`、`FAIL`、`MANUAL_REQUIRED` 或 `NOT_RUN`，附命令、exit code 和证据。
  - 更新本文件任务状态与“实际偏差记录”。
  - 运行规格一致性 review、代码 review 和项目要求的 E2E review；未通过不得声明完成。

---

## Acceptance Coverage Matrix

| AC | 测试/实现任务 | 最终验证 |
|----|---------------|----------|
| AC-01 | T008-T011, T015-T016 | T019, T020 |
| AC-02 | T008-T011, T017-T018 | T019, T020 |
| AC-03 | T006-T009, T012-T013, T015-T018 | T019, T020 |
| AC-04 | T015-T018 | T020 |
| AC-05 | T006-T013 | T019 |
| AC-06 | T008-T011 | T019 |
| AC-07 | T001-T003 | T019 |
| AC-08 | T002-T003, T014 | T019, T020 |
| AC-09 | T004-T005, T008-T013 | T019 |
| AC-10 | T010-T011 | T019, T020 |
| AC-11 | T012-T013 | T019, T020 |
| AC-12 | T002-T005, T008-T013 | T019 |

---

## Requirement Coverage Matrix

| Requirement | Tasks |
|-------------|-------|
| REQ-001 | T004-T005, T008-T011, T019-T020 |
| REQ-002 | T006-T013, T015-T020 |
| REQ-003 | T006-T009, T012-T013, T015-T020 |
| REQ-004 | T010-T011, T019-T020 |
| REQ-005 | T001-T003, T010-T014, T019 |
| REQ-006 | T002-T003, T014, T019 |
| REQ-007 | T004-T005, T008-T013, T019 |
| REQ-008 | T012-T013, T019-T020 |
| REQ-009 | T001-T005, T008-T009, T019 |

---

## Quality Gates

- [x] QG-01：T001 只读审计已有证据，迁移风险可量化。
- [ ] QG-02：所有 Test-First 测试任务先观察到预期失败，再由实现任务转绿。
- [ ] QG-03：后端定向测试、ruff、arch-guard 全部通过。
- [ ] QG-04：MySQL upgrade/downgrade 演练通过；DM8 有 CI 证据或明确 `MANUAL_REQUIRED`。
- [x] QG-05：Client 定向测试与 build 通过。
- [x] QG-06：个人知识库前端和后端均无置顶入口。
- [x] QG-07：频道置顶回归通过，成员表字段未删除。
- [x] QG-08：所有 AC 在 `verification.md` 中有新鲜证据。
- [x] QG-09：无无关文件、格式化或当前用户修改进入本特性 diff。

---

## Tasks Review

**Reviewed**: 2026-07-14  
**Decision**: `PASS_TO_IMPLEMENTATION_CONFIRMATION`

- Task ID：`T001-T020` 连续且唯一。
- Metadata：20/20 任务均包含 `_Requirements`、`_Acceptance`、`_Verification`、`_Depends`、`_Boundary`。
- Requirement Coverage：`REQ-001` 至 `REQ-009` 全覆盖。
- Acceptance Coverage：`AC-01` 至 `AC-12` 全覆盖，均映射到实现任务和最终验证。
- Test-First：迁移、Repository、错误码、Service、列表缓存、API 和两个前端入口均先测试后实现。
- Scope：不修改门户宿主生产代码，不新增知识库级别切换，不迁移频道置顶。
- Risk Gate：T001 只读审计完成前禁止执行 F057 目标环境迁移。
- Review Finding：无阻塞项；通用 `sdd-review` 的分离式文档前置条件由项目本地合并式 `spec.md + tasks.md` 约定替代。

---

## 实际偏差记录

> 实施阶段按任务记录发现、决策、验证证据和与 spec 的偏差。未发生偏差时保留“无”。

- **T001 审计结果**：MySQL 审计 PASS；`user_link` 无复合唯一约束，仅有三个单列普通索引；重复组 0、重复额外行 0；现有类型仅 `portal_agent_favorite` 5 行；ACTIVE SPACE 历史置顶 6 条、个人库置顶 0 条、预期回填上限 6 条。首次只读聚合使用 `SUM(COUNT())` 被 MySQL 拒绝，修正为分组计数后在应用层求和，未执行任何 DDL/DML。
- **实现偏差**：通用 `ruff check` 扫描整个历史大文件时暴露 108 个既有问题；本特性新增文件的 format/check 全绿。`PortalKnowledgeWorkbench.test.tsx` 全文件存在 40 个既有失败，聚焦组件与 Hook 测试全绿。部分生产骨架早于新增测试落盘，因此 QG-02 不标记通过。
- **验证限制**：未在当前配置数据库执行 F057，避免直接修改现有数据；真实 MySQL upgrade/downgrade、DM8 CI 和浏览器人工 E2E 仍需在受控环境执行。
