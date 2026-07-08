# 灵思任务模式 write_file 死循环（recursion_limit=200）根因分析与优化方案

> 技术方案（先文档后代码的对齐产物）。范围：核心三层 L2+L3+L4（不改 system prompt、不动 max_tokens）。

## Context / 背景

客户环境（COFCO，模型 Qwen3.6-35B-A3B，MoE 3B 激活）任务："挖掘二级市场投资机会，形成报告"。
- 澄清问答 + 10~11 次知识库检索（~92s）正常，拿到大量券商研报。
- 进入写报告环节：模型调用 `write_file` 时参数缺 `content` → 报错 `content: Field required` → 反复重试（在"空参 `{}`" 和 "只有 `file_path`" 之间横跳）**62 次** → 撞 LangGraph `recursion_limit=200` → 任务失败，前端只显示通用"任务执行失败"卡片。耗时 **1133s（~19 分钟）**。

现场初判：①模型能力弱（填不进大文本参数）②框架缺同工具连续失败熔断。**核实后修正为：根因是"content 是巨大的工具参数被截断/解析丢弃"，模型能力只是诱因之一，框架侧有三个叠加缺口。**

---

## 根因分析（已核实到源码行）

### A. 现象的机理链（"为什么报的是 `content: Field required`"）

1. 灵思用 `agent.astream(..., stream_mode=["updates","messages","values"])` 驱动图（`linsight/domain/task_exec.py:804`）。`stream_mode="messages"` 挂上 `StreamMessagesHandler`（`langgraph/pregel/_messages.py:49`，是 `_StreamingCallbackHandler`）→ agent 节点里的 `model.ainvoke` **内部走流式**，tool-call 参数逐块拼接后用 **`parse_partial_json`（容错 JSON 解析）** 解出（`langchain_core/messages/ai.py:541`）。

2. `parse_partial_json` 对**被截断的参数串**有决定性行为（`langchain_core/utils/json.py:113-131`）：
   - 截断落在 **content 值开始之前**（`{"file_path":"x.md"` / `{"file_path":"x.md",` / `{"file_path":"x.md","content"`）→ 回溯**丢弃**残缺的 content 键 → 解出 `{"file_path":"x.md"}` 甚至 `{}` → **content 键整个消失**。
   - 截断落在 **content 值已吐出部分字节**（`{...,"content":"半截`）→ 自动**补全**成 `"半截"` → 校验通过，写出**截断短文件**（不报此错）。

3. content 缺失的 args dict 被当作**合法 tool_call**（不是 invalid_tool_call）派发给 ToolNode，撞 `WriteFileSchema`（`deepagents/middleware/filesystem.py:334-338`，`content` 必填、无默认）→ 抛 `content: Field required`（`langgraph/prebuilt/tool_node.py:956-966`），包成 error `ToolMessage` 回喂模型 → 模型重试 → 循环。

> **∴ `content: Field required` 是"截断落在任何 content 字节到达之前"的正向证据**——不是"模型不知道要传 content"，而是"content 还没来得及吐 / 残缺 JSON 被解析器丢了"。

### B. 为什么偏偏这个大参数出事（三个放大因素，均已核实）

- **无 max_tokens 兜底**：灵思链路从不传 `max_tokens`，只有管理员在模型 DB `config` JSON 手填才有；无代码级默认（`llm.py:281-282` 是唯一入口；`agent_factory.py:748` 只传 temperature）。输出预算实际由推理服务端 context 窗口（`max_model_len`）兜底。
- **上下文被检索结果挤占**：11 次券商研报检索灌进上下文，留给"吐一篇大报告正文"的输出空间被大幅压缩。
- **reasoning 再吃预算**：Qwen3 是 reasoning 模型，正式吐 tool call 前先吐大段 `reasoning_content`（`chat_openai_reasoning.py:70-95` 仅塞进 `additional_kwargs`），进一步逼近 `finish_reason=length`。

### C. 三个框架缺口（把一次截断放大成 19 分钟空转）

1. **无 `finish_reason=="length"` 检测**：截断响应是正常 HTTP 200、不抛异常；容错中间件 `resilience_middleware.py` 只分类**异常**，看不到它 → 直接掉进 pydantic 校验循环。
2. **无同工具连续失败熔断**：`linsight/` `tool/` 全无 consecutive/circuit/retry-cap 守卫；唯一兜底是 `recursion_limit=max_steps=200` → 62 次 ×~18s ≈ 1133s。
3. **失败态是通用卡片**：`GraphRecursionError` 无专门捕获，`classify_for_event` 归 `ErrorType.UNKNOWN` → 前端渲染通用"任务执行失败"。

### 结论

根子在 **content 是一个巨大的工具参数**，在被检索结果 + reasoning 挤占的上下文里被截断/解析丢弃；叠加"无 length 检测 + 无熔断 + 通用失败卡片"三个框架缺口，放大成 ~19 分钟空转。**不是"模型能力弱到数不清 2 个参数"**。现象里偶发的 `{}`（完全空参）略偏"模型畸形调用"一支，故最可能是**两支混合、以 content 过大/截断为主**——两支的修法一致。

