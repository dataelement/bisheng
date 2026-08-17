# Tasks: 知识空间与频道统一权限设置入口（F048 适配）

**关联规格**: [spec.md](./spec.md)
**关联设计**: [design.md](./design.md)
**版本**: v3.0.0-beta1

---

## 状态

| 步骤 | 状态 | 备注 |
|---|---|---|
| spec.md | ✅ 已评审 | 用户已确认 |
| design.md | ✅ 已评审 | 2026-08-17 用户确认；接手时第一入口 |
| tasks.md | ✅ 已拆解 | `/sdd-review tasks` 21 项评审 LGTM |
| 实现 | 🟡 进行中 | 20 / 37 完成；偏差见本文末尾 |

---

## Wave 0：合并基线与数据库基础

- [x] **T001 合入 2.6 UI 迁移基线**
  - **范围**: Git merge `origin/feat/2.6.0` → `feat/3.0.0-beta1-merge-2.6.0`
  - **逻辑**: 按 Design D8 逐项解冲突；完整页面布局/文案/移动交互取 2.6，F044 relation/permission_id/binding 不作为运行时保留，F048 代码与契约取 beta1；排除 COFCO F045/F046。
  - **验证**: 无 unmerged path；`git diff --check`；记录冲突文件与裁决结果。
  - **依赖**: 无

- [x] **T002 Knowledge/Channel 创建幂等 ORM 字段**
  - **文件**: `src/backend/bisheng/knowledge/domain/models/knowledge.py`, `src/backend/bisheng/channel/domain/models/channel.py`
  - **逻辑**: 两表增加 nullable `creation_request_id VARCHAR(64)` 和 `creation_payload_hash VARCHAR(64)`；不回填存量，不把创建草稿存 JSON。
  - **影响**: 修改 Knowledge/Channel 已有对象，仅增加 F050 幂等事实，不改 F048 Grant 归属。
  - **依赖**: T001

- [x] **T003 双库 DDL 与唯一索引**
  - **文件**: `src/backend/bisheng/core/database/alembic/versions/v3_0_0_beta1_f050_creation_idempotency.py`
  - **逻辑**: 仅 DDL；Knowledge 唯一范围 tenant + creator + type + request ID，Channel 为 tenant + creator + request ID；MySQL/DM8 兼容的 nullable 列和索引长度。
  - **回滚**: downgrade 先删索引再删两列；不做 SELECT/UPDATE/回填/seed。
  - **依赖**: T002

---

## Wave 1：Permission Application Protocol（后端 Test-First）

- [x] **T004 Prospective Grant 协议测试**
  - **文件**: `src/backend/test/permission/test_prospective_grant_application.py`
  - **逻辑**: 测试 owner 可授予 active models、Catalog release、tenant/active 主体 canonicalization、创建前不构造 target/不 Check/不写 Grant。
  - **覆盖 AC**: AC-01, AC-02, AC-07, AC-12, AC-13, AC-14, AC-18, AC-19, AC-27, AC-33
  - **依赖**: T003

- [x] **T005 Prospective Grant 协议实现**
  - **文件**: `src/backend/bisheng/permission/application/prospective_grant.py`, `src/backend/bisheng/permission/application/ports.py`
  - **逻辑**: 实现 `ProspectiveGrantApplicationPort`；只读 Catalog/subject directory，返回 release + grantable models，禁止业务 ORM 查询和权限写入。
  - **验证**: T004 全部通过。
  - **依赖**: T004

- [x] **T006 Initial Grant 协议测试**
  - **文件**: `src/backend/test/permission/test_initial_grant_application.py`
  - **逻辑**: verified target + ADD-only；重验 Catalog/model/subject/tenant/manage；原子普通 Grant mutation；稳定 idempotency key；拒绝 MOVE/REMOVE/protected/client source。
  - **覆盖 AC**: AC-13, AC-15, AC-16, AC-17, AC-18, AC-19, AC-23, AC-25, AC-33
  - **依赖**: T005

