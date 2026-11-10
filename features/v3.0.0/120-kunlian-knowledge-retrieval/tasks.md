# Tasks：昆联知识库检索节点

- **Feature ID**: F120
- **Status**: MOCK_IMPLEMENTED
- **Mode**: IMPLEMENT_MOCK
- **Updated**: 2026-11-06（Asia/Shanghai）
- **关联**: [spec.md](./spec.md)、[design.md](./design.md)、[版本契约](../release-contract.md)。

## 1. 状态与范围

| 阶段 | 状态 | 说明 |
| --- | --- | --- |
| spec.md | CONFIRMED | 单库、单问题；10 项需求、20 条 AC。 |
| design.md | CONFIRMED | 用户已确认组件／变量复用、独立适配、发布和运行保护方案。 |
| tasks.md | ACTIVE | 2026-11-06 用户授权实施 Mock 阶段。 |
| Mock 开发 | COMPLETE | 42 / 42。T028 独立本地 Redis 已通过，见 R-06。 |
| 正式契约适配 | WAITING_EXTERNAL | T043 至 T046，0 / 4；对应 EXT 未确认。 |
| 实现合计 | PARTIAL | 42 / 46。当前代码与验证结果见 [verification.md](./verification.md)。 |
| 受控中间件／浏览器及真实昆联验收 | NOT_RUN | 见第 5 节，待执行；分别记录，不能互相替代。 |

本轮在当前分支实施 Mock 范围。T043 至 T046 继续等待正式契约，环境验收状态单独记录。

后续实施继续使用当前昆联对接分支，保护现有暂存及未暂存改动。没有新增 SQL 表，不创建迁移、权限镜像或新的鉴权体系。Client 不新增业务界面，仅随统一错误文案构建获得生成产物。

### 1.1 路径前缀

为避免长路径反复占据任务正文，下列前缀仅用于本文，均相对仓库根目录：

| 前缀 | 实际路径 |
| --- | --- |
| `B/` | `src/backend/bisheng/` |
| `BT/` | `src/backend/test/workflow/` |
| `P/` | `src/frontend/platform/src/` |
| `N/` | `src/frontend/platform/src/pages/BuildPage/flow/FlowNode/` |
| `L/` | `src/frontend/platform/public/locales/` |
| `EL/` | `src/frontend/packages/locales/src/api_errors/` |
| `F/` | `features/v3.0.0/120-kunlian-knowledge-retrieval/` |

## 2. 批次与验证规则

| 批次 | 任务 | 可观察交付 | 验证重点 |
| --- | --- | --- | --- |
| W0 基础 | T001–T004 | 登记、严格合同、默认配置及安全错误。 | 合同与三语静态一致性。 |
| W1 Mock 服务 | T005–T009 | 经本地授权的模拟目录、详情、配置校验和检索服务；真实未就绪明确拒绝。 | V-02、V-04、V-06；API 边界。 |
| W2 编辑器 | T010–T019 | 组合现有组件，单库／单问题、固定输出、保存重开和缓存隔离。 | V-01；前后端能力合同。 |
| W3 发布 | T020–T025 | 检索与 Agent 全部校验后一次发布，版本保护和双向变量引用。 | V-03、V-05。 |
| W4 运行 | T026–T040 | 冻结图、真实本地操作者、节点／Worker／停止／事件／试运行完整接线。 | V-02、V-03、V-04；遗漏入口必须拒绝。 |
| W5 Mock 闭环 | T041–T042 | 可执行端到端测试、示例图及人工清单。 | V-05、V-06；按环境执行。 |
| W6 真实适配 | T043–T046 | 正式合同测试、可信凭据及真实资源／检索适配。 | 对应 EXT 齐备后执行，仍不等于真实验收通过。 |

表格用于组织批次，不是并行 Agent 授权；按每项 Depends 串行推进，同一文件的后续任务只增量实现明确的方法，不重写前序工作。W2 可在 W1 的接口合同稳定后开发；编写完整运行证据必须等待 W3／W4 接线完成。

- 权限、状态、事务和并发先写测试再实现；基础配置和错误定义不机械拆测试配对。测试任务只写测试及必要的局部夹具。
- 复用已有 pytest／前端测试配置。仅缺少本特性夹具时增补测试同目录文件，不新建整套测试框架或安装依赖。
- 每个任务有 REQ／AC／V 追踪，测试任务另列“覆盖 AC”。同一行为以一个主要层级验证；API、Worker、Redis、浏览器仅补其独立边界风险。
- 一批行为只执行一次定向验证，阶段结束一次模块验证；相同代码状态复用成功证据，不为逐条 AC 重复跑命令。
- 主要任务限一至两个源文件。T004、T019 的三语文件是一个不可拆的文案批次；生成产物由原脚本生成，不能手改。
- 代码／测试产物和环境验收分别记账。勾选任务需有实际产物及已说明的本地可执行证据；关键产物或本地验证未完成时保持未勾选并记录 PARTIAL。受控数据库、Redis、Broker／Worker／浏览器、真实昆联证据单列，缺环境标 NOT_RUN，不据此宣称 Mock 闭环或全特性验收通过。
- 实施开始时创建 `verification.md`，逐批记录命令、代码状态、环境、结果和证据 ID；本轮不生成虚假的运行记录。测试收集失败或仅导入成功不代替业务断言通过。

### 2.1 TODO 与外部门禁

用户要求的 TODO 优先于审查清单中禁止无理由延期 TODO 的通用规则。仅标记模拟目录／数据、模拟外部身份、模拟调用及未确认协议；本地授权、校验、发布事务、停止保护和脱敏必须在 Mock 阶段完成。

```text
# TODO [F120][EXT-01] 当前目录为模拟知识库，正式授权资源契约确认后替换。
# TODO [F120][EXT-02] 当前外部授权为模拟映射，确认 Token 复用或已有委托规则后接入。
# TODO [F120][EXT-03] 当前检索、数量和超时为模拟约定，确认正式协议后替换并补真实验证。
```

Python 使用 `# TODO`，TypeScript 使用 `// TODO`，注释使用中文，说明当前模拟内容与替换条件；EXT-04 对应测试样例和联调材料。界面只标“模拟数据”，不显示内部 TODO 编号。

