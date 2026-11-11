# Tasks 昆联 Workflow 管理入口与发布登记

- **Feature ID**: F121（合入前复核）
- **Status**: MOCK_IMPLEMENTED
- **Mode**: IMPLEMENT_MOCK
- **Updated**: 2026-11-10（Asia/Shanghai）
- **管理页补充** · T026–T034 已实施并通过本地 Mock 验证，T035–T036 真实环境待执行。
- **关联**: [规格](./spec.md)、[设计](./design.md)、[版本契约](../release-contract.md)。

## 1. 状态与范围

| 阶段 | 状态 | 说明 |
| --- | --- | --- |
| 规格与设计 | CONFIRMED | 首轮复用毕昇画布和管理接口，昆联主动拉取发布与下线变化。 |
| 任务规划 | CONFIRMED | 用户授权 T001–T021、T026–T034。 |
| 实现 | PARTIAL | T001–T021 本地实施与 Mock 验证完成，21 / 25。T022–T025 保持待执行。 |
| 工作流管理页补充 | MOCK_VERIFIED | T026–T034 已完成，分批验收见 §6 与验证记录 E-012 至 E-016。 |
| 管理页真实验证 | NOT_RUN | T035–T036 覆盖真实数据库、OpenFGA 和昆联 SSO。 |
| 双方合同 | WAITING_EXTERNAL | EXT-01 至 EXT-05 按任务解除。 |
| 环境验证 | NOT_RUN | 真实数据库、权限、浏览器和昆联同步待执行。 |

T001–T021 和 T026–T034 在工作区完成本地验证，复用既有画布、F118、F048、F119／F120 和开放平台的职责边界。候选接口由隔离测试应用装配，正式合同和真实环境验证分别待执行。证据见 [verification.md](./verification.md)。

路径前缀均相对仓库根目录。`B/` 为 `src/backend/bisheng/`，`BT/` 为 `src/backend/test/workflow/`，`P/` 为 `src/frontend/platform/src/`，`F/` 为本特性目录。

| 批次 | 任务 | 可观察交付 |
| --- | --- | --- |
| W0 基础 | T001–T003 | 范围、内部合同及持久结构，集成默认关闭。 |
| W1 管理入口 | T004–T008 | 创建可重试、实际用户可见列表、草稿冲突和画布复用。 |
| W2 发布事实 | T009–T014 | 固定版本资料、原子发布与下线、旧路径保护、实时可用性。 |
| W3 拉取与补偿 | T015–T019 | 授权全量和增量、游标断点、回执及安全接口。 |
| W4 本地闭环 | T020–T021 | 毕昇显示登记结果，模拟昆联消费者验收完整流程并记录证据。 |
| W5 合同与环境 | T022–T025 | 正式身份与报文，真实中间件、双系统和回退验收。 |

## 2. 本地实现与验证

### W0 基础

- [x] **T001** [基础设施] 登记特性和启用边界
  - 在 `features/v3.0.0/release-contract.md` 登记 F121、Workflow 领域归属及依赖，复核编号和开放平台错误码。登记默认关闭、按连接／租户显式纳入、回退时先关闭可用性再停同步的边界。检查既有 F048 权限和 F118 会话合同，收集登记范围内可能变更 `Flow`／`FlowVersion` 的入口。
  - _Requirements: REQ-01, REQ-06, REQ-08, REQ-10_
  - _Acceptance: AC-02, AC-06, AC-10, AC-11_
  - _Verification: V0 检查编号、范围、错误分配和入口清单。_
  - _Depends: 无_

- [x] **T002** [基础设施] 定义本地开发合同
  - 在 `B/workflow/domain/schemas/kunlian_registration.py` 定义版本资料、变化、登记结果及安全错误边界，支持固定版本 ID、变化顺序和独立登记状态。候选接口字段作为本地夹具，正式命名、Schema 方言和凭据受 EXT-01／02／03 约束。
  - _Requirements: REQ-06, REQ-07, REQ-09, REQ-10_
  - _Acceptance: AC-06, AC-08, AC-10, AC-12_
  - _Verification: V0 检查字段白名单、状态与错误合同，行为证据见 V-03。_
  - _Depends: T001_

