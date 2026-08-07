# Tasks: F079 标签管理控制台

**关联规格**: [spec.md](./spec.md)
**Spec Discovery**: [spec-discovery.md](./spec-discovery.md)
**版本**: v2.6.0
**分支**: `feat/v2.6.0/079-tag-management-console`

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec-discovery.md | ✅ 已确认 | 2026-08-07，含 D11 推翻记录 |
| spec.md | ✅ 已评审 | 两轮 `/sdd-review spec` 共 16 条问题全部处理，用户 2026-08-07 确认 |
| tasks.md | ✅ 已拆解 | `/sdd-review tasks` 第 1 轮 7 条问题已修复，第 2 轮 LGTM |
| 实现 | 🚧 进行中 | 5 / 23 完成 |

---

## 开发模式

**后端 Test-First**：项目已有 `src/backend/test/conftest.py`（F000 建立），提供
`db_session` / `async_db_session` / `tenant_context` / `mock_redis` 等 fixture，直接复用，无需再搭基础设施。
新测试放 `src/backend/test/workstation/`，`asyncio_mode=auto`。

**前端 Test-Alongside**：platform 已配 vitest + jsdom（`vitest.config.ts`，测试放 `src/test/*.test.tsx`）。
**纯逻辑**（模式切换、筛选参数拼装、URL 构造、批量按钮启用规则）写自动化单测；
**渲染交互**（拖选、悬停浮层、弹窗视觉）用手动验证，每个任务附验证步骤。

> 注意：本地 jsdom 依赖 `canvas` 原生模块，若未编译则整个 vitest 跑不起来。
> 遇到时把新测试拆成不依赖 DOM 的纯函数测试，或在 CI 上跑。

**自包含任务**：每个任务内联文件路径、逻辑要点与关键约束，实现阶段不需要回读 spec.md。

**贯穿性硬约束**（每个后端任务都适用）：
- 分层 `Endpoint → Service → Repository`，不跨层
- 双库兼容：不用 `JSON_EXTRACT` / `information_schema` / 方言专有语法
- 不手写 `WHERE tenant_id = X`，由 SQLAlchemy 事件自动注入
- 所有写操作结束后失效 Link B 目录缓存（见 T011 / T013）

---

## Tasks

### 基础设施（无测试配对）

- [x] **T001**: 审核留痕字段迁移 + ORM
  **文件**:
  `src/backend/bisheng/core/database/alembic/versions/v2_6_0_f079_tag_review_audit_fields.py`（新建），
  `src/backend/bisheng/database/models/tag.py`（改），
  `src/backend/bisheng/database/models/review_tags.py`（改）
  **逻辑**: 加三个可空列 —
  `review_tag.reviewer_id`(Integer, nullable)、
  `tag.reviewer_id`(Integer, nullable)、`tag.review_time`(DateTime, nullable)。
  ORM 侧在 `Tag` / `ReviewTag` 上补同名字段。
  `down_revision` 取生成时实际 head（当前 `f078_knowledge_parse_priority`）。
  **约束**: 三列必须可空且无 server_default，存量数据为 NULL；不得使用 `ON UPDATE`、JSON、LONGTEXT。
  **回滚方案**: `downgrade()` 用 `op.drop_column()` 逐列删除三个新列。
  本迁移**纯加列、不改不删既有列、不迁移数据**，因此回滚无损：
  回滚后旧代码路径完全不受影响，只是丢失回滚前写入的审核留痕（该数据在本特性上线前本就不存在）。
  升级与回滚都要在 MySQL 与 DM8 上各跑一次验证。
  **覆盖 AC**: AC-19
  **依赖**: 无

- [x] **T002**: 错误码定义
  **文件**: `src/backend/bisheng/common/errcode/workstation.py`
  **逻辑**: 追加 4 个继承 `BaseErrorCode` 的类，取 120 段（该文件现已用到 12045）：
  `TagConsoleBatchTooLargeError`(12046)、`TagConsolePageParamsError`(12047)、
  `TagConsoleActionNotApplicableError`(12048)、`TagConsoleRejectReasonRequiredError`(12049)。
  **注意**: 不要用 knowledge 的 109 段——本特性端点在 workstation 模块。
  release-contract.md 的模块编码表已登记，无需再改。
  **依赖**: 无

