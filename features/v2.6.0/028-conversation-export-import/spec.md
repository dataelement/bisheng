# Feature: F028-conversation-export-import（工作台会话回答级导出与导入知识空间）

> **前置步骤**：已完成 Spec Discovery（架构师提问），PRD 不确定性已对齐。
> 关键澄清结论：导出 / 导入两条能力共用同一份内容生成器；PDF 走 `pypandoc → docx → LibreOffice → pdf`；图片预下载到本地临时文件再喂 pandoc；复用 `AddToKnowledgeModal` 配合新增「可上传空间」API；本期同步生成、不引入异步任务。

**关联 PRD**: 飞书 wiki [2.6 beta3 PRD](https://dataelem.feishu.cn/wiki/RLZ2wa8GTiXC7FknbfGcaODPnPd) §3「工作台会话导出和导入知识空间（中信保 6.10、首钢）」
**优先级**: P0（首钢 / 中信保 6.10 项目交付）
**所属版本**: v2.6.0（合入 `feat/2.6.0-beta3` 分支）
**模块编码**: 沿用 120 (`workstation`)，新增错误码段位 12060-12069
**依赖**: F004（ReBAC core）、F008（resource-rebac-adaptation）

> **范围边界**
> - **本次纳入**：
>   - 工作台「日常模式」、「应用-助手」、「应用-工作流」三种会话场景的**回答级**导出（Word / PDF / Markdown / TXT）。
>   - 同一选择态下「导入到知识空间」能力，目标为知识空间根目录或文件夹，复用现有上传 + 解析 + 入库链路。
>   - PC 与 H5 两端 UI；H5 走底部弹层。
>   - 新增「列出当前用户可上传的知识空间 / 文件夹」API（用于 `AddToKnowledgeModal` 在本场景的数据源）。
> - **本次明确排除**：
>   - 整会话导出（顶部 `/api/v1/audit/session/export/data` 维持原状，仅返 JSON，归审计用途）。
>   - Linsight、Channel Article 等非工作台会话的回答导出。
>   - 流式生成中边导边停 / 中途取消 / 暂存草稿。
>   - 自动云存归档：本期不把生成的文件落仓库，请求结束即清理临时文件。
>   - 思考过程 / 工具调用过程 / RAG 命中片段的导出（只导 `agent_answer.msg` 最终文本）。
>   - 覆盖同名文件、人工选择覆盖 vs 重命名（PRD 已定「自动追加序号」，本期不开放选项）。
>   - 导入文件大小校验：聊天记录生成的 md 文件体量恒定较小，本接口不做单文件大小限制；知识空间整体配额（文件数 / 容量）仍按现有 `KnowledgeSpaceService.add_file` 链路校验（AC-23）。
>   - 导入侧敏感词二次过滤：会话内容在生成阶段已走过聊天敏感词过滤链路，本接口不重复跑敏感词检查；现有 `KnowledgeSpaceService.add_file` 链路若仍触发敏感词检查，按其原有 `sensitive_status` 字段展示，不阻断导入响应。

---

## 1. 概述与用户故事

**故事 A（业务用户 · 工作台日常模式）**：
作为 **使用工作台日常模式与模型对话的用户**，
我希望 **把某条 AI 回答连同我的提问，直接导出成 Word / PDF / Markdown / TXT 拿走**，
以便 **离线归档、转交给同事或粘进项目报告，不必手动复制再排版**。

**故事 B（业务用户 · 应用会话）**：
作为 **在工作台打开助手 / 工作流应用使用的用户**，
我希望 **把应用产出的回答按回答粒度沉淀下来**，
以便 **复用助手回答的结论，而不是只能保留整段会话历史**。

**故事 C（知识沉淀者 · 中信保 / 首钢场景）**：
作为 **希望把高质量 AI 回答沉淀为企业知识资产的用户**，
我希望 **在选择回答后一键导入到某个知识空间 / 文件夹，自动走入库解析**，
以便 **未来在知识空间检索时能命中这些经过验证的回答，形成可复用的企业知识**。

**故事 D（前端研发）**：
作为 **工作台 Client 前端研发**，
我希望 **「选择态」「query / answer 配对联选」「底部固定操作栏」逻辑由 Recoil 全局状态统一管理，复用现有 `AddToKnowledgeModal`**，
以便 **不在每个会话页面散落选择态实现；目标选择器一次写、未来其他模块复用**。

**故事 E（后端研发）**：
作为 **维护工作台与知识空间的后端研发**，
我希望 **「内容生成 → 多格式渲染 → 入知识空间」共用一份 Markdown 中间表达，导出与导入双入口走同一个 Service**，
以便 **改一处文案 / 一处样式 / 一处图片处理逻辑两个能力同时生效；不在不同入口里重复维护**。

---

## 2. 验收标准

> AC-ID 在本特性内唯一，格式 `AC-NN`。
> tasks.md 中的测试任务必须通过 `覆盖 AC: AC-NN` 追溯到此表。

### 2.1 导出能力

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-01 | 任意已登录用户 | 在工作台一条**已完成生成**的 AI 回答下方点击「导出」icon | 当前会话整体进入消息选择态；本回答与其对应 query（按 `extra.parentMessageId` 关联）默认勾选；底部出现固定操作栏（PC：全选 + 4 格式导出按钮 + 导入到知识空间 + 关闭；H5：全选 + 导出到本地 + 导入到知识空间 + 关闭） |
| AC-02 | 用户 | 选择态下点击「导出为 Word / PDF / Markdown / TXT」 | 后端 `POST /api/v1/chat/messages/export` 同步返回对应格式文件流；浏览器按 `Content-Disposition` 中的文件名下载；下载完成后选择态保持，不自动退出 |
| AC-03 | 用户 | 勾选某条 answer | 该 answer 对应的 query 自动联选；反向亦然；取消勾选同步取消 |
| AC-04 | 用户 | 点击「全选」 | 当前会话所有 message 进入选中态；上滑加载更多历史消息时，新加载出的消息也自动选中 |
| AC-05 | 用户 | 在某条消息上点击「全选以下消息」 | 该消息（含自身）及其下方所有 message 进入选中态 |
| AC-06 | 用户 | 对同一条 query「重新生成」产生多条 answer，勾选其中任一条 | 该 query 与**所有** answer 均被勾选；导出文件中按时间顺序依次包含全部 answer（每条 answer 独立成段，前置标签 `<模型名/应用名>：`） |
| AC-07 | 用户 | AI 回答正处于流式生成中（SSE 或 WebSocket 流未关闭） | 该 answer 下方不展示「导出」icon；与现有「复制」icon 的可见性条件完全一致 |
| AC-08 | 用户 | 选中超过 200 条 message 并点击任意导出 / 导入按钮 | 前端 toast 报「单次最多选中 200 条消息」并阻止请求；后端接口同样做 200 条上限校验，超过返 `ConversationMessageBatchTooLargeError` (12061) |
| AC-09 | 用户 | 工作流 OUTPUT 节点输出含表单、按钮、附件等非纯文本结构 | 导出文件中对应位置渲染为 `[交互组件：<节点类型>]` 占位文本；不报错、不丢内容上下文 |
| AC-10 | 用户 | 导出文件成功后查看文件名 | 文件名格式 `<会话标题>_yyyyMMddHHmm.<ext>`；会话标题为空时使用 `未命名会话`；标题部分截断到 80 字符；按 Windows 最严标准把 `< > : " / \| ? *`、ASCII 控制字符、末尾点与空格替换 / 删除为 `_` |
| AC-11 | 用户 | 打开 Word / PDF 导出文件 | A4 纵向白底；正文使用微软雅黑或系统中文字体（由 reference docx 模板控制）；用户名段、模型名段单独成段且加粗 14pt；query 段与 answer 段之间渲染一条灰色横线；Markdown 编号列表渲染为真实编号；表格渲染为真实表格；代码块保留等宽字体 + 浅灰底；图片嵌入正文 |
| AC-12 | 用户 | 打开 Markdown 导出文件 | 保留 Markdown 原始结构；用户名段写为 `**Admin：**`，模型名段写为 `**DeepSeek v3.2：**`，每对 query/answer 之间一条 `---` 横线；图片仍使用 Markdown 图片语法 `![](url)`；URL 保持 MinIO 内部地址（PRD §「导出 md 图片 URL」决策，外网失效不补救） |
| AC-13 | 用户 | 打开 TXT 导出文件 | 纯文本；保留段落与换行；表格降级为 Tab 对齐纯文本；图片以 `[图片：<文件名>]` 占位；代码块保留缩进；用户名 / 模型名 / query / answer 之间用空行分隔 |
| AC-14 | 用户 | 导出含 bisheng RAG 引用角标的回答 | 文件中角标（`[1]`、`[2]`、`<sup>` 等所有现有形式）被完全剥除；不出现「跳转链接」、不在末尾追加「来源列表」 |
| AC-15 | 用户 | 导出 `agent_answer` 类回答 | 文件中只包含 `events[]` 的最终文本（与 `message.msg` 字段一致）；不包含 `thinking` / `tool_call` / `tool_result` / 中间步骤；不报错、不留空段 |

### 2.2 导入知识空间能力

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-16 | 用户 | 选择态下点击「导入到知识空间」 | 弹出 `AddToKnowledgeModal`（`mode="channel_sync"` 或新增 `mode="message_export"`，二选一，见 §4 AD-09）；列表数据源走新增 `GET /api/v1/knowledge/space/uploadable` |
| AC-17 | 用户 | 查看可选知识空间列表 | 列出当前用户在 OpenFGA 中持有 `upload_file` 关系的全部知识空间；支持搜索关键词；支持展开文件夹；支持选择「根目录」或「具体文件夹」 |
| AC-18 | 用户 | 选好目标后点击确认 | 后端 `POST /api/v1/chat/messages/import-to-knowledge` 同步返回 `{success: true, file_id: <number>, dup_renamed: <bool>, target_filename: <string>}`；前端 toast「导入成功，文件正在解析中」附知识空间链接；选择态保持 |
| AC-19 | 用户 | 目标文件夹已存在 `xxx_202602031117.md` | 后端在 `KnowledgeSpaceFileDao` 当前层级 list 同名文件 → 追加 `(1)`、`(2)` ……直到不重名 → 用新文件名走 `add_file`；响应里 `dup_renamed=true`、`target_filename` 给最终落地的文件名 |
| AC-20 | 用户 | 对目标空间 / 文件夹无 `upload_file` 权限 | 后端先做一道 `PermissionService.check(<resource>, "upload_file")`（即使 `KnowledgeSpaceService.add_file` 也会自校验，本接口仍前置一次以早返错），返 `ConversationImportPermissionDeniedError` (12067)；前端 toast「暂无权限导入到该知识空间」 |
| AC-21 | 用户 | 目标空间不存在 / 已删除 | 后端返 `ConversationImportSpaceNotFoundError` (12065)；前端 toast「知识空间不存在或已删除」 |
| AC-22 | 用户 | 目标文件夹不存在 / 已删除 | 后端返 `ConversationImportFolderNotFoundError` (12066)；前端 toast「文件夹不存在或已删除」 |
| AC-23 | 用户 | 当前租户 / 用户已用满知识空间文件容量 | 复用现有配额校验链路（`KnowledgeSpaceService.add_file` 内部已校验），错误码归一化映射到 `ConversationImportQuotaExceededError` (12068)；前端按现有「知识空间配额已满」文案 |
| AC-24 | 用户 | `add_file` 入队后立即返回 | 文件状态由 `KnowledgeSpaceFile` 现有链路从 `WAITING` → `PROCESSING` → `SUCCESS` / `FAILED` / `TIMEOUT`；本接口不等待解析完成；前端在知识空间页面看进度 |

### 2.3 权限与越权边界

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-25 | 用户 A | 携带用户 B 的 `message_ids` 调 `POST /api/v1/chat/messages/export` 或 `import-to-knowledge` | 后端按 `(message_id, user_id)` 二元过滤查询，命中 0 条 → 返 `ConversationMessageNotOwnedError` (12062)；前端 toast「消息不存在或无访问权」 |
| AC-26 | 用户 A | message 实际隶属于其他租户的会话 | SQLAlchemy 多租户事件自动注入当前 `tenant_id` 过滤；查询命中 0 条 → 同 AC-25 错误码；不暴露「跨租户」语义 |
| AC-27 | 用户 | `message_ids` 列表中混入不存在 / 已删除的 ID | 整批拒绝，返 `ConversationMessageNotFoundError` (12060)；不做「部分导出 + 部分失败」的妥协行为；前端 toast「消息不存在或已删除，请刷新会话」 |
| AC-28 | 用户 | 选中的 `message_ids` 跨越多个会话（`chat_id`） | 后端按第一个 message 的 `chat_id` 校验全部 message 必须同会话；不同会话返 `ConversationMessageNotOwnedError` (12062)（不暴露具体原因）；前端选择态本身限制在单会话内，不允许跨会话选择 |

### 2.4 渲染与失败处理

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-29 | 用户 | 选中含**外网图片**且后端进程因网络问题取不到图片 | 该图片在导出文档中替换为占位文本 `[图片加载失败：<原 URL>]`；不影响其它内容；不整批失败 |
| AC-30 | 用户 | pypandoc 转 docx 进程异常 / LibreOffice 转 PDF 进程超时（>30s） | 后端返 `ConversationExportRenderFailedError` (12064)，`msg` 含 renderer 名称便于排障；前端 toast「文件生成失败，请稍后重试」附简要 reason |
| AC-31 | 用户 | 请求 format 非 `docx` / `pdf` / `md` / `txt` | 后端返 `ConversationExportFormatUnsupportedError` (12063)；前端不应允许触发，本码主要防直调 API |

---

## 3. 边界情况

- **多会话切换**：用户在选择态下切到另一会话 → 自动退出选择态（清空选中集合 + 锚点 + 当前会话引用）。
- **页面刷新**：选择态不持久化，刷新即重置。
- **流式生成完成事件迟到**：以前端"复制"icon 的可见性条件为准（同一个 `isStreaming` flag）。"导出"icon 与"复制"icon 看同一个开关。
- **`extra.parentMessageId` 缺失**：legacy 数据可能不带；后端取数循环按"时间相邻、type 配对"作为兜底配对策略；前端联选时若找不到 parentMessageId 则只选当前一条，不报错。
- **工作流 OUTPUT 节点多次输出**：单条 `agent_answer` 的 `events[]` 中可能含多条 `output` 事件；导出时按 events 顺序拼接成单段文字；非文本 output 走 AC-09 占位。
- **同名扫描冲突**：导入时仅扫描目标层级（不递归），用 `SpaceFileDao.async_list_children` 当前接口；扫描与 `add_file` 之间存在毫秒级 race，本期不做分布式锁，重名冲突极小概率漏检；若 add_file 自校验报重名再走一遍重命名重试（最多 1 次），仍冲突直接返 `ConversationImportFailedError` (12069)。
- **会话标题动态生成**：会话标题由后台 LLM 异步生成，可能尚未生成完成；按 `MessageSession.name` 当前值取，为空或 `New Chat` 时统一使用 `未命名会话`。
- **图片 URL 形态多样**：
  - MinIO 内部地址：走 `MinioManager` SDK 直拉 bytes。
  - 公网 http(s)：走 `httpx` 拉 bytes，超时 5s。
  - `data:` URL（极少出现）：直接 decode bytes。
  - 其它私有协议：跳过并替换为占位文本。
- **临时文件清理**：每次请求在 `tempfile.TemporaryDirectory()` 上下文中处理；FastAPI 响应完成后自动清理；进程崩溃由 OS 清理 `/tmp` 兜底；不持久化任何中间产物。
- **batch 上限的执行时机**：前端在拼好 `message_ids` 时就拦截；后端二次校验。**不**做"导出 200 条用户队列等队 5 分钟"的妥协设计 —— 本期没有任务队列。
- **不支持**：
  - 选中跨会话消息（前端约束）。
  - 自定义文件名 / 自定义模板 / 自定义页眉页脚。
  - 导出含 RAG 引用角标的"溯源列表"。
  - 「导出后自动转发到企微 / 飞书 / 邮件」等下游分发动作。
  - 「导入后立即查看解析结果」（解析为后台 Celery，前端到知识空间页面查看）。

---

## 4. 架构决策

| ID | 决策 | 选项 | 结论 | 理由 |
|----|------|------|------|------|
| AD-01 | DOCX 渲染选型 | A pypandoc<br>B python-docx 手撸<br>C LibreOffice HTML→DOCX | **A** pypandoc | pyproject.toml 已有 `pypandoc>=1.15`，pandoc 是 Markdown→DOCX 的最强转换器；表格 / 列表 / 代码块 / 图片自带支持；手撸 python-docx 工作量极大且样式难统一 |
| AD-02 | PDF 渲染选型 | A weasyprint<br>B pypandoc 出 docx → LibreOffice 转 PDF<br>C docx2pdf | **B** | Docker 镜像已装 LibreOffice（见 `libreoffice_converter.py`，知识库 PPT→PDF / DOC→DOCX 在用），零新增依赖；DOCX 与 PDF 共用同一份 docx 渲染，效果一致 |
| AD-03 | 中间表达 | A 手撸 docx<br>B 统一 Markdown 中间表达<br>C HTML 中间表达 | **B** | 一份 Markdown 同时承载导出 md、导入 md、docx、PDF、TXT 五种出口；改文案 / 改样式只动一处；TXT 由 Markdown 简化派生 |
| AD-04 | Markdown 中"用户名 / 模型名"标签的渲染方式 | A 加粗段落 + `---` 分隔<br>B 用 H3 等 Heading<br>C Definition List | **A** | 与 PRD 样式图最接近；不与回答内既有 H 标题冲突（回答内 H 不需 demote）；模板 docx 给「加粗段落 14pt」一份样式即可控制 |
| AD-05 | 回答内 H 标题层级处理 | A 强制 demote 2 级<br>B 不处理 | **B** | AD-04 已用加粗段落而非 Heading 表示标签，层级不冲突；强制 demote 反而把回答里的 `# 一级标题` 压成 `### 三级`，破坏作者原意 |
| AD-06 | 图片处理流程 | A pandoc 自己去网络拉<br>B 后端预下载到本地临时文件再喂 pandoc | **B** | pandoc 网络访问失败时报错噪声大、不可控；后端预下载可统一处理 MinIO 内部 URL + 公网 URL + 失败 fallback 占位；可控、可调试、可降级 |
| AD-07 | 导出 md 中图片 URL 策略 | A 签名公网 URL<br>B Base64 内嵌<br>C 打包 zip + 相对路径<br>D 保持内部 URL | **D** | PRD 决策（用户确认）：用户离开内网图片失效是可接受代价；导出 md 与导入 md 内容一致，导入侧知识空间解析能读内部 URL |
| AD-08 | 同步 vs 异步 | A 全同步<br>B 全 Celery + 轮询 | **A** | 单次 ≤ 200 条 message，pypandoc + LibreOffice 整体在 5s 内可完成；不引入任务表、不增前端轮询 UI；如未来发现 P99 超阈再加 Celery |
| AD-09 | `AddToKnowledgeModal` 复用方式 | A 后端新增 `getUploadableSpacesApi` + Modal 加数据源开关<br>B 复用 article 模式（managed 权限）<br>C 抽独立 picker 组件 | **A** | PRD 要求"按 upload_file 权限过滤"，managed 权限与之不严格等价；Modal 加一个 `dataSourceApi` prop 或新增 `mode="message_export"` 内含正确 API 调用，是改动最小且语义最准的方式 |
| AD-10 | 同名文件策略 | A 导入接口里特殊处理（自己 list 后追加序号）<br>B 下沉到 `KnowledgeSpaceService.add_file` 加参数 `on_name_conflict` | **A** | 不动现有上传 service 行为面；本场景的"自动追加序号"是导出导入特有诉求；未来其它场景如需要类似行为再考虑下沉 |
| AD-11 | 导入成功判定 | A `add_file` 入队即返成功<br>B 等到 Celery 解析完成 | **A** | 解析在 Celery，等待会让接口请求长时间挂起；前端用 toast 提示「文件正在解析中」并附知识空间链接由用户自行查看进度 |
| AD-12 | 工作流非纯文本输出 | A 降级为 `[交互组件：xxx]` 占位<br>B 跳过 | **A** | 保留对话上下文完整性，让阅读者知道"这里有过交互"；占位文字短、不会破坏排版 |
| AD-13 | 流式态下 icon 显隐 | A 单独维护一套"是否完成"判断<br>B 复用现有"复制"icon 的可见性条件 | **B** | bisheng client 端日常模式走 SSE、应用会话走 WebSocket，但前端的"复制"icon 显隐已经处理过两条链路统一的 `isStreaming` flag；导出 icon 直接挂同一个 condition |
| AD-14 | reference docx 模板来源 | A UX 提供原始 .docx<br>B 后端 python-docx 程序化生成入仓<br>C 手动 Word 制作入仓 | **B**（占位）→ **A**（精修） | 第一版用 python-docx 程序化生成一份能跑的占位模板入仓 (`assets/conversation_export_template.docx`)；UX 后续提供精修模板替换 |
| AD-15 | 错误码归属 | A 新建模块编码<br>B 沿用 120 (workstation) | **B** | 本特性入口是工作台，业务语义归 workstation；段位 12060-12079；不为单 feature 创建新模块编码 |

---

## 5. 数据库 & Domain 模型

### 5.1 复用现有表（不新增表）

| 表 | 来源模块 | 用途 |
|----|---------|------|
| `chat_message` (`ChatMessage`) | `chat_session` | 取被勾选的 message：`id` / `chat_id` / `user_id` / `type` / `category` / `message` / `sender` / `extra` |
| `message_session` (`MessageSession`) | `chat_session` | 取会话标题 (`name`) / 会话所属应用名 (`flow_name`) / 会话场景 (`flow_type`) |
| `knowledge_space` / `knowledge_space_file` / `knowledge_space_folder` | `knowledge_space` | 导入目标解析 + 同名扫描 |
| `flow_version` | `flow` | 工作流 / 助手场景下取应用最新版本名作为名称回退（仅当 `flow_name` 为空时使用） |

### 5.2 Domain 模型（DTO / Schema）

```python
# src/backend/bisheng/workstation/domain/schemas/conversation_export.py

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ExportFormat(str, Enum):
    DOCX = "docx"
    PDF = "pdf"
    MARKDOWN = "md"
    TXT = "txt"


class ExportMessagesRequest(BaseModel):
    chat_id: str = Field(..., description="目标会话 ID，所有 message 必须同会话")
    message_ids: list[int] = Field(
        ...,
        min_length=1,
        max_length=200,
        description="待导出的 message id 列表；最大 200",
    )
    format: ExportFormat


class ImportMessagesToKnowledgeRequest(BaseModel):
    chat_id: str
    message_ids: list[int] = Field(..., min_length=1, max_length=200)
    knowledge_space_id: int = Field(..., description="目标知识空间 ID")
    parent_id: Optional[int] = Field(
        None,
        description="目标文件夹 ID；为空代表知识空间根目录",
    )


class ImportMessagesToKnowledgeResponse(BaseModel):
    file_id: int
    target_filename: str
    dup_renamed: bool


class UploadableSpaceItem(BaseModel):
    id: int
    name: str
    icon: Optional[str] = None
    description: Optional[str] = None


class UploadableSpaceListResponse(BaseModel):
    data: list[UploadableSpaceItem]
```

### 5.3 内部中间结构（不入库）

```python
# Markdown 生成器的中间表达，不持久化
class ConversationTurn(BaseModel):
    user_name: str            # "Admin" / "张三"
    user_query: str           # query 段纯文本（已剥角标）
    sender_name: str          # 日常模式：模型名；应用：应用名
    answers: list[str]        # 多 answer 顺序保留；单条 answer 内容是已 normalize 的 Markdown
```

---

## 6. API 契约

### 6.1 端点列表

| Method | Path | 描述 | 认证 |
|--------|------|------|------|
| POST | `/api/v1/chat/messages/export` | 同步导出选定 message 为指定格式文件流 | 是（`UserPayload.get_login_user`） |
| POST | `/api/v1/chat/messages/import-to-knowledge` | 同步把选定 message 生成 .md 并加入目标知识空间 | 是 |
| GET | `/api/v1/knowledge/space/uploadable` | 列出当前用户可上传文件的知识空间（OpenFGA `upload_file` relation） | 是 |

> 三个 endpoint 实际放置位置：`workstation` 模块下 `domain/services/conversation_export_service.py` + `api/endpoints/conversation_export.py`；`uploadable` 路由跨模块 —— 路由路径以 `/api/v1/knowledge/space/uploadable` 出现（前端心智一致），endpoint 文件位置归 `knowledge_space` 模块 endpoints 目录，service 调 `PermissionService.list_resources(user, "upload_file", "knowledge_space")`。

### 6.2 请求 / 响应示例

**导出**：

```json
POST /api/v1/chat/messages/export
Content-Type: application/json

{
  "chat_id": "abc-123",
  "message_ids": [1001, 1002, 1003, 1004],
  "format": "pdf"
}
```

成功响应（非 JSON，文件流）：
```
HTTP/1.1 200 OK
Content-Type: application/pdf
Content-Disposition: attachment; filename*=UTF-8''%E5%85%B3%E4%BA%8E%E9%BB%84%E9%87%91...%E7%9A%84%E8%B5%B0%E5%8A%BF_202602031117.pdf

<binary PDF bytes>
```

错误响应（统一走 `UnifiedResponseModel`）：
```json
{
  "status_code": 200,
  "status_message": "ConversationMessageBatchTooLargeError",
  "data": {
    "code": 12061,
    "message": "单次最多选中 200 条消息"
  }
}
```

**导入知识空间**：

```json
POST /api/v1/chat/messages/import-to-knowledge
{
  "chat_id": "abc-123",
  "message_ids": [1001, 1002],
  "knowledge_space_id": 42,
  "parent_id": 1024
}
```

成功响应：
```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "file_id": 99887,
    "target_filename": "关于未来黄金价格的走势_202602031117(1).md",
    "dup_renamed": true
  }
}
```

**列出可上传空间**：

```json
GET /api/v1/knowledge/space/uploadable?keyword=黄金
```

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "data": [
      {"id": 42, "name": "宏观研究", "icon": null, "description": "..."},
      {"id": 56, "name": "黄金专题",  "icon": null, "description": "..."}
    ]
  }
}
```

### 6.3 错误码表

| HTTP Status | MMMEE Code | Error Class | 场景 | 关联 AC |
|-------------|------------|-------------|------|---------|
| 200 (body) | 12060 | ConversationMessageNotFoundError | message_id 不存在或已删除 | AC-27 |
| 200 (body) | 12061 | ConversationMessageBatchTooLargeError | 单次选中超过 200 条 | AC-08 |
| 200 (body) | 12062 | ConversationMessageNotOwnedError | message 不属于当前用户 / 跨会话 / 跨租户 | AC-25, AC-26, AC-28 |
| 200 (body) | 12063 | ConversationExportFormatUnsupportedError | format 非 docx/pdf/md/txt | AC-31 |
| 200 (body) | 12064 | ConversationExportRenderFailedError | pandoc 进程崩 / LibreOffice 超时（>30s） | AC-30 |
| 200 (body) | 12065 | ConversationImportSpaceNotFoundError | 目标知识空间不存在 | AC-21 |
| 200 (body) | 12066 | ConversationImportFolderNotFoundError | 目标文件夹不存在 | AC-22 |
| 200 (body) | 12067 | ConversationImportPermissionDeniedError | 无 upload_file 权限 | AC-20 |
| 200 (body) | 12068 | ConversationImportQuotaExceededError | 超出知识空间配额 | AC-23 |
| 200 (body) | 12069 | ConversationImportFailedError | add_file 内部失败 / 同名重命名重试 1 次仍冲突 | AC-19 兜底 |

---

## 7. Service 层逻辑

### 7.1 新增 `ConversationExportService`

位置：`src/backend/bisheng/workstation/domain/services/conversation_export_service.py`

| 方法 | 输入 | 输出 | 职责 |
|------|------|------|------|
| `async export_messages` | `(req: ExportMessagesRequest, user: UserPayload)` | `(filename: str, mimetype: str, bytes_io: BytesIO)` | 取 message → 构建 turns → 生成 Markdown → 按 format 渲染 → 返回文件流 |
| `async import_messages_to_knowledge` | `(req: ImportMessagesToKnowledgeRequest, user: UserPayload)` | `ImportMessagesToKnowledgeResponse` | 取 message → 构建 turns → 生成 Markdown bytes → 同名扫描 + 改名 → 复用 `KnowledgeSpaceService.add_file` |
| `async _load_and_validate_messages` | `(chat_id, message_ids, user)` | `list[ChatMessage]` | 鉴权：必须同 `chat_id`、必须同 `user_id`、必须同 `tenant_id`（多租户事件自动加）；数量校验 ≤200；缺失即整批拒绝 |
| `async _build_turns` | `list[ChatMessage] + MessageSession` | `list[ConversationTurn]` | 按 `extra.parentMessageId` 配对（缺失走时间相邻兜底）；按 `flow_type` 取 sender 名（15→`ChatMessage.sender` 模型名；5/10→`MessageSession.flow_name`）；剥角标；只取 `agent_answer.msg`；工作流非纯文本输出降级 |
| `_render_markdown` | `list[ConversationTurn]` | `str` | 拼字符串：`**<user>：**\n\n<query>\n\n---\n\n**<sender>：**\n\n<answer>\n\n` 循环 |
| `_render_docx` | `markdown_str` | `bytes` | 调 pypandoc + reference docx 模板 |
| `_render_pdf` | `markdown_str` | `bytes` | 先调 `_render_docx` → 临时文件 → `libreoffice_converter._convert_file_extension(input, 'pdf', ...)` → 读结果 → 清理 |
| `_render_txt` | `markdown_str` | `bytes` | 简单 Markdown→纯文本退化：剥 `**`、`#`、`` ` ``、表格还原为 Tab 对齐、图片占位 `[图片：<name>]` |
| `_preprocess_images` | `markdown_str` | `(processed_md, temp_dir)` | 扫描所有 `![](url)`：MinIO 内部 URL 走 `MinioManager` 拉 bytes；公网走 httpx；失败占位；替换为本地 `file://` 路径 |
| `_resolve_filename` | `MessageSession + ext` | `str` | `<title>_yyyyMMddHHmm.<ext>`；标题截 80 字符 + 非法字符替换 + 末尾空格点删除；空标题用「未命名会话」 |
| `_resolve_unique_filename` | `(spaceid, parent_id, base_filename)` | `str` | 在目标层级 list 同名 → 追加 `(1)`、`(2)`……直到不重名 |
| `_strip_citation_marks` | `str` | `str` | 用正则把 RAG 角标 (`[1]`、`[[doc-id]]`、`<sup>...</sup>` 等所有现有形式) 全部去掉；正则集合在实现阶段对照真实数据补全 |