- [x] **T003** [基础设施] 落持久事实与索引
  - 在 `B/workflow/domain/models/kunlian_registration.py` 和需要的模型发现落点定义创建请求进度、版本资料及登记状态、连接／租户流控制行和变化明细。约束创建幂等键、版本键、作用域序号及回执归属，核对租户自动隔离与 MySQL／DM8 可用索引。回退保留新增事实，关闭接入后走原流程。真实建表或迁移另行确认。
  - _Requirements: REQ-02, REQ-06, REQ-07, REQ-09_
  - _Acceptance: AC-03, AC-08, AC-10, AC-11, AC-12_
  - _Verification: V0 模型发现与双数据库静态检查，运行证据由 T024 补齐。_
  - _Depends: T001, T002_

### W1 管理入口

- [x] **T004** [测试／后端] 编写管理入口及创建恢复用例
  - 在 `BT/test_kunlian_workflow_management.py` 覆盖安全回跳和伪造身份、同键重试和同键异参、配额和所有者投影失败、A／B 可见及撤权、草稿并发冲突。用既有测试夹具控制身份、权限与失败点。
  - **覆盖 AC: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07**。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-04, REQ-10_
  - _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07_
  - _Verification: V-01、V-02。浏览器证据另记。_
  - _Depends: T002, T003_

- [x] **T005** [后端应用] 接入可重试创建
  - 在 `B/api/v1/workflow.py` 和 `B/workflow/application/kunlian_workflow_creation.py` 为现有创建入口接逻辑请求标识。首次提交持久化稳定对象及进度，继续复用创建资格、配额、初始版本和 F048 所有者投影。同键重试恢复原对象，投影未完成时不返回创建成功。
  - _Requirements: REQ-02, REQ-10_
  - _Acceptance: AC-03, AC-04_
  - _Verification: V-02 复用 T004 创建与失败断言。_
  - _Depends: T003, T004_

- [x] **T006** [后端应用] 复用可见列表和详情
  - 在 `B/workflow/application/kunlian_workflow_management.py` 及 `B/api/services/flow.py` 收口已有列表和详情的业务读取。按真实用户查询 `visible` 范围，返回裁剪摘要及分别判定的编辑、发布和下线动作。浏览器详情读取登记摘要前校验同一业务目标。模拟委托仅经测试注入。
  - _Requirements: REQ-01, REQ-03, REQ-10_
  - _Acceptance: AC-02, AC-05, AC-06_
  - _Verification: V-02 复用 T004 身份、越权和撤权断言。_
  - _Depends: T002, T004_

- [x] **T007** [后端应用] 接草稿修订及版本保护
  - 在 `B/api/services/flow.py` 及版本仓储落点复用版本读写，给接入流程按预期修订保存。检查编辑权限、归属、在线及历史登记版本的不可覆盖约束，冲突返回可识别错误。为 T012 提供同一候选摘要及修订语义。
  - _Requirements: REQ-03, REQ-04, REQ-05_
  - _Acceptance: AC-05, AC-07, AC-09_
  - _Verification: V-02 复用 T004 冲突与无权场景，发布阶段复验冻结保护。_
  - _Depends: T003, T004_

- [x] **T008** [前端 Platform] 复用新建和画布入口
  - 在 `P/pages/BuildPage/` 及 `P/controllers/API/workflow.ts` 接创建标识、草稿修订和冲突提示，沿用 `/flow/:id/`、创建组件和既有请求封装。用现有安全回跳规则验证临时入口。正式 Origin、网关允许项和昆联页面分工由 T022／T023 对接。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-04_
  - _Acceptance: AC-01, AC-02, AC-03, AC-05, AC-07_
  - _Verification: V-01 验证回跳、重复提交及冲突提示，运行现有 Platform 质量检查。_
  - _Depends: T005, T006, T007_

### W2 发布事实