| 门禁 | 影响 | 未满足时 |
| --- | --- | --- |
| EXT-01 | 昆联知识库发现、状态、使用权限、可选修订语义。 | T045 待执行；Mock 继续。 |
| EXT-02 | SSO Access Token 复用或现有可信委托、租户和有效期。 | T044 待执行；不以 ID Token、同步 Key 或创建人凭据替代。 |
| EXT-03 | 同步检索、片段来源、限制、错误与超时正式合同。 | T046 待执行；保留明确 Mock 约定。 |
| EXT-04 | OpenAPI、测试库／文档、A／B 账号、地址和联调时间。 | 真实联调 NOT_RUN。 |
| ENV-STORE | 受控 MySQL／DM8、Redis、OpenFGA。 | 对应真实事务、原子性与授权验证 NOT_RUN。 |
| ENV-RUN | 正常 API、Broker、Worker、浏览器及普通测试账号。 | 正常运行链路验收 NOT_RUN。 |

## 3. Mock 开发任务

### W0 基础

- [x] **T001** [基础设施] 登记 F120 边界
  - **文件**：`features/v3.0.0/release-contract.md`。
  - **工作**：登记复用 Workflow 图与临时 Redis 运行事实、无新增 SQL 表和权限动作；F118／F048 Owner 不变。只新增本特性登记，不覆盖用户已有改动。
  - _Requirements: REQ-05, REQ-06, REQ-10_
  - _Acceptance: AC-09, AC-12, AC-19_
  - _Verification: V-03, V-04, V-05；V0 领域及兼容边界核对。_
  - _Depends: 无_
  - _Boundary: 无迁移、部署或全局不变量变更。_

- [x] **T002** [基础设施] 定义节点合同与默认配置
  - **文件**：`B/workflow/domain/schemas/platform_knowledge.py`、`B/core/config/settings.py`。
  - **工作**：定义单库、常量／变量单问题、严格 top_k、四项固定输出及 actor 数据合同；拒绝重复 ID／参数和伪造输出。增加默认 Mock 配置，按设计设置本地数量／查询／预算／大小限制，未确认数值保留 EXT-03 TODO。
  - _Requirements: REQ-02, REQ-03, REQ-04, REQ-09_
  - _Acceptance: AC-03, AC-04, AC-05, AC-07, AC-17_
  - _Verification: V-02, V-06；合同断言在 T005 中执行。_
  - _Depends: T001_
  - _Boundary: 仅代码中的默认值；不修改运行中 YAML、环境或数据库配置。_

- [x] **T003** [基础设施] 定义安全错误并登记
  - **文件**：`B/common/errcode/flow.py`、`features/v3.0.0/release-contract.md`。
  - **工作**：重新检查候选 10563–10570 是否占用，按设计定义配置、权限、资源、未就绪、上游、输出、执行及超时错误；沿既有 HTTP 合同，未知异常不透传原文。
  - _Requirements: REQ-07, REQ-08, REQ-09_
  - _Acceptance: AC-13, AC-14, AC-15, AC-17_
  - _Verification: V-02, V-04, V-06；码段与 HTTP 状态静态核对。_
  - _Depends: T001_
  - _Boundary: 不复用 Agent 专属错误含义；冲突时调整未落码候选并同步设计。_

- [x] **T004** [基础设施／共享文案] 补齐错误三语源
  - **文件**：`EL/zh-Hans.json`、`EL/en.json`、`EL/ja.json` 及原流程生成产物。
  - **工作**：补安全错误文案，使用现有 locales 构建生成 Platform／Client 产物；保留三个语言键一致。
  - _Requirements: REQ-07, REQ-08_
  - _Acceptance: AC-13, AC-14, AC-15_
  - _Verification: V-02, V-05；现有 locales 构建与错误文案校验。_
  - _Depends: T003_
  - _Boundary: 三语同批机械变更，不手改生成件，不新增 Client 页面。_

### W1 Mock 服务

- [x] **T005** [测试／后端] 编写合同、目录与服务拒绝测试
  - **文件**：`BT/test_platform_knowledge_contract.py`、`BT/test_platform_knowledge_api.py`。
  - **工作**：先定义正常／空／非法来源样例、输入与数量边界、固定输出声明、双向文本引用及伪造引用拒绝；覆盖 A／B 同库文档裁剪、跨租户及伪造身份拒绝。API 验证目录、详情、validate 不执行检索，以及能力／错误合同；实际用户权限通过受控 Owner 夹具注入，不以管理员全通过代替。
  - **覆盖 AC: AC-01, AC-02, AC-04, AC-05, AC-07, AC-08, AC-11, AC-12, AC-13, AC-16, AC-17**。
  - _Requirements: REQ-01, REQ-03, REQ-04, REQ-06, REQ-07, REQ-09_
  - _Acceptance: AC-01, AC-02, AC-04, AC-05, AC-07, AC-08, AC-11, AC-12, AC-13, AC-16, AC-17_
  - _Verification: V-02, V-04, V-06；测试先于 T006–T009 实现。_
  - _Depends: T002, T003, T004_
  - _Boundary: 只写测试及本文件必要样例，不用假成功覆盖真实入口失败。_

- [x] **T006** [后端 Domain] 实现 Provider 与 Mock
  - **文件**：`B/workflow/domain/clients/platform_knowledge.py`、`B/workflow/domain/clients/platform_knowledge_mock.py`。
  - **工作**：实现 list_knowledge／get_knowledge／check_use／retrieve 协议、默认通用 B、可选 tenant:user 专项映射；提供维护、制度、私有库及故障场景，匹配查询与无匹配可重复。模拟来源保留 EXT-01／EXT-02／EXT-03 TODO；real 未就绪、disabled 明确拒绝。
  - _Requirements: REQ-01, REQ-04, REQ-09_
  - _Acceptance: AC-01, AC-02, AC-07, AC-08, AC-16, AC-17_
  - _Verification: V-02, V-04, V-06；通过 T005 的 Provider／样例断言。_
  - _Depends: T005_
  - _Boundary: 无前端硬编码目录，无真实网络调用，无真实业务数据。_

