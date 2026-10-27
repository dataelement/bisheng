# Tasks: 助手节点与助手应用调用技能

**关联规格**: [spec.md](./spec.md) · [design.md](./design.md)
**版本**: v3.0.0（开发分支 `feat/SEC-3.0.0-1016`）

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-10-16 用户确认，提交 90dd94500 |
| design.md | ✅ 已评审 | 2026-10-16 用户确认 |
| tasks.md | ✅ 已拆解 | 2026-10-16 按 tasks-checklist 自审后重拆 |
| 实现 | 🟡 第一期代码完成 | 第一期剩 T40（端到端验收，待部署 114）；T35、T37、T38 只完成 workflow 部分，助手部分随第二期；第二期 10 个任务暂缓 |

---

## 分期（2026-10-16 用户拍板）

本期只开发 workflow 助手节点，助手应用暂不开发。spec 的需求范围不变，助手应用相关的 AC 顺延到第二期验收。

| 分期 | 任务 | 说明 |
|---|---|---|
| 第一期（本期） | T01、T02、T04–T22、T25–T28、T32–T34、T35 的 workflow 部分、T36、T37 的 workflow 调试面板部分、T38 的 workflow 部分、T40 的 workflow 部分 | 共用组件（错误码、工作区、技能判定、代码执行工具、交付文件、临时会话、构建器、下载接口）在本期完成 |
| 第二期（暂缓） | T03、T23、T24、T29、T30、T31、T35 的助手部分、T37 的助手配置页部分、T38 的助手部分、T39 | 助手应用的表结构、create_agent 迁移、配置读写、对话接入、开放 API、前端 |

第二期顺延验收的 AC：AC-02、AC-15、AC-35，以及 AC-13、AC-21、AC-24、AC-26、AC-36 中涉及助手应用的部分。

---

## 开发模式

- 任务按 Wave 组织。同一 Wave 内无依赖的任务可以并行。
- 后端先写测试任务（红），再做配对的实现任务（绿）。测试放在 `src/backend/test/agent_runtime/`、`src/backend/test/workflow/`、`src/backend/test/assistant/`。
- 前端用手动验证，环境为 114：platform `http://192.168.106.114:4101/`，client `http://192.168.106.114:4101/workspace/`。
- 设计论证指向 design.md 的决策编号，本文不重复。
- 并发子 agent 共用工作树时，禁止仓库级 git 写操作（`git stash`、`git checkout .`、`git reset --hard`、`git clean`）。
- 路径简写：`B/` = `src/backend/bisheng/`，`F/` = `src/frontend/`，`T/` = `src/backend/test/`。

---

## Wave 0：基础设施（无测试配对）

- [x] **T01**：错误码
  **文件**: `B/common/errcode/linsight.py`、`features/v3.0.0/release-contract.md`
  **逻辑**: 新增 11078（技能已被管理员停用，消息参数为技能名）、11079（技能已被管理员删除）、11077（当前模型的执行方式不支持技能）；跳过 locale 残留的 11060；在 release-contract「已分配模块编码」登记。决策见 design §6.3。
  **依赖**: 无

- [x] **T02**：错误码文案三语
  **文件**: `F/packages/locales/src/api_errors/{zh-Hans,en,ja}.json`
  **逻辑**: 为 11078、11079、11077 写三语文案，中文分别为「{name} 技能已被管理员停用」「{name} 技能已被管理员删除」「当前模型的执行方式不支持技能」；运行生成脚本，不手改生成产物。
  **验证**: `pnpm --filter @bisheng/locales check`、`pnpm check-i18n` 通过。
  **依赖**: T01

- [ ] **T03**：助手表 `skill_names` 列与迁移
  **文件**: `B/database/models/assistant.py`、`B/core/database/alembic/versions/v3_0_0_f078_assistant_skill_names.py`
  **逻辑**: `JsonType`、可空；迁移带 `column_exists` 守卫，`down_revision` 接当前唯一 head（写任务时用 `alembic heads` 确认）；`downgrade()` 删除该列，回滚安全，因为旧代码不读这一列。决策见 design 决策 9、K7。
  **验证**: MySQL 上 upgrade → downgrade → upgrade 可重复执行；人工复核 DM8 语法（C2）。
  **依赖**: 无

