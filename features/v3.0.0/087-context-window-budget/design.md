# Design: 任务模式按模型上下文长度控制上下文

> **本文档定位 — 现状快照（Why this How）**
>
> - `spec.md` 回答做什么；本文回答为什么这么实现；`tasks.md` 是流水账。
> - 实现变化时覆盖更新本文；推翻已确认的决策要先与用户重新确认。
> - 问题背景、现状盘点、采访决策 D1–D10 见 [plan.md](./plan.md)，本文不重复。

**关联**: [spec.md](./spec.md) · [tasks.md](./tasks.md) · [plan.md](./plan.md)
**版本**: v3.0.0
**最后更新**: 2026-10-21（P0、P1、P2 已实现；P0、P1 的端到端验证待客户现场）

---

## 1. 目标与非目标

- **目标**：任务模式在每次运行开始时确定所用模型的上下文长度，把它交给 deepagents，使压缩在超窗之前触发；超窗和压缩失败时，任务以可识别的原因结束，而不是以"未知错误"结束。
- **非目标**：不改 deepagents 源码；不改拿不到上下文长度时的行为；不覆盖日常模式、助手、工作流；不在模型配置页面加字段。完整清单见 spec.md 范围边界。

---

## 2. 关键约束

- 遵循 `docs/constitution.md` C1–C8。本功能涉及的条款：C1（linsight 调 llm 模块的 domain service，不跨 api 层）、C5（新增错误码 11075、11076，见 §6.1）、C8（上下文长度缓存放 Redis，不放进程内存或本地文件）。
- **deepagents 0.6.12 只开放了一个入口。** `create_deep_agent` 没有压缩、计数、转存相关的参数。框架读取的唯一外部信息是模型实例的 `profile["max_input_tokens"]`（`deepagents/middleware/summarization.py:261`）。P0 只用这个入口；P1 要替换框架部件，必须先做技术验证（决策 7）。
- **中间件顺序固定。** deepagents 主图的中间件栈是 `[TodoList, (Skills，仅当 create_deep_agent 收到 skills 参数), Filesystem, SubAgent, Summarization, PatchToolCalls, *BiSheng 中间件]`；linsight 通过 `middleware=` 自己挂 SkillsMiddleware，所以它也在 BiSheng 中间件之列（`deepagents/graph.py:773-812`），子图同理（`graph.py:643-654`）。列表靠前的是外层，所以 BiSheng 的 resilience 中间件在压缩中间件的**内层**，先于它看到模型异常。
- **多节点部署。** API 进程（保存模型配置）和任务执行进程（linsight worker）可能在不同机器上。上下文长度缓存及其失效必须经过 Redis。
- **服务商接口读取发生在任务启动路径上。** 每个模型每小时最多读取一次，单次超时 3 秒；读取失败不能阻塞任务。

---

## 3. 方案对比与选定

### 决策 1：怎样把上下文长度交给 deepagents

- **备选**：
  - A. 在模型实例上设置 `profile = {"max_input_tokens": 可用输入}` — 框架公开机制，主图和子图共用同一个模型实例，一处设置两处生效；只能控制压缩阈值（85%）和保留比例（10%）。
  - B. P0 就替换框架的压缩中间件 — 能控制所有参数，但要先完成决策 7 的技术验证，拖慢 P0。
- **选定**：A（P0）；B 留给 P1。
- **原因**：A 把压缩阈值从固定 170K 改成 0.85 × 可用输入，框架读到 profile 后的默认比例正好是 plan 推导的值，P0 不需要额外参数。
- **P0 的局限（必须知道）**：框架判断"到没到阈值"有两条路，满足任一条就压缩（`langchain/agents/middleware/summarization.py:583`）：
  1. **用量路径**：最近一条模型回复的 `usage.total_tokens` 达到阈值。这个数是服务商实测的，准确，但不包含这条回复之后新进来的消息（主要是刚返回的工具结果）。
  2. **估算路径**：deepagents 用 `count_tokens_approximately` 按 4 个字符 1 个 token 估算全部消息（`deepagents/middleware/summarization.py:527`、`:1016`），中文会被少算 2 倍以上。

  所以 P0 下，"上一次请求的实测用量 + 一大段中文工具结果"可能在估算上没到阈值、实际已经超窗。这种情况由 AC-13 的超窗后压缩重试兜住，任务不会因此失败，但会多一次被拒的请求。准确的提前判断要等 P1 的计数（决策 10、AC-21）。§7 的手动验证据此区分"提前压缩"和"超窗后压缩"两种日志。
- **备选 C（被否）**：P0 把 profile 设得比可用输入更小（例如乘 0.6），以抵消中文少算。被否原因：它同时把保留量和转存判断也按比例缩小，对英文内容过度压缩，而且这个系数没有依据。
- **何时该重新考虑**：deepagents 升级后改了 `compute_summarization_defaults` 的比例，或不再读取 `profile`。

### 决策 2：profile 里放可用输入，不放上下文长度

- **选定**：`profile["max_input_tokens"]` 设为 spec 术语"可用输入"。
- **原因**：框架用这个值乘以比例算阈值，把它当作"输入上限"使用。如果放上下文长度，配置了最大输出时，阈值会把输出空间也算进输入。
- **不设置 profile 的情况**：拿不到上下文长度时完全不设置，框架回到 170K 默认值（spec AC-08）。不能设成 170000 之类的占位值，因为那样会让框架改用比例模式，保留量从"6 条消息"变成"占位值的 10%"，行为就变了。
- **备选（被否）**：放上下文长度本身。被否原因见上。
- **何时该重新考虑**：deepagents 的 profile 增加单独的输出字段并据此扣除。

