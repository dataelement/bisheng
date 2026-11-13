# F132 验证记录

本文件记录 Wave 0 的基线与待验证项 V1–V8 的结论（2026-11-13，无人值守开发）。结论如何回写 design，见文末"回写分级"；需要用户确认的事项在 `pending-confirmation.md`。

## 基线

- **运行前置条件**：本 worktree 软链主检出的 `src/backend/.venv` 与 `src/frontend` 各级 `node_modules`，从主检出复制 `src/backend/bisheng/config.yaml`。后端测试必须清掉六个代理变量（SOCKS 代理会让 httpx 在收集阶段报 ImportError），并用 `uv run --no-sync python -m pytest`（不同步共享环境；`-m pytest` 让 `bisheng` 解析到本 worktree 的代码）。
- **基线在独立的干净 worktree 上生成**：本 worktree 在基线运行期间已有改动，为避免污染，基线在 `git worktree add --detach <scratchpad>/basewt ba7ca05695` 上运行（该提交只含文档，代码等于 `origin/feat/3.0.0@741662475b`）。
- **分片运行**：串行全量约需 5 小时（无中间件时大量用例在连接超时上等待）。改为按 `test/` 下顶层条目轮转分 8 片并行，基线与每次比对使用同一分片规则（`shard_run.py`），合并成一个 junit 文件再比较。
- **收集错误**：基线里 `test/app_runtime/test_runtime_management.py`、`test/knowledge/test_knowledge_chat_history_retention_worker.py` 两个文件在收集阶段 ImportError（与本功能无关），所以运行带 `--continue-on-collection-errors`。
- **架构检查基线**：`baseline/arch-guard.txt`，51 行，其中 23 行 VIOLATION（与本功能无关的既有违规）。
- **后端基线数量**：`baseline/shard_run.py` 8 片合并后共 14379 个用例，其中 1321 个失败或报错（无中间件、既有缺陷），耗时约 13 分钟。各片汇总行：173 failed/10 errors、5 failed、15 failed/6 errors、472 failed、383 failed/9 errors、49 failed/54 errors、114 failed/15 errors、15 failed。
- **〔基线比对〕的命令**（工作目录 `src/backend/`）：`python3 ../../features/v3.0.0/132-long-term-memory/baseline/shard_run.py $PWD /tmp/f132-current.xml 8 && python3 ../../features/v3.0.0/132-long-term-memory/baseline/compare_junit.py ../../features/v3.0.0/132-long-term-memory/baseline/backend.xml /tmp/f132-current.xml`。

## 回写分级（T009）

| 项 | 结论 | 与 design 的关系 | 分级 |
|---|---|---|---|
| V1 助手回调脱敏 | 可行，按 `run_id` 识别；`on_tool_error` 拿不到工具名，只能靠 `run_id`；`intermediate_steps` 也要脱敏 | 做法不变，落点更精确，补 `intermediate_steps` | 自己定（更严） |
| V2/V8 登记回调 | 可行：`dispatch_client` 加默认 `None` 的 `memory_register` 参数，只有登录态两个 endpoint 传值；助手在 `init_gpts_agent` 开头调用，工作流在拿到 `chat_id` 后调用 | 做法不变；补助手异常分支的一轮结束 | 自己定 |
| V3 深度研究脱敏 | 可行：`_handle_exec_step` 入口一处覆盖库、Redis、WS；压缩写文件实际在 deepagents 的 `_offload_to_backend`；大结果卸载三条路径，在工作区 `write/awrite` 拦截带固定前缀的记忆输出；记忆工具加入子 agent 禁用名单 | 落点改动、增加约束，方向更严 | 自己定（更严） |
| V4 工作流取值 | 可行：`GraphState` 增加两个冻结字段；开关查询放在 `worker/workflow/tasks.py`，不放 `GraphEngine.init_nodes`（发布校验也会构造引擎）；"上线版本"= `is_current=1` 且 `flow.status==2` | 位置改动，判定更严 | 自己定（更严） |
| V5 助手注入 | 消息能送达；正确做法是裁剪结果先复制再插入、`run()` 返回前按 id 剔除 | 决策 11 的实现细节更正，行为不变 | 自己定 |
| V6 管理端接口 | 助手/工作流页走 `/session/chat/history` 渲染 `category=tool` 行；日常页只在 `msg` 为空时回落渲染原始 JSON | T080 的落点更正 | 自己定 |
| V7 深度研究轮次 | 主路径每一轮新建 svid 与任务消息行，按 `message_id`/svid 关联可行；只有 `/workbench/continue` 路径符合原假设，且其追问问题不落库、上一轮结果被覆盖 | **推翻**决策 7、15 的深度研究前提；`/continue` 路径的整理口径需用户选择 | 要用户确认（P-01），先按保守做法继续 |

---

## F132 Wave 0：V1 / V2·V8 / V5 验证结论（助手与工作流）

代码基线：worktree `elegant-bouman-6dde5b`，分支 `feat/v3.0.0/132-long-term-memory`，未改任何产品代码。路径省略前缀 `src/backend/bisheng/`。

实验测试运行结果（`pt.sh test/memory/spike -q`，含另一任务的 V4 测试）：

```
27 passed, 27 warnings in 4.21s
```

本任务的两个文件单独运行：`pt.sh test/memory/spike/test_v1_callback.py test/memory/spike/test_v5_assistant_inject.py -q` → `11 passed`。

---

## V1（T002）助手工具回调里的脱敏

### 结论

可行，design 决策 10 的"在回调处理器内脱敏"成立，但实现必须**以 `run_id` 为键**，不能以 `kwargs["name"]` 为键。原因是错误路径上 LangChain 不传工具名。测试文件：`src/backend/test/memory/spike/test_v1_callback.py`。该测试用真实的 `StructuredTool.ainvoke(..., config={"callbacks": [handler]})` 驱动真实的 `AsyncGptsDebugCallbackHandler`，只替换了 `ChatMessageDao.insert_one` 与 websocket。

### 取证

- **`on_tool_start` 拿得到工具名**：`serialized["name"]`（`api/v1/callback.py:478`）。同时拿到 `run_id`（UUID），处理器以 `run_id.hex` 为键把入参缓存进 `self.tool_cache`（`:480-484`）。
- **`on_tool_end` 能按 `run_id` 认出同一次调用**：LangChain `BaseTool.arun` 以 `on_tool_end(output, color=..., name=self.name, **kwargs)` 回调（`.venv/.../langchain_core/tools/base.py:1233`），`run_id` 与 start 相同。处理器用 `self.tool_cache.get(run_id.hex)` 取回入参（`callback.py:524`），落库后 pop（`:545`）。测试断言 start/end 的 `run_id` 相同、三个落点的 `extra.run_id` 相同。
- **`on_tool_error` 有 `run_id`，但没有工具名**：LangChain 调用的是 `on_tool_error(error, tool_call_id=...)`（`langchain_core/tools/base.py:1229`）。所以 `callback.py:572` 的 `parse_tool_category(kwargs.get("name"))` 得到 `("", "tool")`，落库行的 category 恒为 `tool`。websocket 帧用的是缓存里的 category（`:558`）。测试 `test_error_path_has_run_id_but_no_name` 断言了这一点。
- **原文的三个出口**：
  1. 开始帧：`callback.py:485-494`。`message` 是 `{"tool_key", "serialized", "input_str"}` 的 JSON，`intermediate_steps` 是 `Tool input: ... input_str`。注意 `serialized` 里还带工具的 `description`。
  2. 结束帧：`:512-522`（正常）、`:556-565`（错误）。`message` 是 `{"tool_key", "output"}`，`intermediate_steps` 带输出原文或错误文本。
  3. 落库：`:532-544`（正常）、`:574-586`（错误），写 `ChatMessage`，`category` 由工具名前缀决定（普通工具为 `tool`），`message` = 输入与输出合并后的 JSON，`intermediate_steps` = 输入步骤 + 输出步骤，`extra` = `{"run_id"}`。
  4. 调试运行（`chat_id` 为空）只下发、不落库（`:526-529`、`:568-571`）。
- **还有两条 debug 日志带原文**：`:474`、`:498`（design §8 已记）。
- **ReAct 执行器下这是唯一的工具落库路径**：见 V5，ReAct 的 `run()` 结果在 `client.py:400` 切出来的工具消息是空的或是 `AgentAction`，路径一什么都不落。所以 V1 这一处脱敏对 ReAct 是必需的。