- [x] **T007 Initial Grant 协议实现**
  - **文件**: `src/backend/bisheng/permission/application/initial_grant.py`, `src/backend/bisheng/permission/application/ports.py`
  - **逻辑**: 实现 `InitialGrantApplicationPort`，只调 F048 durable mutation；返回真实 version/assignee/result，不创建或删除业务资源。
  - **验证**: T006 全部通过。
  - **依赖**: T006

---

## Wave 2：Knowledge/Channel 创建编排（后端 Test-First）

- [x] **T008 Knowledge 创建幂等与初始授权测试**
  - **文件**: `src/backend/test/knowledge/test_unified_permission_creation.py`
  - **逻辑**: 旧 payload；新 payload；资源/owner 失败；Grant 部分失败；同 key 同 hash 前向重试；同 key 异 hash 冲突；唯一键竞争；自动标签字段不丢。
  - **覆盖 AC**: AC-01, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-30, AC-31, AC-33
  - **依赖**: T007

- [x] **T009 Knowledge 创建编排实现**
  - **文件**: `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`, `src/backend/bisheng/knowledge/domain/schemas/knowledge_space_schema.py`
  - **逻辑**: 业务资源与 protected owner 先成功，再调 Initial Grant port；持久 request/hash；返回原资源形状 + 可选 result；保留自动标签及既有副作用。
  - **验证**: T008 全部通过。
  - **依赖**: T008

- [x] **T010 Channel 创建幂等与初始授权测试**
  - **文件**: `src/backend/test/channel/test_unified_permission_creation.py`
  - **逻辑**: 旧/新 payload、订阅外部信息源后重试不重复、owner/Grant 失败分界、同 key/hash 语义，保留 filter/subchannel/`knowledge_sync`。
  - **覆盖 AC**: AC-02, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-30, AC-32, AC-33
  - **依赖**: T007

- [x] **T011 Channel 创建编排实现**
  - **文件**: `src/backend/bisheng/channel/domain/services/channel_service.py`, `src/backend/bisheng/channel/domain/schemas/channel_manager_schema.py`
  - **逻辑**: 持久 request/hash；对已完成外部订阅的重试跳过重复副作用；资源 + owner 后调 Initial Grant port；保留知识同步/通知。
  - **验证**: T010 全部通过。
  - **依赖**: T010

- [x] **T012 创建 context/candidates API 测试**
  - **文件**: `src/backend/test/knowledge/test_creation_permission_context_api.py`, `src/backend/test/channel/test_creation_permission_context_api.py`
  - **逻辑**: 两域创建资格、同形 context、users/groups 分页、department children/search/path-tree、tenant 隔离、失权/fail-closed。
  - **覆盖 AC**: AC-01, AC-02, AC-07, AC-10, AC-11, AC-12, AC-13, AC-19, AC-27
  - **依赖**: T009, T011

- [x] **T013 创建 context/candidates API 实现**
  - **文件**: `src/backend/bisheng/knowledge/api/endpoints/knowledge_space.py`, `src/backend/bisheng/channel/api/endpoints/channel_manager.py`
  - **逻辑**: 实现 Design §4.6.1 路由；Endpoint 只注入 actor 并委托业务 Service/Prospective port，不查组织 ORM，不接受 tenant_id。
  - **验证**: T012 全部通过。
  - **依赖**: T012

---

## Wave 3：编辑与 private 语义（后端 Test-First）

- [x] **T014 Knowledge/Channel 编辑顺序与 private 测试**
  - **文件**: `src/backend/test/knowledge/test_unified_permission_update.py`, `src/backend/test/channel/test_unified_permission_update.py`
  - **逻辑**: 业务失败不写 Grant；private 只清 ordinary sources 且保留 protected/其他独立来源；编辑权与 manage 分离；失权、过期 version、多来源。
  - **覆盖 AC**: AC-03, AC-04, AC-07, AC-08, AC-09, AC-10, AC-11, AC-20, AC-21, AC-22, AC-23, AC-24, AC-25, AC-26, AC-27, AC-28, AC-29, AC-31, AC-32, AC-33
  - **依赖**: T013

