# Design: 日常模式与任务模式内容安全审查（F063）

> **本文档定位 — 实现方案 / 现状快照（Why this How）**
>
> - `spec.md` 回答 **做什么**
> - `design.md`（本文）回答 **为什么这么实现**、挂在哪、SSE 怎么换、哪些路必须一起拦
>
> **关联**: [spec.md](./spec.md) · PRD《3.0 beta2》§5.2
> **版本**: v3.0.0-beta1
> **最后更新**: 2026-09-09

---

## 1. 目标与非目标

- **目标**：商业版工作台用**一份租户词表**审查日常模式输入 + 最终回答、任务模式输入；命中后用管理员配置的自动回复结束本轮。匹配引擎、词表形态、配置面板与现有知识空间 / 频道 / 工作流关键词审查对齐，不新造一套敏感词系统。
- **非目标**：见 [spec.md](./spec.md) 范围边界。实现上额外钉死：
  - **不把审查放进 Java Gateway**。工作流走 Gateway 是因为它的请求/响应是助手/技能那套 JSON；日常模式是自定义 `agent_answer` SSE，Gateway 解析不了「最终回答 vs 思考」。
  - **不把策略塞进工作台 JSON 配置**。词表已有 `sensitive_word_policy` 表，按 `business_type` 分行。
  - **不新增表、不 Alembic**（只加枚举值）。
  - **命中不是错误码**：对用户是一条正常助手消息，文案来自自动回复。

---

## 2. 关键约束

全局铁律遵循 `docs/constitution.md` C1–C7。本功能特有：

- **商业版**：UI 用 `appConfig.isPro`，运行时用 `settings.get_system_login_method().bisheng_pro`。开源进程即使库里有策略行，也跳过审查。
- **一份策略**：PRD 只有首页一个面板，日常和任务共用 `business_type=workbench_chat`。
- **只审文本**：用户输入取 `APIChatCompletion.text` / 灵思 `question`；不读 `files[]`、不读解析结果。语音识别后进输入框的字算用户文本，要审。
- **日常输出只审最终回答**：累积对象是 `final_msg`（`agent_answer/stream` 的正文），不是 `agent_thinking`、不是 tool_call。
- **100 字**：按 Python `len(str)`（Unicode 码点）计，与「字」一致。每次用**全文**跑 AC，不用「最近 100 字窗口」（否则词跨边界会漏）。流结束必须再审余量。
- **任务模式命中不能发 `linsight_task_handoff`**：前端收到 handoff 会 `createLinsight` + `start-execute`。命中后走日常 `agent_answer` 结束本轮即可（发送时已经插了普通助手占位气泡）。
- **i18n**：面板文案三语齐发；自动回复是管理员配置的租户内容，原文入库，不走 i18n。
- **C6**：日志可记「命中 / 租户 / business_type」，**不要把命中词和用户原文打进 info 日志**。

---

## 3. 方案对比与选定

### 决策 1：挂 Python `sensitive_word`，不扩展 Gateway 过滤器

- **备选**：
  - A. 在 `SensitiveWordPolicyService` 上新增 `workbench_chat`，在日常/任务入口调用 `check_text`。
  - B. 扩展 Gateway `SensitiveWordsFilter` / `CustomResponseFilter`，把 `/api/v1/workstation/chat/completions` 加进拦截名单。
  - C. 把词表写进工作台 `workstation` JSON，聊天链路自己扫字符串。
- **选定**：A。
- **原因**：
  - 知识空间文件解析、频道文章已经是 A：租户行 + AC 自动机 + 同一张 `sensitive_word_policy`。
  - 工作流走 B 是历史包袱：Gateway 只认 `/api/v2/assistant/chat/completions` 和 `/api/v1/process`，流式字段是 `choices[0].delta.content` / `data.result.answer`。日常模式是 `category=agent_answer` 的自定义 SSE，Gateway 要新写一套协议才能区分思考和最终回答。
  - 首页配置是**租户一份**，不是按应用 `resource_id`。Gateway 表 `gt_sensitive_words` 是按资源绑的，和「工作台首页」对不上。
  - C 会把大词表推进本就脆弱的工作台 JSON，和 F036 已落地的表重复。
- **何时该重新考虑**：若产品改成「每个应用单独词表」且审查要在网关统一掐入口。

### 决策 2：日常和任务共用一个 `business_type`