- [x] **T007** [后端 Domain] 实现授权、目录、校验与纯检索规则
  - **文件**：`B/workflow/domain/services/platform_knowledge_service.py`、`B/workflow/application/platform_knowledge.py`。
  - **工作**：按 Workflow 业务目标、当前用户事实和 F048 授权；实现目录／详情／图校验及单次检索规则、严格来源归一、同源派生四输出和总预算。有效 null／空白短路 retrieve，缺失变量不短路；运行上下文装配在 T029 增量接入。
  - _Requirements: REQ-01, REQ-03, REQ-04, REQ-06, REQ-07_
  - _Acceptance: AC-02, AC-04, AC-05, AC-07, AC-08, AC-11, AC-12, AC-13_
  - _Verification: V-02, V-04；执行 T005 服务行为断言，敏感值不进入错误。_
  - _Depends: T006_
  - _Boundary: 不直查用户表、不绕过权限 Owner，不实现不受运行保护的公共检索入口。_

- [x] **T008** [后端 API] 接目录、详情和配置校验路由
  - **文件**：`B/workflow/api/endpoints/platform_knowledge.py`、`B/workflow/api/router.py`。
  - **工作**：提供设计中的 GET 列表／详情及 POST validate；认证注入，委托应用服务，返回标准成功与安全错误。目录支持 name／cursor，资源 ID 按不透明字符串处理。
  - _Requirements: REQ-01, REQ-02, REQ-06, REQ-07_
  - _Acceptance: AC-01, AC-02, AC-03, AC-06, AC-12, AC-13_
  - _Verification: V-01, V-02, V-04；通过 T005 API 断言。_
  - _Depends: T007_
  - _Boundary: 不接受业务载荷中的用户、租户、模式、令牌或 URL，不新增浏览器直调检索 API。_

- [x] **T009** [后端 API] 暴露安全能力标识
  - **文件**：`B/api/v1/endpoints.py`。
  - **工作**：在 env 增加检索 enabled／mode／policy_revision／connection_id，保留 multi_tenant_enabled。Mock 就绪可用，disabled／当前 real 未就绪不可执行；配置读取失败关闭能力，不返回映射或凭据。
  - _Requirements: REQ-01, REQ-09_
  - _Acceptance: AC-01, AC-02, AC-17_
  - _Verification: V-01, V-06；T005 覆盖默认与显式模式的 env 合同。_
  - _Depends: T008_
  - _Boundary: 不改变其他节点能力与现有 env 字段。_

### W2 Platform 编辑器

- [x] **T010** [前端 Platform] 定义 API、模板与类型
  - **文件**：`P/controllers/API/platformKnowledge.ts`、`P/types/flow/platformKnowledge.ts`。
  - **工作**：使用请求封装实现能力／目录／详情／validate；定义独立节点模板、问题联合类型和四个固定根输出，采用现有 var／global 描述，不引入深层字段协议。
  - _Requirements: REQ-01, REQ-02, REQ-04, REQ-10_
  - _Acceptance: AC-01, AC-03, AC-07, AC-20_
  - _Verification: V-01, V-05；类型检查及 T011 合同测试。_
  - _Depends: T002, T008, T009_
  - _Boundary: 请求只在 API 模块，Zustand 不调 HTTP，无新依赖。_

- [x] **T011** [测试／前端 Platform] 校验能力与请求合同
  - **文件**：`P/controllers/API/platformKnowledge.test.ts`。
  - **工作**：验证真实 env 解包，保留 multi_tenant_enabled 的 true／false／缺省三态、连接和修订；资源编码、分页及失败不补假目录。使用与后端相同外形的响应样例。
  - **覆盖 AC: AC-01, AC-02, AC-17**。
  - _Requirements: REQ-01, REQ-09_
  - _Acceptance: AC-01, AC-02, AC-17_
  - _Verification: V-01, V-06；接口层独立风险，与组件交互不重复。_
  - _Depends: T010_
  - _Boundary: 只写测试，不调整产品协议以迁就测试。_

- [x] **T012** [测试／前端 Platform] 编写问题、结果联动和试运行输入测试
  - **文件**：`N/component/PlatformKnowledgeQueryItem.test.tsx`、`N/RunTest.platformKnowledge.test.tsx`。
  - **工作**：覆盖常量／变量单选、保存重开、变量更名／失效、固定输出 key、不兼容映射提示；试运行只提取已选变量，常量不生成试填项，切换和失败清理旧结果。
  - **覆盖 AC: AC-03, AC-04, AC-06, AC-18, AC-20**。
  - _Requirements: REQ-02, REQ-03, REQ-04, REQ-10_
  - _Acceptance: AC-03, AC-04, AC-06, AC-18, AC-20_
  - _Verification: V-01, V-02, V-05；共享控件本身不重测。_
  - _Depends: T010_
  - _Boundary: 只写交互测试，正常 Worker／浏览器证据另记。_

- [x] **T013** [前端 Platform] 组合已有单问题组件
  - **文件**：`N/component/PlatformKnowledgeQueryItem.tsx`。
  - **工作**：复用 VarSelectSingleItem、SelectVar 和已有输入控件，组合变量／常量选择；沿用 onVarEvent、变量名称更新及 onOutPutChange，切换问题不改变四个输出 key。
  - _Requirements: REQ-02, REQ-03, REQ-04, REQ-10_
  - _Acceptance: AC-03, AC-04, AC-06, AC-20_
  - _Verification: V-01；通过 T012 问题组件断言。_
  - _Depends: T011, T012_
  - _Boundary: 不重写通用变量选择器，不复制批量问题生成 key 的逻辑。_

- [x] **T014** [测试／前端 Platform] 编写选库与缓存隔离测试
  - **文件**：`N/component/PlatformKnowledgeSelectItem.test.tsx`。
  - **工作**：覆盖目录加载／空／失败、资源失效、单选保存、空 ID 过滤；兼容 tenant_id／leaf_tenant_id／服务器明确单租户，切换用户／租户／模式／连接／修订清理旧候选，多租户缺身份阻断。
  - **覆盖 AC: AC-01, AC-02, AC-03, AC-06, AC-20**。
  - _Requirements: REQ-01, REQ-02, REQ-06, REQ-10_
  - _Acceptance: AC-01, AC-02, AC-03, AC-06, AC-20_
  - _Verification: V-01；请求夹具保留 T011 的实际能力合同。_
  - _Depends: T011_
  - _Boundary: 只写测试，不通过固定 tenant_id 绕过当前用户信息合同。_

