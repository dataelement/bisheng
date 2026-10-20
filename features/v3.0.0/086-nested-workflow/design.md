# Design: 工作流嵌套工作流

> **本文档定位 — 现状快照（Why this How）**
>
> - `spec.md` 回答 **做什么**（AC、边界）；需求规则的唯一来源是 PRD §3
> - `design.md`（本文）回答 **为什么这么实现**：关键决策、运行时不直观的事实、对外契约
> - `tasks.md` 是 **流水账**
>
> 调整原则见 `docs/SDD-Guide.md` §3-§4：推翻已 ★ 确认的决策先停下重新确认；纯实现细节直接改本文。

**关联**: [spec.md](./spec.md) · [tasks.md](./tasks.md) · [PRD](../../../docs/PRD/3.0-SEC/工作流嵌套工作流/工作流嵌套工作流%20PRD.md)
**版本**: v3.0.0（开发分支 `feat/SEC-3.0.0-1016`）
**最后更新**: 2026-10-20

本文路径约定：`B/` = `src/backend/bisheng/`，`P/` = `src/frontend/platform/src/`。

---

## 1. 目标与非目标

- **目标**：新增【子工作流】节点，在父工作流的一个节点内同步运行另一个工作流的当前版本，按名称传入参数、取回【结束】节点配置的返回结果；配套提供选用条件、引用关系登记、上线校验、保存提醒、删除拦截和调试面板的嵌套日志。
- **非目标**：子工作流内的交互（输入节点、交互型输出节点）；超过 2 层的嵌套；版本固定；子工作流节点的失败分支；变量类型元数据；整次运行的总步数预算；client 端界面改动；应用列表上线入口的既有缺口（§8）。理由见 PRD §5。

---

## 2. 关键约束

- 遵循 `docs/constitution.md` C1–C8。本功能涉及：C1（新代码放 `B/workflow/domain/`，不给旧 DAO 加入口）、C2（新表只用通用列类型）、C3（新表带 `tenant_id`；新模型模块必须登记进租户过滤，见坑 9）、C4（选用、接口查询和新增引用走权限运行时，见决策 13；删除拦截必须早于权限投影删除、晚于删除权限检查，见坑 10）、C5（错误码占 105 模块 10560–10566）。
- **运行时读取的数据**：子工作流一律读 `Flow.data`。保存当前版本和切换当前版本时，`FlowVersionDao` 会同步写 `Flow.data`（`B/database/models/flow_version.py:73-104,207-226`），所以「当前版本」与 `Flow.data` 始终一致。父工作流调试时运行的是前端发来的画布数据，但子工作流仍读 `Flow.data`。
- **执行模型**：工作流在 Celery `workflow_celery` 队列中同步执行（`async_mode=False`），暂停期间整个对象常驻 worker 内存。子工作流不暂停，没有跨请求的状态需要保存，不涉及 C8。
- **引擎没有整体超时，也没有总步数**：`Workflow.timeout` 只存不用（`B/workflow/graph/workflow.py:41`），只有单节点执行次数上限 `max_steps`（`B/workflow/nodes/base.py:220`）。R-7.6 按此口径定为「只算耗时、沿用单节点上限」。

---

## 3. 方案对比与选定

### 决策 1：子工作流作为独立引擎在节点内同步运行

- **备选**：
  - A. 【子工作流】节点的 `_run` 内新建一个 `Workflow`（包装 `GraphEngine`）同步跑完，取结果返回。
  - B. 把子工作流编译成 LangGraph 子图，作为父图的一个节点。
- **选定**：A
- **原因**：平台节点依赖引擎级对象——每个引擎自带 `GraphState`、节点 id 命名空间和回调；B 需要合并两套 `GraphState` 与节点 id，改动面大。本期子工作流不暂停，A 不需要 LangGraph 的中断传播。
- **何时该重新考虑**：要支持子工作流内的交互节点时。可行路径见 PRD 附录 A.2：仍用 A，子引擎停住时父节点调用 `interrupt()`。

### 决策 2：用 `Workflow` 包装类运行子引擎，不直接调 `GraphEngine.run`

- **备选**：A. `GraphEngine.run()` 一次；B. `Workflow.run()`。
- **选定**：B
- **原因**：引擎把每个【输出】节点的 fake 节点都放进 `interrupt_before`，非交互型【输出】节点也会让图停下，此时状态仍是 RUNNING，需要外层循环调用 `continue_run` 才能继续（`B/workflow/graph/workflow.py:70-85`、`B/workflow/graph/graph_engine.py:262-268,376-401`）。直接调 `GraphEngine.run()` 会在第一个【输出】节点处提前返回。
- **何时该重新考虑**：引擎去掉非交互型输出节点的 fake 中断时。

### 决策 3：输入参数按变量名称覆盖子工作流开始节点的 `custom_variables`

- **备选**：
  - A. 运行前深拷贝子工作流 `Flow.data`，在开始节点 `custom_variables` 中按 `label` 匹配参数名，替换该项的 `value`。
  - B. 沿用开放 API 的 `override`（`B/worker/workflow/redis_callback.py:92-113`）：按 `{node_id: {param_key: value}}` 整体替换一个参数，需要父工作流知道子工作流开始节点的 id，并整表替换。
- **选定**：A。匹配不到的参数忽略，未传的保留原值；值不做类型转换（R-7.1）。
- **原因**：PRD R-1.3、R-5.6 按名称匹配；变量的 `key` 是随机 uuid，名称才是对外接口。前端已校验同一工作流内变量名称唯一（`P/pages/BuildPage/flow/FlowNode/component/GlobalVarItem.tsx:34-50`）。开始节点运行时把列表转为 `{key: value}` 字典（`B/workflow/nodes/start/start.py:75-77`），值本身原样保留。
- **何时该重新考虑**：开始节点改为声明独立的输入参数区，或变量名称不再唯一时。

### 决策 4：返回结果存在【结束】节点自己的变量里，按执行顺序合并

- **备选**：
  - A. 【结束】节点新增参数 `return_enabled`（开关）和 `return_results`（`[{key: 名称, value: 引用}]`）。开关打开时 `EndNode._run` 返回 `{名称: 值}`，基类写入该节点变量；父节点按 `SubflowCallback` 记录的执行顺序，合并已执行的【结束】节点的变量，后执行的覆盖同名项。
  - B. 由父节点在子引擎跑完后自行解析【结束】节点配置中的引用——【结束】节点单独运行时看不到返回值，且解析逻辑与节点分离。
  - C. 合并顺序取 `variables_pool` 的键顺序——变量池不记录执行顺序，「后执行覆盖」无法得出。