### 插入位置（当前代码）

在 `AsyncGptsDebugCallbackHandler`（`api/v1/callback.py:399`）内部改，三处都以 `run_id.hex` 为键：

| 位置 | 改动 |
|---|---|
| `callback.py:478` 之后、`:479` 之前 | 若 `serialized["name"]` 以 `memory_` 开头：把 `run_id.hex` 记入一个集合（或在 `tool_cache[run_id]` 里加 `"memory": True`）；把 `input_str` 替换为脱敏 JSON；`serialized` 只保留 `name`。之后 `:479-494` 的缓存与开始帧自然就是脱敏后的内容 |
| `callback.py:503` 之后、`:507` 之前 | 若 `run_id.hex` 属于记忆调用：把 `result` 替换为脱敏 JSON。之后 `:507-544` 的结束帧与落库行都用脱敏内容 |
| `callback.py:552` 之后、`:554` 之前 | 若 `run_id.hex` 属于记忆调用：错误文本替换为中性说明。**只能靠 `run_id`**，此处没有工具名 |
| `_is_nested_tool_run`（`:400-417`） | 不用改。记忆工具若被包装（目前 `AssistantCitationToolWrapper` 只包引用类工具），内层调用本来就被跳过 |

测试里的 `_RedactingHandler` 是这三处改动的原型，断言三个出口都不含原文、非记忆工具不受影响。脱敏内容里的 `item_ids` 要等工具执行完才知道，所以 `on_tool_end` 的脱敏 JSON 应由工具返回值解析而来（工具返回里带 `item_ids`），`on_tool_start` 只能写 `op`。

### 与 design 的偏差

- design §4.4 写的落点 `:472-495`、`:523-545`、`:572-585` 与当前代码一致（行号未漂移）。
- 补充事实（design 未写）：错误路径没有工具名，脱敏判定必须以 `run_id` 为键；ReAct 下路径二是唯一落库路径。不推翻 design 方案。

---

## V2 / V8（T003）登记回调的注入点

### 结论

可行，design 决策 6 的"登录态 endpoint 注入可调用对象、客户端在 `chat_id` 确定或切换时调用"成立。三类路径都汇入同一个 `chat_manager.dispatch_client`（`common/chat/manager.py:235`），由它构造 `ChatClient` 或 `WorkflowClient`。所以注入方式是：给 `dispatch_client` 增加一个默认为 `None` 的关键字参数，只有两个登录态 endpoint 传值。

### 三类路径如何构造客户端

| 路径 | endpoint | 调用 `dispatch_client` | 身份来源 |
|---|---|---|---|
| 登录态助手 | `api/v1/assistant.py:244-259` | `:259`，不带 `session_subject` | `UserPayload.get_login_user_from_ws` |
| 登录态工作流 | `api/v1/workflow.py:381-396` | `:396`，不带 `session_subject` | 同上 |
| 免登录助手 | `public_endpoints/api/endpoints/assistant.py:35-53` | `:44`，带 `session_subject` | `public_execution(...).operator` |
| 免登录工作流 | `public_endpoints/api/endpoints/workflow.py:22-48` | `:39`，带 `session_subject` 与 `execution_snapshot` | 同上 |
| 开放面助手 | `open_endpoints/api/endpoints/assistant.py:160-208` | `:200`，带 `session_subject` 与 `message_admission` | 开放 API 主体 |
| 开放面工作流 | 不存在 WebSocket 入口（`open_endpoints`、`open_api` 下只有助手一个 `@router.websocket`） | — | — |

`dispatch_client`（`manager.py:250-276`）把 `graph_data`、`session_subject`、`execution_snapshot` 作为 `**kwargs` 传给客户端构造函数。`ChatClient` 把 kwargs 存在 `self.kwargs`（`common/chat/client.py:75`），`WorkflowClient` 经 `BaseClient` 存在 `self.kwargs`（`common/chat/clients/base.py:28`）。

### 注入点

1. `common/chat/manager.py:235-247`：`dispatch_client` 签名加 `memory_register: Callable[..., Awaitable[None]] | None = None`，在 `:251-263` 与 `:265-276` 两处构造时原样传入。
2. `common/chat/client.py:76` 一带：`self.memory_register = kwargs.get("memory_register")`；`workflow_client.py:49` 一带同理。
3. `api/v1/assistant.py:259` 与 `api/v1/workflow.py:396`：传 `memory_register=<memory 提供的回调，已绑定 login_user>`。这两个文件是 API 层，可以引用 `memory` 的 domain service；`common/` 下只持有可调用对象，不引用 `memory`，符合 C1。
4. 免登录（`public_endpoints/.../assistant.py:44`、`workflow.py:39`）与开放面（`open_endpoints/.../assistant.py:200`）不改，参数默认 `None`。现有测试 `test/public_endpoints/test_anonymous_identity.py:109`、`test/open_api/test_websocket_tenant_revalidation.py:127` 对 `dispatch_client` 打桩，新增参数带默认值，不影响它们。

### 客户端里 `chat_id` 确定或切换的位置

**助手（`ChatClient`）**：

- 构造时：`client.py:70`，值来自 URL 查询参数 `chat_id`。构造函数是同步的，不在这里调用回调。
- 切换：`client.py:371-372`（`handle_gpts_message` 中无 `input` 的消息即切换），随后 `:376` 调 `init_gpts_agent`。
- 每轮：`client.py:380` 调 `init_gpts_agent`。
- 建议的调用点：`init_gpts_agent` 开头（`client.py:231` 之前），条件是 `self.chat_id and self.memory_register`。`init_gpts_agent` 只有 `:376`（切换）与 `:380`（每轮）两个调用方，一处覆盖两种情形；每轮调用一次 `open`，登记行已存在且时区不变时零写入，与日常模式一致。
- 开放面的特殊点：带 `message_admission` 时 `handle_message` 会 `copy(self)` 出一个 worker（`client.py:110-119`），切换会话只改 worker 的 `chat_id`。开放面不传回调，不受影响；浅拷贝会带上 `memory_register` 属性，而它在开放面恒为 `None`。

**工作流（`WorkflowClient`）**：

- 构造时：`base.py:23`（URL 查询参数）。
- 确定或切换：`workflow_client.py:98` `self.chat_id = message.get("chat_id", "")`，位于 `check_status`。`check_status` 有两个调用方：`action == "check_status"`（`:75`）与 `init_workflow`（`:173`）。`handle_user_input` 不改 `chat_id`。
- 建议的调用点：`workflow_client.py:98` 之后、`:99` 之前，条件 `self.chat_id and self.memory_register`。登录态下 `session_subject` 为 `None`，`:99-119` 不执行。
- 执行模型：`BaseClient.handle_message` 用 `thread_pool.submit` 提交协程（`base.py:54-59`），协程分支走 `asyncio.create_task`（`utils/threadpool.py:30-32`），即与 API 在同一个事件循环、带拷贝的 contextvars。所以回调可以用异步 DAO。
- 评测与调试：调试运行 `chat_id` 为空，`:98` 之后条件不成立，不登记。

### 助手：回答落库后调用 `after_answer_persisted`

| 情形 | 当前位置 | 插入点 |
|---|---|---|
| 正常 | `client.py:430` 落 reasoning，`:431` `res = await self.add_message("bot", answer, "answer")` | `:445` 之后（引用落库完成后）、`:446` 发送之前：`self.gpts_agent.after_answer_persisted(res.id if res else None, interrupted=False)` |
| 中断 | `client.py:462-466` 进入 `save_stopped_response`；后者在 `:351` 落 `break_answer` | `save_stopped_response` 的 `:351` 之后：`after_answer_persisted(res.id if res else None, interrupted=True)`。`question_saved` 为真时 `init_gpts_agent` 已在 `:380` 执行完，`self.gpts_agent` 不为空 |
| 业务错误 / 其它异常 | `client.py:473-480` | 回答不落库；本轮记录应以 `message_id=None` 结束，避免留下悬空行。design 未覆盖这一分支 |

design 写的 `:427-428`（正常）与 `:337-354`、`:461-465`（中断）已漂移，当前分别为 `:430-431`、`:335-352`、`:462-466`。

### 工作流：任务函数让出控制的位置（`end_turn`）

`worker/workflow/tasks.py`：