### 7.2 新增 `KnowledgeSpaceService.list_uploadable_spaces`

位置：`src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`（已有 service 内追加方法）

```
async def list_uploadable_spaces(
    self, user: UserPayload, keyword: Optional[str] = None
) -> list[UploadableSpaceItem]:
    space_ids = await PermissionService.list_resources(
        user=user,
        relation="upload_file",
        resource_type="knowledge_space",
    )
    # 拉 KnowledgeSpace 元信息（name / icon / description），按 keyword 过滤、按 update_time 倒序
    ...
```

> 这里走的是 OpenFGA `list_objects` 方向（"该 user 对哪些 space 持有 `upload_file` relation"）。`PermissionService` 现有 `list_resources` 已封装此能力（F008 引入），无需额外 OpenFGA SDK 调用。

### 7.3 权限检查

- `export_messages`：仅做"会话 owner 校验"（`WHERE user_id = current_user`），不查 OpenFGA。理由：日常 / 助手 / 工作流会话天然只属于发起者，本期不开放"看别人会话"能力，故无需 ReBAC。
- `import_messages_to_knowledge`：先调 `PermissionService.check(<space|folder>, "upload_file")` 做一道前置短路 → 再调 `KnowledgeSpaceService.add_file`（service 内自校验是兜底，不依赖前端"已过滤"列表）。
- `list_uploadable_spaces`：内部用 `PermissionService.list_resources`，自带租户隔离。