- [x] **T015 Knowledge/Channel 编辑顺序与 private 实现**
  - **文件**: `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`, `src/backend/bisheng/channel/domain/services/channel_service.py`
  - **逻辑**: 保持业务可见性的 source ownership；private 复用 `remove_ordinary_sources`；投影成功后才清 membership/通知；不恢复旧 relation fallback。
  - **验证**: T014 全部通过。
  - **依赖**: T014

---

## Wave 4：Client API 与权限草稿

- [x] **T016 Client F048 adapter 契约测试**
  - **文件**: `src/frontend/client/src/api/unifiedPermissionSettings.test.ts`
  - **逻辑**: 创建 context/candidates 两域同形映射；创建可选字段/响应兼容；F048 context/grants/models/mutate 的 version 不丢失；AbortSignal 透传。
  - **覆盖 AC**: AC-01, AC-02, AC-07, AC-08, AC-09, AC-11, AC-12, AC-13, AC-16, AC-19, AC-20, AC-23, AC-30, AC-33
  - **依赖**: T013

- [x] **T017 Knowledge/Permission Client adapter 实现**
  - **文件**: `src/frontend/client/src/api/knowledge.ts`, `src/frontend/client/src/api/permission.ts`
  - **逻辑**: 使用 wrapped request；增加 Knowledge creation context/candidates 和创建可选契约；编辑复用 F048 adapter；不写 403 业务分支。
  - **验证**: T016 对应 Knowledge/F048 断言通过。
  - **依赖**: T016

- [x] **T018 Channel Client adapter 实现**
  - **文件**: `src/frontend/client/src/api/channels.ts`
  - **逻辑**: 增加 Channel creation context/candidates 和创建可选契约；保留 source/filter/subchannel/`knowledge_sync`；映射部分失败 result。
  - **验证**: T016 对应 Channel 断言通过。
  - **依赖**: T016

- [x] **T019 F048 PermissionDraft hook 测试**
  - **文件**: `src/frontend/client/src/components/permission/usePermissionDraft.test.ts`
  - **逻辑**: ADD/MOVE/REMOVE touched diff；protected/inherited/read-only 不入 draft；同主体多来源不合并；取消无写入；baseline resource/catalog/assignee version。
  - **覆盖 AC**: AC-08, AC-09, AC-13, AC-18, AC-20, AC-22, AC-23, AC-24, AC-25, AC-27, AC-33
  - **依赖**: T017, T018

- [x] **T020 F048 PermissionDraft hook 实现**
  - **文件**: `src/frontend/client/src/components/permission/usePermissionDraft.ts`
  - **逻辑**: 保留 2.6 hook 对页面的交互 API，内部改为 F048 modelKey/assignee/source/version；只存组件内存，不新增 Recoil/localStorage。
  - **验证**: T019 全部通过。
  - **依赖**: T019

- [ ] **T021 权限草稿面板/选择器测试**
  - **文件**: `src/frontend/client/src/components/permission/PermissionDraftPanel.test.tsx`, `src/frontend/client/src/components/permission/PermissionDraftPickerDialog.test.tsx`
  - **逻辑**: 保留 2.6 布局/文案/选择流；模型、主体、多来源、protected 显示；部门懒加载/搜索；无 manage 不请求敏感数据。
  - **覆盖 AC**: AC-06, AC-08, AC-09, AC-12, AC-13, AC-18, AC-24, AC-25
  - **依赖**: T020

- [ ] **T022 权限草稿面板/选择器适配**
  - **文件**: `src/frontend/client/src/components/permission/PermissionDraftPanel.tsx`, `src/frontend/client/src/components/permission/PermissionDraftPickerDialog.tsx`
  - **逻辑**: 保留 2.6 JSX/样式/移动交互；将 relation/modelId 输入改为 F048 model/subject；候选使用可注入 create/edit adapter。
  - **验证**: T021 全部通过。
  - **依赖**: T021

- [ ] **T023 统一设置交互原语适配**
  - **文件**: `src/frontend/client/src/components/permission/UnifiedPermissionControls.tsx`, `src/frontend/client/src/components/permission/PermissionLevelMenu.tsx`
  - **逻辑**: 保留 2.6 访问范围行、章节标题、固定 footer 和模型菜单交互；不显示 ModeHeader；遵守语义 token/无 blur。
  - **覆盖 AC**: AC-05, AC-06, AC-26, AC-27
  - **依赖**: T022