- [x] **T015** [前端 Platform] 组合昆联单库选择
  - **文件**：`N/component/PlatformKnowledgeSelectItem.tsx`。
  - **工作**：使用共享 Select、useSelectLabels 和 React Query v4，按 T014 处理缓存、分页和错误；展示 Mock 标识，保留已选失效 ID 供修复，不能继续作为有效授权。
  - _Requirements: REQ-01, REQ-02, REQ-06, REQ-09_
  - _Acceptance: AC-01, AC-02, AC-03, AC-06, AC-17_
  - _Verification: V-01, V-06；通过 T014 交互断言。_
  - _Depends: T014_
  - _Boundary: 不调用本地知识库 API，不提供多库或关闭用户鉴权设置。_

- [x] **T016** [前端 Platform] 接模板装载与侧栏
  - **文件**：`P/controllers/API/workflow.ts`、`P/pages/BuildPage/flow/Sidebar.tsx`。
  - **工作**：引入独立模板，按服务器能力展示“昆联知识库检索”；默认 Mock 可添加，关闭时不开放新可执行节点，旧图仍能打开查看。
  - _Requirements: REQ-01, REQ-09, REQ-10_
  - _Acceptance: AC-01, AC-17, AC-19_
  - _Verification: V-01, V-05, V-06；模板枚举及已有节点列表回归。_
  - _Depends: T013, T015_
  - _Boundary: 原本地节点模板和 Agent 入口保持原义。_

- [x] **T017** [前端 Platform] 接参数与图标
  - **文件**：`N/Parameter.tsx`、`N/NodeLogo.tsx`。
  - **工作**：为两个新参数类型装配上述组合组件，数量复用 InputItem、结果复用 VarItem；使用现有检索图标表达，不复制整套节点编辑器。
  - _Requirements: REQ-02, REQ-04, REQ-10_
  - _Acceptance: AC-03, AC-07, AC-20_
  - _Verification: V-01, V-05；T012／T014 的组件接线与变量枚举。_
  - _Depends: T016_
  - _Boundary: 不新增检索权重、重排、过滤或鉴权开关。_

- [x] **T018** [前端 Platform] 接节点展示与运行标签
  - **文件**：`N/index.tsx`、`N/RunLog.tsx`。
  - **工作**：沿用现有检索节点的布局和状态样式；日志识别模式、资源、数量和安全错误标签，变量仍由原日志通路展示。
  - _Requirements: REQ-08, REQ-10_
  - _Acceptance: AC-15, AC-19, AC-20_
  - _Verification: V-01, V-05；T041／T042 检查正常与失败界面。_
  - _Depends: T017_
  - _Boundary: 无新增样式规范或详情页，不展示内部凭据和 TODO 编号。_

- [x] **T019** [前端 Platform] 补齐节点三语文案
  - **文件**：`L/zh-Hans/flow.json`、`L/en-US/flow.json`、`L/ja/flow.json`。
  - **工作**：同步节点、问题／范围／输出、模拟标识、空态／错误和日志文案，复用已有业务用词。
  - _Requirements: REQ-01, REQ-08, REQ-09, REQ-10_
  - _Acceptance: AC-01, AC-02, AC-15, AC-20_
  - _Verification: V-01, V-05；三语键校验及前端质量门禁。_
  - _Depends: T018_
  - _Boundary: 三语同批；不为本期修改旧功能文案含义。_

### W3 发布与引用

- [x] **T020** [测试／后端] 编写发布事务和版本保护测试
  - **文件**：`BT/test_platform_knowledge_publication.py`、`BT/test_platform_knowledge_versions.py`。
  - **工作**：覆盖发布者动作权限和资源预检拒绝、并发编辑摘要变化、发布后草稿隔离、Agent＋检索全成全败；保存／切换／删除／复制／导入／移除最后节点不得绕过绑定保护。Agent-only 与无新节点图保留原义。
  - **覆盖 AC: AC-06, AC-09, AC-10, AC-12, AC-19**。
  - _Requirements: REQ-02, REQ-05, REQ-06, REQ-07, REQ-10_
  - _Acceptance: AC-06, AC-09, AC-10, AC-12, AC-19_
  - _Verification: V-03, V-05；本地事务断言与受控 MySQL／DM8 锁语义分别登记。_
  - _Depends: T007_
  - _Boundary: 先写测试；SQLite 不证明真实双数据库锁行为。_

- [x] **T021** [后端 Repository] 抽取既有发布事务
  - **文件**：`B/workflow/domain/repositories/platform_node_publication.py`、`B/workflow/domain/repositories/platform_agent.py`。
  - **工作**：抽取 Flow／FlowVersion 读取、锁定、图摘要复核和单次发布提交；候选图剥离两类服务端绑定。F119 原方法保留委托入口，Agent-only 摘要含义保持。
  - _Requirements: REQ-05, REQ-10_
  - _Acceptance: AC-09, AC-19_
  - _Verification: V-03, V-05；T020 及受影响 F119 发布仓储回归。_
  - _Depends: T020_
  - _Boundary: 只抽取已确认发布事务；无 Schema 或原权限策略变化。_

- [x] **T022** [后端 Domain] 实现两类节点的发布材料准备
  - **文件**：`B/workflow/domain/services/platform_agent_service.py`、`B/workflow/domain/services/platform_knowledge_service.py`。
  - **工作**：各自提供 prepare_publication；检索材料固定选库、问题、数量及模式／连接／修订，Agent 沿用固定版本和 Schema。外部预检不在数据库锁内执行，真实内容不被声称为快照。
  - _Requirements: REQ-02, REQ-05, REQ-06_
  - _Acceptance: AC-06, AC-09, AC-10, AC-12_
  - _Verification: V-03, V-04；T020 的两类材料及撤权断言。_
  - _Depends: T021_
  - _Boundary: 增量提取原发布逻辑，不复制 Agent Schema 或 Token 到检索配置。_

- [x] **T023** [后端应用] 协调一次完整发布
  - **文件**：`B/workflow/application/platform_node_publication.py`、`B/api/services/workflow.py`。
  - **工作**：替换含检索图的 update_status 分支，先汇总两类预检再一次提交；候选或当前图含新节点均检查，清理旧绑定；保留 Agent-only 原入口和动作授权。
  - _Requirements: REQ-05, REQ-06, REQ-10_
  - _Acceptance: AC-09, AC-10, AC-12, AC-19_
  - _Verification: V-03, V-05；T020 混合图发布与原分支回归。_
  - _Depends: T022_
  - _Boundary: 不先提交 Agent 再追加知识校验，不新增发布 API。_