### 决策 3：上下文长度的来源与读取方式

- **来源优先级**：高级配置 `context_window` → Ollama 的 `max_tokens`（即 `num_ctx`）→ 服务商接口 → 未知。
- **读取方式**：
  - A. 每种服务商按自己的接口单独实现，地址和密钥取自 BishengLLM 已经算好的客户端参数（`BishengLLM._get_llm_params` 的结果）。
  - B. 直接读 `server_info.config`，每种服务商重新拼一遍地址和密钥。
- **选定**：A。
- **原因**：客户端参数已经处理过各服务商的字段别名、去掉了结尾斜杠、合并了代理设置。方案 B 要把这些逻辑再写一遍，两份逻辑以后会不一致。
- **各服务商的接口和字段**：见 plan.md §3.1 调研表。实现时以"读取器"为单位，每个读取器声明自己适用的服务商类型，返回 `(数值, 数值种类, 来源)`。数值种类分两种：总长度（输入加输出）、仅输入上限（anthropic 的 `max_input_tokens`）。
- **何时该重新考虑**：服务商把上下文长度加进对话接口的响应，或 BiSheng 新增"上下文长度"表单字段（届时它成为第一来源）。

### 决策 4：缓存放 Redis，保存配置时主动清除

- **备选**：A. 进程内 TTL 缓存；B. Redis；C. 写进模型配置表。
- **选定**：B。键为 `linsight:context_window:<model_id>`。读取成功时缓存 1 小时，读取失败时缓存一个"失败"标记 5 分钟。清除时机：凡是调用 `invalidate_llm_info_cache` 表示"模型配置变了"的异步入口，都同时删除对应的键。目前是 `update_llm_server`（`llm/domain/services/llm.py:1066`）和 `verify_model_status`（`:1102`）。`invalidate_llm_info_cache` 本身是同步函数、只清进程内缓存，不在它内部发 Redis 请求。删除模型时不清除，键在 1 小时内自然过期，且模型已不存在、不会再被读取。
- **原因**：A 违反 C8，API 进程清不掉 worker 进程的缓存；C 已在采访中否决（D2），部署变化后要人工重新保存才能更新。
- **防止旧值写回**：保存配置只清了 API 进程的 `LLM_CACHE`，任务执行进程最多还会用旧配置 60 秒；这期间它会把按旧配置读到的结果重新写进 Redis，并保留 1 小时。所以缓存值带一个 `fingerprint`（服务商类型、base URL、模型名的哈希），读取时与当前配置不一致就当作未命中、重新读取。
- **日志不带密钥**：`ModelSnapshot` 的 `client_params`、`model_config` 含 API key，两个字段设为不进 repr。loguru 的文件日志默认开启 `diagnose`，打印 traceback 时会输出局部变量。读取器里的请求头也含密钥，所以 `probe_context_window` 对预期之外的异常只记录异常类型，不打印 traceback。
- **何时该重新考虑**：出现需要"立刻"反映部署变化的现场需求时，可在管理端加"重新读取"操作，而不是缩短 TTL。
- **注意**：手动来源（高级配置、Ollama 字段）不进缓存，每次从模型配置读取。模型配置本身经过 `LLM_CACHE`（进程内 60 秒），所以保存配置后最多 60 秒生效。这一点满足 spec AC-06 的"下一次任务"要求，因为保存时同时清了 `LLM_CACHE`。

### 决策 5：在 BishengLLM 里识别超窗错误

- **备选**：
  - A. 在 `BishengLLM` 的四个调用入口（`_generate`、`_agenerate`、`_stream`、`_astream`）里识别服务商的超窗错误，改抛 `ContextOverflowError` 的子类。
  - B. 在 resilience 中间件里识别。
- **选定**：A，并且识别发生在被装饰函数的内部。
- **原因**：deepagents 的压缩中间件只认 `ContextOverflowError` 这个类型，而且它在 resilience 的外层（§2）。只有在模型调用这一层就换成正确的类型，外层才能接住。识别放在被装饰函数内部，是为了让 `wrapper_bisheng_model_limit_check_async` 看到的已经是新类型（见决策 6）。
- **识别规则**：按报错文本匹配，规则集中在一张表里，每条规则配一个单元测试，测试里用真实报错原文。初始规则：

  | 来源 | 报错原文特征 |
  |---|---|
  | vLLM（旧版）、DeepSeek | `maximum context length is` |
  | vLLM（新版） | `is longer than the maximum model length` |
  | OpenAI | `context_length_exceeded`（langchain-openai 已识别，这里兜底） |
  | Anthropic | `prompt is too long` |
  | SGLang | `exceeds the maximum allowed length` |
  | llama.cpp | `exceeds the available context size` |

