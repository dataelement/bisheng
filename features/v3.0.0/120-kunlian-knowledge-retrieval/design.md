# Design：昆联知识库检索节点

- **Feature ID**: F120
- **Status**: CONFIRMED
- **Confirmed**: 2026-11-05，用户确认设计，要求按 Mock 优先拆分任务并继续复用现有组件和变量机制。
- **Mode**: DESIGN_ONLY
- **Created / Updated**: 2026-11-05（Asia/Shanghai）
- **关联**: [已确认规格](./spec.md)、[版本契约](../release-contract.md)、[架构约束](../../../docs/constitution.md)。
- **当前阶段**: Mock 实现已落地。本地验证与待执行环境项见 [verification.md](./verification.md)，正式契约仍待确认。

## 1. 目标与非目标

在 Workflow 中新增独立的昆联知识库检索节点，优先组合现有问题选择、结果展示和变量引用组件，完成单库、单问题的同步检索。先通过默认可用的 Mock 验证配置、发布、试运行和「开始 → 输入 → 检索 → 输出」，真实协议通过适配器替换。

范围以 spec 为准：本期不做多库／批量问题、本地与外部混检、知识文档管理、检索算法调整、外部文档预览或下载、异步恢复及新增身份体系。大模型生成回答仍由已有大模型节点完成。

## 2. 关键约束

遵循架构约束 C1–C8 及版本契约；领域所有权不变。本设计不新增 SQL 表、迁移或依赖，不改造本地知识库权限策略。

- 新节点类型拟为 `platform_knowledge_retriever`；原 `knowledge_retriever` 及其图配置保持原义。
- 默认 `mock`，显式 `disabled`／`real` 生效。真实未就绪即拒绝，禁止自动回落模拟成功。
- 只支持已登录自然人；实际编辑者、发布者、试运行者和运行者分别鉴权。共享流程不继承创建人的昆联数据权限。
- 节点图、队列、事件及日志不携带令牌。真实外部凭据只能在服务端通过已确认的授权方式临时取得。
- 本地 Mock 初始约定：`top_k=5`，允许 1–20 的严格整数；查询最多 8192 个字符；节点总等待预算 5 秒；上游响应最多 1 MiB。这些值是毕昇侧开发约定，带 EXT-03 TODO，不宣称昆联已支持。
- 结果数量控制片段条数，不沿用本地 `max_chunk_size` 的文本长度含义。
- 页面使用现有设计规范和已交付 `@bisheng/ui` 控件，仅新增业务组合，不变更组件库样式、状态管理或依赖。

## 3. 方案对比与选定

### D-01 独立执行节点，复用现有交互与变量机制

- **备选**：扩展 `RagUtils` 增加外部检索分支；或者独立 `BaseNode`，在配置、输出和运行入口复用现有机制。
- **选定**：独立 `PlatformKnowledgeRetrieverNode`，不继承 `RagUtils`。
- **原因**：`RagUtils` 当前组合本地知识库／空间／临时文件、Milvus／ES、重排及本地文件元信息；其用户鉴权开关也允许配置者范围。直接继承会引入本期不需要且语义不同的能力。
- **重新考虑条件**：未来出现已确认、可同时表达本地与昆联检索的公共协议，再抽取纯结果处理或纯配置逻辑；不先构造通用检索框架。

### D-02 复用组合组件，固定单问题的输出标识

- **备选**：照搬多问题 `VarSelectItem` 并按问题变量生成输出 key；或者组合现有单选变量组件并固定输出 key。
- **选定**：组合 `VarSelectSingleItem`、`VarItem` 和现有变量校验；固定 `retrieved_result` 等输出标识，问题变化仅更新说明及校验状态。
- **原因**：现有 `VarSelectItem.valueToOutput` 通过切分上游路径生成 key，且默认多选。本期只有一个问题，动态 key 会使更换问题来源时下游引用失效，也不能直接表达常量。固定 key 仍通过原 `type: var`、`global` 和 `onOutPutChange` 声明输出。
- **重新考虑条件**：明确纳入批量问题时，再设计多问题与结果的稳定关联，不直接恢复旧的字符串切分规则。

### D-03 片段集合为主，便捷结果统一派生

- **备选**：仅输出拼接文本；直接透传昆联响应；或者归一为现有检索结果习惯的片段集合。
- **选定**：归一片段集合，同时派生文本、来源集合和数量，沿用既有根变量引用。
- **原因**：本地节点已返回含 `text` 和 `metadata` 的集合；现有变量选择器可以暴露多个根输出，无须新增 Schema 编辑器或深层字段选择协议。外部来源不能直接交给假设本地文档 ID 的引用助手。
- **重新考虑条件**：双方确认外部引用打开协议后，单独适配引用注册／预览；不把远端 ID 转成本地文件 ID。

### D-04 Mock 在服务端适配，外部授权独立替换

- **备选**：前端写死下拉选项或失败时补假结果；或者在正常服务调用边界装配 Mock Provider。
- **选定**：使用服务端 `PlatformKnowledgeProvider`，目录、状态和检索均走正常 API／节点链路。
- **原因**：需要覆盖权限、发布和 Worker，前端假数据只能证明控件有内容。F119 真实模式目前也只拒绝未就绪调用，不能视为已有通用昆联令牌委托实现。
- **重新考虑条件**：EXT-01 至 EXT-04 确认后新增真实适配器；优先复用已确认的 SSO Access Token，不预设新增鉴权接口。

### D-05 发布一次提交，检索结果受本次运行约束