- [x] **T04**：`agent_runtime` 模块骨架
  **文件**: `B/agent_runtime/__init__.py`、`B/agent_runtime/domain/__init__.py`、`B/agent_runtime/api/router.py`、`B/api/router.py`
  **逻辑**: 按 `src/backend/AGENTS.md` 的模块布局建空骨架，注册路由前缀 `/agent-runtime`。决策见 design 决策 2。
  **依赖**: 无

## Wave 1：后端基础服务

- [x] **T05**：技能查询 Repository 测试
  **文件**: `T/agent_runtime/test_skill_repository.py`
  **测试**: 按名字批量查询时，返回已启用和已停用的行，不存在的名字不返回；其他租户的技能不可见。
  **覆盖 AC**: AC-27
  **依赖**: 无

- [x] **T06**：技能查询 Repository 实现
  **文件**: `B/linsight/domain/repositories/interfaces/skill_repository.py`、`B/linsight/domain/repositories/implementations/skill_repository_impl.py`
  **逻辑**: 参照 `B/knowledge/domain/repositories/` 的接口与实现结构；查询不过滤 `enabled`，受自动租户过滤约束。不在 `LinsightSkillDao` 上加方法（C1）。属于 F035 模块的新增只读代码，不改技能库已有的读写行为。
  **测试**: T05 通过。
  **依赖**: T05

- [x] **T07**：技能可用性判定测试
  **文件**: `T/agent_runtime/test_skill_resolver.py`
  **测试**: 已停用技能抛 11078，且消息带技能名；不存在的技能抛 11079；`None` 与 `[]` 返回空；全部可用时按配置顺序返回。
  **覆盖 AC**: AC-06、AC-12、AC-25、AC-30
  **依赖**: T01

- [x] **T08**：技能可用性判定实现
  **文件**: `B/agent_runtime/domain/services/skill_resolver.py`
  **逻辑**: `resolve_skills(names: list[str] | None) -> list[LinsightSkill]`，调用 T06 的 Repository。决策见 design 决策 5。
  **测试**: T07 通过。
  **依赖**: T06、T07

- [x] **T09**：工作区服务测试
  **文件**: `T/agent_runtime/test_agent_workspace.py`
  **测试**: 用假 MinIO 验证以下几点：
  - 三类工作区键（正式、临时、一次性）的推导结果；
  - 第二次运行能读到上一次的文件；
  - 换一个本地目录（模拟另一个服务节点）仍能读到；
  - 水合时跳过 `skills/`，技能每次都被重拷为当前版本；
  - 输入文件被拷进 `uploads/`；
  - 按会话前缀删除后，对象为空。
  **覆盖 AC**: AC-10、AC-11、AC-20、AC-21、AC-22、AC-23
  **依赖**: 无

- [x] **T10**：工作区服务实现
  **文件**: `B/agent_runtime/domain/services/agent_workspace.py`
  **逻辑**: `AgentWorkspace` 提供以下方法：
  - `key_for(...)`：推导工作区键；
  - `aprepare(skills, input_files)`：依次做本地目录、水合、基线、重拷技能（`materialize_session_skills(strict=True)`）、拷输入文件，返回 `WorkspaceBackend`、本地目录和基线；
  - 模块函数 `adelete_session_workspaces(minio, session_key)`：删除 `workspace/agent/{session_key}/` 前缀；
  - `cleanup_local()`：删除本地目录。
  决策见 design 决策 3、坑 2、坑 3、坑 5。
  **测试**: T09 通过。
  **依赖**: T09

- [x] **T11**：通用代码执行工具测试
  **文件**: `T/agent_runtime/test_code_tool.py`
  **测试**: 未配置时返回「未配置」；构建异常时返回「配置错误」并记 ERROR；local、container、e2b 三种执行器的工作区注入参数正确；e2b 的文件列表包含 `skills/`。
  **覆盖 AC**: AC-08、AC-09
  **依赖**: 无

- [x] **T12**：通用代码执行工具实现
  **文件**: `B/agent_runtime/domain/services/code_tool.py`、`B/linsight/domain/services/workbench_impl.py`
  **逻辑**: 把 `_init_bisheng_code_tool`（`workbench_impl.py:2224`）里的工作区注入逻辑抽成 `build_workspace_code_tool(file_dir, workspace_prefix, user_id, app_type) -> CodeToolResult(tool | None, status, reason)`，任务模式改为调用它，行为不变。影响范围：任务模式的代码执行器初始化，必须跑任务模式现有测试。决策见 design 决策 10、坑 4。
  **测试**: T11 通过；`T/linsight/` 现有测试保持通过。
  **依赖**: T11

