# Tasks: F083-expert-qa-enhancement

**关联规格**: [spec.md](./spec.md)  
**技术方案**: [design.md](./design.md)  
**UI 用例（85% 场景）**: [ui-test-cases.md](./ui-test-cases.md)  
**版本**: v2.6.0

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | grilling + 第 2 轮 sdd-review；用户确认 |
| design.md | ✅ 已确认 | 用户确认重设计 |
| tasks.md | ✅ 已冻结 + 增量 | 2026-08-13 冻结；2026-08-15 增量 T046–T047；再增 T048–T049（真实 MySQL 流转） |
| 实现 | 🔄 进行中 | T001–T038、T046–T049、T039–T040、T045 完成；T041–T044 spec 已写、CLI 待账号 |

---

## 开发模式

**后端 Test-First**：每个 Domain/API 测试任务先于配对实现；`覆盖 AC:` 必须逐条列举。  
**Portal UI**：本 Feature **引入 Playwright**（门户现网无 Playwright/Cypress）。用例权威见 `ui-test-cases.md`；选择器只用 `data-testid`。  
**BiSheng Platform / Client**：不适用（spec §8.1）。  
**测试降级**：仅 UI-37～40（竞态/时钟/账号停用）不进 Playwright，改由 pytest 覆盖，理由见 ui-test-cases §2。

---

## Tasks

### 基础设施（无测试配对）

- [x] **T001**: Alembic 迁移 F083
  **文件**: `src/backend/bisheng/core/database/alembic/versions/v2_6_0_f083_expert_qa_enhancement.py`
  **逻辑**: 按 design.md §1：核心表补 `tenant_id`；`qa_question` 加 `question_type/content_locked/asker_anonymous/asker_reveal_on_public/adopt_count/resolved_at/active_publish_request_id`；`qa_expert.status`；`qa_answer.user_id/anonymous/reveal_on_public`；`qa_comment.anonymous/reveal_on_public`；新建 `qa_question_invite`、`qa_answer_adopt`、`qa_anonymous_alias`、`qa_answer_eligibility`、`qa_publish_request`、`qa_publish_approver`。列均中文 COMMENT。回填：`tenant_id=1`，存量 `question_type=public`，邀请串→invite 表，已采纳→adopt 表。`downgrade()` 删除新表/新列。
  **依赖**: 无

- [x] **T002**: ORM 对齐迁移
  **文件**: `src/backend/bisheng/database/models/qa_expert.py`
  **逻辑**: 映射 T001 全部新列/新表；`tenant_id` 以便 tenant_filter 自动发现。不改投票表。
  **依赖**: T001

- [x] **T003**: 错误码 183
  **文件**: `src/backend/bisheng/common/errcode/qa_expert.py`
  **逻辑**: `QaExpertQuestionAccessDeniedError` 18301 … `QaExpertPublishDurationInvalidError` 18310，继承 `BaseErrorCode`。模块码已在 release-contract 登记。
  **依赖**: 无

### 后端 Domain（Test-First）

- [x] **T004**: CapabilityResolver 单测
  **文件**: `src/backend/test/qa_expert/test_capability_resolver.py`
  **逻辑**: mock 仓储。断言 `display_status` 三态；`unresolved` 筛选集合；directed 可见性；回答/评论/采纳/转公开 capabilities。
  **测试**: `test_display_status_unanswered_pending_solved`；`test_directed_hidden_from_stranger`；`test_public_expert_can_answer_before_first_adopt`；`test_disabled_expert_cannot_answer`
  **覆盖 AC**: AC-01, AC-02, AC-04, AC-06, AC-12, AC-13, AC-14, AC-15, AC-37
  **依赖**: T002, T003

- [x] **T005**: CapabilityResolver 实现
  **文件**: `src/backend/bisheng/qa_expert/domain/capability.py`
  **逻辑**: `resolve(user, question) -> QuestionCapabilities + display_status`；专家库管理员对齐 `is_admin()`+角色名集；不查 `role_access`。
  **测试**: T004 全绿
  **覆盖 AC**: AC-01, AC-02, AC-04, AC-06, AC-12, AC-13, AC-14, AC-15
  **依赖**: T004

- [x] **T006**: 提问/列表/类似问题 单测
  **文件**: `src/backend/test/qa_expert/test_question_service.py`
  **逻辑**: 定向邀 1–3；公开 0–3；无权列表/详情/similar 不回标题；未登录拒绝；similar 不合并问题；存量默认 public。
  **覆盖 AC**: AC-03, AC-04, AC-05, AC-06, AC-07, AC-41, AC-42
  **依赖**: T002, T003

