# Design: 任务模式开放 API

> **本文档定位 — 现状快照（Why this How）**
>
> - `spec.md` 回答 **做什么**（目标、AC、边界）
> - `design.md`（本文）回答 **为什么这么实现**：关键决策、运行时不直观的事实、对外契约
> - `tasks.md` 是 **流水账**：拆了哪些任务、做了什么改动
>
> 调整原则（详见 `docs/SDD-Guide.md` §3-§4）：实现变化 → 覆盖更新本文档；推翻已 ★ 确认的决策 → 停下与用户重新确认；纯实现细节 → 直接改 design。

**关联**: [spec.md](./spec.md) · [tasks.md](./tasks.md) · PRD `docs/PRD/3.0-beta2/3.0 任务模式开放 API PRD.md` v1.4
**版本**: v3.0.0-beta1（发版线 `feat/3.0.0-beta2`）
**最后更新**: 2026-09-30（已评审，未实现）

> 本文锚点均于 2026-09-30 在 `feat/3.0.0-beta2` 上核对，路径相对 `src/backend/bisheng/`。

---

## 1. 目标与非目标

- **目标**：在 F053 已开放的 `/api/v2` 会话能力上，点亮「任务 × 异步」：一次提交即入队，凭任务标识查询状态、取回结果、下载产物、终止；并按运行模式扩展可用配置查询。执行内核（灵思 worker、队列、产物、失败分类）原样复用，本 Feature 只做开放面的准入、编排与结果投影，外加执行内核上两处受开关控制的改动（不提问、执行前复核技能）。
- **非目标**：不改工作台任务模式的交互与行为（v1 SSE 交接、前端编排、`ask_user` 停车）；不做事件流、续接、限流、幂等、回调；不改日常模式的请求契约（仅补「模型不可用」错误码）；不修 v1 灵思端点既有的越权问题（§5 第 9 条登记，另行处理）。

---

## 2. 关键约束

- 遵循 `docs/constitution.md` C1–C7；错误码归模块 260（F053 所有，本 Feature 按 release-contract 登记借段）。
- **身份**：沿用 F053 `OpenApiPrincipal` 与 `SessionSubject`。自身身份下服务账号不是自然人，凡要求 `user.user_id` 的旧表（`message_session.user_id`、`linsight_session_version.user_id` 外键、LLM 调用的 `invoke_user_id`）一律写**资源归属人**作兼容 id，真实主体写 `message_session.api_subject_*`——与日常模式一致（F053 design §8 第 6 条）。
- **执行在独立进程**：灵思 worker 从 Redis `linsight:queue` 取任务，与 HTTP 进程不共享 ContextVar。worker 执行期**不做任何用户级权限判定**（知识检索只按提交时的 id 白名单，`tool/domain/langchain/linsight_knowledge.py:44-70`），因此全部权限判定必须在提交时完成。
- **队列无上限**（PRD DT-5）：API 与工作台共用一个队列，先到先执行。
- **附件临时桶 3 天回收**（`core/storage/minio/minio_storage.py:318-330`），上传返回的预签名链接却标 7 天。提交时复制到正式存储的只是会话里展示用的副本（`core/storage/chat_attachment.py:95`）；worker 在**执行时**才按 `pending_files` 里的临时桶地址读取附件（`linsight/domain/services/workbench_impl.py` `ingest_pending_files`），所以排队超过 3 天的附件会过期，结果中列为「已过期」（spec 边界情况）。
- **双 DB**：新增一列 JSON，须用项目既有 `JsonType`，MySQL / DM8 同时验证。
- **prompt ⟺ tool 同步**（`linsight/AGENTS.md:24`）：关闭 `ask_user` 必须同时去掉工具与系统提示词中的相关段落。

---

## 3. 方案对比与选定

### 决策 1：契约形态——提交复用会话端点，其余为任务资源端点

- **备选**：
  - A. 提交走既有 `POST /api/v2/workstation/chat/completions`，以 `run_mode="task"` + `execution="async"` 区分；查询、下载、终止新增 `/api/v2/workstation/tasks/{task_id}` 资源端点。
  - B. 另起 `/api/v2/linsight/tasks` 一整套端点。
- **选定**：A。
- **原因**：父 PRD D11 / D12 要求「运行模式」「传输方式」是同一能力上的两个独立参数、只维护一套契约；F053 的异常处理器已经按 `run_mode` / `execution` 字段名给出 `26017` / `26015`（`open_api/api/exception_handlers.py:163-182`），A 与之一致，日常模式调用方零改动。异步提交之后的状态、产物、终止天然是「任务」资源，放在同一 `/workstation` 前缀下即可，不必伪装成会话消息。
- **何时该重新考虑**：日常模式也开放异步时，`/tasks` 资源可同时承载日常异步作业，届时评估是否把资源名泛化。

### 决策 2：任务标识 = 灵思会话版本 id（`LinsightSessionVersion.id`）