- 首次执行 `_execute_workflow`（`:58-101`）：`workflow.run()` 在 `:92` 返回后由 `_judge_workflow_status`（`:93` → `:40-55`）分三种结束：成功或失败（`:43-46`）、等待输入（`:47-52`，对象存进 `_global_workflow`）、意外状态（`:53-55`）。异常分支 `:94-101`。
- 继续执行 `_continue_workflow`（`:169-191`）：`:182` `workflow.run(user_input)` → `:183` `_judge_workflow_status`；异常分支 `:184-191`。
- 建议：在 `_execute_workflow` 与 `_continue_workflow` 各加一个 `finally`（`chat_id` 非空时调用），每次函数返回即一次让出控制，覆盖成功、失败、等待输入与异常四种情形。这里是 Celery 线程中的同步代码，需要 `end_turn` 的同步实现（与日常模式中断路径相同）。
- **最后一条消息 id 目前拿不到**：消息由 `RedisCallback.save_chat_message`（`worker/workflow/redis_callback.py:532`）在 `:583` 插入并返回 id，但不保存在对象上。继续执行时 `_continue_workflow` 新建的 `redis_callback`（`tasks.py:171`）不是写消息的那个对象，写消息的是 `workflow.graph_engine.callback`（`workflow/graph/graph_engine.py:47`）。如果 `end_turn` 需要 id，有两个办法：在 `redis_callback.py:583` 之后记 `self.last_message_id = message.id` 并经 `workflow.graph_engine.callback` 读取；或者 `end_turn` 自己按 `chat_id` 查最大消息 id。工作流按 design 决策 15 不做归因，整理水位又按消息表读取，后者足够。

### 与 design 的偏差

- 方案成立，不推翻。
- 行号漂移：助手回答落库与中断落库的行号（见上表）。
- 补充：开放面工作流没有 WebSocket 入口，V8 判据里"开放 API 不被登记"对工作流只需验证免登录路径。
- 补充：助手异常分支（`client.py:473-480`）没有回答行，`after_answer_persisted` 不会被调用，需要另行结束本轮。
- 待定（不属本任务）：助手与工作流的 WebSocket 消息里目前没有时区字段（`client.py`、`workflow_client.py` 中无 `timezone`），决策 13 的"客户端上报一次"在这两个场景要新增字段或沿用用户设置里的时区。

---

## V5（T006）助手两种执行器下的系统消息注入

### 结论

消息送达可行，design 决策 11 的"裁剪之后插入一条系统消息"在两种执行器下都能送到模型。但 design 对切片偏移的描述不准确，改法需要更正为"**插入到裁剪结果的副本里，`run()` 返回前按 id 剔除**"。测试文件：`src/backend/test/memory/spike/test_v5_assistant_inject.py`。它构造真实的 `AssistantAgent`，调用真实的 `init_agent`（`api/services/assistant_agent.py:428-458`）与 `run`（`:576-603`），只跳过 `init_llm`、`init_tools` 两个读库步骤，模型换成记录收到消息的桩模型。真实端点上多条系统消息是否被接受，仍按 tasks.md 留给 T094。

### 消息序列（测试已断言）

- **注入位置必须在最后一条之前**：ReAct 的 `react_run` 把 `inputs[-1].content` 当作问题、`inputs[:-1]` 当作历史（`assistant_agent.py:668-674`）。
- **ReAct**：提示词是 `[System(助手提示词 + 工具说明), *chat_history, Human(问题)]`（`bisheng_langchain/gpts/prompts/react_agent_prompt.py:60-67`）。注入的系统消息进入 `chat_history` 占位符，位于历史之后、问题之前。
- **function call**：`create_react_agent(llm, tools, prompt=prompt)`（`:453`）在每次模型调用时把助手提示词作为第一条系统消息前置，状态里的注入消息原样保留。模型看到的是"助手提示词系统消息在首位，注入的系统消息在问题之前"。
- 两种执行器下工具回调都会触发（测试中 `on_tool_start` 收到 `memory_probe`）。

### `run()` 返回值与 `client.py:400` 切片

`client.py:397-407` 用 `answer = result[-1]`、`new_history = result[len(chat_history):-1]` 切出本轮新增的工具消息。实测发现这个切片依赖三处列表别名，design 原先的"多一条就错一位"只在部分情形成立：

1. `run()` 把问题 append 到调用方的 `chat_history` 上（`assistant_agent.py:585-587`），所以 `len(chat_history)` 已包含问题。
2. `trim_messages` 没有裁掉任何消息时返回**同一个列表对象**（`:570-572`），裁掉消息时返回新列表（`:571` 的切片）。
3. ReAct 的 `react_run` 往 `inputs` 上 append `AgentAction` 和回答（`:679-681`），而未裁剪时 `inputs` 就是调用方的 `chat_history`。

由此得到的实测结果：

| 情形 | 现状（不注入） | 原地插入、不剔除 | 插入副本、按 id 剔除（建议） |
|---|---|---|---|
| function call，未裁剪 | `[tool_call, tool_result]` | 同现状。原因是插入也改了调用方的列表，偏移被抵消；注入消息留在 `client.py` 的局部 `chat_history` 与 `run()` 结果里 | 同现状 |
| function call，裁掉 1 条 | `[tool_result]`（**现存缺陷**：裁掉 k 条，切片就少 k 条，与记忆无关） | 与现状不同：+1 与 -1 偶然抵消；裁掉 2 条时仍错一位 | 同现状 |
| ReAct，未裁剪 | `[]`（结果就是 `chat_history` 本身，切片恒为空，路径一从不落 ReAct 的工具调用） | 同现状 | `[AgentAction]`，走 `client.py:406-407` 的 "unexpected message type" 告警分支，不落库 |

结论：只有"插入副本 + 按 id 剔除"在所有情形下与现状一致（ReAct 多一条告警日志，不落库，不改变持久化结果）。原地插入在未裁剪时看起来正常，裁剪发生时才出错，不容易测出。

### 插入位置（当前代码）

| 位置 | 改动 |
|---|---|
| `assistant_agent.py:592` 之后（`run`） | `inputs = list(inputs)`；若本轮有常驻记忆，`inputs.insert(len(inputs) - 1, SystemMessage(content=..., id=<固定 id>))` |
| `assistant_agent.py:598` 之后、`:601` 之前（`run`） | `result = [m for m in result if m.id != <固定 id>]`；同处对记忆工具的 `AIMessage.tool_calls` 与 `ToolMessage` 做路径一的脱敏 |
| `assistant_agent.py:618` 之后（`astream`） | 同样插入。`astream` 目前在 `client.py` 中没有调用方（`client.py` 只调 `run`，`:391`），可只做插入不做剔除 |
| `client.py` | 不改切片 |

裁剪的预算不包含注入的系统消息（在裁剪之后插入），这是 design 的本意（防止常驻记忆被最先裁掉）；代价是总长度可能超出 `assistant.max_token` 一条常驻记忆的长度。

### 与 design 的偏差

- **需要更正决策 11 第 3 条的措辞**：design 写"`run()` 返回前把这条注入的系统消息从结果里剔除……多出一条会让偏移错一位"。实测是：原地插入时，未裁剪的情形里偏移被列表别名抵消，只在裁剪发生时出错；而如果原地插入后再按 id 剔除，未裁剪的情形反而会错一位（调用方列表多了一条，结果少了一条）。正确做法是先复制再插入，返回前按 id 剔除。方向不变，实现细节需要改写进 design。
- **现存缺陷（与记忆无关，建议另行处理）**：`trim_messages` 裁掉 k 条历史时，`client.py:400` 的切片少 k 条，本轮的前 k 条工具消息不落库。
- **补充事实**：ReAct 执行器下 `client.py:400-407` 从不落工具消息，工具调用只由 V1 的回调路径落库。design 决策 10 的"助手路径一"对 ReAct 是空操作。

---

## 文件

- `src/backend/test/memory/spike/test_v1_callback.py`（新建，6 个用例）
- `src/backend/test/memory/spike/test_v5_assistant_inject.py`（新建，5 个用例）
- `src/backend/test/memory/__init__.py`、`src/backend/test/memory/spike/__init__.py` 在本任务开始前已存在，未改动

---

## F132 Wave 0：V3 / V7 验证结论（深度研究）

代码基线：worktree `elegant-bouman-6dde5b`，分支 `feat/v3.0.0/132-long-term-memory`，2026-11-13。路径省略前缀 `src/backend/bisheng/`。deepagents 版本 0.6.12（`.venv` 指向主检出的 venv）。

