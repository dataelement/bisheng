# Tasks 昆联平台 Agent 节点

- **Feature ID**: F119
- **Status**: IN_PROGRESS
- **Mode**: IMPLEMENT_SELECTED_TASKS
- **Updated**: 2026-11-05（Asia/Shanghai）
- **关联** — [spec.md](./spec.md)、[design.md](./design.md)、[版本契约](../release-contract.md)。

## 1. 状态与执行边界

| 阶段 | 状态 | 说明 |
| --- | --- | --- |
| spec.md | CONFIRMED | 9 项需求、25 条 AC 已确认，含 Mock／TODO 要求。 |
| design.md | CONFIRMED | 用户已确认设计及其中的执行附属表、发布事务和内部授权方案。 |
| tasks.md | IN_PROGRESS | 已授权实施 T001—T040。 |
| Mock 开发 | IN_PROGRESS | T001 至 T038 本地实施完成，38 / 40；T039、T040 的正常环境验收待执行。 |
| 真实接口替换 | WAITING_EXTERNAL | T041 至 T047，0 / 7。 |
| 真实环境验证 | NOT_RUN | T048 至 T050，0 / 3，待执行。 |
| 全部实施 | IN_PROGRESS | 38 / 50，真实接口和环境任务保留未执行。 |

用户已确认任务规划并授权实施 T001—T040 的 Mock 部分。任务勾选须有产物及验证依据。本轮范围不含 T041—T050，真实接口和环境验证保持待执行。

## 2. 批次、验证和 TODO 规则

| 批次 | 任务 | 可观察交付 | 前置条件 |
| --- | --- | --- | --- |
| Wave 0 | T001 至 T007 | 领域登记、模型、类型、设置及错误基础。 | 已确认设计。 |
| Wave 1 | T008 至 T017 | 后端 Mock 资源、版本及参数验证 API。 | Wave 0。 |
| Wave 2 | T018 至 T031 | 节点同步执行、事务发布、实际用户、调度及输出保护。 | Wave 1 的契约和仓储。 |
| Wave 3 | T032 至 T040 | 画布配置、试运行及 Mock 最小流程交付。 | Wave 2 和现有本地测试能力。 |
| Wave 4 | T041 至 T047 | 真实身份及 HTTP 适配器替换。 | Mock 主流程及对应 EXT 合同。 |
| Wave 5 | T048 至 T050 | 双数据库、双系统和浏览器验收证据。 | 受控环境与对应接口就绪。 |

依赖以各任务的 `Depends` 为准。T048 仅依赖 Mock 交付，可在受控中间件具备时执行，无须等待昆联正式接口。任务在同一文件上的修改按明确分工增量完成，不能重写前序逻辑。

### 2.1 验证组织

- 配置、模型和错误基础排在业务前。权限、事务、并发、发送许可及状态转换先写测试，再接实现。
- 测试任务只增加测试或必要的同目录夹具，实施任务只接产品逻辑。复用现有 pytest、SQLite、权限及请求夹具，只有确实缺失时才增补局部夹具。
- `Acceptance` 是任务的 AC 追溯。测试任务另列“覆盖 AC”，两处编号须一致，禁止缩写或范围编号。
- 按独立业务风险分组，等价场景参数化。同一代码状态的成功证据可以复用，批次完成后做一次模块验证，避免逐任务重复跑全套。
- 本地 SQLite、受控 HTTP、Mock API E2E、真实 Worker／中间件及昆联真实环境分别登记。脚本已编写不能计作脚本已执行。
- 主要任务控制在一至两个源文件。T007 的三语生成产物由既有构建命令产生，属于同批机械产物，不能手改或单独重复拆任务。
- 仅 Platform 增加业务界面。Client 的共享错误文案生成件随既有流程更新。

### 2.2 待替换标记

用户已明确要求保留 TODO。此要求优先于任务审查中禁止无理由延期 TODO 的通用条款。

```text
# TODO [F119][EXT-01] 当前目录和版本使用 Mock，正式资源契约确认后替换并补真实联调。
# TODO [F119][EXT-02] 当前外部身份为模拟映射，确认 Token 复用或现有委托规则后替换。
# TODO [F119][EXT-03] 当前 invoke 使用 Mock，正式同步、超时和幂等契约确认后替换并验证。
```

Mock 来源、真实占位适配及未确认假设都在实际代码位置留下标记。Python 使用 `# TODO`，TypeScript 使用 `// TODO`，注释使用中文。标记须包含 EXT、模拟内容和替换条件。TODO 不能代替本地授权、类型校验、事务、去重、停止保护或脱敏的实现。

### 2.3 外部门禁

| 门禁 | 影响 | 未满足时 |
| --- | --- | --- |
| EXT-01 | 目录、版本、Schema 和权限预检映射。 | Mock 可继续，真实资源适配待执行。 |
| EXT-02 | Token 复用或可信委托、身份与租户含义。 | Mock 使用已授权的本地用户，真实授权适配待执行。 |
| EXT-03 | invoke 状态、版本证明、超时、错误及幂等。 | 真实执行待执行，首期 POST 不自动重发。 |
| EXT-04 | 专属地址、样例、身份、OpenAPI 和联调时间。 | 真实双系统及浏览器验证 NOT_RUN。 |
| EXT-05 | 选定 Agent 涉及双向嵌套时的防环规则。 | 保留 TODO，涉及嵌套的版本不纳入首批真实验收。 |
| ENV-DB | 受控 MySQL／DM8、Redis、OpenFGA、Worker 及多实例能力。 | 真实存储和调度验证 NOT_RUN。 |
| ENV-IDENTITY | F118 真实身份联调及 A／B／跨租户测试资格。 | 不把 Mock 身份审计计作真实通过。 |

## 3. Wave 0 基础契约

- [x] **T001** [基础设施] 登记 F119 的领域边界与依赖
  - **文件** — `features/v3.0.0/release-contract.md`。
  - **工作** — 登记 Workflow 执行附属表、F118 内部授权及现有发布入口扩展。表由 Workflow 负责，F118、F048 和平台凭据 Owner 保持原归属，不新增权限动作或修改既有不变量。
  - _Requirements: REQ-03, REQ-04, REQ-06, REQ-08_
  - _Acceptance: AC-06, AC-17, AC-22_
  - _Verification: V-02, V-03，领域归属与设计 D3、D4、D5 一致。_
  - _Depends: 无_