- **备选**：
  - A. `workbench_chat` 一条策略。
  - B. `workstation` + `linsight` 两条，首页两个面板。
- **选定**：A。
- **原因**：PRD 只有一个入口、一套词表、一份自动回复。任务模式本期不审输出，差异在**挂点**，不在配置。
- **何时该重新考虑**：产品要任务单独开关或单独回复话术。

### 决策 3：输入命中也落库（用户句 + 自动回复），输出命中丢掉模型正文

- **备选**：
  - A. 输入命中：仍写用户消息和助手自动回复；不调 LLM / 不创建任务。输出命中：停止生成，助手行只存自动回复，不存已流出的模型字。
  - B. 输入命中：HTTP/SSE 报错，前端 toast，不写消息。
  - C. 输出命中：在已流出的正文后面追加自动回复。
- **选定**：A。
- **原因**：PRD 是「返回固定自动回复 / 替换当前模型回答」，不是错误码。前端发送时已经插入用户气泡和空助手气泡；报错会留下空助手行。输出若追加，违规字仍留在历史里，刷新后还能看见。
- **何时该重新考虑**：合规要求「命中的用户原文也不能落库」。

### 决策 4：输出替换复用已有 `agent_answer/end`，不新事件类型

- **备选**：
  - A. 停止 token 后发 `agent_answer/end`，`message.msg` = 自动回复，并带 `events: [{type:'text', content: auto_reply}]`。
  - B. 新增 `agent_answer/replace`。
- **选定**：A。
- **原因**：`useAiChatSSE.ts` 在 `type==="end"` 时已经用 `message.msg` **整段覆盖** `responseText`，有 `events` 则整表替换。最多泄漏的是上一次审查前已流出的 ≤99 字，随后被覆盖。新事件要改两端协议，收益只是少一次覆盖语义。
- **代价**：命中前用户可能瞥见最多约 100 字模型输出。这是 PRD「每 100 字审一次」的固有窗口，与工作流 Gateway 流式过滤同类。
- **何时该重新考虑**：产品要求「一个字都不能先画出来」——那时改为先缓冲满 100 字再发给前端（首包延迟换零泄漏）。

### 决策 5：配置面板跟首页「保存」，不单独再做一个保存条

- **备选**：
  - A. 与知识空间 / 频道一样：`ref.save()` 挂进首页现有保存按钮。
  - B. 工作流那种侧栏 Sheet + 面板内保存。
- **选定**：A。
- **原因**：PRD 入口是首页最下方折叠面板，首页已经有保存。知识空间、频道已经是这套，校验失败则整页不写。工作流 Sheet 是按**单个应用**配的，这里是租户策略。
- **何时该重新考虑**：词表要和工作台其它字段解耦、分开权限。

---

## 4. 系统现状与改造后数据流

### 4.1 今天（缺口）

```
管理后台首页 DailyChatConfig
  → 只保存 workstation JSON（欢迎语 / 模型 / 工具 / 技能入口…）
  → 没有内容安全面板

知识空间 / 频道页
  → KnowledgeSpaceSensitivePolicy / SubscriptionSensitivePolicy
  → GET/PUT /api/v1/sensitive-word-policies/{knowledge_space_file_parse|channel_article}

工作流 / 助手（商业版）
  → FlowSetting / AssistantSetting → Gateway /api/sensitive/*
  → 过滤器拦 /process 与助手 completions

日常 / 任务
  POST /workstation/chat/completions
    → stream_chat_completion
         ├─ task_mode → _task_mode_stream_completion → submit_user_question → handoff
         └─ 日常 → _agent_stream_chat_completion → LLM astream → agent_answer
  遗留 POST /linsight/workbench/submit → 同样 submit_user_question
  全程无 check_text
```

可复用、不要重写：

| 模块 | 路径 | 用途 |
|------|------|------|
| 策略表 / DAO | `sensitive_word/domain/models/sensitive_word_policy.py` | 租户 + `business_type` 唯一行 |
| AC 匹配 | `SensitiveWordPolicyService.check_text` | 内置 `words.txt` ∪ 自定义；默认大小写不敏感 |
| 配置 API | `GET/PUT /api/v1/sensitive-word-policies/{business_type}` | 已按枚举路由，加枚举值即通 |
| 面板样板 | `KnowledgeSpaceSensitivePolicy.tsx` + 工作流 `FormSet.tsx` | 词表多选、txt 上传、自动回复、500 字 |
| 商业开关 | `env.pro` / `appConfig.isPro` | 与工作流审查入口同一套 |
| 输出覆盖 | `useAiChatSSE` 的 `agent_answer/end` | `message.msg` 覆盖整段回答 |