---

## Wave 5：Knowledge 完整页

- [ ] **T024 Knowledge 页面/表单测试**
  - **文件**: `src/frontend/client/src/pages/knowledge/SpaceSettings/KnowledgeSpaceSettingsPage.test.tsx`, `src/frontend/client/src/pages/knowledge/SpaceSettings/useKnowledgeSpaceSettingsForm.test.ts`
  - **逻辑**: create/edit；自动标签库/自定义；edit 与 manage 区域隔离；同 payload 立即重试；进设置页后 F048 mutation；private；失权/冲突；390px。
  - **覆盖 AC**: AC-01, AC-03, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-13, AC-14, AC-16, AC-17, AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-24, AC-25, AC-26, AC-27, AC-28, AC-29, AC-31, AC-33, AC-34
  - **依赖**: T023

- [ ] **T025 Knowledge 完整页与表单适配**
  - **文件**: `src/frontend/client/src/pages/knowledge/SpaceSettings/KnowledgeSpaceSettingsPage.tsx`, `src/frontend/client/src/pages/knowledge/SpaceSettings/useKnowledgeSpaceSettingsForm.ts`
  - **逻辑**: 保留 2.6 完整页 UI；保留自动标签全部业务字段；创建走 prospective + initial grants，编辑业务保存后 reload F048 再 mutate；部分成功真实反馈。
  - **验证**: T024 全部通过。
  - **依赖**: T024

- [ ] **T026 Knowledge 路由与旧独立入口收敛测试**
  - **文件**: `src/frontend/client/src/pages/unifiedPermissionEntryRoutes.test.tsx`
  - **逻辑**: 空间/频道 create/settings 路由；列表/详情跳转；无 edit 不显示；直达失权；两类资源的旧独立权限弹窗入口消失。
  - **覆盖 AC**: AC-03, AC-04, AC-05, AC-10, AC-11
  - **依赖**: T025

- [ ] **T027 Knowledge 路由与菜单收敛**
  - **文件**: `src/frontend/client/src/routes/index.tsx`, `src/frontend/client/src/pages/knowledge/index.tsx`
  - **逻辑**: 注册完整页路由，将创建/设置操作指向新页，移除知识空间独立权限入口；其他菜单能力不变。
  - **验证**: T026 对应断言通过。
  - **依赖**: T026

---

## Wave 6：Channel 完整页

- [ ] **T028 Channel 表单 hook 测试**
  - **文件**: `src/frontend/client/src/pages/Subscription/ChannelSettings/useChannelSettingsForm.test.ts`
  - **逻辑**: source/filter/subchannel/knowledge sync 不丢；创建/编辑 F048 草稿；业务先保存 + reload + mutate；private/失权/部分成功/重试。
  - **覆盖 AC**: AC-02, AC-04, AC-07, AC-08, AC-09, AC-11, AC-13, AC-14, AC-16, AC-17, AC-19, AC-20, AC-21, AC-22, AC-23, AC-25, AC-26, AC-28, AC-29, AC-32, AC-33
  - **依赖**: T023

- [ ] **T029 Channel 表单 hook 适配**
  - **文件**: `src/frontend/client/src/pages/Subscription/ChannelSettings/useChannelSettingsForm.ts`
  - **逻辑**: 保留 2.6 表单对页面的 API；删除 relation/permission_ids/authorizeChannel 逻辑；改接 prospective/F048 draft；保留 `knowledge_sync` 和业务可见性。
  - **验证**: T028 全部通过。
  - **依赖**: T028

- [ ] **T030 Channel 页面与抓取队列测试**
  - **文件**: `src/frontend/client/src/pages/Subscription/ChannelSettings/ChannelSettingsPage.test.tsx`, `src/frontend/client/src/pages/Subscription/hooks/useCrawlQueue.test.ts`
  - **逻辑**: 保留 2.6 双栏/390px 布局；抓取排队/取消/失败/预览/进行中禁提交；知识同步；manage 区隔离；protected/多来源。
  - **覆盖 AC**: AC-02, AC-04, AC-05, AC-06, AC-08, AC-09, AC-10, AC-18, AC-24, AC-25, AC-27, AC-32, AC-34
  - **依赖**: T029

