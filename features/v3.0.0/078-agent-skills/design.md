# Design: 助手节点与助手应用调用技能

> **本文档定位 — 现状快照（Why this How）**
>
> - `spec.md` 回答做什么（目标、AC、边界）。
> - `design.md`（本文）回答为什么这么实现：关键决策、运行时不直观的事实、对外契约。
> - `tasks.md` 是流水账：拆了哪些任务、做了什么改动。
>
> 调整原则：实现变化时覆盖更新本文，只留今天的状态，但每个决策保留「为什么 + 被否方案」和坑。推翻已 ★ 确认的决策时，停下与用户重新确认。

**关联**: [spec.md](./spec.md) · [tasks.md](./tasks.md)
**版本**: v3.0.0（开发分支 `feat/SEC-3.0.0-1016`）
**最后更新**: 2026-10-16（初版，尚未实现）

> 本文中的「现状」指 `origin/feat/3.0.0` 41bf8c650 的代码。「目标」指 F078 实现后的状态。路径以 `src/backend/bisheng/`（简写 `B/`）和 `src/frontend/`（简写 `F/`）为根。

---

## 1. 目标与非目标

- **目标**：让 workflow 助手节点和独立助手应用复用任务模式的技能能力。配置了技能的运行获得会话级工作区、文件工具和代码执行器，生成的交付文件以文件卡片交给用户。两处入口共用一个 Agent 构建器，配不配技能都走同一条执行路径。
- **非目标**：不改 ReAct 执行方式；不改技能库的管理与存储；不做日常对话；不做工作区容量上限；不修任务模式既有的下载越权缺口（见 §8）。

---

## 2. 关键约束

全局铁律遵循 `docs/constitution.md` C1–C8。本功能特有的约束如下。

| # | 约束 | 来源 | 对方案的影响 |
|---|---|---|---|
| K1 | 配不配技能必须走同一条技术路径，不维护两套 | 用户拍板（2026-10-16） | 决策 1 |
| K2 | 未配置技能的助手节点和助手应用行为与改动前一致 | spec AC-25、V3-INV-4 | 决策 1 否决整体 deepagents |
| K3 | workflow 节点同步执行：Celery `workflow_celery` 队列线程池里调用 `node.run`，`async_mode=False` | `B/worker/workflow/tasks.py:79-90`、`B/workflow/nodes/base.py:250` | 决策 4 |
| K4 | 多节点部署是默认假设，本地盘只能做缓存 | C8 | 决策 3：工作区以 MinIO 为准 |
| K5 | 技能查询依赖当前租户上下文（`strict_tenant_filter`，不回落 Root） | `B/linsight/domain/models/linsight_skill.py:212-218` | 运行前必须设置租户上下文 |
| K6 | 下载只限登录且有权查看会话的用户 | spec AC-28、AC-29、AC-37 | 决策 7：不复用任务模式下载接口 |
| K7 | `assistant` 表新增列要兼容 DM8：用 `JsonType`，迁移带 `column_exists` 守卫 | C2 | 决策 9 |

**Constitution Check**：

| 条款 | 结论 |
|---|---|
| C1 分层 | 合规。新增的技能按名查询走 Repository（`B/linsight/domain/repositories/`），不新增 DAO 入口；Service 里不写 ORM。 |
| C2 双 DB | 合规。新列用 `JsonType`，不用 `JSON_EXTRACT` 类查询。 |
| C3 多租户 | 合规。技能查询依赖自动注入的租户上下文；Celery 线程里由 runner 设置上下文，不手写 tenant 条件。 |
| C4 权限 | 合规。会话归属不是 ReBAC 资源，沿用 chat_session 现有的 `SessionSubject` 归属校验；workflow 与助手的使用权限仍由既有入口校验。 |
| C5 错误码 | 合规。使用技能管理段 11061–11063，并在 release-contract 登记。 |
| C6、C7 | 不涉及新密钥；前端 store 不直接发 HTTP。 |
| C8 本地盘 | 合规。工作区与交付文件以 MinIO 为准，本地目录每次运行新建、结束即删。 |

---

## 3. 方案对比与选定

### 决策 1：Agent 构建方式——统一用 `create_agent`，技能以 middleware 按配置挂载

