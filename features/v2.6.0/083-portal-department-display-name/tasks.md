# 任务拆分 Tasks: F083 门户部门简称统一展示

## 元信息 Metadata

- Feature ID: `083-portal-department-display-name`
- Status: `implemented_manual_e2e_required`
- Related spec: `features/v2.6.0/083-portal-department-display-name/spec.md`
- Created: `2026-08-10`
- Updated: `2026-08-11`
- Repositories:
  - BiSheng: `/Users/wenruli/code/project/bisheng/bisheng`
  - 首钢门户: `/Users/wenruli/code/project/bisheng/shougang-group-knowledge-portal`

## 状态

| 阶段 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已确认 | 用户已确认规格并授权实施 |
| tasks.md | ✅ 已确认 | T001-T015 已完成；T016 为同一规格内的授权用户组织树缺陷修复 |
| 实现 | ✅ 已完成 | T001-T016 已完成 |
| verification.md | ✅ 已创建 | 自动化证据已归档，真实环境 E2E 标记 MANUAL_REQUIRED |

## 实施原则

- **先决条件**：实施前确认 F082 migration 已合入目标分支、Alembic 单 head 且测试环境存在 `department.short_name`。
- **共享规则 Test-First**：先锁定统一派生与稳定排序，再接入各业务投影。
- **模块级 Red-Green**：每个后端模块先增加可观察契约测试，再做最小实现；同一模块不拆成大量重复页面用例。
- **API 兼容**：现有正式名称字段不改值，只增量增加简称/展示字段。
- **前端兼容**：新前端按 `display_name → short_name → name` 回退，提交和 key 继续使用部门 ID。
- **历史保护**：审批快照与历史知识空间名称不更新、不回填。
- **范围保护**：不修改 Platform、组织同步、Filelib 匹配、首页硬编码积分榜、遥测和 worker 中间表。
- **跨仓库提交**：两个仓库分别保持最小 diff 和独立验证记录，不混入现有用户改动。

## 依赖图

```text
T001 → T002 shared contract
          ├─→ T003 user + PDF
          ├─→ T004 → T005 knowledge
          ├─→ T006 permission
          ├─→ T007 approval
          └─→ T008 qa_expert

T003 + T005 + T006 + T007 + T008
          └─→ T009 Client contract
                ├─→ T010 Client knowledge
                └─→ T011 Client member/approval/watermark

T003 + T005 + T008
          └─→ T012 portal BFF contract
                └─→ T013 portal UI

T010 + T011 + T013 → T014 regression → T015 E2E/evidence
```

---

## 阶段 0：实施基线与共享契约

- [x] T001 建立实施基线和部门展示规则失败测试
  - Files:
    - `src/backend/test/department/test_department_display_name.py`（新建）
    - 两个仓库的 `git status`、分支与相关版本信息（只读记录）
  - Logic:
    - 先确认 F082 model/migration/schema 存在，测试数据库 fixture 支持 `short_name`；条件不满足时停止，不为 F083 补做 F082 migration。
    - 参数化覆盖非空简称、首尾空白、`null`、空字符串、纯空白和无简称历史部门。
    - 覆盖重复简称允许，以及 `display_name → name → id` 的稳定排序契约；ID 仅用于排序 tie-break，不作为展示回退。
    - 增加一个跨投影契约 fixture，供后续 user/knowledge/permission/approval/qa_expert 用同一预期值。
  - Done when: 测试因统一派生能力尚未存在而正确失败；失败原因不是 fixture 漏列或环境错误。
  - _Requirements: REQ-001, REQ-003, REQ-009_
  - _Acceptance: AC-01, AC-02, AC-06, AC-15, AC-16, AC-18_
  - _Verification: V-UNIT-01, V-SCOPE-01_
  - _Depends: none_
  - _Boundary: tests and read-only baseline only; no production changes_