- [x] **T007**: QuestionService 实现
  **文件**: `src/backend/bisheng/qa_expert/domain/services.py`（提问/列表方法增量）
  **逻辑**: 写 `qa_question` + `qa_question_invite`；列表 `filter=mine|invited_me` 与 `display_status`；禁止用 status=3/4 当待采纳。详情 `hydrate_related_docs`：解析 `{spaceId}-{fileId}`，按访问者 knowledge 权限填 `RelatedDocView`；`forbidden` 不得写成 `not_found`。
  **测试**: T006、T020 全绿
  **覆盖 AC**: AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-41, AC-42, AC-47, AC-48
  **依赖**: T005, T006

- [x] **T008**: 回答与首答锁 单测
  **文件**: `src/backend/test/qa_expert/test_answer_lock.py`
  **逻辑**: 首答原子 `content_locked` 0→1；并发双首答都成功；删光未采纳答不解锁。
  **覆盖 AC**: AC-09, AC-10, AC-11
  **依赖**: T002, T003

- [x] **T009**: 回答提交实现
  **文件**: `src/backend/bisheng/qa_expert/domain/services.py`（`submit_answer`）
  **逻辑**: 资格校验；插 `qa_answer`；条件更新锁；通知 inbox。
  **测试**: T008 全绿
  **覆盖 AC**: AC-09, AC-10, AC-11
  **依赖**: T005, T008

- [x] **T010**: 评论资格 单测
  **文件**: `src/backend/test/qa_expert/test_comment_gate.py`
  **逻辑**: 定向无有效回答不可评；有答可评；公开可评；追问不受专家先答门槛。
  **覆盖 AC**: AC-43, AC-44, AC-45
  **依赖**: T002, T003

- [x] **T011**: `add_comment` 实现
  **文件**: `src/backend/bisheng/qa_expert/domain/services.py`（评论方法）
  **逻辑**: 18309；写匿名/reveal_on_public。
  **测试**: T010 全绿
  **覆盖 AC**: AC-43, AC-44, AC-45
  **依赖**: T009, T010

- [x] **T012**: 采纳槽位 单测
  **文件**: `src/backend/test/qa_expert/test_adopt.py`
  **逻辑**: 首次采纳 resolved；第 4 次 18304；同专家多答可多槽；公开首次采纳写 eligibility（含已删未采纳答作者）；mock F070 挂钩被调用且本域不写 `user_point_log`。
  **覆盖 AC**: AC-16, AC-17, AC-18, AC-14
  **依赖**: T002, T003

- [x] **T013**: `adopt_answer` 实现
  **文件**: `src/backend/bisheng/qa_expert/domain/services.py`（采纳）
  **逻辑**: 锁问题行；写 `qa_answer_adopt`；调既有 points hook。
  **测试**: T012 全绿
  **覆盖 AC**: AC-16, AC-17, AC-18, AC-14
  **依赖**: T009, T012

- [x] **T014**: 匿名别名 单测
  **文件**: `src/backend/test/qa_expert/test_anonymous_alias.py`
  **逻辑**: 时间序 A/B；删内容不重排；非管理员响应无真名字段；管理员可读真名。
  **覆盖 AC**: AC-19, AC-20, AC-21, AC-22
  **依赖**: T002

- [x] **T015**: `mask_identity` 实现
  **文件**: `src/backend/bisheng/qa_expert/domain/identity.py`
  **逻辑**: 读写 `qa_anonymous_alias`；转公开用预存 reveal 字段，不再询问。
  **测试**: T014 全绿
  **覆盖 AC**: AC-19, AC-20, AC-21, AC-22
  **依赖**: T014

- [x] **T016**: 转公开 单测
  **文件**: `src/backend/test/qa_expert/test_publish_request.py`
  **逻辑**: duration∈{1,3,7}；同题一 pending；同意/拒绝不可改；默认同意可静默通过+审计；到期 expired；提问者停用 ended；+1 天延期累计≤3；通过后非受邀不可答。
  **覆盖 AC**: AC-23, AC-24, AC-25, AC-26, AC-27, AC-28, AC-46, AC-34
  **依赖**: T002, T003