- [x] **T009** [测试／后端] 编写发布与状态路径回归
  - 在 `BT/test_kunlian_workflow_publication.py` 验证图、状态、资料和变化同成同败，覆盖无权、无效版本、候选并发保存、并发提交顺序、旧入口下线、解除登记与删除、旧回执及 V2 替换 V1。复用 F119／F120 夹具检查混合图。
  - **覆盖 AC: AC-05, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12**。
  - _Requirements: REQ-03, REQ-04, REQ-05, REQ-06, REQ-07, REQ-08, REQ-09_
  - _Acceptance: AC-05, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12_
  - _Verification: V-02、V-03。受控夹具与真实数据库的证据分开。_
  - _Depends: T003, T007_

- [x] **T010** [后端 Domain] 生成固定版本登记资料
  - 在 `B/workflow/domain/services/kunlian_descriptor.py` 将发布候选、输入输出声明及已有外部绑定转为工具描述和依赖摘要。保留原版本 ID 和摘要，校验缺字段和不支持的输出形态。资料不完整时记录待补充，裁剪所有非白名单字段。
  - _Requirements: REQ-05, REQ-06, REQ-09, REQ-10_
  - _Acceptance: AC-08, AC-09, AC-10, AC-12_
  - _Verification: V-03 复用 T009 固定版本、资料不足和脱敏用例。_
  - _Depends: T002, T009_

- [x] **T011** [后端 Repository] 实现同事务变化写入
  - 在 `B/workflow/domain/repositories/kunlian_registration.py` 提供共享提交路径，按设计的锁顺序复核版本及摘要、分配流内序号、写入发布资料和变化。下线及替换保留不可用事实，提交失败整体回滚，已下线的同版重新发布产生新变化。
  - _Requirements: REQ-05, REQ-06, REQ-07, REQ-08, REQ-09_
  - _Acceptance: AC-08, AC-09, AC-11, AC-12_
  - _Verification: V-02、V-03 复用 T009 回滚、排序和发布变化用例。_
  - _Depends: T003, T009, T010_

- [x] **T012** [后端应用] 复用发布和下线主入口
  - 在 `B/api/services/workflow.py` 和现有平台节点发布协调落点接 T011。事务外沿用图和 F119／F120 资源预检，事务内核对修订、摘要、登记范围及环境版本。原有动作权限和普通流程分支继续工作。
  - _Requirements: REQ-04, REQ-05, REQ-06, REQ-08, REQ-09_
  - _Acceptance: AC-07, AC-08, AC-09, AC-11, AC-12_
  - _Verification: V-02、V-03 复用 T009，包含普通流程及混合图回归。_
  - _Depends: T007, T009, T011_

- [x] **T013** [后端 API] 收口状态捷径与删除入口
  - 在 `B/api/v1/workflow.py` 与 `B/api/v1/flows.py` 将登记范围内的状态变化送入 T012。删除路径按原删除授权处理，先使版本不可用并保留可拉取记录。用 T007 的保护复查版本切换和删除，阻止旧入口覆盖登记中的快照。
  - _Requirements: REQ-04, REQ-05, REQ-07, REQ-08_
  - _Acceptance: AC-07, AC-09, AC-11_
  - _Verification: V-02、V-03 验证其他入口无法绕过发布记录与下线状态。_
  - _Depends: T007, T009, T012_

- [x] **T014** [后端应用] 提供版本权威可用性判定
  - 在 `B/workflow/application/kunlian_registration.py` 用已验证主体及指定版本读取登记资料和当前事实。无权或资料不足时拒绝，旧版本、下线或失效范围返回安全不可用状态。判定留给登记和未来反向调用消费。
  - _Requirements: REQ-06, REQ-08, REQ-09, REQ-10_
  - _Acceptance: AC-06, AC-10, AC-11, AC-12_
  - _Verification: V-03 用 T009 验证下线后、旧版本和失权路径。_
  - _Depends: T009, T011, T013_

### W3 拉取与补偿