- **备选**：
  - A. 两处 function call 分支都改用 `langchain.agents.create_agent`。构建器根据配置决定 middleware 列表：没有技能时列表为空，配置了技能时挂文件工具、技能、代码执行器等组件。
  - B. 统一改用 `deepagents.create_deep_agent`。
  - C. 配置了技能时用 `create_deep_agent`，否则保留现状。
- **选定**：A。
- **原因**：
  - C 违反 K1。
  - B 违反 K2。`create_deep_agent` 总会追加默认提示词 "You are a deep agent…"，总会装 `TodoListMiddleware`、`FilesystemMiddleware` 和自动压缩。它的子代理和 todo 可以关掉，但开关只在 `HarnessProfile` 里。`HarnessProfile` 是进程级全局注册表，按「提供方:模型名」查找（`deepagents/profiles/harness/harness_profiles.py:1255`），不能按单个助手设置。毕昇的模型大多走 OpenAI 兼容接口，key 形如 `openai:qwen-max`，注册一份裁剪配置会同时改变同进程里用这些模型的任务模式。它还是 beta API。
  - A 和任务模式用同一批 middleware 类，以后的能力扩展（任务规划、子代理、压缩）都在同一条路径上追加。
- **何时该重新考虑**：产品决定所有助手默认都具备任务规划、子代理和文件系统，并接受现有助手的行为一起变化。

### 决策 2：共享代码放在新模块 `B/agent_runtime/`

- **备选**：
  - A. 新建业务模块 `agent_runtime`（`domain/services` + `api/endpoints`），它依赖 linsight 的技能与工作区服务，被 workflow 节点和助手应用调用。
  - B. 放在 `B/linsight/domain/services/` 下。
  - C. 放在 `B/common/` 下。
- **选定**：A。
- **原因**：
  - C 违反 arch-guard RULE-1：`common/` 不能 import `linsight` 等业务模块，而构建器必须用 `WorkspaceBackend`、`materialize_session_skills`。
  - B 会让任务模式模块承载助手节点和助手应用的生命周期逻辑。release-contract 已登记「助手工作区」归 F078，不归 F035。
  - workflow 节点和 `B/api/services/` 下的代码只受 RULE-7/8/9 约束，可以 import `agent_runtime`。
- **何时该重新考虑**：日常对话也接入技能时，评估 `agent_runtime` 是否要承接任务模式的部分逻辑。

### 决策 3：工作区以 MinIO 为准，复用 `WorkspaceBackend`，key 由会话推导

- **备选**：
  - A. 复用 `WorkspaceBackend(svid, minio, file_dir)`。`svid` 传 `agent/{会话键}/{运行面}`，对象落在 `workspace/agent/...`。不建数据库表，前缀由会话 ID 确定性推导。
  - B. 新建工作区表，记录每个工作区的前缀和归属。
- **选定**：A。
- **原因**：
  - `WorkspaceBackend` 只把 `svid` 当字符串拼进对象键（`workspace_backend.py:107`、`:542`），没有绑定 `LinsightSessionVersion`，可以直接复用。
  - 前缀可以从会话 ID 推导出来，C8 要求的「数据库行记指针」由会话表本身承担，不必新建表。交付文件另有指针（决策 6）。
- **工作区键**：
  - workflow 正式会话：`agent/{chat_id}/wf-{node_id}`。同一会话里的多个助手节点各用各的工作区（AC-20）。
  - 助手应用正式会话：`agent/{chat_id}/assistant`。
  - 调试临时会话：`agent/tmp-{临时会话 ID}/...`（决策 8）。
  - 一次性工作区（评测、助手开放 API）：`agent/once-{uuid}/assistant`，运行结束即删。
  - 同一会话的工作区共享前缀 `workspace/agent/{chat_id}/`，删除会话时按前缀一次清理（AC-23）。
- **每次运行的本地生命周期**（`AgentWorkspace` 服务负责）：
  1. 在 `CACHE_DIR/agent_runtime/{工作区键哈希}/{运行 ID}` 新建本地目录。目录名带运行 ID，避免同一 worker 上并发运行互相覆盖。
  2. 从 MinIO 把该工作区前缀下除 `skills/` 以外的文件全部拉到本地（「水合」）。不水合的话，本地代码执行器看不到上一轮生成的文件，AC-21、AC-22 不成立。
  3. 记录基线指纹 `snapshot_file_fingerprints`。
  4. 清空本地和 MinIO 的 `skills/`，重新拷入本次配置的技能（AC-11：始终用当前版本）。
  5. 拷入输入文件到 `uploads/`（仅助手节点，AC-10）。
  6. 运行结束后收集交付文件（决策 6），然后 `tool.close()`、`release_local_run(file_dir)`，最后删除本地目录。