### 7.4 DAO 调用约定

- `ChatMessageDao.aget_messages_by_ids(message_ids, user_id, chat_id)` —— 新增或扩展现有方法，必须支持按 `user_id + chat_id` 复合过滤。
- `KnowledgeSpaceFileDao.async_list_children(space_id, parent_id)` —— 复用现有方法，用于同名扫描。
- `KnowledgeSpaceService.add_file(...)` —— 复用，传入预先生成的 `file_path: List[str]` 形式。

> **注意 (P0 红线)**：endpoint 层禁止直接 import `bisheng.database.models.*`；所有 DAO 调用均通过 Service 中转。

---

## 8. 前端设计

### 8.1 Client 前端（src/frontend/client/）

> Recoil + shadcn/ui + `react-query v5` + axios（包装在 `~/api/request.ts`）

#### 路由与触发位置

- 触发点：每条已完成的 AI 回答下方操作 icon 区域（与"复制"按钮同行）。
- 涉及组件：`src/components/Chat/Messages/`（具体子文件由开发阶段确认）。

#### 状态管理（Recoil）

新增 atom：`~/store/messageSelectionStore.ts`

```ts
interface MessageSelectionState {
  active: boolean;
  chatId: string | null;
  selectedIds: Set<string>;
  anchorMessageId: string | null;
  globalSelectAllOn: boolean;       // 「全选」是否开启
  selectAllBelowAnchor: string | null; // 「全选以下消息」的锚点
}

export const messageSelectionAtom = atom<MessageSelectionState>({...})

export const isMessageSelectedSelector = selectorFamily<boolean, string>({
  // 综合 selectedIds / globalSelectAllOn / selectAllBelowAnchor 判定
})
```