- [x] T002 实现统一部门展示投影并使共享测试转绿
  - Files:
    - `src/backend/bisheng/department/domain/services/department_display_service.py`（新建）
    - `src/backend/bisheng/department/domain/schemas/department_schema.py`（仅在共享投影 DTO 必需时修改）
  - Logic:
    - 实现 `short_name.strip() or name` 的纯派生规则、正式/简称/展示投影和稳定排序 key。
    - 不查询数据库、不写 Department、不持有缓存、不手写租户过滤。
    - 批量业务调用方负责一次取数后复用投影，禁止在 helper 内逐部门查询。
  - Done when: T001 全部通过，helper 没有业务模块依赖和副作用。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-009_
  - _Acceptance: AC-01, AC-02, AC-03, AC-06, AC-15, AC-16_
  - _Verification: V-UNIT-01_
  - _Depends: T001_
  - _Boundary: department display projection only; no API or consumer edits_

---

## 阶段 1：BiSheng 后端投影

- [x] T003 用 Test-First 扩展用户主部门与服务端 PDF 水印
  - Files:
    - `src/backend/test/user/test_user_primary_department_contract.py`（修改）
    - `src/backend/test/knowledge/pdf/test_portal_pdf_download_service.py`（修改）
    - `src/backend/bisheng/user/domain/repositories/implementations/user_repository_impl.py`（修改）
    - `src/backend/bisheng/user/domain/services/user.py`（修改）
    - `src/backend/bisheng/user/api/user.py`（修改）
    - `src/backend/bisheng/knowledge/domain/services/portal_pdf_download_service.py`（修改）
  - Logic:
    - 先增加有简称/无简称两组失败测试，再最小实现。
    - 主部门批量/单值投影同时保留正式名称并提供简称和展示名称；`/user/info` 增量返回 `department_short_name`、`department_display_name`。
    - PDF 水印直接复用同一主部门展示投影，不复制回退表达式。
    - 无主部门用户沿用现有空值行为。
  - Done when: 用户 API 正式名称未变，PDF 水印与 API 展示名称一致，目标测试通过。
  - _Requirements: REQ-001, REQ-002, REQ-006, REQ-009, REQ-010_
  - _Acceptance: AC-02, AC-03, AC-11, AC-15, AC-17_
  - _Verification: V-BE-USER-01_
  - _Depends: T002_
  - _Boundary: user primary department projection and portal PDF watermark only_

- [x] T004 建立 Knowledge 部门展示、搜索与默认名称失败测试
  - Files:
    - `src/backend/test/knowledge/test_department_display_projection.py`（新建）
    - `src/backend/test/test_department_knowledge_space_service.py`（修改）
  - Logic:
    - 覆盖创建选项部门列表、部门树、逐级路径、绑定列表、来源部门元数据和有/无简称回退。
    - 覆盖关键字按正式名称与简称命中、按展示名称稳定排序。
    - 覆盖新部门知识空间默认名称使用当前展示名；历史空间名在简称变化后保持原值。
    - 测试查询次数或 repository 调用次数，防止列表场景 N+1。
  - Done when: 测试按预期因 Knowledge 尚未返回展示字段、搜索简称或默认名称仍用正式名称而失败。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-008, REQ-009_
  - _Acceptance: AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-14, AC-15, AC-16_
  - _Verification: V-BE-KNOWLEDGE-01_
  - _Depends: T002_
  - _Boundary: knowledge tests only; no production edits_

- [x] T005 实现 Knowledge 部门展示投影与搜索
  - Files:
    - `src/backend/bisheng/knowledge/domain/schemas/knowledge_space_schema.py`（修改）
    - `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`（修改）
    - `src/backend/bisheng/knowledge/domain/services/department_knowledge_space_service.py`（修改）
    - 仅当现有查询无法批量取得简称时，修改对应 knowledge repository
  - Logic:
    - 部门选项/树返回 `name`、`short_name`、`display_name`；标量响应保留 `department_name` 并增加展示字段。
    - 路径按部门 ID 链批量生成正式路径和展示路径。
    - 有服务端 keyword 的接口匹配正式名与简称；排序使用共享稳定排序 key。
    - 来源部门元数据和绑定列表提供展示字段。
    - 仅新自动创建的部门空间默认名称使用展示名，不对已有 `Knowledge.name` 写入。
  - Done when: T004 转绿；知识权限、层级、绑定和提交 ID 回归不变，无逐行部门查询。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-008, REQ-009, REQ-010_
  - _Acceptance: AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-14, AC-15, AC-16, AC-17_
  - _Verification: V-BE-KNOWLEDGE-01_
  - _Depends: T002, T004_
  - _Boundary: knowledge response projection/search/default naming only; no historical rename_

