# 灵思任务模式运行链路与 deepagents 上下文工程对比

> 一句话结论：当前灵思任务模式 = **deepagents 内核 + 毕昇企业级"外骨骼"**——单图规划/执行被 deepagents 的 `create_deep_agent` 接管（`write_todos` 现场拆解、内置 SummarizationMiddleware 压缩、WorkspaceBackend 真文件系统），外层包了分布式 Worker 队列、Redis checkpointer 跨进程 park/resume、StreamEventMapper 防腐层与 WebSocket 回传；而 deepagents demo 是同一框架的**最小默认形态**（单进程单图、useStream SSE 直连、子代理并行委派、Skills progressive disclosure 真生效）。毕昇为修 HITL 正确性，**主动砍掉了 demo 引以为核心的 `task` 子代理委派与 Skills 热插拔**——这正是两者最尖锐的分歧。
>
> 本文定位：取代旧两篇调研（《灵思任务模式 vs deepagents demo 上下文工程对比调研.md》《灵思任务模式全局运行链路与 SOP 必要性研判.md》），基于本地最新代码（HEAD=`77beaa6f0`，分支 `feat/2.6.0-beta4`）的真实调用链重写。**2026-06-17 一连串重构（SOP 残留代码整体物理删除、知识检索收窄到知识库/知识空间并改精确注入、SearchKnowledgeBase 改条件注入）已全部折叠进正文为当前真相**，所有毕昇侧锚点为本次实读的 CURRENT 行号；deepagents demo 侧凡未在本仓库复验的论断均显式标注可信度。

---

## 1. 全局运行链路

### 1.1 时序泳道速览

```
用户(client UI)        HTTP/SSE/WS 网关        Redis 队列            Linsight Worker(多进程)        deepagents agent
─────────────         ────────────────        ──────────           ──────────────────────         ─────────────────
点击发送 ──submit(SSE)──▶ submit_user_question
                        ├ linsight_workbench_submit  (落 session_version)
                        └ linsight_workbench_title_generate
   ◀────────────────────┘
直接 start-execute ─POST▶ queue.put(裸 svid) ─RPUSH▶ [svid]
   │                                                    │ BLPOP
   │                                          process_one_item ─acquire 槽─▶ async_run
   ├─连 WS task-message-stream ◀─BLPOP 消费事件队列─ push_message(RPUSH) ◀─ StreamEventMapper ◀─ astream(updates/messages/values)
   │                                                    │                                          ├ write_todos(现场规划)
   │                                                    │                                          ├ 工具调用 / read_file / search_kb
   │                                                    │                                          └ ask_user → interrupt()
   │  收到 call_user_input 卡片                          │  park: astream 自然结束 → done_callback → semaphore.release(归还槽)
   └─答复 user-input ─POST▶ queue.put_head(resume=True) ─LPUSH 头插▶ [resume]
                                                         │ BLPOP(优先)
                                              process_one_item ─acquire▶ async_resume(Command(resume=...) 同 thread_id)
                                                         │                                          └ 续跑 → write_file 产物 → FINAL_RESULT
   ◀────────── FINAL_RESULT 事件(经事件队列→WS)──────────┘  COMPLETED
```

三种通道并存：**submit 走 SSE**（两事件），**start-execute / user-input / continue 走普通 POST**，**执行结果回传走 WebSocket**。

### 1.2 线性叙事（编号即时间序）

**链路一·首次提交新任务**

1. 用户在 landing（`/linsight/new`）输入框敲回车。真实入口是 `TaskModeChatInput`（`components/Sop/index.tsx:45` 守卫 `versionId==='new' && !sopId`，`:55` 渲染），复用日常 `AiChatInput` + `taskMode:true`。`TaskModeInput.tsx` 是另一套 shell，只在执行页底部输入框出现（`ExecutionFlow.tsx:221`），landing 不用它。
2. `handleSend`（`TaskModeChatInput.tsx:78`）构造 submission，调 `setLinsightSubmission('new', {...})`（`useLinsightManager.tsx:175`）写入 Recoil。
3. `useLinsightSubmit`（`useLinsightManager.tsx:204`）固定 watch `'new'` 键，监听到后打开 SSE 连 `/api/v1/linsight/workbench/submit`（`useLinsightManager.tsx:257`），payload 经 `convertTools`（`:393`）把伪工具映射成后端标志位。
4. 后端 `submit_linsight_workbench`（`linsight.py:158`）：校验邀请码，`submit_user_question` 落库 message_session + session_version 并发 `linsight_workbench_submit`；随后 `task_title_generate` + `insert_one`，发 `linsight_workbench_title_generate`。两事件之间**无任何 SOP 生成调用**（SOP 生成代码已物理删除）。`submit_user_question` 构造 `LinsightSessionVersion` 时**不传 `sop` 字段**，该字段默认 None（`linsight_session_version.py:84`，仅留存兼容）。
5. 前端 `linsight_workbench_title_generate` 回调里**直接** `startLinsight(versionId)`（`useLinsightManager.tsx:338`，POST `/workbench/start-execute`）——无 SOP 步骤，注释 `useLinsightManager.tsx:335` 明写 "no SOP generation step anymore"。
6. 后端 `start_execute`（`linsight.py:215`）：校验 owner + 非终态，`queue.put(data=linsight_session_version_id)`（`linsight.py:251`）传**裸 svid**。注意 wire 层并非裸字符串——`arpush`（`redis_conn.py:425`）先 `pickle.dumps` 再 RPUSH；消费端 `ablpop`（`redis_conn.py:392`）`pickle.loads` 还原回原始 `str`，故 Worker 在 Python 层确实拿到裸 str。**端点已无任何 SOP 写入逻辑**（随 SOP 残留代码删除），只做入队。
7. 同时 `ExecutionFlow.tsx:68` 通过 `useLinsightWebSocket(versionId)` 连 WS `/workbench/task-message-stream`。后端 WS 端点（`linsight.py:534`）只做 `MessageStreamHandle.connect()` 纯订阅推送，**不参与调度/入队**。