派生 hook：`useMessageSelection()`

- `enterSelectionMode(initialMessageId)` —— 进入选择态，默认勾该回答 + 对应 query
- `toggleMessage(messageId)` —— 单条切换，自动联选 query/answer
- `selectAll()`、`selectAllBelow(anchorId)`、`exit()`
- `getSelectedIds(currentMessages)` —— 把 globalSelectAllOn / selectAllBelowAnchor 实例化成具体 ID 集合
- `isOverLimit(currentMessages)` —— 是否超 200 条

#### 组件

- `<MessageSelectionToolbar>` —— 底部固定栏，PC 与 H5 两个 layout：
  - PC：横向排列「全选」+ 4 个格式按钮 + 「导入到知识空间」+ 关闭 icon。
  - H5：「全选」+ 「导出到本地」（点击展开底部弹层选格式）+ 「导入到知识空间」+ 关闭。
- `<MessageCheckbox>` —— 选择态下消息左侧出现的圆形 checkbox；联选规则在 `useMessageSelection` 里处理。
- `<ExportFormatSheet>` —— H5 底部弹层选格式（移动端专用）。
- `<MessageSelectAllAnchorBanner>` —— 「点击全选以下消息」横条，悬浮在选择态下的消息列表中某一条上方。

#### API 调用

