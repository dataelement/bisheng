# Tasks: 任务模式开放 API

**关联规格**: [spec.md](./spec.md) · [design.md](./design.md)
**版本**: v3.0.0-beta1（发版线 `feat/3.0.0-beta2`）

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-09-30 用户确认；同日复核：执行身份失效时已受理任务继续执行至终态（维持），AC-15 改为不提供已下线的个人知识库，AC-34 改为自身身份下模型用量记在资源归属人名下 |
| design.md | ✅ 已评审 | 2026-09-30 用户确认 |
| tasks.md | ✅ 已拆解 | 2026-09-30 `/sdd-review tasks` 两轮；余 low：T008、T009、T014、T015 测试与实现同任务（改动小），T018 多文档登记 |
| 实现 | 🔲 未开始 | 0 / 20 完成 |

---

## 开发模式

- 按 Wave 组织；同一 Wave 内无相互依赖，可并行。
- 后端 Test-First：测试任务与实现任务配对，测试放 `src/backend/test/open_api/`、`test/linsight/`、`test/workstation/`（`asyncio_mode=auto`）。
- 设计论证不在此重复，指向 design 决策编号。
- 多 agent 并行实现时禁止仓库级 git 写操作（根 `AGENTS.md` §7）。
- 本 Feature 无前端页面改动；仅新增三语错误文案。

---

## Tasks

### Wave 1 — 基础设施（互不依赖）

- [ ] **T001**: `linsight_session_version.api_meta` 列与迁移
  **文件**: `src/backend/bisheng/linsight/domain/models/linsight_session_version.py`，`src/backend/bisheng/core/database/alembic/versions/v3_0_0b1_f073_linsight_api_meta.py`
  **逻辑**: 增加可空 `api_meta`（`JsonType`）；迁移只加列、无回填，降级删列；`public_dump()` 不输出该列（design 决策 6、§4.3）
  **测试**: MySQL 与 DM8 各执行一次 upgrade / downgrade
  **覆盖 AC**: AC-21、AC-19（为其提供开关）
  **依赖**: 无

- [ ] **T002**: 错误码 26060–26067 与三语文案
  **文件**: `src/backend/bisheng/common/errcode/open_api.py`，`src/frontend/packages/locales/src/api_errors/{zh-Hans,en,ja}.json`
  **逻辑**: 按 design 决策 14 定义 8 个类（继承 `OpenApiAuthError`，带 `http_status`）；26062 / 26065 支持 `data` 载荷；运行文案生成脚本，不手改生成物；`pnpm check-i18n` 通过
  **覆盖 AC**: AC-02、AC-09、AC-12、AC-13、AC-17、AC-18、AC-23
  **依赖**: 无

- [ ] **T003**: 请求与视图 schema
  **文件**: `src/backend/bisheng/open_api/domain/schemas/task_mode.py`
  **逻辑**: `OpenTaskSubmitReq`（`extra=forbid`，字段与长度上限见 design §4.2）；`OpenTaskView`、`OpenTaskResult`、`OpenTaskFile` 等视图；状态枚举含 `waiting_input`（design 决策 12）
  **测试**: `test/open_api/test_task_mode_schema.py`——多余字段、个人知识库字段、`conversationId`、超长文本均被拒
  **覆盖 AC**: AC-10、AC-15、AC-17、AC-27
  **依赖**: 无

### Wave 2 — 执行内核改动（依赖 T001）

- [ ] **T004**: 共享提交核心测试
  **文件**: `src/backend/test/workstation/test_task_submit_service.py`
  **逻辑**: 断言 v1 路径行为不变（先写任务轮再入队、入队失败 best-effort）；v2 路径入队失败置版本为失败并抛出；传入 `session_subject` 时会话带主体标记、附件分区为 `subject.storage_partition`；`api_meta` 写入；埋点 `source` 取值
  **覆盖 AC**: AC-08、AC-32、AC-33、AC-34
  **依赖**: T001

