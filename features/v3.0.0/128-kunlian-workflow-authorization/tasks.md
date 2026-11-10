# 昆联对接毕昇 Workflow 授权管理任务

- **Feature ID** `F128`（拟用，合入前复核）
- **版本** `v3.0.0`
- **关联** [已确认规格](./spec.md) · [已确认设计](./design.md) · [版本契约](../release-contract.md)

## 1. 状态与批次验收

| 阶段 | 状态 |
| --- | --- |
| 规格与设计 | `CONFIRMED`，用户确认进入任务拆分。 |
| Mock 实施 | `PASS`，14 / 14。 [验证记录](./verification.md) |
| 正式契约与适配 | T015、T016 为 `WAITING_EXTERNAL`。 |
| 真实环境验收 | T017（V-03）、T018（V-04）为 `NOT_RUN`，待执行。 |

| 批次 | 任务 | 验收出口 |
| --- | --- | --- |
| W1 · 身份与权限查询 | T001–T005 | V-01。管理者看到直接授权和修订，普通查看者只读本人有效动作。越权、权限未知或读取期间修订变化时拒绝返回受保护内容。 |
| W2 · 单条授予与撤销 | T006–T009 | V-01。复用 F048 执行同租户用户授权，精准撤销指定本地直接来源。拒绝不受管模型、跨租户目标、保护来源和过期修订。 |
| W3 · 原操作查回与闭环 | T010–T014 | V-01、V-02。并发或响应丢失时仅一次有效变更，未最终确认可区分。通过既有 Workflow 入口验证授权生效、撤销后拒绝及保留独立授权来源。 |
| W4 · 正式接入与真实验收 | T015–T018 | 正式契约与持久回执待确认。受控 F048 环境与昆联实际联调分别保留证据。 |

路径前缀 `B/` 为 `src/backend/bisheng/`，`WT/` 为 `src/backend/test/workflow/`，`PT/` 为 `src/backend/test/permission/`。候选基址 `/__mock__/kunlian/workflows/{workflow_id}` 由隔离 ASGI 应用显式注册。复用现有权限策略和测试夹具，先写定向失败用例，再完成对应实现。各批记录命令、结果、覆盖、跳过和阻塞到 `verification.md`。同一代码状态的通过证据直接复用。

## 2. 本地 Mock 任务

### W1 身份与权限查询

- [x] **T001** [基础设施] 在 `WT/kunlian_workflow_authorization_fixtures.py` 建立局部测试装配，复用现有 F048 资源、授权策略及投影夹具。准备管理者 A、受权者 B、无权者和其他租户，支持在同一权限事实上切换身份、预置独立组授权、注入权限不可用，并提供隔离的原子回执端口夹具。测试实例及其回执随夹具销毁。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-04, REQ-05, REQ-06_ · _Acceptance: AC-01, AC-03, AC-04, AC-05, AC-06, AC-07_ · _Verification: V-01、V-02 由后续行为用例验证_ · _Depends: 无_
- [x] **T002** [后端 API 测试] 在 `WT/test_kunlian_workflow_authorization_reads.py` 用隔离 ASGI 验证管理者清单与本人动作分别读取。覆盖直接来源与只读来源、过滤后空页仍可续读、两次修订核对、只读查看者访问清单被拒、错误接入方或租户、身份上下文不匹配及权限未知。核对安全返回和授权不变。
  - _Requirements: REQ-01, REQ-02, REQ-05_ · 覆盖 AC: AC-01, AC-04 · _Verification: V-01_ · _Depends: T001_
- [x] **T003** [后端 Domain] 在 `B/workflow/application/kunlian_workflow_authorization.py` 接入可信身份与目标校验，绑定接入方、实际自然人、当前租户、委托范围及 Workflow。建立租户 ContextVar，复用既有 Workflow 资源适配和 F048 actor，核对传入 actor 与受信主体一致，保留数据范围约束。清单和写操作显式校验 `manage_permission`。
  - _Requirements: REQ-01, REQ-02, REQ-05_ · _Acceptance: AC-01, AC-04_ · _Verification: V-01，联跑 T002_ · _Depends: T002_
- [x] **T004** [后端 Domain] 在 `B/workflow/application/kunlian_workflow_authorization.py` 分别编排 `list_grants` 和 `get_my_permissions`。管理者清单复用 `get_context`、`get_grantable_models`，比较读取前后资源及 Catalog 修订、投影就绪与当前授权。只返回本地直接来源的允许字段，已有组和保护来源按权限只读展示。本人动作只返回当前操作者的 `actions`。权限未知时关闭访问。
  - _Requirements: REQ-01, REQ-02, REQ-05_ · _Acceptance: AC-01, AC-04_ · _Verification: V-01，联跑 T002_ · _Depends: T002, T003_