- **选定**：A
- **原因**：沿用基类「`_run` 返回值即节点变量」的约定（`B/workflow/nodes/base.py:213-253`），调试面板也能看到返回值。开关关闭时 `_run` 仍返回 `None`，与改动前一致。
- **返回名称规则**：与开始节点变量相同（字母或下划线开头，只含字母、数字、下划线，≤50 字符，节点内唯一），另外禁止 `chat_history`：`GraphState.get_variable` 对这个键名做了特判，会返回聊天记录（`B/workflow/graph/graph_state.py:50-51`）。
- **何时该重新考虑**：引擎为节点变量引入类型或命名空间时。

### 决策 5：「父工作流引用了哪些返回结果」由引擎在构建前预扫得出

- **备选**：
  - A. `GraphEngine` 在实例化节点**之前**预扫原始 nodes JSON：对每个【子工作流】节点，在其它节点参数序列化后的文本中，用正则 `(?<![A-Za-z0-9_])<节点id>\.([A-Za-z_][A-Za-z0-9_]*)` 找出被引用的名称（遇到 `#` 下标后缀自然截断），作为构造参数 `referenced_outputs` 传给该节点。子工作流跑完后，被引用的名称不在返回结果里，节点失败（R-5.7）。
  - B. 把节点配置中缓存的「输出结果」列表全部视为必需——子工作流删掉一个没人用的返回结果也会让父工作流失败，与 R-5.7「引用的」不符。
  - C. 返回缺失时写空值——R-5.7 明确否决。
- **选定**：A
- **原因**：变量引用的文本形态固定为 `<节点id>.<变量>[#下标]`（`B/workflow/graph/graph_state.py:56-80`），模板中为 `{{#<节点id>.<变量>#}}`，正则可以覆盖。现有 `init_nodes` 是边扫边构造（`B/workflow/graph/graph_engine.py:214-269`），所以必须先预扫一遍。
- **何时该重新考虑**：变量引用格式变化时（§6.2）。

### 决策 6：静默执行靠专用回调，嵌套日志放进父节点的运行日志

- **备选**：
  - A. 新回调 `SubflowCallback(BaseCallback)`：丢弃所有面向会话的事件，记录内部节点的开始时间与 `on_node_end` 数据。
  - B. 复用 `RedisCallback` 并加一个静默开关——它把事件写入 Redis 事件流并落聊天记录（`B/worker/workflow/redis_callback.py:527-537`），静默开关要散落到十个事件方法里，且开放 API、调试、正式会话三条路径都依赖它，改动风险高。
- **选定**：A。父节点的 `parse_log` 在常规日志之后追加一项 `{key: "subflow_logs", type: "subflow_logs", value: [...]}`，前端 `RunLog` 识别该类型并渲染可展开列表。
- **原因**：节点日志本来就随 `node_run` 事件下发、不落库，嵌套日志沿用同一通道即可。子工作流事件在源头被丢弃，开放 API 只消费父工作流的事件，R-6.4 无需额外处理。注意：现有代码中没有用 `BaseCallback` 驱动完整引擎运行的先例——`WorkFlowService.run_once` 只跑单个节点（`B/api/services/workflow.py:873-890`），上线检查构造引擎但不运行（`B/api/services/workflow.py:955`）。测试必须覆盖完整运行。
- **中止**：`SubflowCallback` 在每个内部节点开始和结束时，调用父回调的中止检查（`RedisCallback.get_workflow_stop`，`B/worker/workflow/redis_callback.py:518-520`），发现已中止就让子引擎停下。见坑 6。
- **失败日志**：`BaseNode.run` 只在 `_run` 成功后调用 `parse_log`（`B/workflow/nodes/base.py:229-252`）。基类新增钩子 `parse_failed_log(exec_id)`（默认返回 `None`），异常路径用它的返回值作为 `log_data`；`SubflowNode` 覆写它，返回已收集的嵌套日志。见坑 7。
- **何时该重新考虑**：平台引入统一的运行日志持久化时，嵌套日志应改为写入该存储。

### 决策 7：引用关系登记在新表，在 `Flow.data` 变化的服务层入口同步

- **备选**：
  - A. 新表 `workflow_subflow_ref(parent_flow_id, child_flow_id, tenant_id)`，在写 `Flow.data` 的服务入口同步。
  - B. 每次需要时扫描本租户全部工作流的 `Flow.data`。
  - C. 在 SQL 层对 `Flow.data` 做 `LIKE` 过滤。
- **选定**：A
- **原因**：「谁在引用我」每次保存都要查（R-3.3、R-5.5），B 每次保存都要加载全部工作流的大 JSON；C 依赖 JSON 列的文本匹配，违反 C2 对 JSON 列的限制，在 DM8 上没有保障。A 的代价是同步入口必须覆盖全；入口已于 2026-10-19 逐一核实（§4.3）。
- **同步规则**：只按父工作流的**当前版本**计算；每次把该父工作流的记录改成与新数据一致（删掉多余的、插入缺少的，保留不变的行）；父工作流删除时删除其记录。同一父工作流被并发保存时，后提交的一方会撞唯一键或删到已删除的行，Repository 回滚后重读重试，最多 3 次。本功能是新增能力，存量数据中没有【子工作流】节点，不需要回填。
- **何时该重新考虑**：出现新的 `Flow.data` 写入口时，必须接入同步，否则删除拦截会放行仍被引用的工作流（坑 4）。

### 决策 8：选用条件由新接口判定，节点构成判定集中在一个纯函数

- **备选**：
  - A. 新接口 `GET /api/v1/workflow/subflow/candidates`：端点层调用现有 `get_all_flows_envelope(flow_type=WORKFLOW, managed=True)` 取有编辑权限的工作流，把这一页交给 `SubflowService.filter_candidates`；后者用现有的 `FlowDao.aget_flow_by_ids`（`B/database/models/flow.py:231`）批量读取这些工作流的 `Flow.data`，排除自身和含禁止节点的工作流。一页不满时继续取下一页，每次请求最多取 5 页，然后返回游标让前端继续加载。
  - B. 前端用现有列表接口取回后自行过滤——列表接口不返回 `data`，前端无法判断节点构成。