- **备选**：先发布 Agent 再校验检索；复制整套 Agent 执行账本；或者复用发布事务模式，检索使用轻量运行上下文。
- **选定**：含新节点的流程先完成所有外部节点校验，再一次提交发布；检索以 Redis 保存临时运行事实，限制本次执行的输出提交。
- **原因**：当前 Agent 发布入口提前返回，简单追加检索校验会被跳过或导致部分发布。检索是只读操作，无须 Agent 的远端运行账本，但只靠进程内 `stop_flag` 不能拦住跨进程停止后的迟到结果。
- **重新考虑条件**：需要跨长时间恢复或远端副作用时，再评估持久账本；若需要新表或改变已确认的退出规则，先重新确认范围。

## 4. 系统现状与拟实施方案

### 4.1 已核对的现有实现

| 位置 | 当前作用 | 本期复用边界 |
| --- | --- | --- |
| `src/frontend/platform/src/controllers/API/workflow.ts` | 本地检索模板包含用户问题、检索范围、过滤、高级检索和输出。 | 保留模板装载入口，新模板放独立文件，避免复制扩展长文件。 |
| `FlowNode/component/VarSelectItem.tsx` | 多问题组件、导出的 `VarSelectSingleItem`，包含变量选择和有效性校验。 | 复用单选组件和 `SelectVar`；不直接复制多问题派生 key。 |
| `FlowNode/component/VarItem.tsx`、`Parameter.tsx` | 展示输出变量并根据参数类型装配组件。 | 直接展示根输出，新增少量参数类型接线。 |
| `FlowNode/component/KnowledgeSelectItem.tsx` | 查询本地库／空间／临时文件并多选。 | 参考交互，数据源和多选语义不适用；新建薄的昆联单库组合。 |
| `FlowNode/RunTest.tsx`、`RunLog.tsx` | 从参数类型提取试运行输入，展示日志。 | 复用页面；补新问题类型的变量提取和参数标签。 |
| `src/backend/bisheng/workflow/nodes/knowledge_retriever/knowledge_retriever.py` | 返回文本与元信息片段集合，设置本地来源／引用隐变量；异常可能作为结果字符串返回。 | 参考结果语义，外部节点独立处理来源和失败。 |
| `workflow/graph/graph_state.py`、`nodes/base.py` | 存取根变量和一级 `#` 索引；`BaseNode.run` 通过 `output_commit_scope` 写结果。 | 复用变量池和提交钩子；区分缺失与合法 null。 |
| `api/services/workflow.py` | `run_once` 对大多数节点直接调 `_run`，Agent 单独执行受理与 `run`；`update_status` 存在 Agent 发布分支。 | 新节点必须显式接入受理、提交钩子和统一发布，不能只注册类型。 |
| `workflow/application/platform_agent.py`、Worker 及 `RedisCallback` | F119 已覆盖部分可信身份、冻结图、调度和输出约束。 | 复用模式和可抽取的发布事务；不把检索调用存进 Agent 执行表。 |

表中 `FlowNode/` 相对 `src/frontend/platform/src/pages/BuildPage/flow/`，`workflow/` 相对 `src/backend/bisheng/`。上述为复用依据。F120 验证结果见 [verification.md](./verification.md)。

### 4.2 目标数据流

```mermaid
flowchart LR
    A[现有画布与变量选择] --> B[Workflow 检索应用服务]
    B --> C[本地身份与工作流授权]
    C --> D[目录及检索 Provider]
    D --> E[Mock 或已确认的真实适配器]
    E --> F[校验片段与外部来源]
    F --> G[本次运行的输出提交检查]
    G --> H[原变量池与节点事件]
    H --> I[输出节点或大模型节点]
```

配置、发布、试运行和运行共用配置解析及输出归一规则。浏览器不直接调用昆联，不接受其自行声称的用户、租户或执行模式。

### 4.3 节点配置与变量合同

新类型 `platform_knowledge_retriever`，节点版本 `v: 1`。仍存于原 Workflow 图的 `group_params`，不新建配置表。

解析时拒绝重复节点 ID、重复参数 key、节点外层 ID 与 data.id 不一致、超出本期配置的字段和多值选库；下游输出声明必须匹配本地固定合同，不能直接相信前端声明。

| 参数 key / type | 值与约束 |
| --- | --- |
| `user_question` / `platform_knowledge_query` | 常量为 `{"source":"constant","value":"轴承温度异常如何处理？"}`；变量为 `{"source":"variable","variable":"input_x.question"}`。仅保存当前分支，拒绝多问题及未知字段。 |
| `knowledge` / `platform_knowledge_select` | `{"resource_id":"mock:maintenance"}`，仅一个非空字符串 ID；连接由服务端选择，不保存 URL、身份和令牌。 |
| `top_k` / `number` | 严格整数，Mock 默认 5、范围 1–20；布尔、字符串和小数无效。 |
| `retrieved_result` / `var` | `value` 中声明下表的四个固定根输出，使用原 `global` 输出枚举方式。输出声明由服务端按类型重建校验，不能借图配置新增伪造输出。 |

| 输出 | 类型 | 用途 |
| --- | --- | --- |
| `retrieved_result` | 片段数组 | 主结果，与现有检索节点一样可交给下游作为整体变量。 |
| `retrieved_text` | 字符串 | 逐条以文档标题、已有位置及正文组织的文本，便于输出或提示词使用。 |
| `citations` | 来源数组 | 与片段顺序一致的来源摘要，无预览或下载承诺。 |
| `hit_count` | 整数 | 与片段数组长度一致，可用于已有条件节点。 |