- **备选**：A. 直接用 `session_version_id`（uuid）；B. 新建任务映射表。
- **选定**：A。
- **原因**：每次提交新建会话且只有一个版本（不续接，PRD DT-7），版本 id 与任务一一对应；已是随机 uuid，不可枚举；无需新表。
- **何时该重新考虑**：开放续接（同一会话多轮任务）时，仍以版本 id 为任务标识即可，无需改变。

### 决策 3：提交编排抽成共享核心，v1 SSE 与 v2 JSON 两个出口

- **备选**：
  - A. 从 `_task_mode_stream_completion`（`workstation/domain/services/chat_service.py:2465`）抽出 `submit_task_turn(...)`：内容安全 → 建会话与版本 → 写任务轮 → 入队；v1 在其外包 SSE 交接与标题生成，v2 在其外返回 JSON。
  - B. v2 另写一份编排。
- **选定**：A。
- **原因**：两份编排必然漂移（v1 已修过「先写任务轮再入队」的竞态，`chat_service.py:2526-2541` 注释）。共享核心增加两个 v2 必需的差异，由参数控制：① 入队失败在 v2 **不是 best-effort**——v1 可依赖前端 start-execute 兜底，v2 没有前端，入队失败即把版本置为「失败」并向调用方返回 503 / `26068`，不返回任务标识；② v2 **不调用 LLM 生成标题**，建会话时直接取任务描述首行前 30 个字作会话名（v1 在 SSE 流里最多等 30 秒生成标题，`chat_service.py:2462`）。原因：fire-and-forget 的后台任务会在请求结束后被回收、标题永远停在「New Chat」（v1 代码注释记录过这个坑）；且开放 API 的任务描述多为客户应用内置的同一段提示词，LLM 标题也会千篇一律。
- **何时该重新考虑**：v1 前端不再需要 start-execute 兜底时，v1 也可改为入队失败即报错。

### 决策 4：身份——提交时判定，worker 不恢复开放 API 身份

- **备选**：
  - A. 所有权限在提交时按当前 `OpenApiPrincipal` 判定；worker 沿用现状，只凭版本上的兼容 `user_id` 运行。
  - B. 版本上存 `OpenApiExecutionSnapshot`，worker 出队时 `restore_execution_context`（`open_api/domain/services/execution_context.py:70`）并复核凭据，与 workflow 的 Celery 任务一致。
- **选定**：A。
- **原因**：spec 边界情况经用户两次确认——执行身份在任务排队或执行期间失效，已受理任务继续执行至终态（2026-09-30）。B 的 `validate_execution_snapshot` 会在出队时因凭据吊销 / 账号停用直接拒绝，与该口径冲突。且 worker 执行期本就不做用户级权限判定（§2），恢复 permission actor 没有消费方。
- **代价**：与 workflow（F053 §6.1）在「吊销后排队任务是否执行」上行为不同，须写进对外文档（spec AC-36）。
- **何时该重新考虑**：worker 引入执行期权限过滤（例如知识检索按文件级可见性过滤）时，必须改为 B，否则自身身份下会按资源归属人的权限过滤——那是错误主体。

### 决策 5：会话主体标记——共享核心接收 `SessionSubject`

- **选定**：`LinsightWorkbenchImpl.submit_user_question`（`linsight/domain/services/workbench_impl.py:228`）增加可选 `session_subject` 参数；传入时新建的 `MessageSession` 经 `SessionSubject.stamp()` 写入主体标记与兼容 `user_id`。代表他人 → `natural_person`（`api_subject_type` 为空，出现在员工工作台）；自身身份 → `service_account`（带标记，被工作台列表 `api_subject_type IS NULL` 条件排除，`chat_session/domain/session_subject.py:139-142`）。附件提升使用 `subject.storage_partition`。
- **原因**：与日常模式开放 API 同一机制（spec AC-32、AC-33），不另造可见性规则。
- **提交时的 `login_user`**：取 `get_open_api_operator_async()`（`open_endpoints/domain/utils.py:62`）——代表他人为被代表用户；自身身份为资源归属人，且强制去掉管理员角色（`force_non_admin`）。它只用于旧表兼容字段与 LLM 调用，权限判定一律走 permission actor（决策 9）。
- **被否**：自身身份时把会话挂在一个虚拟用户下——F053 已裁定服务账号不建影子用户（INV-31）。
- **何时该重新考虑**：旧表的 `user_id` 外键放开、可直接记录服务账号主体时，去掉兼容 id。

### 决策 6：「来自开放 API」的标记存在版本上的新 JSON 列 `api_meta`

