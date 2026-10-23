# Tasks: 日常模式与任务模式内容安全审查（F063）

**关联规格**: [spec.md](./spec.md) · **设计真相**: [design.md](./design.md)
**版本**: v3.0.0-beta1

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 用户 2026-09-09 确认 |
| design.md | ✅ 已评审 | 用户 2026-09-09 确认；接手时的第一入口 |
| tasks.md | ✅ 已拆解 | 16 个任务 / 6 个 Wave；AC-01～AC-15 全部有测试或手动验证覆盖 |
| 实现 | ✅ 编码完成 | 16 / 16；后端单测已绿。Platform 面板 / Client 流式命中需商业版手动验证（T013–T015） |

---

## 开发模式

- **后端 Test-First**：测试任务在实现任务之前；实现任务的「测试」字段写明要转绿的用例。
- **前端手动验证**：Platform 与 Client **分任务**。配置 UI 无 Playwright（与知识空间面板同类）→ T013 标测试降级。
- **无 DDL、无新错误码、无新对外路径**。复用 `GET/PUT /api/v1/sensitive-word-policies/{business_type}`；命中走现有 `agent_answer/end`。
- **自包含**：任务内联文件与逻辑；**为什么这么做指向 design §3 决策编号，不复制论证**。
- **共享文件**：`sensitive_word_policy_service.py` / `chat_service.py` 只做增量，禁止改知识空间 / 频道 / Gateway 审查语义。
- **禁止**把词表写入 workstation JSON、禁止发 `linsight_task_handoff` 作为命中响应、禁止把命中词/用户原文打进 info 日志。

---

## Tasks

### Wave 1 — 无依赖，可并行（枚举 + i18n）

- [x] **T001**: 新增 `workbench_chat` 业务类型
  **文件**: `src/backend/bisheng/sensitive_word/domain/schemas.py`
  **逻辑**: `SensitiveWordBusinessType` 增加 `WORKBENCH_CHAT = 'workbench_chat'`。不改表、不 Alembic（`business_type` 已是 `String(64)`）——**无 DDL，无需回滚**。既有 `knowledge_space_file_parse` / `channel_article` 取值一字不改。FastAPI 路由已按枚举路径参数工作，加值后 `GET/PUT .../workbench_chat` 即通。
  **设计依据**: design §3 决策 2 · §4.6
  **跨 Feature 影响**: 枚举被知识空间 / 频道策略 API 共用；只增量一个成员。
  **依赖**: 无

- [x] **T002**: Platform 工作台审查文案 i18n
  **文件**: `src/frontend/platform/public/locales/{zh-Hans,en-US,ja}/bs.json`
  **逻辑**: 在 `bench`（或现有 `build` 下与面板一致的命名空间）新增三语 key，**禁止硬编码中文**：①面板说明「通过敏感词表对会话内容进行安全审查」；②自定义词表占位「使用换行符进行分隔，每行一个」；③自动回复占位「填写命中安全审查时的自动回复内容，例如“当前对话内容违反相关规范，请修改后重新输入”」；④校验「请至少选择一个敏感词表」「自动回复内容不能为空」「自动回复内容不能超过500字」（AC-05 指定句，不要复用知识空间/工作流里措辞不同的旧 key）。`build.contentSecurityReview` / `build.builtinWordList` / `build.customWordList` / `build.txtFile` / `build.wordListType` 已存在则复用。组件接线在 T013。
  **覆盖 AC**: AC-01, AC-03, AC-04, AC-05
  **依赖**: 无

### Wave 2 — 策略默认值 / 校验 / 商业开关（Test-First）