- [x] **T005** [后端 API] 在 `B/open_endpoints/api/endpoints/kunlian_workflow_permissions.py` 增加隔离 `GET …/permissions` 与 `GET …/my-permissions`。按已确认候选合同校验路径、游标及页长，使用统一封装、安全错误和 `no-store`。测试装配注入可信身份及服务依赖。
  - _Requirements: REQ-01, REQ-02, REQ-05_ · _Acceptance: AC-01, AC-04_ · _Verification: V-01，联跑 T002_ · _Depends: T002, T004_

**批次验收。** 运行 `test_kunlian_workflow_authorization_reads.py`。用同一 Workflow 分别以 A、B、其他租户和权限未知身份请求。核对返回的授权数据、修订、分页游标及错误分类，并断言拒绝前后的授权状态相同。

### W2 单条授予与撤销

- [x] **T006** [后端 Domain 测试] 在 `PT/test_f048_kunlian_workflow_grant_lookup.py` 复用现有 F048 资源和来源夹具，验证直接用户来源只读检查。覆盖精确对象、租户、来源 ID、非保护和来源可管理性。越权、继承、组来源及保护来源不能作为本期撤权目标。
  - _Requirements: REQ-01, REQ-03, REQ-05_ · 覆盖 AC: AC-04 · _Verification: V-01_ · _Depends: T001_
- [x] **T007** [后端 Domain 测试] 在 `WT/test_kunlian_workflow_authorization_changes.py` 验证单次变更的应用分支。覆盖同租户用户授予、指定来源撤销、目标不合格或跨租户、操作者不能管理该模型，以及资源、Catalog、来源修订变化后的拒绝。核对传给 F048 的 `ADD` 或 `REMOVE` 请求和授权状态。
  - _Requirements: REQ-01, REQ-03, REQ-04, REQ-05, REQ-06_ · 覆盖 AC: AC-04, AC-05 · _Verification: V-01 的写入边界与旧修订_ · _Depends: T001, T004_
- [x] **T008** [后端 Domain] 在 `B/permission/application/resource_api.py` 接入本地直接用户来源的窄只读检查。使用已验证目标、当前操作者和 F048 授权上下文精确定位来源，返回本次撤销所需的最小信息。保留现有通用授权列表和 `mutate_grants` 合同。
  - _Requirements: REQ-01, REQ-03, REQ-05_ · _Acceptance: AC-04_ · _Verification: V-01，联跑 T006_ · _Depends: T006_
- [x] **T009** [后端 Domain] 在 `B/workflow/application/kunlian_workflow_authorization.py` 实现应用内部的单次变更调用。授予解析同租户有效自然人和允许的 F048 普通模型。撤销调用 T008，保留原资源、Catalog、来源修订及字符串来源标识。把受信上下文及内部幂等键交给 F048 `mutate_grants`，由 F048 裁决修订、级别和授权投影。候选写路由随 W3 装配。
  - _Requirements: REQ-01, REQ-03, REQ-04, REQ-05, REQ-06_ · _Acceptance: AC-04, AC-05_ · _Verification: V-01，联跑 T007_ · _Depends: T004, T007, T008_

**批次验收。** 运行 `test_f048_kunlian_workflow_grant_lookup.py` 和 `test_kunlian_workflow_authorization_changes.py`。核对精确撤销、原投影服务调用和修订冲突。跨租户、未授权模型、保护来源及过期请求均不能产生授权变更。

### W3 原操作查回与闭环

- [x] **T010** [后端 Domain 测试] 在 `PT/test_f048_kunlian_workflow_grant_lookup.py` 补原投影操作查读测试，核对租户、Workflow、操作人或操作类型不匹配时不返回结果。在 `WT/test_kunlian_workflow_authorization_receipts.py` 先写重试与并发用例，覆盖同键同内容、同键不同内容、不同键竞争同一修订、撤权后重试和提交后响应丢失。分别验证 `COMMITTED`、无确定事实和 `FINALIZED`，核对只发生一次有效写入及审计无凭据。
  - _Requirements: REQ-01, REQ-04, REQ-05_ · 覆盖 AC: AC-04, AC-05, AC-06 · _Verification: V-01_ · _Depends: T001, T009_
- [x] **T011** [后端 Domain] 在 `B/permission/application/resource_api.py` 增加原投影操作的只读查回。授权管理检查通过后，复用既有投影记录读取，绑定租户、Workflow、操作人、内部幂等键和 `GRANT_MUTATION`。仅向应用返回安全状态及原生效修订。维护、修复及投影写入继续由 F048 处理。
  - _Requirements: REQ-01, REQ-04, REQ-05_ · _Acceptance: AC-04, AC-05, AC-06_ · _Verification: V-01，联跑 T010 的权限应用用例_ · _Depends: T008, T010_