- [x] **T002** [基础设施] 定义执行附属模型及租户登记
  - **文件** — `src/backend/bisheng/workflow/domain/models/platform_agent_execution.py`、`src/backend/bisheng/core/database/tenant_filter.py`。
  - **工作** — 定义 `workflow_platform_agent_execution` 的身份、冻结图、调度、调用和生命周期字段。使用 JsonType、有界列及索引，参加模型发现和自动租户过滤。只声明新表，不在任务中执行真实建表或历史数据处理。
  - _Requirements: REQ-03, REQ-06, REQ-08_
  - _Acceptance: AC-08, AC-17, AC-19, AC-22_
  - _Verification: V-02, V-04，模型发现与双数据库声明检查，真实锁语义交 T048。_
  - _Depends: T001_
  - _Boundary: 回退先禁用 F119 并保留记录，不能自动删表或清理调用事实。_

- [x] **T003** [基础设施] 定义规范化类型和受控子设置
  - **文件** — `src/backend/bisheng/workflow/domain/schemas/platform_agent.py`、`src/backend/bisheng/core/config/settings.py`。
  - **工作** — 定义资源、版本、绑定、输入、InvokeResult、可信 Actor 和内部执行引用。增加 `WorkflowConf.platform_agent`，按用户最新要求默认 mock，包含模式、连接修订、可选 Mock 主体映射及设计中的预算和大小限制。身份和凭据字段不得由节点业务输入构造。
  - _Requirements: REQ-01, REQ-02, REQ-04, REQ-09_
  - _Acceptance: AC-04, AC-11, AC-23, AC-25_
  - _Verification: V-01, V-03, V-07，后续 T008 覆盖严格类型、默认 Mock、显式关闭及来源区分。_
  - _Depends: T001_

- [x] **T004** [基础设施] 核对并登记错误码
  - **文件** — `docs/constitution.md`、`features/v3.0.0/release-contract.md`。
  - **工作** — 实施时扫描 Workflow 105 段及相关源码的实际占用，为配置、版本、冲突、上游、结果未知和模式错误登记未占用码位。身份和权限继续复用 Owner 错误，记录分配结果供 T005、T006、T007 使用。
  - _Requirements: REQ-06, REQ-07_
  - _Acceptance: AC-15, AC-16, AC-20, AC-21_
  - _Verification: V-05，编码唯一性和同批登记检查。_
  - _Depends: T001_

- [x] **T005** [基础设施] 增加安全领域错误类型
  - **文件** — `src/backend/bisheng/common/errcode/flow.py`；`src/backend/bisheng/main.py` 增加仅针对新错误类的 HTTP 状态接线。
  - **工作** — 按 T004 登记定义 BaseErrorCode 子类及 HTTP 状态，公开信息仅含稳定类别和允许的关联信息，禁止把原始异常或上游正文带入响应。
  - _Requirements: REQ-06, REQ-07_
  - _Acceptance: AC-15, AC-16, AC-18, AC-20, AC-21_
  - _Verification: V-04, V-05，T018 的错误与秘密探针验证。_
  - _Depends: T004_

- [x] **T006** [基础设施] 增加中文和英文错误文案源
  - **文件** — `src/frontend/packages/locales/src/api_errors/zh-Hans.json`、`src/frontend/packages/locales/src/api_errors/en.json`。
  - **工作** — 为 T005 实际新增码位补齐两语言文案，说明配置、权限、未知结果和重新授权动作，保留原有键。
  - _Requirements: REQ-06, REQ-07_
  - _Acceptance: AC-15, AC-16, AC-20, AC-21_
  - _Verification: V-05，JSON 解析及新增键核对。_
  - _Depends: T005_

- [x] **T007** [基础设施] 补日文并生成共享错误产物
  - **文件** — `src/frontend/packages/locales/src/api_errors/ja.json`，及既有 locales 构建生成件。
  - **工作** — 补齐日文。使用 `@bisheng/locales` 的现有 build／check 命令生成两端产物，核对三语键一致和后端码位覆盖，不手写生成件。
  - _Requirements: REQ-07, REQ-08_
  - _Acceptance: AC-20, AC-21, AC-22_
  - _Verification: V-05, V-06，复用项目 check-i18n 与生成产物检查。_
  - _Depends: T006_

## 4. Wave 1 Mock 资源与校验接口

- [x] **T008** [后端 Domain／测试] 编写类型、Schema 与 Mock 契约测试
  - **文件** — `src/backend/test/workflow/test_platform_agent_contract.py`。
  - **工作** — 用参数化样例覆盖授权／空目录／失败、支持和不支持的 Schema、零值和缺失、模式修订隔离及 TODO 来源标记。Mock 目录和版本须沿同一规范化类型，测试只使用虚构数据。
  - **覆盖 AC**: AC-01, AC-02, AC-04, AC-05, AC-23, AC-24, AC-25
  - _Requirements: REQ-01, REQ-02, REQ-09_
  - _Acceptance: AC-01, AC-02, AC-04, AC-05, AC-23, AC-24, AC-25_
  - _Verification: V-01, V-04, V-07，先观察契约功能缺失的失败。_
  - _Depends: T002, T003, T005, T007_

- [x] **T009** [后端 Domain] 实现 Provider 契约与 Schema 校验
  - **文件** — `src/backend/bisheng/workflow/domain/clients/platform_agent.py`、`src/backend/bisheng/workflow/domain/schemas/platform_agent.py`。
  - **工作** — 实现 `list_agents/get_version/check_use/invoke` 的类型边界、模式选择及真实未就绪占位。按设计 D6 校验 Schema 子集、输入输出和 MISSING，禁止远程引用、静默忽略约束或类型强转。真实协议假设添加 `# TODO [F119][EXT-01/EXT-02/EXT-03]`，实际注释按对应单项 EXT 分开标记。
  - _Requirements: REQ-01, REQ-02, REQ-05, REQ-09_
  - _Acceptance: AC-04, AC-05, AC-13, AC-14, AC-23, AC-25_
  - _Verification: V-01, V-04, V-07，T008 的对应契约用例。_
  - _Depends: T008_

- [x] **T010** [后端 Domain] 实现后端 Mock Provider 与样例
  - **文件** — `src/backend/bisheng/workflow/domain/clients/platform_agent_mock.py`。
  - **工作** — 提供 A／B／跨租户样例映射、Agent V1／V2、权限拒绝、不可用版本、成功输出、超时、错误输出和非终态。样例只读，可变领取和调用事实交 SQL 仓储。各来源与故障假设逐项保留 `# TODO [F119][EXT-NN]`。
  - _Requirements: REQ-01, REQ-05, REQ-06, REQ-09_
  - _Acceptance: AC-01, AC-02, AC-15, AC-16, AC-18, AC-23, AC-24_
  - _Verification: V-01, V-04, V-07，T008 验证过滤、形态、模式与标记。_
  - _Depends: T009_