- **何时该重新考虑**：单个工作区文件很多、每轮水合耗时明显时，改为按需拉取，并让代码执行器支持 copy-in。

### 决策 4：同步的 workflow 节点通过 `run_async_safe` 调用异步准备步骤

- **备选**：
  - A. 构建器的准备步骤（查技能、拷技能、水合）写成 async。workflow 节点在 Celery 线程里用现有的 `B/utils/async_utils.py:118` `run_async_safe` 调用。Agent 本身仍用同步 `invoke`。
  - B. 把 AgentNode 改成 async 节点。
- **选定**：A。
- **原因**：workflow 引擎整体是同步模式（K3）。只改一个节点为 async 需要改引擎，超出范围。`run_async_safe` 专为「Celery 线程里调异步客户端」设计，使用进程级常驻事件循环。
- **注意**：`run_async_safe` 默认超时 10 秒，水合和拷技能要显式传更长的超时。
- **何时该重新考虑**：workflow 引擎改为 async 模式时，直接 await。

### 决策 5：技能可用性先按名字逐个判定，再拷贝

- **备选**：
  - A. 运行前先按名字查技能行，不过滤启用状态：行存在但已停用，报「已被管理员停用」；行不存在，报「已被管理员删除」。全部可用后，再调用 `materialize_session_skills(..., strict=True)` 拷贝。
  - B. 直接用 `materialize_session_skills(strict=True)` 的 `SkillsUnavailableForRunError`。
- **选定**：A。
- **原因**：`materialize_session_skills` 只按「已启用集合」判断，停用和删除都表现为「不在集合里」，区分不了（`skill_provisioning.py:118-123`）。AC-12 和 AC-30 要求两种不同的错误信息。
- **实现要点**：在 `B/linsight/domain/repositories/` 新建技能查询 Repository（接口 + 实现，参照 `B/knowledge/domain/repositories/` 的结构），提供按名字批量查询、不过滤 `enabled` 的方法，仍受租户过滤约束（K5）。不在 `LinsightSkillDao` 上加方法，因为 C1 禁止为新功能新增 DAO 入口。
- **何时该重新考虑**：技能库改为软删除时，可以合并成一次查询。

### 决策 6：交付文件沿用任务模式的判定规则，存成会话附件

- **判定**：复用 `B/linsight/domain/utils.py:397` 的 `select_deliverables(file_details, baseline)` 和 `NON_DELIVERABLE_ZONES`（`:118`）。和任务模式不同的一点：格式校验失败的文件不丢弃，保留并打上 `format_error` 标记（spec AC-33）。任务模式的 `get_final_result_file` 会丢掉这类文件，所以不复用它。
- **存储备选**：
  - A. 交付文件拷到会话附件对象 `chat/{user_id}/agent/{chat_id}/{file_id}{ext}`，文件描述里带 `file_id` 和 `object_name`，写进该轮消息的 `files` 字段。
  - B. 沿用输出节点的做法，只存 7 天预签名链接。
- **选定**：A。
- **原因**：
  - 现有删除会话的 `_remove_attachments` 会按 `object_name` 删掉消息里的全部附件（`B/chat_session/domain/chat.py:141-162`），AC-23 的交付文件清理不用另写。
  - 现有 `resolve_attachment_url`（`chat.py:165-188`）已实现「先校验会话归属，再从消息里取对象名，最后签发短时链接」的流程，满足 AC-18 和 AC-28。
  - B 的链接 7 天后失效，也没有对象名，会话删除时清不掉。
- **何时该重新考虑**：交付文件需要在会话之外共享时。

### 决策 7：下载走新的鉴权跳转接口，不复用任务模式下载接口