- **备选**：A. `linsight_session_version` 新增可空 JSON 列 `api_meta`；B. 从 `MessageSession.api_subject_type` 推断；C. 塞进 `question` 或 `tools`。
- **选定**：A。字段：`channel="open_api_v2"`、`instructions`（业务上下文指令，可空）、`credential_id`、`identity_mode`（审计冗余，便于排障）。
- **原因**：worker 需要据此切换「不提问」和「执行前复核技能」两种行为；B 不成立——代表他人时会话没有标记（归员工本人）；C 会污染工作台展示给员工的问题原文。
- **何时该重新考虑**：若日后工作台也需要「无人值守」执行，把 `channel` 泛化为执行选项。

### 决策 7：不提问——worker 按 `api_meta.channel` 同步去掉 `ask_user` 与澄清提示

- **选定**：`agent_factory.py` 组装主图时，`channel == "open_api_v2"` 则：工具列表不含 `ask_user`（`:1170`，含修复中间件列表 `:1131`）；系统提示词由实际装配的工具列表生成，去掉第 0 步「先澄清再动手」（`:112-122`）与 `ask_user` 使用规则（`:142-152`、`:163`），替换为无人值守段：「不得向用户提问；信息不足时按合理的默认假设推进，并在答复中单列一节写明所做假设」。业务上下文指令以独立段落追加在系统提示词之后，标明其优先级低于平台规则。
- **原因**：spec AC-21、AC-27；`linsight/AGENTS.md` prompt ⟺ tool 同步规则。只去工具不改提示词，模型会按第 0 步反复尝试澄清或把问题写进正文（参见 memory 中 qwen-max 把 ask_user 写成正文的实测）。
- **被否**：保留 `ask_user`、停车后由 API 自动回答「按默认假设」——停车是持久化等待状态，自动回答要伪造用户输入，且仍会出现「等待输入」状态。
- **何时该重新考虑**：开放「等待输入」状态（spec AC-27 留位）时，按调用方声明决定是否装配 `ask_user`。

### 决策 8：执行前复核——仅对开放 API 任务，技能缺失即失败

- **选定**：worker 装配技能时（`materialize_session_skills(..., strict=True)`），`channel == "open_api_v2"` 且所选技能中有不存在、未启用或复制失败的，抛 `SkillsUnavailableForRunError`，经 `_handle_task_failure` 以「失败」结束，失败说明列出技能名，不继续执行。模型无需改动：解析失败或已下线本就抛错并以「失败」结束（`agent_factory.py:1192-1231` → `task_exec.py:2454`）。
- **原因**：spec AC-19。工作台任务模式的静默丢弃是既有行为，本 Feature 不改（非目标）。
- **何时该重新考虑**：工作台也决定「技能缺失即失败」时，去掉 channel 条件。

### 决策 9：提交时校验逐项复用既有判定入口

| 入参 | 判定 | 入口 |
|---|---|---|
| 模型 | 在执行身份的工作台模型列表内，且存在、为 LLM、提供方存在、在线 | `WorkStationService.get_open_api_daily_config` 的 `models` + `OpenTaskModeService.model_is_usable`（`BishengBase.get_model_server_info`，不构造客户端）；失败 `26066`。配置查询的模型列表经同一 `model_is_usable` 过滤（`usable_models`） |
| 技能 | 在本租户已启用集合内（`LinsightSkillDao.list_enabled`，`strict_tenant_filter`） | 任一不在即 `26062`，`data.unavailable` 列出全部技能名 |
| 平台工具 | 工具组 `use` 动作 | `WorkStationService.afilter_tools_by_use_permission`（`workstation_service.py:556`）；不可用 `26067` |
| 文档知识库 | `Knowledge.type == 0`，`knowledge_library` 的 `use` 动作 | `KnowledgeService` 批量动作判定（与 `GET /api/v2/filelib/` 同一实现）；沿用知识模块既有 403 / 404 码 |
| 知识空间 | `Knowledge.type == 3`，可见（F048 对 `knowledge_space` 无 `use` 动作，`core/openfga/authorization_model_f048.py:60-83`） | 按当前 permission actor 的可见集合判定；沿用既有 403 / 404 码 |
| 附件 | 属于同一调用主体的上传引用 | `TempUploadService.assert_owned_references`（`knowledge/domain/services/temp_upload_service.py:40`），不属于 → 404 |
| 任务模式使用权限 | 仅代表他人：被代表用户的有效菜单含 `linsight_task_mode` | `UserPayload.assert_effective_web_menu_contains`（`user/domain/services/auth.py:840`）；缺失 `26063` |
| 内容安全 | 任务描述 + 业务上下文指令 | `SensitiveWordPolicyService.evaluate_workbench_user_text`（`sensitive_word/domain/services/sensitive_word_policy_service.py:367`）；命中 `26065`，`data.auto_reply` 为处置文案，不建会话 |