- **保持原异常的类型与属性**：`BishengLLM` 是全平台共用的，日常模式、助手、工作流都经过它。改抛的异常必须仍然是原 SDK 异常的实例，并保留 `body`、`status_code`、`response`，否则按 SDK 类型捕获的代码和 `_provider_error_reason`（`llm/domain/utils.py:508`，从 `exc.body` 取服务商原文）都会受影响。做法：openai SDK 的错误改抛 langchain-openai 已有的 `OpenAIContextOverflowError(openai.BadRequestError, ContextOverflowError)`，anthropic 的改抛 langchain-anthropic 的 `AnthropicContextOverflowError`，用原异常的 `message`、`response`、`body` 构造；其他 SDK 的错误改抛 BiSheng 的 `LLMContextOverflowError(ContextOverflowError)`，并复制 `body`、`status_code`。三者都带 `reported_input_tokens` 属性，`__cause__` 指向原异常。下文统称"超窗异常"，判断一律用 `isinstance(exc, ContextOverflowError)`。
- **对任务模式以外的影响**（spec 只覆盖任务模式，以下是共用 `BishengLLM` 带来的附带变化）：
  1. 日常模式的错误分类（`workstation/domain/services/chat_service.py:2377` 调用 `label_error`）会得到 `context_overflow`，前端共用 `ChatErrorCard`。因此新文案必须对两种模式都成立，不能写"请拆分任务"这类只适用于任务模式的话（决策 8）。
  2. 所有场景下超窗都不再把模型标为异常（决策 6）。
  3. 日常模式、助手、工作流里没有使用 `SummarizationMiddleware`（已 grep 确认，只有 linsight 使用 deepagents），所以不会因为异常类型变化而触发新的压缩行为。
- **输出预留本身超过上下文长度不算超窗**：vLLM 对"输入加 `max_tokens` 超过上下文长度"和"`max_tokens` 本身就超过上下文长度"用的是同一句 "maximum context length is N"。前者是带 `max_tokens` 的模型最常见的超窗（输入先越过 `N − max_tokens`），压缩历史能解决，按超窗处理；后者是模型配置错误，压缩解决不了，仍按普通 400 处理并把模型标为异常（决策 6）。判断方式：从报错中解析出输出预留（新版 `is too large: X`，旧版 `C in the completion`），只有它不小于上下文长度 N 时才排除。曾经按"messages 部分小于 N 就排除"实现，把前一种常见超窗也排除掉了，第二轮代码审查发现后改为现在的判据。
- **输入 token 数的提取（AC-15）**：识别规则之外另有一张提取正则表（`_INPUT_TOKEN_PATTERNS`），例如 vLLM 的 `your prompt contains at least (\d+) input tokens` 或 `\(parameter=input_tokens, value=(\d+)\)`。提取结果存在超窗异常的 `reported_input_tokens` 属性，提取不到时为 `None`，日志记为 `unknown`。记录日志的位置：主图失败时由 `task_exec._handle_task_failure` 记录；子任务超窗时由决策 9 的中间件记录。
- **流式路径**：任务模式用 `astream` 驱动，`BishengLLM.streaming` 默认开启，实际走 `_astream`。超窗在请求开始时就被拒绝，异常在第一次迭代时抛出，所以在 `_astream` 里包一层识别即可，不会出现"已经输出一半再超窗"的情况。
- **何时该重新考虑**：langchain 各 partner 包自己识别了这些文本，这张表就可以缩减。

### 决策 6：超窗不把模型状态标为异常

- **现状**：`llm/domain/utils.py` 的四个装饰器（`wrapper_bisheng_model_limit_check`、`_async`、`wrapper_bisheng_model_generator`、`_async`）都在任何异常时把模型状态写成 ERROR，模型管理列表会把这个模型显示为异常。任务模式实际走的是 `wrapper_bisheng_model_generator_async`（流式）。
- **选定**：四个装饰器都对 `ContextOverflowError` 跳过状态写入，遥测仍然记为失败。
- **备选（被否）**：按 HTTP 状态码区分，400 一律不标异常。被否原因：鉴权、参数错误也是 400，这些确实是配置问题，应当标异常。
- **原因**：超窗是这一次请求的内容太长，不是模型服务坏了。如果标为异常，管理员会去排查一个正常的模型。
- **何时该重新考虑**：模型状态改为由独立的探测任务维护，不再由业务调用写入。

### 决策 7：P1 接管框架压缩部件的方式（D7，T019 已验证）

- **做法**：
  1. 按模型的 provider（`deepagents._models.get_model_provider`，即 `_get_ls_params()["ls_provider"]`）注册一个 harness profile：`excluded_middleware={"SummarizationMiddleware"}`，`extra_middleware=_summarizer_guard`。每个 provider 只注册一次。
  2. `create_linsight_agent` 把 `BishengSummarizationMiddleware` 放在主图 `middleware=` 列表和研究员子图 `middleware` 列表的**第一位**，每个图一个实例。
  3. `create_deep_agent` 在 `bisheng_summarization(model)` 块内调用。块内设置一个 ContextVar；`_summarizer_guard` 不添加任何中间件，只检查这个 ContextVar，在块外组装时抛 `RuntimeError`（坑 18）。