- [x] **T024** [后端应用] 接版本生命周期保护
  - **文件**：`B/api/services/flow.py`。
  - **工作**：含检索节点或绑定的版本保存／切换／删除沿共用 Repository 保护；复制／导入清除服务端绑定，已发布图不可被草稿覆盖，最后节点移除不残留绑定。
  - _Requirements: REQ-02, REQ-05, REQ-10_
  - _Acceptance: AC-03, AC-09, AC-19_
  - _Verification: V-03, V-05；T020 版本入口断言。_
  - _Depends: T023_
  - _Boundary: 不修改其他应用类型或已有授权方式。_

- [x] **T025** [后端 Domain] 补双向变量引用识别
  - **文件**：`B/workflow/domain/services/platform_agent_service.py`、`B/workflow/domain/services/platform_knowledge_service.py`。
  - **工作**：按固定输出合同识别四根变量，允许检索文本传给 Agent；允许合法 Agent 文本字段作为检索问题，运行时仍校验实际值。拒绝伪造输出、缺失节点和不支持的深层路径。
  - _Requirements: REQ-02, REQ-03, REQ-04, REQ-10_
  - _Acceptance: AC-04, AC-06, AC-07, AC-19, AC-20_
  - _Verification: V-02, V-05；T005 中的固定声明／伪造引用断言，T041 补跨入口互连。_
  - _Depends: T022_
  - _Boundary: 只扩展新类型的合法输出识别，不放宽任意前端声明。_

### W4 正常运行链路

- [x] **T026** [测试／后端] 编写运行事实与节点结果保护测试
  - **文件**：`BT/test_platform_knowledge_repository.py`、`BT/test_platform_knowledge_node.py`。
  - **工作**：覆盖执行受理／领取／环境切换／过期、停止与提交竞争、旧 owner 和终态保护；节点缺失与 null 区别、空短路、失败不残留、迟到不下传及安全日志。原子性另接受控真实 Redis 夹具。
  - **覆盖 AC: AC-04, AC-07, AC-08, AC-10, AC-12, AC-13, AC-14, AC-15, AC-17**。
  - _Requirements: REQ-03, REQ-04, REQ-05, REQ-06, REQ-07, REQ-08, REQ-09_
  - _Acceptance: AC-04, AC-07, AC-08, AC-10, AC-12, AC-13, AC-14, AC-15, AC-17_
  - _Verification: V-02, V-03, V-04, V-06；本地合同与 Redis 原子性分开记账。_
  - _Depends: T007_
  - _Boundary: 只写测试，不把进程内锁或内存替身计为分布式原子性通过。_

- [x] **T027** [测试／后端] 编写入口与 Worker 桥接测试
  - **文件**：`BT/test_platform_knowledge_entrypoints.py`、`BT/test_platform_knowledge_workflow_bridge.py`。
  - **工作**：覆盖浏览器／已发布／试运行操作者、START／CONTINUE／STOP 引用一致性、headers 租户恢复、缺上下文拒绝、token_version 变化及 F119 混合保护；试运行只允许声明的问题变量，不可覆盖资源和身份。断言秘密探针不进入图／队列／事件。
  - **覆盖 AC: AC-11, AC-12, AC-14, AC-15, AC-19**。
  - _Requirements: REQ-06, REQ-07, REQ-08, REQ-10_
  - _Acceptance: AC-11, AC-12, AC-14, AC-15, AC-19_
  - _Verification: V-03, V-04, V-05；模拟调用桥仅证明传递合同，真实 Broker 在 ENV-RUN 验证。_
  - _Depends: T026_
  - _Boundary: 先写接线测试；不通过服务账号或创建人回退补身份。_

- [x] **T028** [后端 Repository] 实现 Redis 运行事实与原子检查
  - **文件**：`B/workflow/domain/repositories/platform_knowledge_run.py`。
  - **工作**：实现冻结图、当前执行引用、领取 owner、step／call 结果、停止／失效／终态和 7 天清理 TTL；原子核对执行引用及状态，旧 STOP 不能影响新轮次，丢失记录拒绝。
  - _Requirements: REQ-05, REQ-06, REQ-07_
  - _Acceptance: AC-09, AC-12, AC-14_
  - _Verification: V-03, V-04；通过 T026 仓储合同，真实 Redis 竞争证据单列。_
  - _Depends: T026_
  - _Boundary: 无新 SQL 表，不修改 Agent 执行表，无远端 exactly-once 承诺。_
  - **进度**：使用独立本地 Redis 7.2.17 执行原子性用例并通过，见 R-06。受控中间件联合验收待执行。

- [x] **T029** [后端应用／Domain] 装配可信运行上下文
  - **文件**：`B/workflow/application/platform_knowledge.py`、`B/workflow/domain/services/platform_knowledge_service.py`。
  - **工作**：增量实现 BrowserPlatformKnowledgeRuntime.prepare／resume／abort 与 retrieve_node；受理冻结图和操作者引用，执行及提交前重读 Owner 身份、Workflow 权限和环境指纹，总预算覆盖授权／资源检查／检索。
  - _Requirements: REQ-05, REQ-06, REQ-07, REQ-09_
  - _Acceptance: AC-09, AC-10, AC-11, AC-12, AC-14, AC-17_
  - _Verification: V-02, V-03, V-04, V-06；T026／T027 的上下文和撤权断言。_
  - _Depends: T027, T028, T025_
  - _Boundary: 队列只传服务端引用，不存 Token；无自然人拒绝，不自动恢复崩溃调用。_

- [x] **T030** [后端节点] 实现独立检索节点
  - **文件**：`B/workflow/nodes/platform_knowledge_retriever/platform_knowledge_retriever.py`、同目录 `__init__.py`。
  - **工作**：继承 BaseNode，严格解析问题变量，调用受保护服务、返回四输出；run 前清除旧结果，output_commit_scope 保护临时写入并回滚失效输出。使用 utils 异步桥，外层 timeout=None。
  - _Requirements: REQ-03, REQ-04, REQ-07, REQ-08_
  - _Acceptance: AC-04, AC-05, AC-07, AC-08, AC-13, AC-14, AC-15_
  - _Verification: V-02, V-03, V-05；通过 T026 节点行为断言。_
  - _Depends: T029_
  - _Boundary: 不继承本地 RagUtils、不调用本地引用注册，不导入 Worker。_