### 4.2 改造后：配置

```
构建 → 工作台 → 首页（商业版）
  → WorkbenchSensitivePolicy（页面最底部，RecommendedApps 之下）
  → GET/PUT /api/v1/sensitive-word-policies/workbench_chat
  → sensitive_word_policy 一行
       tenant_id + business_type=workbench_chat + scope=tenant
```

面板字段对齐 PRD，并与知识空间面板同一交互：

- 开关 `enabled`
- 词表类型多选：内置 / 自定义
- 自定义文本框 +「txt 文件」
- 自动回复（知识空间面板现在没有这一项，工作流 FormSet 有；本面板要有）
- 关闭时仍提交当前词表和自动回复，只把 `enabled=false`（AC-06）

首页 `handleSave`：先 `sensitivePolicyRef.save()`，失败则不写工作台 JSON。

### 4.3 改造后：日常输入

```
POST /workstation/chat/completions  (task_mode=false)
  → 商业版且策略生效？
       否 → 现有 _agent_stream_chat_completion
       是 → check_text(tenant, workbench_chat, data.text)
              命中 → 初始化会话 + 写入用户句 + 写入助手自动回复
                    → SSE：created → agent_answer/end(msg=auto_reply, events=[text]) → 关流
                    → 不创建 LLM、不跑工具
              未命中 → 现有链路
```

挂点建议在 `_agent_initialize_chat` **之前**（或 initialize 之后立刻、调 LLM 之前）。今天 initialize 就会插用户行；命中时也需要用户行，所以可以走同一 initialize，然后**跳过** agent 循环，只 persist 自动回复并短流结束。

### 4.4 改造后：日常输出（100 字）

在 `_agent_stream_chat_completion` 里，**两处**往 `final_msg` 追加正文的循环都要接扫描器（有工具的 `astream_events` 和无工具的 `bisheng_llm.astream`）。不要只改一处。

```
scanner = StreamContentSafetyScanner(tenant, workbench_chat)
每追加一段最终回答 delta:
    final_msg += delta
    照常 yield agent_answer/stream   # 决策 4：先画再审
    if scanner.should_check(len(final_msg)):      # 距上次 ≥ 100
        if check_text(final_msg).hits:
            停消费 LLM
            final_msg = auto_reply
            events 里的 text 全部换成一句 auto_reply（思考/工具事件丢掉，避免历史里还挂着半截）
            persist agent_answer = {msg: auto_reply, events: [{type:text, content: auto_reply}]}
            extra 可带 {content_safety: true} 便于以后排查，不要写命中词
            yield agent_answer/end(msg=auto_reply, events=...)
            结束 generator
流正常结束:
    余量再 check_text 一次（不足 100 字也会命中）
```

`should_check`：对**全文**做 AC，不是对新增窗口。100 只是**触发频率**。

思考过程 `reasoning_content` 继续只进 `agent_thinking`，不进 scanner。

### 4.5 改造后：任务输入

两条入口都要在 `submit_user_question` **之前**拦截：

1. `stream_chat_completion` → `_task_mode_stream_completion`（F035 统一入口，主路径）
2. `POST /linsight/workbench/submit`（遗留）

```
check_text(question)
  命中 → 不调用 submit_user_question / enqueue / persist_task_turn
        若尚无会话：只建日常会话（flow_type 仍是工作台会话），写入用户句 + 助手自动回复
        SSE：与日常输入命中相同（created + agent_answer/end），禁止 linsight_task_handoff
  未命中 → 现有 submit + handoff
```

前端：`onTaskHandoff` 不会被调用；占位助手气泡走 `agent_answer/end` 填上自动回复；`safeEnd` 在流关闭时解开发送按钮。**不必为命中单独加 SSE 事件名**，但 `useAiChat.ts` 里 task 发送不要假设「这次 SSE 一定有 handoff」——没有 handoff 就是日常气泡结束（今天若服务端报错也已经是这条路）。实现时补一条：task 模式下收到 `agent_answer/end` 也要 `setIsStreaming(false)`（`safeEnd` 已做）。

### 4.6 关键数据结构