- **原因**：可用配置查询（决策 10）用同一批入口，保证「查到的提交时一定能用」（spec AC-05）。所有权限判定走当前 permission actor（HTTP 层已由 F053 设为服务账号或被代表用户），权限引擎异常原样抛出、由 v2 处理器转 503（INV-32，`permission/application/business_authorization.py:115-185` 不吞异常）。
- **何时该重新考虑**：worker 执行期引入权限判定（决策 4 的触发条件）时，提交时判定降为预检，执行期判定为准。
- **校验顺序**：身份与权限位（F053 管线）→ 任务模式使用权限 → 请求体形态 → 附件归属 → 模型 → 技能 → 工具 → 知识 → 内容安全 → 建会话入队。任一失败不写任何行。

### 决策 10：可用配置查询——主体接口 + 知识分页接口

- **选定**：
  - `GET /api/v2/workstation/config?run_mode=task`：返回 `models`（`id`、`name` 等，与日常一致）、`default_model_id`（租户 `linsight_default_model_id`，已被 `_filter_workbench_config` 过滤，`llm/domain/services/llm.py:376-393`）、`tools`（与日常同一过滤）、`skills`（`name`、`display_name`、`description`）。不带参数或 `run_mode=daily` 时，返回内容与现状逐字节一致。
  - `GET /api/v2/workstation/config/knowledge?type=library|space&name=&cursor=&page_size=`：按执行身份列出可用的文档知识库（`use`）或可见的知识空间，游标分页、按名称搜索。
- **原因**：模型、工具、技能数量有限，一次返回；知识库与知识空间可能很多，需要分页与搜索（spec AC-07），塞进同一个响应会让配置接口变慢且不可分页。两个接口同在 `/workstation/config` 下、同一权限位，仍是「扩展已有的配置查询」（PRD DT-9）。
- **何时该重新考虑**：技能或工具数量增长到需要分页时，按知识接口同样拆出。
- **被否**：让调用方改用 `GET /api/v2/filelib/`——要求 `knowledge:read`，且 `type=3` 返回的是「我创建或加入的空间」（`knowledge_space_service.py:2034`），服务账号不会「加入」空间，结果与提交判定口径不一致。

### 决策 11：产物下载经平台代理流式返回

- **选定**：`GET /api/v2/workstation/tasks/{task_id}/files/{file_id}`：在该任务 `output_result.final_files` 中按 `file_id` 查到对象键，校验任务归属后从 MinIO 流式读出，`Content-Disposition` 用 RFC 5987 `filename*`。结果中不返回任何链接。
- **原因**：PRD 要求不返回长期有效直链；MinIO 预签名默认 7 天，且私有化部署中 MinIO 主机常不对外（client AGENTS.md「MinIO presigned-URL host」坑）。按 `file_id` 在本任务清单内查找，天然避免 v1 `file_download` 「签发桶内任意对象」的问题（PRD 附录 A 第 2 项）。
- **被否**：返回短时效预签名链接——仍有主机可达性问题，且链接可被转发，归属校验只做在签发那一刻。
- **何时该重新考虑**：大文件下载占用后端带宽成为瓶颈时，改为「鉴权后签发一次性短链」并解决主机可达性。

### 决策 12：状态、进度与结果的投影

| 对外状态 | 内部 `SessionVersionStatusEnum` | 附带 |
|---|---|---|
| `queued` | `not_started` | `queue_position`：`LinsightQueue.index()` > 0 时为该值；返回 0 时为空（已出队、尚未置为执行中的瞬间） |
| `running` | `in_progress` | `progress`：`{done, total}`，按顶层待办行计数（`LinsightExecuteTaskDao.get_by_session_version_id(..., is_parent_task=True)`，`done` = `success` 行数）；尚无待办为空 |
| `waiting_input` | `waiting_for_user_input` | 本期不出现（决策 7），枚举保留（spec AC-27） |
| `completed` | `completed` | `partial` = `output_result.partial`；`result` 见下 |
| `failed` | `failed`、`sop_generation_failed` | `failure`：`{category, message}`，`category` = `output_result.error_type`，缺失时为 `unknown`（worker 崩溃清扫不写 `error_type`，`linsight/domain/utils.py:742-746`） |
| `terminated` | `terminated` | — |

- `result.answer`：`output_result.answer` 依次经 `strip_citation_markers`（`citation/domain/services/citation_prompt_helper.py:75`）与 `strip_citation_handles`（`citation/domain/services/citation_handle_service.py:546`）。
- `result.files[]`：由 `final_files` 投影为 `file_id`、`file_name`、`file_type`（扩展名）、`size`（读时 `stat_object`）、`primary`（下标 0，与工作台「首个即主交付物」一致，`linsight/domain/utils.py:420-423`）。**不输出 `file_path`、`file_url`**（前者是 worker 本地绝对路径）。
- `result.unavailable_deliverables[]`：`phantom_deliverables` → `reason=not_generated`；`invalid_deliverables` → `reason=invalid_format`。
- `result.attachments[]`：`LinsightSessionVersion.files` 中 `valid=false` 的条目，`reason` 取 `parsing_status`（`unsupported` / `failed` / `expired`）。
- 查询只读数据库与 Redis 队列，不消费任何事件流（PRD DT-3），不影响工作台 WebSocket。
- **被否**：直接返回 `public_dump()`——含本地路径与内部键名，且把 worker 的存储形状变成对外契约。
- **何时该重新考虑**：开放事件流时，进度改由事件驱动，本投影只保留终态结果。

