# Design: 工作台会话回答级导出 + 导入到知识空间（F028）

> **本文档定位 — 现状快照（Why this How）**
>
> - spec.md 回答 **做什么**（目标、31 条 AC、边界）
> - design.md（本文）回答 **为什么这么实现**：关键决策、运行时不直观的事实、对外契约
> - tasks.md 是 **流水账**：拆了哪些任务、做了什么改动
>
> 实现变化触发的更新规则：触及"系统认知"（数据模型/接口契约/配对逻辑/依赖格式）必须**覆盖更新本文档**，
> 同时在 tasks.md「实际偏差记录」追加一笔。

**关联**: [spec.md](./spec.md) · [tasks.md](./tasks.md) · [e2e-checklist.md](./e2e-checklist.md)
**版本**: v2.6.0-beta3
**最后更新**: 2026-06-02（PDF 引擎从 libreoffice 切到 chromium/playwright）

---

## 1. 目标与非目标

- **目标**：用户在工作台聊天页面，按"对话轮次"勾选问答对，导出成 docx / pdf / md / txt，或直接导入到已选的知识空间作为可被检索的资料。
- **非目标**：
  - 不导出未发送 / 撤回 / 编辑历史
  - 不做异步导出队列（同步返回文件流即可，单次最多 N 轮）
  - 不在导出时做语义抽取或摘要（原文导出）
  - 不支持跨会话拼接（只导出当前一条会话的选中轮次）

---

## 2. 关键约束

- **双 DB 兼容**（CLAUDE.md §3.2）：本 feature 取数走现有 chat 消息表，无新 DDL，天然兼容
- **多租户**（CLAUDE.md §3.3）：取数依赖现有 `chat_message` 表的 tenant 自动注入，无需手动 WHERE
- **权限**（CLAUDE.md §3.4）：导入到知识空间走 `PermissionService.check` + 写 OpenFGA owner 元组，复用现有 add_file 路径
- **依赖**：服务端必须有 `pandoc`（系统二进制）+ `pypandoc`（Python 包，docx 路径）+ `playwright` / chromium binary（pdf 路径，md→html→pdf）+ `python-markdown`
- **错误码段**：120**20-12069** 段分配给本 feature，定义在 `common/errcode/workstation.py`

---

## 3. 方案对比与选定

### 决策 1：消息配对策略 — 数组位置 vs parentMessageId

- **备选**：
  - A. 用 `parentMessageId` 字段配对（业界常见做法，按父子关系）
  - B. 按消息数组位置配对（assistant 的前一条 user 就是它的配对）
- **选定**：**B**
- **原因**：实测工作台运行时 `parentMessageId` 一直是空串，无法用来配对。前端消息流是有序的，按位置配对在所有运行时分支上都成立。
- **何时该重新考虑**：上游 chat 模块给 `parentMessageId` 落地真实值（届时 B 仍能工作，但 A 更语义化、能支持分支会话）

### 决策 2：用户 query 字段的形态 — 平文本 vs JSON envelope

- **备选**：
  - A. 把 `query` 当成纯文本字段直接取
  - B. 兜底把 `query` 当作 JSON envelope 解包
- **选定**：**B（必须解包）**
- **原因**：实测两种运行时下 `query` 都是 JSON 包裹：
  - 日常模式 `{"query": "<text>", "files": []}`
  - 工作流模式 `{"data": {...}, "input": "<text>"}`
  - 平文本读会拿到带 `{...}` 的乱码
- **何时该重新考虑**：上游 chat 统一改为平文本（届时把 `_extract_query_text` 简化为直读）

### 决策 3：assistant 答案文本来源 — agent_answer.msg vs events[]

- **备选**：
  - A. 只读 `agent_answer.msg`
  - B. `msg` 空时回退到 `events[type=text]`
- **选定**：**B（必须兜底）**
- **原因**：v2.5 agent-native 格式下 `msg` 可能为空，正文文本只存在于 `events[]` 数组中（每个 chunk 一个事件）。工作流 OUTPUT 节点 `output_type=text` 也走 events。如果不兜底，导出空答复 + RAG 角标残留（因为 strip 拿不到文本）。
- **何时该重新考虑**：agent-native 格式统一回写 `msg` 字段后