- [x] **T011** [后端 Domain／测试] 编写发布及执行仓储测试
  - **文件** — `src/backend/test/workflow/test_platform_agent_repository.py`；同目录 `conftest.py` 提供非自动应用的 F119 SQL 夹具。
  - **工作** — 复用隔离 SQL 夹具，覆盖候选摘要冲突、发布回滚、原图保留、冻结快照、调度重复领取、同键异参、停止和成功提交竞争。SQLite 只验证事务结果和状态转换，真实两实例锁由 T048 补证。
  - **覆盖 AC**: AC-06, AC-07, AC-08, AC-17, AC-19
  - _Requirements: REQ-03, REQ-06_
  - _Acceptance: AC-06, AC-07, AC-08, AC-17, AC-19_
  - _Verification: V-02, V-04，先写失败用例，T012、T013 组成同一验证批次。_
  - _Depends: T002, T003, T005_

- [x] **T012** [后端 Domain] 实现发布事务及图读取仓储
  - **文件** — `src/backend/bisheng/workflow/domain/repositories/platform_agent.py`。
  - **工作** — 提供业务目标读取、`publish_validated_graph` 和版本保存／切换／删除所需短事务。统一 Flow→FlowVersion 锁序，在同一提交中核对摘要并写发布图、绑定、指针和状态。F119 离线草稿不覆盖最后发布图，外部查询在事务外完成。
  - _Requirements: REQ-01, REQ-03, REQ-08_
  - _Acceptance: AC-06, AC-07, AC-08, AC-22_
  - _Verification: V-02，T011 发布子集覆盖冲突与回滚。_
  - _Depends: T011_

- [x] **T013** [后端 Domain] 实现执行登记和发送许可仓储
  - **文件** — `src/backend/bisheng/workflow/domain/repositories/platform_agent.py`。
  - **工作** — 增量实现 `prepare_execution/claim_dispatch/reserve_call/finish_call/request_stop`。先提交发送许可再网络调用，比较 owner 和请求摘要，终态不回退。活动 Session、独立新运行、合法节点序号和恢复调度分别辨认，缺记录拒绝，旧消息不重建执行。
  - _Requirements: REQ-03, REQ-06, REQ-08_
  - _Acceptance: AC-08, AC-17, AC-19, AC-22_
  - _Verification: V-02, V-04，T011 全部状态和领取用例。_
  - _Depends: T012_

- [x] **T014** [后端 API／测试] 编写资源及校验路由测试
  - **文件** — `src/backend/test/workflow/test_platform_agent_api.py`。
  - **工作** — 覆盖现有认证依赖与 Workflow 编辑资格、租户、目录分页和空态、版本详情、无副作用的 validate，以及供发布预检复用的当前操作者权限判断。伪造身份、凭据或模式不能改变主体。Mock 使用真实本地授权检查，真实未就绪不能回落 Mock。
  - **覆盖 AC**: AC-01, AC-02, AC-03, AC-06, AC-10, AC-11, AC-12, AC-21, AC-25
  - _Requirements: REQ-01, REQ-02, REQ-04, REQ-07, REQ-09_
  - _Acceptance: AC-01, AC-02, AC-03, AC-06, AC-10, AC-11, AC-12, AC-21, AC-25_
  - _Verification: V-01, V-03, V-05, V-07，使用受控请求及仓库现有授权夹具。_
  - _Depends: T010, T013_

- [x] **T015** [后端 Domain] 实现资源和参数验证应用入口
  - **文件** — `src/backend/bisheng/workflow/domain/services/platform_agent_service.py`、`src/backend/bisheng/workflow/application/platform_agent.py`。
  - **工作** — 加载已验证 Workflow 目标并经 F048 校验当前用户，再调用统一 Provider 查询目录／版本／使用权限和验证映射。生成按节点字段定位的问题和绑定材料，游标绑定用户、租户及模式，不直接写 ORM。
  - _Requirements: REQ-01, REQ-02, REQ-04, REQ-09_
  - _Acceptance: AC-01, AC-02, AC-04, AC-05, AC-06, AC-11, AC-12, AC-23_
  - _Verification: V-01, V-03，T014 的业务资格与无副作用验证。_
  - _Depends: T014_

- [x] **T016** [后端 API] 实现三个本地资源路由
  - **文件** — `src/backend/bisheng/workflow/api/router.py`、`src/backend/bisheng/workflow/api/endpoints/platform_agent.py`。
  - **工作** — 提供 `GET /workflow/platform-agents`、版本详情 GET 和 `/workflow/platform-agents/validate` POST，路径及请求响应按设计第 6.1 节。端点使用现有用户依赖和响应封装，只委托应用入口。
  - _Requirements: REQ-01, REQ-02, REQ-04_
  - _Acceptance: AC-01, AC-02, AC-03, AC-11, AC-12_
  - _Verification: V-01, V-03，T014 的路由验证。_
  - _Depends: T015_

- [x] **T017** [后端 API] 注册路由及无秘密能力摘要
  - **文件** — `src/backend/bisheng/api/router.py`、`src/backend/bisheng/api/v1/endpoints.py`。
  - **工作** — 挂载新子路由，在 env 的 workflow 摘要公开节点可用性及 `platform_agent_mode`。API／Worker 使用共享配置修订，无节点的原路径不装配外部客户端，不返回地址、秘密或样例用户映射。
  - _Requirements: REQ-01, REQ-07, REQ-08, REQ-09_
  - _Acceptance: AC-01, AC-21, AC-22, AC-23, AC-25_
  - _Verification: V-01, V-05, V-07，Wave 1 统一执行 T008、T011、T014，记录真实运行结果。_
  - _Depends: T016_

## 5. Wave 2 Mock 节点、发布和执行

- [x] **T018** [后端 Domain／测试] 编写同步执行及输出提交测试
  - **文件** — `src/backend/test/workflow/test_platform_agent_node.py`。
  - **工作** — 使用可控 Provider 和 SQL 执行记录，覆盖真实值映射、固定版本再次校验、当前调用资格、成功输出、错误／非终态、总预算、同次发送一次、失败无输出、停止与迟到结果。覆盖 Workflow 恢复时的新调度上下文、新节点工厂注册及旧节点默认提交行为。检查实际发送次数、变量及安全事件，构造节点不能发送请求。
  - **覆盖 AC**: AC-04, AC-09, AC-11, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20, AC-21, AC-22, AC-23
  - _Requirements: REQ-02, REQ-03, REQ-04, REQ-05, REQ-06, REQ-07, REQ-08, REQ-09_
  - _Acceptance: AC-04, AC-09, AC-11, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20, AC-21, AC-22, AC-23_
  - _Verification: V-04, V-05，T019 至 T023 按同一业务批次转绿。_
  - _Depends: T017_

