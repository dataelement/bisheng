# Tasks: F069-Filelib OpenAPI 外部用户权限上下文

**关联规格**: [spec.md](./spec.md)
**版本**: v2.6.0
**状态**: Confirmed（用户于 2026-08-02 授权在当前分支实施）

---

## 阅读摘要

- 本计划只修改四个已确认的 Filelib OpenAPI：知识资源列表、文件列表、文件详情和 Chunk 检索。
- `X-Developer-Token` 始终先验证调用资格；`external_id` 可选，未传时保留 Token 绑定用户行为。
- 传入 `external_id` 时全局解析唯一有效用户，完整继承目标用户权限，包括全局超级管理员，并在本次请求内解除租户过滤。
- 权限与共享 ContextVar 风险采用 Test-First；Repository、Service、API 分三批先红后绿。
- 不新增 DAO、数据库表、migration、依赖、配置、前端或非目标 Filelib 路由。
- 当前工作区已有与 F069 无关的修改，实施时必须保持不变。

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| `spec.md` | ✅ 已确认 | 用户于 2026-08-02 确认双重身份、全局匹配、完整权限和错误语义。 |
| `tasks.md` | ✅ 已确认 | 用户于 2026-08-02 授权在当前分支按 T001-T008 实施。 |
| 实现 | ✅ 自动化范围完成 | T001-T008 完成；T009 为隔离环境人工门禁。 |
| 验证 | ⚠️ 人工门禁待执行 | 自动化验证见 `verification.md`；隔离环境人工验证为 `MANUAL_REQUIRED`。 |

---

## 开发模式与边界

- **后端 Test-First**：用户唯一性、身份替换、超级管理员继承、Token 错误优先级和上下文复位均先写失败测试。
- **分层约束**：`Endpoint → FilelibUserContextService → UserRepository → DB`；Endpoint 不查 ORM，Service 不写 ORM 查询，不新增 `UserDao` 方法。
- **失败关闭**：不存在、禁用和重复用户统一 HTTP `403`；显式空白或超长参数 `422`；不得回退或任取第一条。
- **认证优先**：Token 失败时不得查询外部用户或调用 Filelib 业务。
- **上下文安全**：解除租户过滤和可见租户限制仅覆盖显式外部用户请求，成功、拒绝和异常后都必须复位。
- **兼容性**：不传 `external_id` 的请求、成功响应字段和非本特性错误保持不变。
- **敏感信息**：测试与日志不得包含真实 Token；对外错误不得回显 `external_id`、匹配数量或用户状态。
- **共享文件约束**：T003-T006 会串行编辑 `open_endpoints/api/dependencies.py`、`filelib.py` 及其测试，禁止并发写冲突。
- **环境约束**：自动化测试不得连接生产 MySQL、Redis、OpenFGA、Milvus、Elasticsearch 或 MinIO；人工验证只能在获授权的隔离环境执行。

---

## Tasks

### 阶段 1：User Repository 唯一性契约

- [x] **T001**: 编写按全局 `external_id` 列出有效用户的 Repository 失败测试
  - Done when: 隔离 Repository 测试定义精确匹配、`delete=0` 过滤、无匹配返回空列表、不同 `source` 下相同 `external_id` 返回全部有效候选，以及禁用记录不掩盖有效记录；当前接口缺失导致测试按预期失败。
  - _Requirements: REQ-004, REQ-007, REQ-009_
  - _Acceptance: AC-06, AC-12_
  - _Verification: V-003_
  - _Depends: none_
  - _Boundary: `src/backend/test/user/test_user_repository_external_id.py` only; isolated async session/fake result, no live database or DAO changes_

- [x] **T002**: 实现 User Repository 全局候选查询
  - Done when: `UserRepository` 增加稳定的异步只读契约，`UserRepositoryImpl` 使用 SQLModel/SQLAlchemy 参数化精确条件返回全部 `delete=0` 候选，不调用 `.first()`，不按 `source` 或租户过滤，不新增 DAO；T001 转绿。
  - _Requirements: REQ-004, REQ-009_
  - _Acceptance: AC-06, AC-12_
  - _Verification: V-003_
  - _Depends: T001_
  - _Boundary: `src/backend/bisheng/user/domain/repositories/interfaces/user_repository.py` and `implementations/user_repository_impl.py` only; no model, schema, migration or existing repository semantic changes_

### 阶段 2：Filelib 用户身份与全局上下文

