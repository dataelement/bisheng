# Tasks — F066 PAT 数据范围收窄与「AI 助手接入」界面

**关联规格**: [spec.md](./spec.md) · 设计: [design.md](./design.md)
**版本**: v3.0.0-beta1

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-09-13 `/sdd-review spec`（1 CONFLICT 经契约修订处置、3 low 已修、补 AC-R7），用户已确认 |
| design.md | ✅ 已评审 | 2026-09-13 `/sdd-review design`（自查修 C4 分层 high + C4 触碰登记），用户已确认 |
| tasks.md | ✅ 已拆解 | 2026-09-13 `/sdd-review tasks` |
| 实现 | 🔲 未开始 | 0 / 26。偏差处理见 design.md 顶部调整原则 |

AC 编号来源：AC-P23～AC-P31 = PRD v2.9 §五 R10；AC-R1～AC-R7 = spec §3。

---

## Tasks

### Wave 0 · 基础设施（无测试配对）

- [ ] **T001**: 错误码 26044
  **文件**: `src/backend/bisheng/common/errcode/open_api.py`
  **逻辑**: 26043 之后新增 `PersonalTokenDataScopeError`（26044，HTTP 403，msg「个人访问令牌数据范围受限」；`data` 只含 `{"scope": "personal_only"}`，不列资源 id——防枚举，design 决策 2）
  **依赖**: 无

- [ ] **T002**: `open_api_tenant_setting` 加列 + alembic
  **文件**: `src/backend/bisheng/open_api/domain/models/open_api_tenant_setting.py`、`src/backend/bisheng/core/database/alembic/versions/`（新文件）
  **逻辑**: 模型加 `pat_data_scope: str`（`server_default 'all_visible'`，常量 `DATA_SCOPE_ALL='all_visible'` / `DATA_SCOPE_PERSONAL='personal_only'`）；新迁移 down_revision=当时 `alembic heads` 唯一头（勿改 `f053_pat_tenant_setting`——已有后继），upgrade 加列带 server_default、downgrade 对称 drop（可回滚）；遵守 `alembic/AGENTS.md` 单头纪律
  **依赖**: 无

- [ ] **T003**: 契约 schema 字段
  **文件**: `src/backend/bisheng/open_api/domain/schemas/personal_token.py`
  **逻辑**: `PersonalTokenSettingUpdate.data_scope: str | None = None`（可选=保持现值，design 决策 4；仍 `extra="forbid"`，值域校验 all_visible/personal_only）；`PersonalTokenSettingResponse.data_scope: str`；`PersonalTokenStatus` 增 `data_scope: str` 与 `ttl_days: int`（弹窗四态与 `{{days}}` 数据源）
  **依赖**: 无

### Wave 1 · 后端策略链路（Test-First 配对）

- [ ] **T004**: 策略链路单元测试
  **文件**: `src/backend/test/open_api/test_pat_tenant_setting.py`（扩展既有）
  **逻辑**: ①缓存 dict 缺 `data_scope` 键 → 按 all_visible（模拟旧节点回填）；②DB 未知值 → 按 personal_only；③PUT 缺省字段 → 现值不变（preserve）；④PUT 变更 → 写审计（action `open_api.pat.settings.update`、before/after 三字段、操作人）、未变更不写；⑤写后 invalidate、sync 路径零缓存直读
  **覆盖 AC**: AC-R1, AC-R6, AC-P28
  **依赖**: T002, T003

- [ ] **T005**: 策略链路实现
  **文件**: `src/backend/bisheng/open_api/domain/services/tenant_setting_service.py`
  **逻辑**: `TenantPatPolicy` 加 `data_scope` 字段；**七处引用同步**（cache 读 :35-39 缺键=all_visible / DB 回退 :41-45 未知值=personal_only / cache 写 :46-50 / sync :53-59 / 响应组装 :61-70 / 覆盖写 :81-82 改 preserve / dataclass :23-26）；`update` 增审计写入（范本 `personal_token_service.py:73-79`，写 `audit_log.audit_metadata`，仅值变化时）
  **测试**: T004 全绿
  **覆盖 AC**: AC-R1, AC-R6, AC-P28
  **依赖**: T004

### Wave 2 · 权限层强制与收口（Test-First 配对）

- [ ] **T006**: 权限层强制单元测试（mock 解析协议）
  **文件**: `src/backend/test/permission/test_data_scope_enforcement.py`（新）
  **逻辑**: mock `DataScopeOwnershipResolver`：①actor.data_scope 受限 + 资源非 owned → `check_action` 在 `_identity_shortcut`（super_admin=True）之前抛 `DataScopeDeniedError`；②`check_visible` 在 FGA 查询前拒绝（FGA client 不被调用）；③batch 同；④`list_visible_objects` 结果与 owned 集取交（静默、不抛）；⑤协议未注册 + 受限 actor → 一律拒绝（fail-closed）；⑥data_scope='all' 零行为变化
  **覆盖 AC**: AC-P24, AC-P26, AC-P23
  **依赖**: T001