**链路二·澄清（ask_user / clarify）回填**

8. Worker 执行中触发 `interrupt()`（ask_user），astream 在 `__interrupt__` chunk 后自然结束，任务 park 为 `WAITING_FOR_USER_INPUT`。前端 WS 收到 `call_user_input` step，`ExecutionFlow` 选最新未完成项渲染 `ClarifyCard`。`PlanningRow`（由 `planning` 布尔门控 `{planning && <PlanningRow/>}`，`ExecutionFlow.tsx:161`）是"规划中呼吸点"，与 SOP 无关，**在用**。
9. 用户答完，`ClarifyCard.finishAndSubmit` 合并多问成一段文本 → `handleClarifySubmit`（`ExecutionFlow.tsx:112`）→ `sendInput(...)` POST `/workbench/user-input`。
10. 后端 `user_input`（`linsight.py:321`）的关键 **session-level 分支**：`session_level = linsight_execute_task_id == session_version_id`（`linsight.py:358`）。session-level（todo 尚未生成时的 ask_user，task_id 等于伪 session 任务、无 `LinsightExecuteTask` 行——注释 `linsight.py:353-357`）硬置 `already_completed=False`（`:361`）并**跳过 `set_user_input`**（否则 task 找不到会抛 500：not-found 的 `ValueError` 在 `state_message_manager.py:265`，经 except `:292` 包成 `:294` `ServerError.http_exception()`）；非 session-level 才进 `else` 分支查 `USER_INPUT_COMPLETED` 幂等（`:363-368`）并 `set_user_input`（`:371`）。
11. 若 `not already_completed`（`:380` 门控），`queue.put_head(encode_queue_item(svid, resume=True, ...))`（`linsight.py:385`）**LPUSH 头插**，让 park 任务插队优先恢复。Worker 取到 `resume=True` → `async_resume`。

**链路三·已完成会话再追一轮（continue / 多轮）**

12. 执行页底部 `TaskModeInput.onFollowUp`（`ExecutionFlow.tsx:235`）→ `continueConversation(versionId, question)`（`useLinsightManager.tsx:73`）：前端先把当前轮快照进 `history`、清空顶层字段开新轮，再 POST `/workbench/continue`。
13. 后端 `continue_conversation`（`linsight.py:264`）：要求会话 COMPLETED/FAILED 终态，**先翻回 IN_PROGRESS**（`:296-299`，否则 Worker 非终态守卫会丢弃），再 `queue.put(encode_queue_item(svid, continue_question=question))`（`:307`）尾插。Worker 取到 `continue_question != None` → `async_continue`（喂同一 thread 保留上下文）。

### 1.3 队列与 Worker 调度（`worker.py`，本轮未改动）

- **LinsightQueue = RPUSH/BLPOP FIFO + LPUSH 头插队**：`put`→`arpush`=RPUSH（pickle），`get_wait`→`ablpop`=BLPOP（unpickle），`put_head`→`alpush`=LPUSH（`alpush` 自身不 pickle，故 `put_head` 在 `worker.py:159` 手动 `pickle.dumps` 保持一致）。
- **`parse_queue_item`**（`worker.py:64-78`）：dict 直接用；裸 str 落 legacy 分支 `{session_version_id, resume:False, user_input:None, continue_question:None}`（`:78`）。`index`（`worker.py:173`）算排队位时跳过 resume 项，避免插队项虚增他人等待位。
- **多进程模型**：`start_schedule_center_process`（`worker.py:371`）起 `worker_num`（默认 4）个 `ScheduleCenterProcess`（daemon Process，`spawn` 启动），每进程独立 event loop + 独立 `asyncio.Semaphore(max_concurrency)`（默认 32）。
- **三分派**（`worker.py:299-310`，守卫顺序）：`continue_question is not None`→`async_continue`（`:304`）；`elif resume`→`async_resume`（`:307`）；`else`→`async_run`（`:310`）。派发前有 **pre-flight 非终态守卫** `_session_is_terminal`，终态/缺失则丢弃并立即释放槽（防 park 期间被终止的任务被陈旧 resume 复活）。
- **park 不占并发槽**：`task.add_done_callback(handle_task_result)`（`worker.py:316`）。`interrupt()` 让 astream 自然结束、协程 return，done_callback 的 `finally` 无条件 `semaphore.release()`（`worker.py:236`）。**park 瞬间即归还并发槽，漫长等待期不占槽**（注释 `worker.py:312-315`），长时间等用户输入不会饿死 Worker。

### 1.4 direct-answer fallback 与步骤持久化

- **direct-answer fallback**：astream 跑完、**未 park** 且 `_final_result` 仍为 None（planner 没产 TaskEnd，即没有 todo 状态迁移到终态）→ 走 `_handle_direct_answer_completion`。典型是问候/纯问答被 deepagents planner 直接作答、不产 todo。effect：用 `_last_assistant_text` 兜底答复并置 COMPLETED，避免前端卡"规划中"；若 todo 已生成却无产物，仍 `get_final_result_file` + `build_fallback_report_file` 兜底合成报告。
- **流式/孤儿步骤刷新不丢**：规划/收尾/direct-answer 这类路由到 `task_id=svid`（无独立 `LinsightExecuteTask` 行）的步骤，过去刷新即丢；现 `add_execution_task_step` 按 `call_id` upsert（thinking delta 累积成一条、tool start/end 合并成一帧）并补了一个 session-level 伪任务行承载它们，`get_execute_task_detail` 在其为空时再剔除——强化"刷新不丢"。

---

## 2. 主 agent 的上下文是怎么装配的

主 agent 真实看到的上下文有**两条通道**，只看 system_prompt 会严重漏判。

### 2.1 静态通道：system_prompt