新增 `~/api/messageExport.ts`：

```ts
export async function exportMessagesApi(payload: {
  chatId: string;
  messageIds: number[];
  format: 'docx'|'pdf'|'md'|'txt';
}): Promise<Blob> {
  return axios.post('/api/v1/chat/messages/export', payload, { responseType: 'blob' });
}

export async function importMessagesToKnowledgeApi(payload: {
  chatId: string;
  messageIds: number[];
  knowledgeSpaceId: number;
  parentId: number | null;
}): Promise<{ file_id: number; target_filename: string; dup_renamed: boolean }> {
  return axios.post('/api/v1/chat/messages/import-to-knowledge', payload);
}

export async function listUploadableSpacesApi(keyword?: string) {
  return axios.get('/api/v1/knowledge/space/uploadable', { params: { keyword } });
}
```

#### 复用 `AddToKnowledgeModal`

文件：`src/pages/Subscription/Article/AddToKnowledgeModal.tsx`

改造点（最小动）：
- 新增 prop `dataSourceApi?: (keyword?: string) => Promise<UploadableSpaceItem[]>`，默认行为不变（继续按 mode=channel_sync 用 `getMineSpacesApi`）。
- 当本次工作台导出场景使用时，传入 `dataSourceApi={listUploadableSpacesApi}`。
- 回调 `onSyncSelect({knowledgeSpaceId, knowledgeSpaceName, folderId, folderPath})` 透传不变；本场景父组件接住后调 `importMessagesToKnowledgeApi`。