- [x] T006 用 Test-First 扩展 Permission 成员管理部门树与展示路径
  - Files:
    - `src/backend/test/test_permission_team_space_grant_departments.py`（修改）
    - `src/backend/test/permission/test_grant_subject_user_tree.py`（修改）
    - `src/backend/bisheng/permission/api/endpoints/resource_permission.py`（修改）
    - `src/backend/bisheng/permission/domain/services/grant_subject_user_service.py`（修改）
  - Logic:
    - 先覆盖部门节点正式/简称/展示字段、展示排序和成员正式/展示路径并存，再实现。
    - 路径每一级独立应用共享规则；旧 `subject_department_paths` 不改值，新增 `subject_department_display_paths`。
    - 部门节点搜索能力若在后端执行则同时匹配两种名称；若仅由 Client 本地执行，后端仍完整返回字段。
    - 断言授权 relation、角色、成员范围和部门 ID 完全不变，并保护批量查询。
  - Done when: 两个目标测试文件通过，PermissionService/ReBAC 写入路径无行为变化。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-009_
  - _Acceptance: AC-02, AC-03, AC-04, AC-05, AC-06, AC-08, AC-15, AC-16_
  - _Verification: V-BE-PERM-01_
  - _Depends: T002_
  - _Boundary: permission read projections only; no relation or authorization semantics changes_

- [x] T007 用 Test-First 扩展 Approval 实时展示与快照回退
  - Files:
    - `src/backend/test/approval/test_approval_center_query_service.py`（修改）
    - `src/backend/test/approval/test_department_file_view_approval.py`（修改）
    - `src/backend/bisheng/approval/domain/services/approval_center_service.py`（修改）
    - `src/backend/bisheng/approval/domain/services/department_file_view_approval_service.py`（仅在响应映射必要时修改）
    - 对应 approval schema（仅增量字段）
  - Logic:
    - 先覆盖有效部门当前简称、简称更新后刷新、部门失效回退快照、无 ID 快照和跨租户不可见回退。
    - 证明审批创建时既有 `department_name` 快照仍保存正式名称，查询不会回写快照。
    - 列表与详情按当前租户批量解析部门，增加 `applicant_department_display_name` / `department_display_name` 等明确字段。
    - 不改变 ApprovalInstance/Task 状态、权限或分页契约。
  - Done when: 实时展示和失效回退测试通过，快照原值及跨租户隔离断言通过，无 N+1。
  - _Requirements: REQ-001, REQ-002, REQ-007, REQ-009, REQ-010_
  - _Acceptance: AC-02, AC-03, AC-12, AC-13, AC-15, AC-17_
  - _Verification: V-BE-APPROVAL-01_
  - _Depends: T002_
  - _Boundary: approval query/read projection and response schema only; no snapshot migration or state changes_

- [x] T008 用 Test-First 扩展 QA Expert 部门投影、搜索与排序
  - Files:
    - `src/backend/test/qa_expert/test_expert_management_list.py`（修改）
    - `src/backend/bisheng/qa_expert/domain/services.py`（修改）
    - 对应 qa_expert schema（仅在现有 schema 不允许新增字段时修改）
  - Logic:
    - 覆盖专家列表/详情和筛选部门选项的正式名称、简称、展示名称。
    - 既有 `depart_ment` 保持正式名称；新增 `department_short_name`、`department_display_name`。
    - 搜索正式名与简称，部门展示排序使用共享稳定规则；筛选请求和结果仍基于部门 ID。
    - 批量加载专家部门，禁止逐专家查询。
  - Done when: 专家 API 兼容字段、双名称搜索、展示排序和 ID 筛选测试通过。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-005, REQ-009, REQ-010_
  - _Acceptance: AC-02, AC-03, AC-05, AC-06, AC-09, AC-15, AC-16, AC-17_
  - _Verification: V-BE-EXPERT-01_
  - _Depends: T002_
  - _Boundary: qa_expert read/filter projections only; no expert write semantics changes_

