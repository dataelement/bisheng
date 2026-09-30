# Tasks: F058 系统管理员调整部门知识库所属部门

**关联规格**: [spec.md](./spec.md)  
**版本**: v2.6.0  
**Status**: Implemented — 自动化验证完成，外部环境验证待执行  
**Created**: 2026-07-16  
**Updated**: 2026-07-16

---

## 1. 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| `spec.md` | ✅ 已确认 | 用户于 2026-07-16 确认。 |
| `tasks.md` | ✅ 已确认 | 用户于 2026-07-16 确认任务。 |
| 实现 | ✅ 已完成 | 10 / 10 完成。 |
| 验证 | ✅ 自动化完成 | MySQL/DM8、真实 OpenFGA 与浏览器人工冒烟待外部环境执行。 |

---

## 2. 开发与范围规则

- 后端采用 Test-First：先提交能够复现缺失行为的失败测试，再实现最小代码使其通过。
- 前端采用 Test-First/Test-Alongside：先补充组件和 API 契约测试，再修改交互。
- 不修改 `space_level`，不新增或删除数据库约束，不创建 Alembic migration。
- 不修改独立仓库 `shougang-group-knowledge-portal`。
- 不修改当前工作区已有未提交变更涉及的 `knowledge_space_service.py` 和 `knowledge_space_schema.py`；如实现时发现不可避免，必须停止并先更新 spec。
- 不使用 `git reset`、`git checkout --`、自动 stash 或覆盖用户现有改动。
- 任一实现任务发现范围或设计变化时，先更新 `spec.md` 并重新评审，不得直接扩大实现。

---

## 3. Tasks

### Phase A：工作区与测试基线

- [x] **T001：建立隔离开发边界并记录基线**  
  _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006_  
  _Acceptance: AC-01..AC-11_  
  _Verification: V-001_  
  _Depends: 无_  
  _Boundary: 只检查 Git 状态、现有修改和测试命令；不得切换、重置、stash 或覆盖当前 `feat/2.6.0/057-domain-bindable-spaces-perf` 工作区。_  
  **交付物**：确认 F058 的实现分支/工作树策略，记录当前脏文件清单，证明后续修改不覆盖用户已有变更。若无法建立安全边界，停止实现并报告阻塞。

- [x] **T002：增加后端失败测试**  
  _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005_  
  _Acceptance: AC-02..AC-10_  
  _Verification: V-002_  
  _Depends: T001_  
  _Boundary: 新建 `src/backend/test/knowledge/test_department_space_reassignment.py`；只使用 fixture/mock 或测试事务，不写生产数据库和真实 OpenFGA。_  
  **测试场景**：
  - `admin` 调整成功，binding 与 scope 同步变更且 `space_level=department`。
  - 非 `admin` 被拒绝。
  - 源知识库不存在、不是部门知识库或 scope 不一致时拒绝。
  - 目标部门不存在、已归档、跨租户或已绑定时拒绝。
  - 相同部门幂等，无重复权限操作。
  - 唯一约束并发冲突转换为 `18002`。
  - `approval_enabled`、`sensitive_check_enabled` 和知识库业务字段保持不变。
  - 手工成员保留，部门来源成员删除/恢复/新增规则正确。
  - OpenFGA 批次包含旧部门撤销与新部门授予；失败时保留 `FailedTuple` 语义。
  **完成条件**：测试在实现前因缺少接口/服务/Repository 而失败，失败原因与本特性一致。

### Phase B：后端数据库事务与领域逻辑

- [x] **T003：实现部门归属事务 Repository**  
  _Requirements: REQ-002, REQ-003, REQ-005_  
  _Acceptance: AC-03, AC-04, AC-05, AC-06, AC-08, AC-10_  
  _Verification: V-002, V-003_  
  _Depends: T002_  
  _Boundary: 只新增 `department_space_assignment_repository` interface/implementation 及必要导出；不得在 Service 中直接写 ORM 查询，不得增加 legacy DAO 入口。_  
  **文件**：
  - `src/backend/bisheng/knowledge/domain/repositories/interfaces/department_space_assignment_repository.py`
  - `src/backend/bisheng/knowledge/domain/repositories/implementations/department_space_assignment_repository_impl.py`
  **逻辑**：
  - 使用注入的 `AsyncSession` 和单一事务读取/锁定源 binding、scope 与目标绑定。
  - 校验目标一对一状态，并更新 binding 与 scope。
  - 在同一事务处理 `membership_source=department_admin` 记录；纯手工成员不修改，临时提升成员恢复原角色。
  - 捕获 MySQL/DM8 唯一冲突并转换为稳定领域冲突结果，禁止暴露数据库异常细节。
  - 不更新审批、安全检测、知识库内容或标签字段。