- [x] **T017**: PublishService 实现
  **文件**: `src/backend/bisheng/qa_expert/domain/publish_service.py`
  **逻辑**: `create_publish_request` / `decide_publish` / `on_expert_disabled`；通过后 `question_type=public`。
  **测试**: T016 全绿
  **覆盖 AC**: AC-23, AC-24, AC-25, AC-26, AC-27, AC-28, AC-46
  **依赖**: T013, T016

- [x] **T018**: 专家停用 单测
  **文件**: `src/backend/test/qa_expert/test_expert_status.py`
  **逻辑**: 非管理员写 18307；停用后不可邀/不可答；恢复不加入历史已结束申请；DELETE 映射为停用非硬删。
  **覆盖 AC**: AC-29, AC-30, AC-31, AC-35
  **依赖**: T002, T003

- [x] **T019**: 专家停用/恢复实现
  **文件**: `src/backend/bisheng/qa_expert/domain/services.py`（ExpertService 增量）
  **逻辑**: `disable_expert`/`enable_expert`；管理鉴权。
  **测试**: T018 全绿
  **覆盖 AC**: AC-29, AC-30, AC-31
  **依赖**: T017, T018

- [x] **T020**: 关联文档鉴权 单测
  **文件**: `src/backend/test/qa_expert/test_related_docs.py`
  **逻辑**: 详情始终返回问题正文。有权：`accessible=true`，id 与写入的 durable entry 一致。无权：`accessible=false` 且 `unavailable_reason=forbidden`，**不得**为 `not_found`。真删除：`not_found`。
  **覆盖 AC**: AC-08, AC-47, AC-48
  **依赖**: T007

- [x] **T021**: 通知 inbox 单测
  **文件**: `src/backend/test/qa_expert/test_inbox_notify.py`
  **逻辑**: 邀请/回答/采纳/转公开走 inbox；匿名触发人用别名；旧申请审批入口再鉴权失败。
  **覆盖 AC**: AC-36
  **依赖**: T009, T017

- [x] **T022**: 反向约束 单测
  **文件**: `src/backend/test/qa_expert/test_negative_guards.py`
  **逻辑**: 无 closed 状态写入；不把中文「管理员」设 `is_global_super`；专家库管理员调 moderate-delete 拒绝。
  **覆盖 AC**: AC-32, AC-33, AC-37, AC-38, AC-39, AC-40
  **依赖**: T005, T019

### 后端 API（Test-First）

- [x] **T023**: 问题 API 测试
  **文件**: `src/backend/test/qa_expert/test_question_api.py`
  **逻辑**: TestClient：POST/GET/PUT/DELETE questions；similar；错误 18301。GET 详情 `related_docs` 含 `accessible` / `unavailable_reason`。
  **覆盖 AC**: AC-04, AC-05, AC-06, AC-08, AC-41, AC-47, AC-48
  **依赖**: T007

- [x] **T024**: 问题 endpoints
  **文件**: `src/backend/bisheng/qa_expert/api/endpoints.py`
  **逻辑**: 委托 Service；`UserPayload.get_login_user`；`resp_200`。列表 query 对齐 design §2.2。
  **测试**: T023 全绿
  **覆盖 AC**: AC-04, AC-05, AC-06
  **依赖**: T007, T023

- [x] **T025**: 回答/采纳/评论 API 测试
  **文件**: `src/backend/test/qa_expert/test_answer_comment_api.py`
  **覆盖 AC**: AC-09, AC-16, AC-17, AC-43
  **依赖**: T011, T013

- [x] **T026**: 回答/采纳/评论 endpoints
  **文件**: `src/backend/bisheng/qa_expert/api/endpoints.py`
  **测试**: T025 全绿
  **覆盖 AC**: AC-09, AC-16, AC-43
  **依赖**: T013, T025

- [x] **T027**: 转公开 API 测试
  **文件**: `src/backend/test/qa_expert/test_publish_api.py`
  **覆盖 AC**: AC-23, AC-24
  **依赖**: T017
  **说明**: 并发首答（AC-10）已在 T008 覆盖，本任务不重复。

- [x] **T028**: 转公开 endpoints + router
  **文件**: `src/backend/bisheng/qa_expert/api/router.py`
  **逻辑**: 注册 publish-requests approve/reject；专家 disable/enable；OpenAPI 字段与 design 一致便于导 YApi。
  **测试**: T027 全绿
  **覆盖 AC**: AC-23, AC-24
  **依赖**: T017, T027

- [x] **T029**: 专家写接口鉴权 API 测试
  **文件**: `src/backend/test/qa_expert/test_expert_admin_api.py`
  **覆盖 AC**: AC-29, AC-30, AC-32
  **依赖**: T019