- [x] **T003**: Console Schema 定义
  **文件**: `src/backend/bisheng/workstation/domain/schemas/tag_console_schema.py`（新建）
  **逻辑**: 按 spec §5 定义 `TagConsoleFilter` / `TagConsoleSearchReq` / `TagConsoleItem` /
  `TagConsoleSearchResp` / `TagConsoleReviewRef` / `TagConsoleReviewItem` /
  `TagConsoleReviewSearchReq` / `TagConsoleReviewSearchResp` / `TagConsoleBatchResult` 及四个批量请求模型。
  **关键约束**: 模式 B 的行标识是 `TagConsoleReviewRef(name, resource_type)`，**不是 id**——
  同名标签在多个知识空间会有多条 `review_tag` 记录，现有链路按 `(name, resource_type)` 分组处理（AD-10）。
  **依赖**: 无

---

### 后端 — 审核留痕写入（Test-First 配对）

- [x] **T004**: 审核留痕写入测试
  **文件**: `src/backend/test/workstation/test_review_tag_audit_fields.py`（新建）
  **逻辑**: 用 `async_db_session` fixture 造一条 pending `review_tag` + link，
  走 `WorkstationTagsService.approve_or_reject_review_tag`。
  **测试**:
  - `test_approve_writes_reviewer_to_review_tag` — 通过后 `review_tag.reviewer_id` = 当前登录用户
  - `test_approve_carries_reviewer_to_tag` — 搬运产生的 `tag` 行带上 `reviewer_id` 与 `review_time`
  - `test_approve_preserves_submitter` — `tag.user_id` 仍是原提报人，不被审核人覆盖
  - `test_reject_writes_reviewer_and_time` — 驳回后 `reviewer_id` / `review_time` / `reject_reason` 都写入
  **覆盖 AC**: AC-19, AC-31, AC-32
  **依赖**: T001

- [x] **T005**: 审核留痕写入实现
  **文件**:
  `src/backend/bisheng/workstation/domain/repositories/tags_repository.py`（改 `approve_tag_to_move`，L17-39），
  `src/backend/bisheng/workstation/domain/repositories/review_tags_repository.py`（改 `approve_review_tag` / `reject_review_tag`），
  `src/backend/bisheng/workstation/domain/services/workstation_tags_service.py`（把当前登录用户传下去）
  **逻辑**: `approve_tag_to_move` 目前只复制
  name/business_id/user_id/tenant_id/resource_type/create_time/update_time，
  补上从 `review_tag` 带过来的 `reviewer_id` 与 `review_time`。
  **关键约束**: `tag.user_id = review_tag.user_id` 这行**不能动**——它是提报者语义（AC-10）。
  工作台旧页面走的是同一条路径，改动必须向后兼容（AC-40）。
  **测试**: T004 全部通过
  **覆盖 AC**: AC-19, AC-31, AC-32
  **依赖**: T001, T004

---

### 后端 — 模式 A：已入库标签查询（Test-First 配对）

- [ ] **T006**: 模式 A 查询测试
  **文件**: `src/backend/test/workstation/test_tag_console_search.py`（新建）
  **逻辑**: 造多个标签库 + 多条 `tag` + `tag_link`，覆盖各筛选组合。
  **测试**:
  - `test_search_all_libraries_when_ids_empty` → AC-05
  - `test_search_filters_by_selected_libraries` → AC-03, AC-04
  - `test_search_excludes_pending_and_rejected` — 结果里不出现任何 `review_tag` 数据 → AC-10
  - `test_search_filter_by_tag_name / resource_type / submitter / reviewer` → AC-11, AC-12, AC-13
  - `test_search_filter_by_date_range_and_single_side` → AC-14
  - `test_search_pagination_total_and_stable_order` → AC-16
  - `test_search_scoped_for_department_admin` — 范围外空间的标签不出现 → AC-38
  - `test_search_ignores_missing_library_ids` — 传入不存在的 library_id 不报错
  **覆盖 AC**: AC-03, AC-04, AC-05, AC-10, AC-11, AC-12, AC-13, AC-14, AC-16, AC-38
  **依赖**: T003