- [x] **T015** [测试／后端] 编写拉取、权限与回执合同用例
  - 在 `BT/test_kunlian_workflow_registration_sync.py` 覆盖游标篡改、跨范围、凭据轮换、窗口失效、全量扫描期间变化、乱序和重复、失权、失败回执及旧成功回执。验证同步身份读取范围与用户接口隔离。
  - **覆盖 AC: AC-06, AC-10, AC-11, AC-12**。
  - _Requirements: REQ-06, REQ-07, REQ-08, REQ-09, REQ-10_
  - _Acceptance: AC-06, AC-10, AC-11, AC-12_
  - _Verification: V-03。崩溃重放和目录切换跨端证据由 T021 补齐。_
  - _Depends: T002, T014_

- [x] **T016** [后端 Domain] 实现独立游标和分页令牌
  - 在 `B/workflow/domain/services/kunlian_registration_cursor.py` 分开持久游标、窗口令牌及全量分页令牌。绑定消费组、连接、租户、范围世代和接口版本，校验完整性与保留点。凭据换发保持消费身份连续，失权和过期按合同拒绝或要求重扫。
  - _Requirements: REQ-07, REQ-08, REQ-10_
  - _Acceptance: AC-06, AC-11_
  - _Verification: V-03 复用 T015 范围、过期和游标断言。_
  - _Depends: T015_

- [x] **T017** [后端应用] 提供全量扫描与有界增量
  - 在 `B/workflow/application/kunlian_registration.py` 及 T011 仓储增量接入 `snapshot`、`changes`。同一权威提交视图读取 `B`、`H`、稳定扫描页和有序变化。保留必要下线及替换记录，跟踪保留点及全量扫描有效期。扫描基准失去保留条件时返回重建状态。按授权范围返回最小资料。
  - _Requirements: REQ-06, REQ-07, REQ-08, REQ-09_
  - _Acceptance: AC-10, AC-11, AC-12_
  - _Verification: V-03 用 T015 核对断点、并发变化与漏消息对账。_
  - _Depends: T011, T015, T016_

- [x] **T018** [后端应用] 记录幂等回执和登记进度
  - 在 `B/workflow/application/kunlian_registration.py` 及 T011 仓储校验回执主体、事件、版本和来源序号。登记结果与发布状态分开，并通过 T006 的读取边界提供摘要。回执重放无副作用，旧状态不能覆盖新状态，同次失败后允许补偿成功。
  - _Requirements: REQ-07, REQ-08, REQ-09, REQ-10_
  - _Acceptance: AC-06, AC-10, AC-11, AC-12_
  - _Verification: V-03 复用 T015 回执、乱序和失败补偿断言。_
  - _Depends: T011, T015, T017_

- [x] **T019** [后端 API] 接入候选读写接口及安全错误
  - 在 `B/open_endpoints/api/endpoints/` 与开放平台入口注册候选只读管理、全量、增量、版本资料和回执路由，委托已完成的应用服务。候选接口仅用于本地契约测试，生产默认关闭。按 T001 预留口径完成错误与三语文案，用现有生成流程更新共享文案产物。
  - _Requirements: REQ-01, REQ-03, REQ-06, REQ-07, REQ-08, REQ-10_
  - _Acceptance: AC-02, AC-05, AC-06, AC-10, AC-11_
  - _Verification: V-02、V-03 复用 T004 与 T015，确认默认关闭和错误安全。_
  - _Depends: T001, T004, T006, T014, T015, T017, T018_

### W4 本地闭环

- [x] **T020** [前端 Platform] 展示发布和登记结果
  - 在 `P/pages/BuildPage/flow/` 的既有发布区域及 `P/controllers/API/workflow.ts` 读取 T006／T018 的登记摘要，分开显示毕昇发布状态及昆联待同步、已同步、失败待补偿状态。沿用原发布／下线操作和既有文案规范，详情随当前权限重新读取。
  - _Requirements: REQ-03, REQ-06, REQ-07, REQ-08, REQ-10_
  - _Acceptance: AC-05, AC-10, AC-11_
  - _Verification: V-01、V-03 验证状态分离、失败提示和下线后旧回执不使界面恢复可用。_
  - _Depends: T006, T008, T012, T018_