- [x] **T019** [后端 Domain] 实现发布预检与同步执行编排
  - **文件** — `src/backend/bisheng/workflow/domain/services/platform_agent_service.py`。
  - **工作** — 增量接发布预检、执行受理、当前本地资格和 Mock 外部身份、输入及版本 Schema 复核、发送许可、invoke 与规范化失败。成功结果留待输出提交，远端未知不推断为失败或取消。真实授权分支保持明确未就绪并保留 TODO。
  - _Requirements: REQ-03, REQ-04, REQ-05, REQ-06, REQ-09_
  - _Acceptance: AC-06, AC-09, AC-10, AC-12, AC-13, AC-15, AC-16, AC-17, AC-18, AC-23, AC-25_
  - _Verification: V-02, V-03, V-04，T018 的调用、预算及结果用例。_
  - _Depends: T018_

- [x] **T020** [后端 Domain] 实现平台 Agent 节点
  - **文件** — `src/backend/bisheng/workflow/nodes/platform_agent/platform_agent.py`、同目录 `__init__.py`。
  - **工作** — 解析 agent_ref 和 input_bindings，独立判断缺失变量，调用 T019，成功仅输出 result。实现供 T021 基类调用的受控输出作用域，构造仅做纯解析，parse_log 使用允许字段，运行元信息不混入业务变量。
  - _Requirements: REQ-02, REQ-05, REQ-07, REQ-08_
  - _Acceptance: AC-04, AC-13, AC-14, AC-20, AC-21, AC-22_
  - _Verification: V-04, V-05，T018 的构造无副作用、结果及事件断言。_
  - _Depends: T019_

- [x] **T021** [后端 Domain] 接入受控输出提交及节点上下文
  - **文件** — `src/backend/bisheng/workflow/nodes/base.py`、`src/backend/bisheng/workflow/graph/graph_engine.py`。
  - **工作** — BaseNode 增加默认空的 output_commit_scope，仅平台节点复核 owner、终态、截止时间和模式后写变量。变量或 SQL 提交失败恢复本次变量，GraphEngine 传递服务侧执行上下文，旧节点保持默认路径。
  - _Requirements: REQ-05, REQ-06, REQ-08_
  - _Acceptance: AC-13, AC-14, AC-19, AC-22_
  - _Verification: V-04, V-06，T018 的停止竞争和提交失败，相关旧节点回归。_
  - _Depends: T020_

- [x] **T022** [后端 Domain] 贯通 Workflow 执行和恢复上下文
  - **文件** — `src/backend/bisheng/workflow/graph/workflow.py`。
  - **工作** — 向图传递内部 execution 引用，恢复既有输入节点时更新 dispatch 上下文，节点不能固化旧 owner。保留运行发起人和配置作者的区别，不实现 Agent 异步恢复或通用断点重建。
  - _Requirements: REQ-03, REQ-04, REQ-06, REQ-08_
  - _Acceptance: AC-08, AC-11, AC-17, AC-19, AC-22_
  - _Verification: V-03, V-04，T018 先覆盖图级恢复上下文，T027 仅补入口和队列这一独立边界。_
  - _Depends: T021_

- [x] **T023** [后端 Domain] 注册新节点类型
  - **文件** — `src/backend/bisheng/workflow/common/node.py`、`src/backend/bisheng/workflow/nodes/node_manage.py`。
  - **工作** — 注册 platform_agent 工厂类型，既有 agent 与其他类型保留。不在模块导入或构造时初始化外部网络和凭据。
  - _Requirements: REQ-01, REQ-08_
  - _Acceptance: AC-01, AC-22_
  - _Verification: V-04, V-06，完成 T018 所属节点批次，原节点工厂相关回归。_
  - _Depends: T022_

- [x] **T024** [后端 API／测试] 编写试运行及发布版本入口回归
  - **文件** — `src/backend/test/workflow/test_platform_agent_workflow_bridge.py`。
  - **工作** — 覆盖 run_once 的完整生命周期、未完成草稿、版本更换、发布并发、离线草稿不覆盖发布图、移除最后平台节点后的保护，以及原节点成功合同。只增加测试，不改旧业务入口。
  - **覆盖 AC**: AC-03, AC-05, AC-06, AC-07, AC-08, AC-09, AC-11, AC-22
  - _Requirements: REQ-02, REQ-03, REQ-04, REQ-08_
  - _Acceptance: AC-03, AC-05, AC-06, AC-07, AC-08, AC-09, AC-11, AC-22_
  - _Verification: V-01, V-02, V-03, V-06，保留明确的前后行为断言。_
  - _Depends: T023_

- [x] **T025** [后端 API] 接通节点试运行和发布入口
  - **文件** — `src/backend/bisheng/api/services/workflow.py`。
  - **工作** — 平台节点 run_once 传当前用户及资源租户，走完整 run 和受控输出，不再仅调用 _run。发布分支调用统一预检与原子发布入口，无平台节点的路径保持原授权及响应合同。
  - _Requirements: REQ-02, REQ-03, REQ-04, REQ-08_
  - _Acceptance: AC-03, AC-06, AC-07, AC-08, AC-11, AC-22_
  - _Verification: V-01, V-02, V-03，T024 的试运行和发布子集。_
  - _Depends: T024_

- [x] **T026** [后端 API] 接通版本保存、切换与删除保护
  - **文件** — `src/backend/bisheng/api/services/flow.py`。
  - **工作** — 当前图、提交图或既有绑定任一属于 F119 时，版本操作进入共享事务。在线当前版本保持原编辑限制，离线草稿保存不覆盖最后发布图，普通旧版本逻辑和元信息资格保持。
  - _Requirements: REQ-03, REQ-08_
  - _Acceptance: AC-05, AC-07, AC-08, AC-09, AC-22_
  - _Verification: V-02, V-06，T024 全部用例，失败时旧发布内容和运行资格不变。_
  - _Depends: T025_