- [ ] **T007**: 模式 A 查询实现
  **文件**:
  `src/backend/bisheng/workstation/domain/repositories/tag_console_repository.py`（新建），
  `src/backend/bisheng/workstation/domain/services/tag_console_service.py`（新建 `search`）
  **逻辑**: `resolve_reviewable_space_ids()` 拿可见空间集合 →
  过滤 `tag`（`business_type='tag_library'`）→ `ORDER BY create_time DESC, id DESC` → `LIMIT/OFFSET`。
  当页 ID 拿到后**批量**补齐库名、用户名、来源知识（`tag_link` → 知识文件）、已标识知识数。
  **关键约束**:
  - 单表查询，**不要 UNION**（AD-02 已推翻合并方案）
  - 补齐必须批量，禁止 N+1（10 万标签下 P95 < 800ms）
  - `page_size` 上限 200，越界或 ≤0 抛 `TagConsolePageParamsError`
  **测试**: T006 全部通过
  **覆盖 AC**: 同 T006
  **依赖**: T002, T003, T006

---

### 后端 — 模式 B：待审核/已驳回查询（Test-First 配对）

- [ ] **T008**: 模式 B 查询测试
  **文件**: `src/backend/test/workstation/test_tag_console_review_search.py`（新建）
  **逻辑**: 造 pending / rejected `review_tag` + link，含"同名跨多空间"和两类应被排除的数据。
  **测试**:
  - `test_review_search_groups_by_name_and_resource_type` — 同名跨 3 个空间只出 1 行，
    `review_tag_count`=3，`source_files` 含全部 3 个文件 → AC-25
  - `test_review_search_excludes_names_already_in_library` — 名字已在正式标签库的被排除 → AC-41
  - `test_review_search_excludes_orphan_without_active_link` — 无有效 link 的孤儿被排除 → AC-41
  - `test_review_search_status_filter_pending_rejected_all` → AC-27
  - `test_review_counts_ignore_status_filter` — status 筛成 pending 时 `rejected_count` 仍是真实值 → AC-26
  - `test_review_search_other_filters` — 标签名/来源/提报者/审核者/日期区间 → AC-28
  - `test_review_search_stable_order` — `MAX(create_time) DESC, name, resource_type` 全序，翻页不重不漏 → AC-16
  - `test_pending_count_matches_review_search` — 左栏角标与模式 B 的 `pending_count` 同口径 → AC-02
  - `test_review_search_scoped_for_department_admin` → AC-38
  **覆盖 AC**: AC-02, AC-16, AC-25, AC-26, AC-27, AC-28, AC-38, AC-41
  **依赖**: T003

- [ ] **T009**: 模式 B 查询实现
  **文件**: `tag_console_repository.py`（加 review 查询）、`tag_console_service.py`（加 `review_search` / `pending_count`）
  **逻辑**: `GROUP BY name, resource_type` 聚合 `review_tag`，
  排序 `ORDER BY MAX(create_time) DESC, name ASC, resource_type ASC`（分组查询下用不了 id 做 tiebreak）。
  **关键约束（最容易漏）**: 必须照抄现有
  `review_tags_repository.py:374-388` 的两个隐含过滤，否则本页条目会比工作台旧页面多出一批、两处数字对不上：
  1. `ReviewTag.name.not_in(_library_tag_name_subquery(tenant_id))` — 排除名字已在正式标签库的
  2. `_active_review_tag_link_exists(tenant_id)` — 排除无有效 link 的孤儿

  外加基础条件 `is_deleted == False` 与空间范围子句 `_pending_space_scope_clause`。
  `pending_count` / `rejected_count` 用**剔除 status 后**的同一套条件 `COUNT(DISTINCT name, resource_type)`。
  左栏角标接口复用同一个查询函数。
  **测试**: T008 全部通过
  **覆盖 AC**: 同 T008
  **依赖**: T003, T008

---

### 后端 — 写操作（Test-First 配对）