### 决策 13：终止复用共享逻辑，已结束一律 409

- **选定**：把 v1 `terminate-execute`（`linsight/api/endpoints/linsight.py:473-549`）的动作（出队、置已终止、写任务轮、推终止事件）下沉到 `LinsightWorkbenchImpl.terminate(svid)`，v1、v2 共用。v2 在调用前判定：`completed`、`failed`、`sop_generation_failed`、`terminated` 一律 `26064`。
- **原因**：v1 只拦 `completed`、`terminated`，会把「失败」改写成「已终止」（§5 第 7 条）；v2 需要确定性的 409。v1 的判定本期不改，避免改变工作台行为。
- **被否**：v2 直接调用 v1 端点函数——F053 禁止 v2 import `*.api.*`（F053 design §5.E E3）。
- **何时该重新考虑**：修 v1 终止判定时，把终态判定也下沉到共享 `terminate`。

### 决策 14：错误码 26060–26068

| 码 | 类名（`common/errcode/open_api.py`） | HTTP | 场景 |
|---|---|---|---|
| 26060 | `OpenApiTaskModeSyncUnsupportedError` | 400 | 任务模式要求同步，或缺少 `execution` |
| 26061 | `OpenApiTaskConversationNotAcceptedError` | 400 | 任务模式传入 `conversationId` |
| 26062 | `OpenApiTaskSkillUnavailableError` | 400 | 技能不存在或未启用；`data.unavailable` 列名 |
| 26063 | `OpenApiTaskModeForbiddenError` | 403 | 被代表用户不具备任务模式使用权限（查询与提交同码） |
| 26064 | `OpenApiTaskAlreadyFinishedError` | 409 | 终止已结束的任务 |
| 26065 | `OpenApiContentBlockedError` | 400 | 内容安全拦截；`data.auto_reply` |
| 26066 | `OpenApiModelUnavailableError` | 400 | 模型不在可用列表、不存在或未上线；**日常模式同场景一并替换原裸 400**（`open_api/domain/services/daily_chat_service.py:35`） |
| 26067 | `OpenApiToolUnavailableError` | 400 | 任务模式所选平台工具不可用（日常模式的工具裸 400 本期不动） |
| 26068 | `OpenApiTaskQueueUnavailableError` | 503 | 入队失败（版本已置失败、不返回任务标识）。不复用 26030：后者语义是「密钥校验服务不可用」 |

- **为什么从 26060 起**：26045–26049 为 F053 预留（F053 design §6.3）；26050–26052 已被 `3.0-vibe` 托管应用占用（vibe `common/errcode/open_api.py`），vibe 日后从发版线合入时会撞号。
- 任务不存在或归属不匹配用既有 `NotFoundError` → 404，不新增码（防枚举）。
- 三语文案只落 `src/frontend/packages/locales/src/api_errors/*.json`；落码后按 C5 回写 `docs/constitution.md`，并在 release-contract 260 段登记。
- **何时该重新考虑**：F053 预留段 26045–26049 正式释放时不回迁，已分配的码保持不变。

---

## 4. 系统现状（接手必读）

### 4.1 数据流

**提交**：`POST /api/v2/workstation/chat/completions`（body `run_mode="task"`）
→ 端点按原始 body 的 `run_mode` 分派：缺省或 `daily` 走现有 `OpenDailyChatCompletionReq`（不变）；`task` 走 `OpenTaskSubmitReq`；其它值 `26017`
→ `OpenTaskModeService.submit(principal, req)`（新，`open_api/domain/services/task_mode_service.py`）：决策 9 校验
→ `submit_task_turn(...)`（新共享核心，自 `chat_service._task_mode_stream_completion` 抽出）：`submit_user_question(..., session_subject, api_meta, telemetry_source="api")` → `persist_task_turn_message` → `enqueue_session_for_execution`（失败即置失败并 503）
→ 返回 `{task_id, status: "queued", queue_position}`

**执行**：worker（不变）出队 → `agent_factory` 读 `api_meta.channel` 切换无人值守提示词与工具集（决策 7）→ 装配技能，缺失即失败（决策 8）→ 执行 → 写 `output_result` 与状态。

**查询**：`GET /api/v2/workstation/tasks/{task_id}` → 归属校验 → 读版本、待办行、队列位置 → 决策 12 投影。

**下载**：`GET /api/v2/workstation/tasks/{task_id}/files/{file_id}` → 归属校验 → 清单内查找 → MinIO 流式返回。

**终止**：`POST /api/v2/workstation/tasks/{task_id}/terminate` → 归属校验 → 终态判定 → `LinsightWorkbenchImpl.terminate`。