示例引用：`{{#platform_knowledge_x.retrieved_text#}}`。界面通过原变量选择器插入，无须用户手写。片段数组可整体下传；不新增对 `result#0.text` 等深层路径的承诺。

服务端引用校验也必须识别四个输出：当前 F119 的 `validate_reference` 不枚举普通 `type: var` 数组中的所有别名。实施时针对新节点按其固定合同识别 `retrieved_text` 等输出，保证检索结果可以传给 Agent；检索问题也可引用已有 Agent 的合法结果字段，并在执行时检查实际文本类型。不放宽为接受任意前端 output 声明。

归一后的单条片段示例：

```json
{
  "text": "优先检查润滑和负载，按设备规程处理温度异常。",
  "metadata": {
    "provider": "kunlian",
    "connection_id": "kunlian",
    "knowledge_id": "mock:maintenance",
    "document_id": "mock:doc-001",
    "chunk_id": "mock:chunk-001",
    "document_name": "模拟设备维护手册",
    "location": "第 12 页"
  },
  "score": 0.91
}
```

`metadata` 按白名单保留远端字符串标识，不解析成本地整数 ID；`document_name` 可缺省，但必须有非空库、文档及片段或等价定位信息。`location`、`score` 可缺省；Mock 使用文档和片段 ID，真实等价定位的映射留 EXT-03 TODO。校验所选库与每条命中所属库一致，类型、正文、来源或大小异常均使本次节点失败，不保留半份结果。分数只展示，不重新排序或推导阈值。

`citations` 仅从这些片段派生标题、库／文档／片段标识及已有位置；不调用本地 `annotate_rag_documents_with_citations`，不写本地文件引用注册和来源隐变量。外部 `citation_key`／URL 在未确认前不激活。`retrieved_text` 采用纯文本组织，下游展示沿用原文本处理，不渲染上游原始 HTML。

输入解析区分三种情况：配置未填或变量路径不存在 → 配置错误；已声明、确实存在的变量为 null／空白文本 → 身份及资源检查通过后返回四项空结果，且不调用 `retrieve`；非文本非 null → 输入错误。不能仅以 `GraphState.get_variable()` 返回 None 认定变量存在，也不调用会把任意对象转字符串的本地问题规范化函数。

配置校验沿画布连线向上游查找问题变量的来源节点，再校验它声明的输出。断开连线和自引用不能通过预检。单节点试运行只允许试填已选择的问题变量，编辑器先对完整图校验，再提交试填值。

### 4.4 前端组件复用

| 部分 | 拟实施方式 |
| --- | --- |
| 问题输入 | 新 `PlatformKnowledgeQueryItem.tsx` 组合已有 `VarSelectSingleItem` 与共享文本输入，提供“变量／常量”。适配旧组件接收的字符串 `value`，保留变量名称更新、存在性校验及 `onVarEvent`。 |
| 结果联动 | 问题修改时通过原 `onOutPutChange('retrieved_result', descriptors)` 更新输出说明，四个 key 保持不变；常量也有对应结果变量。下游引用使用 `isVarInFlow` 和原变量事件机制。 |
| 选库 | 新 `PlatformKnowledgeSelectItem.tsx` 使用已交付 `@bisheng/ui` 单选及 `useSelectLabels`。只加载授权昆联目录，不调用 `readFileLibDatabase`，不带本地库／空间／临时文件 Tab。 |
| 结果数量与输出 | 复用 `InputItem` 数字输入和 `VarItem` 输出展示；不复用包含本地权重、重排、鉴权开关的 `RetrievalWeightSlider`。 |
| 目录请求 | 独立 API 模块通过现有请求封装调用后端；React Query v4 管理目录与详情，Zustand 仅保存图配置。 |
| 节点接线 | 原模板装载、Sidebar、Parameter、NodeLogo 和必要的节点类型样式接线；复用本地检索的已有视觉表达，不新增样式方案。 |
| 试运行 | `RunTest` 识别 `platform_knowledge_query`：变量分支只生成该变量的试填字段，常量分支不生成；执行前清空上次结果，仍调用既有 `run_once`。 |
| 日志 | 继续原日志视图，补参数和来源标签，不新增运行详情页面。 |

目录缓存 key 包括用户、有效租户范围、Workflow、模式、连接和策略修订；搜索条件放入查询 key，分页使用 `pageParam`。能力请求只依赖登录用户，不以前端可选的 `tenant_id` 为硬门槛；租户显示范围取 `tenant_id ?? leaf_tenant_id`，只有后端明确 `multi_tenant_enabled=false` 才允许 `single-tenant` 缓存范围。后端仍确定真实租户，缺失多租户上下文不请求目录。

切换用户、租户、模式或连接后移除旧目录缓存；保留图中已选 ID，但标记需要重新校验，不能继续展示旧权限结果。过滤空 ID 后再渲染选择项；错误使用现有请求错误处理，不自建 403 分支。加载、无可用库、失败和已选资源失效分别显示。Mock 以“模拟数据”标识，业务界面不显示 EXT 或 TODO 内部编号。

目录或详情刷新失败时，查询库可能仍持有上次成功的响应。选库以当前请求成功状态为准，详情失败时移除失效选项并阻止通过节点校验。目录拒绝使用已有业务错误文案，与空目录和查询失败分别展示。

### 4.5 后端职责与接口