- **选定**：A
- **原因**：`flow_type` 不传时 `get_all_flows_envelope` 会同时返回助手（`B/api/services/workflow.py:597-630`）。分页由端点层组织，`SubflowService` 只接收行数据，避免 `B/workflow/domain/` 反向依赖 `B/api/services/`。5 页上限防止可编辑工作流很多时单次请求扫描全部数据。
- **纯函数 `inspect_flow_data(data)`**：返回是否含【输入】节点、交互型【输出】节点（`output_result.type in ('input', 'choose')`，`B/workflow/nodes/output/output.py:22,54`）、【子工作流】节点，以及开始节点变量名称和开关打开的【结束】节点返回名称；另返回【子工作流】节点指向的工作流 id（`subflow_ids`，供 `sync_refs` 使用）和不合规原因代码 `ineligible_reasons`（`input_node`、`interactive_output_node`、`subflow_node`、`invalid_output_name`）。候选接口、上线校验、保存提醒共用它，保证口径一致。
- **何时该重新考虑**：工作流数量增长到 5 页上限经常取空时，改为在引用表旁登记「节点构成」摘要列。

### 决策 9：运行期兜底按「实际执行过的节点类型」判定

- **备选**：
  - A. 引擎新参数 `subflow_depth`（默认 0）透传给节点，【子工作流】节点在 `subflow_depth >= 1` 时直接失败；子引擎跑完后，用 `SubflowCallback` 记录的已执行节点 id 对照子引擎 `nodes_map` 的类型，执行过【输入】或交互型【输出】节点即失败；子引擎状态停在 INPUT 也失败。
  - B. 只看子引擎是否停在 INPUT 状态——【输入】节点只有在 `get_input_schema()` 非空时才把状态置为 INPUT（`B/workflow/graph/graph_engine.py:386-394`），表单为空的【输入】节点会被外层循环直接越过。
  - C. 运行前检查子工作流是否含禁止节点——R-3.4 要求「执行到时」失败，含这类节点但没走到的分支不应失败。
- **选定**：A
- **原因**：上线校验已拦住正常路径，这里只兜底，判定必须覆盖 B 漏掉的情况。
- **何时该重新考虑**：放开交互节点（决策 1 的重新考虑条件）时。

### 决策 10：失败信息用标记前缀携带错误码与三项信息；用户中止不包装

- **备选**：
  - A. 父节点失败时抛出的异常文本为 `<SUBFLOW_ERROR_MARKER>{json}`，json 为 `{status_code, status_message, data}`；`RedisCallback.parse_workflow_failed` 最先识别该标记，然后才走「stop by user」和其它子串分支。用户中止从不包装（见下），所以先认标记与先判中止结果相同，而先认标记不会让子工作流内部恰好含「stop by user」的错误文本被吞掉。
  - B. 直接抛出子引擎的原始失败文本。
- **选定**：A
- **原因**：沿用 F078 技能错误的做法（`B/workflow/nodes/agent/skill_support.py:60-67`）。按 B，子工作流内部的 `-- has run more than ...` 等子串会被父工作流的子串匹配误判（`B/worker/workflow/redis_callback.py:194-226`）。
- **用户中止**：子引擎因中止失败（reason 为 `stop by user`，`B/workflow/nodes/base.py:218-219`）时，父节点原样抛出 `IgnoreException("stop by user")`，不包装成 10560；否则中止会被显示成一条错误（坑 6）。
- **失败节点名称**：取 `SubflowCallback` 记录的最后一个带 `reason` 的 `on_node_end`。子引擎在构造阶段就抛错时（例如缺开始节点、模型配置失效，`B/workflow/graph/graph_engine.py:86-102,271-279`），不会有节点事件，`node_name` 为空，`reason` 为构造异常文本，错误码仍为 10560。
- **前端本地化**：节点事件的 `reason` 保留标记与 JSON，不在后端改写成文字。platform 的 `nodeLogData.ts` 解析标记，按 `api_errors:<status_code>` 和 `data` 插值显示，与运行失败的提示一致；不带标记的 `reason` 原样显示。曾尝试由后端只下发英文消息（244b83c5f），因前端无法本地化而撤回（坑 16）。
- **何时该重新考虑**：平台引入结构化的失败原因字段（替代字符串匹配）时。

### 决策 11：运行时不校验运行者对子工作流的权限

- **备选**：A. 不校验，随父工作流授权；B. 运行时校验运行者对子工作流的使用权限。
- **选定**：A
- **原因**：PRD R-5.1 的产品决定：编排者配置时已具备编辑权限，配置即授权；B 要求管理员为全部终端用户补授子工作流权限。子工作流按 id 从 `Flow` 读取，租户自动过滤保证只能读到同租户数据。
- **护栏**：Worker 的 `_authorize_workflow_use`（`B/worker/workflow/tasks.py:108`）只检查顶层工作流，这是有意为之；不要为子工作流补 `use` 检查，否则 AC-09 会失败。「配置时已具备编辑权限」由决策 13 在写入时保证。
- **何时该重新考虑**：产品要求子工作流可以单独控制谁能间接使用时。

### 决策 12：子引擎沿用父引擎的运行上下文

- **备选**：
  - A. 子引擎的 `workflow_id`、`workflow_name`、`user_id`、`tenant_id`、`chat_id`、`tmp_session_id`、`max_steps` 都取父引擎的值；`flow_user_id` 取子工作流的所有者。
  - B. `workflow_id`、`workflow_name` 取子工作流的值。
- **选定**：A（2026-10-19 用户拍板：消耗记在父工作流名下）
- **原因**：助手节点和大模型节点用 `workflow_id` 作为模型调用记录的应用 id（`B/workflow/nodes/llm/llm.py:42,126`、`B/workflow/nodes/agent/agent.py:236,377`）；R-7.6 要求子工作流的消耗随调用方计入父工作流。不透传 `tmp_session_id` 时，调试运行中子工作流内的每个助手节点会各自生成工作区 id（`B/workflow/nodes/agent/skill_support.py:92`）。
- **聊天记录与当前时间（R-6.2）**：引擎在构建节点前从原始数据找出开始节点 id，作为 `start_node_id` 透传给节点（`Workflow` 不需要这个参数）。子引擎构造完成后，父节点把父引擎 `graph_state.history_memory` 的消息拷入子引擎开始节点新建的记忆窗口（坑 5），并把子开始节点的 `current_time` 参数设为父开始节点的 `current_time` 变量（坑 8）。`user_info` 由同一个 `user_id` 计算，天然一致。
- **何时该重新考虑**：需要在子工作流名下统计被调用消耗时，改为同时记录父子两个 id。