---

## 阶段 2：BiSheng Client 知识门户

- [x] T009 建立 Client 部门展示兼容契约与 API 类型
  - Files:
    - `src/frontend/client/src/api/knowledge.ts`（修改）
    - `src/frontend/client/src/api/permission.ts`（修改）
    - `src/frontend/client/src/api/approval.ts`（修改）
    - `src/frontend/client/src/utils/departmentDisplayName.ts`（新建）
    - `src/frontend/client/src/utils/departmentDisplayName.test.ts`（新建）
    - 相关 API contract tests（修改）
  - Logic:
    - 类型增量表达正式、简称、展示名称，以及 `subject_department_paths` / `subject_department_display_paths` 等成对路径字段。
    - 兼容函数按 `display_name → trimmed short_name → name` 读取；缺失新增字段时可靠回退。
    - 搜索词集合包含正式名、简称和展示名；去重后沿用现有大小写/contains 规则。
    - 不在前端合成权限、租户或审批历史语义。
  - Done when: 有/无新字段、空白简称和旧响应的单元测试通过，TypeScript 不使用不安全强转掩盖字段缺失。
  - _Requirements: REQ-002, REQ-003, REQ-010_
  - _Acceptance: AC-03, AC-04, AC-05, AC-15, AC-17_
  - _Verification: V-CLIENT-01_
  - _Depends: T003, T005, T006, T007, T008_
  - _Boundary: Client API types and compatibility helper only_

- [x] T010 实现 Client 知识空间与来源部门展示
  - Files:
    - `src/frontend/client/src/pages/knowledge/CreateKnowledgeSpaceDrawer.tsx`（修改）
    - `src/frontend/client/src/pages/knowledge/CreateKnowledgeSpaceDrawer.test.tsx`（修改）
    - `src/frontend/client/src/pages/knowledge/portal/components/PortalInfoDrawer.tsx`（修改）
    - `src/frontend/client/src/pages/knowledge/portal/components/PortalInfoDrawer.test.tsx`（修改）
    - 必要的 portal knowledge option/tree 组件及其既有定向测试
  - Logic:
    - 部门选择器、选中项、知识空间部门信息和来源部门使用兼容 helper。
    - 本地搜索同时匹配正式名与简称，列表按展示名称稳定排序。
    - 保存、筛选、React key 继续使用部门 ID；不把展示名写入提交字段。
    - 旧后端响应只含正式名称时仍正常展示。
  - Done when: AC-07 的有简称、无简称、旧响应和 ID payload 用例通过，既有知识空间创建/信息抽屉行为回归通过。
  - _Requirements: REQ-003, REQ-004, REQ-009, REQ-010_
  - _Acceptance: AC-05, AC-06, AC-07, AC-15, AC-16, AC-17_
  - _Verification: V-CLIENT-01_
  - _Depends: T009_
  - _Boundary: Client knowledge department rendering/search only_

- [x] T011 实现 Client 成员管理、审批与预览水印展示
  - Files:
    - `src/frontend/client/src/components/permission/SubjectSearchDepartment.tsx`（修改）
    - `src/frontend/client/src/components/permission/PermissionListTab.tsx`（修改）
    - `src/frontend/client/src/components/permission/PermissionGrantTab.tsx`（必要时修改）
    - `src/frontend/client/src/pages/knowledge/SpaceDetail/KnowledgeSpaceShareDialog.tsx`（必要时修改）
    - `src/frontend/client/src/components/approval/ApprovalCenterDialog.tsx`（修改）
    - `src/frontend/client/src/pages/knowledge/FilePreview/KnowledgePreviewWatermark.tsx`（修改）
    - 上述组件既有定向测试（修改）
  - Logic:
    - 部门树和路径使用展示字段，本地搜索双名称，提交部门 ID 不变。
    - 成员列表优先展示 `subject_department_display_paths`，旧响应回退 `subject_department_paths`。
    - 审批列表/详情使用实时展示字段，无字段时回退历史正式名称。
    - Client 水印使用用户 `department_display_name`，无新字段时回退 `department_name`。
    - 测试只按成员管理、审批、水印三个独立结果分组，不为每个 JSX 位置复制用例。
  - Done when: 成员授权结果不变，审批快照回退可见，水印有/无简称测试和目标 Vitest 通过。
  - _Requirements: REQ-003, REQ-004, REQ-006, REQ-007, REQ-009, REQ-010_
  - _Acceptance: AC-04, AC-05, AC-08, AC-11, AC-12, AC-13, AC-15, AC-16, AC-17_
  - _Verification: V-CLIENT-01_
  - _Depends: T009_
  - _Boundary: Client member management, approval display and preview watermark only_