- [x] **T003**: 编写 Filelib 用户上下文 Service 失败测试
  - Done when: 测试先定义 `external_id is None` 原样返回 Token 用户且不改变上下文；唯一普通用户构造完整角色身份；唯一全局超级管理员保留 `is_global_super=true`；不存在、仅禁用和重复有效用户统一拒绝；外部用户业务作用域内租户过滤和 Token 可见租户限制解除；正常返回、403、取消和下游异常后全部 ContextVar/过滤开关恢复；当前 Service 缺失导致测试按预期失败。
  - _Requirements: REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008, REQ-009_
  - _Acceptance: AC-03, AC-04, AC-05, AC-06, AC-08, AC-09, AC-11, AC-12_
  - _Verification: V-002, V-005, V-006_
  - _Depends: T002_
  - _Boundary: `src/backend/test/open_endpoints/test_filelib_external_user_context.py` service/context tests only; use fake repository and patched login-user initialization, no endpoint edits_

- [x] **T004**: 实现 Filelib 用户上下文 Service 与依赖注入
  - Done when: 新 Service 接收 `DeveloperTokenPrincipal`、可选 `external_id` 和 `UserRepository`；缺失时复用 principal.user；显式值查询全部有效候选并要求恰好一条；使用现有登录身份初始化能力获得角色与 `is_global_super`；为外部用户业务调用提供可可靠退出的全局数据上下文；`open_endpoints/api/dependencies.py` 只负责注入 Repository/Service 和组合依赖；详细拒绝原因不对外回显且日志不含原始标识；T003 转绿。
  - _Requirements: REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008, REQ-009_
  - _Acceptance: AC-03, AC-04, AC-05, AC-06, AC-08, AC-09, AC-11, AC-12_
  - _Verification: V-002, V-005, V-006_
  - _Depends: T003_
  - _Boundary: new `src/backend/bisheng/open_endpoints/domain/services/filelib_user_context_service.py` plus strictly necessary providers in `src/backend/bisheng/open_endpoints/api/dependencies.py`; no DeveloperTokenService, middleware, global tenant-filter or Knowledge permission semantic changes_

### 阶段 3：四接口参数和身份传播

- [x] **T005**: 编写四个 Filelib Endpoint 契约与安全失败测试
  - Done when: 参数化路由/Endpoint 测试先覆盖三个 GET Query 和 `/retrieve` Body 的可选 `external_id`；完全缺失回退；空字符串、纯空白和超过 255 字符返回 `422` 且不调用业务；无效 Token 与无效 `external_id` 同时出现时只返回现有 Token 错误且不查询用户；四接口把普通用户或超级管理员 `UserPayload` 传给对应 Knowledge 业务；Token 用户有权/目标用户无权和反向场景均按目标用户决定；成功响应及既有错误 fixture 不变；当前接口未接线导致测试按预期失败。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-005, REQ-006, REQ-007, REQ-008_
  - _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-05, AC-07, AC-08, AC-10, AC-11_
  - _Verification: V-001, V-004, V-006_
  - _Depends: T004_
  - _Boundary: `src/backend/test/open_endpoints/test_filelib_external_user_context.py` route/endpoint tests and strictly necessary updates to `src/backend/test/knowledge/test_knowledge_space_chat_service_retrieve.py`; no production endpoint edits_

- [x] **T006**: 接入 GET Query、Retrieve Body 与四接口业务用户
  - Done when: 三个 GET Endpoint 接收经统一校验的可选 Query 参数并在 Token principal 成功后解析业务用户；`RetrieveReq` 接收可选 `external_id`，最大长度 255 且显式空白失败；`/retrieve` 在解析用户后以该用户构造或绑定 `KnowledgeSpaceChatService`；列表、文件列表、详情和检索的权限主体均为解析用户；外部用户的全局上下文覆盖完整业务调用并在所有退出路径复位；未传路径继续使用 Token 用户；T005 和既有 Filelib/Knowledge 回归转绿。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008_
  - _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11_
  - _Verification: V-001, V-004, V-005, V-006_
  - _Depends: T005_
  - _Boundary: `src/backend/bisheng/open_endpoints/domain/schemas/filelib.py`, the four confirmed handlers in `src/backend/bisheng/open_endpoints/api/endpoints/filelib.py`, and strictly necessary local dependency wiring only; do not alter other Filelib routes or response schemas_

### 阶段 4：发布契约与接口文档