### 决策 13：新增引用时校验编辑权限，已有引用不复查

- **备选**：
  - A. 在写入工作流数据的入口，找出数据中**新增**的子工作流 id，逐个要求编辑权限，不满足抛 10566。「已有」指该父工作流在引用表中已登记的子工作流，加上被替换的那份数据中已有的子工作流。
  - B. 每次保存都检查数据中全部子工作流的编辑权限。
  - C. 不在服务端检查，只靠候选列表与接口查询要求编辑权限（2026-10-20 之前的状态）。
- **选定**：A（2026-10-20，`/sdd-code-review` 发现 C 的缺口后用户批准）
- **原因**：C 下 R-5.1「配置即授权」的前提只在界面上成立：知道工作流 id 的同租户用户可以直接调用接口把它配进自己的工作流，运行后在节点日志中看到其内部节点的输入输出（提示词、检索片段），并阻止其所有者删除它。B 会让失去编辑权限的编排者连父工作流的其它改动都保存不了，违反 AC-10。
- **入口**：`SubflowService.check_new_refs(login_user, flow_id, data, known_data)`，由以下入口调用：
  - 保存版本（`known_data` 为被覆盖的版本数据）。
  - 另存新版本（`known_data` 为来源版本的数据）。
  - 新建工作流（无已有引用，全部检查）。复制工作流、从模板创建也走新建：复制者对其中任一子工作流没有编辑权限时，复制被拒并返回 10566（2026-10-20 用户确认接受）。
  - 调试运行：`WorkflowClient.init_workflow`，用连接路径上的工作流 id 查已有引用，不用消息里的 `flow_id`。
  - 单节点运行 `run_once`。
- **不检查的入口**：切换当前版本和上线。这两个入口切换到的版本数据在写入时已检查过；2026-10-20 之前保存的版本没有经过检查，属于存量（§8）。
- **何时该重新考虑**：产品要求子工作流单独控制谁能间接使用时，与决策 11 一起改。

---

## 4. 系统现状（目标状态）

### 4.1 数据流

**编排**：编排者拖入【子工作流】节点 → 下拉调用候选接口（决策 8）→ 选定后调用接口查询，取子工作流的输入参数和返回名称 → 节点保存 `subflow_id` 与快照 → 下游节点经变量选择器引用 `<节点id>.<返回名称>`。

**保存**：`PUT /workflow/versions/{id}` → 对新增的引用检查编辑权限，无权限抛 10566、不写入（决策 13）→ 若保存的是当前版本，同步引用表（决策 7）；若该工作流被引用，并且含禁止节点或接口有变化，在响应中附带 `subflow_warning` → 前端弹窗。接口变化的比较基准是写入前的旧数据：保存版本时取 `version_info.data` 被覆盖前的值（`B/api/services/flow.py:220`），切换版本时取切换前的 `Flow.data`；必须在写入前读出，写入后 `Flow.data` 已是新数据。`POST /workflow/change_version` 同理，调用处只有版本卡片 `CardSelectVersion.tsx`。编辑页 `Header.tsx` 的版本下拉切换只在本地加载目标版本，切换前先等待当前版本保存完成：保存失败时停在当前版本；保存响应带 `subflow_warning` 时弹窗；当前版本已上线时不保存。

**上线**（两个入口都拦截，坑 2）：
- `PATCH /workflow/status`：校验**待上线版本**的数据（`version_info.data`，上线后才切换为当前版本，`B/api/services/workflow.py:952-960`）。
- `PATCH /workflow/update/{id}` 带 `status=2`：校验 `Flow.data`。
- 两者对数据中的每个【子工作流】节点，读取子工作流的 `Flow.data` 并用 `inspect_flow_data` 检查，不满足抛 10564。

**删除**：`DELETE /flows/{id}` → 先检查删除权限 → 再**在 `project_flow_delete` 之前**查引用表中 `child_flow_id = id` 的记录 → 有则抛 10565 并列出引用方名称；无则继续原删除链路，最后清除以它为父的记录（坑 10）。

**调试与单节点运行的入口检查**：调试运行发来的画布数据、`run_once` 的单个【子工作流】节点，先按决策 13 检查新增引用；无权限时调试运行以 `error` 事件下发 10566，不启动任务。

**运行**：父引擎执行到 `SubflowNode._run` →
1. 检查 `subflow_depth`；用同步的 `FlowDao.get_flow_by_id` 按 `subflow_id` 读 `Flow`（依赖 worker 已设置的租户上下文自动过滤），不存在抛 10561。
2. 解析输入参数（「引用」经 `get_other_node_variable` 取值，「输入」按字符串处理），按名称覆盖 `custom_variables`（决策 3）。
3. 构造 `Workflow`：上下文按决策 12；`callback=SubflowCallback`；`subflow_depth=1`。构造异常按决策 10 包装为 10560。
4. 拷入聊天记录、设置 `current_time`（决策 12）。
5. `Workflow.run()`；`SubflowCallback` 在每个内部节点开始和结束时检查中止。
6. 判定结果：中止 → 原样抛 `stop by user`；执行过禁止节点或停在 INPUT → 10563；FAILED → 10560；SUCCESS → 继续。
7. 按执行顺序合并【结束】节点变量（决策 4），检查 `referenced_outputs`，缺失抛 10562，返回 `{名称: 值}`。
8. 成功时 `parse_log`、失败时 `parse_failed_log` 附带嵌套日志（决策 6）。

**中止**：用户点击中止 → `RedisCallback` 写入中止标记 → 子引擎的下一个内部节点开始或结束时，`SubflowCallback` 发现标记 → `SubflowNode.stop()` 停止子引擎 → 子引擎以 `stop by user` 失败 → 父节点原样抛出 → 父引擎以 `stop by user` 结束，前端不显示错误。

### 4.2 关键数据结构 / 字段约定