---

## 阶段 3：独立首钢门户 BFF 与前端

- [x] T012 用 Test-First 扩展门户 BFF 用户、专家与后台部门契约
  - Repository: `/Users/wenruli/code/project/bisheng/shougang-group-knowledge-portal`
  - Files:
    - `backend/app/schemas/auth.py`（修改）
    - `backend/app/services/portal_auth_service.py`（修改）
    - `backend/app/services/bisheng_runtime_service.py`（必要时修改）
    - `backend/app/api/routes/expert_qa.py`（仅当代理会丢弃新增字段时修改）
    - `backend/app/api/routes/admin_config.py`（仅当代理会丢弃新增字段时修改）
    - `backend/tests/test_portal_bisheng_user_lookup.py`（修改）
    - `backend/tests/test_expert_qa_api.py`（修改）
    - `backend/tests/test_admin_config_api.py`（修改）
  - Logic:
    - 先证明现有 schema/映射是否丢弃新增字段，再做最小修改；透明 JSON 代理若自然保留则不改生产文件。
    - 用户会话保留 `department_name`，增加 `department_short_name`、`department_display_name`。
    - 专家和后台部门代理完整透传正式/简称/展示字段，不把正式名称字段重写为简称。
    - 旧 BiSheng 后端响应仍能构造门户 DTO，展示字段回退正式名称。
  - Done when: 三组 BFF 定向测试通过，正式字段兼容、旧后端回退和新增字段透传均有证据。
  - _Requirements: REQ-002, REQ-005, REQ-006, REQ-009, REQ-010_
  - _Acceptance: AC-03, AC-09, AC-10, AC-11, AC-15, AC-17_
  - _Verification: V-PORTAL-01_
  - _Depends: T003, T005, T008_
  - _Boundary: portal BFF response mapping only; no auth or permission policy changes_

- [x] T013 实现独立门户专家、后台与浏览器水印展示
  - Repository: `/Users/wenruli/code/project/bisheng/shougang-group-knowledge-portal`
  - Files:
    - `frontend/src/api/auth.ts`（修改）
    - `frontend/src/api/expertQa.ts`（修改）
    - `frontend/src/api/adminConfig.ts`（修改）
    - `frontend/src/utils/deptKnowledgeBinding.ts`（修改）
    - `frontend/src/utils/previewWatermark.ts`（修改）
    - `frontend/src/utils/departmentDisplayName.ts`（新建）
    - `frontend/src/pages/ExpertQAPage.tsx`（修改）
    - `frontend/src/pages/ExpertQADetailPage.tsx`（修改）
    - `frontend/src/pages/ExpertManagePage.tsx`（修改）
    - `frontend/src/components/ExpertInvitePicker.tsx`（修改）
    - `frontend/src/pages/AdminPage.tsx`（修改）
    - `frontend/tests/expertManagement.test.ts`、`deptKnowledgeBinding.test.ts`、`previewWatermark.test.ts` 及必要的聚焦测试（修改/新建）
  - Logic:
    - 先扩展类型和兼容 helper，再把专家卡片/详情/邀请/管理、部门筛选、后台绑定列表/树/确认文案切换到展示名。
    - 前端本地搜索匹配正式名与简称，排序使用展示名；筛选与绑定 payload 继续使用 ID。
    - 浏览器预览水印使用用户展示部门，旧会话字段回退正式名称。
    - 不修改 `HomePage.tsx` 的硬编码积分榜，不修改内容 API 中未实际渲染的 dormant 字段。
  - Done when: Node 定向测试、`npm run build` 和相关 lint/typecheck 通过；AC-09～AC-11、AC-17、AC-18 有证据。
  - _Requirements: REQ-003, REQ-005, REQ-006, REQ-009, REQ-010_
  - _Acceptance: AC-05, AC-06, AC-09, AC-10, AC-11, AC-15, AC-16, AC-17, AC-18_
  - _Verification: V-PORTAL-01, V-SCOPE-01_
  - _Depends: T012_
  - _Boundary: named portal expert/admin/watermark surfaces only; HomePage hardcoded data excluded_