- [x] **T030**: 专家 endpoints 收口
  **文件**: `src/backend/bisheng/qa_expert/api/endpoints.py`
  **逻辑**: create 必须登录+管理员；DELETE deprecated 转 disable；moderate-delete 保持 `require_platform_admin`。
  **测试**: T029 全绿
  **覆盖 AC**: AC-29, AC-30, AC-32, AC-33
  **依赖**: T019, T029

### Worker

- [x] **T031**: 转公开过期任务测试
  **文件**: `src/backend/test/qa_expert/test_publish_expire_task.py`
  **逻辑**: freeze 时间；pending 且 `expire_at<=now` → expired；通知 inbox。
  **覆盖 AC**: AC-26
  **依赖**: T017

- [x] **T032**: Celery 过期任务
  **文件**: `src/backend/bisheng/worker/qa_expert/tasks.py`
  **逻辑**: Beat 扫描；任务参数带 `tenant_id`，执行前恢复 `current_tenant_id` ContextVar；读时惰性过期与 Beat 双保险。
  **测试**: T031 全绿
  **覆盖 AC**: AC-26
  **依赖**: T017, T031

### Portal 前端（非 Platform/Client）

- [x] **T033**: Portal API 契约对齐
  **文件**: `shougang-group-knowledge-portal/frontend/src/api/expertQa.ts`
  **逻辑**: `display_status`、`capabilities`、`filter`、`RelatedDocView`、publish/disable 类型与 design §2 一致；废弃 status=3/4 业务态。
  **覆盖 AC**: AC-03
  **依赖**: T024

- [x] **T034**: 列表页三态与筛选
  **文件**: `shougang-group-knowledge-portal/frontend/src/pages/ExpertQAPage.tsx`
  **逻辑**: 文案未回答/待采纳/已解决；testid 见 ui-test-cases §3。
  **覆盖 AC**: AC-01, AC-02, AC-37
  **依赖**: T033

- [x] **T035**: 提问页定向/公开/类似问题
  **文件**: `shougang-group-knowledge-portal/frontend/src/pages/ExpertQAAskPage.tsx`
  **逻辑**: 定向必邀；类似问题不阻断；关联文档选择器只提交 durable `{spaceId}-{fileId}`；挂 testid。
  **覆盖 AC**: AC-04, AC-05, AC-42, AC-47
  **依赖**: T033, T046

- [x] **T036**: 详情页资格驱动 UI
  **文件**: `shougang-group-knowledge-portal/frontend/src/pages/ExpertQADetailPage.tsx`
  **逻辑**: 只按 `capabilities` 显隐回答/采纳/评论/转公开/锁定条/文档灰显/匿名身份。无权文档用 `eqa-related-doc-blocked`，文案不得为「文档不存在」。
  **覆盖 AC**: AC-08, AC-09, AC-12, AC-16, AC-19, AC-23, AC-47, AC-48
  **依赖**: T033

- [x] **T037**: 专家管理停用
  **文件**: `shougang-group-knowledge-portal/frontend/src/pages/ExpertManagePage.tsx`
  **逻辑**: 删除按钮改为停用/恢复；非 `isPortalAdmin` 无写入口。
  **覆盖 AC**: AC-29, AC-30, AC-31
  **依赖**: T033

- [x] **T038**: 违规删除入口
  **文件**: `shougang-group-knowledge-portal/frontend/src/pages/ExpertQADetailPage.tsx`（增量）
  **逻辑**: `eqa-moderate-delete` 仅 `canModerateExpertQaPoints`。
  **覆盖 AC**: AC-32, AC-33
  **依赖**: T036

- [x] **T046**: 门户 QA 选择树与详情同一 ID
  **文件**: `shougang-group-knowledge-portal/backend/app/api/routes/knowledge.py`（`list_qa_tree_children` 等）
  **逻辑**: 登录态选择关联文档时，children 返回的 `fileId` 必须与 `/space/{spaceId}/file/{fileId}` / `shougang-portal/files` 能 resolve 的 entry 一致。禁止再对 QA picker 使用与详情不一致的 `discovery_scope=legacy`。不在 `qa_expert` 另造映射表。无 DDL。
  **覆盖 AC**: AC-47
  **依赖**: T033

