# F087 任务模式上下文窗口预算 — 方案

**状态**：方案已对齐（决策见 §7），下一步拆成 spec.md / design.md / tasks.md
**所属版本**：v3.0.0（只提交到 `feat/3.0.0`）
**分支**：`feat/3.0.0/087-context-window-budget`
**触发问题**：某客户现场用 vLLM 部署本地模型（`max_model_len=133120`），任务模式执行技能时报 400：`This model's maximum context length is 133120 tokens. However, you requested 0 output tokens and your prompt contains at least 133121 input tokens`。

---

## 0. 结论

任务模式里没有"上下文预算"这个概念。BiSheng 不知道模型的上下文窗口有多大，所有大小限制都是写死的数字。这些数字是按 200K 左右的窗口、按英文"4 个字符约等于 1 个 token"设计的。窗口一旦小于 170K，或者内容以中文为主，触发压缩、限制单次输入、处理超窗这三个环节会一起失效。

本方案的做法是：每个模型确定一个上下文窗口，其余预算全部从这个窗口推导；同时补上"压缩失败"和"超窗之后"两处缺失的处理，让异常对用户和运维可见。

### 术语

本文统一使用以下术语，每个概念只用一个词。

| 术语 | 定义 |
|---|---|
| 上下文窗口（W） | 模型单次请求能接受的 token 总数，输入加输出。vLLM 中即 `--max-model-len` |
| 输出预留（R） | 为模型输出保留的 token 数 |
| 输入预算（I） | `I = W − R`，单次请求输入部分的上限 |
| 压缩 | deepagents 的 `SummarizationMiddleware` 把较早的历史消息替换成一段摘要 |
| 转存 | 把过大的工具结果写进工作区文件 `/large_tool_results/<call_id>`，上下文里只保留开头片段和文件路径 |
| 超窗 | 请求的 token 数超过上下文窗口，服务商返回 400 |

---

## 1. 根因

这次报错由两处缺陷叠加造成。

**第一，压缩阈值大于上下文窗口。** deepagents 0.6.12 先读模型的 `profile["max_input_tokens"]`。读到时，压缩在输入达到 85% 时触发；读不到时，压缩阈值固定为 170000 tokens（`deepagents/middleware/summarization.py:261-298`）。BiSheng 没有给任何模型设置 `profile`，所以一律使用 170000。客户的窗口是 133120，小于 170000，所以压缩永远不会在超窗之前触发。

**第二，超窗报错没有被识别。** deepagents 有一层兜底：模型抛出 `ContextOverflowError` 时，它当场压缩历史并重试一次（`summarization.py:1435`）。但 `langchain_openai` 只把三种文本识别为超窗：`context_length_exceeded`、`Input tokens exceed the configured limit`、`prompt is too long`（`langchain_openai/chat_models/base.py:520`）。vLLM 的文本是 `This model's maximum context length is ...`，不在其中。已用这段原文在本地验证：它没有被转换成 `ContextOverflowError`。之后 BiSheng 的 resilience 中间件把这个 400 归为 DEGRADABLE（`common/services/llm_error_classifier.py:324`），主图直接失败，错误标签是 UNKNOWN。

---

## 2. 现状盘点

以下 7 类逻辑都和上下文窗口有关，覆盖从"窗口从哪来"到"多轮之间"的全部环节。代码位置以 `feat/3.0.0`（8510a9645）和 deepagents 0.6.12 为准。

### A. 窗口来源：目前没有来源

| 项 | 现状 |
|---|---|
| 模型配置 | 没有"上下文窗口"字段。全仓没有任何 `profile` 赋值 |
| 服务商接口 | vLLM 等服务商的接口能返回窗口（见 §3.1），BiSheng 没有读取 |
| `max_tokens` 一词两义 | Ollama 把它改名为 `num_ctx`，含义是上下文窗口（`llm/domain/llm/llm.py:96`）；其他服务商把它当输出预留发出（`llm.py:367`）。前端 `ModelItem.tsx` 按服务商切换标签，管理员容易把窗口大小填进"最大输出" |

### B. 压缩时机：阈值和计数都不准