#### i18n

key 前缀 `workstation.messageExport.*`，三语全量补齐（`zh-Hans` / `en-US` / `ja`）。关键文案：

| key | 中文 |
|-----|------|
| `workstation.messageExport.entry` | 导出 |
| `workstation.messageExport.exportAsWord` | 导出为 Word |
| `workstation.messageExport.exportAsPdf` | 导出为 PDF |
| `workstation.messageExport.exportAsMarkdown` | 导出为 Markdown |
| `workstation.messageExport.exportAsTxt` | 导出为 TXT |
| `workstation.messageExport.importToKnowledge` | 导入到知识空间 |
| `workstation.messageExport.selectAll` | 全选 |
| `workstation.messageExport.selectAllBelow` | 全选以下消息 |
| `workstation.messageExport.cancel` | 取消 |
| `workstation.messageExport.batchLimit` | 单次最多选中 200 条消息 |
| `workstation.messageExport.importSuccess` | 导入成功，文件正在解析中 |
| `workstation.messageExport.permissionDenied` | 暂无权限导入到该知识空间 |
| `workstation.messageExport.spaceNotFound` | 知识空间不存在或已删除 |
| `workstation.messageExport.folderNotFound` | 文件夹不存在或已删除 |
| `workstation.messageExport.renderFailed` | 文件生成失败，请稍后重试 |

