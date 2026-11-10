# Tasks 昆联 Agent 反向调用毕昇 Workflow

- **Feature ID**: F122（当前分支拟用）
- **Version**: v3.0.0
- **Status**: MOCK_DONE，T001–T012 完成
- **关联**: [规格](./spec.md)、[已确认设计](./design.md)、[F121 登记验证](../121-kunlian-workflow-management/verification.md)、[版本契约](../release-contract.md)。

## 1. 批次与范围

| 批次 | 任务 | 批次出口 | 当前状态 |
| --- | --- | --- | --- |
| W1 固定版本、幂等受理与授权 | T001–T004 | 通过 F121 权威状态保存指定版本快照与待投递会话，提供统一的实际用户授权入口。 | 4 / 4，E-002 |
| W2 图执行与补偿 | T005–T007 | 同一会话只由一个 Worker 领取，运行固定图并提交稳定终态，投递失败可补偿。 | 3 / 3，E-003 |
| W3 Mock 提交与查询 | T008–T009 | 昆联模拟调用方可提交、重试和查询，越权访问被拒。 | 2 / 2，E-005 |
| W4 本地验收与回归 | T010–T012 | 通过候选 HTTP 接口、真实图引擎和测试调度完成最小闭环及异常回归。 | 3 / 3，E-005、E-006 |
| W5 正式接入与受控验证 | T013–T016 | 正式契约适配、实际基础设施验证与双方联调。 | 契约待确认，环境 `NOT_RUN` |

实施时优先完成 T001–T012。运行记录表仅由隔离夹具建表，候选接口和任务仅在测试环境按需装配。实际环境迁移及上线另行确认。以下 `B` 指 `src/backend/bisheng/`，`BT` 指 `src/backend/test/workflow/`。授权、事务、幂等及状态竞争先写定向用例，批次结束复用已有验证结果。新增测试放在现有目录，复用 F121 测试数据和夹具，并为并发场景使用独立数据库连接。

## 2. Mock 开发任务

### W1 固定版本、幂等受理与授权

- [x] **T001** [数据与契约] 定义运行记录和 Mock 数据边界。
  - 在 `B/workflow/domain/models/kunlian_workflow_run.py`、`B/workflow/domain/schemas/kunlian_workflow_invocation.py` 定义运行表、状态、摘要、终态保留和输入输出合同。登记运行事实归属，接入租户过滤。运行表使用双库兼容字段，唯一键为租户、接入方、实际用户与幂等键摘要。给 `BT/conftest.py` 增加显式隔离夹具。
  - _Requirements: REQ-02, REQ-04, REQ-05, REQ-07_
  - _Acceptance: AC-01, AC-05_
  - _Verification: V-01、V-02。检查作用域、唯一键与对象键顺序等价。_
  - _Depends: 已确认设计，F121 本地登记能力。_

- [x] **T002** [发布仓储] 复用 F121 发布事务，校验可调用版本。
  - 在 `B/workflow/domain/repositories/kunlian_registration.py` 增加事务内读取入口，沿用 Flow → FlowVersion 锁顺序。核验连接、租户、版本归属、在线及 `AVAILABLE` 状态，并取出该版本的图和 Schema。按设计校验线性最小图，区分不支持的图和输入不合约。目录缓存或同步回执只用于登记流程。
  - _Requirements: REQ-01, REQ-02, REQ-06_
  - _Acceptance: AC-02, AC-03, AC-06_
  - _Verification: V-02。覆盖异属、替换、下线、登记不完整和状态不可确认。_
  - _Depends: T001。_

- [x] **T003** [运行仓储] 实现幂等提交和冻结版本。
  - 在 `B/workflow/domain/repositories/kunlian_workflow_run.py` 实现已有记录匹配、内容冲突和新记录提交。锁定 Flow 后用能读到最新提交的查询再次查同键，再核验版本。同一事务保存冻结图、Schema、规范化输入及 `QUEUED` 会话。唯一键竞争失败须回滚并在新事务读取胜出记录。事务提交后才允许投递。
  - _Requirements: REQ-01, REQ-02, REQ-04, REQ-05_
  - _Acceptance: AC-01, AC-02, AC-05_
  - _Verification: V-02。覆盖同键同内容、跨工作流复用、响应丢失和版本后来下线。_
  - _Depends: T001, T002。_

- [x] **T004** [身份与授权] 装配 Mock 可信主体和 F048 校验。
  - 在 `B/workflow/application/kunlian_workflow_invocation.py` 封装当前主体、接入方和租户的校验。通过统一 `use` 授权提交、重试、查询和 Worker 启动。模拟调用方与真实用户权限边界分开，隔离应用使用依赖覆盖，默认身份入口拒绝。正式适配留 `TODO [F122][EXT-01]`。
  - _Requirements: REQ-03, REQ-06, REQ-07_
  - _Acceptance: AC-04, AC-05_
  - _Verification: V-02。覆盖缺身份、伪造字段、停用、撤权与授权依赖不可用。_
  - _Depends: T001。_