实验测试：`src/backend/test/memory/spike/test_v3_linsight_paths.py`，运行结果：

```
pt.sh test/memory/spike/test_v3_linsight_paths.py -q
11 passed, 7 warnings in 1.41s
```

---

## V3：深度研究里工具内容的落点与脱敏切入点

### 结论

V3 成立，可以在落库前脱敏。步骤事件只有一个上游：`StreamEventMapper` 产出的 `ExecStep`，它经过 `task_exec._handle_exec_step` 一个函数同时写进数据库、Redis 任务键和推给前端的 Redis 消息列表。在这个函数入口脱敏一次，三处同时覆盖。design 原先给的三个 mapper 行号（`:631`、`:662`、`:700-712`）也对，但要改三处，并且漏掉乱序到达的路径（下文）。

上下文压缩写的工作区文件不在 `utils.py:104-117`。那几行只是目录常量。真正写文件的是 deepagents 的 `SummarizationMiddleware._offload_to_backend` / `_aoffload_to_backend`，BiSheng 的 `BishengSummarizationMiddleware`（`context_budget.py:144`）继承了它们，没有覆盖。大结果卸载有**三条**独立路径，都会把 `memory_search` 的结果写成 `large_tool_results/<tool_call_id>` 文件，现有的排除名单都不含 `memory_`。

### 实测：一次 `memory_search` 的入参与返回出现在哪里

| # | 落点 | 入参 | 返回 | 证据（测试函数） |
|---|---|---|---|---|
| 1 | `ExecStep` start 帧 `params` | 原文 | — | `test_mapper_start_and_end_frames_carry_raw_args_and_result` |
| 2 | `ExecStep` end 帧 `params` + `output`（`output` ≤ 8000 字符截断） | 原文 | 原文 | 同上 |
| 3 | 子 agent（researcher）里调用：同样的帧，`extra_info.namespace` 有值 | 原文 | 原文 | `test_mapper_subagent_namespace_also_carries_raw_content` |
| 4 | 结果先于调用到达（乱序缓冲 `stream_event_mapper.py:686-690`，合并 `:671-673`） | 原文 | 原文 | `test_mapper_orphan_end_buffered_then_merged_with_raw_content` |
| 5 | 数据库 `linsight_execute_task.history`（会话伪任务行，`id == svid`），start/end 按 `call_id` 合并为一条 | 原文 | 原文 | `test_exec_step_reaches_db_history_redis_task_key_and_ws_list` |
| 6 | Redis `linsight_tasks:{svid}:execution_tasks:{svid}`（1 小时 TTL） | 原文 | 原文 | 同上 |
| 7 | Redis 列表 `linsight_tasks:{svid}:messages` → WS `/workbench/task-message-stream` → 浏览器（事件 `task_execute_step`） | 原文 | 原文 | 同上 |
| 8 | 工作区 `conversation_history/{thread_id}.md`（MinIO `workspace/{svid}/…` + 本地 file_dir），压缩时写 | 原文（XML 格式的 tool_calls） | 原文 | `test_compaction_offload_writes_raw_args_and_result_to_workspace` |
| 9 | 工作区 `large_tool_results/<tcid>`：BiSheng `ToolResultBudgetMiddleware`（结果 > 可用输入 10%） | — | 原文 | `test_bisheng_result_budget_offloads_memory_result_to_workspace_file` |
| 10 | 工作区 `large_tool_results/<tcid>`：deepagents `FilesystemMiddleware`（> 80000 字符；窗口未知、BiSheng 预算未挂时仍生效） | — | 原文 | `test_framework_filesystem_middleware_offloads_huge_memory_result_without_budget` |
| 11 | 工作区 `large_tool_results/<tcid>`：压缩遇到上下文溢出时的尾部裁剪 `_overflow_clip._clip_overflow_tail`（只放过 `read_file`） | — | 原文 | `test_overflow_tail_clip_offloads_trailing_memory_result` |
| 12 | LangGraph 检查点（Redis，7 天） | 原文 | 原文 | 读代码；design 决策 11 已列为已知限制，不脱敏 |
| 13 | 压缩生成的摘要文本（进检查点、再喂给模型） | 可能被模型复述 | 可能被模型复述 | 读代码：`_acreate_summary` 收到的是未脱敏的消息 |

补充观察（读代码 + 测试 `test_mapper_streamed_chunk_args_do_not_reach_params_for_plain_tools`）：流式模型的工具调用，第一个 chunk 只有 name+id，参数后到；mapper 只给 `task` 委派补参数。所以普通工具（含 `memory_search`）在流式模型下落库的 `params` 是 `{}`，非流式时是原文。脱敏函数两种情况都要处理，不能假定 `params` 里一定有 `action`/`query`。

`state_message_manager.py:494-500` 的 info 日志会打印 `params`/`output`，但只对 `step_type ∈ {tool_call, knowledge, subagent, call_user_input}`。mapper 给记忆工具的 `step_type` 是 `tool`（名字不含 `_KNOWLEDGE_TOOL_HINTS`），所以今天不进日志。如果在 `_handle_exec_step` 入口脱敏，这条也自动覆盖。

工作区文件会扩散：`seed_workspace_from_previous`（`workspace_backend.py:444-448`）在同一会话的下一个 svid 开始时把 `large_tool_results/` 整体复制过去；`_sync_workspace_originals` 每轮把它拉回本地 file_dir。所以一旦写进去，删除记忆后这份原文会随会话后续每一轮继续存在。

### 分享链接读任务详情走的接口

`GET /api/v1/linsight/workbench/execute-task-detail?session_version_id=…`（`linsight/api/endpoints/linsight.py:579-617`）→ `LinsightWorkbenchImpl.get_execute_task_detail`（`workbench_impl.py:1995`）→ `LinsightExecuteTaskDao.get_by_session_version_id`，原样返回每行的 `history`。分享人校验在 `:600-615`（`share_link.resource_id == session_id` 或 `meta_data.versionId == svid`），并在 `bypass_tenant_filter_if(share_link)` 下读。落点 5 脱敏后，这个接口自然不含原文，不需要在读侧再处理。

旁支发现（不属于 F132，报告给用户判断）：WS `/workbench/task-message-stream`（`linsight.py:620-640` → `message_stream_handle.py`）没有校验连接者是不是任务主人，任何登录用户拿到 svid 就能订阅实时步骤流。落点 7 脱敏后对记忆无影响，但对其它工具内容是一个独立问题。

### 精确切入点

| 落点 | 切入位置 | 做法 |
|---|---|---|
| 1–7（数据库、Redis 任务键、WS 列表、日志） | `linsight/domain/task_exec.py:1920`，`_handle_exec_step` 第一行（在 `:1921 add_execution_task_step` 与 `:1922 push_message` 之前） | `event = redact_exec_step(event)`：`event.name` 以 `memory_` 开头时，`params`/`output` 换成 `{"redacted": true, "op": ..., "item_ids": [...]}`。一处覆盖 start、end、乱序合并、子 agent 四种帧 |
| 1–7 的备选（design 原方案） | `stream_event_mapper.py:662`（start 帧 `params=args`）、`:711-712`（end 帧 `params`/`output`） | 两处都要改；乱序路径经 `:673` 调 `_build_end_step`，也被 `:711-712` 覆盖。`:631`（`_OpenCall.params`）是内存簿记，不出模块，不必改。不推荐：mapper 现在是"纯翻译器"，入口一处更不易漏 |
| 8 `conversation_history/*.md` | `linsight/domain/services/context_budget.py` 的 `BishengSummarizationMiddleware`（类在 `:144`）新增覆盖 `_offload_to_backend` / `_aoffload_to_backend`（父类 `deepagents/middleware/summarization.py:1225`、`:1300`），先把消息列表里记忆工具的 ToolMessage 内容和 AIMessage 里记忆工具的 `tool_calls.args` 换成脱敏副本，再调 `super()` | 只改写入文件的副本，不动 state |
| 13 摘要文本（可选） | 同类已有的 `_create_summary`（`:242`）/ `_acreate_summary`（`:249`），传入前用同一函数脱敏 | 是否要做由 design 决定：不做则摘要可能复述记忆，与检查点同级 |
| 9 BiSheng 预算卸载 | `context_budget.py:404-424` 的 `wrap_tool_call` / `awrap_tool_call`，在 `:411`、`:422` 判断 `TOOLS_EXCLUDED_FROM_EVICTION` 之前加：名称以 `memory_` 开头时走 `self._clip(...)`（截断+提示），不走卸载 | 与 `ls/glob/grep` 同等处理 |
| 10、11 框架卸载 | 无法按工具名排除：`TOOLS_EXCLUDED_FROM_EVICTION` 是 deepagents 模块常量（`filesystem.py:696`），溢出尾部裁剪（`_overflow_clip.py`）只认 `read_file`。三条卸载路径最后都走 `_offload_tool_message_content` → `backend.write`/`awrite`，写失败时它们都**保留原消息**不卸载（`_message_eviction.py:133-136`、`filesystem.py:2049-2051`）。所以在 `linsight/domain/services/workspace_backend.py:879 write` 与 `:1143 awrite` 入口拒绝写入：路径在 `large_tool_results/` 下、并且内容以记忆工具输出的固定前缀开头时，返回 `WriteResult(error=...)` | 内容前缀判定无状态，多节点安全。要求 `memory_search` 的输出以一个固定标记开头，并把自身长度控制在 80000 字符与"可用输入 10%"之下，否则保留在上下文里也会挤占窗口 |