- [ ] **T010**: 模式 A 写操作测试
  **文件**: `src/backend/test/workstation/test_tag_console_write.py`（新建）
  **测试**:
  - `test_create_tag_success` — 写入 `tag`，`business_type='tag_library'` → AC-20
  - `test_create_tag_without_library_rejected` → AC-20
  - `test_create_tag_duplicate_name_rejected` — 复用 `_ensure_global_tag_names_available` → AC-21
  - `test_batch_delete_removes_tag_and_links` → AC-22, AC-23
  - `test_batch_move_rewrites_business_id` — 断言写入的是
    `TagLibraryTagService._business_id(library_id)` 编码，不是裸 id → AC-24
  - `test_batch_move_skips_duplicate_name_in_target` → AC-24
  - `test_batch_over_limit_rejected` — >500 抛 `TagConsoleBatchTooLargeError`
  - `test_batch_partial_failure_not_rolled_back` — 已被他人删除的条目计入 failed，其余照常成功 → AC-36
  - `test_write_invalidates_link_b_cache` — 每个写操作后目录缓存被失效一次 → AC-37
  **覆盖 AC**: AC-20, AC-21, AC-22, AC-23, AC-24, AC-36, AC-37
  **依赖**: T007

- [ ] **T011**: 模式 A 写操作实现
  **文件**: `tag_console_service.py`（`create_tag` / `batch_delete` / `batch_move`）
  **逻辑**: 逐条执行，失败计入 `failed` 明细而**不整批回滚**（AD-08）。
  **关键约束**:
  - `batch_move` 写 `business_id` 必须走 `TagLibraryTagService._business_id(library_id)`
    （参考 `tags_repository._resolve_approved_tag_business_id`）
  - 提交事务后调一次 `TagLibraryTagService.invalidate_link_b_tenant_catalog_cache_async(tenant_id)`，
    批量场景**合并为一次**，不要每条调一次
  - 重名校验复用 knowledge 侧的 `_ensure_global_tag_names_available`，不要自己写一套
  **测试**: T010 全部通过
  **覆盖 AC**: 同 T010
  **依赖**: T002, T007, T010

- [ ] **T012**: 审核操作测试
  **文件**: `src/backend/test/workstation/test_tag_console_review_action.py`（新建）
  **测试**:
  - `test_review_detail_returns_all_source_files` — 同名跨多空间时列出全部文件 → AC-30
  - `test_batch_approve_uses_own_source_knowledge` — 每项用自身来源知识作 `knowledge_id` → AC-31, AC-34
  - `test_batch_approve_multi_space_takes_first_in_scope` — 跨空间时取可见范围内第一个
  - `test_batch_approve_without_source_knowledge_fails` — link 为空计入 failed，原因「缺少来源知识」
  - `test_batch_reject_requires_reason` — 空原因抛 `TagConsoleRejectReasonRequiredError` → AC-32, AC-35
  - `test_rejected_item_cannot_be_approved` — 对已驳回条目调 approve 抛
    `TagConsoleActionNotApplicableError`，**不要**让它掉进 `ReviewTagNotFoundError` → AC-33
  - `test_review_action_invalidates_link_b_cache` → AC-37
  **覆盖 AC**: AC-30, AC-31, AC-32, AC-33, AC-34, AC-35, AC-37
  **依赖**: T009

- [ ] **T013**: 审核操作实现
  **文件**: `tag_console_service.py`（`review_detail` / `batch_approve` / `batch_reject`）
  **逻辑**: 逐项复用 `WorkstationTagsService.approve_or_reject_review_tag`。
  **关键约束**:
  - 入参是 `TagConsoleReviewRef(name, resource_type)`，不是 id（AD-10）
  - 调用前**先判状态**：已驳回的直接抛 `TagConsoleActionNotApplicableError`。
    现有 `get_review_tag_list_by_tag_name` 硬过滤 `review_status == 0`，
    不先判会让用户看到含义不明的「标签不存在」（AD-11）
  - **不要**为了支持已驳回改判去放开 `get_review_tag_list_by_tag_name` 的状态过滤——
    工作台旧页面走同一条路径，会破坏 AC-40 的回归要求
  - 缓存失效同 T011
  **测试**: T012 全部通过
  **覆盖 AC**: 同 T012
  **依赖**: T005, T009, T012

---

### 后端 — API 层（Test-First 配对）

- [ ] **T014**: 端点集成测试
  **文件**: `src/backend/test/workstation/test_tag_console_api.py`（新建）
  **逻辑**: 用 `test_client` fixture 打 9 个端点，覆盖 happy path + 主要 error path。
  **测试**:
  - 每个端点的 200 响应结构符合 `UnifiedResponseModel` 包装
  - `test_requires_login` — 未登录被拒
  - `test_permission_denied_for_non_reviewer` — 无标签管理权限的用户被拒（沿用
    `resolve_reviewable_space_ids` 的 `ReviewTagPermissionDeniedError`）→ AC-39
  - `test_page_params_invalid` → `TagConsolePageParamsError`
  **覆盖 AC**: AC-39
  **依赖**: T011（模式 A 写操作实现）, T013（审核操作实现）——本任务要打全部 9 个端点，两边 Service 都得先就位