- **验证结果**：框架自带部件的 `name` 返回公开别名 `SummarizationMiddleware`，子类返回自己的类名，所以 BiSheng 子类不会被同一条排除规则移除（`deepagents/middleware/summarization.py:499-515`）。主图和研究员子图都只有 BiSheng 实例在工作，框架自带部件一次也没有被调用（`test_context_summarization.py`）。
- **为什么放在列表第一位，而不是用 `extra_middleware` 工厂注入**：T019 的验证脚本最初用工厂注入，但 `extra_middleware` 追加在调用方中间件之后，压缩部件因此位于 resilience 的内层。代码审查发现这样会让 resilience 的每次重试（transient、截断 nudge、incomplete-stream）都重新执行一次压缩：多调一次摘要模型，并把同一段历史再追加到 `/conversation_history/`。放在调用方列表第一位，它就紧接在框架的 PatchToolCalls 之后、resilience 之外，和框架自带部件原来的位置一致：resilience 的重试不会重复压缩；resilience 按 FAIL_FAST 抛出的超窗异常由它接住、压缩后重试。
- **ContextVar 的并发安全**：`create_deep_agent` 的组装是同步代码，期间不会切换到其他 asyncio 任务；ContextVar 的值也按任务隔离。
- **拿不到上下文长度时**：BiSheng 子类的参数与框架默认完全一致（`compute_summarization_defaults`、`count_tokens_approximately`、`trim_tokens_to_summarize=None`、不启用用量基数），满足 AC-08。摘要失败的重试与报错（AC-17、AC-18）在两种情况下都生效。
- **拿不到 provider 时**：不注册 profile、不放 BiSheng 子类，框架自带部件保留，P1 的计数、摘要上限、摘要失败处理都不生效。BishengLLM 总能报出内层客户端的 provider，这条路径只在测试用的假模型上出现。
- **何时该重新考虑**：deepagents 升级后改变 harness profile 的查找方式（按 provider 回退）、`excluded_middleware` 的匹配规则或调用方中间件的位置，或进程内出现第二个使用 deepagents 的模块（坑 11、18）。

### 决策 8：失败原因走 error_type，同时登记错误码

- **现状**：任务失败时，前端按 `output_result.error_type` 选择文案（`client/src/components/ChatErrorCard.tsx`），`error_code` 一律是 11090，前端不读它。
- **选定**：
  - 新增两个 `ErrorType`：`context_overflow`、`context_compress_failed`，前端据此显示文案。`context_overflow` 的文案要对任务模式和日常模式都成立（决策 5），建议大意为"内容超出了模型一次能处理的长度。请缩短内容或拆分成几个小任务，也可以换用上下文更长的模型"。这比 spec AC-14 的示例措辞更宽，含义不变。
  - 同时新增错误码 11075（`LinsightContextOverflowError`）、11076（`LinsightContextCompressFailedError`）。`classify_for_event` 遇到这两种类型时写入对应的 `error_code`，不再写 11090。
- **备选（被否）**：只加 error_type，不加错误码。界面能显示，但 spec AC-14、AC-18 要求可观测的错误码，日志检索和开放 API 调用方也需要区分失败原因。
- **何时该重新考虑**：前端改为按错误码选择文案时，error_type 可以退化为错误码的派生字段。
- **顺带修复**：刷新或打开历史任务时，前端只恢复了 `error_message`，没有从 `output_result.error_type` 恢复 `taskErrorInfo`（`useLinsightManager.tsx:134`、`:203`），所以刷新后一律显示"未知错误"。不修这一处，AC-14 在刷新后就不成立，所以纳入本次。

### 决策 9：子任务超窗的处理位置（AC-16）

- **问题**：子任务的 resilience 中间件在压缩中间件内层。如果它像现在这样把超窗"降级"成一条普通回复，外层的压缩就永远看不到超窗，子任务也就不会先压缩再重试。
- **选定**：
  1. resilience 中间件对 `ContextOverflowError` 一律直接抛出，主图、子图都一样（`classify_behavior` 返回 FAIL_FAST）。这样压缩中间件能先处理一次。
  2. 压缩后重试仍超窗时，异常从子图抛出，经 `task` 工具到达主图。主图新增一个 `wrap_tool_call` 中间件，只处理 `task` 工具的 `ContextOverflowError`：返回一条工具结果，说明"这一步超出了模型上下文长度，请缩小范围后再委派"，并计入研究员 resilience 实例的 `_degrade_count`。超过 `max_degrade` 时改为抛出，任务以 `context_overflow` 失败。
- **返回的工具结果**：`status` 用默认的成功状态，内容是说明文字。不用 `status="error"`，因为 `LinsightToolLoopBreaker` 会把连续的错误结果计入失败连击，与降级计数重复计算。
- **异常能传到主图的依据**（已核对源码）：deepagents 的 `task` 工具直接 `await subagent.ainvoke`，没有捕获（`deepagents/middleware/subagents.py:721`）；langgraph ToolNode 默认的 `_default_handle_tool_errors` 对非 `ToolInvocationError` 重新抛出（`langgraph/prebuilt/tool_node.py:383`）；ToolNode 把调用交给 `awrap_tool_call` 链（`tool_node.py:1200`）。主图上现有的工具中间件（resilience、loop breaker、binary guard、invalid-call repair）都不吞异常。
- **备选（被否）**：在子图最外层加一个中间件处理。被否原因：BiSheng 中间件只能追加在框架中间件之后，也就是压缩中间件的内层，排不到子图最外层。
- **原因**：只有在子图外面，才能确定子图自己的压缩已经尝试过。和 resilience 共用计数器，是为了满足 AC-16 的"沿用现有降级次数上限"。
- **何时该重新考虑**：deepagents 的 `task` 工具开始自己捕获子图异常，或 ToolNode 的默认错误处理改为吞掉异常。见 §6.2。

### 决策 10：token 计数以服务商用量为基数（P1，plan §3.3）