| 项 | 现状 |
|---|---|
| 压缩阈值 | 没有 profile 时为 170000 tokens |
| 压缩后保留 | 没有 profile 时保留最近 6 条消息，和 token 数无关 |
| token 计数 | `count_tokens_approximately`，4 个字符算 1 个 token。用服务商返回的用量校正时，放大系数上限 1.25（`langchain_core/messages/utils.py:2392`）。中文在 Qwen 类 tokenizer 下约 1 到 1.5 个字符算 1 个 token，所以中文内容会被少算一半左右（估算值，未用客户模型实测） |
| 按用量触发 | 只看上一条模型回复的 `usage_metadata.total_tokens`，不包含之后新进入的工具结果 |

### C. 单次输入：固定字符上限，部分没有上限

| 来源 | 上限 | 位置 |
|---|---|---|
| 框架转存阈值、`read_file` 单次截断 | 80000 字符（`4 × 20000`） | `deepagents/middleware/filesystem.py:2040`、`:1061` |
| `ls` / `glob` / `grep` 输出 | 80000 字符 | `deepagents/backends/utils.py:68` |
| 代码执行输出 | 成功 30000 字符，失败 8000 字符 | `bisheng_langchain/gpts/tools/code_interpreter/base_executor.py:199` |
| 自定义 API 工具 | 10000 字符 | `bisheng_langchain/gpts/tools/api_tools/base.py:68` |
| 网页读取（F085） | 默认 20000 字符，可配 1000–200000 | `bisheng_langchain/gpts/tools/web_fetch/tool.py` |
| 知识库检索 | 条数由模型传入，没有上界；单个分段不截断 | `tool/domain/langchain/linsight_knowledge.py` |
| 联网搜索、MCP 工具 | 没有上限 | — |
| 图片 | 单张不超过 500KB，张数不限 | `linsight/domain/services/workspace_backend.py` |
| 引用来源表 | 每次模型调用最多约 9000 字符 | `linsight/domain/services/citation_source_middleware.py` |
| 技能清单 | 技能个数不限 | deepagents `SkillsMiddleware` |
| 一轮并行多个工具调用 | 上面的单条上限按调用个数叠加 | — |
| 固定开销（system prompt 与工具 schema） | 约 2 万多字符，粗估 1.2–1.6 万 tokens | `linsight/domain/services/agent_factory.py` |

### D. 压缩本身：摘要调用不截断，失败时静默

`create_summarization_middleware` 在创建压缩中间件时传入 `trim_tokens_to_summarize=None`（`summarization.py:1659`）。结果是"生成摘要"这次模型调用会把待压缩的全部历史原样发给模型。在超窗兜底这条路径上，待压缩的历史接近整个窗口，摘要调用本身也会超窗。摘要调用失败时，异常被 `except Exception` 吞掉，摘要内容变成一行 `Error generating summary: ...`（`langchain/agents/middleware/summarization.py:846`）。任务继续执行，但之前的历史只剩一个文件指针，日志里也没有错误级别的记录。

### E. 超窗之后：任务直接失败，原因不可见

| 项 | 现状 |
|---|---|
| 报错识别 | vLLM 的超窗文本不被识别为 `ContextOverflowError`，框架兜底不执行 |
| 主图 | resilience 中间件归为 DEGRADABLE，直接抛出，任务失败，标签 UNKNOWN |
| 研究员子代理 | 返回降级消息，最多 3 次后抛出，期间父图上下文仍在增长 |

### F. 多轮之间：历史没有上界

| 路径 | 现状 |
|---|---|
| "继续"、"重试"、`ask_user` 回答后恢复 | 复用同一个 thread，从 checkpoint 恢复全部消息。历史大小完全依赖 B 类压缩 |
| 新一轮任务带入上一轮摘要 | `build_prior_conversation_summary(max_chars=8000)`（`linsight/domain/utils.py:1108`）；第一轮和最近一轮总是保留，所以只是软上限 |

### G. 死配置

`linsight` 配置里的 `tool_buffer`、`file_content_length`、`max_file_num`、`max_knowledge_num`、`retry_temperature`、`max_file_content_num` 都没有代码读取。现场修改它们不起作用。

---

## 3. 方案

### 3.1 确定上下文窗口

BiSheng 按以下优先级确定每个模型的上下文窗口：