- [x] **T004：实现部门调整领域服务与权限操作构建**  
  _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005_  
  _Acceptance: AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10_  
  _Verification: V-002, V-003_  
  _Depends: T003_  
  _Boundary: 修改 `department_knowledge_space_service.py`；复用 `PermissionService`、部门服务和 T003 Repository，不直接访问 OpenFGA SDK。_  
  **逻辑**：
  - 以 `login_user.is_global_super` 做后端权威鉴权，避免将子租户管理员误判为系统管理员。
  - 校验源空间及 scope 均为部门层级，目标部门有效且属于当前租户。
  - 相同部门返回幂等成功，不写数据库或 OpenFGA。
  - 读取旧/新部门管理员，形成部门来源成员调整输入。
  - 数据库事务提交后，使用一个 crash-safe 批次撤销旧部门 `viewer`/旧自动管理员 `manager`，并授予新部门 `viewer`/新管理员 `manager`。
  - OpenFGA 失败时保留 `FailedTuple` 并返回可观察状态；不得记录“权限同步成功”。
  - 记录包含 `space_id`、旧/新部门、操作者及权限同步结果的审计日志。

- [x] **T005：增加专用 API 契约和依赖注入**  
  _Requirements: REQ-001, REQ-002, REQ-006_  
  _Acceptance: AC-02, AC-03, AC-04, AC-05, AC-06_  
  _Verification: V-002, V-003_  
  _Depends: T004_  
  _Boundary: 修改 `knowledge_space.py` 与 `knowledge/api/dependencies.py`，新增独立 request schema 文件；不得扩展通用 `KnowledgeSpaceUpdateReq`。_  
  **文件**：
  - 新增 `src/backend/bisheng/knowledge/domain/schemas/department_space_assignment_schema.py`
  - 修改 `src/backend/bisheng/knowledge/api/endpoints/knowledge_space.py`
  - 修改 `src/backend/bisheng/knowledge/api/dependencies.py`
  **API**：`PUT /api/v1/knowledge/space/department-binding/{space_id}`，请求体 `{"department_id": number}`。  
  **响应**：返回 `space_id`、`space_level=department`、新 `department_id` 和 `department_name`。  
  **错误**：目标冲突复用 `DepartmentKnowledgeSpaceExistsError(18002)`，消息固定为“目标部门已绑定知识库”；非 admin 复用现有 `UnAuthorizedError`。

- [x] **T006：完成后端定向回归与静态检查**  
  _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005_  
  _Acceptance: AC-02..AC-10_  
  _Verification: V-002, V-003, V-004_  
  _Depends: T005_  
  _Boundary: 只格式化/检查 F058 后端文件并运行知识库、部门管理员同步、审批设置相关定向测试；不得批量格式化仓库。_  
  **完成条件**：F058 后端测试从红转绿；现有部门知识库创建、绑定、上传审批及权限测试无新增失败。

### Phase C：Client 前端交互

- [x] **T007：增加 Client 失败测试**  
  _Requirements: REQ-001, REQ-006_  
  _Acceptance: AC-01, AC-02, AC-04, AC-11_  
  _Verification: V-005_  
  _Depends: T001_  
  _Boundary: 只修改 `CreateKnowledgeSpaceDrawer.test.tsx`、`api/knowledge.test.ts`，并按需新增知识库编辑编排测试；不得先修改生产组件。_  
  **测试场景**：
  - 系统管理员编辑部门知识库时显示部门选择器并预选当前部门。
  - 非系统管理员仍显示只读“部门知识库 - 部门名”。
  - 创建模式行为不变。
  - 目标未变化时不发送部门调整请求。
  - 目标变化时发送正确的 PUT 路径和 `department_id`。
  - `18002` 显示“目标部门已绑定知识库”并保持抽屉打开。
  - 成功后更新 active space 并失效知识库相关查询。
  **完成条件**：测试因缺少管理员编辑能力和 API helper 而失败，失败原因与本特性一致。

- [x] **T008：实现 Client API 与编辑抽屉部门选择器**  
  _Requirements: REQ-001, REQ-006_  
  _Acceptance: AC-01, AC-02, AC-04_  
  _Verification: V-005, V-006_  
  _Depends: T005, T007_  
  _Boundary: 修改 `src/frontend/client/src/api/knowledge.ts` 与 `CreateKnowledgeSpaceDrawer.tsx`；不得改变创建模式、层级枚举或其他角色权限。_  
  **逻辑**：
  - 新增 `reassignDepartmentSpaceApi(spaceId, departmentId)`。
  - Drawer 接收明确的 `canReassignDepartment` 权限输入，不自行推断知识库权限。
  - 编辑部门知识库且为系统管理员时复用部门单选组件，默认选中 `editingSpace.departmentId/ownerId`。
  - 非管理员保持只读层级文本。
  - 部门列表失败或尚未加载完成时阻止部门变更提交并显示明确提示。
  - 提交数据包含变更后的 `departmentId`，不修改 `spaceLevel`。