### W2 图执行与补偿

- [x] **T005** [Worker] 接通条件领取和启动前授权复核。
  - 在 `B/worker/workflow/kunlian_workflow_run.py` 接入专用任务，消息只携带受信会话引用及恢复租户范围所需的最小元数据。重新加载接入方、实际用户和工作流，复核 `use`。只允许未过期的 `QUEUED` 记录通过条件更新成为 `RUNNING`。未获领取或已终态的任务退出，权限失效时记录安全失败。
  - _Requirements: REQ-02, REQ-03, REQ-04, REQ-05_
  - _Acceptance: AC-02, AC-04, AC-05_
  - _Verification: V-02。覆盖重复领取、受理后撤权、不同租户与消息引用不一致。_
  - _Depends: T003, T004。_

- [x] **T006** [图执行] 运行固定版本并保存最终结果。
  - 复用 `Workflow` 和回调协议。先运行冻结图，到预定表单点后用已校验输入在同一任务内续跑。采集指定输出节点文本并校验 `result`。异常等待、缺失输出、执行异常及输出不合约转为安全失败。按领取标识写入终态，并清理图、输入及临时执行材料。
  - _Requirements: REQ-02, REQ-03, REQ-05, REQ-06_
  - _Acceptance: AC-01, AC-02, AC-04, AC-06_
  - _Verification: V-01。验证实际用户、预置文本输入、无输入图以及稳定成功或失败结果。_
  - _Depends: T005。_

- [x] **T007** [调度补偿] 补投待领取记录并收敛超时。
  - 实现测试范围内有界补投、排队超时和领取后超时。覆盖提交后投递失败与投递结果未知。复用会话引用补投，保留原状态记录。已领取任务失联后进入失败终态，迟到写入通过领取标识和状态条件拦截。使用可控时钟核对保留窗口及临时材料清理。
  - _Requirements: REQ-04, REQ-05, REQ-06_
  - _Acceptance: AC-05, AC-06_
  - _Verification: V-02。故障注入验证补投、超时、重复消息和迟到结果。_
  - _Depends: T005, T006。_

### W3 Mock 提交与查询

- [x] **T008** [候选 API] 接通提交和幂等重试。
  - 在 `B/open_endpoints/api/endpoints/kunlian_workflow_runs.py` 提供候选 `POST /api/v2/kunlian/workflow-runs`，要求 `Idempotency-Key`、目标及版本。返回 `202` 或原会话摘要，错误分类区分输入错误、版本不可用、权限拒绝及幂等冲突。正式 HTTP 契约留 `TODO [F122][EXT-02]`。仅隔离应用装配路由。
  - _Requirements: REQ-01, REQ-03, REQ-04, REQ-05, REQ-06, REQ-07_
  - _Acceptance: AC-01, AC-03, AC-04, AC-05, AC-06_
  - _Verification: V-01、V-02。验证受理后才投递、重放同一会话、非法提交无运行。_
  - _Depends: T003, T004, T007。_

- [x] **T009** [候选 API] 接通状态和结果查询。
  - 同路由提供 `GET /api/v2/kunlian/workflow-runs/{session_id}`。先按可信租户、接入方和用户匹配会话，再复核当前 `use`。返回四态及对应结果，使用禁止共享缓存的响应。会话不可见和不存在统一处理，存储或授权服务临时异常保持原终态。只记录关联标识及安全分类。
  - _Requirements: REQ-03, REQ-05, REQ-06, REQ-07_
  - _Acceptance: AC-01, AC-04, AC-06_
  - _Verification: V-01、V-02。验证轮询、终态重读、不可见会话及临时故障。_
  - _Depends: T004, T006, T008。_

### W4 本地验收与回归

- [x] **T010** [Mock E2E] 验证发布、提交和轮询闭环。
  - 在 `BT/test_kunlian_workflow_invocation_e2e.py` 复用 F121 发布样例，准备 A 发布、B 调用的两版最小图。经候选 HTTP 提交并关闭原请求连接，调用实际图执行路径后用新请求取得最终输出。覆盖保存草稿、V2 替换及 V2 下线，验证 V1 会话实际执行 V1。验收用例随对应实现先写，批次闭环统一核对。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-05, REQ-07_
  - _Acceptance: AC-01, AC-02, AC-04, AC-06_
  - _Verification: V-01、V-02。标明身份、权限和队列替身的边界。_
  - _Depends: T008, T009。_