- **选定**：新增 `GET /api/v1/agent-runtime/files/{session_key}/{file_id}`。先鉴权，再 302 跳转到短时预签名链接。AC-16 输出变量和开放 API `files` 字段里给出的都是这个地址。
- **鉴权**：
  - 正式会话：用 `SessionSubject` 校验调用方拥有该会话（`B/chat_session/domain/session_subject.py:110-125`、`chat.py:76` `get_subject_session`）。普通登录用户和开放 API 身份（PAT、服务账号）走同一套判断。
  - 临时会话：校验 Redis 中登记的发起人（决策 8）。
  - 对象名一律从服务端记录里取，不信任请求参数。
- **被否方案**：复用 `/api/v1/linsight/workbench/file_download`。它直接预签名调用方传来的 `file_url`，不校验该文件是否属于这个会话（`B/linsight/api/endpoints/linsight.py:138-169`），而且绑定 `LinsightSessionVersion`。
- **何时该重新考虑**：平台统一文件下载网关时，迁到统一网关。

### 决策 8：调试窗口的临时会话登记在 Redis，三重清理

- **临时会话 ID**：
  - 助手调试：`ChatClient` 在 `chat_id` 为空时生成，保存在该 WebSocket 连接对象上，同一连接内的多次消息共用。注意现状是每条调试消息都重建 Agent（`B/common/chat/client.py:210-228`），所以 ID 必须放在连接对象上，不能放在 Agent 上。
  - workflow 调试：使用 `WorkflowClient` 为空 `chat_id` 生成的 `hash_key`（`B/common/chat/clients/workflow_client.py:175`），并通过 `Workflow → GraphEngine → 节点` 参数传下去。
  - workflow 单节点测试（`WorkFlowService.run_once`，`B/api/services/workflow.py:855-923`）：它是一次 HTTP 请求，没有会话，也没有 WebSocket。每次测试生成一个新的临时会话 ID，交付文件在测试结果里可下载；因为没有关闭事件，只靠第 2、3 步清理。
- **登记**：Redis 键 `agent_runtime:tmp_session:{ID}` 存 `{user_id, tenant_id}`，TTL 24 小时，每次运行刷新。下载接口据此判定发起人（AC-37）。
- **清理**：
  1. WebSocket 关闭时（`workflow_client.py:51-67`、助手 `ChatClient` 关闭钩子）删除 `workspace/agent/tmp-{ID}/` 前缀和临时交付文件。
  2. 临时交付文件放在 tmp 桶，tmp 桶已有 7 天生命周期过期规则（`B/core/storage/minio/minio_storage.py:252-262`），兜底异常断开。
  3. 临时工作区在 public 桶，没有生命周期规则，由 Celery Beat 定时任务按前缀扫描，清理 Redis 登记已过期的 `tmp-*` 目录。
- **何时该重新考虑**：如果平台给 public 桶的 `workspace/agent/tmp-` 前缀配置了生命周期规则，可以删掉第 3 步。

### 决策 9：技能配置的存储

- **助手节点**：节点参数新增 `skill_list: [{key: 技能名, label: 显示名}]`，与 `tool_list` 形状一致。节点参数由前端整体提交，后端在运行时再按决策 5 校验，不信任提交内容。
- **助手应用**：`assistant` 表新增 `skill_names` 列，类型为 `JsonType`、可空。`None` 和 `[]` 都表示不配置技能。
- **被否方案**：存进 `AssistantLink`。该表只有 `tool_id`、`flow_id`、`knowledge_id`，没有可以存技能名的列，而 `flow_id` 已经表示 workflow。改表结构的代价比加一个 JSON 列大，而且本期不需要按技能反查助手。
- **命名**：代码和接口里一律叫 `skill_names` / `skill_list`，不叫 `skill`。原因是 `flow_list`、i18n 键 `build.skill` 在助手里已经表示「workflow」（`B/api/v1/schemas.py:290-292`）。
- **何时该重新考虑**：需要「哪些助手用了某技能」这类反查时，改成关联表。

### 决策 10：未配置代码执行器时的判定与提示