- [x] **T003**: `workbench_chat` 策略服务单测
  **文件**: `src/backend/test/sensitive_word/test_workbench_chat_policy.py`
  **逻辑**: mock DAO / `bisheng_pro`。①`default_response(WORKBENCH_CHAT)` 的 `auto_reply` 是工作台示例句，**不是**知识空间「上传内容命中敏感词…」（design 坑 7）。②`KNOWLEDGE_SPACE_FILE_PARSE` 默认句不变。③`enabled=True` 且 `words_types=[]` 或 `auto_reply` 空白 / 超 500 字 → upsert 拒绝。④`enabled=False` 仍写入 `custom_words` 与 `auto_reply`（AC-06）。⑤`is_workbench_content_safety_active`：`bisheng_pro=False` 为 False（即使策略 enabled）；pro=True 且 `is_effective` 为 True 才 True。⑥`evaluate_workbench_user_text`：未激活或无 hits 返回 `None`；命中返回带 `auto_reply` 的 result。⑦`check_text(..., WORKBENCH_CHAT)` 命中走现有 AC 引擎（builtin ∪ custom）。⑧策略无效时 `enabled=False, hits=[]`，不得当命中（design 坑 14）。
  **覆盖 AC**: AC-02, AC-05, AC-06, AC-07, AC-14
  **依赖**: T001

- [x] **T004**: 策略服务：分类型默认回复 + 开启校验 + 运行时开关
  **文件**: `src/backend/bisheng/sensitive_word/domain/services/sensitive_word_policy_service.py`
  **逻辑**: `default_response` / `to_response` 按 `business_type` 选默认 `auto_reply`（工作台用 PRD 示例句）。`aupsert_policy` 在 `business_type=workbench_chat` 且 `enabled=True` 时校验：`words_types` 至少一项、`auto_reply` 去空白后非空、长度 ≤500；失败用现有 `resp_500` / 校验异常，**不新开错误码模块**。关闭时不校验、不清空词表。新增 `is_workbench_content_safety_active(tenant_id)`：先读 `settings.get_system_login_method().bisheng_pro`，再 `is_effective(..., WORKBENCH_CHAT)`。新增 `evaluate_workbench_user_text(tenant_id, text) -> Optional[CheckResult]`：未激活或无 hits 返回 `None`，命中返回 result（仅 `enabled and hits`）。放在本 Service 是为了让 workstation 与 linsight **两边都能调、不形成 workstation↔linsight 循环 import**。不改 `check_text` 匹配算法。
  **设计依据**: design §3 决策 1 / 决策 2 · §5 坑 7、9、10、14
  **跨 Feature 影响**: 知识空间 / 频道 upsert 不走本类型校验；其默认回复不得被改掉。
  **测试**: T003 全绿；`test/sensitive_word/test_sensitive_word_policy_service.py` 仍全绿
  **覆盖 AC**: AC-02, AC-05, AC-06, AC-07, AC-14
  **依赖**: T001, T003

### Wave 3 — 流式全文扫描器（Test-First）

- [x] **T005**: `StreamContentSafetyScanner` 单测
  **文件**: `src/backend/test/sensitive_word/test_stream_scanner.py`
  **逻辑**: mock `check_text`。①累积 99 字不调用检查；第 100 字调用一次，参数是**全文**不是窗口。②第 101 字不立即再调；满 200 再调。③词跨 99–101 边界：喂「x」*99 + 敏感词首字，再喂剩余，第 100 字那次检查能命中（design 坑 5）。④`finish()` 对余量 <100 再检查一次（design 坑 6）。⑤`feed` 只接受最终回答 delta；本测试不把 thinking 喂进去（护栏：thinking 字符串不含敏感词时即使模型思考里有词也不该被本 scanner 看到——由 T009 保证调用点）。⑥命中后返回 `auto_reply`，不再 feed。
  **覆盖 AC**: AC-10
  **依赖**: T001

- [x] **T006**: 实现 `StreamContentSafetyScanner`
  **文件**: `src/backend/bisheng/sensitive_word/domain/services/stream_scanner.py`
  **逻辑**: 新文件。构造传入 `tenant_id` + `WORKBENCH_CHAT`。`feed(delta) -> Optional[CheckResult]`：追加到内部 buffer，`len(buffer) - last_checked >= 100` 时对 **buffer 全文** `check_text`；命中（`enabled and hits`）则返回 result。`finish() -> Optional[CheckResult]` 再审一次余量。字数用 `len(str)`（Unicode 码点）。本文件不 yield SSE、不读 ChatMessage。
  **设计依据**: design §4.4 · §5 坑 5、6
  **测试**: T005 全绿
  **覆盖 AC**: AC-10
  **依赖**: T004, T005