**配置**：`GET /api/v2/workstation/config?run_mode=task`、`GET /api/v2/workstation/config/knowledge`（决策 10）。

**归属校验**（查询、下载、终止共用）：由 `task_id` 取版本 → 取其 `MessageSession` → `session_subject_from_principal(principal).matches(session)`（`chat_session/domain/session_subject.py:110`）；不匹配或不存在一律 404。

### 4.2 关键数据结构 / 字段约定

| 字段 / 结构 | 类型 / 格式 | 说明 | 谁会消费 |
|---|---|---|---|
| 提交 body | `run_mode:"task"`、`execution:"async"`、`text`、`instructions?`、`model`、`skills?[]`、`tools?[]`、`knowledge_ids?[]`、`knowledge_space_ids?[]`、`files?[]`、`clientTimestamp` | `extra=forbid`；`text` 1–20000 字符；`instructions` ≤ 4000；两类知识各 ≤ 50；`files` 为 `/api/v2/knowledge/upload` 返回的引用 | 调用方 |
| 提交响应 `data` | `{task_id, status, queue_position}` | UnifiedResponseModel 信封 | 调用方 |
| 任务视图 `data` | `{task_id, status, queue_position?, progress?, partial?, failure?, result?, created_at, updated_at}` | `result` 仅 `completed` 时出现 | 调用方 |
| `linsight_session_version.api_meta` | JSON，可空 | `{channel, instructions, credential_id, identity_mode}`；工作台发起的任务为空 | worker、审计排障 |
| 埋点 `NEW_MESSAGE_SESSION.source` | `"api"` / `"platform"` | 开放 API 发起写 `"api"`，与 workflow 发布调用一致（`workflow/domain/services/published_workflow_service.py:84`） | 运营统计 |

### 4.3 数据库迁移与版本契约登记

- **Alembic**：一个迁移，`linsight_session_version` 增加可空列 `api_meta`（`JsonType`），无回填、无索引；降级删列。MySQL 与 DM8 各跑一次升级 / 降级。
- **release-contract**（`features/v3.0.0-beta1/release-contract.md`）：表 1 新增 F073 行（无新领域对象；`LinsightSessionVersion.api_meta` 增量归 F073）；表 3 记依赖 F053 / F063 / F048；表 4 记修订 F053 日常模式「模型不可用」错误码（26066）与 `26017` 收窄；260 段登记 26060–26068。

### 4.4 关键模块职责