- [ ] **T005**: `submit_user_question` 接收主体、来源与 `api_meta`
  **文件**: `src/backend/bisheng/linsight/domain/services/workbench_impl.py`
  **逻辑**: 签名增加 `*, session_subject: SessionSubject | None = None, api_meta: dict | None = None, telemetry_source: str = "platform"`；传入主体时新会话经 `session_subject.stamp()` 创建，附件提升用 `session_subject.storage_partition`；`api_meta` 写入版本；埋点 `source=telemetry_source`。默认参数下行为与现状完全一致（design 决策 5、决策 6）
  **测试**: T004 中 `submit_user_question` 相关用例通过
  **覆盖 AC**: AC-32、AC-33、AC-34
  **依赖**: T001、T004

- [ ] **T020**: 抽出共享提交核心 `submit_task_turn`
  **文件**: `src/backend/bisheng/workstation/domain/services/task_submit_service.py`（新），`workstation/domain/services/chat_service.py`
  **逻辑**: `async def submit_task_turn(data: APIChatCompletion, login_user: UserPayload, *, session_subject=None, api_meta=None, telemetry_source="platform", strict_enqueue=False) -> LinsightSessionVersion`：`_to_linsight_submit` → `submit_user_question`（T005）→ `persist_task_turn_message` → `enqueue_session_for_execution`；`strict_enqueue=True` 时入队失败把版本置为 `failed`（`output_result.error_message` 写明原因）并抛 503。内容安全与标题生成**不在**核心内，由调用方处理。`_task_mode_stream_completion` 改为调用它（`strict_enqueue=False`），SSE 交接与标题生成原样保留（design 决策 3）
  **测试**: T004 全部通过；`test/workstation/` 既有任务模式用例不回归
  **覆盖 AC**: AC-08
  **依赖**: T005

- [ ] **T006**: 无人值守装配测试
  **文件**: `src/backend/test/linsight/test_agent_factory_headless.py`
  **逻辑**: `channel` 为空时工具含 `ask_user`、提示词含第 0 步；`channel="open_api_v2"` 时二者同时不存在、含无人值守段与业务上下文指令段（断言 prompt ⟺ tool 同步）
  **覆盖 AC**: AC-21、AC-10
  **依赖**: T001

- [ ] **T007**: 无人值守装配实现
  **文件**: `src/backend/bisheng/linsight/domain/services/agent_factory.py`
  **逻辑**: 按 `api_meta.channel` 从实际工具列表生成提示词；去掉 `ask_user`（含修复中间件列表）；追加无人值守段与 `instructions`（design 决策 7）。worker 已按队列项携带的 `tenant_id` 恢复租户上下文（`encode_queue_item`），本任务不改该机制
  **测试**: T006 全部通过
  **覆盖 AC**: AC-21、AC-10
  **依赖**: T001、T006

- [ ] **T008**: 执行前复核技能（测试 + 实现）
  **文件**: `src/backend/bisheng/linsight/domain/services/skill_provisioning.py`，`src/backend/test/linsight/test_skill_provisioning_open_api.py`
  **逻辑**: `channel="open_api_v2"` 且所选技能有缺失时抛出，任务以「失败」结束，说明列出技能名；工作台任务仍静默丢弃（design 决策 8）
  **测试**: 两种 channel 各一例
  **覆盖 AC**: AC-19
  **依赖**: T001

- [ ] **T009**: 终止逻辑下沉
  **文件**: `src/backend/bisheng/linsight/domain/services/workbench_impl.py`，`linsight/api/endpoints/linsight.py`，`src/backend/test/linsight/test_terminate_shared.py`
  **逻辑**: 抽出 `async def terminate(cls, session_version: LinsightSessionVersion) -> None`（出队 → 置 `terminated` → 写任务轮 → 推终止事件），不含归属与终态判定；v1 端点保留自身判定后调用它，响应不变（design 决策 13）
  **测试**: 排队中、执行中各终止一次，状态与任务轮一致；v1 端点响应不变
  **覆盖 AC**: AC-23
  **依赖**: 无