- [x] **T047**: 关联文档打开文案分流
  **文件**: `shougang-group-knowledge-portal/frontend/src/pages/DetailPage.tsx`、`ExpertQADetailPage.tsx`
  **逻辑**: `error || !detail` 不得一律「文档不存在」。有权且 resolve 成功：标题+预览。`forbidden`：无权限/链接不可用。仅真删除或无 entry：`not_found` 才用「文档不存在」。testid：`eqa-related-doc` / `eqa-related-doc-blocked`。
  **覆盖 AC**: AC-08, AC-47, AC-48
  **依赖**: T033, T036

### 接口落库流转（真实 MySQL，Playwright 之前）

> 验收门：171 MySQL（`config.yaml`）。SQLite / mock 仓储不算本段完成。数据前缀 `df-flow-`，测完删除。无 DDL。

- [x] **T048**: 流转测试改打 171 MySQL
  **文件**: `src/backend/test/qa_expert/conftest.py`、`test_data_flow.py`、`features/.../api-data-flow-matrix.md`
  **逻辑**: 夹具用 `config.yaml` 解密后的 MySQL（aiomysql）；每次 `get_async_db_session` 新连接（勿共用一条 session，否则测不到行锁）。标题/专家名 `df-flow-`；user_id 用 88xxxxxx 段避免撞现网账号；fixture 起止按前缀清理 `qa_*`。跑通 DF-01～DF-13。先 `alembic upgrade head`。
  **覆盖 AC**: AC-04, AC-05, AC-06, AC-08, AC-09, AC-11, AC-12, AC-14, AC-15, AC-16, AC-17, AC-23, AC-24, AC-28, AC-29, AC-30, AC-31, AC-43, AC-47
  **依赖**: T023, T025, T027, T029

- [x] **T049**: MySQL 行锁 / 并发首答
  **文件**: `src/backend/test/qa_expert/test_data_flow.py`（增量）
  **逻辑**: 两专家并发 POST 首答：两行 `qa_answer` 均可成功；`content_locked` 仅 0→1 一次。两路并发采纳不同回答：走 `SELECT … FOR UPDATE`，槽位与 `adopt_count` 与成功次数一致、无超 3。
  **覆盖 AC**: AC-10, AC-17
  **依赖**: T048

### UI 自动化（Playwright，85%）

- [x] **T039**: Playwright 工程脚手架
  **文件**: `shougang-group-knowledge-portal/frontend/playwright.config.ts`
  **逻辑**: baseURL `http://127.0.0.1:5173`；`use.headless: true`（CI=`true` 禁止 `--headed`）；角色 `storageState` 目录 `e2e/.auth/`；trace=on-first-retry。新增依赖 `@playwright/test`。执行约定见 ui-test-cases §6：回归/CI 用无头 CLI `npx playwright test e2e/expert-qa --project=chromium`；Agent 单步排障可用 Playwright MCP（`user-playwright`），不替代 CLI 门禁。
  **依赖**: T034

- [x] **T040**: 夹具与 Page Object
  **文件**: `shougang-group-knowledge-portal/frontend/e2e/expert-qa/fixtures.ts`
  **逻辑**: 实现 ui-test-cases §5.1 角色夹具；种子数据前缀 `uitest-f083-`。
  **依赖**: T039

- [ ] **T041**: P0 列表/提问/可见性 E2E
  **文件**: `shougang-group-knowledge-portal/frontend/e2e/expert-qa/list-ask-access.spec.ts`
  **逻辑**: 落地 UI-01～UI-09（样例见 ui-test-cases §5.2/§5.3）。执行：无头 `npx playwright test e2e/expert-qa/list-ask-access.spec.ts --project=chromium`；单条失败可用 MCP 复现。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-41, AC-42, AC-37
  **依赖**: T034, T035, T040

- [ ] **T042**: P0 回答/锁定/采纳/匿名 E2E
  **文件**: `shougang-group-knowledge-portal/frontend/e2e/expert-qa/answer-adopt-anon.spec.ts`
  **逻辑**: UI-10～UI-16, UI-20, UI-21, UI-23, UI-25, UI-41（采纳样例 §5.4）。执行：无头 CLI；MCP 仅单步。
  **覆盖 AC**: AC-08, AC-09, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-19, AC-21, AC-47, AC-48
  **依赖**: T036, T040, T046, T047

- [ ] **T043**: P0 转公开与管理 E2E
  **文件**: `shougang-group-knowledge-portal/frontend/e2e/expert-qa/publish-admin.spec.ts`
  **逻辑**: UI-27～UI-30, UI-32～UI-34。执行：无头 CLI；MCP 仅单步。
  **覆盖 AC**: AC-22, AC-23, AC-24, AC-28, AC-29, AC-30, AC-31, AC-32, AC-33
  **依赖**: T036, T037, T038, T040