| 字段 / 结构 | 格式 | 说明 | 谁会消费 |
|---|---|---|---|
| 节点类型 `subflow` | `NodeType.SUBFLOW = "subflow"` | 新节点类型 | 引擎、前端模板 |
| `subflow` 节点参数 `subflow_id` | `{id: str, name: str}` | 选中的子工作流；`name` 为配置时的快照，仅用于展示 | 节点运行、前端 |
| `subflow` 节点参数 `subflow_inputs` | `[{key: 参数名, type: "ref"\|"input", value, label}]` | 与代码节点 `code_input` 同形 | 节点运行 |
| `subflow` 节点参数 `subflow_outputs` | `[{key: 返回名称}]`，`global: "code:value.map(...)"` | 配置时的返回名称快照，供变量选择器列出 | 前端变量选择器 |
| `end` 节点参数 `return_enabled` / `return_results` | `bool` / `[{key, type: "ref", value, label}]` | 【结束】节点 v2 新增；旧数据无此参数时按关闭处理 | `EndNode._run`、`inspect_flow_data` |
| `subflow` 节点运行日志 | `[[{key: "subflow_inputs", type: "params"}, {key: "subflow_outputs", type: "params"}, subflow_logs 项]]`；失败时没有 `subflow_outputs` | 实际传入的参数、返回结果与嵌套日志 | 前端 `RunLog` |
| 运行日志项 `subflow_logs` | `{key, type: "subflow_logs", value: [{node_id, name, type, duration_ms, reason, log_data, input_data}]}` | 嵌套日志；成功和失败时都有 | 前端 `RunLog` |
| 保存响应 `subflow_warning` | `{referenced_by: [{id, name}], forbidden_nodes: [{id, name, type}], interface_changes: {inputs_added, inputs_removed, outputs_added, outputs_removed}}` | 仅在有需要提醒的内容时出现 | 前端保存弹窗 |
| 表 `workflow_subflow_ref` | `id, tenant_id, parent_flow_id, child_flow_id, create_time, update_time`；唯一 `(parent_flow_id, child_flow_id)` | 引用关系 | 删除拦截、保存提醒 |

### 4.3 关键模块职责

`B/workflow/domain/` 目前只有 `services/`，`models/`、`repositories/interfaces/`、`repositories/implementations/` 为本功能新建，结构参照 `B/knowledge/domain/repositories/`。

| 模块 / 文件 | 职责 | 不做什么 |
|---|---|---|
| `B/workflow/nodes/subflow/subflow.py` `SubflowNode` | 运行子引擎、传参、取结果、组织失败信息与嵌套日志；定义 `SUBFLOW_ERROR_MARKER`、`SubflowRunError` 与 `parse_subflow_error`；运行中的子引擎放在 `sub_workflow` 属性上，`stop()` 经它停止子引擎 | 不查权限，不写引用表 |
| `B/workflow/callback/subflow_callback.py` `SubflowCallback` | 丢弃会话事件，记录内部节点执行顺序与日志，检查中止 | 不写 Redis 事件流 |
| `B/workflow/nodes/base.py` | 新增 `parse_failed_log` 钩子 | 不改成功路径 |
| `B/workflow/nodes/end/end.py` | 开关打开时解析并返回返回结果；「引用」行没有选变量时以可读原因失败（编辑器会先拦住，这里兜底经接口保存的数据） | 开关关闭时行为不变 |
| `B/workflow/graph/graph_engine.py`、`workflow.py` | `GraphEngine`、`Workflow` 新参数 `subflow_depth`；引擎预扫开始节点 id 与 `referenced_outputs`（`scan_referenced_outputs`）并透传给节点 | — |
| `B/workflow/domain/services/subflow_inspect.py` `inspect_flow_data` | 纯函数：节点构成、开始节点变量名、返回名称 | 不访问数据库 |
| `B/workflow/domain/models/subflow_ref.py` | 引用表模型；模块路径登记进 `_TENANT_AWARE_MODEL_MODULES` | — |
| `B/workflow/domain/repositories/` | 引用表读写（异步） | 不读 `Flow`：`Flow` 的读取沿用现有 `FlowDao`（同步 `get_flow_by_id` 供节点使用，异步 `aget_flow_by_ids` 供服务使用） |
| `B/workflow/domain/services/subflow_service.py` `SubflowService` | 候选过滤、接口查询、新增引用的权限检查 `check_new_refs`、引用同步 `sync_refs`、上线校验、保存提醒、删除拦截 | 不运行工作流，不调用 `B/api/services/` |
| `B/api/v1/workflow.py` | 新增候选与接口查询两个端点；创建、上线入口调用 `SubflowService` | — |
| `B/api/services/flow.py`、`B/api/services/workflow.py`、`B/api/v1/flows.py` | 保存、切换版本、上线、删除入口调用 `SubflowService` | — |
| `B/worker/workflow/redis_callback.py` | `parse_workflow_failed` 识别子工作流标记 | — |
| `B/common/chat/clients/workflow_client.py` | 调试运行启动前调用 `check_new_refs`；业务错误码以 `error` 事件原码下发 | — |
| `P/controllers/API/workflow.ts` `workflowTemplate` | `subflow` 节点模板；`end` 节点模板 v2 | — |
| `P/util/flowCompatible.ts` | `end` v1→v2：补「返回结果」分组，开关默认关闭 | — |
| `P/pages/BuildPage/flow/FlowNode/component/` | `SubflowSelectItem`：选择子工作流，并渲染输入参数表与返回名称（写入隐藏参数 `subflow_inputs`、`subflow_outputs`）；`EndReturnItem`：【结束】节点开关与返回结果表；`subflowParams.ts`：按接口重建节点参数的纯函数。`CodeInputItem` 新增可选 prop `refOnly`、`validateName`、`fixedKeys`，不传时与代码节点原有用法相同；另经 `onVarEvent` 注册运行前检查，「引用」行指向的变量不存在时拦截运行并标红该行（`flowUtils.findInvalidRefItems`，发版线修复，代码节点同样受益）。`SubflowSelectItem` 在接口查询成功后才切换选中的工作流 | 不改现有组件样式 |
| `P/pages/BuildPage/flow/SubflowWarningDialog.tsx`（新） | 保存与切换版本后的 `subflow_warning` 弹窗，供 `Header.tsx`（保存、版本下拉切换前的保存）与 `CardSelectVersion.tsx`（切换当前版本）调用 | `Header.tsx` 已有 862 行，超过 600 行上限，弹窗不放进去 |
| `P/pages/BuildPage/flow/FlowNode/RunLog.tsx`、`SubflowRunLog.tsx`（新） | `RunLog` 把 `subflow_logs` 项交给 `SubflowRunLog` 渲染为可展开列表；【结束】节点有返回结果时显示日志 | — |
| `P/pages/BuildPage/flow/FlowChat/nodeLogData.ts`（新） | 节点结束事件转为节点日志：失败时错误项在前、失败日志在后；解析 `SUBFLOW_ERROR_MARKER` 并按错误码本地化（决策 10） | 不处理成功日志 |
| `P/pages/BuildPage/flow/FlowNode/nodeLayer.ts`（新） | 节点日志浮层打开时提升所在画布节点的层级，关闭时恢复（坑 17）；所有节点类型共用 | 画布已改动层级时不恢复 |
| `P/util/flowUtils.ts` `isVarInFlow` | 运行前判断引用的变量是否存在；`subflow_output` 与 `code_output` 一样按各项 `key` 识别（PR #2509） | — |