`Endpoint → PlatformKnowledgeService → Provider／Workflow Repository`。应用装配读取服务端配置并注入身份和运行上下文；节点只负责解析变量、调用服务和返回根输出。Router 不跨模块访问用户、SSO 或权限实现。

| 毕昇接口 | 请求／响应与调用方 |
| --- | --- |
| 既有 `GET /api/v1/env` | 增加 `workflow.platform_knowledge_enabled`、`platform_knowledge_mode`、`platform_knowledge_policy_revision`、`platform_knowledge_connection_id`，并透传既有顶层 `multi_tenant_enabled`。Mock 就绪时 enabled 为 true，disabled 或当前未就绪的 real 为 false；已保存节点仍可查看。 |
| `GET /api/v1/workflow/platform-knowledge` | `workflow_id`、可选 `cursor`／`name`；返回 `items:[{resource_id,name,status,provider_mode}]`、`next_cursor`。空成功返回空列表。 |
| `GET /api/v1/workflow/platform-knowledge/{resource_id}` | `workflow_id`；返回当前有权使用的资源摘要及本地支持的检索约束，不返回凭据，不要求知识库版本。ID 经过编码，按不透明标识处理。 |
| `POST /api/v1/workflow/platform-knowledge/validate` | `{"workflow_id":"...","graph":{},"node_id":"可选"}`；有效返回 `{"valid":true,"issues":[]}`，配置问题返回按节点和字段定位的 issues；身份／权限错误走标准错误合同。仅校验，不检索、不保存图。 |
| 既有节点试运行及 Workflow 入口 | 通过原入口执行，不新增浏览器直调检索接口；试填值只允许覆盖所选问题变量，不能改变身份、模式、资源或发布绑定。 |

Provider 的本地协议为 `list_knowledge(actor, cursor, name)`、`get_knowledge(actor, resource_id)`、`check_use(actor, resource_id)`、`retrieve(actor, resource_id, query, top_k, call_id)`。`check_use` 是适配器能力，可复用详情判权，不表示昆联必须新增接口。所有返回经过本地严格归一校验。

`authorize` 先由 Workflow Repository 读取业务目标，结合 `user.application.runtime_identity.read_current_person_facts` 核对当前用户状态、租户及 token_version，再经 F048 入口检查 `edit`／`publish`／`use`。目录、校验和试运行使用 edit；发布使用 publish；已发布运行使用 use。服务端生成 actor，不接受业务载荷中的身份字段。

### 4.6 发布、试运行和正式运行

**发布**：只在候选图或当前已发布图包含本特性时进入平台节点发布协调，保证移除最后一个新节点时也能清理旧绑定。

1. 从服务端读取目标 FlowVersion，确认归属、发布权限，取得候选图；同时剥离两个服务端绑定 `_platform_agent_publication` 与 `_platform_knowledge_publication`，不信任客户端传来的绑定。
2. 在同一候选图上完成新节点配置、问题引用和当前发布者的昆联资源可用性校验；有 Agent 时复用其版本／Schema 预检。校验期间不持有数据库事务。
3. 将结果制成各自绑定：检索绑定保存 `binding_version`、候选图摘要、模式／连接／策略修订、各节点选库／问题映射／top_k 摘要，不保存知识内容快照或令牌。
4. 共用一次发布事务：锁定 Flow 和目标 FlowVersion，复核候选图摘要，保存两个绑定、当前版本及 ONLINE 状态。任一校验失败或并发编辑导致摘要变化时不发布。

拟从 F119 的 `publish_validated_graph` 抽取 `platform_node_publication.py` 中的纯候选图处理与发布 Repository；F119 原方法保留委托入口，原 Agent-only 语义不变。将其预检整理为 `prepare_publication`，由新协调器组合；Agent 预检结果仍由原领域服务产生，不复制到检索服务。不得先提交 Agent 发布，再追加知识校验。只有 F119 的图仍沿用原入口，并回归验证摘要和发布行为。

保存／切换／删除版本时，将当前 `api/services/flow.py` 对 Agent 图的保护分支扩展到含检索节点或检索绑定的版本；复用上述 Repository 的事务模式。已发布版本不可经草稿保存覆盖，复制和导入时移除服务端绑定并重新校验，移除最后一个检索节点不遗留旧绑定。原图没有平台节点时继续沿既有分支，不能通过另一个版本入口绕过发布检查。

**节点试运行**：`run_once` 为新类型构造受理上下文、校验声明的变量输入，调用 `node.run()`，再按既有响应格式返回日志。不得沿用该方法对普通节点直接调 `_run()` 的分支，否则会绕过输出提交检查。未保存草稿可试运行，但必须有 Workflow edit 权限。

**正式／画布运行**：API 受理时冻结服务端认定的图和实际操作者引用；已发布运行只取发布版本。浏览器 WebSocket、认证 v2／公开入口适配及 Worker START／CONTINUE 都必须携带同一服务端生成的检索执行引用，Worker 再读取当前身份与权限。应用层拟提供 `BrowserPlatformKnowledgeRuntime.prepare/resume/abort`，由已有路由装配后注入 common 层端口；对称传递的队列参数为 `platform_knowledge_execution`，只含执行引用。无实际自然人或上下文缺失时拒绝，不回退创建人；即便某入口漏接上下文，新节点也必须拒绝执行。

**同步检索步骤**：本次执行有效性与本地授权 → 配置和问题实际值校验 → 当前模式及外部资源使用检查 → 空值短路或一次 `retrieve` → 全量归一与来源校验 → 提交输出。默认不自动重试，鉴权／限流／超时均明确失败。节点通过 `bisheng.utils.async_utils.run_async_safe(..., timeout=None)` 调用受总预算保护的异步服务，不导入 Worker 包装配任务。