- [x] **T027** [Worker／测试] 编写受理、调度及身份传递测试
  - **文件** — `src/backend/test/workflow/test_platform_agent_entrypoints.py`；`test/sso/test_kunlian_ws_admission.py` 的原有身份回归补普通图读取桩，保留原断言。
  - **工作** — 覆盖开放和浏览器入口、headers 中 tenant_id 恢复、A／B 实际身份、无可信用户拒绝、override 篡改、投递失败、重复领取、恢复换 owner、旧任务不得写新 Session 运行。Mock 外部身份不能绕过本地 F048。
  - **覆盖 AC**: AC-08, AC-10, AC-11, AC-12, AC-17, AC-19, AC-20, AC-22, AC-25
  - _Requirements: REQ-03, REQ-04, REQ-06, REQ-07, REQ-08, REQ-09_
  - _Acceptance: AC-08, AC-10, AC-11, AC-12, AC-17, AC-19, AC-20, AC-22, AC-25_
  - _Verification: V-03, V-04, V-05, V-06, V-07，受控队列边界，实际 Broker 与多进程另记。_
  - _Depends: T026_

- [x] **T028** [后端 API] 接通开放运行受理
  - **文件** — `src/backend/bisheng/workflow/domain/services/published_workflow_service.py`。
  - **工作** — 通过现有认证与 Workflow use 后，校验服务端发布绑定，保存冻结图和实际用户，提交后投递 execution／dispatch 引用。拒绝覆盖平台节点，session_id 对外合同保持，投递失败明确记录。
  - _Requirements: REQ-03, REQ-04, REQ-05, REQ-08_
  - _Acceptance: AC-08, AC-10, AC-11, AC-12, AC-13, AC-22_
  - _Verification: V-03, V-06，T027 的开放入口用例。_
  - _Depends: T027_

- [x] **T029** [后端 API] 接通浏览器运行和既有输入恢复
  - **文件** — `src/backend/bisheng/common/chat/{clients/workflow_client.py,manager.py}`、`src/backend/bisheng/{api/v1/workflow.py,public_endpoints/api/endpoints/workflow.py}`、`src/backend/bisheng/workflow/application/platform_agent.py`。
  - **工作** — 含平台节点的 WS 调试／正式运行复用统一受理，使用当次已认证用户及租户。原输入恢复登记新的 dispatch，核对原运行人，因果信息继续仅用于追踪，Session 重连不自动创建第二次执行。
  - _Requirements: REQ-03, REQ-04, REQ-06, REQ-08_
  - _Acceptance: AC-08, AC-10, AC-11, AC-12, AC-17, AC-22_
  - _Verification: V-03, V-04, V-06，T027 的 WS 和恢复用例。_
  - _Depends: T028_

- [x] **T030** [Worker] 接通持久领取和执行作用域
  - **文件** — `src/backend/bisheng/worker/workflow/tasks.py`。
  - **工作** — 先恢复 Celery headers 的 tenant_id ContextVar，核对记录的租户、实际主体、会话及派发种类，再领取唯一 dispatch，复核当前 use／edit 资格后才更新 Redis 和构造图；拒绝时结束已领取执行并公开安全原因。重复消息直接结束且不改原状态，图取 SQL 快照，缺记录拒绝，恢复显式刷新 owner。
  - _Requirements: REQ-03, REQ-04, REQ-06, REQ-08_
  - _Acceptance: AC-08, AC-10, AC-11, AC-12, AC-17, AC-19, AC-22_
  - _Verification: V-03, V-04, V-06，T027 断言调用次数、ContextVar 恢复和旧任务状态不覆盖。_
  - _Depends: T029_

- [x] **T031** [Worker] 接通停止、终态及安全日志
  - **文件** — `src/backend/bisheng/worker/workflow/redis_callback.py`。
  - **工作** — F119 停止及会结束本地运行的超时先记录 SQL 事实，事件与状态绑定 execution。NodeEnd 输出安全诊断及模式，不泄漏秘密，不能让迟到或旧任务成功覆盖已结束状态。原回调路径保持兼容。
  - _Requirements: REQ-06, REQ-07, REQ-08, REQ-09_
  - _Acceptance: AC-16, AC-19, AC-20, AC-21, AC-22, AC-23_
  - _Verification: V-04, V-05, V-06，Wave 2 统一验证 T018、T024、T027 和相关旧节点回归。_
  - _Depends: T030_

## 6. Wave 3 Platform 与 Mock 主流程交付

- [x] **T032** [前端 Platform] 增加 API、节点模板和类型
  - **文件** — `src/frontend/platform/src/controllers/API/workflow.ts`、`src/frontend/platform/src/types/flow/index.ts`。
  - **工作** — 增加资源、版本和 validate API 封装及 platform_agent 模板，定义绑定、问题和 result 类型。沿用请求封装，产品代码不内置资源成功列表或模拟执行结果。
  - _Requirements: REQ-01, REQ-02, REQ-09_
  - _Acceptance: AC-01, AC-03, AC-04, AC-23_
  - _Verification: V-01，后续组件测试消费这些类型与真实 API 层形态。_
  - _Depends: T017, T031_

- [x] **T033** [前端 Platform／测试] 编写节点配置行为测试
  - **文件** — `src/frontend/platform/src/pages/BuildPage/flow/FlowNode/component/PlatformAgentItem.test.tsx`。
  - **工作** — 使用接口固定响应验证资源与版本选择、空值 ID 过滤、草稿重开、常量／变量及零值、更换不兼容版本、身份或租户变更后缓存隔离，以及“模拟数据”展示。组件测试桩不进入产品运行代码。
  - **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-20, AC-23
  - _Requirements: REQ-01, REQ-02, REQ-07, REQ-09_
  - _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-05, AC-20, AC-23_
  - _Verification: V-01, V-05，现有 Platform Vitest。_
  - _Depends: T032_

- [x] **T034** [前端 Platform] 实现平台 Agent 参数组件
  - **文件** — `src/frontend/platform/src/pages/BuildPage/flow/FlowNode/component/PlatformAgentItem.tsx`、`src/frontend/platform/src/pages/BuildPage/flow/FlowNode/Parameter.tsx`。
  - **工作** — 使用已落地共享控件选择 Agent／版本、展示 Schema、配置类型明确的常量或变量及整体对象／数组，展示缺项和兼容性问题。查询键绑定身份、租户、模式和修订，旧资源不静默改选。
  - _Requirements: REQ-01, REQ-02, REQ-09_
  - _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-05, AC-23_
  - _Verification: V-01，T033 的核心选择及映射用例。_
  - _Depends: T033_

- [x] **T035** [前端 Platform] 接通变量引用和侧栏能力
  - **文件** — `src/frontend/platform/src/util/flowUtils.ts`、`src/frontend/platform/src/pages/BuildPage/flow/Sidebar.tsx`。
  - **工作** — 识别 result 整体及可支持的一级字段／索引，版本更换后重新校验引用。侧栏按后端能力显示新节点和 Mock 标记，禁用时阻止新增，旧节点菜单保持。
  - _Requirements: REQ-01, REQ-02, REQ-08, REQ-09_
  - _Acceptance: AC-01, AC-04, AC-05, AC-22, AC-23_
  - _Verification: V-01, V-06，T033 及已有变量引用相关回归。_
  - _Depends: T034_