`create_linsight_agent`（`agent_factory.py:81`）在 `create_deep_agent(...)`（`:156` 区）传入 `system_prompt=LINSIGHT_SYSTEM_PROMPT_ZH`（`agent_factory.py:37`，开篇即"你是深度研究任务智能体…"）——一段静态中文"拆解待办清单 + ask_user 澄清纪律"指令，**不含 SOP / 知识 / 文件**。这只是 deepagents 拼接的最外层：框架还会在其后追加 `BASE_AGENT_PROMPT`，各内置中间件（TodoList/Filesystem/Summarization）再注入各自工具行为段。真实任务上下文不在这条里。

### 2.2 动态通道：运行期首条 user message

`_build_agent_input`（`task_exec.py:801`）把首条 user message 的 content 用 `"\n".join(parts)` 拼成，`parts` 顺序：

1. **`history_summary`**（拼接 `task_exec.py:817-818`，调用点 `:716`）= `build_prior_conversation_summary(chat_id)`（`utils.py:411`）：按 chat_id 从统一会话流 `ChatMessage` 重建跨轮"用户/助手"配对，确定性 head+tail 截断（永远保留第一轮原始诉求 + 最近若干轮，`max_chars=8000`，省略中间轮加标记）。**这是 per-session Redis checkpointer 看不到的更早 daily/task 轮次前情**。
2. **`session_model.question`**（`task_exec.py:819-820`）。
3. **文件指针块（条件）**：`prepare_file_list`（`workbench_impl.py:534`）返回**零正文**的 `<uploaded_files>` 指针块（path/name/lines/images，offload-first），拼到 `\n# 可用文件\n{block}`（`task_exec.py:827`）。模型按需 `read_file` 取正文。
4. **可用知识库块（条件）**：`_resolve_knowledge_block`（`task_exec.py:861`）经 `_resolve_user_knowledge_bases`（`:835`）拉取**用户在日常选择器里精确勾选的那几个** org KB + 知识空间 id（`session_version.organization_knowledge_ids` + `knowledge_space_ids`，`linsight_session_version.py:72/75`），**不再用 `org/personal_knowledge_enabled` 两个布尔拉"该类型全部 KB"**（旧逻辑勾 1 个会喂 20+ 个；布尔列仅留存兼容）；经 `prepare_knowledge_list`（`workbench_impl.py:572`）渲成 `- 名称 (knowledge_id: {id})` 行，拼到 `\n# 可用知识库...`（`task_exec.py:828-831`）。**这是 `search_knowledge_base` 拿到真实 `knowledge_id` 的唯一来源**；且工具白名单 `_resolve_allowed_knowledge_ids`（`:874`）取**同一组 id**，"prompt advertise 的 id"与"工具实际放行的 id"严格一致（C4 隔离）。

> **SOP 注入分支已删除**：原先这里有第 3 项 `if session_model.sop: parts.append("# 执行规范(SOP)...")`，随 2026-06-17 SOP 残留代码清理**整段移除**，`_build_agent_input` 不再有 SOP 段（详见 §4.1）。

若 parts 全空则退化为 `session_model.question or ""`。

---

## 3. 工具与中间件拓扑

### 3.1 deepagents 默认装配 vs 毕昇调整

| 维度 | deepagents 框架默认 | 毕昇 `create_linsight_agent` |
|---|---|---|
| `write_todos`（TodoListMiddleware） | 默认装 | **保留**（规划核心） |
| 文件工具 read/write/edit/ls/grep（FilesystemMiddleware） | 默认装，挂 StateBackend | **保留但覆盖 backend** → 真 `WorkspaceBackend`（MinIO）。注：旧自研 local_file 工具集已退役，文件能力统一走框架中间件 |
| `task` 子代理委派（SubAgentMiddleware） | 默认装，且不传 `subagents=` 时自动注入 1 个 general-purpose 子代理 | **剥离**：`_ToolExclusionMiddleware(excluded={"task"})`（`agent_factory.py:140`）从模型可见工具集过滤掉 `task` |
| SummarizationMiddleware | 默认装 | **保留内置**（自研 `tool_buffer` 压缩退役，避免与内置重复触发 langchain "duplicate middleware" 断言） |
| Skills（SkillsMiddleware） | demo 真生效 | **整体 DISABLED**（运行时零注入，见 §4.2） |
| web_search / think_tool | 框架不强制，由应用层选择 | **不注入**（全仓 grep 零命中） |
| `ask_user`（HITL interrupt） | 框架无内置 ask-human 工具 | **新增硬注入**（`agent_factory.py:156` `tools=[*tools, ask_user]`） |

### 3.2 默认工具集真相

agent 最终工具集 = **用户日常勾选 tools** + **`ask_user`（恒硬注入）** + **`search_knowledge_base`（条件注入）**：

- **用户日常勾选 tools**：`_generate_tools`（`task_exec.py:551`）在 `session_model.tools` 为空时返回 `[]`，否则转调 `init_linsight_config_tools`（`workbench_impl.py:904`）。task 模式**不再用 per-app 灵思白名单**，而直接复用 DAILY chat 配置 / 用户日常勾选：`tool_ids = _extract_tool_ids(session_version.tools)`（`:925`）是真正绑定源，`config_tool_ids`（来自日常配置，`:934`）**仅供 code-interpreter 分支使用**。
- **`search_knowledge_base`（条件注入，非恒注入）**：`init_linsight_tools`（`tool/domain/services/tool.py:588`，工具组"知识库和知识空间检索" `:617`）注入 `SearchKnowledgeBase`（类在 `tool/domain/langchain/linsight_knowledge.py:21`），在 fresh/resume/continue 三条路径都 extend。两点关键变化（2026-06-17）：
  - **只检索知识库/知识空间**，已删除 `search_linsight_file`（milvus 文件语义检索）分支——上传文件改由 agent 直接 `read_file` 读工作区里的解析 markdown（`_init_file_directory` 已把解析 markdown 下载进 workspace），白名单也只剩 KB/space id（不含上传文件 id）。
  - **条件注入**：当白名单 `allowed_knowledge_ids` 为**空 set**（未选 KB 且无可检索目标）时 `init_linsight_tools` 直接 `return []`（`tool.py:608-609`），**不注入该工具**——否则模型会看到它并带缺失 `knowledge_id` 误调，报 "Field required"；`None`（back-compat）才保留工具且不设门控。