| 字段 / 结构 | 类型 / 格式 | 说明 | 谁消费 |
|---|---|---|---|
| `SensitiveWordBusinessType.WORKBENCH_CHAT` | `'workbench_chat'` | 新枚举值 | 策略 API、check_text |
| 策略行 | 现有表，无 DDL | `enabled` / `words_types` / `custom_words` / `auto_reply` | 管理后台、运行时 |
| 用户输入 | `APIChatCompletion.text` | 只审这个字符串 | 日常+任务 |
| 最终回答 | `final_msg: str` | 只累积 `agent_answer` 正文 | 日常输出扫描 |
| SSE 命中结束 | 现有 `agent_answer` + `type=end` | `message.msg` = 自动回复 | `useAiChatSSE` |
| 落库 `ChatMessage` | `category=agent_answer` | `{msg, events:[{type:text, content}]}` | 历史 / 导出 |
| 本类型默认自动回复 | 与知识空间默认**分开** | 知识空间默认是「上传内容命中…」；工作台用 PRD 示例句，仅当库中 `auto_reply` 为空时回退 | `default_response` 按 business_type 分支 |

前端常量：`WORKBENCH_CHAT_POLICY = "workbench_chat"` 加到 `sensitiveWordPolicy.ts`。

### 4.7 模块职责

| 模块 / 文件 | 职责 | 不做什么 |
|---|---|---|
| `sensitive_word/domain/schemas.py` | 增加 `WORKBENCH_CHAT` | 不感知聊天 SSE |
| `SensitiveWordPolicyService` | 按类型给默认自动回复；`enabled` 时校验词表+回复（至少本类型） | 不读 ChatMessage |
| `StreamContentSafetyScanner`（新，放 `sensitive_word` 或 `workstation/chat_helpers`） | 记录上次审查的字数、是否该再审、命中则带 `auto_reply` | 不 yield SSE |
| `chat_service.stream_chat_completion` | 输入审查分流 | 不在 endpoint 里写匹配 |
| `_agent_stream_chat_completion` | 输出扫描 + 替换结束 | 不审思考/工具 |
| `_task_mode_stream_completion` + `submit_linsight_workbench` | 输入命中短路 | 不审任务执行输出 |
| `WorkbenchSensitivePolicy.tsx` | 首页面板；`isPro` 外层才挂载 | 不改知识空间/频道面板 |
| `bench/index.tsx` | 底部插入面板；保存时 `ref.save()` | 不把策略写入 workstation JSON |
| `useAiChatSSE.ts` | 原则上不改；`end.msg` 已覆盖 | 不要为命中再加 toast（PRD 是替换回答） |

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | 日常 SSE 不是 OpenAI `delta.content`，Gateway 现有过滤器帮不上忙 | 配了词表日常完全不审，或误伤思考过程 | 决策 1，挂在 `final_msg` |
| 2 | 有工具 / 无工具两条 LLM 循环都会写 `final_msg` | 只改一条，另一种对话绕过输出审查 | §4.4 两处都接 scanner |
| 3 | 任务统一入口命中后若仍发 `linsight_task_handoff` | 前端会创建任务并 `start-execute`，PRD「不创建任务」直接破 | §4.5 改走 `agent_answer/end` |
| 4 | 遗留 `/linsight/workbench/submit` 仍在 | 只拦 chat/completions，旧客户端或脚本绕过 | 两处入口都拦 |
| 5 | 只拿最近 100 字做匹配会漏掉跨窗口的词 | 「abc」在 99–101 字被拆开就不命中 | 每次审**全文**；100 只控制频率 |
| 6 | 流结束余量 < 100 也必须审 | 最后 80 字里的敏感词放行 | `finish()` 再 check 一次 |
| 7 | 知识空间默认自动回复是上传场景文案 | 工作台未填回复时用户看到「上传内容命中敏感词」 | 按 `business_type` 分默认句 |
| 8 | 首页 `ScopeBar` 是部门工作台配置继承；词表 API 是**租户**行 | 管理员以为按部门各配一份，其实全租户共用 | 文档写明；本期不做部门 scope |
| 9 | `aupsert` 在 `enabled=false` 时仍写入词表 | 这正是 AC-06；不要在关闭时清空 `custom_words` | 关闭只改 `enabled` |
| 10 | 开源环境 `BISHENG_PRO` 为 false | 只藏 UI 不够，API 仍可能被直接 PUT 出策略 | 运行时第一句判断 `bisheng_pro` |
| 11 | 输入命中若跳过 initialize | 新会话没有 `conversationId`，前端气泡对不上 | 命中也走会话初始化，只跳过 LLM |
| 12 | 输出命中后若把半截 `final_msg` 落库 | 刷新又能看到违规正文 | persist 前把 `msg/events` 换成自动回复 |
| 13 | 知识空间面板**没有**自动回复框，工作流 FormSet 有 | 复制知识空间组件会漏 PRD 字段 | 以 FormSet + 知识空间布局拼工作台面板 |
| 14 | `check_text` 在策略无效时 `enabled=False` 且 `hits=[]` | 不要把「未开启」当成命中 | 仅 `result.enabled and result.hits` 才拦截 |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 契约 | 形式 | 谁在用 |
|---|---|---|
| `GET/PUT /api/v1/sensitive-word-policies/workbench_chat` | 现有 HTTP，新枚举值 | platform 首页面板 |
| 日常/任务命中时的助手消息 | 现有 `agent_answer/end` SSE + 落库 | client `useAiChatSSE` |
| `SensitiveWordPolicyService.check_text(..., WORKBENCH_CHAT)` | 内部 Python | workstation / linsight 入口 |