- [x] **T13**：交付文件服务测试
  **文件**: `T/agent_runtime/test_deliverables.py`
  **测试**:
  - 输出区优先；输出区为空时，取别处本次新建的文件；
  - 上轮留下、本轮未改动的文件不交付；
  - 被修改的输入原件不交付；
  - 假 pptx 保留，并带 `format_error`；
  - 模型声称生成但实际不存在的文件不出现；
  - 正式会话的文件上传到 public 桶 `chat/{user_id}/agent/{chat_id}/`，临时会话的文件上传到 tmp 桶；
  - 返回的描述字段符合 design §4.2。
  **覆盖 AC**: AC-19、AC-31、AC-32、AC-33
  **依赖**: 无

- [x] **T14**：交付文件服务实现
  **文件**: `B/agent_runtime/domain/services/deliverables.py`
  **逻辑**: `collect_deliverables(file_dir, baseline, session) -> list[dict]`，调用 `select_deliverables` 与 `deliverable_format_error`。格式错误的文件只标注、不丢弃，所以不复用 `get_final_result_file`。决策见 design 决策 6。
  **测试**: T13 通过。
  **依赖**: T13

- [x] **T15**：临时会话服务测试
  **文件**: `T/agent_runtime/test_tmp_session.py`
  **测试**: 登记后可以查到发起人；每次运行刷新 TTL；关闭时清理工作区前缀和 tmp 桶交付文件；登记过期后查不到发起人。
  **覆盖 AC**: AC-36、AC-37
  **依赖**: 无

- [x] **T16**：临时会话服务实现
  **文件**: `B/agent_runtime/domain/services/tmp_session.py`
  **逻辑**: Redis 键 `agent_runtime:tmp_session:{ID}` 存 `{user_id, tenant_id}`，TTL 24h；提供 `register`、`touch`、`owner_of`、`aclose`。决策见 design 决策 8。
  **测试**: T15 通过。
  **依赖**: T10、T15

## Wave 2：构建器与无技能迁移

- [x] **T17**：技能提示词 middleware 测试
  **文件**: `T/agent_runtime/test_skill_prompt_middleware.py`
  **测试**: 有执行器、无执行器两个变体的追加内容（「只用文字交付」变体属于第二期，2026-10-20 删除了预埋代码）；追加位置在 system prompt 尾部；创建者提示词原样保留。
  **覆盖 AC**: AC-07、AC-09、AC-35
  **依赖**: 无

- [x] **T18**：技能提示词 middleware 实现
  **文件**: `B/agent_runtime/domain/services/skill_prompt_middleware.py`
  **逻辑**: 从 `_build_linsight_system_prompt` 的技能段提炼通用内容，不带任务模式专属占位符。决策见 design 决策 11。
  **测试**: T17 通过。
  **依赖**: T17

- [x] **T19**：AgentRunner 测试
  **文件**: `T/agent_runtime/test_agent_runner.py`
  **测试**:
  - 无技能时 middleware 为空，不建工作区、不建执行器；
  - 有技能时，模型可见工具包含文件工具，且不含 `execute`；
  - 用户已在工具列表加代码解释器时，只保留一个；
  - 未配置执行器时返回 `code_executor_missing` 提示代码；
  - ReAct 模型配置了技能时抛 11077；
  - `finish()` 在异常时也会调用 `close()`、`release_local_run()` 并删除本地目录。
  **覆盖 AC**: AC-06、AC-08、AC-09、AC-13、AC-25
  **依赖**: T01

- [x] **T20**：AgentRunner 实现
  **文件**: `B/agent_runtime/domain/services/agent_runner.py`
  **逻辑**:
  - `aprepare(...)`：组合 T08、T10、T12、T18，返回 `RunnerPlan(middleware, extra_tools, notices)`。middleware 包括 `FilesystemMiddleware(WorkspaceBackend)`、`SkillsMiddleware(FilesystemBackend(本地目录))`、技能提示词、非法工具调用修复。
  - `afinish()`：调用 T14 收集交付文件，并在 finally 中收尾。
  - 运行前按传入的 `tenant_id` 设置租户上下文。
  - 每次运行打 `act=agent_runtime_run` 日志。
  决策见 design 决策 1、决策 10、坑 1、坑 6、坑 15、坑 16。
  **测试**: T19 通过。
  **依赖**: T08、T10、T12、T14、T18、T19