---

## 阶段 4：回归、集成与证据

- [x] T014 执行两仓定向回归和范围审查
  - Files: 不修改生产代码；失败时只回到对应任务做最小修复
  - Commands/Checks:
    - BiSheng backend：运行 T001～T008 涉及的 department、user、knowledge、permission、approval、qa_expert、PDF 定向 pytest。
    - BiSheng backend：对改动 Python 文件执行 `uv run ruff format --check`、`uv run ruff check` 和必要的 `compileall`。
    - BiSheng Client：运行 T009～T011 的定向 Vitest、typecheck/build 和项目已有架构边界检查。
    - 独立门户 backend：运行 T012 涉及的 pytest。
    - 独立门户 frontend：运行 T013 定向 Node tests、`npm run build`，仅对改动范围执行可行的 lint。
    - 两仓分别执行 `git diff --check`。
    - 代码搜索确认旧正式字段未被改写、首页硬编码积分榜/Platform/同步/Filelib/遥测无生产 diff。
  - Done when: 所有可运行的 V1/V2 证据在同一代码状态下通过；失败、跳过和环境限制均已记录，不重复运行无关全量 suite。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008, REQ-009, REQ-010_
  - _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18_
  - _Verification: V-UNIT-01, V-BE-USER-01, V-BE-KNOWLEDGE-01, V-BE-PERM-01, V-BE-APPROVAL-01, V-BE-EXPERT-01, V-CLIENT-01, V-PORTAL-01, V-SCOPE-01_
  - _Depends: T010, T011, T013_
  - _Boundary: verification and fixes strictly attributable to F083 only_

- [x] T015 完成最小 E2E、发布兼容检查与 verification 归档
  - Files:
    - `features/v2.6.0/083-portal-department-display-name/verification.md`（新建）
    - `features/v2.6.0/083-portal-department-display-name/tasks.md`（更新状态与偏差）
    - `features/v2.6.0/README.md`（更新最终状态）
  - Logic:
    - 在可用环境验证一组有简称部门和一组无简称部门：专家/后台部门选择、知识空间成员管理、审批、浏览器预览水印和 PDF 水印至少覆盖一条跨层主路径。
    - 验证新后端 + 旧前端、旧字段响应 + 新前端两个兼容方向；不能真实降级时用 contract fixture 代替并明确证据边界。
    - 确认发布顺序为 F082 migration → F083 backend → Client → portal BFF/frontend，回退顺序与 spec 一致。
    - 记录每条命令、结果、代码状态、未运行项、人工步骤、已知风险和实施偏差；环境不可用的浏览器/真实 PDF 证据标记 `MANUAL_REQUIRED`。
  - Done when: `verification.md` 能把全部 AC 映射到实际证据或明确待人工项；未验证项不标记完成。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008, REQ-009, REQ-010_
  - _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18_
  - _Verification: V-E2E-01 and all prior verification IDs_
  - _Depends: T014_
  - _Boundary: E2E/compatibility evidence and SDD docs only; no deployment or live data mutation_