- **选定**：`下一次请求的 token 数 = 最近一条带 usage 的模型回复的 total_tokens + 估算(这条回复之后的消息) `。估算使用识别中日韩文字的函数：中日韩字符按 1 个 token 计，其余字符按 4 个字符 1 个 token 计。
- **为什么基数总是有效**：第 N 次调用检查时，最近一条回复来自第 N−1 次调用，那次调用的输入正是当时的有效消息列表；压缩只发生在某次调用内部，那次调用产生的回复的用量已经反映了压缩后的列表。所以不存在"压缩后用量对不上"的问题。plan.md 早先把"刚压缩完之后的第一次调用"列为例外，这个判断有误，已在 plan 中更正。
- **仍需全量估算的情况**：一次运行的第一次调用；服务商不返回用量；最近的回复是降级生成的合成消息（没有 usage）。
- **备选（被否）**：直接用 langchain 的用量校正（`use_usage_metadata_scaling`）。它的放大系数上限是 1.25（`langchain_core/messages/utils.py:2392`），中文内容需要约 2 倍；而且 deepagents 自己计数时没有开启它。
- **备选（被否）**：每次调用前用 vLLM 的 `/tokenize` 精确计数。只有部分服务商提供，而且每次模型调用多一次网络请求。可以用来离线校准中日韩系数。
- **整体计数与局部计数分开**：用量基数只描述"截至某条回复的整个上下文"，不能用来数一段子列表。所以 `BishengSummarizationMiddleware` 只在 `_count_tokens`（判断要不要压缩的整体计数）里用 `count_context_tokens`；传给框架的 `token_counter`（框架用它算保留量的切点、裁剪摘要输入）是纯估算 `estimate_tokens`。
- **何时该重新考虑**：系数在校准中偏差超过 20%；或接入的模型以非中英文为主。

---

## 4. 系统现状（接手必读）

### 4.1 数据流（P0 实现后）

1. `task_exec._create_agent`（`linsight/domain/task_exec.py:1108`）→ `agent_factory.create_linsight_agent`（`linsight/domain/services/agent_factory.py:1276`）。
2. `_resolve_model`（`agent_factory.py:1529`）通过 `LLMService.get_bisheng_linsight_llm` 得到一个新的 `BishengLLM` 实例。每次调用都新建实例（`llm/domain/llm/base.py:33`），所以给它设置 profile 不影响其他任务。
3. **新增**：`create_linsight_agent` 调用 `ContextWindowService.resolve(model)`（llm 模块，见 §4.3），得到 `(可用输入, 来源)`，在日志里记录（AC-09）；可用输入不为空时设置 `model.profile`。这一步必须在 `create_deep_agent` 之前完成，因为框架在构造压缩中间件时就读取 profile（`summarization.py:1718`）。
4. `create_deep_agent`（`agent_factory.py:1493`）构造主图和研究员子图；两者用同一个模型实例，压缩阈值相同。
5. 运行中服务商返回超窗 → `BishengLLM` 改抛超窗异常（决策 5）→ resilience 中间件直接抛出 → deepagents 压缩中间件接住，压缩后重试一次（`summarization.py:1435`）。
6. 重试仍然超窗：
   - 主图：异常传到 `task_exec._execute_agent`（`:1544`），被包成 `TaskExecutionError`，经 `_handle_task_failure`（`:2559`）→ `classify_for_event`（`common/services/llm_error_classifier.py:422`）沿 `__cause__` 找到原始异常，标为 `context_overflow`、错误码 11075 → 写入 `output_result`，推送 `ERROR_MESSAGE` 事件 → 前端 `ChatErrorCard` 按 `error_type` 显示文案。
   - 子图：见决策 9。

### 4.2 关键数据结构 / 字段约定

| 字段 / 结构 | 类型 / 格式 | 说明 | 谁会消费 |
|---|---|---|---|
| 模型高级配置 `user_kwargs.context_window` | 正整数 | 管理员手动指定的上下文长度。构造客户端前必须取出，不能发给服务商 | `ContextWindowService`、`BishengLLM._get_llm_params` |
| Redis `linsight:context_window:<model_id>` | `{"window": int, "kind": "total"\|"input", "source": str, "fingerprint": str}` 或 `{"failed": true, "fingerprint": str}` | 服务商接口读取结果；TTL 成功 3600 秒、失败 300 秒。`fingerprint` 是服务商类型、base URL、模型名的哈希，与当前配置不一致时按未命中处理（决策 4） | `ContextWindowService` |
| `output_result.error_type` | `"context_overflow"` \| `"context_compress_failed"` | 新增两个失败类型 | client `ChatErrorCard`、历史恢复 |
| `output_result.error_code` | 11075 \| 11076 | 新增错误码 | 日志、开放 API 调用方 |
| 日志 `[linsight-context-window]` | `model_id=… window=… kind=… source=… usable_input=…` | 任务开始时记录（AC-09）；超窗失败时再加 `reported_input_tokens`（AC-15） | 现场运维 |

### 4.3 关键模块职责