不新增对外路径、不新增错误码段：配置校验失败用前端 toast（文案见 AC-05）；命中不是错误。后端 PUT 在 `enabled=true` 时应对本类型做与前端相同的校验（词表至少一项、自动回复非空且 ≤500），用现有 `resp_500` / 校验异常即可，避免只靠前端。

若校验要让前端按码分支，再在 `common/errcode` 给 `sensitive_word` 分一段；**本期默认不占新 MMM**，与知识空间策略保存一致。

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 风险点 |
|---|---|---|
| `sensitive_word_policy` 表与 AC 实现 | F036 已上线 | 改 `check_text` 语义会同时影响知识空间/频道 |
| `env.pro` / `BISHENG_PRO` | 现有商业开关 | 开关误关则整页不出现、运行时不审 |
| `agent_answer/end` 覆盖语义 | client SSE | 若以后 end 改为「只补 delta」，替换会失效，必须回归 |
| F035 任务 handoff | `linsight_task_handoff` | 命中路径不得发该事件 |
| 工作台首页保存 | `DailyChatConfig` `handleSave` | 盲存保护（`is_fallback`）不要误伤策略 PUT |

### 6.3 版本契约登记

- 表 1：无新领域对象；本 Feature 拥有枚举值 `workbench_chat` 的写入与日常/任务挂线。
- 表 3：依赖既有 sensitive_word 与工作台聊天入口。
- 不新增 INV；不新增错误码模块。

---

## 7. 测试与可观测

- **单元**：`check_text` 对 `workbench_chat` 的启用/关闭/空词表；scanner 在 99/100/101 字与跨窗口词、余量命中。
- **服务**：mock 策略后打 `stream_chat_completion`：日常输入命中不调 LLM；日常输出在第 100 字命中则 end 为自动回复且 DB 无模型正文；`task_mode` 命中无 handoff、无 `LinsightSessionVersion`；`/workbench/submit` 同样。
- **前端**：`isPro=false` 不渲染面板；开启保存三项校验；关闭再开配置还在。
- **手动（商业版）**：首页打开审查 → 内置或自定义词 → 日常输入命中词 → 只看到自动回复；日常诱导模型输出该词 → 流中途被替换；任务输入命中 → 无任务气泡 / 无排队。
- **日志**：命中打 `warning` 级别，带 `tenant_id`、`mode=input|output`、`chat_id`，不带原文和词。

---

## 8. 后续改进 / 不打算做的事

- 任务模式输出审查、文件/解析审查、模型审查：PRD 明确本期不做。
- 命中审计表、工作台日志「是否命中」列：需要产品另开。
- 先缓冲再下发以做到零泄漏：与「流式体验」权衡后再改决策 4。
- 抽公共 `SensitivePolicyPanel` 合并知识空间/频道/工作台三份 UI：本期先复制改，避免顺手重构频道/知识空间。
- 部门级词表：与首页 ScopeBar 对齐要改 `scope_type`，不是加个 JSON 字段能完事。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-09-09 | 初版实现方案 | 将《3.0 beta2》§5.2 改写为可施工设计 |