### 待客户日志坐实项（区分主因、用于调参，非阻塞）

1. 失败调用的 `finish_reason` 是否 `length`；
2. 模型吐出的**原始 `arguments` 串**（是 `{"file_path":"...",` 被切断，还是干净的 `{}`）；
3. 当时 **prompt token 数 vs 模型 context 窗口**；
4. 服务端 `max_tokens` / `max_model_len` 配置。

---

## 优化方案（三层，按对本根因的针对性排序）

> 设计取向沿用灵思既有容错风格：厂商无关、复用现有中间件装配点（每图一实例：主图 + researcher 子代理各一）、软约束缓解 + 硬兜底保底。

### Layer 2 · 截断即时检测与纠偏（model-call 层，最佳靶向）
`LinsightModelResilienceMiddleware.awrap_model_call` 拿到模型返回后，检测 `finish_reason == "length"` 且带**参数缺失/被截断的 tool_call**：
- 注入针对性纠偏（"上次输出因过长被截断，请把文档拆成多个较小部分分次写入；或缩短单次 content"）→ **有界重试（默认 ≤2 次）**。
- 重试仍截断 → 落 L3/L4 兜底（走抢救路径）。
- 唯一在**故障发生的那一刻**就拦住的修法，避免掉进 pydantic 循环。行为分桶仍纯用 `finish_reason`/消息形状，不碰厂商码。

### Layer 3 · 同工具连续失败熔断（tool-call 层，兜底）· 优雅终止 + 抢救中间产物
新增 `LinsightToolLoopBreakerMiddleware`（`AgentMiddleware`），复用 `agent_factory.py:459 _empty_retry_count` 的消息遍历范式：
- **计数**：走 `state["messages"]` 尾部，统计"连续、同一工具名、`status=="error"`"的 ToolMessage 段（一次成功/新 human 轮重置）。
- **soft 阈值**（默认 3）：`awrap_tool_call` 给返回的 error ToolMessage **追加强化纠偏提示**（write_file：内容可能过长被截断→分段写；务必把完整文本放进 content）。
- **hard 阈值**（默认 8）：**优雅终止 + 抢救**：
  1. 从 `state["messages"]` 抢救：模型**分析结论**（AIMessage 文本）+ **检索到的知识**（`search_knowledge_base` 结果 ToolMessage，精简）。
  2. 组装 = 道歉前言 + 抢救内容。
  3. 作为**任务结果返回给用户**（COMPLETED，非红色报错）。
- propagation：`aafter_model` 命中 hard 抛携带 `partial_result` 的 `LinsightToolLoopError`（内置 `ToolCallLimitMiddleware` 的成熟范式，能干净冒泡出 astream）。外层 `task_exec._handle_task_partial` 把 `partial_result` 渲染为可读结果（镜像 `_handle_direct_answer_completion`）。
- 每图一实例，主图 + researcher 子代理都挂。
- 效果：62 次/1133s → hard 阈值内（数秒~1~2 分钟），且用户拿到有意义的中间产出。

### Layer 4 · 超限/终止的有意义收尾（友好态 + 抢救）
- `GraphRecursionError`（其它原因触顶）与 L3 终止异常 → 同样走 `_handle_task_partial`（GraphRecursionError 无 `partial_result`，退化用 `_last_assistant_text`）。
- 确无可抢救内容 → 友好分类失败（`llm_error_classifier` 加 `ErrorType.TASK_ABORTED` + 友好中文 error_message），不再是裸 recursion 文本 / UNKNOWN 通用卡片。

---

## 涉及文件与复用点

| 层 | 文件 | 动作 |
|----|------|------|
| L3 | `linsight/domain/services/tool_loop_middleware.py`（新增） | `LinsightToolLoopBreakerMiddleware` + `build_*` + `LinsightToolLoopError(partial_result=...)` + 抢救组装；复用 `agent_factory.py:459` 遍历范式 |
| L3 | `linsight/domain/services/agent_factory.py` | 主图（~640）+ 子代理（~702）装配新中间件 |
| L3/L4 | `linsight/domain/task_exec.py` | `__init__` 加抢救字段；`_execute_agent_tasks` 捕获 `LinsightToolLoopError`/`GraphRecursionError`；`_handle_task_completion` 加分支；新增 `_handle_task_partial` |
| L4 | `common/services/llm_error_classifier.py` | `ErrorType.TASK_ABORTED` + `label_error` 识别 `GraphRecursionError`/`LinsightToolLoopError` |
| L2 | `linsight/domain/services/resilience_middleware.py` | `awrap_model_call` 加 `finish_reason=length`+缺参 tool_call 检测 → 纠偏 + 有界重试 |
| 配置 | `core/config/settings.py:386 LinsightConf` + `initdb_config.yaml` | `tool_failure_soft_limit=3` / `tool_failure_hard_limit=8` / `truncation_retry_limit=2`（可配，复用 `get_linsight_conf`） |
| 测试 | `test/linsight/test_tool_loop_middleware.py`（新增） | soft 追加提示 / hard 抛携带 partial_result 的终止 / 成功重置 / 非错误与 interrupt 透传 / 抢救组装 |