- [ ] **T015**: 端点定义 + Router 注册
  **文件**:
  `src/backend/bisheng/workstation/api/endpoints/tag_console.py`（新建），
  `src/backend/bisheng/workstation/api/router.py`（改）
  **逻辑**: 9 个端点，前缀 `/api/v1/workstation/tags/console`：
  `POST /search`、`POST /create`、`POST /batch-delete`、`POST /batch-move`、
  `POST /review/search`、`POST /review/detail`、`POST /review/batch-approve`、
  `POST /review/batch-reject`、`GET /review/pending-count`。
  认证 `UserPayload = Depends(UserPayload.get_login_user)`，响应 `resp_200(data)`。
  **关键约束**: endpoint 只做参数校验与委托，业务逻辑一律在 Service；
  不得 `import bisheng.database.models.*`（arch-guard RULE-3）。
  **测试**: T014 全部通过
  **覆盖 AC**: AC-39
  **依赖**: T013, T014

---

### 前端 Platform — API 层与纯逻辑（Test-Alongside）

> 本特性**不涉及 Client 前端**（`src/frontend/client/`）。
> 唯一的交叉点是来源文件外链跳到 client 的 `/knowledge-portal`，那是既有页面，不需要改。

- [ ] **T016**: 前端 API 封装 + 类型
  **文件**:
  `src/frontend/platform/src/controllers/API/knowledgeSpaceTagLibrary.ts`（改，追加 console 段），
  `src/frontend/platform/src/pages/BuildPage/bench/standalone/tagConsole/tagConsoleTypes.ts`（新建）
  **逻辑**: 9 个请求函数 + 对应 TS 类型；状态/来源到展示文案与颜色的映射表。
  **关键约束**: 用 `@/controllers/request`，不要 `import axios`。
  待审核项的类型用 `{ name, resource_type }` 作 key，不要用 id。
  **依赖**: T015

- [ ] **T017**: 纯逻辑工具函数 + 配套单测（Test-Alongside 配对任务）
  > 本任务同时产出实现与测试，这是「前端 Test-Alongside」模式的既定配对方式（见开发模式），
  > 不适用后端 Test-First 的"测试任务不得混入实现"约束。
  **文件**:
  `src/frontend/platform/src/pages/BuildPage/bench/standalone/tagConsole/buildTagFileDetailUrl.ts`（新建），
  `src/frontend/platform/src/test/tagConsoleLogic.test.ts`（新建）
  **逻辑**: 把不依赖 DOM 的规则抽成纯函数并测：
  - `buildTagFileDetailUrl(resource)` — 按现有
    `KnowledgeSpaceReviewTagSection.buildReviewTagFileDetailUrl` 同规则拼
    `getWorkspaceClientUrl('/knowledge-portal?spaceId=..&fileId=..&fileName=..&folderId=..')`；
    缺 fileId/spaceId/fileName 任一返回 `null` → AC-18
  - `resolveMode(selectedLibraryIds, reviewEntryActive)` — 选库 → `'library'`；点待审核 → `'review'` 且清空选中 → AC-03, AC-06
  - `buildSearchParams(filters, libraryIds)` — 空值不下发、日期单边成立 → AC-14
  - `canBatch(action, selectedRows)` — 已驳回行不参与入库/驳回 → AC-33
  **注意**: 这些测试必须是纯函数测试，不要 import 组件——本地 jsdom 依赖未编译的 `canvas` 时会整体跑不起来。
  **覆盖 AC**: AC-03, AC-06, AC-14, AC-18, AC-33
  **依赖**: T016

---

### 前端 Platform — 页面实现（手动验证）