- [x] **T036** [前端 Platform] 接通节点试运行和结果日志
  - **文件** — `src/frontend/platform/src/pages/BuildPage/flow/FlowNode/RunTest.tsx`、同目录 `RunLog.tsx`。
  - **工作** — 收集真实类型输入，调用既有试运行入口，保留完整错误。显示 result、模式、版本和允许的关联信息，超时使用远端结果未知表述，未通过校验不触发运行。HTTP 失败不触发成功后的界面行为。
  - _Requirements: REQ-02, REQ-05, REQ-06, REQ-07, REQ-09_
  - _Acceptance: AC-03, AC-04, AC-13, AC-15, AC-16, AC-20, AC-21, AC-23_
  - _Verification: V-01, V-05, V-06，T033 与 T039 运行界面证据。_
  - _Depends: T035_

- [x] **T037** [前端 Platform] 补节点标识及英文文案
  - **文件** — `src/frontend/platform/src/pages/BuildPage/flow/FlowNode/NodeLogo.tsx`、`src/frontend/platform/public/locales/en-US/flow.json`。
  - **工作** — 使用现有图标能力识别新节点，补资源、版本、映射、模拟来源及失败说明的英文键，界面不展示认证内部字段。
  - _Requirements: REQ-01, REQ-07, REQ-09_
  - _Acceptance: AC-01, AC-20, AC-21, AC-23_
  - _Verification: V-01, V-05，键引用及图标渲染检查。_
  - _Depends: T036_

- [x] **T038** [前端 Platform] 补中文和日文并完成静态门禁
  - **文件** — `src/frontend/platform/public/locales/zh-Hans/flow.json`、`src/frontend/platform/public/locales/ja/flow.json`。
  - **工作** — 与 T037 保持键一致，说明模拟数据、缺项、版本问题及未知结果。修复本批新增 lint／typecheck 问题，保持新文件无严格检查豁免。
  - _Requirements: REQ-01, REQ-06, REQ-07, REQ-09_
  - _Acceptance: AC-01, AC-15, AC-16, AC-20, AC-21, AC-23_
  - _Verification: V-01, V-05, V-06，统一执行组件测试、前端 lint、typecheck 及三语检查，复用同状态证据。_
  - _Depends: T037_

- [ ] **T039** [后端 API／测试] 补齐并执行 Mock 最小流程 E2E
  - **当前状态** — PARTIAL：脚本和手动清单已编写；运行得到 1 skipped（NOT_RUN），正常 API／Broker／Worker 联验待执行。
  - **文件** — `src/backend/test/workflow/test_platform_agent_e2e.py`，必要时增补同目录 `conftest.py` 的局部夹具。
  - **工作** — 按项目 e2e-test 流程，经正常认证、资源查询、草稿、发布和运行入口执行最小图。外部 Agent 使用 Mock，本地授权及队列执行须如实区分。验证 A 发布／B 运行、V1 固定、下游类型和一条拒绝或超时。实际 API／Broker／Worker 未具备时记录 NOT_RUN，不能用内联调用冒充该边界通过。
  - **覆盖 AC**: AC-03, AC-08, AC-10, AC-13, AC-15, AC-20, AC-22, AC-23
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-04, REQ-05, REQ-06, REQ-07, REQ-08, REQ-09_
  - _Acceptance: AC-03, AC-08, AC-10, AC-13, AC-15, AC-20, AC-22, AC-23_
  - _Verification: V-06，记录端到端实际环境、调用标识和结果。_
  - _Depends: T038_

- [ ] **T040** [集成交付] 交付 Mock 示例与验证记录
  - **当前状态** — PARTIAL：示例、source-state.json 和验证记录已交付，进程内图执行通过；依赖 T039 的正常环境验收待执行，不提前勾选。
  - **文件** — 本目录 `mock-workflow.example.json`、`verification.md`；补充 `source-state.json`、`e2e-checklist.md`、`code-review.md` 保存源码状态及阶段检查。
  - **工作** — 提供可由正常产品入口使用的最小图，Agent／身份均明确为 Mock。汇总批次实际命令、代码状态、结果和未执行边界，登记 TODO 位置与 EXT 的对应关系，分别说明 Mock 开发完成度及真实联调缺口。
  - _Requirements: REQ-05, REQ-07, REQ-08, REQ-09_
  - _Acceptance: AC-13, AC-20, AC-22, AC-23, AC-24, AC-25_
  - _Verification: V-06, V-07，示例可用性、证据可追溯及所有临时来源标记。_
  - _Depends: T039_

### M-MOCK 阶段验收

T040 后执行特性阶段审查，按项目 sdd-code-review 核对已实现的 Mock 范围，复用上述成功证据。补充必需的浏览器手动检查，问题修复后只重跑受影响验证。确认实际用户、版本固定、失败阻断、重复发送和秘密保护均有证据后，才能记 Mock 开发阶段完成。T041 至 T050 的未就绪项继续待执行，阶段审查不触发部署或将真实验收记为通过。

## 7. Wave 4 真实接口替换

本批当前状态均为 WAITING_EXTERNAL。收到对应合同和实施授权后再执行，Mock 交付不依赖本批完成。TODO 只有在正式来源已接入且对应验证有证据后才关闭。

- [ ] **T041** [接口契约] 固化正式合同与替换映射
  - **文件** — 本目录 `design.md`、`src/backend/test/workflow/fixtures/kunlian-agent-contract.json`。
  - **工作** — 记录正式目录／版本／invoke、鉴权和同步语义，提供脱敏且无真实凭据的契约样例。逐项核对 EXT、现有内部类型及 TODO。新合同超出已确认范围时按既有 SDD 偏差规则处理，不能直接扩大功能。
  - _Requirements: REQ-01, REQ-03, REQ-04, REQ-05, REQ-06, REQ-09_
  - _Acceptance: AC-06, AC-09, AC-10, AC-13, AC-16, AC-24, AC-25_
  - _Verification: V-03, V-04, V-07，正式合同及样例可追溯，当前 WAITING_EXTERNAL。_
  - _Depends: T040_
  - _Boundary: 依赖 EXT-01、EXT-02、EXT-03、EXT-04。EXT-05 仅在涉及嵌套时适用。_