- [x] **T021** [测试／集成交付] 用模拟消费者跑全链路
  - 在 `BT/test_kunlian_workflow_registration_e2e.py` 和 `F/verification.md` 用现有测试设施走 A 新建、授权 B、保存、发布 V1、登记、发布 V2、下线。模拟目录先落库再推进游标，覆盖崩溃重放、回执失败、全量对账及旧绑定保留。按批记录实际命令、代码状态、证据和环境未执行项。
  - **覆盖 AC: AC-01, AC-03, AC-05, AC-07, AC-08, AC-10, AC-11, AC-12**。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-04, REQ-05, REQ-06, REQ-07, REQ-08, REQ-09, REQ-10_
  - _Acceptance: AC-01, AC-03, AC-05, AC-07, AC-08, AC-10, AC-11, AC-12_
  - _Verification: V-01 至 V-03 本地证据，真实 V-04 待执行。_
  - _Depends: T008, T012, T013, T019, T020_

## 3. 正式契约及环境任务

- [ ] **T022** [契约与测试] 固化双方合同并补兼容用例
  - 在 `F/` 正式合同材料与 `BT/test_kunlian_workflow_registration_sync.py` 固化 HTTPS 入口、实际用户与同步身份、范围、OpenAPI、Schema、回执、游标和时效。先加双方正式样例与拒绝用例，再做 T023。EXT-04 中的扩展需求按单独范围处理。
  - **覆盖 AC: AC-01, AC-02, AC-05, AC-06, AC-10, AC-11, AC-12**。
  - _Requirements: REQ-01, REQ-03, REQ-06, REQ-07, REQ-08, REQ-09, REQ-10_
  - _Acceptance: AC-01, AC-02, AC-05, AC-06, AC-10, AC-11, AC-12_
  - _Verification: V-02、V-03 正式合同样例与边界。_
  - _Depends: T021。EXT-01、EXT-02、EXT-03、EXT-05 齐备。_

- [ ] **T023** [后端 API] 接正式身份与拉取合同
  - 在 `B/open_endpoints/api/endpoints/` 及 `B/open_api/domain/scopes.py` 装配已确认的代用户查询和同步凭据校验，分离登记读和回执写。接正式资料与回执字段。按 EXT-01 核验 F118 允许落点及网关配对配置。真实凭据只从约定的安全入口注入。
  - _Requirements: REQ-01, REQ-03, REQ-06, REQ-07, REQ-08, REQ-10_
  - _Acceptance: AC-01, AC-02, AC-05, AC-06, AC-10, AC-11_
  - _Verification: V-02、V-03 通过 T022 合同用例，环境待 T025。_
  - _Depends: T022。生产启用、凭据发放及安全策略变更按项目规则确认。_

- [ ] **T024** [测试／环境] 验证真实存储、授权和浏览器边界
  - 在 `BT/` 的受控数据库验证入口和 `F/verification.md` 验证 MySQL／DM8 事务、并发顺序、范围隔离，真实 OpenFGA 投影恢复、撤权及 F118 安全回跳。按测试能力分批运行，保留数据库版本、账号角色及结果。该批可在自有受控环境先执行。
  - **覆盖 AC: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-11**。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-04, REQ-05, REQ-06, REQ-07, REQ-08, REQ-10_
  - _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-11_
  - _Verification: V-01、V-02、V-03 真实基础设施证据。_
  - _Depends: T021。受控环境、测试账号及表结构执行授权齐备。_

- [ ] **T025** [测试／双方联调] 验证实际登记、下线和回退
  - 在 `F/verification.md` 记录双方真实站点的发布、拉取、目录登记、回执、下线及故障演练。复核失权、断线重试、全量切换、V2 替换及安全禁用顺序，保留请求关联 ID 和实际传播时延。演练使用专用环境，生产部署另行安排。
  - **覆盖 AC: AC-01, AC-05, AC-10, AC-11, AC-12**。
  - _Requirements: REQ-01, REQ-03, REQ-06, REQ-07, REQ-08, REQ-09, REQ-10_
  - _Acceptance: AC-01, AC-05, AC-10, AC-11, AC-12_
  - _Verification: V-04。缺环境或材料时保持 NOT_RUN。_
  - _Depends: T023, T024。双方专用测试环境、同步器和可核对的时效口径齐备。_