- [x] **T21**：助手节点 create_agent 迁移的对照测试
  **文件**: `T/workflow/test_agent_node_create_agent.py`
  **测试**: 用假 LLM 做对照：无技能配置下，迁移前后模型收到的 system prompt、工具列表和返回内容一致；带图片输入的路径可用；ReAct 分支不受影响。
  **覆盖 AC**: AC-25
  **依赖**: 无

- [x] **T22**：助手节点迁移到 create_agent
  **文件**: `B/workflow/nodes/agent/agent.py`
  **逻辑**: function call 分支从 `create_react_agent(..., prompt=...)` 改为 `create_agent(..., system_prompt=..., middleware=[])`；检查 `B/common/image_view/vision_llm.py` 对编译期绑定工具的依赖。决策见 design 决策 1、坑 14。
  **测试**: T21 通过。
  **依赖**: T21

- [ ] **T23**：助手应用 create_agent 迁移的对照测试
  **文件**: `T/assistant/test_assistant_agent_create_agent.py`
  **测试**: `run` 与 `astream(stream_mode="messages")` 两条路径迁移前后输出一致；`recursion_limit=100` 保留；开放 API 流式输出只含 `AIMessageChunk` 文本。
  **覆盖 AC**: AC-25
  **依赖**: 无

- [ ] **T24**：助手应用迁移到 create_agent
  **文件**: `B/api/services/assistant_agent.py`
  **逻辑**: 同 T22。决策见 design 坑 9、坑 14。
  **测试**: T23 通过。
  **依赖**: T23

## Wave 3：接入 workflow 助手节点

- [x] **T25**：会话标识下传到节点
  **文件**: `B/workflow/graph/workflow.py`、`B/workflow/graph/graph_engine.py`、`B/worker/workflow/tasks.py`
  **逻辑**: 把 `chat_id`（调试时用 `hash_key`）按 `tenant_id` 现有的传递方式，从 `Workflow` 传到 `GraphEngine`，再传到节点构造参数；`run_once` 传入新生成的临时会话 ID。Celery 任务参数里已带 `tenant_id`，节点运行时由 AgentRunner 写入 ContextVar。影响范围：所有节点构造参数多一个可选字段，其他节点忽略。
  **验证**: 现有 workflow 测试保持通过。
  **依赖**: 无

- [x] **T26**：助手节点技能接入测试
  **文件**: `T/workflow/test_agent_node_skills.py`
  **测试**:
  - 单次与批量运行；
  - 第二次运行能修改上一次的文件；
  - 未勾选「输出给用户」时，`deliverables` 变量仍有值；
  - 无交付文件时变量为空；
  - ReAct 模型报 11077，技能停用报 11078，技能删除报 11079；
  - 运行日志包含技能名、工具调用和执行器缺失提示；
  - 输入文件进入 `uploads/`。
  **覆盖 AC**: AC-04、AC-10、AC-13、AC-16、AC-17、AC-19、AC-21、AC-26
  **依赖**: T20、T25

- [x] **T27**：助手节点技能接入实现
  **文件**: `B/workflow/nodes/agent/agent.py`
  **逻辑**:
  - 读 `skill_list`、`input_files`；
  - 用 `run_async_safe`（显式超时）调用 `AgentRunner.aprepare()` 与 `afinish()`；
  - 批量模式下每个批次分别准备和收集；
  - 写输出变量 `{node_id}.deliverables`；
  - `parse_log` 增加技能和提示行。
  决策见 design 决策 4、§4.1。
  **测试**: T26 通过。
  **依赖**: T22、T26

- [x] **T28**：节点输出事件携带交付文件
  **文件**: `B/workflow/callback/event.py`、`B/worker/workflow/redis_callback.py`
  **逻辑**: `StreamMsgOverData` 新增 `files`（`exclude=True`，与 `OutputMsgData` 一致）和 `notices`；`RedisCallback.on_stream_over` 把它们写入 `ChatResponse.files` 和 `extra.agent_notices` 并落库。影响范围：只有助手节点会填这两个字段，其它节点事件不变。
  **测试**: 在 T26 中补充断言：落库消息的 `files` 包含 `file_id` 和 `object_name`。
  **覆盖 AC**: AC-14、AC-18
  **依赖**: T27