- **判定**（`B/agent_runtime/domain/services/code_tool.py`）：读取内置工具 `bisheng_code_interpreter` 的工具行，结果分三种状态。
  - `missing`：没有工具行，视为平台未配置代码执行器。
  - `ready`：工具行存在即可构建。配置为空时，执行器类型默认是 `local`，与任务模式一致，所以「配置为空」不算未配置。
  - `error`：构建时抛出异常，包括配置错误和运行用户没有该工具的使用权限（`ToolExecutor.init_by_tool_id` 会校验 `use` 权限）。记 ERROR 日志，对外表现与 `missing` 相同。
  - 任务模式遇到构建异常只记日志、继续运行（`B/linsight/domain/services/workbench_impl.py` 的 `init_linsight_config_tools`）。F078 不这样做，因为 C8 要求不能静默降级：两种不可用状态都要向用户提示。
- **提示**（AC-09）：在输出事件和消息的 `extra.agent_notices` 里放提示代码，前端按 i18n 渲染提示条；workflow 运行日志和助手工具调用记录各加一条同样的提示。模型的回答文字和 AC-16 输出变量保持不变，下游节点不受污染。
- **复用**：任务模式 `_init_bisheng_code_tool` 里「把执行器配置指向工作区」的部分，已抽成纯函数 `bind_code_config_to_workspace(code_config, file_dir, workspace_prefix)`（`B/linsight/domain/services/code_tool_config.py`），任务模式和 F078 共用。查工具行、选择工具、构建工具仍由各自的调用方负责。F078 的入口是 `abuild_workspace_code_tool(...)`，返回 `CodeToolResult(tool, status, reason)`。
- **E2B 执行器**：它的文件列表在构建工具时就固定了（`e2b_executor.py:297-379`），所以代码执行工具必须在水合和拷技能之后构建。

### 决策 11：技能相关提示词由 F078 自己的 middleware 追加

- **内容**：从任务模式 `_build_linsight_system_prompt` 的技能段（`B/linsight/domain/services/agent_factory.py:412-446`）提炼成通用版本，包括三条：先完整读完 SKILL.md 再动手，不要和产出放在同一轮并行调用；交付结果写到 `output/`；有执行器时按技能脚本生成文件。
- **变体**：
  - 无执行器：改为「按技能说明尽量完成，脚本无法执行」。
  - 助手应用开放 API：去掉写文件的引导，改为「本次只能用文字交付结果」（AC-35）。
- **位置**：作为 system prompt 尾部追加，创建者自己的提示词不改。不复用任务模式的提示词模板，因为它带有 `ask_user`、`export_*`、编号步骤等任务模式专属占位符。

---

## 4. 系统现状（接手必读）

### 4.1 数据流（目标状态）

**助手节点（workflow）**

`WorkflowClient` → Celery `execute_workflow` → `GraphEngine` → `AgentNode.run` → `agent_runtime.AgentRunner` → Agent → 收集交付文件 → `StreamMsgOverData.files` → `RedisCallback.on_stream_over` → 消息落库与 WebSocket 推送 / 开放 API 事件

1. `AgentNode.__init__` 读取 `skill_list`（`B/workflow/nodes/agent/agent.py:193` 起）。会话键来自新传入的 `chat_id`；没有 `chat_id` 时用 `hash_key`。
2. `_init_agent` 调用 `AgentRunner.prepare(...)`。它判定技能可用性、准备工作区、构建代码执行工具，返回 middleware 列表和附加工具。没有配置技能时返回空列表，不建工作区。
3. 用 `create_agent(llm, tools, system_prompt=..., middleware=...)` 构建 Agent。ReAct 分支不变；配置了技能但模型是 ReAct 时报错 11063（AC-13）。
4. `_run_once` 照旧 `invoke`。批量模式下每个批次各自做基线和交付文件收集（AC-17）。
5. 运行结束后，`AgentRunner.finish()` 收集交付文件、上传为会话附件，返回文件描述列表。节点把它放进 `StreamMsgOverData.files`，并写入输出变量 `{node_id}.deliverables`（AC-16）。

**助手应用**

`ChatClient.handle_gpts_message` → `AssistantAgent.run` → 同一个 `AgentRunner` → 回答消息的 `files` 和 `extra.agent_notices` → WebSocket `end` 事件 → 前端渲染文字和文件卡片

- 正式会话用 `chat_id`；调试用连接上的临时会话 ID；评测和开放 API 用一次性工作区。
- `init_assistant` 不准备工作区。`update_status` 上线校验（`B/api/services/assistant.py:604`）和调试窗口每条消息都会调用 `init_assistant`，把工作区放在这里会白建很多次。准备工作放在每次 `run` 开始时。