- [x] **T007**: 更新 release contract 和 Filelib OpenAPI 文档
  - Done when: `release-contract.md` 登记 F069 对 DeveloperToken/User/Knowledge 的依赖和新不变量：Token 先验证资格、可选外部用户决定四接口权限、全局匹配失败关闭、完整超级管理员继承、仅当前无租户部署允许；接口文档逐接口增加参数位置、可选回退、错误优先级、统一 `403`、空白 `422`、curl 示例、安全警告和兼容说明；文档不包含真实 Token 或用户标识。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008_
  - _Acceptance: AC-01, AC-02, AC-03, AC-05, AC-06, AC-07, AC-08, AC-10, AC-11_
  - _Verification: V-006, V-007_
  - _Depends: T006_
  - _Boundary: `features/v2.6.0/release-contract.md`, `docs/api/filelib-openapi-interfaces.md`, and F069 status metadata only; no source, config, Token whitelist or live deployment mutation_

### 阶段 5：自动化验收与人工门禁

- [x] **T008**: 执行 V3 定向回归并创建 `verification.md`
  - Done when: 相关 User Repository、Open Endpoints、DeveloperToken 和 Knowledge pytest，Ruff format/check，架构守卫、敏感信息源码扫描、文档参数一致性及 `git diff --check` 均记录实际命令、退出码和摘要；AC-01 至 AC-12 分别标记 `PASS`、`FAIL`、`MANUAL_REQUIRED` 或 `NOT_RUN`；确认无新 migration、依赖、配置、前端或非目标路由改动；未连接真实外部基础设施。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008, REQ-009_
  - _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12_
  - _Verification: V-001, V-002, V-003, V-004, V-005, V-006, V-007_
  - _Depends: T002, T004, T006, T007_
  - _Boundary: read-only validation commands, formatting limited to F069 touched Python files, F069 `verification.md` and task status only; no live DB/Redis/OpenFGA/storage calls_

- [ ] **T009**: 在隔离环境执行真实权限与全局作用域人工验收
  - Done when: 经环境负责人授权后，使用受控 Token、普通有权用户、普通无权用户、重复 `external_id` 数据和全局超级管理员分别调用四接口；确认 Token 错误优先、缺省回退、目标用户权限、全局数据作用域、统一错误、成功响应兼容及连续请求无上下文泄漏；记录环境、脱敏请求、结果和回滚检查；如果环境启用多租户则停止并回到 spec 更新，不继续验证。
  - _Requirements: REQ-001, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008_
  - _Acceptance: AC-01, AC-03, AC-04, AC-05, AC-06, AC-08, AC-09, AC-10, AC-11_
  - _Verification: V-008_
  - _Depends: T008_
  - _Boundary: authorized isolated environment only; never production, never create/modify real Token, user, permission tuple or tenant data without separate explicit approval_

---

## Verification Checkpoints

| Checkpoint | 触发点 | 最低证据 | 禁止事项 |
|------------|--------|----------|----------|
| CP-01 | T002 完成 | T001 Repository 测试转绿，证明重复候选不会被 `.first()` 隐藏。 | 不修改 User model、DAO、migration 或同步规则。 |
| CP-02 | T004 完成 | T003 身份、超级管理员、统一拒绝和上下文复位测试转绿。 | 不修改全局 middleware、PermissionService 或 DeveloperTokenService 语义。 |
| CP-03 | T006 完成 | T005 四接口契约、安全优先级与身份传播测试转绿，既有定向回归通过。 | 不扩展到其他 Filelib 路由，不连接真实外部服务。 |
| CP-04 | T008 完成 | V-001 至 V-007 的实际证据写入 `verification.md`，所有 AC 有状态。 | 不重复运行同一代码状态下的同范围成功命令，不伪报 V-008。 |
| CP-05 | T009 完成 | V-008 隔离环境证据和回滚检查完整。 | 多租户环境、生产环境或无授权数据变更必须立即停止。 |

### T008 最终命令范围

后端命令从 `src/backend/` 执行；实际任务可在定向测试文件确定后收窄或补充，但必须在 `verification.md` 记录最终范围：

```bash
uv run pytest test/user/test_user_repository_external_id.py \
  test/open_endpoints/test_filelib_external_user_context.py \
  test/knowledge/test_knowledge_space_chat_service_retrieve.py \
  test/developer_token/test_developer_token_dependency.py

uv run ruff format --check \
  bisheng/user/domain/repositories/interfaces/user_repository.py \
  bisheng/user/domain/repositories/implementations/user_repository_impl.py \
  bisheng/open_endpoints/domain/services/filelib_user_context_service.py \
  bisheng/open_endpoints/api/dependencies.py \
  bisheng/open_endpoints/domain/schemas/filelib.py \
  bisheng/open_endpoints/api/endpoints/filelib.py \
  test/user/test_user_repository_external_id.py \
  test/open_endpoints/test_filelib_external_user_context.py \
  test/knowledge/test_knowledge_space_chat_service_retrieve.py

uv run ruff check <上述 Python 文件>
```