### 决策 4：导出执行 — 同步流式返回 vs 异步任务

- **备选**：
  - A. 同步：HTTP POST 直接返文件流（docx/pdf/md/txt）
  - B. 异步：Celery 任务 + 回调 URL 下载
- **选定**：**A**
- **原因**：单次导出体量小（最多 N 轮 + 若干图片），渲染 < 30s 可接受；同步实现简单、用户体验好、无状态。
- **何时该重新考虑**：单次导出范围放开到整个会话或多会话拼接、平均耗时 > 30s、渲染进程阻塞 worker
- **注**：PDF 渲染引擎已从 libreoffice 改为 chromium（见决策 6）；本决策只关乎同步 vs 异步，与引擎无关。

### 决策 5：知识空间下拉数据源 — 复用 list vs 新增 uploadable 端点

- **备选**：
  - A. 复用现有知识空间列表接口，前端过滤
  - B. 新增 `GET /api/v1/knowledge/space/uploadable` 专用端点，后端按"可上传文件类型"过滤
- **选定**：**B**
- **原因**：可上传性不只是 read 权限，还涉及空间类型（QA / 文件库）/ 文件格式白名单，过滤逻辑放后端更稳。复用 `AddToKnowledgeModal` 加 `dataSourceApi` prop 切换数据源即可。
- **何时该重新考虑**：知识空间类型扩展或前端需要更多元数据

### 决策 6：PDF 渲染引擎 — libreoffice vs chromium(playwright)

- **备选**：
  - A. docx → libreoffice 子进程 → pdf（复用 docx 渲染产物）
  - B. md → html → chromium(playwright) → pdf（绕开 docx）
- **选定**：**B（改用 chromium）**
- **原因**：实测真实数据下，libreoffice 解析 pandoc 生成的 docx 时表格 / 列表布局崩塌，排版不可用。直接 md→html→chromium 打印 pdf，绕开 docx 中间产物，布局可控。
- **何时该重新考虑**：pandoc/libreoffice 的 docx 排版兼容性显著改善，或需要 docx 与 pdf 完全像素一致

---

## 4. 系统现状（接手必读）

### 4.1 数据流

```
工作台聊天页面
  ↓ 用户勾选轮次
前端 useMessageSelection (Recoil store)
  ↓ POST /api/v1/chat/messages/export 或 /import-to-knowledge
后端 conversation_export endpoint
  ↓
ConversationExportService.export_messages()
  ├─ 取数：chat_message 表（按 chat_id + 选中 message_id 列表）
  ├─ 配对：_pair_user_assistant（按数组位置）
  ├─ 抽文本：_extract_query_text（unwrap JSON） + _extract_answer_text（msg + events 兜底）
  ├─ 预处理：图片预下载（httpx 并发 8，超时 5s）+ RAG 角标 strip
  ├─ 渲染：renderer 工厂（md/txt 直拼，docx 走 pypandoc + 模板，pdf 走 chromium(playwright)：md→html→pdf，绕开 docx）
  └─ 返回：StreamingResponse(file_bytes)
```

import-to-knowledge 路径相同，最后一步改为：渲染成 docx 临时文件 → 调用现有 `add_file` → 失败重试同名。

### 4.2 关键数据结构 / 字段约定

| 字段 / 结构 | 类型 / 格式 | 说明 | 谁会消费 |
|---|---|---|---|
| `chat_message.message` (user 行) | JSON envelope `{"query": str, "files": [...]}` 或 `{"data": {...}, "input": str}` | 用户输入；必须用 `_extract_query_text` 解包 | 导出、历史回放 |
| `chat_message.message` (assistant 行) | `{"msg": str, "events": [{"type": "text", "content": str}, ...]}` 等 | 答案；`msg` 空时回退 events | 导出、历史回放 |
| `POST /chat/messages/export` 请求 | `{chat_id, message_ids: int[], format: "docx"\|"pdf"\|"md"\|"txt"}` | 同步导出 | 前端 sheet 组件 |
| `POST /chat/messages/import-to-knowledge` 请求 | `{chat_id, message_ids: int[], knowledge_id: int, filename?: str}` | 同步导入 | 前端 sheet 组件 |
| `GET /knowledge/space/uploadable` 响应 | `PageData[KnowledgeSpaceItem]` | 过滤后的可写入空间列表 | `AddToKnowledgeModal` |
| 文件名约定 | `<会话标题>_<YYYYMMDD-HHmm>.<ext>` | 服务端生成；中英日字符已 escape | 浏览器下载 / add_file 入参 |