### 4.2 关键数据结构 / 字段约定

| 字段 / 结构 | 类型 / 格式 | 说明 | 谁会消费 |
|---|---|---|---|
| 助手节点参数 `skill_list` | `[{key: 技能名, label: 显示名}]` | 缺省或空表示不配置技能 | `AgentNode`、platform 节点面板 |
| 助手节点参数 `input_files` | `[node.var]`，上游文件变量 | 运行时拷进 `uploads/` | `AgentNode` |
| `assistant.skill_names` | JSON 字符串数组，可空 | `None` 与 `[]` 等价 | 助手配置读写、`AssistantAgent` |
| 交付文件描述 | `{file_id, file_name, object_name, bucket, size, file_url, format_error?}` | `file_url` 是决策 7 的鉴权跳转地址，用这个键名是因为前端文件卡片已认 `file_url`；`bucket` 为 `public`（正式会话）或 `tmp`（临时会话）；`format_error` 只在 AC-33 情况出现 | 消息 `files`、前端文件卡片、开放 API `files` |
| 输出变量 `{node_id}.deliverables` | 文本，每行「文件名：下载地址」 | 没有交付文件时为空串 | 下游节点 |
| 消息 `extra.agent_notices` | `["code_executor_missing"]` 等提示代码 | 前端按 i18n 渲染 | client、platform |
| Redis `agent_runtime:tmp_session:{ID}` | `{user_id, tenant_id}`，TTL 24h | 临时会话归属 | 下载接口、清理任务 |
| MinIO `workspace/agent/{会话键}/{运行面}/…` | public 桶 | 工作区内容；`skills/` 只读 | `WorkspaceBackend` |

### 4.3 关键模块职责