### 与 design 的偏差

1. design §4.4 与决策 10 把 `utils.py:104-117` 写成"压缩写文件"的位置。那里只是目录常量，写文件的是 deepagents 的 `_offload_to_backend`，切入点应改为 `BishengSummarizationMiddleware` 上新增的覆盖方法。
2. design 只提到"大结果卸载会不会写成工作区文件"。实测是会，而且有三条路径，其中两条在 deepagents 内、按工具名无法排除，需要在 `WorkspaceBackend.write/awrite` 拦截，并要求记忆工具输出带固定前缀、自限长度。这是 design 未写的新约束。
3. 推荐把数据库/Redis/WS 的脱敏收敛到 `task_exec.py:1920` 一处，而不是 mapper 的三个行号。
4. 记忆工具目前不在 `_SUBAGENT_TOOL_DENY`（`agent_factory.py:69-78`），按黑名单规则会被 researcher 子 agent 继承。`memory_write` 是写副作用，按现有惯例应加入该名单；`memory_search` 是否给子 agent 需要 design 明确。子 agent 里的调用同样经过 `_handle_exec_step`，脱敏覆盖不受影响。
5. 落点 13（摘要可能复述记忆）design 未提及，需要明确"处理"或"记入已知限制"。

---

## V7：深度研究追问轮的存储与前端轮次标识

### 结论

design 对"轮"的前提只对一条已基本不可达的路径成立。产品主路径与 design 假设不同，需要用户确认后改写决策 7、15 的深度研究部分。

深度研究有两种"下一轮"：

- **主路径（日常对话 `/c` 里打开任务模式再发一条）**：每一条都是一次新的提交，生成**新的 svid**、新的 `LinsightSessionVersion` 行、新的 `category='task'` 消息行。入口是 `workstation/domain/services/chat_service.py:2699` → `workstation/domain/services/task_submit_service.py:31 submit_task_turn` → `LinsightWorkbenchImpl.submit_user_question`（`workbench_impl.py:265`，`:336` 每次 `uuid4` 新 svid）。前端每一轮是一个独立的 `TaskTurnPanel`（`client/src/components/Chat/AiMessageBubble.tsx:590`），带 `versionId=svid` 和该轮消息的 `messageId`。这里**一轮 = 一个 svid = 一条任务消息行**，不存在"多轮共用同一任务消息行"。
- **`/workbench/continue`（同 svid 追问）**：只在独立页 `/linsight/new` 首次提交后的 `ExecutionFlow` 底部输入框触发（`ExecutionFlow.tsx:305` → `useLinsightManager.tsx:178`）。`/linsight/:id` 打开历史会话是只读（`Sop/index.tsx:64-71`），客户端没有任何导航入口指向 `/linsight/new`（只有手输 URL）。这条路径才是 design K9 描述的"多轮共用同一个任务消息行"。

### 每一轮的问题与结果存在哪里

| 轮的类型 | 问题 | 结果 | 能否按轮读 |
|---|---|---|---|
| 主路径（每轮新 svid） | `linsight_session_version.question`；同时以普通用户消息写入 `chatmessage`（`utils.py:1063 persist_task_user_turn`，调用处 `workbench_impl.py:402`） | `linsight_session_version.output_result`（`answer`、`final_files`、失败时 `error_message`）；`chatmessage`（`category='task'`，`extra.linsight_session_version_id=svid`）的 `message` 字段 | **能**。数据源 `LinsightSessionVersionDao.get_by_id(svid)` 取 `question` + `output_result`；或 `ChatMessageDao` 按 `chat_id` + `category='task'` 取行，用 `extra.linsight_session_version_id` 对应 |
| `/workbench/continue` 追问轮 | **不落库**。只存在于队列项 `continue_question`（`linsight.py:371-376` → `worker.py:400-407`）和 LangGraph 检查点里的 HumanMessage（`task_exec.py:701-703`，Redis 7 天） | 写回**同一个** `output_result` 和**同一条**任务消息行（`utils.py:1017-1019` 原地更新），上一轮结果被覆盖 | **不能**。上一轮的问题和结果在数据库里都不存在；前端的多轮只保存在内存（`useLinsightManager.tsx:150-170` 的 `history`，`roundId = ${versionId}_round_${n}`），刷新即丢 |
| ask_user 补充后恢复 | 用户回答写入伪任务行 `history` 与 `task_data.clarify_answers` | 同一轮，结果同上 | 属于同一轮，不是新轮 |

### 每一轮的开始与结束（代码点）

开始（建本轮概要行、生成 `turn_id`）。推荐放在 worker 里，因为所有入口（`/workbench/submit`、日常对话任务模式、开放 API、`/continue`）都在这里汇合；开放 API 用 `is_unattended_run(session_model)`（`linsight/domain/services/unattended_run.py:20`）跳过：

| 轮的开始 | 位置 | 说明 |
|---|---|---|
| 新 svid 的首轮 | `linsight/domain/task_exec.py:732` 之后（`_execute_workflow` 里 `persist_task_turn_message` 刚写/更新了占位任务消息行） | 此时任务消息行已存在，`message_id` 可直接取到（对主路径，决策 15"回答行还没插入"的前提不成立；占位行在提交时就由 `task_submit_service.py:76` 写入） |
| `/continue` 追问轮 | `task_exec.py:660` 之后（`_continue_workflow` 里状态翻回 IN_PROGRESS） | 追问问题只有这里拿得到（参数 `question`），要在这里写进本轮概要行，否则以后读不到 |
| ask_user 恢复 | `task_exec.py:521`（`_resume_workflow`） | 不是新轮：按 svid 取最近一条未结束的本轮概要行，复用其 `turn_id` |

如果坚持 design 写的 API 层（`linsight.py:174`、`:327`）建行：`:174` 覆盖不到主路径（主路径走 `chat_service.py:2699`），需要改成 `submit_user_question`（`workbench_impl.py:265`）或 `task_submit_service.py:31`；并且 `turn_id` 还得经队列项或数据库传给 worker 才能进 `MemoryContext`。所以不推荐。

结束（调 `end_turn`）。design 列的 4 个点（`:1990`、`:2075`、`:2369`、`:2440`）不全：

| 结束方式 | 现有处理 | 本轮结果已落库的位置 |
|---|---|---|
| 成功 | `_handle_task_success`（`task_exec.py:2440`） | `:2489` `persist_task_turn_message` 之后 |
| 部分结果 | `_handle_task_partial`（`:2369`） | `:2433` 之后 |
| 直接回答 | `_handle_direct_answer_completion`（`:2075`） | `:2137` 之后 |
| 失败（含所有异常 → `_handle_execution_error` `:2597`） | `_handle_task_failure`（`:2538`） | `:2573` 之后。**design 漏了这一条** |
| 用户终止（首轮） | `_handle_user_termination`（`:1990`，由 `:786` 与 `:2027` 调用）；任务消息行由 API 侧 `workbench_impl.py:463-475` 写 | API 侧已写 |
| 用户终止（`/continue` 轮与恢复轮） | **不调** `_handle_user_termination`：`_check_termination` 抛出的 `UserTerminationError` 在 `async_continue`（`:640`）/ `async_resume`（`:471`）里只记日志 | API 侧已写。**按处理函数挂 `end_turn` 会漏掉这条** |
| 停在等待用户补充 | `_handle_need_user_input`（`:1901` 置 `_waiting_for_input`，`:1910` 改状态） | 不是轮结束，不调 `end_turn` |

