# Tasks 昆联反向调用 Workflow 人工输入与恢复

- **Feature ID**: F123（拟用，合入前复核）
- **Version**: v3.0.0
- **Status**: MOCK_VERIFIED，T001–T012 已完成并验证
- **关联**: [规格](./spec.md)、[已确认设计](./design.md)、[本期验证记录](./verification.md)、[F122 验证记录](../122-kunlian-workflow-invocation/verification.md)。

## 1. 批次与范围

| 批次 | 任务 | 批次验收 | 当前状态 |
| --- | --- | --- | --- |
| W1 交互受理与恢复材料 | T001–T003 | 显式交互模式冻结符合范围的文本图，隔离测试可保存并还原等待材料。 | 3 / 3，见 E-001、E-004 |
| W2 等待、提交与 Worker 恢复 | T004–T007 | 首次 Worker 释放执行，答案只受理一次，恢复与超时按原会话收敛。 | 4 / 4，见 E-002、E-005 |
| W3 候选 HTTP | T008–T009 | 模拟昆联能轮询和提交，归属及实际用户权限边界生效。 | 2 / 2，见 E-003 |
| W4 Mock 验收与兼容回归 | T010–T012 | 两个独立执行进程走通真实最小图，验证竞争、授权、数据清理和 F122 兼容。 | 3 / 3，见 E-004～E-006 |
| W5 正式适配与真实环境 | T013–T016 | 固化正式合同，分别验证真实基础设施及昆联联调。 | `WAITING_EXTERNAL`／`NOT_RUN` |

实施范围优先 T001–T012。复用 F122 运行行及 `material`，采用单次文本表单和轮询，候选 API 与调度只在隔离测试环境装配。`B` 代表 `src/backend/bisheng/`，`BT` 代表 `src/backend/test/workflow/`。授权、并发和状态流转先写定向用例，再合并批次证据。实施时按批更新本文件和 `verification.md`。

## 2. Mock 实施任务

### W1 交互受理与恢复材料

- [x] **T001** [合同与受理] 支持显式交互模式和冻结文本表单。
  - 在 `B/workflow/domain/schemas/kunlian_workflow_invocation.py` 和运行仓储中扩展启动合同。校验原生单文本表单、线性最小图与空初始输入。仅交互模式写入新标识及冻结表单。未指定模式时原请求摘要与受理行为兼容，复用启动键切换模式返回冲突。
  - _Requirements: REQ-01, REQ-02, REQ-07_
  - _Acceptance: AC-01, AC-03, AC-07_
  - _Verification: V-01、V-02。覆盖非法图、旧输入模式、同键变更模式。_
  - _Depends: 已确认设计及 F122 本地运行能力。_

- [x] **T002** [图快照] 提取和还原已验证的等待点结构。
  - 在 `B/workflow/graph/` 提供交互专用的快照适配，按会话标识保存图检查点、共享变量、记忆配置和节点计数，绑定版本、图摘要和预定节点。只处理有界 JSON，拒绝未知版本、未支持的挂起写入和不匹配的节点。用现有设计探针作对照，验证丢失上下文的恢复不算成功验收。
  - _Requirements: REQ-02, REQ-04, REQ-06, REQ-07_
  - _Acceptance: AC-02, AC-06_
  - _Verification: V-01、V-02。验证恢复材料往返及非法快照拒绝。_
  - _Depends: T001。_

- [x] **T003** [测试环境] 准备独立执行进程与隔离存储夹具。
  - 在 `BT/` 扩展 F122 测试夹具，准备单文本图、可区分的 V1／V2、可控时钟、同租户其他用户和跨租户测试身份。让候选 HTTP 和两个 Worker 子进程使用同一隔离测试数据库，竞争场景使用独立连接。确认子进程退出并收集执行次数与结果。
  - _Requirements: REQ-04, REQ-05, REQ-07_
  - _Acceptance: AC-02, AC-03, AC-05_
  - _Verification: V-01、V-02。验证进程隔离及测试数据可追溯。_
  - _Depends: T001。_

### W2 等待、提交与 Worker 恢复

- [x] **T004** [首次 Worker] 到达等待点后提交快照并释放任务。
  - 在 `B/worker/workflow/kunlian_workflow_run.py` 和运行仓储接入交互分支。以原实际用户执行固定图，确认停在冻结表单节点，按当前领取标识和执行期限原子保存快照、交互标识和截止时间。状态成为 `WAITING_INPUT` 后退出任务。丢失领取或保存失败时不能发布待填表单。
  - _Requirements: REQ-02, REQ-04, REQ-05, REQ-06_
  - _Acceptance: AC-01, AC-02, AC-05, AC-06_
  - _Verification: V-01、V-02。验证等待状态与快照同时可见，首阶段旧投递无效。_
  - _Depends: T001, T002, T003。_