- [x] **T031** [后端接线] 注册新节点类型
  - **文件**：`B/workflow/common/node.py`、`B/workflow/nodes/node_manage.py`。
  - **工作**：注册 platform_knowledge_retriever 与节点工厂映射，构造节点不发网络请求；保留已有类型及映射。
  - _Requirements: REQ-01, REQ-10_
  - _Acceptance: AC-01, AC-19_
  - _Verification: V-05；工厂构造、T027 入口断言及 T041 独立导入。_
  - _Depends: T030_
  - _Boundary: 无旧节点重命名、删除或迁移。_

- [x] **T032** [后端图引擎] 传递检索运行上下文
  - **文件**：`B/workflow/graph/workflow.py`、`B/workflow/graph/graph_engine.py`。
  - **工作**：对新节点图传入／恢复 platform_knowledge_context，按冻结图构造节点；与 Agent context 并存，后续节点调度使用当前执行保护。
  - _Requirements: REQ-05, REQ-06, REQ-07, REQ-10_
  - _Acceptance: AC-09, AC-11, AC-12, AC-14, AC-19_
  - _Verification: V-03, V-04, V-05；T027 混合上下文及旧图回归。_
  - _Depends: T031_
  - _Boundary: 无新节点图不创建检索上下文，不改变其原执行路径。_

- [x] **T033** [后端节点框架] 接提交和下一节点检查
  - **文件**：`B/workflow/nodes/base.py`。
  - **工作**：对受保护的新节点图检查当前引用和状态，提交失败不写变量、停止后不调度后续节点；安全错误进入既有结束事件。保留 Agent 提交钩子和原节点行为。
  - _Requirements: REQ-07, REQ-08, REQ-10_
  - _Acceptance: AC-13, AC-14, AC-15, AC-19_
  - _Verification: V-02, V-03, V-05；T026／T027 竞争及原节点回归。_
  - _Depends: T032_
  - _Boundary: 不以一次非原子的 Redis GET 冒充提交保护，不扩大未保护旧图的行为。_

- [x] **T034** [后端浏览器桥] 通过端口传递运行引用
  - **文件**：`B/common/chat/manager.py`、`B/common/chat/clients/workflow_client.py`。
  - **工作**：沿现有注入端口接 prepare／resume／abort，传递检索执行引用，STOP 先失效匹配执行；与 Agent 端口并存，避免新旧运行串用。
  - _Requirements: REQ-06, REQ-07, REQ-10_
  - _Acceptance: AC-11, AC-12, AC-14, AC-19_
  - _Verification: V-03, V-04, V-05；T027 浏览器桥合同。_
  - _Depends: T033_
  - _Boundary: common 层不反向导入 Workflow 领域实现，仅接受路由注入端口。_

- [x] **T035** [后端 API] 注入浏览器与公开入口端口
  - **文件**：`B/api/v1/workflow.py`、`B/public_endpoints/api/endpoints/workflow.py`。
  - **工作**：在各自现有入口装配 BrowserPlatformKnowledgeRuntime，绑定真实认证操作者；公开调用缺少可信自然人时拒绝新节点，不能提升为创建人身份。
  - _Requirements: REQ-06, REQ-07, REQ-10_
  - _Acceptance: AC-11, AC-12, AC-14, AC-19_
  - _Verification: V-04, V-05；T027 两类入口一致性与拒绝断言。_
  - _Depends: T034_
  - _Boundary: 不新增公开路径、白名单或权限动作。_

- [x] **T036** [后端已发布运行] 接认证与公开运行适配
  - **文件**：`B/workflow/domain/services/published_workflow_service.py`。
  - **工作**：已发布图使用服务端发布版本，通过共同受理创建检索引用；OpenAPI 执行快照必须明确实际自然人，队列只携带引用与既有快照。
  - _Requirements: REQ-05, REQ-06, REQ-10_
  - _Acceptance: AC-09, AC-11, AC-12, AC-19_
  - _Verification: V-03, V-04, V-05；T027 已发布调用合同。_
  - _Depends: T029, T035_
  - _Boundary: 不改变服务账号的既有全局策略，只拒绝本节点不支持的无自然人调用。_

- [x] **T037** [Worker] 接 START／CONTINUE／STOP
  - **文件**：`B/worker/workflow/tasks.py`。
  - **工作**：新增 platform_knowledge_execution 引用；Celery headers 中的 tenant_id 恢复到 ContextVar，并与受理记录／执行快照核对。领取后重读身份，冻结图执行，STOP 失效匹配引用，失败和终态不覆盖新执行。
  - _Requirements: REQ-05, REQ-06, REQ-07, REQ-10_
  - _Acceptance: AC-09, AC-11, AC-12, AC-14, AC-19_
  - _Verification: V-03, V-04, V-05；T027 桥接断言，真实 Broker／Worker 证据单列。_
  - _Depends: T036_
  - _Boundary: 不依赖 API 进程初始化；旧消息无有效引用时拒绝新节点，不自动重发远端检索。_

- [x] **T038** [Worker 回调] 保护事件、停止与终态
  - **文件**：`B/worker/workflow/redis_callback.py`。
  - **工作**：按检索执行引用保护事件入队和状态变更，消费时剥离内部标记；混合图同时满足两种上下文保护，原子拒绝迟到、旧 owner、已停止和终态覆盖。
  - _Requirements: REQ-07, REQ-08, REQ-10_
  - _Acceptance: AC-14, AC-15, AC-19_
  - _Verification: V-03, V-04, V-05；T026 原子边界与 T027 回调断言。_
  - _Depends: T028, T037_
  - _Boundary: 不更改公共事件类别，不把内部引用或令牌暴露给前端。_

- [x] **T039** [后端试运行] 通过完整节点生命周期执行
  - **文件**：`B/api/services/workflow.py`。
  - **工作**：为新类型增量接入 run_once 的受理、声明输入白名单和 node.run；返回原日志格式，成功／失败结束对应试运行，不允许覆盖图资源、身份或模式。
  - _Requirements: REQ-02, REQ-03, REQ-06, REQ-07_
  - _Acceptance: AC-03, AC-04, AC-12, AC-13, AC-14_
  - _Verification: V-02, V-04, V-05；T027 节点试运行入口断言。_
  - _Depends: T023, T030, T033, T038_
  - _Boundary: 不对新节点直接调用 _run 绕过提交检查，不修改其他节点试运行合同。_