**`Flow.data` 写入口与引用同步**（2026-10-19 已逐一核实为完整清单）：

| 入口 | 位置 | 同步动作 |
|---|---|---|
| 新建工作流（含复制工作流 `P/pages/BuildPage/apps.tsx:192-203`、模板创建 `CreateApp.tsx:180`、知识库导入 `FileUploadStep4.tsx:194`，都走这里） | `B/api/v1/workflow.py:407-435` | 按新数据插入 |
| 保存版本 | `B/api/services/flow.py:200-226` | 仅当 `is_current == 1` 时重算 |
| 切换当前版本 | `B/api/services/flow.py:139-161` | 按新当前版本重算 |
| 上线时切换版本 | `B/api/services/workflow.py:935-966` | 按上线版本重算 |
| 删除工作流 | `B/api/v1/flows.py:27` → `B/api/services/flow.py:391` | 先拦截，再清除以它为父的记录 |

不需要同步的写入：`PATCH /workflow/update/{id}` 跳过 `data` 字段（`B/api/v1/workflow.py:550-552`）；资源共享只改 `is_shared`（`B/tenant/domain/services/resource_share_service.py:353-359`）；`POST /workflow/versions` 新建的版本不是当前版本。

新增引用的权限检查（决策 13）挂在新建工作流、保存版本、`POST /workflow/versions` 三个写入口，以及调试运行和 `run_once`，都在写入或启动之前。

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | 非交互型【输出】节点也会让引擎停下，状态仍为 RUNNING | 子工作流在第一个【输出】节点后就「结束」，返回结果为空 | 决策 2，用 `Workflow.run()` 的外层循环 |
| 2 | 上线有两个入口：编辑页走 `PATCH /workflow/status`（有构建检查，要求发布权限），应用列表走 `PATCH /workflow/update/{id}` 带 `status`（无构建检查，只要求编辑权限，`B/api/v1/workflow.py:530-565`） | 从应用列表上线可绕过子工作流校验 | 两个入口都调用 `SubflowService` 的上线校验（T22）。应用列表入口缺构建检查、只要求编辑权限是既有缺口，F086 不修，见 §8 |
| 3 | 子工作流内部的失败文本可能包含 `-- has run more than ...`、F078 技能错误标记等子串 | 父工作流的失败被误判成别的错误码 | 决策 10，`parse_workflow_failed` 先识别子工作流标记 |
| 4 | 引用表只在已接入的入口同步 | 新增的 `Flow.data` 写入口不接同步，删除拦截会放行仍被引用的工作流 | 决策 7；新增写入口必须调用 `SubflowService.sync_refs` |
| 5 | 开始节点 `__init__` 会用新的记忆窗口替换 `graph_state.history_memory`（`B/workflow/nodes/start/start.py:26-27`） | 构建子引擎前拷入的聊天记录被冲掉 | 子引擎构造完成后再拷入（§4.1 第 4 步） |
| 6 | 运行中的中止只靠 `RedisCallback.send_chat_response` 在发送非流式事件时检查中止标记（`B/worker/workflow/redis_callback.py:527-535`）；`stop_workflow` 任务只处理停在 INPUT 状态的对象（`B/worker/workflow/tasks.py:47-50,222-229`） | 子引擎事件全被 `SubflowCallback` 丢弃，父回调不再检查中止，子工作流跑完前无法中止；中止后若被包装成 10560，用户主动中止会显示成错误 | 决策 6「中止」、决策 10「用户中止」 |
| 7 | `BaseNode.run` 只在 `_run` 成功时调用 `parse_log` | 子工作流失败时恰好没有嵌套日志，而这正是最需要日志的时候 | 决策 6「失败日志」，基类新增 `parse_failed_log` |
| 8 | 子开始节点 `__init__` 会重新取 `datetime.now()` 作为 `current_time`（`B/workflow/nodes/start/start.py:24`） | 父工作流在【输入】节点暂停后恢复，子工作流的当前时间与父工作流相差数分钟到数小时 | 决策 12，用父开始节点的值覆盖 |
| 9 | 租户过滤只扫描 `_TENANT_AWARE_MODEL_MODULES` 显式列出的模块（`B/core/database/tenant_filter.py:41-133`），`*/domain/models` 的自动发现只给 Alembic 用 | 新表绕过 `tenant_id` 自动填充和查询过滤，跨租户泄漏 | T03 登记模块路径 |
| 10 | `DELETE /flows/{id}` 先执行权限投影删除（`B/api/services/flow.py:391-412`），再删 `Flow` 行 | 引用拦截若放在投影删除之后，会出现「权限记录已删、工作流还在」 | 引用拦截放在 `project_flow_delete` 之前；删除权限检查又放在引用拦截之前，否则无删除权限的用户能从 10565 读到引用方名称 |
| 11 | 父工作流调试时运行的是前端画布数据，子工作流读的是 `Flow.data` | 编辑子工作流后未保存，父工作流调试仍跑旧内容 | 符合 R-4.1；节点帮助文案说明「运行时使用子工作流已保存的当前版本」 |
| 12 | 子引擎沿用父工作流的 `workflow_id`（决策 12），而临时向量分区、F078 工作区等按 `workflow_id`/`chat_id` 加节点 id 区分 | 父子工作流是复制关系、节点 id 相同时，这些资源会串用 | 现状接受；出现串扰时给子引擎的节点 id 加前缀 |
| 13 | 返回名称 `chat_history` 会被 `GraphState.get_variable` 特判为聊天记录 | 下游拿到的是聊天记录而不是返回值 | 决策 4，前端与 `inspect_flow_data` 都禁止该名称 |
| 14 | platform 请求拦截器把返回 403/404 的 GET 直接跳转到 403/404 页面（`P/controllers/request.ts`） | 编排者失去子工作流编辑权限后打开父工作流的节点，整个编辑页被带走，违反 AC-10 | 接口查询请求带 `silent`，失败时沿用节点快照 |
| 15 | 运行前的变量检查 `isVarInFlow`（`P/util/flowUtils.ts`）按参数类型逐个列举可被引用的输出，没列举的类型一律判为不存在 | 新增一种输出参数类型而不加进去，变量选择器能选中，点运行却提示「已失效」（PR #2509 修的就是 `subflow_output`） | 新输出类型同时加进 `isVarInFlow` 的类型判断 |
| 16 | 子工作流失败时，节点事件的 `reason` 是 `SUBFLOW_ERROR_MARKER` 加 JSON，前端靠解析它才能本地化 | 后端把 `reason` 改成文字，节点日志只能显示英文，与运行失败提示的语言不一致 | 决策 10「前端本地化」；`P/pages/BuildPage/flow/FlowChat/nodeLogData.ts` |
| 17 | 画布上每个节点的外层元素各自带 `z-index`，节点内的浮层无法高过后绘制的节点 | 节点日志浮层被右侧或下方的节点遮住 | 浮层打开时 `raiseNodeLayer` 提升所在节点（`nodeLayer.ts`） |
| 18 | `CodeInputItem` 的名称有两处校验：行级只负责标红，列表级决定能否运行 | 两处正则不一致时，合法名称（如单字母 `r`）能运行却一直标红 | 两处统一为 1 到 50 个字符 |
| 19 | 候选列表与接口查询要求编辑权限，只约束界面；保存接口直接收工作流数据 | 同租户用户调用接口即可把任意工作流配成子工作流，读到其内部节点日志并阻止其删除 | 决策 13，写入口调用 `check_new_refs` |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 契约 | 形式 | 谁在用 |
|---|---|---|
| `GET /api/v1/workflow/subflow/candidates?name&cursor&page_size&exclude_flow_id` | HTTP API，返回 `{data: [{id, name, description, logo}], cursor}` | platform 子工作流选择组件 |
| `GET /api/v1/workflow/subflow/{flow_id}/interface` | HTTP API，需编辑权限，返回 `{id, name, inputs: [{name, value}], outputs: [name], eligible, ineligible_reasons}` | platform 节点配置面板 |
| `PUT /workflow/versions/{id}`、`POST /workflow/change_version` 响应新增 `subflow_warning` | 向后兼容的新增字段：保存版本时 `data` 为原版本对象加 `subflow_warning`；切换版本时 `data` 为 `{subflow_warning}`；无提醒时响应与改动前相同 | platform 编辑页 |
| 【结束】节点 v2 参数 `return_enabled` / `return_results` | 工作流数据格式 | 引擎、`inspect_flow_data` |
| 运行日志类型 `subflow_logs` | `node_run` 事件 `log_data` | platform `RunLog` |
| `SubflowService.sync_refs(flow_id, data)`、`clear_refs(flow_id)` | 内部 Python API | 所有 `Flow.data` 写入口（坑 4）；删除入口 |
| `inspect_flow_data(data)` | 内部 Python API | `SubflowService`、`SubflowNode` |
| `SUBFLOW_ERROR_MARKER`（`'-- subflow error --'`）后接 `{status_code, status_message, data}` JSON | 前后端字符串契约：后端在 `B/workflow/nodes/subflow/subflow.py` 定义，前端在 `nodeLogData.ts` 硬编码同一常量，改一端必须同时改另一端 | `RedisCallback.parse_workflow_failed`、platform `nodeLogData.ts` |
| `SubflowService.check_new_refs(login_user, flow_id, data, known_data)` | 内部 Python API | 写入工作流数据与启动运行的入口（决策 13） |
| `BaseNode.parse_failed_log` | 节点基类钩子 | 其它节点可覆写以在失败时附带日志 |

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 风险点 |
|---|---|---|
| `FlowVersionDao` 保存当前版本时同步 `Flow.data` | 隐式数据契约 | 若改为异步或延迟同步，R-4.1「保存即生效」失效 |
| 变量引用文本形态 `<节点id>.<变量>[#下标]` | 隐式格式 | 若改格式，决策 5 的预扫失效 |
| `Workflow` 外层循环语义 | 内部 API | 见坑 1 |
| `BaseNode.run` 的异常与日志语义 | 内部 API | 改动异常路径会影响决策 6 的失败日志 |
| `RedisCallback.get_workflow_stop` | 内部 API | 改名或改语义会让子工作流无法中止 |
| F078 `AGENT_SKILL_ERROR_MARKER` 格式 | 内部字符串格式 | 子工作流标记必须先于它识别 |
| `get_all_flows_envelope(flow_type, managed=True)` 的编辑权限过滤 | 内部 API | 候选列表的权限口径随它变化 |
| `_TENANT_AWARE_MODEL_MODULES` 登记机制 | 租户过滤基础设施 | 机制变化时需复核新表是否仍被过滤 |