- [x] **T005** [交互仓储] 原子受理答案、去重并写入恢复队列状态。
  - 在运行仓储按会话行锁核对归属、当前交互及锁内时间。已授权时先检查历史回执，再校验能否消费。合法答案与提交键摘要、答案摘要及恢复排队期限一次提交。覆盖重复提交、同键改答案、已消费交互、新旧键冲突及非法答案不消耗表单。
  - _Requirements: REQ-03, REQ-05, REQ-06_
  - _Acceptance: AC-04, AC-05, AC-06_
  - _Verification: V-02。独立连接验证提交竞争与截止时间边界。_
  - _Depends: T004。_

- [x] **T006** [恢复 Worker] 按阶段领取并从原节点继续。
  - 恢复消息携带会话、阶段和交互标识，可信租户沿用消息头。Worker 复核原接入方、实际用户和 `use`，用新领取标识和期限进入 `RESUMING`。使用冻结图与快照从原输入节点继续。发布替换或下线不重新选择版本。终态写入必须匹配阶段和领取标识，失联任务由补偿结束。
  - _Requirements: REQ-04, REQ-05, REQ-06_
  - _Acceptance: AC-02, AC-03, AC-04, AC-05, AC-06_
  - _Verification: V-01、V-02。覆盖无前缀重跑、错阶段投递、恢复前撤权和无效快照。_
  - _Depends: T002, T005。_

- [x] **T007** [补偿与保留] 区分等待、恢复排队和恢复执行超时。
  - 使轮询和后台补偿收敛到同一等待超时结果。按状态有界补投未领取的恢复任务，权限服务暂不可用时保留排队直到截止。恢复执行过期后拒绝迟到写入。终态清理图、快照和明文答案，回执在原保留期内仍可重放。保留期届满后清理结果及回执，数值和策略留 `TODO [F123][EXT-03]`。
  - _Requirements: REQ-02, REQ-03, REQ-05, REQ-06_
  - _Acceptance: AC-01, AC-04, AC-05, AC-06_
  - _Verification: V-02。覆盖受理后投递失败、等待与恢复超时及终态清理。_
  - _Depends: T005, T006。_

### W3 候选 HTTP

- [x] **T008** [运行受理与轮询] 接通交互模式和等待状态视图。
  - 在 `B/workflow/application/kunlian_workflow_invocation.py` 和 `B/open_endpoints/api/endpoints/kunlian_workflow_runs.py` 接入候选 POST／GET。使用 F122 的可信身份、会话归属和当前 `use`，在授权后再次核对截止与保留边界。只在 `WAITING_INPUT` 返回可填写的表单和交互标识，终态沿用原结果合同。正式身份及协议留 `TODO [F123][EXT-01]` 和 `TODO [F123][EXT-02]`。
  - _Requirements: REQ-01, REQ-02, REQ-05, REQ-06, REQ-07_
  - _Acceptance: AC-01, AC-05, AC-06, AC-07_
  - _Verification: V-01、V-02。覆盖轮询稳定性、越权不可见、截止及旧响应兼容。_
  - _Depends: T004, T007。_

- [x] **T009** [提交答案] 接通候选提交端点和安全错误。
  - 增加 `POST /api/v2/kunlian/workflow-runs/{session_id}/interactions/{interaction_id}/submit`。授权后按 `Idempotency-Key` 和答案调用仓储，首次受理 `202`，等价重放 `200` 返回原受理回执。提交后使用原会话 GET 查询。区分不可见、冲突、输入错误和暂不可用，避免返回快照、凭据或内部异常。
  - _Requirements: REQ-03, REQ-05, REQ-06, REQ-07_
  - _Acceptance: AC-04, AC-05, AC-06_
  - _Verification: V-01、V-02。覆盖无效输入后修正、终态重放与权限失败。_
  - _Depends: T005, T007, T008。_

### W4 Mock 验收与兼容回归

- [x] **T010** [跨进程闭环] 用候选 HTTP 和真实 Workflow 验收同一次运行。
  - 在 `BT/` 跑固定版本启动、轮询、提交及取结果。A 保存快照并退出，B 从同一隔离数据库读取后恢复。结果同时验证暂停前产生的变量和新答案，断言同会话、同版本、不同进程以及开始节点仅执行一次。覆盖等待期间 V2 替换或 V1 下线。
  - _Requirements: REQ-01, REQ-02, REQ-04, REQ-07_
  - _Acceptance: AC-01, AC-02, AC-03_
  - _Verification: V-01、V-02。探针或同进程调用不能代替该验收。_
  - _Depends: T003, T006, T008, T009。_