- [x] **T009：接入保存编排、错误提示与缓存刷新**  
  _Requirements: REQ-006_  
  _Acceptance: AC-04, AC-11_  
  _Verification: V-005, V-006_  
  _Depends: T008_  
  _Boundary: 修改 `src/frontend/client/src/pages/knowledge/index.tsx`，必要时补充现有 i18n 文件；不得修改独立门户仓库或全局错误拦截器。_  
  **逻辑**：
  - 使用 `/user/info` 返回的 `user.is_global_super` 计算系统管理员能力并传入 Drawer。
  - 仅部门 ID 实际变化时调用专用调整接口。
  - 目标冲突时展示固定业务提示，保留抽屉输入。
  - 成功后以响应数据更新 active/editing space，并失效 `knowledgeSpaces`、详情和部门知识库列表查询。
  - 普通知识库字段继续走现有更新逻辑，不改变其 API 契约。

### Phase D：综合验证与交付

- [x] **T010：执行综合验证并记录证据**  
  _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006_  
  _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11_  
  _Verification: V-002, V-003, V-004, V-005, V-006, V-007, V-008_  
  _Depends: T006, T009_  
  _Boundary: 只运行与 F058 相关的自动化、静态和人工验证；不得真实修改生产数据。_  
  **交付物**：
  - 新建 `features/v2.6.0/058-admin-reassign-department-space/verification.md`。
  - 记录每条命令、退出码、关键输出和 AC 覆盖状态。
  - 对 DM8 和真实 OpenFGA 无法在本地验证的部分标记 `MANUAL_REQUIRED`，提供明确步骤。
  - 更新本文档任务状态与“实际偏差记录”，不得以旧测试证据代替当前验证。

---

## 4. Verification Map

| ID | 命令或方法 | 覆盖范围 |
|----|------------|----------|
| V-001 | `git status --short --branch`、相关文件 diff 检查 | 工作区隔离与用户改动保护 |
| V-002 | `cd src/backend && uv run pytest test/knowledge/test_department_space_reassignment.py -q` | 后端主路径、错误路径、事务、成员与权限 |
| V-003 | `cd src/backend && uv run ruff check <F058-backend-files>` | 后端 lint 与 import |
| V-004 | `cd src/backend && uv run ruff format --check <F058-backend-files>` | 后端格式 |
| V-005 | `cd src/frontend/client && yarn test:ci --runInBand CreateKnowledgeSpaceDrawer.test.tsx knowledge.test.ts` | 前端组件与 API 契约 |
| V-006 | `cd src/frontend/client && yarn tsc --noEmit` | Client TypeScript 类型检查 |
| V-007 | 部门知识库创建、绑定、上传审批、权限相关后端定向回归 | 兼容性回归 |
| V-008 | 人工冒烟：admin 成功调整、非 admin 只读、冲突提示、刷新后新部门展示 | 最终用户行为 |

---

## 5. 执行顺序

```text
T001
 ├─ T002 → T003 → T004 → T005 → T006 ┐
 └─ T007 ───────────────→ T008 → T009 ├─ T010
                                      ┘
```

后端和前端测试准备可以在 T001 完成后独立推进，但 T008 必须等待后端 API 契约 T005 稳定。

---

## 6. 实际偏差记录

- 权限判定由计划中的 `login_user.is_admin()` / `user.role === admin` 收紧为 `is_global_super`。原因是代码检索确认 `is_admin()` 对子租户管理员也可能为真；该调整用于严格满足 BR-002、REQ-001 与 AC-02，不扩大授权范围。
- `uv run` 在隔离工作树自动选择 Python 3.14，而 `onnxruntime` 无兼容构建；验证改用原工作树已有 Python 3.10 虚拟环境，不影响生产代码。
- 新工作树没有独立前端依赖安装，定向 Jest、TypeScript 与 Vite 使用原工作树 `node_modules` 只读依赖执行；未修改 lockfile。
- Client 全量 TypeScript 检查在原工作树与 F058 工作树均为 `671` 个既有错误，退出码均为 `2`，说明 F058 未新增类型错误，但仓库基线未全绿。
- `test_department_knowledge_space_service.py + test_approval_service.py` 在原工作树与 F058 工作树均为 `8 failed, 12 passed`；8 项均因既有缺失模块 `bisheng.api.v1.schema` 在导入阶段失败，未纳入 F058 通过统计。