- **`ask_user`**（`agent_factory.py:156`）：调 langgraph `interrupt()` 实现 park-and-resume，**唯一恒硬注入**的内置工具。

**code_interpreter 非无条件注入**：需双条件——`need_upload and file_dir`（`workbench_impl.py:937`，有上传文件）**且** `bisheng_code_tool.id in config_tool_ids`（`workbench_impl.py:869`，日常配置勾了代码解释器）。

### 3.3 `task` 子代理为何被剥离

注释固化于 `agent_factory.py:129-136`：模型过度委派（单 run 100+ 子代理）且在子代理内调 `ask_user`，HITL interrupt 在子图里**冒泡不上来**，澄清触达不了用户、任务跑成 direct-answer fallback。剥离 `task` 强制所有工作（含 ask_user）回到主图，`interrupt()` 在主图才能正确 park。`_ToolExclusionMiddleware` 加在 SubAgentMiddleware 之后，在模型看到前过滤掉 `task` 工具（隐藏入口，不拆基础设施）。

> ⚠️ **勘误（2026-06-17，`0924be451`）**：禁用方式升级为**双保险**——新增 `_disable_subagent_delegation(model)`（`agent_factory.py:114` 调用 / `:169` 定义），用 deepagents **官方 harness-profile API** 在 profile 级关掉自动注入的 general-purpose 子代理；`_ToolExclusionMiddleware(excluded={"task"})`（`:144`）**仍保留**作辅。注释（`:176`）明示：单靠 `_ToolExclusionMiddleware` **不可靠**（模型仍会 over-delegate 生出调 0 个工具的 `ls`/`glob` "子代理"、并可能在子代理内调 `ask_user` 致 interrupt 不冒泡），故 profile 级禁用才是"唯一可靠"的关法。即由"中间件过滤模型可见工具"单层，改为"profile 级禁用（主）+ 中间件过滤（辅）"双层。

### 3.4 文件系统：WorkspaceBackend（offload-first）

`WorkspaceBackend(FilesystemBackend)`（`workspace_backend.py:123`），**MinIO 为唯一真理源**（key 前缀 `workspace/{svid}/`），local `file_dir` 是 write-through cache。`task_exec._create_agent`（`task_exec.py:560`，backend 实例化在 `:576`）显式注入真 backend，覆盖工厂默认的 `FakeWorkspaceBackend` 测试桩。write/edit/upload 先写 cache 再立即落 MinIO；read 走 `_materialize`（先 cache 后 MinIO 回填）；ls 以 MinIO 为权威。大文件不进窗口——`prepare_file_list` 只给指针，body 按需 `read_file`。

### 3.5 checkpointer 与防腐层

- **`PlainRedisCheckpointer`**（`checkpointer.py:59`）：纯标准 Redis 命令避开 RediSearch，thread_id 即 svid，跨进程 park/resume 用 MULTI/EXEC 原子写 + ZSET 时间索引，TTL 默认 7 天。`make_checkpointer()`（`:362`）三处注入（fresh/resume/continue）。这是 park/resume 能跨 Worker 进程定位 interrupt checkpoint 的前提。
- **`StreamEventMapper`**（`stream_event_mapper.py:111`）= 纯翻译器（硬规则不碰 Redis/MySQL）：把 `astream(stream_mode=["updates","messages","values"], subgraphs=True)` 原始 chunk 翻成 `BaseEvent` 家族（`ExecStep/TaskStart/TaskEnd/GenerateSubTask/NeedUserInput`），`__interrupt__`→`NeedUserInput`（`:198`），`write_todos` 快照三级 diff→`GenerateSubTask`/`TaskStart`/`TaskEnd`。
- **副作用层** `LinsightStateMessageManager` 把事件映射到 10 个冻结 `MessageEventType`，`push_message`→RPUSH 进事件队列；`MessageStreamHandle.connect`（`message_stream_handle.py:46`）循环 BLPOP 消费并 `send_json` 推 WebSocket。这是 Worker（生产）↔ WS 网关（消费）的跨进程解耦队列。

---

## 4. SOP / Skills 现状矩阵

### 4.1 SOP——已物理删除，仅余库表

2026-06-17 一连串 commit（移除 `/integrated-execute` + SOP-gen 级联、移除 workbench SOP/feedback 端点、删 `sop_manage.py` 整文件）把 SOP **执行侧代码全部物理删除**。合并后 `generate_sop` / `modify_sop` / `integrated_execute` / `_generate_sop_content` / `feedback_regenerate_sop_task` / `search_sop` 在生产代码均 **0 处定义**（`linsight.py`、`workbench_impl.py` 各净删数百行；`sop_manage.py` 不复存在）。

| 维度 | 标准 task-mode 链路结论 | 锚点 |
|---|---|---|
| 生成（主 agent 主动产 SOP） | ❌ 不生成，走 deepagents `write_todos` 现场规划 | `task_exec.py:426`（legacy generate_task precall removed 注释） |
| 注入（SOP 反哺主 agent） | ❌ 注入分支**已删除**（原 `if session_model.sop:` 整段移除） | `_build_agent_input`（`task_exec.py:801`）已无 SOP 段 |
| 编排（SOP 驱动任务拆解） | ❌ 编排改由 deepagents kernel（write_todos → StreamEventMapper → GenerateSubTask）承担 | `task_exec.py:390` `_execute_workflow` |
| 生成/反馈端点 | ❌ `/workbench/generate-sop`、`/integrated-execute`、workbench SOP/feedback 端点**均已删除** | 全仓零定义 |
| 库静态资产 | ✅ 仅余 `linsight_sop` / `linsight_sop_record` 库表 + `LinsightSOPDao` + 库 CRUD/评分/showcase 端点；执行链零触点 | `linsight_sop.py`、showcase 端点 `linsight.py:698` |