1. **手动配置。** 管理员在模型配置的"高级配置"JSON 里填写 `{"context_window": 133120}`。不新增前端字段（决策 D8）。高级配置的内容会原样传给模型客户端的构造参数（`llm/domain/llm/llm.py:51` `_get_user_kwargs`），所以 BiSheng 必须在构造客户端之前取出 `context_window`，否则它会被当成未知参数发给服务商。
2. **Ollama 的 `num_ctx`。** Ollama 的"上下文长度"字段（存为 `max_tokens`）会作为 `num_ctx` 随每次请求发出（`llm.py:96`），它就是 Ollama 实际生效的窗口。所以 Ollama 填了这个字段时，直接用它作为上下文窗口。
3. **服务商接口。** 前两步都没有时，调用该服务商的模型信息接口读取。
4. **保持现状。** 以上都拿不到时，不设置 profile，deepagents 使用 170000 的默认阈值。

第 4 步不改默认值，因此本方案对"拿不到窗口"的模型不改变现有行为。这类模型的安全网是 §3.5 的超窗识别：即使阈值偏大，超窗后也会先压缩再重试。

#### 缓存（决策 D2）

BiSheng 在任务开始时读取上下文窗口，结果存进 Redis，所有节点共享。读取成功的结果缓存 1 小时；读取失败的结果缓存 5 分钟，这 5 分钟内按"读不到"处理，不重复请求。管理员保存模型配置时，BiSheng 清除该模型的缓存。部署变化（例如重启 vLLM 时改了 `--max-model-len`）最多 1 小时后自动生效。

#### 服务商接口调研（2026-10-21）

BiSheng 的 19 种服务商类型中，有 8 种能用对话接口的同一个 API key 读取上下文窗口。读到的值分为两种。**部署值**是推理服务启动时实际生效的上限，例如 vLLM 的 `--max-model-len`。**理论值**是模型或平台公布的上限，可能大于实际部署的上限。

| 服务商类型 | 能否读取 | 接口 | 字段 | 值的性质 | 证据 |
|---|---|---|---|---|---|
| vllm | 能 | `GET /v1/models` | `data[].max_model_len` | 部署值 | 源码，v0.5.0 起 |
| llamacpp | 能 | `GET /props` | `default_generation_settings.n_ctx` | 部署值（单个 slot） | 源码 |
| ollama | 部分 | `GET /api/ps`；`POST /api/show` | `models[].context_length`；`model_info["<arch>.context_length"]` | `/api/ps` 是部署值，但只在模型已加载时出现；`/api/show` 是理论值 | 源码 |
| xinference | 能 | `GET /v1/models` | `data[].context_length` | 理论值，不反映启动参数 | 源码 |
| anthropic | 能 | `GET /v1/models/{id}` | `max_input_tokens`；输出 `max_tokens` | 平台公布值 | 官方文档 |
| deepseek | 能 | `GET /models` | `data[].context_window`（输入加输出）；输出 `data[].max_output_tokens` | 平台公布值 | 官方文档 |
| moonshot | 能 | `GET /v1/models` | `data[].context_length` | 平台公布值 | 官方文档 |
| qwen（百炼） | 能，但要走原生接口 | `GET /api/v1/models?model=<name>`（DashScope 原生，不是 `/compatible-mode/v1`） | `output.models[].model_info.context_window`、`max_input_tokens`、`max_output_tokens` | 平台公布值 | 官方文档 |
| MindIE | 部分 | `GET /info`；`GET /v2/models/{name}/config` | `max_input_length`、`max_total_tokens`；`max_seq_len` | 部署值；官方已标为计划弃用，`/info` 可能只在管理端口提供 | 只有搜索摘要，需在真实环境验证 |
| openai | 不能 | `GET /v1/models` 只有 id、created、owned_by | — | — | SDK 类型定义 |
| azure_openai | 不能 | 数据面接口没有 token 上限；控制面需要 Entra ID 鉴权 | — | — | 官方文档 |
| zhipu、minimax、silicon | 不能 | 没有模型列表接口，或列表里没有窗口字段 | — | — | 官方文档 |
| volcengine、qianfan、tencent、spark | 未核实 | 火山方舟、千帆只有控制面接口，需要 AK/SK，不是对话 key | — | — | 文档无法读取或无公开资料 |
| bisheng_rt | 跳过 | 无公开资料 | — | — | — |

另外，以下几种推理服务常被配置成 openai 类型接入。它们也能读取上下文窗口：SGLang（`/v1/models` 的 `data[].max_model_len`，部署值）、LM Studio（`/api/v1/models` 的 `loaded_instances[].config.context_length`）、OpenRouter（`/api/v1/models` 的 `data[].context_length`）、LiteLLM proxy（`/model/info` 的 `model_info.max_input_tokens`）。