## Wave 4：接入助手应用

- [ ] **T29**：助手配置读写 `skill_names`
  **文件**: `B/api/v1/schemas.py`、`B/api/services/assistant.py`
  **逻辑**: `AssistantUpdateReq.skill_names`（为 `None` 时不更新）、`AssistantInfo.skill_names`。在线状态下禁止修改的规则不变。
  **测试**: `T/assistant/test_assistant_skill_names_api.py`：保存后读取一致；字段缺省时不覆盖已有值。
  **覆盖 AC**: AC-02、AC-25
  **依赖**: T03

- [ ] **T30**：助手应用技能接入测试
  **文件**: `T/assistant/test_assistant_skills.py`
  **测试**:
  - 正式会话第二轮修改文件；
  - 同一调试连接内多条消息共用工作区；
  - `update_status` 上线校验不建工作区；
  - 评测和开放 API 使用一次性工作区，不收集交付文件；
  - 回答消息带 `files` 与 `extra.agent_notices`；
  - ReAct 模型报 11077。
  **覆盖 AC**: AC-13、AC-15、AC-21、AC-24、AC-26、AC-35
  **依赖**: T20、T29

- [ ] **T31**：助手应用技能接入实现
  **文件**: `B/api/services/assistant_agent.py`、`B/common/chat/client.py`
  **逻辑**: 在每次 `run` 开始时调用 `aprepare()`，不在 `init_assistant` 里调用；正式会话用 `chat_id`；调试时在 `ChatClient` 连接对象上生成临时会话 ID 并登记；回答消息写入 `files`、`extra.agent_notices`，WebSocket `end` 事件带 `files`；连接关闭时调用 `tmp_session.aclose`。决策见 design 决策 8、坑 10、坑 11。
  **测试**: T30 通过。
  **依赖**: T16、T24、T30

## Wave 5：下载、清理与开放 API

- [x] **T32**：下载接口与会话删除清理测试
  **文件**: `T/agent_runtime/test_file_access.py`（网页登录与临时会话）、`T/chat_session/test_attachment_link.py`（开放 API 身份）
  **测试**:
  - 本人可以下载；他人和未登录被拒；
  - 开放 API 身份可以下载自己会话的文件；
  - 伪造 `file_id` 被拒；
  - 临时会话只有发起人可以下载，登记过期后被拒；
  - 删除会话后，工作区前缀和交付文件都被清理。
  **覆盖 AC**: AC-18、AC-23、AC-28、AC-29、AC-37
  **依赖**: 无

- [x] **T33**：下载接口与会话删除钩子实现
  **文件**: `B/agent_runtime/api/endpoints/files.py`、`B/chat_session/domain/chat.py`
  **逻辑**: `GET /api/v1/agent-runtime/files/{session_key}/{file_id}`：
  - 正式会话用 `SessionSubject` 校验归属，对象名从消息记录里取，校验通过后 302 跳转短时链接；
  - 临时会话校验 Redis 登记的发起人；
  - `delete_session` 在现有 `_remove_attachments` 之后调用 `_remove_agent_workspaces`（内部调用 `adelete_session_workspaces`）。
  影响范围：chat_session 删除会话流程多一步 MinIO 前缀删除，失败只记日志、不阻断删除，与 `_remove_attachments` 的做法一致。决策见 design 决策 7、坑 17。
  **测试**: T32 通过。
  **依赖**: T04、T10、T16、T32

- [x] **T34**：临时工作区 Beat 清理任务
  **文件**: `B/worker/agent_runtime/tasks.py`、Beat 调度注册处
  **逻辑**: 每小时扫描 public 桶 `workspace/agent/tmp-*` 前缀，删除 Redis 登记已过期的目录。该任务只读 MinIO 和 Redis，不查业务表，所以不需要恢复租户 ContextVar，在多租户下也不会漏扫。
  **测试**: `T/agent_runtime/test_tmp_session.py` 的 `TestSweep`：登记过期的目录被删除，登记有效的目录保留。
  **覆盖 AC**: AC-37；spec §3「调试窗口异常断开也要清理」
  **依赖**: T16