### 4.3 关键模块职责

| 模块 / 文件 | 职责 | 不做什么 |
|---|---|---|
| `workstation/api/endpoints/conversation_export.py` | HTTP 入口、auth、参数校验 | 不写业务逻辑 |
| `workstation/domain/services/conversation_export_service.py` (~950 行) | 取数 + 配对 + 文本抽取 + 渲染编排 | 不直接读 ORM 之外的存储（图片走 service 内 httpx） |
| `workstation/domain/services/conversation_export_renderers/*` | 4 个 renderer（md/txt/docx/pdf）+ 图片预处理 + 文件名生成；`_render_pdf` 走 chromium(playwright) md→html→pdf，docx 路径仍 pandoc + 模板 | 不取数据 |
| `workstation/assets/conversation_export_template.docx` | pypandoc reference doc，控制字体/段距/代码块样式 | 渲染脚本由 `scripts/gen_conversation_export_template.py` 再生 |
| 前端 `useMessageSelection.ts` + `messageSelectionStore.ts` | 选择态：意图驱动 + `computeSelectedIds` 实时算。三种意图：显式 `selectedIds`、`globalSelectAllOn`（全选）、`selectAllBelowAnchor`（全选以下，覆盖式；锚点为答案时 `computeSelectedIds` 用 `buildPairGroup` 补回上方关联问题） | 不发请求 |
| 前端 `Chat/MessageSelection/*` | UI：toolbar / checkbox（带 `data-message-id` 供锚点定位）/ sheet / `SelectAllBelowBanner`（常驻 sticky pill + 校准线，按滚动位置算锚点）/ export-button / Provider | 不取业务数据 |
| 前端 `pages/appChat/components/*` + `Chat/AiChatMessages` | 两个聊天入口（日常 vs 工作流/助手）的挂载点 | 各自独立的 chat 容器，不要重构合并 |

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | 工作台运行时 `parentMessageId` 始终为空串，不能用来配对消息 | 配对全错，按选中渲染时 user/assistant 错位 | `useMessageSelection.ts:buildPairGroup` 改用数组位置 |
| 2 | 用户 `query` 字段在所有运行时下都是 JSON envelope，需 unwrap | 导出"query"原文包含 `{...}` 串，看起来像乱码 | `_extract_query_text`（commit `4394ba524`） |
| 3 | v2.5 agent-native 格式下 `agent_answer.msg` 可能为空，正文只在 `events[type=text]` 数组里 | 导出空答复 + RAG 角标 `[^1]` 残留（strip 拿不到文本） | `_extract_answer_text` 兜底从 events 取，取出后必须重跑 `strip_rag_marks`（commit `4394ba524`） |
| 4 | 工作流 OUTPUT 节点 `output_type=text` 也走 events，不走 `msg` | 工作流场景导出空白 | 同 #3 |
| 5 | 第二次点击同一条消息要"取消选中"（不是再次选中） | 用户取消勾选不生效 | `useMessageSelection.ts` toggle 语义 |
| 6 | 图片预下载并发 8、超时 5s；失败的图片**保留原 URL** | 失败图片在文件里是裸链接 | `_prefetch_images`（design 取舍：宁可有链接，不要整次导出失败） |
| 7 | pandoc 默认要求 list 前有空行，否则列表不被识别 | md→html 列表渲染成普通段落 | 渲染时加 `+lists_without_preceding_blankline` extension |
| 8 | 有的来源把 PUA marker 字面化成 `` 这种 6 字符串（非真正的码点） | strip 漏掉，marker 残留在正文 | 兜底同时处理真实 PUA 码点和字面化的 6 字符串 |
| 9 | 兜底 strip 的 `\s*` 不能吃换行 | 吃掉 `ul` 项之间的分隔，多个列表项被粘连 | strip 正则用不含换行的空白类，别用 `\s*` |
| 10 | WenQuanYi / Liberation 字体没有 emoji 字形，docx 路径不会自动 fallback | docx 里 emoji 显示成豆腐块 | docx 路径预替换 emoji 为 `●`（chromium 路径不受影响） |
| 14 | 答案里的图片是 `/bisheng/knowledge/images/...` 根相对路径（前端 nginx 代理路径，后端无此代理）；且 MinIO 返回 `application/octet-stream` | docx/pdf 渲染时图片抓不到(被当不支持 scheme 丢)或扩展名猜成 `.bin` → pandoc 嵌不进 → docx 无图（txt/md 只输出链接文本不受影响） | `_fetch_image_bytes` 相对路径补 `get_minio_share_host()` 再抓；content-type 为泛型时用 URL 后缀兜底扩展名 |
| 13 | 平台 `process_one_file` 按**内容 md5/文件名**去重(重复内容→旧文件标 FAILED、不新建);F028 的 `(1)` 改名是文件名级,绕不过 md5 内容去重 | 重导同一会话内容一致 → md5 命中 → 被当重复拒收，知识空间"只看到一份"，`(1)` 永不出现 | F028 导入给 `add_file`/`process_one_file` 传 `skip_dedup=True` 强制新建（已用 `_resolve_unique_filename` 保证文件名唯一） |
| 12 | 工作流/助手答案落库 category 是 `stream_msg`/`output_msg`（文本在 JSON `msg` 字段），QA 答案是 `{"content":...}`，工作流提问是 `is_bot=1` 的纯字符串 | 后端 `_extract_answer_text` 旧版只认 `answer`/`agent_answer` → 工作流/助手导出**答案整块空** | `_extract_answer_text` 统一处理 `stream_msg`/`output_msg`/`agent_answer`（取 msg+events）+ `{"content"}` + 纯字符串，丢弃 `reasoning_answer`/`input`/thinking/tool |
| 11 | **实时会话中前端消息 id 是临时值，不是真实 DB 主键**：daily 路径提问消息曾被钉死成临时 UUID（`useAiChat.onCreated` 用 `messageId: userMessageId` 覆盖了 `created` 事件带回的真实 id）；workflow 路径答案消息在 `end` 缺 `message_id` 时保留合成 id `unique_id+output_key` | 导出按 `parseInt(messageId)` 取整数 id：UUID→NaN 被丢（提问整轮丢失，导出只剩答案）；纯数字合成 id→发出去后端查无此 id 报 12060「消息不存在」。刷新后走历史接口才映射成真实 id，所以"刷新后正确" | daily：`useAiChat.onCreated` 改为用 `created` 事件的真实 `messageId` 回填，`onFinal` 同步按真实 id 匹配。workflow 路径同类问题（answer 合成 id）尚未修，见 §8 短板 |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 契约 | 形式 | 谁在用 |
|---|---|---|
| `POST /api/v1/chat/messages/export` | HTTP（同步返文件流） | 前端 chat sheet |
| `POST /api/v1/chat/messages/import-to-knowledge` | HTTP（同步返 add_file 结果） | 前端 chat sheet |
| `GET /api/v1/knowledge/space/uploadable` | HTTP `PageData[KnowledgeSpaceItem]` | `AddToKnowledgeModal`（复用，dataSourceApi prop） |
| `ConversationExportService.export_messages(...)` | 内部 Python API | 仅 endpoint 调用，暂无其他 service |
| 错误码 12060-12069 | 5 位 MMMEE | 前端 toast / e2e 断言 |
| 导出文件命名规则 `<标题>_<YYYYMMDD-HHmm>.<ext>` | 隐式契约 | 前端展示、用户文件管理 |

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 风险点 |
|---|---|---|
| `chat_message` 表 schema | 直接 ORM 读 | 若 chat 模块改 `message` 字段格式（如把 envelope 改成平文本、或把 events 整合进 msg），F028 静默坏掉 |
| chat 消息 `query` 字段为 JSON envelope | 隐式数据契约 | 同上，需在 chat 改动 PR 中提前告知 |
| `agent_answer.events[type=text]` 作为答案文本兜底 | 隐式数据契约 | agent-native 格式重构会破坏；评估时必须检查本 feature 的 extractor |
| `add_file` 服务 | 内部 Python API | knowledge 模块若改 add_file 签名/语义，要同步本 feature |
| `pypandoc` + `pandoc` 系统二进制 | 运行时依赖（docx 路径） | Dockerfile 必须装；缺失时 docx 渲染抛错（在 `scripts/check_export_dependencies.sh` 兜底） |
| `playwright` + chromium binary | 运行时依赖（仅 pdf 路径） | 镜像里 chromium 装在 `/root/.cache/ms-playwright/chromium-*`；首次冷启动慢；本地 mac 需 `playwright install chromium`（测试时 mock）|
| `python-markdown` | 运行时依赖（pdf 路径 md→html） | pip 包，缺失时 pdf 渲染抛错 |
| `PermissionService.check` / `authorize` | 内部 Python API | 导入到知识空间必走，权限模型若改要同步 |