- [ ] **T031 Channel 完整页与业务区适配**
  - **文件**: `src/frontend/client/src/pages/Subscription/ChannelSettings/ChannelSettingsPage.tsx`, `src/frontend/client/src/pages/Subscription/ChannelSettings/ChannelBusinessSettings.tsx`
  - **逻辑**: 保留 2.6 JSX/布局/操作区；保留抓取队列和知识同步；权限区改接 F048 draft，无 manage 完全不渲染。
  - **验证**: T030 全部通过。
  - **依赖**: T030

- [ ] **T032 Channel 路由与旧独立入口收敛**
  - **文件**: `src/frontend/client/src/pages/Subscription/index.tsx`, `src/frontend/client/src/pages/Subscription/ArticleList/ChannelActionsMenu.tsx`
  - **逻辑**: create/settings 指向完整页；移除 ChannelPermissionDialog/ShareDialog 的独立成员权限入口；保留置顶/退出/删除/解散能力。
  - **覆盖 AC**: AC-04, AC-05, AC-10
  - **依赖**: T031

---

## Wave 7：i18n、E2E 与总门禁

- [ ] **T033 Client i18n 中英文**
  - **文件**: `src/frontend/client/src/locales/zh-Hans/translation.json`, `src/frontend/client/src/locales/en/translation.json`
  - **逻辑**: 补齐统一设置、F048 模型/来源/protected、部分成功/重试文案；保留 2.6 产品文案，不新增硬编码中文。
  - **覆盖 AC**: AC-05, AC-06, AC-09, AC-16, AC-17, AC-23, AC-24
  - **依赖**: T027, T032

- [ ] **T034 Client i18n 日文与 parity**
  - **文件**: `src/frontend/client/src/locales/ja/translation.json`
  - **逻辑**: 对齐 T033 全部 key；运行 `pnpm check-i18n`，不手改 api_errors 生成物。
  - **覆盖 AC**: AC-05, AC-06, AC-09, AC-16, AC-17, AC-23, AC-24
  - **依赖**: T033

- [ ] **T035 Knowledge 统一设置 API E2E**
  - **文件**: `src/backend/test/e2e/test_e2e_f050_knowledge_permission_settings.py`
  - **逻辑**: 真实 API 覆盖空间创建、user/department/group、owner、部分失败/同键重试、edit/manage 分离、失权、并发、private、多来源、跨租户、旧 payload 和自动标签。
  - **覆盖 AC**: AC-01, AC-03, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-24, AC-25, AC-26, AC-27, AC-28, AC-29, AC-30, AC-31, AC-33, AC-34
  - **依赖**: T015, T034

- [ ] **T036 Channel 统一设置 API E2E**
  - **文件**: `src/backend/test/e2e/test_e2e_f050_channel_permission_settings.py`
  - **逻辑**: 真实 API 覆盖频道创建、user/department/group、owner、部分失败/同键重试、edit/manage 分离、失权、并发、private、多来源、跨租户、旧 payload、知识同步和外部订阅幂等。
  - **覆盖 AC**: AC-02, AC-04, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-24, AC-25, AC-26, AC-27, AC-28, AC-29, AC-30, AC-32, AC-33, AC-34
  - **依赖**: T015, T034

- [ ] **T037 页面验收与质量门禁**
  - **文件**: `features/v3.0.0-beta1/050-unified-permission-settings/e2e-report.md`
  - **逻辑**: 按 `/e2e-test` 执行 API E2E 与页面清单；对照 2.6 UI 验证桌面/390px；验证自动标签、知识同步、抓取队列；运行 backend focused pytest/ruff/arch-guard 与 frontend lint/typecheck/check-i18n。
  - **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-24, AC-25, AC-26, AC-27, AC-28, AC-29, AC-30, AC-31, AC-32, AC-33, AC-34
  - **依赖**: T035, T036

---

## 实际偏差记录

> 只记指向 Design 决策/已知坑的一行摘要。如需推翻用户已确认的 Spec/Design，先停止实现并重新确认。

- 暂无。