### 6.3 错误码分配（105 flow 模块，10560–10566）

| 码 | 类 | 场景 | AC |
|---|---|---|---|
| 10560 | `WorkFlowSubflowRunError` | 子工作流内部节点失败或构造失败；`data: {subflow_name, node_name, reason}` | AC-20 |
| 10561 | `WorkFlowSubflowNotFoundError` | 运行时或上线时子工作流不存在（引用表只记录当前版本，待上线版本可能指向已删除的工作流） | spec §3 |
| 10562 | `WorkFlowSubflowOutputMissingError` | 引用的返回结果不存在；`data: {subflow_name, output_name}` | AC-14 |
| 10563 | `WorkFlowSubflowForbiddenNodeError` | 运行期执行到【子工作流】、【输入】或交互型【输出】节点；`data: {subflow_name, node_name}` | AC-06 |
| 10564 | `WorkFlowSubflowOnlineCheckError` | 上线时子工作流不满足条件；`data: {subflow_name, reasons, reason_codes}`，`reasons` 为不合规节点名称与返回名称，用「, 」连接 | AC-04 |
| 10565 | `WorkFlowReferencedDeleteError` | 删除被引用的工作流；`data: {referenced_by, referrers: [{id, name}]}`，`referenced_by` 为引用方名称，用「, 」连接 | AC-11 |
| 10566 | `WorkFlowSubflowNoPermissionError` | 保存、新建、调试或单节点运行时，新增引用的工作流当前用户没有编辑权限；`data: {subflow_name}`，取节点里保存的名称，不读子工作流 | AC-03（R-2.1、R-5.1） |