### Wave 3 — 开放 API 服务（依赖 Wave 1、Wave 2）

- [ ] **T010**: 提交校验测试
  **文件**: `src/backend/test/open_api/test_task_mode_submit.py`
  **逻辑**: design 决策 9 每一项的拒绝路径与错误码；校验顺序（内容安全命中不建会话）；任一失败不写任何行；自身身份下「资源归属人有权、服务账号无权」的知识库被拒；权限引擎抛错 → 503
  **覆盖 AC**: AC-02、AC-11、AC-12、AC-13、AC-14、AC-15、AC-16、AC-18
  **依赖**: T002、T003

- [ ] **T011**: `OpenTaskModeService.submit`
  **文件**: `src/backend/bisheng/open_api/domain/services/task_mode_service.py`（新）
  **逻辑**: `async def submit(cls, principal: OpenApiPrincipal, req: OpenTaskSubmitReq) -> OpenTaskSubmitted`：决策 9 校验（判定函数单独成 `_check_*`，供 T014 复用）→ 内容安全 → `req.to_internal()` → `submit_task_turn(..., strict_enqueue=True, telemetry_source="api")`（T020）→ `asyncio.create_task` 后台生成标题（异常只记日志）→ 返回 `{task_id, status, queue_position}`
  **测试**: T010 全部通过
  **覆盖 AC**: AC-02、AC-08、AC-11、AC-12、AC-13、AC-14、AC-15、AC-16、AC-18
  **依赖**: T002、T003、T020、T010

- [ ] **T012**: 查询、下载、终止测试
  **文件**: `src/backend/test/open_api/test_task_mode_view.py`
  **逻辑**: 六种内部状态的投影；`queue_position` 为 0 → 空；进度计数；`partial`；缺 `error_type` → `unknown`；答复去引用标记；清单不含路径；幻影与格式错误交付物；附件失败原因；四种主体组合归属校验 → 404；终态终止 → 26064；下载只认本任务清单内的 `file_id`
  **覆盖 AC**: AC-20、AC-22、AC-23、AC-24、AC-25、AC-26、AC-28、AC-29、AC-30、AC-31
  **依赖**: T003

- [ ] **T013**: `OpenTaskModeService` 查询、下载、终止
  **文件**: `src/backend/bisheng/open_api/domain/services/task_mode_service.py`
  **逻辑**: 归属校验（`SessionSubject.matches`）；design 决策 12 投影；MinIO 流式读与 RFC 5987 文件名；终止调用 T009
  **测试**: T012 全部通过
  **覆盖 AC**: AC-20、AC-22、AC-23、AC-24、AC-25、AC-26、AC-28、AC-29、AC-30、AC-31
  **依赖**: T003、T009、T012

- [ ] **T014**: 可用配置查询（测试 + 实现）
  **文件**: `src/backend/bisheng/workstation/domain/services/workstation_service.py`，`open_api/domain/services/task_mode_service.py`，`src/backend/test/open_api/test_task_mode_config.py`
  **逻辑**: `run_mode=task` 返回模型、默认模型、工具、技能；知识接口按类型分页搜索；与 T011 共用同一批判定函数；日常模式响应逐字节不变（design 决策 10）
  **测试**: 查询结果中任意一组提交均通过；停用技能不出现；代表他人无任务模式权限 → 26063；权限引擎抛错 → 503
  **覆盖 AC**: AC-04、AC-05、AC-06、AC-07
  **依赖**: T002、T011

- [ ] **T015**: 日常模式「模型不可用」改用 26066
  **文件**: `src/backend/bisheng/open_api/domain/services/daily_chat_service.py`，`src/backend/test/open_api/test_daily_chat_model_error.py`
  **逻辑**: 替换 `:35` 的裸 400；工具裸 400 不动
  **覆盖 AC**: AC-13
  **依赖**: T002