- [x] **T35**：开放 API
  **文件**: `B/api/services/workflow.py`、`B/assistant/domain/services/published_assistant_service.py`
  **逻辑**: `convert_chat_response_to_workflow_event` 的 StreamMsg 分支填写 `output_schema.files`，没有交付文件时不填；助手开放 API 传入「一次性工作区 + 只用文字交付」标记。
  **测试**: `T/workflow/test_open_api_files.py`：workflow 事件带 `files`，格式与输出节点一致；无交付文件时字段缺省；助手 API 响应结构不变。
  **覆盖 AC**: AC-24、AC-34、AC-35
  **依赖**: T28、T31

## Wave 6：前端 Platform

- [x] **T36**：platform 助手节点配置面板
  **文件**: `F/platform/src/controllers/API/workflow.ts`（节点模板新增 `skill_list`、`input_files`）、`F/platform/src/pages/BuildPage/flow/FlowNode/component/SkillItem.tsx`（新建，参照 `ToolItem.tsx`）、`F/platform/src/pages/BuildPage/flow/FlowNode/component/InputFileItem.tsx`（新建，参照 `ImagePromptItem.tsx` + `SelectVar`，放开为文件变量）
  **逻辑**:
  - 技能候选项来自已启用技能列表，不预选；
  - 用 `GET /api/v1/llm/assistant` 的 `agent_executor_type` 判断模型，ReAct 时禁用并提示；
  - i18n 三语，键名用 `skill_names` 前缀，避开已表示 workflow 的 `build.skill`；
  - 动手前先读 `F/packages/ui/docs/`，只用已落地组件。
  **覆盖 AC**: AC-01、AC-03、AC-04、AC-05
  **手动验证**: 在 platform 编辑 workflow，添加助手节点；切换 function call 与 ReAct 模型，确认技能选择的启用与禁用；选择技能和上游文件变量，保存后重新打开，确认配置仍在。
  **依赖**: T27

- [x] **T37**：platform 助手配置页与两个调试面板
  **文件**: `F/platform/src/pages/BuildPage/assistant/editAssistant/Setting.tsx`、`F/platform/src/store/assistantStore.tsx`、`F/platform/src/components/bs-comp/chatComponent/MessagePanne.tsx`、`F/platform/src/pages/BuildPage/flow/FlowChat/`（消息渲染部分）、相关 `messageStore.ts`、`RunLog.tsx`
  **逻辑**:
  - 助手配置页加技能多选，ReAct 时禁用；
  - 两个调试面板的 bot 消息同时显示文字和全部文件卡片，`end` 事件合并 `files`；
  - 显示格式异常标注和 `agent_notices` 提示条；
  - 运行日志补齐文件工具和代码执行工具的名称。
  展示变化需设计师确认（design 坑 7）。
  **覆盖 AC**: AC-02、AC-03、AC-05、AC-09、AC-26、AC-33、AC-36
  **手动验证**: 在助手调试窗口配置 docx 技能，生成文件后立即下载；第二轮要求修改，确认生成新版本；关闭窗口后，原下载地址被拒绝。workflow 调试面板做同样验证。
  **依赖**: T31、T33

## Wave 7：前端 Client

- [x] **T38**：client 对话页渲染交付文件
  **文件**: `F/client/src/pages/appChat/ChatMessages.tsx`、`F/client/src/pages/appChat/useChatHelpers.ts`、`F/client/src/components/MessageFile.tsx`
  **逻辑**: bot 消息同时渲染文字和文件列表（复用 `AppChatFileList`）；流式 `end` 合并 `files`；显示格式异常标注和 `agent_notices`。展示变化需设计师确认。
  **覆盖 AC**: AC-09、AC-14、AC-15、AC-18、AC-33
  **手动验证**: 在 client 用 workflow 和助手应用各跑一次 docx 技能：实时对话能看到文字和文件卡片；刷新后历史消息仍可下载；退出登录后访问下载地址被拒绝。
  **依赖**: T28、T31、T33

- [ ] **T39**：client 运行日志显示技能工具
  **文件**: `F/client/src/components/MessageRunlog.tsx`、`F/client/src/pages/appChat/appUtils/skillMethod.ts`
  **逻辑**: 让只配了技能的助手也显示工具调用记录；补齐文件工具和代码执行工具的名称映射（design 坑 12）。
  **覆盖 AC**: AC-26
  **手动验证**: 只配置技能、不配置工具的助手对话中，能看到读取 SKILL.md 和执行代码的记录。
  **依赖**: T31