- [x] T016 修复知识类资源授权“用户”组织树未使用部门简称
  - Files:
    - `src/frontend/client/src/components/permission/SubjectSearchUserTree.test.tsx`（修改）
    - `src/frontend/client/src/components/permission/SubjectSearchUserTree.tsx`（修改）
    - `features/v2.6.0/083-portal-department-display-name/verification.md`（更新）
  - Logic:
    - 先增加包含正式名、简称和展示名的组件回归 fixture，确认修复前错误地显示正式名称。
    - 节点可见文本与 `title` 复用现有 `resolveDepartmentDisplayName`，缺失新增字段时回退正式名称。
    - 知识空间、知识库、文件夹和知识文件继续通过 `KNOWLEDGE_RESOURCE_TYPES` 共用该组件，不复制页面级实现。
    - 不修改部门/用户 ID、树加载范围、授权 relation、选择状态或提交 payload。
  - Done when: 缺陷回归用例先红后绿，完整 `SubjectSearchUserTree` 测试文件和 Client 生产构建通过。
  - _Requirements: REQ-003, REQ-004, REQ-009, REQ-010_
  - _Acceptance: AC-08, AC-15, AC-17, AC-19_
  - _Verification: V-CLIENT-01, V-SCOPE-01_
  - _Depends: T009, T011_
  - _Boundary: knowledge-resource permission user-tree department labels only_

---

## 覆盖矩阵 Coverage Matrix

| Requirement | Acceptance Criteria | Tasks | Verification |
|-------------|---------------------|-------|--------------|
| REQ-001 | AC-01, AC-02 | T001, T002, T003, T005, T006, T007, T008, T014, T015 | V-UNIT-01 及各后端模块验证 |
| REQ-002 | AC-03, AC-04 | T002, T003, T005, T006, T007, T008, T009, T012, T014, T015 | V-BE-*, V-CLIENT-01, V-PORTAL-01 |
| REQ-003 | AC-05, AC-06, AC-16 | T001, T002, T004, T005, T006, T008, T009, T010, T011, T013, T014, T015, T016 | V-UNIT-01, V-BE-*, V-CLIENT-01, V-PORTAL-01 |
| REQ-004 | AC-07, AC-08, AC-19 | T004, T005, T006, T010, T011, T014, T015, T016 | V-BE-KNOWLEDGE-01, V-BE-PERM-01, V-CLIENT-01, V-E2E-01 |
| REQ-005 | AC-09, AC-10 | T008, T012, T013, T014, T015 | V-BE-EXPERT-01, V-BE-KNOWLEDGE-01, V-PORTAL-01, V-E2E-01 |
| REQ-006 | AC-11, AC-15 | T003, T011, T012, T013, T014, T015 | V-BE-USER-01, V-CLIENT-01, V-PORTAL-01, V-E2E-01 |
| REQ-007 | AC-12, AC-13 | T007, T009, T011, T014, T015 | V-BE-APPROVAL-01, V-CLIENT-01, V-E2E-01 |
| REQ-008 | AC-14 | T004, T005, T014, T015 | V-BE-KNOWLEDGE-01 |
| REQ-009 | AC-15, AC-16, AC-18 | T001, T002, T003, T005, T006, T007, T008, T010, T011, T012, T013, T014, T015, T016 | V-SCOPE-01 及相关回归 |
| REQ-010 | AC-17 | T003, T005, T007, T008, T009, T010, T011, T012, T013, T014, T015, T016 | V-CLIENT-01, V-PORTAL-01, V-E2E-01 |

## 任务质量门 Task Quality Gate

- [x] Every task references at least one requirement ID.
- [x] Every behavioral task references acceptance criteria.
- [x] Every acceptance criterion is covered by at least one task and verification entry.
- [x] Every task has an observable done condition.
- [x] Dependencies and cross-repository ordering are explicit.
- [x] Boundary annotations prevent unrelated code edits.
- [x] Shared and module-level tests precede or accompany behavior implementation.
- [x] Existing API field meanings and historical data are explicitly protected.
- [x] F082 database readiness is a hard prerequisite, not silently absorbed into F083.
- [x] Live deployment and data mutation are excluded from implementation tasks.

## 规格阶段记录

- 规格生成时，BiSheng 工作区已有与 F083 无关的 `src/backend/bisheng/shougang_portal_config/domain/services/portal_config_service.py` 修改；实施不得覆盖或混入该改动。
- 首钢门户工作区已有未跟踪 `.coaligne/` 与 `.coaligneignore`；实施不得删除或纳入 F083。
- 首页积分榜部门字段为硬编码文本且无稳定部门 ID，按用户确认排除。
- “成员管理”是本期范围；先前“成功管理”为输入笔误，不形成独立场景。
- 规格评审通过前不得开始 T001 以后的实现。