**结论：SOP 从旧文档的"架空（库静态资产 + 死分支 + 死端点）"进一步演进为"已删除"。** 现仅剩 `linsight_sop` 库表 + 一组库管理/案例 showcase 端点（add/update/list/record/sync/showcase），**运行时执行链对 SOP 彻底无触点**。`session_version.sop` 列虽保留（back-compat）但永不写入、永不读取。若未来要复用 SOP 库内容当 deepagents skill/system-prompt 喂料，需重新接线，且会卡在 Skills 因 workspace filesystem shadow bug 被禁用上——**SOP 复用 = Skills 复活，二者绑定**。

### 4.2 Skills（运行时零注入，DISABLED）

- `agent_factory.py:127 middlewares: list = []`，唯一 append 的是 `_ToolExclusionMiddleware`（剥离 `task`）。`TenantSkillsMiddleware` / `make_skills_middleware` 在生产代码**无任何活跃 import / 调用方**（仅自身定义 + 一条 DISABLED 注释 + test 引用）。
- 禁用根因（注释 `agent_factory.py:119-126`）：`TenantSkillsMiddleware` 自带 `FilesystemBackend`（SKILLS_ROOT, virtual_mode），加在 workspace FilesystemMiddleware 之后会 **shadow** agent 的 write_file/read_file，导致交付物落进 skills store、workspace 为空、产不出结果文档。
- `SkillService` / `SkillStore` 仍活跃，但只服务技能库管理端点（CRUD / from_github / set_status），**不参与 agent 执行链路**。前端 submit payload 虽带 `skills` 字段，但 submit schema 明确"does not consume this field yet"，属 forward-compatible 占位，运行时无效。

**结论：Skills 在标准 task-mode 运行时彻底零注入；只剩一套"可管理但不被 agent 消费"的库 + 管理端点。**

---

## 5. deepagents demo 的运行逻辑与上下文工程

> **可信度声明**：`[框架真值-已验证]` = 直读 `.venv/.../deepagents/`（v0.6.8）包源码、可在本仓复核；`[demo专属-未在本仓库复验]` = 据旧调研记录的 demo 仓库实现，demo 源码不在本仓库。关键核查：`ORCHESTRATOR_PROMPT` / `Silent Defaults` / `request_clarification` / `emit_research_card` / `research-agent` 在框架包内 **grep 全无匹配**——它们是 demo 在框架之上自写的应用层 prompt / 工具 / UI，不是框架默认能力。

### 5.1 整体运行逻辑

- **单进程单图**：demo 用 `create_deep_agent(...)` 装一张 LangGraph 图，agent 图与 HTTP server 同进程，规划+执行在同一次 `astream` 连续完成，无独立 Worker、无 Redis 队列、无两段式。`[demo专属-未在本仓库复验]` 框架侧佐证：`create_deep_agent` 末尾即 `create_agent(...).with_config({recursion_limit: 9999})` 返回可直接 invoke/astream 的编译图（`graph.py:840-862`），框架本身不含进程/队列基础设施。`[框架真值-已验证]`
- **SSE useStream 直连**：前端用 `useStream` 直接订阅 graph 原生 SSE 流，**无后端事件翻译层/防腐层**。`[demo专属-未在本仓库复验]`
- **interrupt + resume 同进程**：HITL 在进程内 thread 上靠 `interrupt()` 挂起，`useStream` 同进程 resume（`Command(resume=...)`），无毕昇的分布式 park-release / 释放 Worker 槽 / 跨进程 resume。`[demo专属-未在本仓库复验]`；`interrupt()` 是 LangGraph 原生机制 `[框架真值-已验证]`。

### 5.2 上下文工程要点

- **Prompt 工程**：`ORCHESTRATOR_PROMPT` 把 6 步流水线写死（Step0/Step1 互斥、Silent Defaults 五字段缺省表、最多 1 轮澄清），使规划跨 run 可复现。`[demo专属-未在本仓库复验]`，框架包内不存在。框架默认会把 `BASE_AGENT_PROMPT`（Understand→Act→Verify）拼在调用方 system_prompt 之后（`graph.py:69-92/832-838`），demo 的 6 步是叠加其上的应用层约束。`[框架真值-已验证]`
- **task 子代理并行委派 + 子上下文隔离（demo 核心）**：demo 把 `task` 并行委派当工作流核心，`subagents=[research-agent]` fan-out 并行调研、各子代理隔离上下文里深挖、主图只收综合后单条结果。`[demo专属-未在本仓库复验]`（`research-agent` 框架包内不存在）。框架真值底座 `[框架真值-已验证]`：`task` 调子代理时构造全新隔离 state，从父 state 剔除 `messages/todos/structured_response/...`（`subagents.py:240-264`），子代理 messages 重置为仅一条 `HumanMessage(description)`（`:538-540`）；跑完只把最后一条 AIMessage 文本包成单条 ToolMessage 回传父图（`:494-532`）——这就是子上下文隔离。即便不传 `subagents=`，框架也自动注入 1 个 general-purpose 子代理（`graph.py:687-747`）。
- **文件系统**：demo 文件全在 state 内虚拟 FS、随 checkpoint 持久化，不落 MinIO。`[demo专属-未在本仓库复验]`。框架默认 backend 就是 `StateBackend()`（`filesystem.py:734-735`），文件存于 state `files` 字段（DeltaChannel 增量持久化，`filesystem.py:307-310`）。框架也支持换真实/远程 backend——毕昇正是显式覆盖默认。`[框架真值-已验证]`
- **记忆/压缩**：demo 单 turn deep-research，直接吃框架内置 `SummarizationMiddleware` 默认阈值，无自研调参；单 turn 无跨轮记忆。`[demo专属-未在本仓库复验]`。主 agent 栈固定插入 `create_summarization_middleware`（`graph.py:776-781`）`[框架真值-已验证]`——这点毕昇与 demo 同源同默认。
- **HITL**：demo 有两类——询问型 active（`request_clarification` Step0 规划前澄清，框架包内不存在，demo 自写）+ 审批型 dormant（`interrupt_on` 工具执行前审批，demo 休眠未用）。`[demo专属-未在本仓库复验]`。`interrupt_on` 是框架一等参数，接到 `HumanInTheLoopMiddleware`（`graph.py:808-813`）`[框架真值-已验证]`。
- **Skills 真生效（progressive disclosure）**：demo 的 SkillsMiddleware 真注入，每次 model call 把 skills 渲染进 system message（仅注入 frontmatter 的 name/description，正文靠模型自己 read_file），受架构不变量测试守护。`[demo专属-未在本仓库复验]`。框架代码实证 `skills.py:883-949` `[框架真值-已验证]`。这与毕昇"Skills 整体 DISABLED"形成对比。
- **generative UI**：demo 用 `emit_research_card` 推 title/summary 卡片到前端。`[demo专属-未在本仓库复验]`（框架包内不存在）；框架允许自定义 `state_schema`（须 `DeepAgentState` 子类）`[框架真值-已验证]`。