文案三语写在 `src/frontend/packages/locales` 的 `api_errors` 域。2026-10-19 已核对 `feat/3.0.0`、`feat/3.0.0-vibe` 与本分支均未占用 1056x。T01 负责登记到 `features/v3.0.0/release-contract.md`，同时登记表 1 的领域对象「子工作流引用关系」和一条跨 Feature 不变量：【结束】节点「返回结果」开关关闭时，工作流行为与改动前一致。

---

## 7. 测试与可观测

- **后端单测**（`src/backend/test/workflow/`，不依赖中间件）：`inspect_flow_data` 各类节点判定；`EndNode` 开关两态；`SubflowCallback` 静默、日志收集、中止检查；引擎预扫 `referenced_outputs`；`SubflowNode` 用最小工作流 JSON 构造真实子引擎**完整运行**（决策 6 无先例），覆盖传参、返回合并、缺失返回、深度兜底、空表单【输入】节点兜底、失败标记、构造异常、中止不包装、失败时的嵌套日志、聊天记录与当前时间；`parse_workflow_failed` 的识别顺序。
- **后端集成**（需数据库，CI 运行）：引用表同步的五个入口、删除拦截在投影删除之前、保存提醒、两个上线入口、候选接口权限过滤（用非管理员账号）。
- **E2E**：按 spec AC-01 至 AC-21 逐条验收。
- **手动验证**（114 platform `http://192.168.106.114:4101/`，部署前先征得用户同意；账号用管理员与一个只有父工作流使用权限的普通用户）：
  1. 管理员建工作流 B：开始节点加变量 `industry=通用`，大模型节点，【结束】节点打开「返回结果」并返回大模型输出，保存（不上线）。
  2. 建工作流 A：【输入】→【子工作流】（选 B，`industry` 配「制造业」）→【输出】引用 B 的返回结果→【结束】，上线。
  3. 调试 A，展开【子工作流】节点日志，确认看到 B 的各节点；会话中不出现 B 的消息。
  4. 授权普通用户使用 A（不授权 B），用普通用户在工作台运行 A，结果正常。
  5. 删除 B，被拦截并列出 A。
- **可观测**：子工作流失败时 worker 日志带 `subflow_id`、子工作流名称、失败节点；调试面板展开嵌套日志。

---

## 8. 后续改进 / 不打算做的事

- **子工作流内的交互节点**：技术可行（PRD 附录 A.2），产品决定本期不做。
- **变量类型元数据**：界面不显示类型列（R-7.3），要显示需给全部节点输出补类型声明。
- **整次运行的总步数预算**：引擎没有跨节点步数计数，R-7.6 定为沿用单节点上限（2026-10-19 用户拍板）。
- **应用列表上线入口的既有缺口**：`PATCH /workflow/update/{id}` 上线时不做构建检查，只要求编辑权限。与子工作流无关，2026-10-19 用户确认单独修复，F086 只在该入口补子工作流校验。
- **引用表与 `Flow.data` 的对账脚本**：本期不做；若发现漏记，可写一次性脚本按全部工作流当前版本重建。
- **运行前检查失效引用（已修）**：子工作流返回结果改名后，【代码】节点入参、【结束】节点返回结果和【子工作流】节点输入参数中的失效引用，曾经要到运行时才以 10562 报错。2026-10-20 已改为在编辑器运行前拦截（§4.3 `CodeInputItem` 行）；后端 10562 保留为兜底。
- **2026-10-20 之前保存的版本**：没有经过决策 13 的检查。切换当前版本和上线不复查，所以这类版本中的引用仍可生效；属于功能上线前的测试数据，不做迁移。
- **调试运行消息中的 `flow_id`**：`WorkflowClient` 允许消息里的 `flow_id` 覆盖连接路径上的工作流 id，这是既有行为，与子工作流无关。决策 13 的检查用连接路径上的 id，不受它影响；是否收紧由工作流模块另行处理。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-10-19 | 初版 | PRD 澄清完成 |
| 2026-10-19 | 按 `/sdd-review design` 修订：补中止传递、失败日志、当前时间、租户过滤登记、删除拦截时机、预扫规格、运行上下文（决策 12）、各决策的备选与重新考虑条件、写入口核实结论；R-7.6 改为只算耗时、消耗记父工作流 | 独立审查 22 条意见；用户拍板两项 |
| 2026-10-19 | Wave 0 实现：引用表补 `update_time` 列（task-review 数据库约定）；Repository 只返回父工作流 id，名称由服务补齐 | T03、T04 实现 |
| 2026-10-19 | Wave 1–2 实现：标记识别改为最先进行（决策 10）；`start_node_id` 由引擎预扫得出；`inspect_flow_data` 补 `subflow_ids` 与原因代码；记录 `subflow` 节点日志格式 | T07、T13、T16、T18 实现 |
| 2026-10-19 | Wave 3 实现：10564、10565 的名称字段改为字符串并附机器可读字段；上线时子工作流不存在抛 10561；记录 `subflow_warning` 的响应形态 | T20–T24 实现 |
| 2026-10-19 | Wave 4 实现：子工作流节点改为单分组＋隐藏参数；`CodeInputItem` 加 `fixedKeys`；接口查询静默失败（坑 14）；留空的输入参数沿用子工作流自身的值；保存提醒只接保存与版本卡片 | T25–T32 实现 |
| 2026-10-20 | 119 验证后的修复：失败原因改由前端解析标记并本地化（决策 10）；`isVarInFlow` 识别 `subflow_output`（PR #2509）；节点日志浮层提升层级；`CodeInputItem` 名称校验统一；`CodeInputItem` 的「引用」行接入运行前检查；补坑 15–18 | T34 补验发现 |
| 2026-10-20 | `/sdd-code-review` 修复：新增决策 13 与 10566（新增引用要求编辑权限）；删除先检查删除权限再拦截（坑 10）；引用同步并发重试（决策 7）；【结束】节点空引用兜底；编辑页版本下拉切换前等待保存并弹提醒；`SubflowSelectItem` 接口查询成功后才切换；`SUBFLOW_ERROR_MARKER` 记为前后端契约（§6.1）；补坑 19 与 §8 三项 | 代码审查 NEEDS_FIX |
| 2026-10-20 | 决策 13 补记：复制含子工作流的工作流同样要求对其子工作流有编辑权限，没有则 10566 | 用户确认接受该行为变化 |