### 4.7 运行上下文、停止和迟到结果

仅对包含新节点的图增加 `platform_knowledge_context`，与 F119 的 context 并存，互不伪装。临时运行事实保存在 Redis，使用专属前缀及与既有 Workflow 一致的 7 天清理 TTL；缓存丢失或过期时拒绝继续执行，不从进程内旧图恢复。无新 SQL 表，也不修改 `workflow_platform_agent_execution` 的语义。

- 受理记录包含随机 `execution_id`、session／Workflow／版本、冻结图、操作者 ID／租户／token_version、环境指纹和状态。队列只传引用，不传令牌；记录由服务端创建，不接受客户端自填。
- 同一 session 的“当前执行引用”按用户／租户及 Workflow 隔离，替换时使旧执行失效。START 通过原子领取产生 owner token，重复消息不能领取已运行记录；本期不自动恢复 Worker 崩溃的在途执行。
- 每次节点调用使用 `execution_id + node_id + step + call_id`，在发起和输出提交时核对当前执行、owner、状态、token_version 和模式／连接／策略；提交前重新通过 Owner 读取当前身份并检查 Workflow 动作，不只比较受理时保存的旧值。节点总预算从服务调用开始覆盖授权、资源检查和检索，不以外层桥接超时替代。
- 停止请求先在 Redis 原子标记该执行停止，再通知原有 `workflow.stop()`；本次失败、超时和终态同样使后续提交失效。旧停止消息只能作用于匹配的 execution_id，不能停止新一轮。
- 使用 `BaseNode.output_commit_scope` 暂存和保护本节点输出，Redis 原子比较并提交对应 step 的有效结果；失败或失效时回滚变量池中本节点的临时修改。新节点开始时清除上轮四项输出，失败不复用上次命中。
- 仅有提交前的一次 GET 不足够。事件入队及下一节点开始也按当前引用和状态原子校验；停止与提交有明确先后，停止之后不允许新提交或继续调度。终态写入不覆盖既有终态，成功事件不得在停止后重新写出。
- 对新节点图的 `RedisCallback` 增加检索执行引用并在消费前去掉内部标记；当前 F119 引用检查继续生效，混合图必须同时满足两者。节点执行入口检查保护该图的后续节点，旧执行不能借其他节点继续输出。
- 已发布入口先校验输入消息归属和结构，再领取恢复权及写入本轮输入。错误输入可以更正重提。重新启动已移除检索节点的已发布流程时，先清理同会话残留的检索引用，再写普通或 Agent 运行数据。
- 混合图消费事件时复核事件携带的 Agent 引用。Worker 开始持久化会话消息前检查检索执行和混合图中的 Agent 引用仍有效，试运行只在 Redis 接受成功终态后返回结果。Redis 与会话数据库是独立存储，已开始的会话写入不具备跨库撤销能力。

上述 Redis 检查由 `platform_knowledge_run.py` Repository 的原子操作完成；远程请求不在锁或事务中运行。停止不能保证昆联远端已经取消；本期承诺停止后不接收迟到结果、不推进后续节点。只读查询的重复远端执行仍可能出现在网络边界，不能宣称远端 exactly-once。

### 4.8 Mock 与真实来源

配置拟为 `WorkflowConf.platform_knowledge: PlatformKnowledgeConf`，采用 `mode`、`connection_id`、`policy_revision`、`retrieve_timeout_seconds`、`max_payload_bytes`、可选 `mock_subjects`。数量、查询、等待和响应限制按 §2 本地约定，模式默认 mock、连接默认 kunlian、策略默认 mock-v1；无映射时通用样例可用，不要求修改 YAML 才展示目录。

| Mock 内容 | 行为 |
| --- | --- |
| `mock:maintenance`，设备维护示例 | “轴承温度异常”等查询返回固定维护片段及来源；不匹配返回空集合，不对所有查询返回同一答案。 |
| `mock:policy`，制度查询示例 | 返回另一组文档片段，验证选库和结果归属。 |
| `mock:private`，私有知识示例 | 专项 A 身份可使用；B 不可使用，便于 A 发布／B 拒绝测试。 |
| 同库文档范围样例 | 在 A／B 均可使用的示例库内设置共同片段与仅 A 可见片段；相同查询按模拟用户裁剪，验证 B 看不到 A 专有文档，不只测试整库拒绝。 |
| 专项用户 A／B／C | 默认通用用户为 B，C 无可用库；测试使用真实本地账号映射模拟外部授权，不改变本地实际用户 ID 和权限。 |
| 故障样例 | 通过专属模拟场景资源提供错误、超时、失效、畸形来源和跨库响应；名称明确为模拟场景，原始非法响应仅供测试，不进入正常结果。 |

特殊映射只在服务端配置，键采用与 F119 一致的 `"tenant_id:user_id"`，值为 A／B／C；非空映射中未登记的主体拒绝，不自动分配通用身份。模拟目录和正文均为合成数据，不包含真实业务资料。

真实 `mode=real` 在协议和身份能力未齐备时抛 NotReady，不能使用上述样例。Provider 和模式在调用前、结果提交前再次核对，运行中切换不得使模拟结果进入真实运行。公开能力只返回安全模式信息，不暴露映射或凭据。

### 4.9 拟实施文件结构

以下为实现落点。路径以仓库根目录为基准；未列出的邻接重构不自动纳入。