### 5.3 一句话基线

deepagents demo = **框架默认形态的最小可运行参考**：单进程单图、useStream SSE 直连、同进程 interrupt/resume；上下文工程上**采用框架默认**（state 内虚拟 FS、内置 Summarization、task 子上下文隔离、Skills progressive disclosure 真生效、interrupt_on 审批现成但 dormant），并叠加应用层 prompt/工具（6 步 ORCHESTRATOR_PROMPT + Silent Defaults + request_clarification 澄清 + research-agent 并行委派 + emit_research_card UI）。其最强项是**上下文纯净度与经济性**，代价是不解决排队/并发/断线/规划可审。

---

## 6. 差异对比（context engineering，从效果角度）

### 6.1 主对照表

| 维度 | deepagents demo | 毕昇灵思任务模式 | 效果差异 |
|---|---|---|---|
| 执行框架 | 单进程单图，规划+执行一次 astream | 分布式多进程 Worker + Redis 队列 + 两段式（async_run/resume/continue） | 毕昇解决排队/并发/断线/跨进程恢复 |
| Prompt 工程 | 6 步 ORCHESTRATOR_PROMPT 写死（应用层）`[demo专属]` | 静态 `LINSIGHT_SYSTEM_PROMPT_ZH` + 运行期动态首条 user message（前情/问题/文件指针/知识库 id） | demo 规划确定性强；毕昇上下文按会话动态装配 |
| 工具供给 | task 委派 + demo 自定义 web 工具 `[demo专属]` | 用户日常勾选 + ask_user（恒） + search_knowledge_base（条件，仅 KB/space）；无 web_search/think_tool | 毕昇按租户/用户资源约束，无内置搜索 |
| 子代理 / 子上下文隔离 | `task` fan-out 并行 + 隔离 state（核心）| `task` **剥离**，全工作回主图单上下文 | 毕昇牺牲并行/隔离换 HITL 在主图正确 park |
| HITL | request_clarification（询问型 active）+ interrupt_on（审批型 dormant）`[demo专属]` | `ask_user`→`interrupt()` 主图 park + 跨进程 resume（`Command(resume)` 同 thread_id） | 毕昇 HITL 工业化（park 不占槽、LPUSH 头插优先恢复） |
| 文件系统 / offload | state 内虚拟 FS 随 checkpoint（框架默认） | `WorkspaceBackend`（MinIO 真理源）+ offload-first 指针块 | 毕昇交付物落对 workspace，每写打 MinIO |
| 记忆 / 压缩 | 内置 Summarization（默认阈值），单 turn 无跨轮 | 内置 Summarization + `build_prior_conversation_summary` 跨轮截断前情 | 毕昇额外有跨轮记忆 |
| 流式 / 防腐 | useStream 直订 graph SSE，无翻译层 | astream→StreamEventMapper→Redis 事件队列→WebSocket 三跳 | 毕昇防腐层隔离模型 chunk 与前端协议，可落库重放 |
| Skills | progressive disclosure 真生效 | 整体 DISABLED（运行时零注入） | 毕昇牺牲热插拔领域知识换 workspace 不被 shadow |

### 6.2 分维度要点

- **prompt 工程**：demo 把规划逻辑前置进静态 prompt（跨 run 可复现）；毕昇把规划交给 deepagents kernel，但用**运行期动态 user message** 注入会话级上下文（跨轮前情 + 文件指针 + 真实 knowledge_id），上下文随每次提交装配而非写死。
- **工具供给**：demo 倾向丰富内置/自定义工具；毕昇收口到"用户已有权限的日常勾选 + 知识检索（仅 KB/知识空间）+ HITL"，刻意不给 web_search/think_tool；连知识检索工具也改成"无可检索目标就不注入"，把工具表面积压到最小。
- **subagent 与子上下文隔离**：这是最尖锐对立。demo 靠 `task` 隔离子上下文换纯净度与并行；毕昇为保 `ask_user` interrupt 一定在主图 park，**主动剥离 `task`**，放弃并行与子上下文隔离。
- **HITL**：demo 的 active HITL 是规划前一次性澄清（`request_clarification`）；毕昇是执行中任意点可 park 的 `ask_user`，且 park 后通过 LPUSH 头插 + 跨进程 resume 工业化恢复，park 期间不占并发槽。
- **文件系统与 offload**：demo 文件随 checkpoint（park/resume 无损但撑大 checkpoint）；毕昇 offload-first——大文件不进窗口、只给 `<uploaded_files>` 指针，正文按需 `read_file`，交付物落 MinIO 真理源。
- **记忆与压缩**：turn 内压缩两边同源（内置 SummarizationMiddleware）；跨轮上下文是毕昇独有（确定性 head+tail 截断回顾）。
- **流式与防腐**：demo 前端直订 graph SSE（少一跳但耦合模型 chunk 格式）；毕昇插 StreamEventMapper 防腐层，把模型 chunk 翻成 10 个冻结事件类型再经 Redis 队列 → WebSocket，可落库、可断线重连、前端协议与模型解耦。
- **执行框架**：demo 单进程单图（最小部署）；毕昇分布式多进程 + 信号量并发控制 + Redis checkpointer，把"一个会话的规划→执行→park→resume→多轮 continue"做成可在 Worker 集群上调度的工业链路。