- [x] **T012** [后端 Domain] 在 `B/workflow/application/kunlian_workflow_authorization.py` 编排回执及变更。每次先复核实际用户、目标范围和管理权限。按接入方、租户、操作者、Workflow、幂等键计算作用域并绑定原请求摘要。原子领取后仅由首个请求调用 T009。重复请求查原回执或 T011，只有 `FINALIZED` 确认成功，未确认结果保留 `PENDING`。条件写入回执，保留已确认结果和原生效修订。仅在能证明写前被拒绝时固化拒绝，输出最小审计关联。
  - _Requirements: REQ-01, REQ-04, REQ-05_ · _Acceptance: AC-04, AC-05, AC-06_ · _Verification: V-01，联跑 T010 的回执用例_ · _Depends: T009, T010, T011_
- [x] **T013** [后端 API 测试] 在 `WT/test_kunlian_workflow_authorization_e2e.py` 编写候选写入 HTTP 契约与闭环用例。复用同一隔离权限事实，在候选接口授予 B 后从既有 Workflow 列表及详情访问，校验未获授权动作；撤销后分别验证唯一来源和已有组来源；通过毕昇既有入口另改权限，再对照昆联查询及旧操作回执。核对 HTTP 已生效、待确认、冲突及越权分类。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-04, REQ-05, REQ-06_ · 覆盖 AC: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07 · _Verification: V-01、V-02_ · _Depends: T005, T012_
- [x] **T014** [后端 API] 在 `B/open_endpoints/api/endpoints/kunlian_workflow_permissions.py` 增加 `POST …/permissions/grants` 与 `POST …/permissions/grants/{assignee_id}/revoke`。复用 T003、T012，校验候选合同中的幂等键、修订和十进制字符串来源 ID，输出最小回执及安全状态。仅在隔离装配验证，并保留设计中的四项正式 TODO。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-04, REQ-05, REQ-06_ · _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07_ · _Verification: V-01、V-02，联跑 T013_ · _Depends: T005, T012, T013_

**批次验收。** 联跑回执、F048 查读和端到端测试。记录冲突前后的授权修订、原回执状态和写入次数，并回归 `test_f048_grant_api.py`、`test_f048_grant_policy.py`、`test_f048_projection_service.py` 与 `test_workflow_action_map.py` 的相关用例。执行定向 Ruff、架构守卫和差异检查，将最后结果写入 `verification.md`。

## 3. 正式接入与真实验收

- [ ] **T015** [正式契约] 在 `design.md` 回填 `TODO [F128][EXT-01]`、`TODO [F128][EXT-02]`、`TODO [F128][EXT-03]`、`TODO [F128][EXT-04]`。确认实际用户委托及 SSO Access Token 复用边界、自然人和角色映射、修订及幂等合同、OpenAPI 和联调身份。同步明确正式回执持久化及未留下投影记录的恢复责任。当前 `WAITING_EXTERNAL`。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-04, REQ-05, REQ-06_ · _Acceptance: AC-02, AC-03, AC-04, AC-05, AC-06, AC-07_ · _Verification: V-04 准备_ · _Depends: 双方确认的正式契约与样例_
- [ ] **T016** [正式适配] 按 T015 的结论回到 `design.md` 细化正式接线与测试任务。对受信身份、跨实例回执、重启后查回、过期和未记录投影的恢复建立验收。若需要新增生产数据结构或改变 F048 变更协议，先重新确认设计。当前 `WAITING_EXTERNAL`。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-04, REQ-05, REQ-06_ · _Acceptance: AC-02, AC-03, AC-04, AC-05, AC-06, AC-07_ · _Verification: V-03、V-04_ · _Depends: T014, T015, 正式适配授权_
- [ ] **T017** [受控环境验收] 在 `verification.md` 记录受控 F048 SQL、Redis 一致性标记和 OpenFGA 上的验收。使用受控调用身份验证并发修订、实际投影、未确认查回和撤销后访问阻断。当前 `NOT_RUN`，待执行。
  - _Requirements: REQ-02, REQ-03, REQ-04, REQ-05, REQ-06_ · 覆盖 AC: AC-03, AC-05, AC-06 · _Verification: V-03_ · _Depends: T014, 受控权限环境及测试身份_
- [ ] **T018** [双方联调验收] 在 `verification.md` 记录昆联测试租户的实际用户委托、授权、撤销、权限回读、跨租户与无权拒绝样例。当前 `NOT_RUN`，待执行。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-05, REQ-06_ · 覆盖 AC: AC-02, AC-03, AC-04, AC-07 · _Verification: V-04_ · _Depends: T016, T017, 双方联调环境_

## 4. 实际偏差记录

任务拆分时无偏差。实施发生经确认的设计变化时，记录任务编号及对应设计章节。