- [ ] **T018**: 左栏 + 页面骨架
  **文件**:
  `.../standalone/KnowledgeTagLibraryPage.tsx`（改成左右布局 + `mode` 状态），
  `.../tagConsole/TagLibraryPanel.tsx`、`TagLibraryFormDialog.tsx`（新建）
  **逻辑**: 左栏 = 顶部固定项「待审核标签 (N)」+ 搜索框 + `+` 新增 + 标签库列表（单击多选）。
  悬停标签库名弹浮层显示 `bound_space_names`。
  **关键约束**:
  - 「待审核标签」不参与标签库搜索过滤，始终可见（AC-09）
  - 点标签库自动切回模式 A；点「待审核标签」清空标签库选中（AC-03, AC-06）
  - 左栏固定宽 280px 可折叠
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09
  **手动验证**:
  - 打开 `http://localhost:3001/standalone/knowledge-tag-library`，确认无左侧菜单和顶栏
  - 点标签库 → 高亮 + 右栏跟着变；再点 → 取消选中
  - 点「待审核标签」→ 标签库选中全清空
  - 悬停库名 → 浮层列出关联知识空间；无关联时显示「暂无关联知识空间」
  - 搜索框输入 → 只过滤标签库，「待审核标签」不消失
  **依赖**: T016, T017

- [ ] **T019**: 右栏模式 A（标签管理）
  **文件**: `.../tagConsole/TagTablePanel.tsx`、`TagFilterBar.tsx`、`AddTagDialog.tsx`（新建）
  **逻辑**: 筛选栏（标签名/来源/提报者/审核者/创建日期区间/审核日期区间 + 搜索 + 重置）、
  工具栏（添加 / 批量删除 / 批量移动）、12 列表格、分页。
  **关键约束**:
  - 标签来源用图标区分（系统/人工/AI 各一个 lucide 图标）
  - 审核者/审核时间为空显示 `-`
  - 来源知识文件名用 `buildTagFileDetailUrl` 外链 + `target="_blank"`
  - 表格横向滚动包在自己的 `overflow-x:auto` 容器里，页面本体不横向滚
  **覆盖 AC**: AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-24
  **手动验证**:
  - 各筛选项单独与组合生效；「重置」清空筛选但不清空左栏选中
  - 翻页、改每页条数、总条数正确
  - 表里不出现任何待审核/已驳回标签
  - 点来源文件名 → 新标签页打开门户预览
  - 「添加」重名 → 报「已存在于其他标签库」
  **依赖**: T018