### Wave 4 — 日常输入拦截（Test-First）

- [x] **T007**: 日常输入命中 / 不审文件 单测
  **文件**: `src/backend/test/workstation/test_workbench_content_safety_input.py`
  **逻辑**: mock `evaluate_workbench_user_text` / LLM。①`text` 命中：不调用 LLM / agent 循环；SSE 含 `agent_answer` + `end` 且 `msg=auto_reply`；**没有** `linsight_task_handoff`；落库用户句 + `category=agent_answer` 的 `{msg, events:[{type:text, content: auto_reply}]}`（AC-15）。②`text` 为空但 `files` 非空：不因文件名/内容拦截（AC-11）。③`evaluate` 返回 None（含未开 pro）：不拦，进入现有 agent 初始化。
  **覆盖 AC**: AC-02, AC-08, AC-11, AC-15
  **依赖**: T004

- [x] **T008**: 日常入口：输入命中则跳过 LLM 并短流结束
  **文件**: `src/backend/bisheng/workstation/domain/services/chat_service.py`；若短流/落库不宜内联，第二文件放 `src/backend/bisheng/workstation/domain/services/content_safety.py`（`evaluate` + `blocked_answer_payload`），**禁止**第三文件。
  **逻辑**: `_agent_stream_chat_completion` 在调 LLM **之前**调用 T004 的 `evaluate_workbench_user_text(tenant_id, data.text)`（只审 `text`，不读 `files`）。命中则仍走会话 initialize（写入用户行，design 坑 11），然后 persist 自动回复、yield `created` + `agent_answer/end`、关流。日志 `warning` 只带 `tenant_id` / `mode=input` / `chat_id`，**不带原文和词**。本任务**不**接输出扫描（T010）。日常短流助手若抽到 `content_safety.py`，只放 SSE/落库，**不要**把 `evaluate` 再包一层（linsight 必须直接调 T004，避免循环 import）。
  **设计依据**: design §3 决策 3 · §4.3 · §5 坑 11、14
  **跨 Feature 影响**: `chat_service.py` 是日常统一入口；未命中分支零行为变化。
  **测试**: T007 全绿
  **覆盖 AC**: AC-02, AC-08, AC-11, AC-15
  **依赖**: T004, T007

### Wave 5 — 日常输出扫描（Test-First）

- [x] **T009**: 日常输出 100 字命中 / 只审最终回答 单测
  **文件**: `src/backend/test/workstation/test_workbench_content_safety_output.py`
  **逻辑**: mock scanner / `check_text`。①最终回答累积到 100 字命中：停止后续 token；SSE 最后一条 `agent_answer/end` 的 `msg` 为自动回复；落库 `msg` **不含**已流出的模型正文（AC-15 / 坑 12）。②思考 / tool 文本含敏感词、最终回答不含 → 不替换。③流结束余量 <100 命中 → 同样替换。④有工具 `astream_events` 与无工具 `bisheng_llm.astream` **两条**循环都要能触发（可分两个用例，mock 不同分支）。
  **覆盖 AC**: AC-09, AC-10, AC-15
  **依赖**: T006, T008

- [x] **T010**: 两条 LLM 循环都接 scanner，命中则替换并落库
  **文件**: `src/backend/bisheng/workstation/domain/services/chat_service.py`
  **逻辑**: `_agent_stream_chat_completion` 内，仅当 `is_workbench_content_safety_active` 时构造 `StreamContentSafetyScanner`。**两处**向 `final_msg` 追加最终回答 delta 之后：`feed(delta)`；照常 yield `agent_answer/stream`（决策 4）；命中则停消费 LLM，把 `final_msg` / text events 换成自动回复（丢掉思考/工具事件），persist 后 yield `end` 并 return。流正常结束调 `finish()`。`reasoning_content` 只进 thinking，不 `feed`。`extra` 可 `{content_safety: true}`，不要写命中词。
  **设计依据**: design §3 决策 4 · §4.4 · §5 坑 2、12
  **跨 Feature 影响**: 只增量日常 agent 循环；知识空间 / 频道问答入口不改。
  **测试**: T009 全绿；T007 仍全绿
  **覆盖 AC**: AC-09, AC-10, AC-15
  **依赖**: T006, T009