- [x] **T011** [故障和授权] 验证竞争、撤权及错阶段投递。
  - 用独立数据库连接和可控时钟核对并发提交与截止时间竞争，比较接受次数和真实节点恢复次数。核对响应丢失后重放、提交后撤权、不同用户／租户／接入方、补投、旧任务消息和迟到终态。记录 SQLite 和调度替身的验证边界。
  - _Requirements: REQ-03, REQ-04, REQ-05, REQ-06_
  - _Acceptance: AC-04, AC-05, AC-06_
  - _Verification: V-02。覆盖安全拒绝和可查询失败。_
  - _Depends: T003, T007, T009。_

- [x] **T012** [兼容性与阶段验收] 验证 F122 原路径及交互材料清理。
  - 验证原预置输入、无交互调用、旧幂等记录和原结果响应。检查新模式独立、终态无明文答案及快照、回执到期清理。合并 F123、F122 和直接依赖的回归证据，执行相关 lint、架构检查，记录实际命令和环境边界。
  - _Requirements: REQ-01, REQ-03, REQ-06, REQ-07_
  - _Acceptance: AC-04, AC-06, AC-07_
  - _Verification: V-01、V-02。核对旧合同、终态保留和未装配的正式入口。_
  - _Depends: T010, T011。_

## 3. 正式合同及环境任务

- [ ] **T013** [正式契约] 确认真实身份、交互合同和窗口，状态 `WAITING_EXTERNAL`。
  - 确认实际用户传递、等待表单、轮询、提交幂等、回执和错误、等待／恢复／保留期限。对照正式样例补成功、拒绝和重复提交用例。
  - _Requirements: REQ-02, REQ-03, REQ-05, REQ-06, REQ-07_
  - _Acceptance: AC-01, AC-04, AC-05, AC-06_
  - _Verification: V-03 的合同准备。_
  - _Depends: T012，EXT-01、EXT-02、EXT-03。_

- [ ] **T014** [正式适配] 按正式合同接入，状态 `WAITING_EXTERNAL`。
  - 复用 F122 正式身份接线，适配已确认的响应和错误。确定补投和清理范围、启用条件、旧会话处理及回退顺序。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-05, REQ-07_
  - _Acceptance: AC-01, AC-04, AC-05_
  - _Verification: V-03 的正式适配验证。_
  - _Depends: T013，F122 正式身份及运行契约可用。_

- [ ] **T015** [受控环境] 验证真实数据库、权限和 Worker，状态 `NOT_RUN`。
  - 在受控 MySQL、中心 DM8、OpenFGA、Broker 和独立 Worker 中验证行锁、超时竞争、跨 Worker 持久化恢复、撤权、消息重复与回退。可先用 Mock 昆联身份独立验证基础设施，按实际验证边界记录。
  - _Requirements: REQ-03, REQ-04, REQ-05, REQ-06, REQ-07_
  - _Acceptance: AC-02, AC-04, AC-05, AC-06_
  - _Verification: V-03，真实基础设施待执行。_
  - _Depends: T012，受控环境和测试权限具备。_

- [ ] **T016** [双方联调] 验证真实昆联调用、表单和恢复，状态 `NOT_RUN`。
  - 从昆联测试环境以实际用户调用，验证断线后轮询、表单显示、重复提交、跨 Worker 恢复和终态。环境、账号、版本及联调样例留 `TODO [F123][EXT-04]`。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-04, REQ-05, REQ-07_
  - _Acceptance: AC-01, AC-02, AC-04, AC-05_
  - _Verification: V-03，真实联调待执行。_
  - _Depends: T014, T015，EXT-04。_

## 4. 验证记录与偏差

V-01、V-02 已在隔离 Mock 环境通过，V-03 为 `NOT_RUN`。各批次命令、验收覆盖和真实环境边界见[验证记录](./verification.md)。若需要改变已确认的恢复、授权、状态语义或存储范围，按 [SDD 指南](../../../docs/SDD-Guide.md) 先更新设计并确认。

T001–T012 复审修复了表单校验、恢复答案完整性、明确拒绝分类和超时补偿问题。修复后定向及相关回归通过（E-007～E-009）；任务范围和 T013–T016 的待办状态不变。