| 模块 / 文件 | 职责 | 不做什么 |
|---|---|---|
| `open_endpoints/api/endpoints/workstation.py` | 路由、`@open_api_scope("chat:invoke")`、按 `run_mode` 分派 | 不写业务判定 |
| `open_api/domain/services/task_mode_service.py`（新） | 校验、调用共享核心、归属校验、状态与结果投影、下载流 | 不直接写 ORM（经 DAO / 既有 service） |
| `open_api/domain/schemas/task_mode.py`（新） | 请求与视图模型 | — |
| `workstation/domain/services/task_submit_service.py`（新） | 共享提交核心（v1、v2 共用） | 不产出 SSE、不生成标题 |
| `linsight/domain/services/workbench_impl.py` | `submit_user_question` 接收主体与 `api_meta`；新增 `terminate` | 不做开放 API 准入 |
| `linsight/domain/services/agent_factory.py` | 按 `channel` 装配工具与提示词 | — |
| `linsight/domain/services/skill_provisioning.py` | 开放 API 任务技能缺失即失败 | 工作台行为不变 |

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | 任务分支原先丢弃 `session_subject`（`chat_service.py:2455-2456`），建会话不写主体标记 | 自身身份的任务落进资源归属人的工作台（PRD 附录 A 第 5 项） | 决策 5 |
| 2 | 任务运行时按 id 直接加载知识库，无用户级读权限检查（`task_exec.py:1551-1575`、`knowledge/domain/models/knowledge.py:303-306`） | 调用方可检索任意知识库 | 决策 9 提交时校验 |
| 3 | 技能中不存在或未启用的被静默丢弃（`skill_provisioning.py`） | 调用方以为技能生效 | 决策 9 提交时拒绝 + 决策 8 执行前复核 |
| 4 | 模型在入队之后才解析；v1 的标题模型查找在入队后抛错，请求失败但任务已入队 | 返回失败却有任务在跑 | 决策 9 提交时预解析 |
| 5 | `ask_user` 始终注入，提示词第 0 步要求先澄清；无关闭开关 | API 任务停在「等待输入」永久挂起 | 决策 7 |
| 6 | `LinsightQueue.index()` 对「已出队 / 已结束 / 不存在 / 续跑项」都返回 0（`linsight/worker.py:198-221`） | 把 0 当成「排第 0 位」 | 决策 12：0 → 空 |
| 7 | v1 终止只拦 `completed` / `terminated`，会把「失败」改写成「已终止」 | v2 终止失败任务变成已终止 | 决策 13 |
| 8 | 产物条目的 `file_path` 是 worker 本地绝对路径，`public_dump` 原样输出（`linsight/domain/utils.py:455-462`、`linsight_session_version.py:157-169`） | 泄露服务器路径 | 决策 12 投影不输出 |
| 9 | v1 灵思端点多处不校验归属：`task-message-stream`、`queue-status`、`batch-download-files`、`download-md-to-pdf-or-docx`、`file-parsing-status`；且自身身份任务的兼容 `user_id` 是资源归属人，归属人凭 id 可经 v1 读到任务详情 | 越权读取 | **本期不修**（用户 2026-09-30 裁定与日常模式同类问题另行处理）；v2 端点不复用这些 v1 端点 |
| 10 | 上传返回的预签名链接标 7 天，临时桶实际 3 天回收 | 对外文档写错有效期 | 对外文档写「上传后 3 天内开始执行」，见第 16 条 |
| 11 | 任务模式有意不读个人知识库开关（`task_exec.py:1556-1558`），个人知识库类型已下线 | 误开放个人知识库 | spec AC-15；schema 不含该字段 |
| 12 | 自身身份下 LLM 调用的 `invoke_user_id` 是资源归属人（`agent_factory.py:1225`，外键约束） | 模型用量统计记在归属人名下 | 与日常模式一致；审计记录可查到服务账号，见 §8 |
| 13 | v1 提交遇到「会话不存在或不属于你」会静默新建会话（`workbench_impl.py:271-276`） | — | v2 不接受 `conversationId`（26061），不经过该分支 |
| 14 | 内容安全拦截在 v1 会建会话并写一条自动回复 | v2 若复用会留下空会话 | v2 在建会话前判定，命中即返回 26065，不写任何行 |
| 15 | `_to_linsight_submit` 静默跳过没有 `file_id` 的附件，而开放 API 上传返回值里没有 `file_id` | 附件全部丢失、任务照常跑 | `OpenTaskSubmitReq` 把附件定义为 `{file_path, file_name}`，`to_internal()` 为每个附件生成 `file_id` |
| 16 | worker 执行时才从临时桶读附件，排队超过 3 天即过期 | 以为提交时已转存、对外文档写错 | 对外文档写明；结果中列为「已过期」 |
| 18 | 顶层待办行里有一条 `id == svid` 的会话级伪任务（「执行准备」，`task_exec.py` `_ensure_session_pseudo_task`） | 进度总数多 1、且永远有一项不完成 | `_progress` 排除该行 |
| 19 | `KnowledgeSpaceService.alist_mine_and_joined_cursor` 的「我创建的」按 `login_user.user_id` 查，自身身份下是资源归属人 | 配置查询列出归属人的空间，提交时却按服务账号判可见被拒（违反 AC-05） | 知识空间列表改为按 permission actor 的 `list_visible_objects` 枚举 |
| 20 | 提交端点为按 `run_mode` 分派改收原始 dict，FastAPI 不再为它生成请求体 schema | 对外接口文档显示成无类型对象 | `open_api/api/openapi_schema.py` `_publish_chat_completion_request` 注入 `oneOf`（日常 / 任务两个模型）；两个分支用 `validate_body` 复现 FastAPI 的校验错误形状（`loc` 前缀 `body`、无 `url`），日常模式错误响应不变 |
| 22 | v1 `GET /sop/showcase/result` 直接返回原始版本模型、不做归属校验 | 同租户拿到任务 id 即可读到 `api_meta`（调用方指令、凭据 id） | 该端点显式 `exclude={"api_meta"}`；越权问题本身属既有、另行处理 |
| 21 | `open_endpoints` 各端点从 `bisheng.open_api.api.dependencies` 导入 v2 鉴权依赖，arch-guard 报 RULE-5 | 误以为本 Feature 引入 | F053 既有接入方式，改动前即报；本期不动 |
| 17 | v1 终止相关测试原先 patch 的是端点模块上的依赖 | 抽出共享函数后测试失败或空跑 | 终止主体已移到 `LinsightWorkbenchImpl.terminate`，测试改 patch 新位置 |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 契约 | 形式 | 谁在用 |
|---|---|---|
| `POST /api/v2/workstation/chat/completions`（`run_mode="task"`） | HTTP，JSON 响应 | 外部应用、workflow 代码节点 |
| `GET /api/v2/workstation/tasks/{task_id}` | HTTP | 同上 |
| `GET /api/v2/workstation/tasks/{task_id}/files/{file_id}` | HTTP，文件流 | 同上 |
| `POST /api/v2/workstation/tasks/{task_id}/terminate` | HTTP | 同上 |
| `GET /api/v2/workstation/config?run_mode=task`、`GET /api/v2/workstation/config/knowledge` | HTTP | 同上 |
| 错误码 26060–26068、`26017` 收窄 | 对外可观测 | 调用方、三语文案 |
| `submit_task_turn`、`LinsightWorkbenchImpl.terminate` | 内部 Python API | v1 工作台任务模式（行为不变） |
| `linsight_session_version.api_meta` | 数据列 | worker |

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 风险点 |
|---|---|---|
| F053 密钥管线、`OpenApiPrincipal`、`SessionSubject`、`OPEN_API_SCOPES` 登记 | 内部契约 | 新端点漏登记 → 26031 |
| F053 异常处理器按路径识别 `run_mode` / `execution`（`exception_handlers.py:169`） | 隐式契约 | 分派改到端点后须同步调整处理器，否则 `run_mode="task"` 仍被映射为 26017 |
| F048 `use` / 可见性动作 | 权限契约 | 动作名变化会使提交判定与查询失配 |
| F063 内容安全策略 | 内部 API | 仅商业版生效 |
| 灵思 worker 状态机、`output_result` 形状 | 隐式数据契约 | worker 改键名（`answer`、`final_files`、`partial`、`error_type`）会静默破坏投影；投影层须有契约测试 |
| MinIO `stat_object` / 流式读 | 存储 | 产物对象被删时下载返回 404 |