- [ ] **T007**: 权限层强制实现
  **文件**: `src/backend/bisheng/permission/application/data_scope.py`（新：协议 + 注册表 + `DataScopeDeniedError`）、`src/backend/bisheng/permission/application/identity.py`（`PermissionActor` 加 `data_scope: str = "all"`）、`src/backend/bisheng/permission/application/permission_action_service.py`（四判定点前置调用）
  **逻辑**: design 决策 1/2——判定先于身份短路与 FGA；权限层**不 import 业务 ORM**（C4/INV-10），只调注册协议；请求内 memo 在协议实现侧
  **测试**: T006 全绿
  **覆盖 AC**: AC-P24, AC-P26
  **依赖**: T006

- [ ] **T008**: 归属解析器口径单元测试
  **文件**: `src/backend/test/open_api/test_data_scope_resolver.py`（新）
  **逻辑**: ①文档/QA 库按 `knowledge.user_id=持有人 AND type IN (0,1)`；②空间按 CREATOR∧ACTIVE 成员行 ∧ 无 `department_knowledge_space` 绑定（绑定后即不算——AC-P25 边界）；③本人库内他人文件仍 owned（按父判，不下探创建者）；④file→parent 一次批量归父 + 请求内 memo（同父只查一次）；⑤user_id 为 NULL 的存量行 → 不 owned（fail-closed 表现）
  **覆盖 AC**: AC-P25
  **依赖**: T007

- [ ] **T009**: 归属解析器实现 + 装配注册
  **文件**: `src/backend/bisheng/knowledge/domain/services/data_scope_resolver.py`（新）、装配注册落点（随 T007 注册表的既有装配点，如 permission wiring / app 初始化，≤1 处改动）
  **逻辑**: 口径 A（design 决策 3）：复用 `KnowledgeDao.aget_knowledge_ids_created_by`（knowledge.py:309-328，现零调用方）+ 空间 CREATOR 口径（同 `get_my_created_spaces` 事实源，含部门剪除）；knowledge_file 批量取父后归父判定
  **测试**: T008 全绿
  **依赖**: T007, T008

- [ ] **T010**: 收窄覆盖矩阵测试（先红后绿）
  **文件**: `src/backend/test/open_api/test_data_scope_matrix.py`（新）
  **逻辑**: 从 `open_api/domain/scopes.py` 注册表读 `knowledge:read` 全端点 ×（员工 / 租管 / 超管 PAT）×（all_visible / personal_only）参数化：默认档全组合与现状一致（AC-P23）；收窄档非 owned → 403/26044 且响应无资源存在性信息（AC-P24、AC-R2）；清单端点只回 owned、静默无 26044（AC-R2）；管理员/超管同样收窄（AC-P26）；QA 读取端点同罩（AC-P27）；注册表新增端点未入矩阵 → 测试失败（AC-R3）；改配置后 ≤5s 生效走 invalidate 断言（AC-P24）
  **覆盖 AC**: AC-P23, AC-P24, AC-P25, AC-P26, AC-P27, AC-R2, AC-R3
  **依赖**: T005, T007, T009

- [ ] **T011**: 闸口装填 + status 下发
  **文件**: `src/backend/bisheng/open_api/api/dependencies.py`、`src/backend/bisheng/open_api/domain/services/execution_context.py`、`src/backend/bisheng/open_api/domain/services/personal_token_service.py`
  **逻辑**: dependencies 在 natural_person 分支复用既有 `get_policy` 调用（:69-73，**不加第二次策略读取**——design 坑 15）取 data_scope 装入 `PermissionActor`（:113-118）；execution_context 重放时 `get_policy_sync` 重取（不信任快照旧值）；`status` 响应下发 `data_scope` 与生效 `ttl_days`（管理员=min 后实际值，:52-53）
  **测试**: T010 相应格转绿
  **覆盖 AC**: AC-P24, AC-P31
  **依赖**: T005, T007, T010

- [ ] **T012**: 旁路收口
  **文件**: `src/backend/bisheng/knowledge/domain/services/knowledge_service.py`、`src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`
  **逻辑**: design 决策 5——①`get_knowledge` admin 分支（:502/:547）：actor.data_scope 受限时强制 visible-first/owned 候选并恢复批检；②`system_scope = login_user.is_global_super`（:2841/:2990）：受限 actor 不得进入 system_scope 分支（v2 面咨询 ContextVar actor）
  **测试**: T010 管理员/超管格转绿
  **覆盖 AC**: AC-P26, AC-P27
  **依赖**: T010, T011