| 模块 / 文件 | 职责 | 不做什么 |
|---|---|---|
| `llm/domain/services/context_window.py`（新增） | 按优先级确定上下文长度；Redis 缓存与失效；算出可用输入 | 不了解 deepagents，不设置 profile；不发 HTTP 请求 |
| `llm/domain/services/context_window_probes.py`（新增） | 各服务商读取器（`PROBES` 注册表）；单次超时 3 秒；读不到返回 `None` | 不缓存 |
| `llm/domain/llm/context_overflow.py`（新增） | 超窗识别规则表、输入 token 数提取正则、改抛超窗异常（`as_context_overflow`） | 不处理其他错误 |
| `llm/domain/llm/exceptions.py`（新增） | `LLMContextOverflowError`：没有 langchain 对应类的 SDK 使用 | — |
| `linsight/domain/services/context_budget.py`（新增，P1） | CJK 感知计数（`estimate_tokens`）与用量基数计数（`count_context_tokens`）；`BishengSummarizationMiddleware`；`bisheng_summarization()` 上下文管理器（注册 harness profile、设置 ContextVar）；`ToolResultBudgetMiddleware` 单条结果上限 | 不确定上下文长度（那是 llm 模块的事） |
| `resilience_middleware.py` `SubagentContextOverflowMiddleware`（新增） | 决策 9：主图上只处理 `task` 工具的超窗异常，返回说明并计入研究员的降级次数 | 不处理其他工具 |
| `llm/domain/llm/llm.py` `BishengLLM` | 识别超窗错误并改抛；构造客户端前从高级配置取出 `context_window` | 不做压缩 |
| `llm/domain/utils.py` 四个调用装饰器 | 超窗时不把模型标为异常 | — |
| `linsight/domain/services/agent_factory.py` | 调用 `ContextWindowService`，设置 profile，记日志；挂载决策 9 的 `task` 超窗中间件；把 `BishengSummarizationMiddleware` 放在主图和研究员子图中间件列表第一位，并在 `bisheng_summarization()` 块内组装（决策 7）；已知上下文长度时挂 `ToolResultBudgetMiddleware` | 不读取服务商接口 |
| `linsight/domain/services/resilience_middleware.py` | 超窗直接抛出；降级计数供决策 9 共用 | 不吞掉超窗 |
| `common/services/llm_error_classifier.py` | 新增两个 `ErrorType`；`ContextOverflowError` 归 FAIL_FAST；压缩失败按类名识别（不从 common 导入 linsight） | — |
| `common/errcode/linsight.py` | 新增 11075、11076 | — |
| client `ChatErrorCard.tsx`、`useLinsightManager.tsx`、`locales/*/translation.json` | 显示两种新失败文案；刷新后恢复 `error_type` | 不改卡片样式 |

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | 高级配置里的键会原样传给客户端构造函数（`llm.py:51` `_get_user_kwargs`，各 `_get_*_params` 里 `user_kwargs.update(params)`） | `context_window` 被当成未知参数发给服务商，严格校验的服务商会返回 400 | 在 `_get_llm_params` 统一取出（AC-02） |
| 2 | Ollama 的 `max_tokens` 会被改名为 `num_ctx` 发出（`llm.py:96`），含义是上下文长度 | 把它当作最大输出扣除，Ollama 的可用输入会变成 0 | `ContextWindowService` 对 Ollama 特殊处理 |
| 3 | Ollama 超出 `num_ctx` 时默认**静默截断**提示词，不报错 | 不会触发超窗识别；只能靠 profile 提前压缩 | 依赖决策 1，无额外处理 |
| 4 | 框架在**构造**压缩中间件时，根据 profile 是否存在决定用"比例模式"还是"固定 170K 模式"；具体阈值则在每次调用时按当时的 `model.profile` 计算 | 构造之后才设置 profile，框架已经选了固定模式，不会生效；构造之后修改 profile 的数值则会生效 | 决策 1，在 `create_deep_agent` 之前设置 |
| 5 | 拿不到上下文长度时给 profile 填任何占位值，都会把框架从"保留 6 条消息"切换到"保留 10%" | 改变了 AC-08 要求不变的行为 | 决策 2，不设置 profile |
| 6 | resilience 在压缩中间件内层，现在把子图的所有 400 都降级成普通回复 | 子图超窗时压缩永远不会触发 | 决策 9 |
| 7 | 任务模式的失败文案按 `error_type` 选择，不按 `error_code` | 只加错误码，界面仍显示"未知错误" | 决策 8 |
| 8 | 刷新后前端只恢复 `error_message`，不恢复 `error_type` | 新文案刷新后消失 | 决策 8 顺带修复 |
| 9 | vLLM 的 `/v1/models` 里 LoRA 适配器条目的 `max_model_len` 为 null | 读不到适配器的上下文长度 | 读取器沿 `parent` 字段找基础模型 |
| 10 | 百炼的模型信息接口在 DashScope 原生地址，不在 `/compatible-mode/v1` 下，北京区域还需要 WorkspaceId | 按兼容地址拼接口会 404 | P1 读取器；推导不出时按未知处理 |
| 11 | harness profile 是进程级全局注册的 | P1 的注册会影响同进程内所有 deepagents agent | 决策 7，目前只有 linsight 使用 deepagents |
| 12 | 压缩时生成摘要的调用失败后，langchain 返回字符串 `Error generating summary: …` 并继续执行（`langchain/agents/middleware/summarization.py:846`） | 历史被换成一行错误文本，任务带着失忆继续跑 | P1 子类识别并重试（AC-17、AC-18） |
| 13 | 研究员 resilience 实例的 `_degrade_count` 被同一任务的所有 `task` 调用共用，代码注释把这标为 KNOWN GAP（`resilience_middleware.py:393`） | AC-16 依赖的正是"同一任务累计"这个口径。有人按注释把计数改成按调用分桶，AC-16 会被悄悄破坏 | 改动这个计数器时同步改 AC-16 及其测试 |
| 14 | P0 下 deepagents 按 4 个字符 1 个 token 估算，中文少算 2 倍以上 | 以为 P0 已经能在中文任务上提前压缩，实际常常是"超窗后压缩重试" | 决策 1 的 P0 局限；P1 决策 10 |
| 15 | deepagents 只在"这次调用没有主动压缩"时才接住超窗并压缩重试；如果这次调用已经因为达到阈值而主动压缩，压缩后的请求再超窗，异常直接抛出，不会再压缩一次（`deepagents/middleware/summarization.py` 的 `awrap_model_call`，主动压缩分支里的 `handler` 调用不在 `try` 中） | 以为"超窗后一定会压缩重试"；实际上主动压缩后仍超窗时任务直接按 AC-14 失败。这与 spec"同一次请求最多压缩一次"一致 | 测试 `test_context_overflow_flow.py` 的上下文长度取 20000，使历史介于保留量和触发阈值之间，才能覆盖超窗重试路径 |
| 16 | 压缩后保留的 10% 能装下全部历史时，框架判定"没有可压缩的内容"，超窗后只做一次原样重试 | 以为超窗后一定发生了压缩；日志里看不到摘要调用 | 无需处理；保留比例由 P1 的 AC-24 约束 |
| 17 | `unwrap` 原本沿 `__cause__` 一直走到最底层的 SDK 异常；超窗异常是 `raise ... from 原异常`，会被越过 | 分类器拿到普通的 400，标成 unknown | `unwrap` 遇到超窗异常或压缩失败异常即停止（`llm_error_classifier.py`）；日常模式的 `label_error(unwrap(exc))` 因此也能识别 |
| 18 | harness profile 按 provider 全进程注册；注册之后，同一 provider 的模型如果不经 `bisheng_summarization()` 就组装 deep agent，`_summarizer_guard` 会抛 `RuntimeError` | 以后别的模块用同一 provider 的模型直接调 `create_deep_agent` 会失败 | 有意设计成大声失败，而不是悄悄组装一个没有压缩的 agent；新增 deepagents 使用方时要走 `bisheng_summarization()` |
| 19 | `ToolResultBudgetMiddleware` 借用了 `FilesystemMiddleware` 的私有方法 `_intercept_large_tool_result` / `_process_large_message` 来写 `/large_tool_results/` | deepagents 升级改名或改签名时转存会报错 | `pyproject.toml` 锁 `<0.7`；`test_tool_result_budget.py` 在真实图上验证，升级时会先失败 |
| 20 | P1 之后 CJK 计数更准，原来按 4 个字符估算时不会触发的主动压缩现在会触发；而主动压缩之后再超窗不会重试（坑 15） | 测试或现场观察到"没有超窗重试"不代表退化，而是提前压缩生效了 | `test_context_overflow_flow.py` 调小了工具结果，单独覆盖超窗重试路径 |
| 21 | langchain 裁剪摘要输入时用 `start_on="human"`。任务模式的历史只有开头一条用户消息，从尾部截取的片段里找不到它，裁剪结果为空，摘要变成固定句子 `Previous conversation was too long to summarize.`，而且不算失败 | 每次压缩都把全部历史换成这句话，任务失忆后继续运行 | `BishengSummarizationMiddleware._trim_for_summary`：保留开头指令和最新步骤，最新一步本身过大时截断其文本；这句固定文本也算摘要失败 |
| 22 | 已部署环境数据库配置的 `linsight` 段仍带着 P2 删除的键（`tool_buffer` 等）。`LinsightConf` 构造时忽略未知键，但 `get_linsight_conf` / `aget_linsight_conf` 用 `setattr` 逐个写入，pydantic 对未知字段的 `setattr` 会抛异常 | 所有读取任务模式配置的请求都失败，工作台首页 `/workstation/config` 报错打不开（2026-10-22 在 3002 上复现） | `config_service._apply_linsight_overrides`：只写入 `LinsightConf` 定义了的键 |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 契约 | 形式 | 谁在用 |
|---|---|---|
| 模型高级配置 `context_window` | 管理员可见的配置约定 | 管理员；`ContextWindowService` |
| `ErrorType.CONTEXT_OVERFLOW` / `CONTEXT_COMPRESS_FAILED` | `output_result.error_type`、`ERROR_MESSAGE` 事件 | client 任务模式界面；开放 API 任务模式（F073）返回的失败信息 |
| 错误码 11075 / 11076 | `common/errcode/linsight.py`；文案在 `packages/locales` 的 `api_errors` | 日志、开放 API 调用方。需要在 constitution C5 和 release-contract"已分配模块编码"中登记（灵思模块 110 已分配，这里只是新增号） |
| `ContextWindowService.resolve` / `invalidate` | 内部 Python API | linsight agent_factory；llm 模块保存配置的入口 |
| 超窗异常：`OpenAIContextOverflowError` / `AnthropicContextOverflowError`（保留 openai / anthropic 的 SDK 类型）/ `LLMContextOverflowError`（其他 SDK 及 openai 的非 HTTP 状态错误，只保留 `body`、`status_code`），均为 `ContextOverflowError` | 异常类型 | deepagents 压缩中间件、resilience、错误分类器；日常模式错误分类 |

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 风险点 |
|---|---|---|
| deepagents 0.6.12 读取 `model.profile["max_input_tokens"]` 并按 0.85 / 0.10 计算 | 框架行为 | 升级后比例或读取方式改变；`pyproject.toml` 锁 `<0.7` |
| deepagents 压缩中间件在超窗时压缩并重试一次 | 框架行为 | 同上 |
| langchain 中间件顺序：列表靠前为外层 | 框架行为 | 决策 9 依赖它 |
| 各服务商模型信息接口的字段（plan §3.1） | 外部 HTTP 契约 | 字段改名后读不到，回到"未知"，行为与改动前一致 |
| 各服务商超窗报错的文本 | 外部隐式契约 | 文本改变后识别失败，任务以"未知错误"失败，与改动前一致 |
| 子图异常经 `task` 工具传到主图的 `wrap_tool_call`（决策 9 的依据） | 框架行为：deepagents `subagents.py:721` 不捕获；langgraph ToolNode 默认对非 `ToolInvocationError` 重新抛出 | 任一方改为捕获异常，决策 9 的中间件收不到超窗，AC-16 失效；升级 deepagents 或 langgraph 时由 T012 的测试守住 |