#### 读取策略

1. **按服务商类型分别实现读取逻辑**，每种只用对话接口已有的 base_url 和 API key，不新增凭据。P0 覆盖 7 种：vllm、openai 类型的 `/v1/models` 探测、llamacpp、ollama、xinference、anthropic、deepseek、moonshot（决策 D1）。qwen（百炼）放到 P1，MindIE 在真实环境验证后再定。
2. **openai 类型配了自定义 base_url 时，探测 `GET /v1/models`。** 现场常把 vLLM、SGLang 配成 openai 类型。返回里有 `max_model_len` 就按部署值使用；有 `context_length` 就按平台公布值使用。
3. **优先使用部署值。** Ollama 先读 `/api/ps`；模型未加载时再读 `/api/show` 的 `parameters` 里有没有 `num_ctx`；最后才用 `model_info` 里的理论值。
4. **理论值可以使用，但要记录来源。** 理论值可能大于实际部署的上限，例如 Xinference 用 vLLM 引擎时手动调小了 `max_model_len`。这种情况由 §3.5 的超窗识别兜底：超窗后先压缩再重试。每次任务开始时，BiSheng 在日志里记录窗口大小和来源（手动配置 / Ollama num_ctx / 部署值 / 理论值），方便现场排查。
5. **读不到时不猜。** 不能读取、未核实的服务商类型，或接口调用失败时，按 §3.1 第 4 步保持现状。
6. **百炼需要推导原生接口地址。** 模型配置里通常只有 `/compatible-mode/v1` 的 base_url。原生接口的 host 要从它推导，北京区域还需要 WorkspaceId。推导不出来时按读不到处理。
7. **MindIE 先在真实环境验证再实现。** 现有证据只有搜索摘要，接口已被标为计划弃用，P0 不包含它。

### 3.2 预算推导

确定上下文窗口后，所有预算从它推导：

| 预算 | 推导方式 | W=133120 时 |
|---|---|---|
| 输出预留 R | 模型配置里填了"最大输出 token 数"（`max_tokens`）就取这个值；没填就是 0，不单独预留（决策 D3）。Ollama 的 `max_tokens` 含义是 `num_ctx`，所以 Ollama 的 R 恒为 0 | 0 |
| 输入预算 I | `W − R` | 133120 |
| 压缩阈值 | `0.85 × I`（deepagents 读到 profile 后的默认比例） | 约 113K |
| 压缩后保留 | `0.10 × I` | 约 13.3K |
| 单条工具结果上限 | `0.10 × I`，等于"压缩后保留"，保证刚取回的结果不会在下一次压缩中被整条并进摘要（决策 D6） | 约 13.3K |
| 摘要调用的输入上限 | `0.5 × I` | 约 66.5K |

传给 deepagents 的 `profile["max_input_tokens"]` 设为输入预算 I。deepagents 用这个值乘以比例计算阈值，所以配置了 `max_tokens` 时要先扣掉。R 为 0 时，输出空间来自压缩阈值之上空着的约 15%：133K 窗口约 2 万 token，32K 窗口约 4900 token。

拿不到窗口的模型不推导预算，单条工具结果上限仍是框架的 80000 字符。

### 3.3 token 计数：以服务商用量为基数，只估算增量

服务商每次返回的用量是"刚发出去的那次请求"的实际 token 数。压缩要回答的问题是"下一次请求会不会超窗"。下一次请求比上一次多出来的内容，主要是刚返回的工具结果，这部分还没有被任何服务商计数过。所以完全依赖用量做不到提前判断，但可以把用量当作基数：

```
下一次请求的 token 数 ≈ 上一条模型回复的 usage.total_tokens + 估算(此后新增的消息)
```

`total_tokens` 等于上一次的输入加输出，正好覆盖了到上一条模型回复为止的全部消息。只有之后新增的消息需要估算，估算误差因此只作用在增量上。

以下情况拿不到基数，只能全量估算：

- 一次运行的第一次模型调用。
- 服务商流式响应不返回用量。
- 从没有用量记录的旧 checkpoint 恢复。