| 新增／修改 | 文件或目录 | 职责 |
| --- | --- | --- |
| 新增 | `src/backend/bisheng/workflow/domain/schemas/platform_knowledge.py` | 配置、Provider 结果、actor 及四项输出合同，严格校验。 |
| 新增 | `src/backend/bisheng/workflow/domain/clients/platform_knowledge.py`、`platform_knowledge_mock.py` | Provider 协议、服务端模式装配和合成目录／命中／故障样例。 |
| 新增 | `src/backend/bisheng/workflow/domain/services/platform_knowledge_service.py` | 授权、目录、校验、检索预算、输出归一。 |
| 新增 | `src/backend/bisheng/workflow/domain/repositories/platform_knowledge_run.py` | Redis 受理、领取、停止、结果与事件有效性原子检查。 |
| 新增 | `src/backend/bisheng/workflow/domain/repositories/platform_node_publication.py` | 抽取现有 Flow／FlowVersion 发布事务及候选图归一，不新增表。 |
| 新增 | `src/backend/bisheng/workflow/application/platform_knowledge.py`、`platform_node_publication.py` | 运行上下文装配及混合节点发布协调；不自行查用户表或跨越 Owner。 |
| 新增 | `src/backend/bisheng/workflow/api/endpoints/platform_knowledge.py`、`nodes/platform_knowledge_retriever/` | 上述 API 及独立 BaseNode；不导入 Worker 来解决异步桥接。 |
| 修改 | `src/backend/bisheng/workflow/api/router.py`、`common/node.py`、`nodes/node_manage.py` | 路由和节点注册。 |
| 修改 | `src/backend/bisheng/core/config/settings.py`、`api/v1/endpoints.py` | 默认 Mock 配置及 env 能力输出。 |
| 修改 | `src/backend/bisheng/api/services/workflow.py`、`workflow/domain/services/platform_agent_service.py`、`workflow/domain/repositories/platform_agent.py` | run_once 新分支、发布协调和已有发布事务委托；Agent-only 行为保持。 |
| 修改 | `src/backend/bisheng/api/services/flow.py`、`api/v1/workflow.py`、`public_endpoints/api/endpoints/workflow.py` | 含检索节点版本的编辑／切换／删除保护，浏览器及公开端口运行适配注入；不绕过原有动作权限。 |
| 修改 | `src/backend/bisheng/workflow/graph/{workflow,graph_engine}.py`、`workflow/nodes/base.py` | 仅为受保护的新节点图传递上下文，提交及调度检查；其他图沿原路径。 |
| 修改 | `src/backend/bisheng/common/chat/{manager.py,clients/workflow_client.py}`、`worker/workflow/{tasks,redis_callback}.py` | 浏览器受理、队列、停止、事件和上下文恢复接线，不在 common 中依赖领域实现，按现有运行端口注入。 |
| 修改 | `src/backend/bisheng/workflow/domain/services/published_workflow_service.py` | 认证／公开运行适配共用受理，缺少自然人时拒绝新节点。 |
| 新增 | `src/frontend/platform/src/controllers/API/platformKnowledge.ts`、`src/frontend/platform/src/types/flow/platformKnowledge.ts` | 独立 API、能力读取、模板和类型。 |
| 新增 | `src/frontend/platform/src/pages/BuildPage/flow/FlowNode/component/{PlatformKnowledgeQueryItem,PlatformKnowledgeSelectItem}.tsx` | 组合既有单选变量、输出联动及单库选择。 |
| 修改 | `src/frontend/platform/src/controllers/API/workflow.ts` | 引入独立新模板，保留原节点模板定义。 |
| 修改 | `src/frontend/platform/src/pages/BuildPage/flow/{Sidebar.tsx,FlowNode/Parameter.tsx,FlowNode/NodeLogo.tsx,FlowNode/index.tsx,FlowNode/RunTest.tsx,FlowNode/RunLog.tsx}` | 节点展示、组件装配、试运行及日志标签。 |
| 修改 | `src/frontend/platform/public/locales/{zh-Hans,en-US,ja}/flow.json` | 同批新增三语文案，既有业务词保持一致。 |
| 修改 | `src/backend/bisheng/common/errcode/flow.py`、`src/frontend/packages/locales/src/api_errors/{zh-Hans,en,ja}.json` | 错误定义与三语源；生成产物通过既有脚本生成。 |
| 新增 | `src/backend/test/workflow/test_platform_knowledge_*.py`、相应前端组件／API 测试 | 按 §7 独立风险提供验证，不扩大无关全量测试。 |

若实施发现新增业务表、改变既有领域接口所有权或需要额外公共 API，则先回到设计确认，不通过扩大本表直接授权。

## 5. 已知坑与处理位置