---

## 7. 测试与可观测

- **单元**：请求分派与 schema（含日常模式回归：同一请求体响应不变）；决策 9 每项的拒绝路径与错误码；状态与结果投影（覆盖六种内部状态、`partial`、缺 `error_type`、幻影与格式错误交付物、附件失败）；归属校验四种主体组合（spec AC-28）；终止的终态判定；`agent_factory` 在 `channel` 两种取值下的工具列表与提示词（断言二者同步）。
- **权限反向测试**：自身身份下资源归属人有权、服务账号无权的知识库必须被拒（F053 §8 第 4 条同类）；权限引擎抛错时配置查询返回 503 而非空列表。
- **集成 / e2e**（`/e2e-test`）：spec AC-35 最小表单流程，两种身份各一遍；代表他人的任务在员工工作台可打开并渲染任务面板；自身身份的任务不出现在归属人列表。
- **手动验证**（test 环境，服务账号密钥 `$KEY`，平台地址 `$HOST`）：
  ```bash
  curl -s "$HOST/api/v2/workstation/config?run_mode=task" -H "Authorization: Bearer $KEY"
  curl -s -X POST "$HOST/api/v2/knowledge/upload" -H "Authorization: Bearer $KEY" -H "X-End-User: demo" -F file=@a.pdf
  curl -s -X POST "$HOST/api/v2/workstation/chat/completions" -H "Authorization: Bearer $KEY" -H "X-End-User: demo" \
    -H 'Content-Type: application/json' \
    -d '{"run_mode":"task","execution":"async","clientTimestamp":"2026-09-30T10:00:00","model":"<id>","text":"...","files":[<upload 返回>]}'
  curl -s "$HOST/api/v2/workstation/tasks/<task_id>" -H "Authorization: Bearer $KEY" -H "X-End-User: demo"
  curl -s -OJ "$HOST/api/v2/workstation/tasks/<task_id>/files/<file_id>" -H "Authorization: Bearer $KEY" -H "X-End-User: demo"
  ```
  代表他人时把 `X-End-User` 换成 `X-On-Behalf-Of: <user_id>`（密钥须持 `delegate`），再以该员工登录工作台核对任务可见。
- **可观测**：逐调用审计沿用 F053 中间件（`open_api/api/middleware.py`，`action="open_api.call"`）；worker 日志以 `svid` 关联；`api_meta.credential_id` 便于从任务反查密钥。

---

## 8. 后续改进 / 不打算做的事

- **模型用量按服务账号计量**：受外键约束，自身身份下 LLM 调用记在资源归属人名下（§5 第 12 条），与日常模式一致；spec AC-34 已按此口径改写（2026-09-30 用户确认）。若需按服务账号出账，需另立项改 LLM 调用记账主体。
- **v1 灵思端点归属校验**（§5 第 9 条）：另行处理。
- **worker 恢复开放 API 身份**：触发条件见决策 4。
- **事件流、续接、限流、幂等、回调**：见 spec 范围边界。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-09-30 | 初版 | spec 评审通过 |
| 2026-09-30 | 用户确认 design；spec AC-34 按自身身份模型用量记在资源归属人名下改写 | design 评审 |
| 2026-09-30 | `/code-review` 修正：配置查询的模型列表经 `model_is_usable` 过滤（原先会列出提交时被拒的下线 / 非 LLM 模型）；入队失败改为 `26068`；v1 `sop/showcase/result` 不再回显 `api_meta` | code review |
| 2026-09-30 | 决策 3 标题改为截取任务描述；决策 8 复制失败也判失败；§2 附件有效期订正；§5 增第 15–17 条 | 实现 Wave 1–2 |