- [ ] **T042** [后端 Domain／测试] 编写 F118 限用途授权测试
  - **文件** — `src/backend/test/sso/test_kunlian_agent_authorization.py`。
  - **工作** — 覆盖当前用户／租户、会话撤销、Token 到期、目标用途和受众、目录资格、停用、网络后复核及秘密隔离，以及 API／Worker 按连接修订装配。客户端提供的会话哈希或因果字段不能直接变成调用授权。测试只使用模拟 IDP 和虚构秘密。
  - **覆盖 AC**: AC-10, AC-11, AC-12, AC-21, AC-25
  - _Requirements: REQ-04, REQ-07, REQ-08, REQ-09_
  - _Acceptance: AC-10, AC-11, AC-12, AC-21, AC-25_
  - _Verification: V-03, V-05, V-07，先验证不可信及失效条件被拒绝。_
  - _Depends: T041_

- [ ] **T043** [后端 Domain] 增加 F118 内部会话事实读取
  - **文件** — `src/backend/bisheng/sso_sync/domain/repositories/kunlian.py`。
  - **工作** — 只在 F118 Owner 内封装按执行绑定引用读取当前会话和身份事实的能力，核对预期用户、租户及绑定。Workflow 不直接访问这些表，不新增面向浏览器的哈希查询接口。
  - _Requirements: REQ-04, REQ-07, REQ-08_
  - _Acceptance: AC-10, AC-11, AC-12, AC-21_
  - _Verification: V-03，T042 的事实和失效用例，复用相关 F118 仓储回归。_
  - _Depends: T042_

- [ ] **T044** [后端 Domain] 实现内部限用途授权端口
  - **文件** — `src/backend/bisheng/sso_sync/application/agent_authorization.py`、`src/backend/bisheng/sso_sync/domain/services/kunlian_session.py`。
  - **工作** — 实现 AgentAuthorizationPort，复用当前资格、会话和在线内省，在受控目标用途内给适配器提供单次秘密材料。浏览器准入的 HTTP／WS 合同保持，拒绝过期或错主体，不增加刷新、Token Exchange 或创建者代用路径。
  - _Requirements: REQ-04, REQ-07, REQ-08_
  - _Acceptance: AC-10, AC-11, AC-12, AC-21, AC-25_
  - _Verification: V-03, V-05，T042 全部用例及相关原有会话拒绝路径。_
  - _Depends: T043_

- [ ] **T045** [后端 Domain] 装配 API 与 Worker 的授权适配
  - **文件** — `src/backend/bisheng/sso_sync/application/runtime.py`。
  - **工作** — 各进程按当前连接和修订显式装配受限端口，不能依赖 FastAPI 独有生命周期或缓存允许结果，秘密只通过既有安全解析器取得。Mock 运行不要求真实 F118 Token。
  - _Requirements: REQ-04, REQ-08, REQ-09_
  - _Acceptance: AC-10, AC-11, AC-12, AC-21, AC-22, AC-25_
  - _Verification: V-03, V-07，T042 的装配及秘密隔离，相关 F118 HTTP／WS／Worker 回归。_
  - _Depends: T044_

- [ ] **T046** [后端 Domain／测试] 编写真正 HTTP 契约映射测试
  - **文件** — `src/backend/test/workflow/test_platform_agent_http_client.py`。
  - **工作** — 依据 T041 样例，通过受控 HTTP 传输断言目录和版本字段、授权注入、实际版本、终态、流量限制、总预算、重定向拒绝、无 POST 重试及脱敏。传输桩通过不计真实昆联联调通过。
  - **覆盖 AC**: AC-09, AC-13, AC-14, AC-15, AC-16, AC-18, AC-21, AC-25
  - _Requirements: REQ-03, REQ-04, REQ-05, REQ-06, REQ-07, REQ-09_
  - _Acceptance: AC-09, AC-13, AC-14, AC-15, AC-16, AC-18, AC-21, AC-25_
  - _Verification: V-03, V-04, V-05, V-07，验证正式报文映射与拒绝边界。_
  - _Depends: T045_

- [ ] **T047** [后端 Domain] 替换真实目录、invoke 和授权接线
  - **文件** — `src/backend/bisheng/workflow/domain/clients/platform_agent.py`、`src/backend/bisheng/workflow/domain/services/platform_agent_service.py`。
  - **工作** — 将真实占位替换为已确认 HTTP 映射和 T045 授权端口，固定服务端目标，限制总预算及响应大小，先确认当前 Schema 和版本，明确未知结果。模式或修订不符拒绝，真实错误不返回 Mock，未验证的 TODO 继续保留。
  - _Requirements: REQ-01, REQ-03, REQ-04, REQ-05, REQ-06, REQ-09_
  - _Acceptance: AC-01, AC-09, AC-10, AC-12, AC-13, AC-14, AC-15, AC-16, AC-18, AC-24, AC-25_
  - _Verification: V-03, V-04, V-07，T046 及共享 Provider 契约回归。_
  - _Depends: T046_

## 8. Wave 5 真实环境验证，待执行

本批状态为 NOT_RUN。环境、凭据和测试数据须已获授权并隔离，执行结果填入验证记录，不能借机部署、迁移历史账号或修改无关授权。只完成脚本时，实际环境验证继续未完成。

- [ ] **T048** [集成／测试] 验证真实存储和跨实例竞争
  - **文件** — `src/backend/test/workflow/test_platform_agent_storage_e2e.py`、本目录 `verification.md`。
  - **工作** — 在受控 MySQL／DM8、Redis 和至少两个执行实例中验证新表发现、租户隔离、并发发布回滚、唯一领取、发送前提交后崩溃及停止竞争，留存实际发送次数。可使用 Mock Agent 隔离外部依赖，DM8 在具备驱动的环境执行。
  - **覆盖 AC**: AC-07, AC-08, AC-17, AC-19
  - _Requirements: REQ-03, REQ-06, REQ-08_
  - _Acceptance: AC-07, AC-08, AC-17, AC-19_
  - _Verification: V-02, V-04，当前 NOT_RUN，缺 ENV-DB 时标记待执行。_
  - _Depends: T040_

- [ ] **T049** [集成／测试] 验证真实昆联 API／Worker 闭环
  - **文件** — `src/backend/test/workflow/test_platform_agent_e2e.py`、本目录 `verification.md`。
  - **工作** — 将 T039 的同一流程扩展为明确的真实环境模式，使用正式测试版本与身份跑 A 发布／B 运行、下游输出、拒绝、版本固定及约定失败。核对双方审计中的实际用户及 Agent Run，记录 F118 真实资格前置证据，禁止模拟结果混入。
  - **覆盖 AC**: AC-10, AC-11, AC-12, AC-13, AC-16, AC-21, AC-25
  - _Requirements: REQ-03, REQ-04, REQ-05, REQ-06, REQ-07, REQ-09_
  - _Acceptance: AC-10, AC-11, AC-12, AC-13, AC-16, AC-21, AC-25_
  - _Verification: V-03, V-04, V-06, V-07，当前 NOT_RUN，需 EXT-04、ENV-DB、ENV-IDENTITY。_
  - _Depends: T047, T048_