---

## 7. 测试与可观测

- **单元/集成（80 个）**：覆盖 service 取数、turn 配对、两个 bug 修复路径、4 个 renderer、文件名、导入流程、同名重试、uploadable spaces。（原 94 个，API + renderer 测试因 mock playwright 重写后收敛到 80）命令：
  ```bash
  cd src/backend && uv run pytest test/workstation/ test/knowledge/test_uploadable_spaces*.py
  ```
- **API e2e（9 个）**：契约层，需要 backend + admin token。命令：
  ```bash
  cd src/backend && E2E_ADMIN_PASSWORD='Bisheng@top1' uv run pytest test/e2e/test_e2e_conversation_export.py -v
  ```
- **手动 UI 验证**：[e2e-checklist.md](./e2e-checklist.md)（覆盖 UI 类 AC + 真实导出视觉巡检）
- **可观测**：失败走标准错误码 + service 内 `logger.exception`；目前没有专门的 Prometheus 指标（短板，见 §8）

---

## 8. 后续改进 / 不打算做的事

- **不做异步导出**：除非范围放开到整会话或多会话拼接（见 §3 决策 4）
- **不做语义抽取/摘要**：原文导出更可信，摘要应是另一个 feature
- **短板：chromium 渲染开销** —— 启动 ~1-2s/page、渲染 ~0.5s，首次冷启动尤其慢；高并发或大批量导出时是瓶颈，考虑后续做 browser 复用 / 进程池
- **短板：图片失败保留原 URL** —— 离线打开就是死链；后续可考虑改为占位图 + 旁注
- **短板：缺导出耗时指标** —— 后续接 Prometheus / 业务日志埋点
- **短板：workflow/技能聊天入口（appChat）的临时 id 未修** —— 该入口答案消息在流 `end` 缺 `message_id` 时保留合成数字 id（曾观测到导出请求 `message_ids:[1,71]`、`[9394]`，均小于/不在真实 id 段 → 12060）。daily 入口已修（见 §5 #11），appChat 入口待同样回填真实 id，或在导出侧加"非真实 id 过滤"兜底
- **不打算合并两个聊天入口**（日常 vs 工作流/助手）：两个 chat 容器历史独立，强行合并会牵连大量无关代码

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-06-01 | 初版（覆盖到 commit `4394ba524`） | F028 主体完成，从 handoff 文档沉淀到 SDD 流程 |
| 2026-06-02 | PDF 引擎 libreoffice→chromium/playwright（决策 6）；§4.1/§4.3 渲染路径、§5 坑（删 libreoffice 超时，加 pandoc 空行/PUA 字面化/strip 换行/emoji fallback 4 条）、§6.2 依赖、§7 测试数 94→80、§8 短板同步 | libreoffice 解析 pandoc docx 表格/列表布局崩塌 |