### 8.2 Platform 前端

不涉及。

---

## 9. 文件清单

### 新建

| 文件 | 说明 |
|------|------|
| `src/backend/bisheng/workstation/domain/schemas/conversation_export.py` | 请求 / 响应 DTO |
| `src/backend/bisheng/workstation/domain/services/conversation_export_service.py` | 核心 Service |
| `src/backend/bisheng/workstation/api/endpoints/conversation_export.py` | 两个工作台 endpoint |
| `src/backend/bisheng/workstation/assets/conversation_export_template.docx` | reference docx 模板（程序化首版） |
| `src/backend/bisheng/workstation/assets/__init__.py` | 占位 |
| `src/backend/test/workstation/test_conversation_export_service.py` | Service 单元测试 |
| `src/backend/test/workstation/test_conversation_export_api.py` | API 集成测试 |
| `src/backend/test/workstation/__init__.py` | 占位 |
| `src/frontend/client/src/api/messageExport.ts` | 导出 / 导入 / 列空间 API 封装 |
| `src/frontend/client/src/store/messageSelectionStore.ts` | Recoil atom + selector |
| `src/frontend/client/src/hooks/useMessageSelection.ts` | 选择态派生 hook |
| `src/frontend/client/src/components/Chat/MessageSelection/MessageSelectionToolbar.tsx` | 底部固定操作栏 |
| `src/frontend/client/src/components/Chat/MessageSelection/MessageCheckbox.tsx` | 消息侧 checkbox |
| `src/frontend/client/src/components/Chat/MessageSelection/ExportFormatSheet.tsx` | H5 底部弹层格式选择 |
| `src/frontend/client/src/components/Chat/MessageSelection/SelectAllBelowBanner.tsx` | 全选以下消息横条 |
| `src/frontend/client/src/components/Chat/MessageSelection/index.ts` | 子组件 barrel |