## Wave 8：验收

- [ ] **T40**：端到端测试
  **文件**: `features/v3.0.0/078-agent-skills/e2e/`（由 `/e2e-test` 生成）
  **逻辑**: 运行 `/e2e-test features/v3.0.0/078-agent-skills`，用非管理员账号验证以下场景：
  - workflow 与助手应用的正式会话、调试窗口、开放 API；
  - 多节点；
  - 会话删除。
  跑完后按 worktree 路径清理本地进程。
  **覆盖 AC**: AC-01、AC-02、AC-03、AC-04、AC-05、AC-06、AC-07、AC-08、AC-09、AC-10、AC-11、AC-12、AC-13、AC-14、AC-15、AC-16、AC-17、AC-18、AC-19、AC-20、AC-21、AC-22、AC-23、AC-24、AC-25、AC-26、AC-27、AC-28、AC-29、AC-30、AC-31、AC-32、AC-33、AC-34、AC-35、AC-36、AC-37
  **依赖**: T35、T36、T37、T38、T39

---

## 实际偏差记录

> 只留一行指针，论证在 design.md。推翻已 ★ 确认的决策时，先停下与用户重新确认。

- 2026-10-16 分期：助手应用相关任务顺延到第二期（用户拍板，见本文「分期」）。spec 与 design 不变。
- T12 偏离 → 「未配置代码执行器」只指没有工具行；配置为空时默认 local 执行器可用；构建失败（含无使用权限）为 error 状态（design 决策 10 已更新）。
- T14 偏离 → 交付文件描述用 `file_url` 和新增的 `bucket` 字段（design §4.2 已更新）。
- T25 偏离 → 单节点测试把助手节点放到工作线程执行（`run_async_safe` 不能在运行中的事件循环里调用），并补传 `tenant_id`。
- T27 偏离 → 交付文件变量统一命名为 `<输出键>_deliverables`，运行日志键改为 `skill_list`、`skill_notice`（design §4.1、§4.2 已更新）。
- T33 偏离 → chat_session 新增 `resolve_subject_attachment_url`，供开放 API 身份按会话归属下载（design §6.1 已更新）。
- T35 偏离 → 新增开放 API 下载路由 `GET /api/v2/workflow/files/{chat_id}/{file_id}`，已登记 scope、API 契约与两份接口文档（design §6.1 已更新）。
- T36 偏离 → 助手节点模板升到 v3，旧节点加载时由 `flowCompatible` 补参数；SelectVar 新增 `findFilePath` 模式。
- 基线记录：backend `test/workflow` 既有 14 个失败、platform vitest 既有 16 个失败（与 origin/feat/3.0.0 一致），本特性未新增失败。
- 错误码：原分配 11061–11063，2026-10-20 合并发版线时与技能中心（11061–11074）撞号，改为 11077–11079（含后端、三语文案、测试与 release-contract）；判断与扫描结果见 design §6.3。
- 2026-10-20 `/sdd-code-review --base feat/3.0.0` 修复（design 修订历史同日条目）：
  - 调试窗口临时会话改用连接级 `hash_key`，关闭钩子不再依赖 `self.workflow`，「停止」不清理 → design 决策 8、坑 19；测试 `T/workflow/test_workflow_client_tmp_session.py`。
  - `AgentRunner.aprepare` 失败时释放本地目录 → design 坑 6；测试 `T/agent_runtime/test_agent_runner.py` 的 `TestPrepareFailure`。
  - 补开放 API 下载的归属测试：`T/chat_session/test_attachment_link.py` 的 `TestResolveSubjectAttachmentUrl`。
  - 删除第二期预埋、无调用方的 `WorkspaceKey.once`、`AgentWorkspace.adelete`、`AgentRunSpec.text_only`、`SkillPromptVariant.TEXT_ONLY`、`TmpSessionService.new_id`；第二期按自己的调用方补回。
  - platform `WorkflowMessage` 类型补 `notices`。
  - 未改：上游文件下载无超时（发版线共享函数 `file_download`）、开放 API `session_id` 非安全字符（需新增错误码）→ design §8。

2026-10-27 合并公共发版线：11075、11076 已用于任务模式上下文错误，技能停用/删除改用 11078、11079，执行方式错误保持 11077。