## 4. 验证与外部门槛

| 门槛 | 对应任务 | 当前状态 |
| --- | --- | --- |
| EXT-01 入口及可信代用户查询 | T022、T023、T025 | WAITING_EXTERNAL |
| EXT-02 同步服务凭据、读取与回执授权 | T022、T023、T025 | WAITING_EXTERNAL |
| EXT-03 登记范围与版本资料合同 | T022、T023、T025 | WAITING_EXTERNAL |
| EXT-04 可选的额外治理要求 | 出现明确业务场景后单独确认范围 | WAITING_EXTERNAL |
| EXT-05 游标保留、同步时效和联调材料 | T022、T025 | WAITING_EXTERNAL |
| 本地 Mock 入口与模拟消费者 | T021 | PASS，见 [审查回归 E-010](./verification.md) |
| MySQL／DM8、OpenFGA、F118 和浏览器 | T024 | NOT_RUN |
| 昆联真实拉取、目录和回执 | T025 | NOT_RUN |

按业务批次实施测试先行，模块完成后运行一次相关回归。相同代码状态下复用有效证据。开始实施后建立 `verification.md`，每批记录命令、代码状态、结果及跳过原因。Mock、受控环境与双系统验收分别计账。发现未确认的新表、权限策略或协议变更时，先按设计偏差规则确认，再继续对应任务。

## 5. 实际偏差记录

2026-11-06，创建请求通过既有创建入口携带幂等键，草稿通过版本接口携带修订值。当前版本列表只读取摘要，F121 从服务端完整图计算修订并合并到既有列表。候选同步接口仅在隔离 ASGI 测试应用装配。上述落点属于现有设计，运行证据见 [verification.md](./verification.md)。

## 6. 工作流管理页补充任务