| 模块 / 文件 | 职责 | 不做什么 |
|---|---|---|
| `B/agent_runtime/domain/services/agent_runner.py` | 运行编排：判定技能、准备工作区、构建 middleware 和执行器、收尾 | 不感知 workflow 或助手的业务对象 |
| `B/agent_runtime/domain/services/agent_workspace.py` | 工作区键、水合、基线、拷技能、拷输入文件、按前缀清理 | 不判定交付文件 |
| `B/agent_runtime/domain/services/deliverables.py` | 交付文件判定、格式标注、上传为会话附件 | 不处理下载鉴权 |
| `B/agent_runtime/domain/services/skill_prompt_middleware.py` | 追加技能提示词（三个变体） | 不改创建者提示词 |
| `B/agent_runtime/domain/services/tmp_session.py` | 临时会话登记、刷新、清理 | 不处理正式会话 |
| `B/agent_runtime/api/endpoints/files.py` | 下载鉴权与跳转 | 不签发长效链接 |
| `B/workflow/nodes/agent/agent.py` | 读节点参数、调用 runner、发事件、写日志 | 不直接操作 MinIO |
| `B/api/services/assistant_agent.py` | 读助手配置、调用 runner | 同上 |

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | 技能查询使用严格租户过滤，没有租户上下文就查不到或报错 | Celery 线程里查不到任何技能，所有节点都报「已删除」 | runner 运行前按节点 `tenant_id` 设置上下文 |
| 2 | `WorkspaceBackend.ls` 只返回文件，不返回目录 | `SkillsMiddleware` 直接挂在它上面会发现 0 个技能 | 沿用任务模式：`SkillsMiddleware` 用本地目录上的 `FilesystemBackend` |
| 3 | 本地执行器在本地目录里跑，看不到只在 MinIO 里的上一轮文件 | 第二轮修改文件时报文件不存在 | 决策 3 第 2 步水合 |
| 4 | E2B 执行器的文件列表在构建时固定 | E2B 看不到技能文件 | 决策 10：先水合、拷技能，再建工具 |
| 5 | 代码执行器的 copy-out 能写进 `skills/`，不经过只读守卫 | 模型改了技能文件，下轮又被覆盖，行为不稳定 | 每轮重拷技能；`skills/` 不参与交付判定 |
| 6 | `tool.close()` 和 `release_local_run(file_dir)` 必须都调用 | 本地隔离 uid 和运行目录泄漏 | runner `finish()` 的 finally |
| 7 | client 和 platform 遇到带 `files` 的 bot 消息只渲染文件、不渲染文字（`F/client/src/pages/appChat/ChatMessages.tsx:96`、`F/platform/src/components/bs-comp/chatComponent/MessagePanne.tsx:117`），`FileBs` 只显示第一个文件 | 加了交付文件后回答文字消失 | 前端任务改为「文字 + 文件列表」，涉及组件展示变化，需设计师确认 |
| 8 | 两个前端的流式 `end` 处理都不合并 `files`（`F/client/src/pages/appChat/useChatHelpers.ts:240-310`、`F/platform/.../messageStore.ts:150-172`） | 实时对话看不到文件卡片，刷新历史后才出现 | 前端任务 |
| 9 | 助手 WebSocket 对话走 `run()`，不走 `astream`；只有开放 API 用 `astream(stream_mode="messages")` | 只测开放 API 会漏掉主路径 | 两条路径都要测 |
| 10 | 助手调试每条消息都重建 Agent | 临时会话 ID 放在 Agent 上，每条消息换一个工作区，多轮修改失效 | 决策 8：ID 放在连接对象上 |
| 11 | `update_status` 上线校验会调用 `init_assistant`，此时 `chat_id` 为空 | 每次上线都建一个空工作区 | 工作区准备放在 `run` 开始时 |
| 12 | 助手前端的运行日志按 `tool_list/knowledge_list/flow_list` 查名称，三个列表都空时整块隐藏（`F/client/src/components/MessageRunlog.tsx:51-54`、`F/platform/.../RunLog.tsx:56-58`）；`runLogsTypes` 只认 `tool/flow/knowledge` | 只配了技能的助手看不到任何工具调用记录，违反 AC-26 | 前端任务补技能工具的名称映射 |
| 13 | workflow 节点参数由客户端整体提交，后端照单执行 | 前端绕过 ReAct 禁用也能提交技能 | 后端运行时按决策 5 和 AC-13 校验 |
| 14 | `create_agent` 的流式节点名从 `"agent"` 改成 `"model"`，且每次模型调用都重新 `bind_tools`（`create_react_agent` 在编译时绑定一次） | 依赖节点名的流式过滤失效；按「编译时只绑定一次」写的模型包装类行为会变 | 助手节点已用对照测试锁定迁移前后一致（`T/workflow/test_agent_node_create_agent.py`）。`B/common/image_view/vision_llm.py` 依赖编译时绑定，但它只用于日常对话，助手节点和助手应用都不引用 |
| 15 | `run_async_safe` 默认超时 10 秒 | 拷大技能包或水合大工作区时超时 | 显式传超时 |
| 16 | `FilesystemMiddleware` 总会注册 `execute` 工具，只在 backend 支持执行时才暴露给模型（`deepagents/middleware/filesystem.py:858-870`） | 若判断条件变化，模型会看到一个必然失败的 `execute` | 构建器测试断言模型可见工具列表里没有 `execute` |
| 17 | `ChatSessionService.delete_session` 不校验调用方是否拥有会话 | 在其中加清理钩子会放大这个缺口的影响 | 本期不改，见 §8，已告知用户 |
| 18 | 同一会话的两次运行可能同时发生（如用户开两个标签页） | 两次运行写同一个工作区，同名交付文件后写覆盖先写，交付判定可能把对方的文件算进来 | 本期不加锁；`act=agent_runtime_run` 日志带运行 ID，便于排查；出现投诉再按会话键加 Redis 锁 |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 契约 | 形式 | 谁在用 |
|---|---|---|
| `GET /api/v1/agent-runtime/files/{session_key}/{file_id}` | HTTP，鉴权后 302 到短时链接 | client、platform、下游节点引用的链接、开放 API 调用方 |
| workflow 开放 API 助手节点事件 `output_schema.files` | 事件字段（已有字段，新填值） | 开放 API 调用方（AC-34） |
| 输出变量 `{node_id}.deliverables` | workflow 变量 | 下游节点 |
| 消息 `files`、`extra.agent_notices` | 消息字段 | 两个前端、历史回放 |
| `assistant.skill_names`、`AssistantUpdateReq.skill_names` | 表列、HTTP 字段 | platform 助手配置页 |
| 错误码 11061（已停用）、11062（已删除）、11063（执行方式不支持） | 错误码 | 前端 `api_errors` |
| `AgentRunner` | 内部 Python API | workflow 节点、助手应用；以后的日常对话 |

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 风险点 |
|---|---|---|
| `WorkspaceBackend`、`SkillStore`、`materialize_session_skills`、`select_deliverables` | linsight 内部 API | 任务模式改签名会连带影响；改动 linsight 这些函数时要跑 F078 测试 |
| `SkillsMiddleware`、`FilesystemMiddleware`（deepagents 0.6.12） | 第三方库 | 升级 deepagents 时复核坑 2、坑 16 |
| `langchain.agents.create_agent`（langchain 1.3.11） | 第三方库 | 坑 14 |
| 内置工具 `bisheng_code_interpreter` 配置 | 数据库行 | 未配置时按 AC-09 降级 |
| `_remove_attachments`、`resolve_attachment_url` 的附件约定 | 隐式数据契约 | chat_session 若改附件结构，交付文件的清理和下载会失效 |
| `GET /api/v1/llm/assistant` 返回的 `agent_executor_type` | HTTP | 前端据此禁用技能选择（AC-03） |
| 技能列表 `GET .../skill/selectable` | HTTP | 前端技能候选项 |