### Wave 6 — 任务输入拦截（Test-First）

- [x] **T011**: 任务输入命中：无 handoff、无 session_version 单测
  **文件**: `src/backend/test/linsight/test_workbench_content_safety_task.py`
  **逻辑**: ①`task_mode=True` 走 `stream_chat_completion`：`text` 命中则 **不**调用 `submit_user_question` / `enqueue_session_for_execution`；SSE **没有** `linsight_task_handoff`，有 `agent_answer/end` + 自动回复；落库助手行同日常（AC-15）。②遗留 `submit_linsight_workbench`：`question` 命中同样不创建 `LinsightSessionVersion`，SSE 不是 workbench_submit 成功事件。③未命中：仍 submit（可 assert mock 被调用）。④本文件不把 scanner 接到 task_exec——任务执行输出不审（AC-13）。
  **覆盖 AC**: AC-07, AC-12, AC-13, AC-15
  **依赖**: T004, T008

- [x] **T012**: 统一入口 + 遗留 submit 在创建任务前拦截
  **文件**: `src/backend/bisheng/workstation/domain/services/chat_service.py`, `src/backend/bisheng/linsight/api/endpoints/linsight.py`
  **逻辑**: `_task_mode_stream_completion` 在 `submit_user_question` **之前**对 `data.text` 调 T004 `evaluate_workbench_user_text`；命中则复用 T008 的日常短流（会话 + `agent_answer/end`），**禁止** yield `linsight_task_handoff`（design 坑 3）。`submit_linsight_workbench` 同样在 submit 前调 **同一个** T004 evaluate（坑 4，禁止从 workstation 反 import）；命中用该端点现有 `EventSourceResponse` 返回自动回复（可以是一条业务事件或 typed error，但必须让客户端结束请求），**不**建 `LinsightSessionVersion`。不审任务执行输出，**不改** `task_exec.py`。
  **设计依据**: design §3 决策 3 · §4.5 · §5 坑 3、4
  **跨 Feature 影响**: linsight 执行 / worker 不改；未命中 handoff 契约不变。
  **测试**: T011 全绿
  **覆盖 AC**: AC-07, AC-12, AC-13, AC-15
  **依赖**: T008, T011

### Wave 7 — 前端 Platform（配置面板）

- [x] **T013**: `WorkbenchSensitivePolicy` 面板
  **文件**: `src/frontend/platform/src/pages/BuildPage/bench/WorkbenchSensitivePolicy.tsx`, `src/frontend/platform/src/controllers/API/sensitiveWordPolicy.ts`
  **逻辑**: 常量 `WORKBENCH_CHAT_POLICY = "workbench_chat"`。新组件对齐知识空间面板布局 + 工作流 `FormSet` 的自动回复框（design 坑 13：不要直接复制知识空间而漏自动回复）。开关、词表多选、自定义文本框、txt 上传（换行/逗号/空格）、自动回复 `maxLength={500}`。`save()`：未加载完则报错返回 false；`enabled=true` 时三项校验用 T002 的 AC-05 key；`enabled=false` 仍 PUT 当前词表和回复。不把策略写入 workstation JSON。不改 `KnowledgeSpaceSensitivePolicy` / `SubscriptionSensitivePolicy`。
  **测试降级**: 配置 UI 依赖管理员登录 + `isPro`，Playwright 未覆盖构建页此类折叠面板（与 F036 知识空间面板同一缺口）；本任务以手动验证覆盖 AC-01 / AC-03 / AC-04，校验逻辑后端已由 T003 锁死。
  **设计依据**: design §3 决策 5 · §4.2 · §5 坑 8、9、13
  **覆盖 AC**: AC-01, AC-03, AC-04, AC-05, AC-06, AC-07
  **手动验证**:
  - 商业版打开 http://localhost:3001 构建 → 工作台 → 首页，最下方看到「内容安全审查」及说明文案
  - 开启后不选词表 / 空自动回复 / 超过 500 字保存，分别出现 AC-05 三句提示且不写入
  - 关闭后再开启，词表和自动回复还在
  **依赖**: T002, T004