- [ ] **T050** [集成／测试] 完成真实浏览器验收和最终证据复核
  - **文件** — 本目录 `verification.md`、`code-review.md`。
  - **工作** — 经真实浏览器核对配置重开、版本更换、A／B、到期拒绝、Mock／真实来源展示及安全日志。按 e2e-test 和 sdd-code-review 汇总已有证据及剩余风险，验证禁用和兼容版本回退说明，不能将缺环境项记为通过。
  - **覆盖 AC**: AC-03, AC-08, AC-10, AC-20, AC-21, AC-25
  - _Requirements: REQ-01, REQ-03, REQ-04, REQ-07, REQ-08, REQ-09_
  - _Acceptance: AC-03, AC-08, AC-10, AC-20, AC-21, AC-25_
  - _Verification: V-01, V-03, V-05, V-06, V-07，当前 NOT_RUN，真实验收与本地历史结果分别列示。_
  - _Depends: T049_

## 9. 验收覆盖与批次证据

以下为验证分组，实际状态均为 NOT_RUN。每条 AC 的精确追溯以任务元数据为准。

| Verification | 主要测试任务 | 目标 |
| --- | --- | --- |
| V-01 | T008、T014、T024、T033 | 目录、版本、配置、类型及草稿。 |
| V-02 | T011、T024、T048 | 发布事务、并发及冻结图，真实 DB 单列。 |
| V-03 | T014、T027、T042、T046、T049 | 可信主体、本地资格、外部授权及真实审计。 |
| V-04 | T008、T011、T018、T027、T046、T048、T049 | 调用、输出、预算、去重和停止。 |
| V-05 | T014、T018、T027、T033、T042、T046、T050 | 状态、日志、关联和秘密保护。 |
| V-06 | T024、T027、T039、T049、T050 | 最小流程、正常入口及旧节点兼容。 |
| V-07 | T008、T014、T027、T042、T046、T049、T050 | TODO、模式隔离、契约替换和证据区分。 |

实施首批结束即创建 verification.md，后续各批次追加实际证据，T040 汇总而不重写历史结果。记录命令、执行环境、对应代码状态、结果、使用的契约样例、跳过原因及关联 ID。架构守卫逐修改文件执行，前端门禁按受影响范围执行，相关代码变化后只使对应证据失效。

Mock 阶段完成允许独立报告。完整首批真实验收完成仍要求真实身份、真实调用、存储并发及浏览器证据闭合。无部署、提交推送或历史数据处理任务。

## 10. 实际偏差与规划审查

### 2026-11-05 审查修复批次

- [x] **R8**：修复用户反馈的 Agent 目录空白。兼容 leaf_tenant_id 与无租户字段的单租户用户，能力查询先于目录身份判断；多租户身份缺失时明确提示并阻断。目录／版本继续走真实后端入口，Mock 样例提供直观名称，不在前端填造目录。_Requirements: REQ-01、REQ-04、REQ-09；Acceptance: AC-01、AC-02、AC-23、AC-25；Verification: V-01、V-03、V-07，E-020：前端 11 passed、后端定向 34 passed，前端门禁通过；浏览器验收仍待执行。_

- [x] **R7**：按用户要求默认启用 Mock，无需额外配置即可展示节点、查询通用样例并试运行；空映射使用通用 B 样例，自定义映射仍严格限制。本地身份、租户、Workflow 授权及显式 disabled／real 行为保持。_Requirements: REQ-01、REQ-04、REQ-09；Acceptance: AC-01、AC-12、AC-23、AC-25；Done: 默认目录与完整 Mock 示例通过，显式来源和拒绝回归通过，更新文档与验证记录；Verification: V-01、V-03、V-06、V-07，E-019：153 passed、1 skipped。_

- [x] R6：修复用户反馈的 API 首次导入循环依赖；仅替换平台节点的异步桥接，增加无预加载的独立进程导入回归，复验节点、预算和既有桥接行为。Python 3.11 相关回归 148 passed、1 skipped，当前 Python 3.14 独立导入 2 passed，见 E-018。缺环境验收仍待执行，不修改虚拟环境、不部署。

- [x] R1：T019、T025 补齐调试／试运行的临时 Schema 绑定，覆盖受理后同版本漂移，复用既有试运行回归。E-014。
- [x] R2：T027、T030、T031 补齐排队后拒绝、构造和恢复失败终态，以及旧派发隔离与错误脱敏；恢复输入失败中止、登录失效在写入前拒绝。E-014。
- [x] R3：T033、T034 允许明确移除旧映射／可选输入，合法常量随编辑保存，执行组件与静态门禁。E-015。
- [x] R4：统一更新审查、验证和源码状态；T039、T040 与真实环境任务保持待执行。E-016、E-017。
- [x] R5：T029 的浏览器平台领域调用收回应用端口，由登录及公开 Workflow 路由传入、ChatManager 透传；补齐构造边界、正式图和普通流程回归，common 不新增 F119 领域依赖。E-014、E-016。

### 实际偏差

已实施 T001—T038。T039 脚本、T040 示例及记录已落地，正常 API／Broker／Worker 未具备，保留未勾选和 NOT_RUN；阶段验收未通过。为支持既有 run_once／发布入口的新错误 HTTP 状态，在 main.py 增加仅针对 PlatformAgentError 的映射；补充同目录共享 SQL 夹具，并更新一条 F118 回归夹具的服务端图读取桩。上述均为已确认行为的接线细节，未修改既有权限动作或真实配置，未执行真实建表、数据迁移或部署。实现细节及审查结果见 design.md 和 verification.md。

### 规划审查

按项目 tasks 审查清单执行规划自审。规划时 50 项任务均未勾选；实施后按实际证据更新，需求／AC 引用保持不变。25 条 AC 均有测试任务覆盖，后端行为测试排在对应实现前，基础设施遵循模板的优先规则。任务按一至两个源文件划分，T007 的额外文件为既有命令的机械生成件。

Mock TODO 是用户明确授权的对接替换要求，本地正确性工作没有延期到 TODO。真实接口和真实环境验证分别受外部门禁约束，全部保留未执行状态。文档静态检查与计划审查通过只表示任务规划可供实施，不表示业务测试或端到端验证已通过。