---

## 7. 测试与可观测

- **单元测试**（无外部依赖）：
  - 来源优先级与可用输入计算（含 Ollama、仅输入上限、最大输出 ≥ 上下文长度）。
  - 每个读取器用录制的响应体测试。
  - 超窗识别：每条规则用真实报错原文测试。
  - `context_window` 不出现在客户端参数中。
  - 错误分类：两个新类型与 FAIL_FAST。
  - resilience 对超窗直接抛出；决策 9 的中间件计数与超限抛出。
- **集成测试**：用假模型构造"第一次调用超窗、压缩后成功"和"两次都超窗"的序列，驱动 `create_linsight_agent` 构造的真实图，断言压缩发生、任务结果和 `output_result`。
- **集成测试必须包含中文场景**：假模型返回带 usage 的回复，工具返回大段中文，构造"估算未到阈值、实际超窗"的序列，断言走的是超窗后压缩重试（P0）；P1 完成后同一用例断言改为提前压缩。
- **手动验证（AC-12）**：
  1. 准备一台有 GPU 的测试机（具体机器在 T015 执行时确定），启动 `vllm serve <模型> --max-model-len 32768`；确认 `curl <地址>/v1/models` 返回 `max_model_len: 32768`。
  2. 在测试环境的模型管理里把它配成 vllm 类型，不填 `context_window`；在工作台设为任务模式模型。
  3. 执行"读取多份中文长文档并写报告"的任务。
  4. 在任务执行进程日志里检查：`grep "linsight-context-window"` 应有 `window=32768 source=deployed`；压缩日志出现；任务完成。区分两种压缩：提前压缩（没有超窗报错）和超窗后压缩（先有一次被识别的超窗）。P0 允许后者出现。
  5. 用 `--max-model-len 133120` 复验客户场景。