- [ ] **T044**: P1 补齐至 85%
  **文件**: `shougang-group-knowledge-portal/frontend/e2e/expert-qa/p1-coverage.spec.ts`
  **逻辑**: UI-17～19, UI-22, UI-24, UI-26, UI-31, UI-35, UI-36。无头 CLI 跑完后对照矩阵，自动化行必须 = 35/41。
  **覆盖 AC**: AC-18, AC-20, AC-36, AC-43, AC-44, AC-45
  **依赖**: T041, T042, T043

- [x] **T045**: UI 覆盖率门禁说明
  **文件**: `shougang-group-knowledge-portal/frontend/e2e/expert-qa/README.md`
  **逻辑**: 记录 35/41≈85%；列出 UI-37～40 不进 Playwright 的原因及对应 pytest：T008（AC-10）、T016（AC-25, AC-27, AC-34, AC-35, AC-46）、T031（AC-26）。写明执行：默认无头 `npx playwright test e2e/expert-qa --project=chromium`；CI 禁止 headed；Playwright MCP 仅 Agent 单步复现，不计入门禁。
  **依赖**: T044

---

## AC 追溯总表

| AC | 后端测试任务 | UI 任务 |
|----|--------------|---------|
| AC-01, AC-02, AC-37 | T004 | T041 |
| AC-03 | T006 | T041 |
| AC-04, AC-05, AC-06, AC-41, AC-42 | T006, T023 | T041 |
| AC-07 | T006 | —（迁移，非 UI） |
| AC-08, AC-47, AC-48 | T020 | T042, T046, T047 |
| AC-09, AC-11 | T008 | T042 |
| AC-10 | T008, T049 | T045（降级 pytest；真库并发以 T049 为准） |
| AC-12, AC-13, AC-14, AC-15 | T004, T012 | T042 |
| AC-16, AC-17 | T012, T025 | T042 |
| AC-18 | T012 | T044 |
| AC-19, AC-21 | T014 | T042 |
| AC-20, AC-22 | T014 | T044 / T043 |
| AC-23, AC-24, AC-28 | T016, T027 | T043 |
| AC-25, AC-26, AC-27, AC-34, AC-35, AC-46 | T016, T031 | T045（降级） |
| AC-29, AC-30, AC-31, AC-32, AC-33 | T018, T029 | T043 |
| AC-36 | T021 | T044 |
| AC-38, AC-39, AC-40 | T022 | — |
| AC-43, AC-44, AC-45 | T010 | T044 |

---

## 实际偏差记录

- T001：新表主键用 `INT`（非 design BIGINT），对齐现网 `qa_question.id` / `qa_answer.id`，避免 INT/BIGINT 混用。revision=`f083_expert_qa_enhancement`，接 `f086_merge_points_qa_images`（仓库已有其它 f083_* revision 名，不能复用）。专家 `(tenant_id, user_id)` 唯一：发现重复则跳过加约束、不删行。
- 2026-08-15：合入 `feat/2.5.0-sg` 后与 `f087`/`f089` 三 head 并存，补空合并 `f090_merge_f083_f087_f089`（无 DDL）。
- 2026-08-15 冻结后增量：现网「关联文档显示文档不存在」→ AC-47/48、AD-11、T046（选择树 ID）、T047（文案分流）。任务 45→47。不在 `qa_expert` 另造文档映射；不改 F059 resolver 实现（本 Feature 只消费正确 entry id）。无 DDL。
- 2026-08-15：开发自验收改为真实 MySQL（171）接口+落库流转，增量 T048–T049；T039 Playwright 仍停。无 DDL。
- 2026-08-15：T048/T049 完成。原 `get_by_id_for_update` 返回即释放行锁，并发首答/采纳丢失 `answer_count`/`adopt_count` 并撞资格唯一键；改为 `increment_answer_count` + 同一事务 `apply_adopt_count_locked`。171 上 DF-01～15 全绿。无 DDL。
- 2026-08-15：T039/T040/T045 落地 Playwright 脚手架、角色夹具、README；T041–T044 spec 已写。列表/提问加 RequireAuth（AC-41）；锁后隐藏编辑删除。CLI 门禁需 `e2e/.auth/credentials.json` + 联调栈，尚未跑绿。无 DDL。