- [x] **T011** [故障与安全回归] 验证受理竞争、撤权与重复任务。
  - 在 `BT/test_kunlian_workflow_invocation.py` 验证同键并发、提交后响应丢失、下线前后重放和提交竞争，核对会话数量及图实际启动次数。覆盖跨租户、同租户其他用户、其他连接、受理后撤权、投递失败、重复领取与迟到终态。SQLite 隔离证据只覆盖本地行为和约束，双库行锁与跨进程队列由 T015 验证。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-04, REQ-05, REQ-06_
  - _Acceptance: AC-02, AC-03, AC-04, AC-05, AC-06_
  - _Verification: V-02。验证状态、输出及执行次数，避免只断言 HTTP 响应。_
  - _Depends: T007, T009。_

- [x] **T012** [阶段验证] 记录证据并验证旧入口。
  - 从 `src/backend` 对 F122、F121 发布登记和既有 `workflow:invoke` 相关用例运行一次相关回归。对改动文件执行 Ruff 和架构守卫。实施开始时建立 `verification.md`，按批填命令、结果、测试替身和未执行项。确认候选 API 未挂到正式入口，正常 API／Broker／Worker 和真实环境证据分别登记。
  - _Requirements: REQ-01, REQ-03, REQ-04, REQ-05, REQ-07_
  - _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06_
  - _Verification: V-01、V-02 的本地证据与旧合同回归。_
  - _Depends: T010, T011。_

## 3. 正式契约及环境任务

- [ ] **T013** [契约] 固化双方正式合同，状态 `WAITING_EXTERNAL`。
  - 确认可信用户及接入身份、F121 工具版本绑定、OpenAPI、关联标识、轮询与时限、幂等窗口及过期处理、输出保留与清理。补成功、拒绝、冲突及重试合同样例。期限及清理保留 `TODO [F122][EXT-03]`。
  - _Requirements: REQ-01, REQ-03, REQ-04, REQ-05, REQ-07_
  - _Acceptance: AC-01, AC-04, AC-05_
  - _Verification: V-03 的正式样例先行。_
  - _Depends: T012，EXT-01、EXT-02、EXT-03。_

- [ ] **T014** [正式适配] 按已确认合同接线，状态 `WAITING_EXTERNAL`。
  - 装配真实身份、scope、输入输出和错误映射，确认运行记录清理、补投范围及接入关闭方式。实际环境启用和迁移属于独立授权事项。
  - _Requirements: REQ-01, REQ-03, REQ-04, REQ-05, REQ-06, REQ-07_
  - _Acceptance: AC-01, AC-04, AC-05_
  - _Verification: V-03 合同用例与真实联调准备。_
  - _Depends: T013，正式适配范围已确认。_

- [ ] **T015** [受控环境] 验证存储、权限和 Worker，状态 `NOT_RUN`。
  - 在授权测试环境核对 MySQL 和中心 DM8 的事务顺序及唯一键竞争、真实 OpenFGA 授权和撤权、API／Broker／Worker 跨进程补投、领取与终态保存。可在独立环境用 Mock 昆联身份先验证基础设施，实际权限证据按使用的身份与授权链路记录。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-04, REQ-05_
  - _Acceptance: AC-02, AC-04, AC-05, AC-06_
  - _Verification: V-02 的受控环境证据，按基础设施逐项记录。_
  - _Depends: T012，专用环境、测试账号及环境变更授权。_

- [ ] **T016** [双方联调] 验证真实昆联调用，状态 `NOT_RUN`。
  - 昆联在实际测试目录调用可用版本，验证独立轮询、响应丢失后重试、实际用户撤权和跨租户拒绝。记录真实身份和版本事实、关联标识及回退步骤。测试地址、账号和版本样例保留 `TODO [F122][EXT-04]`。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-04, REQ-05, REQ-07_
  - _Acceptance: AC-01, AC-04, AC-05_
  - _Verification: V-03。_
  - _Depends: T014, T015，EXT-04 及双方专用联调环境。_

## 4. 验证与偏差记录

本地功能验收从 T010–T012 取得证据。T015 的真实存储、权限和队列与 T016 的双系统联调分别记录。测试缺前置条件时保留 `NOT_RUN`。人工交互、取消、事件续取、回调和跨平台嵌套留在后续工作包。

审查修复覆盖 T002–T004、T006–T007 和 T009–T012 的既有边界，详见[验证记录](./verification.md)。若实施会改变已确认的版本准入、权限、幂等或终态语义，先更新设计并按 [SDD 指南](../../../docs/SDD-Guide.md) 重新确认。