（初稿曾把"刚压缩完之后的第一次调用"列为例外，这个判断有误：压缩只发生在某次调用内部，那次调用产生的回复的用量已经对应压缩后的列表。论证见 design.md 决策 10。）

另外，判断"单条工具结果是否超出上限"发生在结果进入上下文之前，这时只能估算。

估算统一使用识别中日韩文字的计数函数：中日韩文字按 1 个字符算 1 个 token，其余字符按 4 个字符算 1 个 token。这个系数偏保守，可以用 vLLM 的 `/tokenize` 接口在真实样本上校准。

### 3.4 单条输入统一按 token 限制

已知上下文长度时，超过 §3.2"单条工具结果上限"的工具结果统一转存到 `/large_tool_results/`，按 §3.3 的计数函数计算 token 数。各工具自带的字符截断保持不变，它们之上由这条统一上限兜住。知识库检索的全部结果是一条工具结果，同样受这条上限约束，不单独限制条数。图片张数和技能清单长度不在本次范围内（见 spec.md 范围边界）。

### 3.5 压缩失败与超窗必须可见

1. **识别超窗。** `BishengLLM` 识别 vLLM、OpenAI 及其他常见服务商的超窗报错，统一转换为 `ContextOverflowError`，让 deepagents 执行压缩后重试。（P0）
2. **超窗收尾（决策 D4）。** resilience 中间件把超窗单独分为一类：不重试，交给压缩处理。压缩后重试仍然超窗时，任务以新增的错误码失败。前端显示三种语言的文案，大意是"任务内容超出了模型一次能处理的长度，请拆分任务或换用上下文更长的模型"。日志记录窗口大小、窗口来源和实际 token 数。已生成的文件保留。（P0）
3. **摘要失败（决策 D5）。** 摘要调用失败时，BiSheng 重试一次，重试时交给模型的内容不超过"摘要调用的输入上限"。仍然失败时，记错误级别日志，任务以明确的错误码失败。`Error generating summary` 不能被当成摘要继续使用。这一项要接管框架的压缩中间件，依赖 §3.6，所以放在 P1。

### 3.6 框架约束与技术路线（决策 D7）

`create_deep_agent` 只暴露了 `profile` 这一个入口。计数函数、摘要截断、摘要失败处理、转存阈值都是框架内部创建中间件时写死的，`FilesystemMiddleware` 还不允许被排除。本方案采用框架允许的替换方式，不修改框架源码。P1 第一步先做技术验证，确认可行后再实现：

1. **替换压缩中间件。** 用 harness profile 的 `excluded_middleware` 按名字排除框架自带的 `SummarizationMiddleware`，再通过 `middleware=` 传入 BiSheng 的子类实例。子类必须改 `name`，否则会被同一条排除规则一起去掉。这样计数函数、摘要截断、保留比例都由 BiSheng 控制。
2. **在内层先转存。** BiSheng 新增一个 `wrap_tool_call` 中间件。它位于框架 `FilesystemMiddleware` 的内层，先拿到工具结果，按"单条工具结果上限"转存。框架 80000 字符的阈值因此不再起作用。主图和研究员子代理都要挂。

升级 deepagents 时，需要复查这两处依赖的接口：`excluded_middleware` 的匹配规则，以及中间件的嵌套顺序。

---

## 4. 分批交付

| 批次 | 内容 | 解决的问题 |
|---|---|---|
| P0 | §3.1 确定上下文窗口（高级配置、Ollama num_ctx、7 种服务商接口、Redis 缓存）并设置 profile；§3.2 输出预留和输入预算；§3.5 第 1、2 项 | 这次的直接报错；超窗后原因不可见 |
| P1 | §3.6 技术验证；§3.3 计数；§3.4 统一的单条上限；§3.5 第 3 项摘要失败；qwen（百炼）接口读取 | 中文内容少算；压缩后刚取回的内容丢失；摘要调用超窗或失败被掩盖 |
| P2 | 删除 G 类死配置 | 现场被无效配置误导 |

## 5. 验收标准