仓库根目录执行：

```bash
bash scripts/arch-guard.sh <逐个 F069 修改的 Python 文件>
rg -n "bst_[A-Za-z0-9]|X-Developer-Token: [^b{]" \
  features/v2.6.0/069-filelib-external-user-context \
  docs/api/filelib-openapi-interfaces.md \
  src/backend/bisheng/open_endpoints \
  src/backend/test/open_endpoints
git diff --check
```

`arch-guard.sh` 接收单文件参数，实施时必须逐个检查 F069 修改的 Python 文件，不能把目录当作单文件传入。

---

## Coverage Matrix

| Requirement | Acceptance Criteria | Tasks | Verification |
|-------------|---------------------|-------|--------------|
| REQ-001 | AC-01 | T005, T006, T007, T008, T009 | V-001, V-007, V-008 |
| REQ-002 | AC-02, AC-07 | T005, T006, T007, T008 | V-001, V-007 |
| REQ-003 | AC-03 | T003, T004, T005, T006, T007, T008, T009 | V-002, V-004, V-008 |
| REQ-004 | AC-04, AC-06 | T001, T002, T003, T004, T006, T007, T008, T009 | V-002, V-003, V-004, V-008 |
| REQ-005 | AC-04, AC-05 | T003, T004, T005, T006, T007, T008, T009 | V-002, V-004, V-008 |
| REQ-006 | AC-05, AC-08, AC-09 | T003, T004, T005, T006, T007, T008, T009 | V-004, V-005, V-008 |
| REQ-007 | AC-06, AC-07 | T001, T003, T004, T005, T006, T007, T008, T009 | V-001, V-002, V-006 |
| REQ-008 | AC-01, AC-03, AC-09, AC-10, AC-11 | T003, T004, T005, T006, T007, T008, T009 | V-001, V-004, V-005, V-006, V-007, V-008 |
| REQ-009 | AC-12 | T001, T002, T003, T004, T008 | V-003, V-007 |

---

## 执行顺序

```text
T001 -> T002 -> T003 -> T004 -> T005 -> T006 -> T007 -> T008 -> T009
```

T001/T003/T005 是失败测试批次，分别在 T002/T004/T006 转绿。所有任务共享身份契约和部分文件，按顺序串行实施；不使用并行 Agent 修改共享代码。

---

## 任务质量门

- [x] 每个任务引用至少一个 `REQ-*`。
- [x] 每个行为任务引用至少一个 `AC-*`。
- [x] AC-01 至 AC-12 均有实现任务或验证任务覆盖。
- [x] 每个任务具有可观察的 Done when 和明确边界。
- [x] Repository、Service、API 三个独立风险批次均测试先行。
- [x] Token 优先、空白防回退、重复失败关闭、超级管理员和上下文复位均有拒绝/失败测试。
- [x] 最终验证复用同一代码状态的证据，不为每个微任务重复跑全套。
- [x] 没有新增 DAO、数据库、migration、依赖、配置、前端或非目标 Filelib 路由任务。
- [x] V-008 被明确标记为需授权的隔离环境人工验证，不混入自动化完成声明。
- [x] 用户已确认 `tasks.md` 并授权实施（2026-08-02）。

---

## 实际偏差记录

- T001-T008 已完成；T009 未执行并标记为 `MANUAL_REQUIRED`。
- 实现中发现用户候选查询若在进入全局上下文前执行，会被 Token 租户过滤；已增加失败测试并将 bypass/visible 上下文提前覆盖候选查询和完整业务调用。
- `filelib.py` 是未统一 Ruff 格式的遗留大文件。为保持最小 diff，未执行数百行全文件机械格式化；新增代码通过定向安全 lint，其余新增/局部文件通过完整 Ruff format/check，详情见 `verification.md`。
- 当前 Git 分支为 `feat/2.5.0-sg`，而 F069 归属 `v2.6.0`；用户已于 2026-08-02 明确授权在当前分支继续实施。
- 工作区已有与 F069 无关的 `src/backend/bisheng/shougang_portal_config/domain/services/portal_config_service.py`、`src/backend/celerybeat-schedule.db`、`.coaligne/` 和 `.coaligneignore` 变更；实施和验证必须保留，不得纳入 F069 修改。
- `features/` 被 `.gitignore` 忽略；F069 SDD 文档不会出现在普通 `git status` 中，是否强制纳入版本控制由用户另行决定，本任务不自行暂存。