### 6.3 错误码分配

技能相关错误放在 linsight 技能管理段 11050–11069（`B/common/errcode/linsight.py:92-100`）。11060 在前端 locale 里有残留键，跳过不用。新分配 11061、11062、11063，三种语言的文案放在 `F/packages/locales/src/api_errors/`。release-contract 的「已分配模块编码」同步登记。

---

## 7. 测试与可观测

- **单元测试**（`src/backend/test/agent_runtime/`）：
  - 工作区：键推导、水合、基线、拷技能。用假 MinIO。
  - 技能判定：停用、删除、ReAct 三种报错。
  - 交付文件：判定和格式标注，复用任务模式的测试夹具。
  - 构建器：无技能时 middleware 为空；有技能时模型可见工具列表正确，且不含 `execute`。
  - 下载鉴权：本人、他人、开放 API 身份、临时会话发起人、未登录。
- **对照测试**：同一配置在迁移前后、无技能时，模型收到的 system prompt 和工具列表一致（AC-25）。
- **e2e**（`/e2e-test`）：在 114 上配置内置 docx 技能，跑通 workflow 和助手应用的正式会话、调试窗口和开放 API，覆盖文件卡片、二轮修改、跨节点、会话删除清理。
- **手动验证**（114 环境，部署方式见 `bash /opt/bisheng-ops/deploy.sh`）：
  1. 用管理员在 platform（`http://192.168.106.114:4101/`）的技能库确认内置 `bisheng-docx` 技能已启用，并在内置工具中配置代码解释器。
  2. 用非管理员账号新建 workflow：开始 → 输入 → 助手节点（选 function call 模型、勾选 docx 技能、勾选「输出给用户」）→ 结束。
  3. 在调试窗口输入「写一份 300 字的周报，生成 Word 文件」，确认出现文件卡片并能下载；第二轮输入「把标题改成『十月周报』」，确认生成新文件。
  4. 发布后在 client（`http://192.168.106.114:4101/workspace/`）重复第 3 步，刷新页面后确认历史消息里的文件仍可下载。
  5. 退出登录后访问文件卡片的下载地址，确认被拒绝；删除该会话后，确认 MinIO `workspace/agent/{chat_id}/` 前缀为空。
  6. 助手应用按第 2–5 步各做一遍。
- **日志**：runner 每次运行打一行 `act=agent_runtime_run`，带会话键、运行 ID、技能名、执行器类型、交付文件数、耗时。

---

## 8. 后续改进 / 不打算做的事

- **任务模式下载接口越权**：`/linsight/workbench/file_download` 不校验文件归属，`batch-download-files` 只校验登录。不在本期范围，建议单独修复。
- **`delete_session` 缺少归属校验**：同上，建议单独修复。
- **ReAct 执行方式下线**：可以消除第二条执行路径，影响所有 ReAct 模型，另起 feature。
- **工作区容量上限**：与任务模式一并处理。
- **工作区按需拉取**：见决策 3 的重新考虑条件。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-10-16 | 初版 | spec 定稿后编写 |