---

## 决策记录

- **范围**：核心三层 L2+L3+L4，不改 prompt、不动 max_tokens。
- **L2 截断动作**：纠偏 + 有界重试（≤2），仍截断落 L3/L4。
- **L3/L4 收尾**：优雅终止 + 抢救中间产物（道歉前言 + 分析结论 + 检索知识精简）；正常结果渲染（非红色卡片）；无可抢救则友好分类失败。
- **阈值**：L2 重试 ≤2、L3 soft=3 / hard=8，均可配 `LinsightConf`。

---

## 实施顺序（编码波次）

1. **Wave 1 · L3 熔断 + 抢救 + L4 收尾**（止血核心）。
2. **Wave 2 · L2 截断即时检测**（源头减少触发）。
3. **Wave 3 · 验证**：单测 → 本地端到端 → 客户日志坐实项回填、微调阈值。

> 波次可独立上线：Wave 1 先止血，Wave 2 再从源头减少触发。

---

## 验证方法

1. **单测**（`test/linsight/`，`asyncio_mode=auto`）：
   - L3：连续 `write_file` error ToolMessage 序列 → soft 追加提示、hard 抛终止（携带 partial_result）、一次成功后重置、非错误 ToolMessage 与 `ask_user` interrupt 透传不受影响；抢救组装。
   - L2：mock `finish_reason=length` + 缺参 tool_call → 命中截断分支并按动作处理。
   - L4：`GraphRecursionError`/`LinsightToolLoopError` 映射到 `TASK_ABORTED` 而非 UNKNOWN。
2. **端到端**（本地起前后端 + 连 test 环境中间件）：确定性逼出（工具必然缺参失败 / mock 截断）→ 任务在 hard 阈值内数秒终止、**抢救内容作为正常结果渲染**（道歉前言、非红色报错），而非 200 步/1133s。
3. **客户侧确认**：按"待坐实项"捞日志，验证 finish_reason/arguments 与假设一致，据此微调阈值。

---

## 实现与验证记录（2026-07-04）

已落地（Wave 1 + Wave 2）：
- **L3** `tool_loop_middleware.py`（新增）：`awrap_tool_call` soft 提示 + `aafter_model` hard 抛 `LinsightToolLoopError(partial_result=...)`；两个防误杀守卫（模型改出纯文本 / 切换工具则不熔断）；抢救组装（分析结论 + 检索知识精简）。装配到主图 + researcher 子代理。
- **L2** `resilience_middleware.awrap_model_call/wrap_model_call` 重构为 while 双预算循环（异常重试 vs 截断重试互不挤占）：`finish_reason∈{length,max_tokens,...}` + 带 tool_call → 注入"分段写"纠偏并有界重试（默认 ≤2），仍截断则交 L3/L4。
- **L4** `llm_error_classifier`：`ErrorType.TASK_ABORTED` + `_is_task_aborted`（识别 `GraphRecursionError` 与 `LinsightToolLoopError`，后者按类名匹配避免 common→linsight 反向依赖）。
- **抢救渲染** `task_exec._handle_task_partial`（镜像 `_handle_direct_answer_completion`）：COMPLETED + 道歉前言 + 抢救正文 + 合成/收集产物文件 + `FINAL_RESULT` 事件（正常渲染，`output_result.partial=True` 标记）。无可抢救时降级 `_handle_task_failure`（TASK_ABORTED 友好卡片）。
- **三条驱动路径统一**：`_stash_partial_abort` 助手被 fresh(`_execute_agent_tasks`)/resume(`_drive_resume`)/continue(`_drive_continue`) 三处 astream 循环共用 → 任一路径的 tool 循环/超限都走抢救。
- **配置** `LinsightConf`：`tool_failure_soft_limit=3` / `tool_failure_hard_limit=8` / `truncation_retry_limit=2`（可配）。

验证：
- 单测 **72 通过**（L3 15 + L2 9 + 既有 resilience 8 + classifier 39 + 1 集成）；生产文件 ruff 干净。
- **集成测试**（`create_agent` + 假模型循环调用缺参工具）证实 `aafter_model` 抛异常能干净冒泡出真实 `ainvoke`、在 recursion_limit 之前熔断——本设计的承重假设成立。
- 待做：连 test 环境的完整前后端 E2E（真实弱模型/大报告，观察抢救卡片渲染与降频）+ 客户日志坐实项回填。

实现教训：`ruff --fix`（PostToolUse hook）会删「当下未被引用」的 import——先加 import 后加用法会被静默删掉，导致运行期 NameError（本次踩了 4 次：GraphRecursionError×2、两个中间件 import）。规则：**先写用法、再补 import**。