推荐只挂一处：在三个入口 `async_run`（`:363`）、`async_resume`（`:443`）、`async_continue`（`:611`）的 `finally` 里（`:399`、`:481`、`:650` 的 `finally` 里、tenant 复位之前）调用一个 `_end_memory_turn()`：`self._waiting_for_input` 为真则跳过；否则按 svid 取本轮概要行并调 `end_turn`，`last_message_id` 取该 svid 的任务消息行 id。这样成功、部分、直接回答、失败、终止（含续轮终止）、`TaskAlreadyInProgressError`（无行则无操作）全部覆盖。

### `turn_id` 怎样到达前端每一轮的面板

前端已经收到的、每一轮唯一的标识：

- 主路径：`TaskTurnPanel` 的 `versionId`（= svid，来自 `chatmessage.extra.linsight_session_version_id`）以及 `linsight.message_id`（来自 `GET /workbench/session-version-list`，`linsight.py:511-576` 里 `get_task_feedback_by_version` 按 svid 回填 `message_id`）。`FINAL_RESULT` WS 事件的 `data` 是 `session_model.model_dump()`，含 `id`=svid。
- `/continue` 页：只有前端自造的 `roundId`，后端没有对应物。

推荐做法：

1. 主路径按 svid 取数，不需要把 `turn_id` 送到前端。记忆接口提供"按 `linsight_session_version_id` 取本轮操作提示与归因"；一个 svid 在主路径下恰好一轮，`TaskTurnPanel`（`TaskTurnPanel.tsx:273` 的 `ResultPanel`）直接用 `versionId` 调。也可以在 `ResultPanel`（`ResultPanel.tsx:58`，与点赞并列）用 `messageId`，因为主路径的任务消息行在轮开始前就存在。
2. 实时信号：design 已计划在 `MessageEventType`（`state_message_manager.py:31-44`）新增一个记忆事件，事件 `data` 带 `turn_id` 与 svid。`/continue` 页在 `useLinsightManager.tsx:150-170` 把当前轮快照进 `history` 时一并保存该轮收到的 `turn_id`。刷新后该页本就不显示历史轮，不需要持久化回放。

### `_generate_tools` 调用点与中间件插入位置（确认）

- `_generate_tools` 定义在 `task_exec.py:1097`（内部调 `LinsightWorkbenchImpl.init_linsight_config_tools`）。调用点确认是 `:537`（恢复）、`:668`（追问）、`:749`（首轮），之后各自在 `:550`、`:674`、`:758` `tools.extend(linsight_tools)`。三处都只经过 `_generate_tools`，所以把记忆工具追加在 `_generate_tools` 内部（`:1101` 的 `return` 之前）一处即可覆盖三条路径，比改三个调用点更不易漏。注意记忆工具进入 `tools` 后会被 researcher 子 agent 按黑名单继承（见 V3 偏差 4）。
- 中间件顺序（`agent_factory.py:create_linsight_agent`，`:1400`）：主图列表从 `:1492` 开始；引用尾部中间件在 `:1558-1559` 追加，语言尾部在 `:1564` 追加。新中间件应插在 `:1553`（技能块结束）之后、`:1555` 注释（`# F069: citation requirement restated…`）之前。注意 `:1598-1600` 还会在语言尾部之后追加 `build_invalid_tool_call_repair_middleware`；它不追加系统提示词，所以"引用、语言两个尾部在系统提示词末尾"仍成立，但"两者在列表最末"的字面说法不对。researcher 子 agent 有自己的列表（`:1610-1637`，引用尾 `:1629`、语言尾 `:1633`），design 只要求主图带入常驻记忆；若子 agent 也要，插在 `:1628` 之前。
- 尾部中间件类定义：`_LanguageTailMiddleware` `agent_factory.py:222-259`，`_CitationTailMiddleware` `:289-296`。

### 与 design 的偏差

1. **K9 / 决策 7 / 决策 15 的前提只适用于 `/continue`**。主路径（日常对话里的任务模式）每轮新 svid、新任务消息行，任务消息行在轮开始前已插入。按 `message_id` 关联在主路径上可行，按消息水位整理也不会"越过追问轮"。
2. **`/continue` 追问轮的问题和上一轮结果不落库**，无法"从深度研究自己的存储里按轮读取"。可选方案（需用户拍板）：
   - A. 本轮概要行在开始时存问题、结束时存结果快照（记忆模块存了对话内容，与"不直接查深度研究的表"一致，但表变大）；
   - B. 深度研究模块新增按轮存储（例如 `linsight_session_round` 表，开始写问题、结束写结果），整理时经它的 Service 读取；
   - C. 鉴于 `/continue` 只在没有导航入口的 `/linsight/new` 页可用，本期把 `/continue` 轮排除在整理之外，记入 §8。
3. 轮开始的 API 入口漏了日常对话任务模式（`chat_service.py:2699` → `task_submit_service.py:31`）；推荐改在 worker `task_exec.py:732` / `:660` 建行。
4. 轮结束漏了失败路径 `:2538`/`:2573` 和续轮终止；推荐改为三个入口的 `finally` 一处。
5. `turn_id` 不必送到主路径前端：按 svid（或 `message_id`）取即可；只有 `/continue` 页需要靠新增的 WS 记忆事件带 `turn_id`。

---

## F132 Wave 0 验证：V4（T005）与 V6（T007）

路径前缀：后端 `src/backend/bisheng/`，前端 `src/frontend/`。行号取自当前 worktree（分支 `feat/v3.0.0/132-long-term-memory`）。

---

## V4：工作流节点取 `chat_id` 与上线版本的开关

### 结论

V4 成立，但实现位置与 design 决策 17 的写法有两处偏差。节点可以通过共享的 `graph_state` 读到 `chat_id` 与一个只读开关：`GraphEngine.__init__` 在 `build_nodes()` 之前创建 `GraphState()`（`workflow/graph/graph_engine.py:69`），所有节点持有同一个对象引用，节点 `_run` 时能读到构造时写入的值。实验测试已跑通：

```
test/memory/spike/test_v4_graph_state.py  5 passed, 8 warnings in 0.17s
```

测试覆盖四点：现有 `GraphState` 拒绝挂未声明属性（`ValueError`）；声明为 `Field(frozen=True)` 的字段构造后不可改（`ValidationError`）；起始节点 + 假节点 + 结束节点组成的真实 `GraphEngine` 跑完后，假节点 `_run` 读到 `chat_id` 与 `memory_enabled`（含评测/调试场景的 `chat_id=""`）；用现成的 `BaseNodeData.get_variable_info` 从 `flow_version.data` 里读出开始节点参数，参数缺失时返回 `None`。

### 现状事实

**GraphEngine 今天拿不到 `chat_id`。** `chat_id` 只进了 `RedisCallback`。调用链是 `worker/workflow/tasks.py:57 _execute_workflow(unique_id, workflow_id, chat_id, user_id, source)` → `RedisCallback(unique_id, workflow_id, chat_id, ...)`（`:66`）→ `Workflow(workflow_id, workflow_name, user_id, workflow_data, False, max_steps, timeout, redis_callback, tenant_id=, flow_user_id=)`（`:79-90`）→ `GraphEngine(user_id, workflow_id, workflow_name, workflow_data, async_mode, max_steps, callback, tenant_id, flow_user_id)`（`workflow/graph/workflow.py:42-52`）。`Workflow` 和 `GraphEngine` 的构造参数里都没有 `chat_id`。节点理论上可以读 `self.callback_manager.chat_id`，但 `BaseCallback`（`workflow/callback/base_callback.py`）没有这个属性，单节点调试用的就是 `BaseCallback()`，所以不能依赖它。

**`GraphState` 是 pydantic 模型，不允许挂任意属性**（`workflow/graph/graph_state.py:8`）。必须在类里声明 `chat_id: str = Field("", frozen=True)` 与 `memory_enabled: bool = Field(False, frozen=True)`，并在 `GraphEngine.__init__` 里以构造参数传入（`graph_engine.py:69` 改为 `GraphState(chat_id=..., memory_enabled=...)`）。

**`GraphEngine` 的全部实例化点**（`Workflow(` 只在两处被构造）：