- [ ] **T013**: 静态防线断言测试
  **文件**: `src/backend/test/open_api/test_data_scope_static_guard.py`（新）
  **逻辑**: 断言 v2 请求链路（open_endpoints/ 与 knowledge 域 v2 消费路径）`login_user.is_admin()/is_global_super` 消费点数量恒定为登记清单（新增即 fail）——AC-R3 的矩阵之外静态防线
  **覆盖 AC**: AC-R3
  **依赖**: T012

### Wave 3 · 技能包（Test-First 配对）

- [ ] **T014**: 技能包内容断言测试
  **文件**: `src/backend/test/open_api/test_skill_pack.py`（扩展既有）
  **逻辑**: zip 含 `references/api.md` 且已渲染 `{{BASE_URL}}`；SKILL.md description 含中文触发词（知识库/检索）与「先列清单再检索」流程指引；search.py 对非 2xx 响应输出 `status_code`/`status_message`（构造 HTTPError body 单测）；打包服务源码零 diff 断言可省略、由 review 把关
  **覆盖 AC**: AC-R4
  **依赖**: T001

- [ ] **T015**: 技能包静态文件修缮
  **文件**: `src/backend/bisheng/open_api/skill_packs/bisheng-knowledge-search/SKILL.md`、`.../scripts/search.py`、`.../references/api.md`（新）
  **逻辑**: design 决策 8——SKILL.md 补中文触发词 + 先清单后检索流程；search.py 读 `exc.read()` 透出业务码与 message；api.md 全量契约（端点表 / wrapper 与 chunk 字段 / extra=forbid / top_k≤200 / QA·个人库不可检索 / cursor 分页 / 引用回链格式 / 错误码表 26001·26002·26003·26030·26040·26043·26044 各自行动指引 / type=3 清单不含部门空间）
  **测试**: T014 全绿
  **覆盖 AC**: AC-R4
  **依赖**: T014

### Wave 4 · 前端 Client（组件测试 + 手动验证）

- [ ] **T016**: client i18n 键族
  **文件**: `src/frontend/client/src/locales/zh-Hans/translation.json`、`en/translation.json`、`ja/translation.json`
  **逻辑**: 新增 `com_ai_access_*` 键族（弹窗四态 / 风险文案 / 入口 / 关停态，文案以 PRD §4.10.6 与交互稿为准）；旧 `com_personal_token*` 键随 T017/T018 组件切换删除（同 PR 内完成，不留双轨）
  **覆盖 AC**: AC-R5
  **依赖**: 无

- [ ] **T017**: 弹窗改造（AI 助手接入）
  **文件**: `src/frontend/client/src/components/PersonalTokenDialog.tsx`（改造，超 600 行则按 design 决策 6 拆子组件）、`src/frontend/client/src/api/personalToken.ts`
  **逻辑**: 基于 beta1 两步弹窗扩状态机：管理员签发前勾选确认（仅 holder_is_admin × data_scope=all）、密钥展示红条 + 范围卡四态（status.data_scope × holder_is_admin）+ 风险红条、`{{days}}` 用 status/签发响应实际值、旧红字文案删除；「最后使用」空值→「从未使用」
  **手动验证**: :4001/workspace 员工与管理员各走一遍生成流程，切管理端收窄后验四态文案与管理员确认降级
  **覆盖 AC**: AC-P29, AC-P31
  **依赖**: T003, T011, T016

- [ ] **T018**: 入口重构 + 深链
  **文件**: `src/frontend/client/src/pages/knowledge/sidebar/KnowledgeSpaceSidebar.tsx`、`src/frontend/client/src/pages/settings/settingsSections.ts`、`src/frontend/client/src/pages/settings/sections/AccountPane.tsx`（移除原行，弹窗挂载迁至新分区文件）
  **逻辑**: 知识库页 sidebar 底部常驻入口（沿用 `shouldShowPersonalTokenEntry` 双闸）+ 设置一级分区 `ai-access`（新 section 组件挂弹窗与关停态卡）；深链 `/settings/ai-access?connect=1` 拉起弹窗，旧 `?api-token=1` 兼容映射；租户关停：入口隐藏、分区保留解释
  **手动验证**: 双入口开同一弹窗；`?api-token=1` 旧链仍拉起；管理端关停后知识库页入口消失、设置分区显示关停说明
  **覆盖 AC**: AC-P30, AC-R7
  **依赖**: T016, T017