- **AC-01**：高级配置里填写了 `context_window` 时，任务模式的输入预算等于 `context_window` 减已配置的 `max_tokens`；未配置 `max_tokens` 时等于 `context_window`。
- **AC-02**：高级配置里的 `context_window` 不出现在发给服务商的请求参数中。
- **AC-03**：Ollama 模型填写了"上下文长度"时，任务模式使用这个值作为上下文窗口。
- **AC-04**：没有手动配置时，P0 覆盖的 7 种服务商能从接口读到窗口；同一模型在缓存有效期内只请求一次接口，所有节点读到同一个值。
- **AC-05**：管理员保存模型配置后，该模型下一次任务重新读取窗口。
- **AC-06**：接口读取失败时，5 分钟内不再重复请求，任务按"读不到"处理。
- **AC-07**：手动配置和服务商接口都拿不到窗口时，任务模式的压缩行为与改动前一致。
- **AC-08**：在 `max_model_len=133120` 的 vLLM 上执行原报错任务，压缩在超窗之前触发，任务不再因超窗失败。
- **AC-09**：上下文窗口配置得比实际值大时，vLLM 返回超窗 400 后，任务先压缩再重试，而不是直接失败。
- **AC-10**：压缩后重试仍然超窗时，任务以新增错误码失败，前端显示对应文案（zh-Hans / en / ja），日志记录窗口大小、窗口来源和实际 token 数。
- **AC-11**：摘要调用失败时重试一次；仍然失败时日志有错误级别记录，任务以明确的错误码失败。（P1）
- **AC-12**：已知窗口时，单条工具结果超过输入预算的 10% 就被转存，上下文中只保留开头片段和文件路径。（P1）
- **AC-13**：以中文为主的任务，压缩触发时的实际 token 数（以服务商返回的用量为准）不超过输入预算。（P1）

## 6. 本次不做

| 项 | 原因 |
|---|---|
| 修改 170K 默认值 | 拿不到窗口的模型保持现有行为 |
| 前端新增"上下文长度"字段 | 决策 D8：手动配置只用高级配置。Ollama 的"上下文长度"与其他服务商的"最大输出"共用 `max_tokens` 字段的问题保持现状 |
| 默认输出预留 | 决策 D3：未配置 `max_tokens` 时不预留 |
| MindIE 接口读取 | 只有搜索摘要作为证据，接口已被标为计划弃用，需先在真实环境验证 |
| 日常模式的 `maxTokens` | 只在日常模式使用，任务模式不读取 |
| 开放 API 的 4000 字符说明上限 | 属于固定开销，已计入输入预算 |
| 任务标题生成 | 只放入用户问题，输出截到 50 字符 |

## 7. 决策记录（2026-10-21 采访对齐）

| 编号 | 问题 | 决策 |
|---|---|---|
| D1 | P0 支持自动读取的服务商 | vllm、openai 类型 `/v1/models` 探测、llamacpp、ollama、xinference、anthropic、deepseek、moonshot；qwen（百炼）放 P1 |
| D2 | 读取结果的存储 | 运行时读取，存 Redis；成功缓存 1 小时，失败缓存 5 分钟；保存模型配置时清除 |
| D3 | 默认输出预留 | 不单独预留；只在配置了 `max_tokens` 时扣除 |
| D4 | 压缩后仍超窗 | 新增错误码，任务失败，前端三种语言文案，日志记录诊断信息，已生成文件保留 |
| D5 | 摘要调用失败 | 重试一次（输入不超过 `0.5 × I`），仍失败则任务以明确错误码失败（P1） |
| D6 | 单条工具结果上限 | 输入预算的 10% |
| D7 | 接管框架内部逻辑的方式 | 用框架允许的方式替换（排除并替换压缩中间件、内层转存），不改框架源码，P1 先做技术验证 |
| D8 | 手动配置入口 | 只用高级配置 JSON 的 `context_window` 键，不新增前端字段 |
| D9 | 子任务压缩后仍超窗 | 降级：向主任务说明"超出上下文长度、应缩小范围"，主任务继续；被结束次数超过现有的 `max_degrade`（默认 3）后整个任务失败（spec AC-16） |
| D11 | P0 下中文计数偏少 | AC-11 改为"按系统的 token 计数"判断；中文准确性由 P1 的 AC-21 保证，P0 下中文任务允许先超窗再压缩重试（2026-10-21 design 审查后确认） |
| D10 | 摘要失败的错误码 | 新增"上下文压缩失败"错误码，与超窗失败分开（spec AC-18） |

## 8. 后续步骤

1. 在 `features/v3.0.0/release-contract.md` 登记 F087。
2. 按 SDD 把本方案拆成 spec.md、design.md、tasks.md，经 `/sdd-review` 后开始实现 P0。