| 调用点 | 用途 | `chat_id` |
|---|---|---|
| `worker/workflow/tasks.py:79` `_execute_workflow` | 真实运行（登录态 WS、开放 API、评测都走它） | 来自任务参数 |
| `api/services/workflow.py:1240` `update_flow_status` ONLINE 分支 | 上线前做初始化校验，`callback=None` | 无 |
| `api/services/workflow.py:1163-1174` 单节点运行 | 不建 `GraphEngine`，直接 `GraphState()` + `NodeFactory.instance_node` | 无 |

**续跑路径不重建图。** `_continue_workflow`（`tasks.py:170-189`）从进程内的 `_global_workflow[unique_id]` 取回同一个 `Workflow` 对象，`graph_state` 原样保留。所以 `chat_id` 与开关在首次执行时写入一次，等待输入（INPUT）后的续跑沿用首次的值。

**各场景的 `chat_id` 取值：**

| 场景 | 位置 | `chat_id` |
|---|---|---|
| 登录态 WS 运行 | `common/chat/clients/workflow_client.py:98` `message.get("chat_id", "")` → `:183` `execute_workflow.apply_async` | 消息体里的会话 id |
| 画布调试 | 前端 `platform/src/pages/BuildPage/flow/FlowChat/ChatPane.tsx:23/37/69/88` 在 `chatId.startsWith('test')` 时传 `undefined` → 后端得到 `""` | `""` |
| 评测 | `evaluation/domain/services/evaluation_service.py:194` `chat_id = ""`，`:202` 下发任务；`workflow_id = evaluation.unique_id`，图数据是评测选定的版本（`workflow_info.data`），不一定是上线版本 | `""` |
| 开放 API | `workflow/domain/services/published_workflow_service.py:62-67`，无 `session_id` 时生成新 uuid | 非空（按 V8 不登记，`MemoryGate` 查不到登记行即不启用） |
| 单节点运行 | `api/services/workflow.py:1163` | 无 `GraphEngine`，`GraphState()` 默认值 |

**读上线版本开始节点参数的现成方法。** "上线"由两列共同表示：`flow.status == FlowStatus.ONLINE (2)`（`database/models/flow.py:43-45`）；当前版本是 `flow_version.is_current == 1 AND is_delete == 0`。现成方法 `FlowVersionDao.get_version_by_flow(flow_id)`（`database/models/flow_version.py:141-149`，同步，返回 `is_current=1` 的行），没有异步版本。注意：工作流下线后 `is_current` 行仍然存在，所以"上线版本的开关"要同时判断 `flow.status == 2`，否则下线的工作流仍会被当作开启（整理任务判定"现在是否仍开启"时尤其要注意）。

`flow_version.data` 的结构是 React Flow 图：`data["nodes"][i]["data"]` 即 `BaseNodeData`。开始节点参数的路径示例：

```
data["nodes"][k]["data"]["type"] == "start"
data["nodes"][k]["data"]["group_params"][1]["params"][j] == {"key": "chat_history", "value": 10, ...}
```

现成读取方式：`BaseNodeData(**node["data"]).get_variable_info("memory_enabled")`（`workflow/common/node.py:72-77`），返回 `NodeParams` 或 `None`。注意它在 `group_params is None` 时会抛 `TypeError`，调用前要判空。

**开始节点参数的定义位置。** 前端模板 `platform/src/controllers/API/workflow.ts:185-253`（`workflowTemplate[0]`，`type: "start"`，`v: "3"`），两组参数："开场引导"（`guide_word`、`guide_question`）与"全局变量"（`user_info`、`current_time`、`chat_history`、`preset_question`、`custom_variables`）。后端类 `workflow/nodes/start/start.py:17 StartNode`，参数由 `BaseNode.init_data`（`workflow/nodes/base.py:85-92`）平铺进 `self.node_params`，不做校验。模板只影响新拖出的节点，存量工作流的开始节点没有 `memory_enabled`，读取得到 `None`，按"缺失视为关"处理即可。

**节点如何校验参数。** 没有统一的参数校验层。校验靠节点 `__init__` 里抛异常，样板是 `CodeNode` 构造时调 `assert_code_node_enabled()`（`workflow/nodes/code/code.py:19-26`）。上线时 `update_flow_status` 用 `Workflow(...)` 实例化整张图，节点构造抛出的异常被包成 `WorkFlowInitError`。前端另有 `platform/src/pages/BuildPage/flow/hooks/useNodeEvent.ts`（已有 `useNodeEvent.test.ts`）。

### 确切插入点

| 要做的事 | 位置 |
|---|---|
| `GraphState` 声明两个只读字段 | `workflow/graph/graph_state.py:8-15` |
| `GraphEngine` 新增构造参数 `chat_id`、`memory_enabled`，传入 `GraphState(...)` | `workflow/graph/graph_engine.py:28-39`（参数）、`:69`（构造） |
| `Workflow` 透传两个参数 | `workflow/graph/workflow.py:10-21`、`:42-52` |
| 查上线版本开关并传入 | `worker/workflow/tasks.py:57-90` `_execute_workflow`：已在 `:60` 查了 `FlowDao.get_flow_by_id`，在此处加 `FlowVersionDao.get_version_by_flow` 与 `flow.status` 判断，结果连同 `chat_id` 传给 `Workflow(...)` |
| 记忆检索节点读取 | 新节点 `_run` 内读 `self.graph_state.chat_id` / `.memory_enabled` |
| 上线校验 | `api/services/workflow.py:1237-1244`：`version_info.data` 已在手，在 `Workflow(...)` 实例化之前或之后遍历 `version_info.data["nodes"]`，"含记忆检索节点且开始节点 `memory_enabled` 不为真"则抛 `WorkFlowInitError`（或新错误码），`limit` 校验可放进新节点 `__init__`，由同一处 `Workflow(...)` 触发 |

### 与 design 的偏差

1. **查库位置不应放在 `GraphEngine.init_nodes`。** 决策 17 写"工作流实例化时（`GraphEngine.init_nodes`）按 `flow_id` 查一次上线版本的开关"。`GraphEngine` 在上线校验时也会被构造（`api/services/workflow.py:1240`），此时数据库里的 `is_current` 行还是旧版本，查出的是发布前的值；评测运行也会触发查询。建议改为在 `worker/workflow/tasks.py:_execute_workflow` 查一次（它已经在查 `FlowDao`），以构造参数传入 `Workflow` → `GraphEngine` → `GraphState`。`GraphEngine` 本身不碰数据库。§4.4 表"工作流：实例化"一行要同步改。
2. **`GraphState` 要声明字段**，design 写"放进 `graph_state` 的只读字段"，没说明它是 pydantic 模型、必须改类定义。只读用 `Field(frozen=True)` 实现，已验证。
3. **"上线版本"需要两个条件。** design 只写"读上线版本"。`get_version_by_flow` 只看 `is_current`，下线后仍返回行；要加 `flow.status == 2`。
4. **续跑沿用首次的值。** 等待输入后的续跑不重读开关，与 AC-74"一轮开始时取一次"一致，但"一轮"在工作流里跨越多次 INPUT 续跑，可能间隔很久。如需每次续跑重读，要在 `_continue_workflow`（`tasks.py:170`）里重查并替换，但 frozen 字段不能改，需要换成重建或放弃 frozen。建议接受现状并在 design 里写明。
5. 评测与调试的 `chat_id` 为空已确认，与 design 一致。

---

## V6：管理端查看会话所用的接口

### 结论

三个页面共用两条接口，渲染器有两套。助手与工作流会话走 `PlatformConversationMessages` → 共享包 `@bisheng/chat` 的 `ConversationMessages`；日常模式会话走 `dailyChatDetail.tsx` 自带的 `extractDisplayText` + `DailyMessageContent`。**助手路径二的工具行会被渲染出来，而且展开后显示的是 `intermediate_steps` 列，不是 `message` 列。** 只脱敏 `message` 列不够，`intermediate_steps` 也必须脱敏，否则管理员展开工具卡片就能看到原文。这是对 V1 与决策 10 的补充。日常模式的工具事件今天不渲染；深度研究的步骤三个页面都不读。

### 页面 → 接口 → 含工具内容的字段