依据[已确认设计 §4.6](./design.md#46-工作流管理页)，先用隔离 API 夹具和浏览器 Mock 完成管理页。浏览器验证使用模拟会话和响应，服务端权限、租户及幂等用例通过实际路由和仓储执行，外部服务使用夹具。每批通过后在 [verification.md](./verification.md) 记录命令、结果和证据。

| 批次 | 任务 | 验收方式 |
| --- | --- | --- |
| W6 管理页与列表 | T026–T027 | 后端用根租户、其他租户、当前租户和跨页数据验证可见范围。浏览器 Mock 检查卡片、搜索、状态筛选、加载、空状态及翻页请求。 |
| W7 只读、编辑及返回 | T028–T030 | 后端直接请求验证详情、画布和写入权限。浏览器 Mock 验证只读详情与编辑器分流、撤权反馈、刷新后返回及未保存确认。 |
| W8 新建与幂等 | T031–T032 | 后端隔离 SQL 夹具验证同键重试、并发、冲突及投影恢复。浏览器 Mock 验证直开工作流表单、重试复用请求键及创建后的跳转。 |
| W9 SSO 回跳与页面闭环 | T033–T034 | 用浏览器 Mock 验证已有会话直达、首次回跳、取消与失败，以及管理页创建、查看、编辑和返回的完整路径。运行本批相关前端回归。 |
| W10 真实环境 | T035–T036 | 在受控环境验证 MySQL／DM8、OpenFGA、昆联按钮和真实 SSO。状态为 NOT_RUN。 |

### W6 管理页与列表

- [x] **T026** [后端／测试] 收敛管理页列表的类型、租户和游标范围
  - 在 `B/api/v1/workflow.py` 和 `B/api/services/workflow.py` 为现有列表接入 `scope=workflow_management`，固定工作流类型和 `visible` 动作，复用 `strict_tenant_filter()` 在分页前收敛当前租户。游标绑定主体、租户、范围和筛选条件，普通应用列表沿用原请求行为。
  - _Requirements: REQ-03, REQ-11_
  - _Acceptance: AC-14_
  - _Verification: V-02。复用 `BT/test_kunlian_workflow_management.py` 的路由和权限夹具，验证可见工作流入列、其他租户和根租户资源排除、筛选及游标隔离。_
  - _Depends: T006_
  - _Boundary: 工作流浏览器列表与现有租户过滤。_

- [x] **T027** [前端 Platform] 接入独立工作流管理页
  - 在 `P/routes/index.tsx`、`P/contexts/userContext.tsx`、`P/layout/MainLayout.tsx` 和 `P/pages/BuildPage/apps.tsx` 增加 `/build/workflows`，复用 `build` 菜单准入及应用卡片。请求走 `P/controllers/API/flow.ts`。隐藏其他类型和导航，保留搜索、状态、分页及加载和错误状态。租户或身份变化时重置列表并丢弃旧响应。
  - _Requirements: REQ-03, REQ-11_
  - _Acceptance: AC-14_
  - _Verification: V-05。Mock 浏览器检查页面和请求参数，确认第二页、筛选重置和空列表可用。_
  - _Depends: T026_
  - _Boundary: Platform 管理页与现有应用列表复用。_

### W7 只读、编辑及返回

- [x] **T028** [后端／测试] 分离只读详情与画布读取
  - 在 `B/api/v1/workflow.py` 和 `B/api/services/flow.py` 接入管理页详情范围。当前租户内有 `visible` 权限时返回只读摘要，画布数据通过 `edit` 校验后读取。保存、发布和下线继续分别走已有动作检查。
  - _Requirements: REQ-03, REQ-11_
  - _Acceptance: AC-15_
  - _Verification: V-02。隔离 API 验证只读摘要、未授权图数据及写入拒绝、授权后编辑和撤权后的旧详情地址。_
  - _Depends: T026_
  - _Boundary: 现有详情、版本读取及动作授权。_

- [x] **T029** [前端 Platform] 连接只读详情和有权执行的管理动作
  - 在 `P/pages/BuildPage/` 接入 `/build/workflows/:id`，仅有查看权限时打开只读详情，有编辑权限时进入既有画布。复用 `useResourceActions` 并按主体及租户隔离动作状态，编辑、发布、下线按各自权限显示和执行。
  - _Requirements: REQ-03, REQ-11_
  - _Acceptance: AC-15_
  - _Verification: V-05。Mock 浏览器验证查看者和编辑者分流，权限状态变化后控件和详情响应符合预期。_
  - _Depends: T027, T028_
  - _Boundary: 管理页卡片、只读详情和动作展示。_

- [x] **T030** [前端 Platform] 统一画布返回目标
  - 在 `P/pages/BuildPage/flow/{index,Header}.tsx` 和 `flow/hooks/useBeforeUnload.ts` 接入固定的 `from=workflow-management` 来源标记。编辑器返回、确认离开及发布成功回跳使用同一解析，保留未保存提示和普通入口的原有导航。
  - _Requirements: REQ-03, REQ-11_
  - _Acceptance: AC-15, AC-17_
  - _Verification: V-05。Mock 浏览器刷新画布后返回管理页，验证取消离开时保留编辑状态，伪造来源值无法改成任意跳转。_
  - _Depends: T028, T029_
  - _Boundary: 画布来源、授权读取和返回导航。_

### W8 新建与幂等

- [x] **T031** [后端／测试] 复用持久创建恢复并区分登记资格
  - 在既有创建接口、`B/workflow/application/kunlian_workflow_creation.py`、`kunlian_workflow_management.py` 及登记仓储落地独立的管理页请求键用途。复用原创建记录、同事务的初始版本及 F048 所有者投影。同键同参恢复原对象，同键异参拒绝。未完成对象在管理页分页前过滤，授权读取和写入沿用待完成检查。管理页创建记录只用于去重与恢复，登记资格沿用原登记键和显式范围。
  - _Requirements: REQ-02, REQ-03, REQ-11_
  - _Acceptance: AC-03, AC-04, AC-16_
  - _Verification: V-02。隔离 SQL 与真实路由夹具覆盖并发同键、投影失败后恢复、无创建权限、普通和旧登记入口兼容及管理页创建不自动纳入登记。_
  - _Depends: T005, T026, T028_
  - _Boundary: 既有工作流创建接口及恢复记录。双数据库实测归 T035。_

- [x] **T032** [前端 Platform] 从管理页直接新建工作流
  - 在 `P/pages/BuildPage/CreateApp.tsx` 复用 `AppType.FLOW` 表单与原权限门槛，连接 `P/controllers/API/workflow.ts` 的管理页幂等请求。提交中的按钮保持锁定。同一次失败恢复复用请求键，成功进入带管理页来源标记的画布。
  - _Requirements: REQ-02, REQ-11_
  - _Acceptance: AC-16, AC-17_
  - _Verification: V-05。Mock 浏览器验证无创建权入口隐藏、直接打开工作流表单、失败重试复用键、成功后编辑及返回。_
  - _Depends: T027, T030, T031_
  - _Boundary: 创建表单与管理页导航。_

### W9 SSO 回跳与页面闭环

- [x] **T033** [前端 Platform] 接入 F118 登录回跳
  - 在 Platform 路由和现有登录桥接处先解析会话。已登录直达，未登录且昆联入口已就绪时用 F118 的安全同站回跳机制发起一次登录。保留原目标路径，取消、失败或入口未就绪时走既有登录或错误处理。
  - _Requirements: REQ-01, REQ-11_
  - _Acceptance: AC-13_
  - _Verification: V-05。Mock F118 入口及回调，核对 `return_to`、已有会话直达、失败后无循环跳转。_
  - _Depends: T027_
  - _Boundary: Platform 跳转与既有 F118 浏览器合同。_

- [x] **T034** [测试／交付] 运行 Mock 浏览器闭环并记录证据
  - 按项目浏览器端到端验证方式运行管理页场景。使用隔离的会话和业务响应，覆盖从昆联入口进入、浏览工作流、创建、查看与编辑分流和返回。结合前几批结果执行一次相关后端回归和 Platform 类型、定向 lint、相关 Vitest 回归，将结果登记到 `F/verification.md`。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-11_
  - _Acceptance: AC-13, AC-14, AC-15, AC-16, AC-17_
  - _Verification: V-05 浏览器闭环及 W6–W8 已有 V-02 证据复核。Mock 与真实环境结果分别记录。_
  - _Depends: T030, T032, T033_
  - _Boundary: 本地 Mock 和关联回归。_

### W10 真实环境（NOT_RUN）

- [ ] **T035** [测试／环境] 验证真实存储、租户与 OpenFGA 权限
  - 在受控环境验证严格租户过滤、分页前排除未完成对象、创建键并发及重放、旧记录兼容和真实 OpenFGA 撤权。分别记录 MySQL／DM8 与权限服务结果。
  - _Requirements: REQ-02, REQ-03, REQ-11_
  - _Acceptance: AC-03, AC-14, AC-15, AC-16_
  - _Verification: V-02 真实存储及权限证据。状态 NOT_RUN。_
  - _Depends: T034；受控数据库、OpenFGA、专用测试数据及运行授权。_
  - _Boundary: 真实测试环境中的管理页读取和创建行为。_

- [ ] **T036** [测试／双方联调] 验证昆联按钮和真实 SSO
  - 在双方测试站点从昆联点击「工作流管理」，分别用有会话和无会话浏览器验证到达 `/build/workflows`。以授权测试账号核对列表范围、只读详情、新建、管理动作和编辑器返回，记录登录失败与回跳结果。
  - _Requirements: REQ-01, REQ-03, REQ-11_
  - _Acceptance: AC-13, AC-14, AC-15, AC-16, AC-17_
  - _Verification: V-04 真实浏览器与 F118 证据。状态 NOT_RUN。_
  - _Depends: T034；浏览器可达的联调 Origin、昆联按钮 URL、F118 凭据及回调登记、已同步并授权的测试账号齐备。_
  - _Boundary: 工作流管理页的双方联调。发布登记沿用 T022–T025。_