- [x] **T014**: 首页挂载面板：仅 `isPro`，保存走 `ref.save()`
  **文件**: `src/frontend/platform/src/pages/BuildPage/bench/index.tsx`
  **逻辑**: `locationContext.appConfig.isPro` 为真时，在 `RecommendedAppsConfig` **之下**渲染 `WorkbenchSensitivePolicy`。`handleSave` 先 `await sensitivePolicyRef.save()`，false 则不写工作台 JSON（不要绕过现有 `confirmBlindOverwrite`）。`isPro` 为假不挂载。不要把词表字段并进 `ChatConfigForm`。
  **设计依据**: design §3 决策 5 · §4.2 · §5 坑 8、10
  **覆盖 AC**: AC-01, AC-02
  **手动验证**:
  - 开源 / `isPro=false`：首页无该面板
  - 商业版：面板在推荐应用下方；点页面保存会带上策略 PUT
  **依赖**: T013

### Wave 8 — 前端 Client + 收口

- [x] **T015**: Client 命中展示确认（原则上不改协议）
  **文件**: `src/frontend/client/src/hooks/useAiChatSSE.ts`
  **逻辑**: 只读确认 `agent_answer/end` 已用 `message.msg` 覆盖 `responseText` 且可替换 `events`（决策 4）。禁止新增 toast、禁止新 SSE 事件名。本任务范围内允许的唯一改动：若无 handoff 的 task 发送关流后按钮仍卡住，在本文件或 `useAiChat.ts` 于 `end`/关流时 `setIsStreaming(false)`——这是本任务要做完的事，不是延后 TODO。
  **覆盖 AC**: AC-08, AC-09, AC-12, AC-15
  **手动验证**:
  - 打开 http://localhost:4001/workspace ，策略开启后：日常输入命中词 → 助手气泡为自动回复、无模型续写
  - 日常诱导模型输出该词 → 流中途气泡被换成自动回复；刷新后历史仍是自动回复不是半截模型字
  - 任务模式输入命中 → **没有**任务卡片 / 排队 / start-execute，助手气泡为自动回复，发送按钮恢复
  **依赖**: T008, T010, T012

- [x] **T016**: 回归重跑 + 端到端手动验证 + 落档
  **文件**: 本文件「实际偏差记录」段
  **逻辑**: ①重跑 `test/sensitive_word/test_sensitive_word_policy_service.py`、T003 / T005 / T007 / T009 / T011。②确认 `task_exec.py` 无 `sensitive_word` / scanner 引用（AC-13）。③按 design §7：商业版配词 → 日常输入 / 日常输出 / 任务输入；开源不展示不审查；只传文件不拦。④实现期改变系统认知的偏差回写 design，此处只留一行指针。
  **覆盖 AC**: AC-02, AC-13, AC-14
  **依赖**: T014, T015

---

## AC 覆盖对照

| AC | 覆盖任务 |
|----|----------|
| AC-01 | T002, T013, T014 |
| AC-02 | T003, T004, T007, T008, T014, T016 |
| AC-03 | T002, T013 |
| AC-04 | T002, T013 |
| AC-05 | T002, T003, T004, T013 |
| AC-06 | T003, T004, T013 |
| AC-07 | T001, T003, T004, T011, T012, T013 |
| AC-08 | T007, T008, T015 |
| AC-09 | T009, T010, T015 |
| AC-10 | T005, T006, T009, T010 |
| AC-11 | T007, T008 |
| AC-12 | T011, T012, T015 |
| AC-13 | T011, T012, T016 |
| AC-14 | T003, T004, T016 |
| AC-15 | T007, T008, T009, T010, T011, T012, T015 |

---

## 实际偏差记录

> **只留一行指针**，论证写进 design.md（决策 / 坑），这里不重复。
> 推翻已 ★ 确认的决策时，先停下与用户重新确认，再记录。

- 商业开关 `_is_bisheng_pro` 直接读 `BISHENG_PRO`（与 `get_system_login_method().bisheng_pro` 同源）；页面保存时策略 PUT 在 `confirmBlindOverwrite` 之后、写 workstation JSON 之前。论证见 design §3 决策 5。