- [ ] **T019**: client 组件测试
  **文件**: `src/frontend/client/src/pages/settings/sections/personalTokenEntry.test.ts`（更新）、`src/frontend/client/src/components/PersonalTokenDialog.test.tsx`（更新/新增）
  **逻辑**: 入口显隐双闸、四态范围文案渲染、管理员确认门控与收窄降级、深链参数拉起、旧文案键不再被引用（AC-P29 自动化半边）
  **覆盖 AC**: AC-P29, AC-P30, AC-P31, AC-R7
  **依赖**: T017, T018

### Wave 5 · 前端 Platform（组件测试 + 手动验证）

- [ ] **T020**: platform i18n
  **文件**: `src/frontend/platform/public/locales/zh-Hans/bs.json`、`en-US/bs.json`、`ja/bs.json`
  **逻辑**: `openApiManagement` 块：Tab/标题改「AI 助手接入」、「租户策略」→「使用策略」、scopeMode 四键（label/all/ownOnly/hint）、收紧确认两键、保存 toast 改「对所有已发放的密钥立即生效」、`deploymentDisabled` 补行动指引、「管理员风险」→「管理员持有」、权限位值显示「只读检索」
  **覆盖 AC**: AC-R5
  **依赖**: 无

- [ ] **T021**: 使用策略卡 + 契约接线
  **文件**: `src/frontend/platform/src/pages/SystemPage/components/PersonalToken/index.tsx`、`src/frontend/platform/src/controllers/API/personalToken.ts`、`src/frontend/platform/src/types/api/openApi.ts`
  **逻辑**: 策略卡加 RadioGroup（全部可见默认 / 仅自建 + hint）；从「全部→仅自建」保存前确认弹窗（文案 T020），反向不确认；PUT 显式带 `data_scope`；保存后回填 + toast
  **手动验证**: :3001 系统管理 → AI 助手接入:切档保存、确认弹窗、员工端密钥立即受限（配合 T010 matrix 或手调 v2 检索验 26044）
  **覆盖 AC**: AC-P28, AC-P24
  **依赖**: T003, T005, T020

- [ ] **T022**: 台账修缮
  **文件**: `src/frontend/platform/src/pages/SystemPage/components/PersonalToken/index.tsx`（台账段；若超 600 行拆 `LedgerTable.tsx` 子组件）
  **逻辑**: 吊销加确认弹窗；「按持有人吊销」合并入「吊销」；补分页（复用后端既有 page/page_size）；管理员徽标与权限列文案切 T020 新键
  **手动验证**: 台账翻页、吊销确认、徽标 tooltip
  **覆盖 AC**: AC-P29
  **依赖**: T020, T021

- [ ] **T023**: platform 测试
  **文件**: `src/frontend/platform/src/test/personalTokenSettingsInteraction.test.tsx`（扩展）、`src/frontend/platform/src/test/openApiManagementApi.test.ts`（扩展）
  **逻辑**: RadioGroup 切档 + 收紧确认流 + PUT 载荷含 data_scope + 保存回填;API 层字段断言
  **覆盖 AC**: AC-P28, AC-R5
  **依赖**: T021, T022

### Wave 6 · 共享 i18n 与收尾

- [ ] **T024**: api_errors 域错误码文案
  **文件**: `src/frontend/packages/locales/src/api_errors/zh-Hans.json`、`en.json`、`ja.json`（+ 重跑 build 产物，产物禁手改）
  **逻辑**: 新增 26044 三语（「个人密钥的检索范围已被管理员限定为仅本人创建的知识库」量级、说人话）；26040 文案按「AI 助手接入」新口径改写
  **覆盖 AC**: AC-R5
  **依赖**: T001

- [ ] **T025**: constitution C4 措辞增补
  **文件**: `docs/constitution.md`
  **逻辑**: C4 短路顺序处补一句「开放面自然人主体的 data_scope 拒绝（F066/D21）先于以上全部身份短路」——design §2 第 7 条登记的宪法触碰，走 PR review 治理
  **依赖**: T007

- [ ] **T026**: e2e 与验收记录
  **文件**: `features/v3.0.0-beta1/066-pat-data-scope-and-ai-access/e2e-checklist.md`（新）
  **逻辑**: 执行 `/e2e-test features/v3.0.0-beta1/066-pat-data-scope-and-ai-access`：API 侧矩阵结果 + 浏览器手动清单（双入口 / 四态 / 管理员确认 / 收紧生效 / 深链）落档
  **覆盖 AC**: AC-P23, AC-P24, AC-P26, AC-P30, AC-P31
  **依赖**: T012, T018, T022

---

## 实际偏差记录

> 只留一行指针，论证在 design.md。推翻已 ★ 确认的决策先停下重确认。

（无）