| 事实与证据 | 不处理的影响 | 设计处理位置 |
| --- | --- | --- |
| `VarSelectItem` 默认多选，并从路径生成输出 key。 | 常量难以表达、更换问题使下游变量失效。 | 新问题组合使用导出的单选组件；固定根输出。 |
| `GraphState.get_variable` 对缺失和 null 均可返回 None。 | 失效变量被当作合法空查询。 | 新配置解析／节点取值先检查声明和存在性，再取值。 |
| F119 `validate_reference` 当前不枚举普通 var 数组的全部输出别名。 | 编辑器可选中检索文本，但混合图的 Agent 发布校验拒绝该引用。 | 新类型按固定输出合同补双方引用识别，补混合图连线验证。 |
| 本地高级检索包含 `user_auth=false`，知识空间可采用配置者范围。 | 直接套用可能按创建人检索。 | 新服务始终使用实际操作者，界面不提供关闭开关。 |
| 本地检索节点对异常可能返回字符串。 | 上游失败会被当作检索结果继续输出。 | 新节点抛安全业务错误，不复制异常变结果的分支。 |
| 本地来源助手依赖本地文档身份及引用注册。 | 远端 ID 被当成本地 ID，出现错误链接或串引用。 | 新结果仅携带明确外部来源，不调用本地注册助手。 |
| 当前 run_once 多数节点直接执行 `_run`；BaseNode 的 stop 检查主要在开始。 | 试运行跳过提交保护，在途结果可能停止后写回。 | 新类型执行 node.run；运行 Repository 与提交／事件／调度共同检查。 |
| 现有 Agent 发布分支完成后即返回。 | 混合图的知识库校验被漏掉或分两次发布。 | 发布协调器预检所有平台节点，事务一次提交。 |
| F119 当前 `/user/info` 适配需要兼容 leaf_tenant_id 与单租户缺少租户字段。 | 新节点照旧字段门槛实现会出现空目录。 | 能力查询及目录缓存按 §4.4，后端确定真实租户。 |
| 节点导入 Worker 容易反向触发任务注册；API 与 Worker 的进程初始化不同。 | 启动循环导入或仅 API 可用。 | 复用 utils 异步桥；API／Worker 各自装配 Provider 和 Repository。 |

## 6. 对外契约与依赖

### 6.1 提供的合同及兼容性

- 新前端 API 见 §4.5；新增 env 字段，不改变原成功响应和其他节点接口。
- 新节点图参数与四个根输出见 §4.3；固定 key 是下游引用合同。未来更名或改变类型需升级节点合同，不能静默替换。
- 内部应用入口提供 `get_service`、`prepare_execution`、`claim_execution` 和浏览器运行端口的 `resume`／`abort`；领域服务提供目录、校验、`prepare_publication` 和 `retrieve`。调用方只传业务目标及服务端运行引用。
- Redis 回调内部标识不透出前端，不改变 Workflow 公共事件类别。新增元信息使用现有节点 params／variable 日志形式。
- 旧图无需迁移；不含新节点的运行不创建检索上下文。部署回退到不认识新类型的代码前，必须先停止或下线含新节点的流程，不把它静默当作本地节点。

### 6.2 依赖与待替换 TODO

| EXT | 依赖／替换位置 | 风险与替换条件 |
| --- | --- | --- |
| EXT-01 | Provider 目录、详情和 check_use；选库及发布材料。 | 昆联正式资源标识、状态、权限和可能的修订语义未确认。优先采用已有等价接口，不强制内容版本。 |
| EXT-02 | 应用装配中的外部授权端口，真实 Provider 获取凭据的边界。 | 现有 SSO 不自动保证 Token 可调用检索。取得可用范围、租户、有效期和用户委托规则后，经 F118 所属授权能力接入；本地身份端口不负责返回外部 Token。 |
| EXT-03 | retrieve 请求、严格响应归一、超时／数量／大小约定与错误映射。 | 正式请求、结果来源及失败语义未确认；不能将本地 Mock JSON 作为要求对方照做的新协议。 |
| EXT-04 | Mock 样例来源说明、真实联调步骤与验证记录。 | 需要 OpenAPI、Base URL、测试库／文档、A／B／跨租户账号及异常样例；齐备前真实验收 NOT_RUN。 |

实现时每个临时数据、模拟调用和协议假设均保留中文注释，例如 `# TODO [F120][EXT-03] 当前为单库模拟检索响应，正式协议确认后替换并补真实验证。` 前端使用合法 `// TODO`。场景数据可收口为一个带来源说明的样例集合，不要求每条片段重复注释。真实适配需要新的服务配置时再提供模板，本轮不修改任何运行中配置。

基础设施复用现有 Redis、Workflow SQL 存储、身份和 F048；不新增二进制、依赖包、向量库集合或文件共享目录。Redis 不可用、身份读失败、授权不可判定均拒绝执行；不能使用未过滤目录或旧结果继续。

### 6.3 错误处理

本地身份和 Workflow 拒绝沿既有鉴权错误合同。检索错误已登记为 Workflow 模块的 10563–10570，分别对应配置、昆联授权、资源不可用、模式关闭／未就绪、上游失败、输出异常、执行失效和超时。

HTTP 状态分别采用 400、403、409、503、502、502、409、504；本地身份失效仍沿原 401 等合同。安全原因可标识 disabled、not_ready、permission_denied、resource_unavailable、rate_limited、upstream_error、invalid_output、execution_invalidated、timeout；不透传上游响应正文和认证信息。未知异常记录脱敏定位信息，再转安全失败，禁止 `str(e)` 写入用户结果。

## 7. 验证策略、追踪与可观测

### 7.1 需求覆盖