### 修改

| 文件 | 变更内容 |
|------|---------|
| `src/backend/bisheng/workstation/api/router.py` | 注册新 endpoint |
| `src/backend/bisheng/knowledge/api/endpoints/knowledge_space.py` | 追加 `GET /uploadable` |
| `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py` | 追加 `list_uploadable_spaces` 方法 |
| `src/backend/bisheng/common/errcode/workstation.py` | 新增 12060-12069 共 10 个错误类 |
| `src/backend/pyproject.toml` | （视实际确认）若 pandoc 二进制或中文字体不在镜像里，更新 docker/Dockerfile 安装 |
| `docker/Dockerfile`（如需） | apt 安装 `pandoc`、`fonts-noto-cjk` / `fonts-wqy-microhei` 等中文字体 |
| `src/frontend/client/src/pages/Subscription/Article/AddToKnowledgeModal.tsx` | 加 `dataSourceApi` prop，保持向后兼容 |
| `src/frontend/client/src/components/Chat/Messages/*.tsx`（具体子文件实现阶段确认） | 在 AI 回答 footer icon 区追加「导出」icon，触发 enterSelectionMode |
| `src/frontend/client/src/components/Chat/Messages/*.tsx` | 选择态下渲染 `<MessageCheckbox>` |
| `src/frontend/client/public/locales/zh-Hans/workstation.json`（或对应实际 i18n 文件结构） | 新增 14 个 key |
| `src/frontend/client/public/locales/en-US/workstation.json` | 同上 |
| `src/frontend/client/public/locales/ja/workstation.json` | 同上 |

---

## 10. 非功能要求

- **性能**：
  - 单次导出 ≤200 条 message，端到端（含 PDF）≤ 5s（P95）；超 30s 视为渲染失败（AC-30）。
  - LibreOffice 子进程超时硬上限 30s；pandoc 子进程超时硬上限 15s。
  - 图片预下载并发上限 8，单图 5s 超时。
- **安全**：
  - 任何 endpoint 必经 `UserPayload.get_login_user` 注入。
  - 跨用户、跨租户、跨会话访问均靠 SQLAlchemy 多租户事件 + 显式 `user_id` / `chat_id` 过滤双重防越权（AC-25/26/28）。
  - 临时文件目录由 `tempfile.TemporaryDirectory()` 管理；文件名含随机 token；不可被外部访问。
  - 不持久化任何导出物到 MinIO / 数据库（导入除外 —— 它走标准上传链路）。
- **兼容性**：
  - 仅影响工作台 Client 端；Platform 端不受任何影响。
  - 复用 `AddToKnowledgeModal` 时新增 prop 必须可选，原 Article / Channel-sync 调用方零改动。
  - 错误码归 120 段位，不与现有 12040-12045 / Approval (181xx) / Channel (190xx) 冲突。
  - Docker 镜像若需补 pandoc / 中文字体，统一从镜像基线层面解决，避免运行时下载。
- **可观测性**：
  - 渲染失败、LibreOffice 超时、图片下载失败都走 `logger.exception` + 计 metric（沿用现有 prometheus 标签风格）。
  - 导入入队成功的事件写入审计日志（`AuditLogService` 现有接口），追溯到导入操作的用户 / 空间 / 文件 / 来源消息列表。

---

## 相关文档

- 版本契约: [features/v2.6.0/release-contract.md](../release-contract.md)
- PRD: 飞书 wiki [2.6 beta3 PRD](https://dataelem.feishu.cn/wiki/RLZ2wa8GTiXC7FknbfGcaODPnPd) §3
- 复用组件：`src/frontend/client/src/pages/Subscription/Article/AddToKnowledgeModal.tsx`
- 复用工具：`src/backend/bisheng/knowledge/rag/pipeline/loader/utils/libreoffice_converter.py`
- 上下游服务：`KnowledgeSpaceService.add_file`（`src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py:2659`）