- [x] **T040** [前端 Platform] 接单节点试运行输入与结果
  - **文件**：`N/RunTest.tsx`。
  - **工作**：识别问题联合类型，仅变量分支生成试填输入；调用既有 run_once，复用原结果界面，失败／切换清空旧结果，显示可定位安全错误。
  - _Requirements: REQ-02, REQ-03, REQ-04, REQ-07, REQ-10_
  - _Acceptance: AC-03, AC-04, AC-13, AC-18, AC-20_
  - _Verification: V-01, V-02, V-05；通过 T012 RunTest 交互断言。_
  - _Depends: T012, T019, T039_
  - _Boundary: 不新增测试专用检索 API，不在浏览器中补模拟成功。_

### W5 Mock 闭环产物

- [x] **T041** [测试／后端与端到端] 编写正常入口与独立导入验证
  - **文件**：`BT/test_platform_knowledge_e2e.py`、`BT/test_platform_knowledge_imports.py`。
  - **工作**：按项目 e2e-test 流程编写 API 端到端用例，支持受控正常 Broker／Worker；验证最小成功、空结果、失败不串旧结果、发布固定、A／B 拒绝、双向 Agent 文本互连及模式切换。独立子进程导入实际 API／节点，避免 conftest 预加载掩盖循环导入。
  - **覆盖 AC: AC-07, AC-08, AC-09, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20**。
  - _Requirements: REQ-02, REQ-04, REQ-05, REQ-06, REQ-07, REQ-08, REQ-09, REQ-10_
  - _Acceptance: AC-07, AC-08, AC-09, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20_
  - _Verification: V-03, V-04, V-05, V-06；脚本编写与正常环境实际执行分别记录。_
  - _Depends: T024, T025, T038, T040_
  - _Boundary: 复用既有测试框架；无账号／中间件时对应执行 NOT_RUN，不把服务方法直调当正常运行证据。_

- [x] **T042** [文档／样例] 提供可复现 Mock 流程与人工清单
  - **文件**：`F/mock-workflow.example.json`、`F/e2e-checklist.md`。
  - **工作**：给出开始—输入—检索—输出示例和可选大模型／Agent 文本互连步骤；说明维护库、正常／无匹配问题、故障样例、保存重开、停止与 A／B 场景，明确前置账号和服务条件。
  - _Requirements: REQ-01, REQ-02, REQ-04, REQ-06, REQ-07, REQ-09, REQ-10_
  - _Acceptance: AC-01, AC-03, AC-07, AC-08, AC-11, AC-14, AC-16, AC-18, AC-19, AC-20_
  - _Verification: V-01, V-03, V-04, V-05；按清单在正常环境执行，未执行项 NOT_RUN。_
  - _Depends: T041_
  - _Boundary: 不含真实业务资料、凭据或新增部署步骤，示例存在不代表已验收。_

## 4. 正式契约适配任务

以下任务全部 WAITING_EXTERNAL。只能在对应正式契约明确后细化字段并实施；若改变已确认需求、身份方式或领域边界，先更新设计确认，不擅自扩展。新增真实适配文件位于设计已确定的 `workflow/domain/clients/` 目录。

- [ ] **T043** [测试／后端] 固化正式接口合同样例
  - **文件**：`BT/test_platform_knowledge_real_contract.py`、`BT/test_platform_knowledge_authorization.py`。
  - **工作**：根据正式 OpenAPI 编写资源、用户委托、同步响应与来源、无匹配／拒绝／超时／限流测试；样例脱敏并标明版本，不把 Mock 字段直接要求对方实现。
  - **覆盖 AC: AC-02, AC-04, AC-05, AC-07, AC-08, AC-10, AC-11, AC-12, AC-13, AC-14, AC-17**。
  - _Requirements: REQ-01, REQ-03, REQ-04, REQ-05, REQ-06, REQ-07, REQ-09_
  - _Acceptance: AC-02, AC-04, AC-05, AC-07, AC-08, AC-10, AC-11, AC-12, AC-13, AC-14, AC-17_
  - _Verification: V-02, V-03, V-04, V-06；正式合同测试 NOT_RUN。_
  - _Depends: T042; EXT-01, EXT-02, EXT-03_
  - _Boundary: 测试先于真实实现；合同样例通过不等于访问真实昆联通过。_

- [ ] **T044** [后端应用] 接入已确认的外部授权能力
  - **文件**：`B/workflow/application/platform_knowledge.py`、`B/core/config/settings.py`。
  - **工作**：通过 F118 所属授权端口取得限时真实凭据，优先按对方确认规则复用 SSO Access Token；处理范围、过期和可信租户，不将凭据加入图、Redis 运行记录、队列或事件。
  - _Requirements: REQ-06, REQ-08, REQ-09_
  - _Acceptance: AC-11, AC-12, AC-15, AC-17_
  - _Verification: V-04, V-06；T043 授权合同及真实身份验收分别记录。_
  - _Depends: T043; EXT-02_
  - _Boundary: 不新建鉴权体系；Owner 端口未具备或需新能力时继续待执行并报告边界。_

- [ ] **T045** [后端适配] 实现真实目录与资源检查
  - **文件**：`B/workflow/domain/clients/platform_knowledge_real.py`、`B/workflow/domain/clients/platform_knowledge.py`。
  - **工作**：映射已授权资源列表、详情及现有等价使用权限检查，配置 real 装配；目录和字段假设替换后保留可追踪 TODO／确认记录，分页、错误和身份保持正式合同。
  - _Requirements: REQ-01, REQ-05, REQ-06, REQ-09_
  - _Acceptance: AC-02, AC-09, AC-10, AC-11, AC-12, AC-17_
  - _Verification: V-01, V-03, V-04, V-06；T043 资源合同，真实目录待验收。_
  - _Depends: T044; EXT-01_
  - _Boundary: 不预设新增预检接口、不强制知识内容版本，不降级 Mock；T046 未完成时 real 仍不可执行。_

- [ ] **T046** [后端适配] 实现真实同步检索
  - **文件**：`B/workflow/domain/clients/platform_knowledge_real.py`、`B/workflow/domain/services/platform_knowledge_service.py`。
  - **工作**：增量接正式 retrieve，映射请求、条数／大小／预算、来源和安全错误；校准 EXT-03 假设，不自动重试，不激活未确认的外部预览／下载链接，保留未解决替换 TODO。
  - _Requirements: REQ-03, REQ-04, REQ-06, REQ-07, REQ-08, REQ-09_
  - _Acceptance: AC-04, AC-05, AC-07, AC-08, AC-11, AC-12, AC-13, AC-14, AC-15, AC-17_
  - _Verification: V-02, V-03, V-04, V-05, V-06；T043 正式合同测试，真实检索另验。_
  - _Depends: T045; EXT-03_
  - _Boundary: real 只在目录、鉴权及检索均就绪后开放能力；不承诺远端取消或 exactly-once。_