| Requirements | AC | 设计位置 | 验证 |
| --- | --- | --- | --- |
| REQ-01 | AC-01、AC-02 | §4.4、§4.5、§4.8 | V-01 |
| REQ-02 | AC-03、AC-06、AC-20 | §4.3、§4.4 | V-01、V-02、V-05 |
| REQ-03 | AC-04、AC-05 | §2、§4.3、§4.6 | V-02 |
| REQ-04 | AC-04、AC-05、AC-07、AC-08、AC-18、AC-20 | §4.3、§4.6 | V-01、V-02、V-05 |
| REQ-05 | AC-06、AC-09、AC-10 | §4.6 | V-01、V-02、V-03 |
| REQ-06 | AC-02、AC-11、AC-12 | §4.4、§4.5、§4.6 | V-01、V-04 |
| REQ-07 | AC-08、AC-10、AC-13、AC-14 | §4.6、§4.7、§6.3 | V-02、V-03 |
| REQ-08 | AC-15 | §4.4、§4.7、§6.3 | V-04、V-05 |
| REQ-09 | AC-01、AC-16、AC-17 | §4.8、§6.2 | V-01、V-02、V-04、V-06 |
| REQ-10 | AC-07、AC-18、AC-19、AC-20 | §3、§4.3、§4.4、§6.1 | V-01、V-02、V-05 |

### 7.2 最小充分的行为证据

- V-01：组件层覆盖选库、空／失败态、单问题、常量切换、固定输出声明、保存重开和用户／租户缓存隔离，不重复测试共享控件内部实现。
- V-02：服务与节点的定向集成覆盖严格查询与数量、有效 null／空白短路、正常／空结果、非法来源、失败及总预算，断言失败没有旧结果、空变量没有 retrieve 调用。
- V-03：发布事务和 Redis 原子边界覆盖并发编辑、Agent＋检索混合发布全成全败、撤权／失效、停止与结果提交竞争、旧调度及终态不覆盖；使用真实事务／Redis 验证独立边界，内存替身不证明原子性。
- V-04：非管理员 A 发布／B 运行、库内文档裁剪、跨租户、token_version 变化和缺身份拒绝；秘密探针不得出现在事件或输出。Mock 只证明毕昇处理，不证明昆联真实鉴权。
- V-05：正常 API、Broker、Worker 和浏览器跑最小流程；复用原变量选择将结果接至输出／大模型，并验证检索文本传给 Agent、Agent 文本字段传给检索问题的服务端引用校验；相关本地检索、Agent-only 及混合图回归。独立进程直接导入实际 API 和节点，避免测试预加载掩盖循环导入。
- V-06：省略配置默认 Mock、显式关闭、real 未就绪、运行中切换来源及 TODO 清单，验证 API 与 Worker 两个角色一致。

实施时按行为批次运行，复用相同代码状态的证据。涉及共享组件、发布和调度只扩大到受影响回归，不为每条 AC 重复跑全套测试。前端执行相关组件测试、lint／typecheck／三语校验；后端执行对应模块测试和架构检查。具体命令在 tasks 和 verification 中依据实际新增文件落定。

### 7.3 手动验收路径

未来实施后在已启动的本地 Platform `http://localhost:3001` 中，用有 Workflow edit／publish／use 权限的普通账号：

1. 新建 Workflow，连接开始、文本输入、昆联检索和输出；选择模拟设备维护库，问题绑定输入变量，结果数量用默认 5。
2. 输出节点通过原变量选择器引用检索的 `retrieved_text` 及来源；运行“轴承温度异常如何处理？”，核对片段和模拟来源。保存重开后，配置和引用不变。
3. 更换无匹配问题得到零命中；有效问题变量为空时成功空结果。再选故障样例，确认错误／超时不会输出上轮文本。
4. 运行中停止或开始新一轮，等待旧模拟延迟返回，确认没有迟到节点结果和下游输出。
5. 发布后修改草稿，不影响已发布选库与配置。专项 A 发布私有库流程，授权 B 运行 Workflow，B 应被昆联 Mock 授权层拒绝。

真实联调将模拟库换为昆联提供的测试库，使用双方确认的账号和配置，并对照昆联调用／授权记录；不在文档写入真实账号密码。当前不启动、重启、部署或访问未提供的真实检索地址。

运行日志使用现有节点事件，白名单记录 node_id、execution_id、call_id、模式、资源 ID、命中数量、耗时和安全错误类别；正文只在用户有权查看的结果／运行详情中展示，不进入普通服务日志。来源限制与原运行记录权限一致，不新增授权方式。

### 7.4 本轮文档验证与实际状态

文档阶段仅执行 V0：文档结构、引用、REQ／AC／V 追踪、TODO 关联和已暂存／已有源码差异保护。实施证据及环境待执行项见 [verification.md](./verification.md)。

## 8. 回退与后续边界

配置为 `disabled` 时阻止新的检索，保留已有图可查看；切换模式使在途执行失效。旧版本不认识新节点时先下线／停止相关流程再回退代码，Redis 临时执行不自动重建，原本地节点及已有用户授权不受迁移影响。

待后续明确场景再考虑多库／多问题、元数据过滤、权重与重排、外部引用预览或异步恢复。本期不通过模拟一个高级设置来假装昆联已经支持。真实适配待 EXT 契约，按用户确认的任务继续，缺少环境的验收保持待执行。

## 修订记录

| 日期 | 变更 | 状态 |
| --- | --- | --- |
| 2026-11-05 | 规格确认后编写初版；优先组合现有检索组件与变量机制，明确 Mock、单库合同及发布／停止边界。 | 设计待确认，代码未实施。 |
| 2026-11-05 | 用户确认设计，编写 Mock 优先任务规划，设计决策及接口合同未变。 | 设计已确认，任务已拆分，代码未实施。 |
| 2026-11-06 | Mock 实现及本地验证已落地。 | 独立 Redis 与环境验收待执行。 |
| 2026-11-06 | Mock 审查补齐上游引用、选库错误态、公开恢复顺序、会话引用和试运行终态检查。 | 复验和环境状态见验证记录。 |