### Wave 4 — 端点与接线（依赖 Wave 3）

- [ ] **T016**: 端点测试
  **文件**: `src/backend/test/open_api/test_task_mode_endpoints.py`
  **逻辑**: `run_mode` 分派（缺省 / `daily` 走原路径且响应不变，`task` 走新路径，其它 → 26017）；任务 × 同步 → 26060、日常 × 异步 → 26015，三者可区分；PAT 调用被拒；缺 `chat:invoke` → 26003；新端点均已在 `OPEN_API_SCOPES` 登记
  **覆盖 AC**: AC-01、AC-03、AC-09
  **依赖**: T011、T013、T014

- [ ] **T017**: 端点实现与异常处理器调整
  **文件**: `src/backend/bisheng/open_endpoints/api/endpoints/workstation.py`，`open_api/domain/scopes.py`，`open_api/api/exception_handlers.py`
  **逻辑**: 提交端点按原始 body 分派；新增 `/tasks/{task_id}`、`/tasks/{task_id}/files/{file_id}`、`/tasks/{task_id}/terminate`、`/config/knowledge`；`/config` 接收 `run_mode`；异常处理器不再把 `run_mode="task"` 映射为 26017（design §6.2）
  **测试**: T016 全部通过；F053 既有 `test/open_api/` 全部通过
  **覆盖 AC**: AC-01、AC-03、AC-09
  **依赖**: T011、T013、T014、T016

- [ ] **T018**: release-contract 登记与对外文档
  **文件**: `features/v3.0.0-beta1/release-contract.md`，`docs/constitution.md`（C5 错误码表），F053 的 v2 接口文档（`features/v3.0.0-beta1/053-openapi-auth-and-identity/generate_openapi_contract.py` 生成物），对客文档「任务模式」章节
  **逻辑**: 按 design §4.3 登记表 1 / 表 3 / 表 4 / 260 段；对外文档逐项写可用配置、入参、状态、结果、错误码及处置、失败类别处置、附件 3 天有效期、执行身份失效时的行为（与 workflow 不同）、完整示例、本期不支持项；升级说明写明存量 `chat:invoke` 密钥须复核
  **覆盖 AC**: AC-36、AC-37
  **依赖**: T017

### Wave 5 — 端到端验收

- [ ] **T019**: `/e2e-test` 端到端
  **文件**: `features/v3.0.0-beta1/073-openapi-task-mode/e2e-checklist.md`，`src/backend/test/open_api/e2e/`
  **逻辑**: spec AC-35 最小表单流程，代表他人、自身身份各一遍；代表他人任务在员工工作台可打开并渲染任务面板；自身身份任务不出现在资源归属人列表；执行中查询不影响工作台实时展示；workflow 代码节点调用一遍（进程内执行模式）
  **覆盖 AC**: AC-24、AC-32、AC-33、AC-35、AC-38
  **依赖**: T017、T007、T008

---

## AC 覆盖核对

| AC | 任务 |
|---|---|
| AC-01、AC-03、AC-09 | T016、T017 |
| AC-02 | T002、T010、T011 |
| AC-04、AC-05、AC-06、AC-07 | T014 |
| AC-08 | T004、T020、T011 |
| AC-10 | T003、T006、T007 |
| AC-11、AC-12、AC-13、AC-14、AC-15、AC-16、AC-18 | T010、T011（AC-13 另含 T015，AC-15 另含 T003） |
| AC-17 | T002、T003 |
| AC-19 | T001、T008 |
| AC-20、AC-22、AC-25、AC-26、AC-28、AC-29、AC-30、AC-31 | T012、T013 |
| AC-21 | T001、T006、T007 |
| AC-23 | T009、T012、T013 |
| AC-24 | T012、T013、T019 |
| AC-27 | T003 |
| AC-32、AC-33、AC-34 | T004、T005、T019 |
| AC-35、AC-38 | T019 |
| AC-36、AC-37 | T018 |

---

## 实际偏差记录

（无）