---

## 7. 效果影响与取舍："削能力换正确性"

毕昇相对 deepagents demo 的几处"减法"都是**用框架能力换交付正确性/工程稳定性**：

- **剥离 `task` 子代理**：牺牲并行 fan-out 与子上下文隔离（纯净度/经济性），换 `ask_user` 的 `interrupt()` 一定在主图 park 稳定触达用户——否则子图内 interrupt 冒泡不上来，澄清丢失、任务跑成 direct-answer fallback。
- **禁用 Skills**：牺牲热插拔领域知识（progressive disclosure），换交付物正确落进 workspace——否则 skills 自带的 FilesystemBackend 会 shadow agent 的 write_file/read_file，产物落进 skills store、workspace 为空、产不出结果文档。
- **删除 SOP 子系统**：牺牲"历史最佳实践前置编排"，换链路简单与一致性——SOP 编排已被 deepagents `write_todos` 现场规划完全取代，残留代码反成维护负担，故 2026-06-17 整体物理删除，仅留库表待未来以 skill 形式重新接回。
- **知识检索收窄 + 条件注入**：牺牲"文件也能语义检索"与"工具恒在"，换正确性——文件改 `read_file` 直读避免双路径歧义，无目标就不注入避免模型带空 id 误调。
- **offload-first（WorkspaceBackend + 指针块）**：牺牲"每写都打 MinIO"的 I/O 成本与"文件不随 checkpoint"，换上下文窗口不被文件正文撑爆、大文件按需读、交付物有持久真理源。
- **防腐层 + 分布式队列**：牺牲单进程的简洁与"少一跳"，换排队/并发/断线/跨进程恢复/可审计落库的工业能力。

净效果：灵思任务模式不是"deepagents 的功能超集"，而是**为企业级交付正确性做了定向取舍的框架特化**——demo 强在上下文纯净度与规划确定性，灵思强在 HITL 工业化、交付物落地与分布式可调度。

---

## 8. 附录

### 8.1 关键代码锚点表（CURRENT，HEAD=`77beaa6f0`）

| 主题 | 锚点（file:line） |
|---|---|
| 前端入口守卫/渲染 | `components/Sop/index.tsx:45`（守卫）/ `:55`（TaskModeChatInput 渲染） |
| 前端 submit SSE 入口 | `hooks/useLinsightManager.tsx:257`；convertTools `:393` |
| 前端 title_generate→startLinsight（无 SOP 步骤） | `useLinsightManager.tsx:335-338` |
| 前端 generate-sop 已移除墓碑注释 | `useLinsightManager.tsx:373-374` |
| 前端 ExecutionFlow（WS/澄清/续问） | `ExecutionFlow.tsx:68`（useLinsightWebSocket）/ `:112`（handleClarifySubmit）/ `:161`（PlanningRow）/ `:221`（TaskModeInput）/ `:235`（onFollowUp） |
| 后端 submit 端点 | `linsight.py:158` |
| sop 字段默认 None（仅留存兼容） | `linsight_session_version.py:84` |
| 精确 KB id 列 | `linsight_session_version.py:72`（organization_knowledge_ids）/ `:75`（knowledge_space_ids） |
| start-execute 入队裸 svid（已无 SOP 写入） | `linsight.py:215`（端点）/ `:251`（queue.put） |
| user-input session-level 分支 | `linsight.py:321`（端点）/ `:353-357`（伪任务注释）/ `:358`（session_level）/ `:361`（already_completed）/ `:363-368`（幂等）/ `:371`（set_user_input）/ `:380,385`（put_head 门控/入队） |
| set_user_input 抛 500 | `state_message_manager.py:265`（not-found ValueError）/ `:294`（包成 ServerError） |
| continue 端点 | `linsight.py:264`（端点）/ `:296-299`（翻 IN_PROGRESS）/ `:307`（queue.put） |
| WS 订阅端点 | `linsight.py:534` |
| SOP showcase 端点（库静态资产唯一残存执行入口） | `linsight.py:698` |
| 队列 RPUSH/BLPOP/LPUSH | `redis_conn.py:425/392/378` |
| Worker 三分派 / park 归还槽 | `worker.py:299-310`；done_callback `:316`；release `:236` |
| 执行器 async_run / _execute_workflow | `task_exec.py:130` / `:390` |
| generate_task 移除（write_todos 现场规划） | `task_exec.py:426` |
| _build_agent_input（上下文装配，无 SOP 段） | `task_exec.py:801`；history_summary 拼接 `:817-818`（调用点 `:716`）；question `:819-820`；文件块 `:827`；知识库块 `:828-831` |
| 精确 KB 解析 / 白名单 | `task_exec.py:835`（_resolve_user_knowledge_bases）/ `:861`（_resolve_knowledge_block）/ `:874`（_resolve_allowed_knowledge_ids） |
| _generate_tools | `task_exec.py:551` |
| _create_agent 注入真 WorkspaceBackend | `task_exec.py:560`（def）/ `:576`（backend 注入） |
| create_linsight_agent / tools=[*tools, ask_user] | `agent_factory.py:81`（def）/ `:156`（create_deep_agent tools=） |
| system_prompt / ask_user 工具体 | `agent_factory.py:37` / `:51` |
| Skills DISABLED 注释 / middlewares=[] / task 剥离 | `agent_factory.py:119-126` / `:127` / `:140` |
| 工具装配 init_linsight_config_tools | `workbench_impl.py:904`；tool_ids 绑定源 `:925`；config_tool_ids `:934` |
| code_interpreter 双条件 | `workbench_impl.py:937`（need_upload and file_dir）+ `:869`（id in config_tool_ids） |
| search_knowledge_base 注入（条件 + KB/space） | `tool/domain/services/tool.py:588`（init）/ `:608-609`（空白名单 return []）/ `:617`（工具组）；类 `tool/domain/langchain/linsight_knowledge.py:21` |
| prepare_file_list / prepare_knowledge_list | `workbench_impl.py:534` / `:572` |
| WorkspaceBackend | `workspace_backend.py:123` |
| PlainRedisCheckpointer / make_checkpointer | `checkpointer.py:59` / `:362` |
| StreamEventMapper（interrupt→NeedUserInput） | `stream_event_mapper.py:111` / `:198` |
| MessageStreamHandle.connect | `message_stream_handle.py:46` |