| 页面 | 前端 API 函数 | 后端端点 | 含工具内容的字段 | 是否渲染 |
|---|---|---|---|---|
| `platform/src/pages/LogPage/useAppLog/appChatDetail.tsx`（助手，`type=5`） | `useMessageStore().loadHistoryMsg` → `components/bs-comp/appChat/historyAdapter.ts:31` `getChatHistory(flowId, chatId, 30, 0)`（`controllers/API/index.ts:1103`） | `GET /api/v1/session/chat/history`（`chat_session/api/endpoints/session.py:21` → `chat_session/domain/chat.py:44` → `ChatMessageDao.afilter_message_by_chat_id`，**不过滤 category**） | 路径二：`category='tool'/'flow'/'knowledge'` 行的 `message`（JSON `{tool_key, serialized, input_str, output}`，`api/v1/callback.py:479-552`）与 `intermediate_steps`（`"Tool input: ... Tool output: ..."`）；路径一：`category='tool_call'/'tool_result'` 行的 `message`（`common/chat/client.py:401-405`） | 路径二渲染为 `run` 卡片；路径一 `kind='hidden'` 不渲染，但接口原样返回 |
| 同上（工作流，`type=10`） | `FlowChat/messageStore.ts:217` 同一个 `createHistoryAdapter(store,'workflow')` | 同上 | 工作流没有记忆工具事件（工作流只有记忆检索节点）；节点运行行 `node_run` 只显示节点名 | — |
| `platform/src/pages/LabelPage/taskAppChats.tsx`（标注，助手/工作流） | 同 `appChatDetail`：`MessagePanne`/`ChatMessages`；另有 `getNextMarkChatApi`、`getMarkStatusApi`（`controllers/API/log.ts:383/394`）只返回 id 与状态 | 同上 + `/api/v1/mark/next`、`/api/v1/mark/get_status` | 同 `appChatDetail` | 同上 |
| `platform/src/pages/LogPage/useAppLog/dailyChatDetail.tsx`（日常模式） | `getChatHistoryApi(cid)`（`controllers/API/index.ts:1279`） | `GET /api/v1/session/chat/messages/{conversationId}`（`chat_session/api/endpoints/session.py:33`，`limit=1000`，`WorkstationMessage.from_chat_message`，`text=message.message` 原样） | `text` 里的 JSON `{msg, events:[{type:"tool_call", tool_name, args, results, ...}]}`（`workstation/domain/services/chat_service.py:2311-2350`）；深度研究轮次是 `category='task'` 行，只带 `linsightSessionVersionId`，页面不据此取步骤 | 不渲染：`extractDisplayText`（`dailyChatDetail.tsx:32-77`）只取 `msg` 与 `type=="thinking"` 的事件 |

补充：`getChatHistory` 里的 URL 切换（`index.ts:1111`）用 `indexOf(...)` 做真值判断，`-1` 为真，实际上管理端恒走 `/api/v1/session/chat/history`。

### 渲染器与占位插入点

**A. `PlatformConversationMessages`（助手与工作流，`components/bs-comp/appChat/PlatformConversationMessages.tsx`）。** 数据流：`historyForHost`（`packages/chat/src/core/historyForHost.ts:12` 把 `intermediate_steps` 复制到 `thought`）→ `messagesForPresentation`（`PlatformConversationMessages.tsx:34`）→ `normalizeHistory` 的 `messageKind`（`packages/chat/src/core/normalizeHistory.ts:12-24`：`tool/flow/knowledge` → `run`，`tool_call/tool_result` → `hidden`）→ `ConversationMessages`（`packages/chat/src/components/ConversationMessages.tsx:68-81`）。`run` 卡片有两处会显示记忆工具：

- 标题 `:78`：`run?.title`，来自 slot `runPresentation`（`PlatformConversationMessages.tsx:45` → `describeRun`）。`describeRun` 按 `payload.tool_key` 在助手的 `tool_list` 里找名字；`memory_search` 不在列表里，会落到"工具已删除"并标红叉（`packages/chat/src/core/describeRun.ts:24`）。**这里要替换为"记忆操作"，且 `unavailable=false`。**
- 展开正文 `:80`：`displayText(message.raw.thought ?? message.raw.intermediate_steps ?? message.payload)`。**这里会显示脱敏结构或（若 `intermediate_steps` 未脱敏）记忆原文，要替换为占位。**

建议的插入点放在平台侧，不改共享包：在 `PlatformConversationMessages.tsx:34` 之后对 `messages` 做一次映射，凡 `kind==='run'` 且 `payload.redacted===true` 或 `payload.tool_key` 以 `memory_` 开头，就把 `raw.thought` 设为占位文案；并在 `:45` 的 `runPresentation` 里对同一判定返回 `{ title: t('memory.operation'), unavailable: false }`。理由：`ConversationMessages` 也被 client 的 `client/src/pages/appChat/ChatMessages.tsx:2` 使用，改共享包会同时改变 client 的应用聊天，而 design 对 client 侧另有渲染方案。若希望两端共用判定函数，可把"是否脱敏的记忆事件"判定放进 `packages/chat/src/core`，渲染替换仍各自做。

**B. `DailyMessageContent`（日常模式，`pages/LogPage/useAppLog/DailyMessageContent.tsx`）。** 它只接收 `extractDisplayText` 产出的字符串，今天不会渲染任何 `tool_call` 事件。唯一的泄漏口是 `dailyChatDetail.tsx:76` `return content || raw`：当回答的 `msg` 为空（例如只调用了记忆工具后中断或出错），会把整段原始 JSON（含 `events`）当 Markdown 渲染出来。插入点：
- `dailyChatDetail.tsx:60-66` 遍历 `events` 处，若存在 `type==='tool_call'` 且 `tool_name` 以 `memory_` 开头（或 `args.redacted`/`results.redacted`），在返回文本里加一行占位"记忆操作"（如果产品要求让管理员看到"这里发生过一次记忆操作"）；
- `dailyChatDetail.tsx:76` 的回退分支，`parsed.events` 存在时不应回退到 `raw`，改为返回占位或空串。
`DailyMessageContent.tsx` 本身无需改动，除非占位要用特殊样式。

### 测试结构

平台端没有 `__tests__` 目录（`find src -type d -name __tests__` 为空）。198 个测试全部与源码同目录放置，命名 `*.test.tsx`，例如 `src/pages/LabelPage/taskAppChats.test.tsx`、`src/components/bs-comp/appChat/scrollHistory.test.tsx`。写法：`vi.hoisted` 建 mock，`vi.mock('@/controllers/API/...')` 替换接口，`@testing-library/react` 的 `render` + `MemoryRouter`。`vitest.config.ts` 的 `include` 是 `src/**/*.{test,spec}.{ts,tsx}`，环境 `jsdom`，`setupFiles: ./src/test/setup.ts`。`pnpm exec vitest --version` 输出 `vitest/3.2.7 darwin-x64 node-v25.8.1`，可用。

### 与 design / tasks 的偏差

1. **`intermediate_steps` 列必须一起脱敏**（最重要）。决策 10 只写"入参与返回替换为 `{redacted...}`"，没点名 `intermediate_steps`。管理端 `run` 卡片的展开正文显示的正是这一列（`ConversationMessages.tsx:80`）。V1 的判据应加上"`chatmessage.intermediate_steps` 不含条目原文"。
2. **记忆工具卡片今天会显示"工具已删除"和红叉**，因为 `describeRun` 在 `tool_list` 里找不到 `memory_*`。T080 需要覆盖标题，不只是正文。
3. **日常模式页面不渲染工具事件**，T080 对 `DailyMessageContent.tsx` 的改动主要是封住 `dailyChatDetail.tsx:76` 的原始 JSON 回退；改动点在 `dailyChatDetail.tsx`，不在 `DailyMessageContent.tsx`。
4. **深度研究步骤不出现在这三个页面**（`linsightSessionVersionId` 未被使用），V6 无需处理 `linsight_execute_task.history`。
5. **T080 测试路径** `src/pages/LogPage/__tests__/memoryPlaceholder.test.tsx` 能被 `include` 匹配，但与仓库同目录放置的惯例不符；建议改为 `src/components/bs-comp/appChat/memoryPlaceholder.test.tsx`（覆盖 A）与 `src/pages/LogPage/useAppLog/dailyChatDetail.memory.test.tsx`（覆盖 B）。
6. 实际渲染组件是共享包的 `ConversationMessages`，`PlatformConversationMessages` 只是包装层；tasks 预期的两个文件仍是正确的平台侧改动点。
7. 旁注（不在本期范围）：`/api/v1/session/chat/messages/{id}` 与 `/api/v1/session/chat/history` 只要求登录，不做会话归属或权限校验（`session.py:21-41`）。AC-09 完全依赖落库脱敏，这一点更说明 `intermediate_steps` 不能遗漏。