- [ ] **T020**: 右栏模式 B（待审核标签）+ 审核弹窗
  **文件**: `.../tagConsole/ReviewTablePanel.tsx`、`TagReviewDialog.tsx`（新建）
  **逻辑**: 状态筛选（全部/待审核/已驳回，默认待审核）、
  工具栏标题「待审核标签（待审核 N / 已驳回 M）」、
  工具栏（批量入库 / 批量驳回）、表格行内「处理」。
  「处理」弹窗：只读上下文（标签名/来源/创建者/所属标签库/**全部**来源文件）+ 选择标签库 + 驳回原因 + 同意/驳回。
  **关键约束**:
  - 原「确认」「驳回」两个按钮合并成一个「处理」入口（AC-29）
  - 已驳回行「处理」禁用，也不参与批量入库/驳回；驳回原因整列可见（AC-27, AC-33）
  - 「同意」必须先选标签库；「驳回」原因必填
  - N/M 不受状态筛选影响（AC-26）
  - 弹窗**不做**「推荐标签」栏（本期不做相似标签）
  **覆盖 AC**: AC-25, AC-26, AC-27, AC-28, AC-29, AC-30, AC-31, AC-32, AC-33, AC-34, AC-35, AC-41
  **手动验证**:
  - 状态切到「已驳回」→ 能看到驳回原因，「处理」灰掉
  - 状态切到「待审核」→ `已驳回 M` 数字不变
  - 同名跨多空间的标签只出一行，弹窗里列出全部来源文件
  - 与工作台旧「待审核标签」区块对比条目集合一致
  **依赖**: T018

- [ ] **T021**: 批量弹窗 + 结果清单
  **文件**: `.../tagConsole/TagBatchDialogs.tsx`（新建）
  **逻辑**: 批量移动 / 批量入库 / 批量驳回三个弹窗 + 统一的结果清单弹窗（成功数 / 跳过数 / 失败明细列表）。
  批量移动与批量入库复用同一个「选择目标标签库」下拉；批量驳回复用「驳回原因」必填输入。
  **关键约束**: 部分失败时不报整体错误，而是弹结果清单逐条列出失败原因（AC-36）；
  成功的那部分必须已经生效，不能因为有失败就整体回滚提示。
  **覆盖 AC**: AC-36
  **手动验证**:
  - 造一个部分失败场景（批量移动到已有同名标签的库），确认弹出清单，
    且清单里"成功"的那几条刷新后确实已移走
  - 批量驳回不填原因 → 前端拦住并提示
  **依赖**: T019, T020

- [ ] **T022**: i18n 文案补齐
  **文件**: `src/frontend/platform/public/locales/{zh-Hans,en-US,ja}/bs.json`（改，三个文件同一批键）
  **逻辑**: 补齐本页全部文案，键前缀统一 `build.tagConsole.*`。
  三种语言的键集合必须完全一致，缺一个就会在该语言下露出 raw key。
  **关键约束**: 不要动 `build.*` 下的既有键——工作台旧页面在用（AC-40）。
  **手动验证**: 切 zh-Hans / en-US / ja 三种语言走一遍页面，确认无 raw key、无中英混排
  **依赖**: T021

---

### 回归与验收

- [ ] **T023**: 旧页面回归 + 端到端串测
  **文件**: 无新增（验证性任务）
  **逻辑**: 确认本特性没有把工作台旧页面带坏。
  **关键约束**: `KnowledgeSpaceTagLibrarySection.tsx`、`KnowledgeSpaceReviewTagSection.tsx`、
  `KnowledgeSpace.tsx` 三个文件的 `git diff` 必须为空。
  **覆盖 AC**: AC-40
  **手动验证**:
  - 打开「工作台 → 知识空间」Tab，标签库管理与待审核标签两个区块外观、分页、增删改、审核通过/驳回全部与改造前一致
  - 走一遍完整链路：上传文件 → AI 打标产生待审核标签 → 在新页面模式 B 处理入库 →
    在模式 A 能看到该标签且「审核者」「审核时间」有值 → 该标签的 Link B 目录缓存已刷新
    （再传一个同类文件，确认不会又生成一条同名待审核标签）
  - 部门管理员账号登录，确认两个模式都只看得到自己范围内的标签
  **依赖**: T022

---

## AC 追溯表

| AC | 覆盖任务 |
|----|---------|
| AC-01 | T018 |
| AC-02 | T008, T018 |
| AC-03 | T006, T017, T018 |
| AC-04 | T006, T018 |
| AC-05 | T006, T018 |
| AC-06 | T017, T018 |
| AC-07 | T018 |
| AC-08 | T018 |
| AC-09 | T018 |
| AC-10 | T006, T019 |
| AC-11 | T006, T019 |
| AC-12 | T006, T019 |
| AC-13 | T006, T019 |
| AC-14 | T006, T017, T019 |
| AC-15 | T019 |
| AC-16 | T006, T008, T019 |
| AC-17 | T019 |
| AC-18 | T017, T019 |
| AC-19 | T004, T005, T019 |
| AC-20 | T010, T019 |
| AC-21 | T010, T019 |
| AC-22 | T010, T019 |
| AC-23 | T010, T019 |
| AC-24 | T010, T019 |
| AC-25 | T008, T020 |
| AC-26 | T008, T020 |
| AC-27 | T008, T020 |
| AC-28 | T008, T020 |
| AC-29 | T020 |
| AC-30 | T012, T020 |
| AC-31 | T004, T012, T020 |
| AC-32 | T004, T012, T020 |
| AC-33 | T012, T017, T020 |
| AC-34 | T012, T020 |
| AC-35 | T012, T020 |
| AC-36 | T010, T021 |
| AC-37 | T010, T012 |
| AC-38 | T006, T008, T023 |
| AC-39 | T014, T015 |
| AC-40 | T023 |
| AC-41 | T008, T020 |

---

## 实际偏差记录

> 完成后，在此记录实现与 spec.md 的偏差，供后续参考。

- **偏差 1（分支）**: 未按 SDD 第 4 步新建 `feat/v2.6.0/079-tag-management-console`，
  而是继续在 `feat/2.5.0-sg` 上开发。原因：本仓近期所有特性（F077 文件夹拖拽排序、
  F078 独立路由等）都落在这条分支上，CI 也是从它打镜像并部署到 171；
  另起分支会把本特性从既有的构建/部署回路里割出去。合并策略不变。