## 5. 验证批次与待执行环境验收

### 5.1 主要验证入口

| Verification | 主要产物／任务 | 执行时机 | 当前状态 |
| --- | --- | --- | --- |
| V-01 | T011、T012、T014 的 API／组件测试；T042 人工步骤。 | W2 完成，W5 补正常浏览器证据。 | 本地通过（E-007、E-008），浏览器待执行 |
| V-02 | T005、T026 的合同／节点测试，正式协议阶段 T043。 | W1 服务规则完成；W4 补独立运行边界。 | 本地 Mock 通过（E-002、E-004 至 E-006），正式协议待确认 |
| V-03 | T020 发布事务、T026 Redis 竞争、T027 调度及 T041。 | W3／W4 完成，真实存储按 ENV-STORE 执行。 | 受控测试通过（E-003 至 E-006），真实存储待执行 |
| V-04 | T005 拒绝、T027 身份桥接、T041 普通用户；T043 真实合同。 | 相应入口接好后；真实身份需昆联环境。 | 本地身份及拒绝测试通过（E-002、E-005、E-006），环境验收待执行 |
| V-05 | T041 API E2E／独立导入、T042 浏览器清单及受影响旧节点回归。 | W5；正常 API／Broker／Worker／浏览器具备后执行。 | 本地导入及回归通过（E-005 至 E-008），正常链路待执行 |
| V-06 | T005／T011／T026／T041 模式边界，TODO 静态核对。 | W1／W4／W5 分别验证独立边界，相关代码未变不重复。 | 本地模式边界通过（E-002、E-005、E-007），正常链路待执行 |

后端复用 `src/backend/AGENTS.md` 的环境和命令，定向运行对应 `test/workflow/test_platform_knowledge_*.py` 及受影响 F119 测试；前端复用现有测试命令和 workspace 的 lint／typecheck／三语门禁。实施时先核对依赖与实际测试入口，不恢复或安装依赖来掩盖环境缺失。每个证据记录实际命令，不把本文模式路径当作已执行命令。

### 5.2 环境验收独立记账

| 验收项 | 需要的环境 | 证明内容 | 前置 | 当前状态 |
| --- | --- | --- | --- | --- |
| ENV-01 真实存储与授权 | 受控 MySQL、DM8、Redis、OpenFGA。 | 发布锁与并发编辑、Redis 原子停止／终态、普通用户拒绝；内存与 SQLite 不能替代。 | T024、T028、T038；ENV-STORE。 | NOT_RUN（待执行） |
| ENV-02 正常 Mock 运行链路 | 正常 API、Broker、Worker、Platform 浏览器和普通账号。 | 最小流程、保存重开、试运行、发布隔离、A／B、停止与旧节点兼容。无须等待昆联正式接口。 | T041、T042；ENV-RUN。 | NOT_RUN（待执行） |
| ENV-03 真实昆联身份与检索 | 昆联测试地址、授权方式、A／B／跨租户账号、测试库和异常样例。 | 同一查询的数据范围差异、真实命中与空结果、无权／过期／资源失效／错误／超时、真实来源。 | T046；EXT-01、EXT-02、EXT-03、EXT-04；正常运行环境。 | NOT_RUN（待执行） |

环境未齐时继续不依赖它的开发，缺项明确列为待执行。没有单独的部署、线上数据写入或自动创建测试账号任务。

### 5.3 AC 覆盖索引

下表列主要测试任务，补充入口风险可引用其他同批证据；不要求每条 AC 单独运行一次。

| AC | 主要测试任务 | Verification |
| --- | --- | --- |
| AC-01 | T005、T011、T014 | V-01 |
| AC-02 | T005、T011、T014 | V-01 |
| AC-03 | T012、T014 | V-01 |
| AC-04 | T005、T026 | V-02 |
| AC-05 | T005 | V-02 |
| AC-06 | T012、T020 | V-01、V-02 |
| AC-07 | T005、T026 | V-02 |
| AC-08 | T005、T026 | V-02 |
| AC-09 | T020、T041 | V-03 |
| AC-10 | T020、T026 | V-03 |
| AC-11 | T005、T027、T041 | V-04 |
| AC-12 | T005、T027 | V-04 |
| AC-13 | T005、T026 | V-02 |
| AC-14 | T026、T027 | V-02、V-03 |
| AC-15 | T027、T041 | V-04、V-05 |
| AC-16 | T005、T041 | V-02、V-04 |
| AC-17 | T005、T011、T026 | V-06 |
| AC-18 | T012、T041 | V-05 |
| AC-19 | T020、T027、T041 | V-05 |
| AC-20 | T012、T014、T041 | V-01、V-05 |

## 6. 批次完成记录与审查

2026-11-06 Mock 审查复验范围沿用既有验收标准。T007／T022／T025 检查断连变量预检，T027／T036／T038 检查公开入口的输入恢复顺序、已停止 Worker 的会话写入、混合图旧事件和普通图复用会话，T039 检查试运行终态，T014／T015 检查选库授权刷新与失败展示。对应 AC-02、AC-06、AC-09、AC-14、AC-19。缺陷、回归及环境待执行项见 [verification.md](./verification.md)。

任务规划已完成 V0 检查。实施按批次执行了本地后端、前端、发布事务、图引擎和独立导入验证，具体命令及结果见 [verification.md](./verification.md)。

未来每批完成后更新任务勾选与 `verification.md`，记录实际代码状态、测试范围及缺少的环境；本地测试通过和真实验收通过分别列出。全部 Mock 任务完成后按项目流程做 E2E 和特性代码审查，再据证据判断是否达到 Mock 阶段交付；真实环境缺项仍保持 NOT_RUN。

Mock 任务均有本地证据。正常 API、Broker、Worker、浏览器及真实昆联验收仍按第 5 节执行。

## 7. 实际偏差记录

- T039 补充既有全局错误处理器接线，使试运行使用 §6.3 约定的 HTTP 状态。
- T042 示例图使用现有表单输入的非空字段标签。工作流样例已通过本地图引擎验证。