- **可观测**：任务开始时的 `[linsight-context-window]` 日志；超窗失败时附带服务商报告的输入 token 数。

---

## 8. 后续改进 / 不打算做的事

- 模型配置页面的"上下文长度"字段（D8 否决）：当高级配置的使用门槛成为现场问题时，再起需求。
- MindIE、火山方舟、千帆、腾讯、讯飞的读取器：拿到真实环境或公开文档后再补。
- 图片张数、技能清单长度的上限：另起需求。
- `ls`、`glob`、`grep` 的输出不转存（转存只会引出又一次列举），超过单条上限时截断，并提示缩小范围。spec AC-19 已写明这一例外（用户 2026-10-21 确认，plan D12）。
- 小窗口模型下压缩后仍可能超窗（2026-10-22 3002 实测，用户决定"有需要支持小模型时再说"）：系统提示词与工具定义固定占约 16K token；模型在同一步并行发起 6–8 次搜索时，这一步的工具结果约 15K，压缩无法移除（下一次调用必须带上）。两者相加已超过 32K，32K 窗口下 23 次调用中有 6 次超过可用输入，最大 43154。窗口在约 48K 以下才会出现；客户的 133K 窗口不受影响。需要支持小模型时，候选做法是给同一步的全部工具结果设总上限（例如可用输入的 25%），按比例截断。
- 百炼读取器的待核实点：本地 dashscope SDK 1.25 用 `GET {base}/api/v1/models/{name}` 查询单个模型，WorkspaceId 是可选请求头；官方文档（2026-10-21）给出的 list 接口则要求北京区域 host 带 WorkspaceId。目前按官方文档实现，默认地址按未知处理。如果现场用真实 key 验证单模型接口在默认地址可用，再补一个读取路径。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-10-21 | 初版 | spec 确认 |
| 2026-10-21 | §5 增坑 15、16、17 | P0 实现与集成测试中发现 |
| 2026-10-21 | 决策 4 增缓存指纹与 repr 脱敏；决策 5 增输出侧超限排除；§4.2、§4.3、§6.1 与代码对齐 | `/code-review` 第一轮 |
| 2026-10-21 | 决策 5 输出侧判据改为"输出预留 ≥ 上下文长度"；读取器兜底异常只记类型 | `/code-review` 第二轮 |
| 2026-10-21 | P1 实现：决策 7 验证结论、§4.3 增 context_budget.py、§5 增坑 18、19、20；P2 删除死配置 | P1 / P2 实现 |
| 2026-10-21 | P1 代码审查：压缩部件改为放在中间件列表第一位（不再经 `extra_middleware` 注入）；摘要输入裁剪改为保留开头指令和最新步骤；`ls`/`glob`/`grep` 输出按单条上限截断；§5 增坑 21 | `/code-review`（T032）|
| 2026-10-22 | §5 增坑 22：数据库配置里的已删除键让任务模式配置读取报错 | 3002 部署验证 |
| 2026-10-22 | §8 记录小窗口下压缩后仍超窗的限制，暂不处理 | 3002 部署验证 |