### 8.2 legacy 模块 liveness 矩阵（`bisheng_langchain/linsight/`）

> SOP 子系统 2026-06-17 物理删除后，`workbench_impl` 已不再 import `bisheng_langchain.linsight`（`LinsightAgent` / `ExecConfig` 引用全消失）。整条 `LinsightAgent → manage → react_task` 链**失去最后一条活跃 import 边，彻底死亡**。现仅余 `event.py` 数据类 + `const.TaskStatus` 作为防腐层基石仍在用。

| 模块/符号 | 状态 | 证据 |
|---|---|---|
| `event.py`（BaseEvent/ExecStep/GenerateSubTask/NeedUserInput/TaskStart/TaskEnd） | **在用（核心）** | `task_exec.py:42` / `stream_event_mapper.py:32` / `state_message_manager.py:19` / `linsight_schema.py:3` 防腐层基石 |
| `const.TaskStatus` | **在用** | `task_exec.py:41` |
| `const.ExecConfig` | **死**（SOP 删除后 workbench_impl 不再 import） | 全仓无活跃 import |
| `agent.py LinsightAgent`（含 generate_sop/feedback_sop/ainvoke/continue_task/generate_task 全部方法） | **死** | 原唯一活跃入口（workbench_impl SOP 旁路）已随 SOP 删除一并移除，仅 agent_test / POC 脚本引用 |
| `manage.py TaskManage` | **死** | 仅 `agent.py:14` 顶层 import；执行入口运行期不触达 |
| `task.py Task / BaseTask` | **死** | 仅 manage/react_task 内部互引 |
| `react_task.py ReactTask` / `react_prompt.py` | **死** | 承载它的传递性 import 边（经 LinsightAgent）随 SOP 删除断裂，无任何活跃调用方 |
| `prompt.py` SOP 三件套（SopPrompt/FeedBackSopPrompt/GenerateTaskPrompt） | **死** | 原仅 SOP 旁路用，SOP 删除后无活跃引用 |
| `utils.format_size` | **在用（散点）** | `local_file.py:9`（与 SOP 链无关） |

> 关键修正：上一版文档（基于 SOP 删除前的 HEAD）把 `LinsightAgent`/`ExecConfig`/`prompt.py` 标为"SOP 旁路在用"。SOP 子系统物理删除后，这些已全部转为 **死代码**——`bisheng_langchain/linsight/` 现在只有 `event.py` + `const.TaskStatus` + `utils.format_size` 三处还有活跃引用。

### 8.3 相比旧两篇调研文档纠正的关键误判

- **system_prompt ≠ 主 agent 全部上下文**：真实任务上下文在运行期首条 user message（history_summary + question + 文件指针 + 知识库 id），只读 `LINSIGHT_SYSTEM_PROMPT_ZH` 会严重漏判。
- **SOP 已物理删除（不止"架空"）**：submit→start-execute 全程无 SOP 生成；`_build_agent_input` 的 SOP 注入分支、`generate_sop`/`search_sop`/`sop_manage.py`、generate-sop/integrated-execute 端点**全部已删**，仅余 `linsight_sop` 库表 + 管理/showcase 端点作静态资产，执行链零触点。
- **知识检索收窄 + 精确注入 + 条件注入**：`search_knowledge_base` 现**只检索知识库/知识空间**（删了文件检索，文件改 `read_file` 直读）；KB 注入改成**用户精确勾选的那几个 id**（不再按类型全量）；白名单为空时**不注入该工具**——故"唯一恒硬注入"实为 `ask_user`，`search_knowledge_base` 是条件注入。
- **Skills 运行时零注入**：`agent_factory.py:127 middlewares=[]` 仅含剥离 task 的中间件，`TenantSkillsMiddleware` 生产代码零 import，因 workspace filesystem shadow bug 整体 DISABLED——旧文档若称 Skills 在运行链路生效为误。
- **`task` 子代理已剥离**：`_ToolExclusionMiddleware(excluded={"task"})` 从模型可见工具集过滤掉 `task`，毕昇放弃了 demo 引以为核心的子代理并行委派与子上下文隔离。
- **默认无 web_search / think_tool**：全仓 grep 零命中；旧自研 local_file 工具集也已退役（文件能力统一走 deepagents FilesystemMiddleware）。
- **自研 tool_buffer 压缩已退役**：改用 deepagents 内置 SummarizationMiddleware（避免 langchain "duplicate middleware" 断言），这点毕昇与 demo 同源同默认。

---

> **维护提示**：本文锚点基于 HEAD=`77beaa6f0`。task-mode 子系统近期改动频繁（2026-06-17 当天即多次重构），若 `task_exec.py` / `linsight.py` / `workbench_impl.py` 再有提交，行号会整体漂移——**以函数名/符号定位为准，行号为辅**。判断任何逻辑"是否在用"务必 grep 调用方 + 追条件守卫，勿据旧行号或历史叙述直接采信。
