# Tasks: 积分扣费扩展（工具调用 + 助手 / 工作流 / 托管应用 + 计费总开关）

**关联规格**: [spec.md](./spec.md) · **设计真相**: [design.md](./design.md) · **QA 参考用例**: [test-cases.md](./test-cases.md)  
**版本**: v3.1.0（F001-credit-billing-extension）

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| release-contract.md | ✅ 已创建 | `features/v3.1.0/release-contract.md` |
| spec.md | ✅ 已评审 | 用户已确认（★2），共 AC-01 ~ AC-32 |
| design.md | ✅ 已评审 | 用户已确认（★3），Constitution Check 全通过 |
| test-cases.md | ✅ 已生成 | 八列 QA 参考用例（TC-CBE-001 ~ TC-CBE-018） |
| tasks.md | ✅ 已拆解 | 按 Wave 1 ~ Wave 5 组织，后端 Test-First |
| 实现 | 🔄 进行中 | 13 / 25 完成（Wave 3 完成，进入 Wave 4） |

---

## 开发模式

- **按 Wave 组织任务**：Wave 1（基础设施与总开关）→ Wave 2（统一账本与工具扣费底座）→ Wave 3（工具设价管理与生命周期）→ Wave 4（助手/工作流/任务模式/托管应用/开放 API）→ Wave 5（前端 Platform、前端 Client、托管文档与全量回归）。
- **后端 Test-First**：所有后端业务与 API 任务均按「测试任务先于实现任务」配对，测试文件位于 `src/backend/test/dsh/`、`src/backend/test/tool/`、`src/backend/test/open_api/`、`src/backend/test/workflow/`。
- **前端区分 Platform / Client**：`src/frontend/platform/` 与 `src/frontend/client/` 严格拆分任务，均附 Vitest 组件测试与手动验证步骤。
- **Worker 租户上下文**：所有涉及 Celery / Linsight Worker 的任务显式通过 `OpenApiExecutionSnapshot` / `durable_workload_scope` 恢复 `current_tenant_id` ContextVar，不依赖 HTTP 进程变量。

---

## Tasks

### Wave 1：基础设施（ORM、双库迁移、全局配置总开关）

- [x] **T001**: 新增 ORM 模型 `DshToolPricing`、`DshToolCall`，扩展 `DshModelCall` 与 `DshMonthlyUsage` 并登记租户过滤
  **文件**: `src/backend/bisheng/dsh/domain/models/tool_pricing.py`, `src/backend/bisheng/dsh/domain/models/tool_call.py`, `src/backend/bisheng/dsh/domain/models/model_call.py`, `src/backend/bisheng/dsh/domain/models/monthly_usage.py`, `src/backend/bisheng/core/database/tenant_filter.py`
  **逻辑**:
  - 新建 `DshToolPricing`（`dsh_tool_pricing`）：唯一键 `(tenant_id, tool_id)`，含 `pricing_mode`、`currency`、`price_micro`、`call_count`（默认 `1`，`CheckConstraint("call_count >= 1 AND call_count <= 1000000")`）、`version`、`updated_by`、`update_time`（使用 `UPDATE_TIME_SERVER_DEFAULT`）。
  - 新建 `DshToolCall`（`dsh_tool_call`）：主键 `request_id`，含 `tenant_id`、`user_id`、`usage_month`、`tool_group_id`、`tool_group_name`、`tool_id`、`tool_key`、`engine`、`pricing_snapshot`（`JsonType`）、`billed_tokens`、`cost_micro`、`currency`、`result`、`source_type`、`source_id`、`started_at`、`ended_at` 及双索引。
  - `DshModelCall` 新增可空列 `source_type` (VARCHAR(32))、`source_id` (VARCHAR(64))。
  - `DshMonthlyUsage` 新增非空列 `usage_type` (VARCHAR(16), `server_default=text("'MODEL'")`, `CheckConstraint("usage_type IN ('MODEL','TOOL')")`)，唯一键升级为 `(tenant_id, user_id, usage_month, usage_type, model_id)`。
  - 将 `tool_pricing` 与 `tool_call` 模块登记到 `tenant_filter.py` 的 `_TENANT_AWARE_MODEL_MODULES`（C3）。
  **依赖**: 无

- [x] **T002**: MySQL + DM8 双库 Alembic 迁移脚本（含回滚方案）
  **文件**: `src/backend/bisheng/core/database/alembic/versions/v3_1_0_f001_credit_billing_extension.py`
  **逻辑**:
  - `upgrade()`：创建 `dsh_tool_pricing`、`dsh_tool_call`；给 `dsh_model_call` 添加可空列 `source_type`、`source_id`；给 `dsh_monthly_usage` 添加 `usage_type`（`server_default='MODEL'`）并按方言安全重建唯一键（DM8 先 `DROP CONSTRAINT uq_dsh_usage_user_model_month` 再 `ADD CONSTRAINT`；全程使用 `JsonType` 与标准 DDL，禁止 MySQL 专有语法，满足 C2）。
  - `downgrade()`：删除 `dsh_monthly_usage` 新唯一键并清理 `usage_type='TOOL'` 行后恢复旧唯一键与删列；删除 `dsh_model_call` 新列；删除 `dsh_tool_call` 与 `dsh_tool_pricing`。
  **覆盖 AC**: AC-31
  **依赖**: T001

- [x] **T003**: 全局「积分与计费总开关」配置测试（Test-First）
  **文件**: `src/backend/test/dsh/test_credit_billing_switch.py`
  **逻辑**: 测试 `Settings.credit_billing.enabled` 默认 `True`；测试 YAML/env 关闭后 `credit_billing.enabled == False`；测试存量配置残留 `dsh.enabled` / `bs_client.enabled` 时 `normalize_client_settings` 平滑忽略不报错；测试桌面端 `/dsh/browser-config` 在总开关关闭时仍返回 `management_enabled=True` 且 `credit_billing_enabled=False`，桌面端模型接口按可见范围放行不扣分、不拦 `26121`。
  **覆盖 AC**: AC-27, AC-28, AC-29, AC-30
  **依赖**: 无

- [x] **T004**: 取消 `settings.dsh.enabled` 耦合门控并实现 `settings.credit_billing.enabled`
  **文件**: `src/backend/bisheng/core/config/dsh.py`, `src/backend/bisheng/core/config/settings.py`, `src/backend/bisheng/dsh/api/endpoints/settings.py`
  **逻辑**: 新增 `CreditBillingConf(enabled: bool = True)` 挂载至 `Settings.credit_billing`；从 `DshSettings` 移除 `enabled` 门控并在 `Settings.normalize_client_settings` 中兼容忽略存量 `dsh.enabled` / `bs_client.enabled`（见 design §5 坑 6）；桌面端 `access_runtime.py`、`dsh/api/endpoints/settings.py`、`user.py` 的 `_dsh_enabled` 改为常驻可用；`/dsh/browser-config` 透传 `credit_billing_enabled`；T003 对应配置断言通过。
  **覆盖 AC**: AC-27, AC-30
  **依赖**: T003

- [x] **T005**: 切换全仓积分/配额/桌面模型/Worker 门控至 `settings.credit_billing.enabled`
  **文件**: `src/backend/bisheng/dsh/domain/services/model_catalog.py`, `src/backend/bisheng/dsh/api/endpoints/unified_policy.py`, `src/backend/bisheng/dsh/api/endpoints/models.py`, `src/backend/bisheng/workstation/api/endpoints/config.py`, `src/backend/bisheng/worker/config.py`
  **逻辑**: 将原检查 `settings.dsh.enabled` 控制积分、倍率提示（`pricing_hint`）与模型授权的地方切换为 `settings.credit_billing.enabled`；总开关关闭时桌面端 `/dsh/models` 与网页端均走 `visible_workbench_models` 保留平台模型可见范围，`/dsh/chat/completions` 与 `/dsh/responses` 跳过 Redis 额度检查与扣费，`/dsh/credits` 返回不限额未启用态；Celery DSH 投影/恢复任务保持常驻（保障重开时账本完整）；T003 全部通过。
  **覆盖 AC**: AC-27, AC-28, AC-29, AC-30
  **依赖**: T004

---

### Wave 2：统一账本底座（Lua、投影、自动恢复与对账）

- [x] **T006**: 统一账本工具入账、4 处守恒校验与故障恢复单元测试（Test-First）
  **文件**: `src/backend/test/dsh/test_tool_billing_ledger.py`
  **逻辑**: 测试 `check_tool_quota.lua`（`used < limit` 放行、`used >= limit` 拒单、`gate` 非 `READY` 拒单）、`record_tool_usage.lua`（原子累加 `:month.used` 与 `:tools:{YM}`、大整数精度、幂等防重、写 `:events` Stream）；测试 `admit.lua`、`read_usage.lua`、`policy.lua`（`install`）及 `AutomaticQuotaRecovery.healthy()` 对 `sum(:models) + sum(:tools) == :month.used` 的校验及历史无 `:tools` 月份兼容；测试 `DshProjectionService` 分流落库 `dsh_tool_call` 与 `dsh_monthly_usage(usage_type='TOOL')`、`recovery_snapshot()` 合并重算一致性、`new_month_proof` / `new_user_proof` 检查 `DshToolCall`。
  **覆盖 AC**: AC-25, AC-26
  **依赖**: T001

- [x] **T007**: 新增 `check_tool_quota.lua`、`record_tool_usage.lua` 并升级 4 处守恒校验
  **文件**: `src/backend/bisheng/dsh/infrastructure/lua/check_tool_quota.lua`, `src/backend/bisheng/dsh/infrastructure/lua/record_tool_usage.lua`, `src/backend/bisheng/dsh/infrastructure/lua/admit.lua`, `src/backend/bisheng/dsh/infrastructure/lua/read_usage.lua`, `src/backend/bisheng/dsh/infrastructure/lua/policy.lua`
  **逻辑**: 实现工具前置额度检查与事后原子入账脚本（大整数字符串运算、幂等键、写 `:events` Stream 带 `event_kind="tool"`）；将 `admit.lua`、`read_usage.lua`、`policy.lua` 的守恒等式全部升级为 `sum(:models:{YM}) + sum(:tools:{YM}) == :month:{YM}.used`（无 `:tools:{YM}` 按 0 处理，见 design §5 坑 1）。
  **覆盖 AC**: AC-26
  **依赖**: T006

- [x] **T008**: 扩展 `ToolUsageEvent`、`QuotaRedis`、`AutomaticQuotaRecovery`、`DshProjectionService` 与 `DshUsageRepository`
  **文件**: `src/backend/bisheng/dsh/domain/schemas/usage.py`, `src/backend/bisheng/dsh/infrastructure/quota_redis.py`, `src/backend/bisheng/dsh/domain/services/automatic_quota_recovery.py`, `src/backend/bisheng/dsh/domain/services/projection.py`, `src/backend/bisheng/dsh/domain/repositories/usage.py`, `src/backend/bisheng/dsh/domain/repositories/policy.py`
  **逻辑**:
  - `usage.py`（schemas）新增 `ToolUsageEvent` 及 `UsageEvent` 可选字段 `source_type` / `source_id`。
  - `QuotaRedis` 新增 `check_tool_quota()` 与 `record_tool_usage()`，并在调用 `admit.lua` / `read_usage.lua` / `policy.lua` 时传入 `:tools:{YM}` 键。
  - `AutomaticQuotaRecovery` 合并 `dsh_model_call` 与 `dsh_tool_call` 重建 `:models`、`:tools` 与 `:month.used`。
  - `DshProjectionService` 按 `event_kind` 分流；`DshUsageRepository` 批量 upsert `dsh_tool_call`、按 `(usage_type, model_id)` 更新 `dsh_monthly_usage`、`persisted_usage()` / `recovery_snapshot()` / `new_month_proof()` 及 `policy.py:new_user_proof()` 同步兼容工具记录（见 design §5 坑 4）；T006 全部通过。
  **覆盖 AC**: AC-25, AC-26
  **依赖**: T001, T006, T007

---

### Wave 3：工具设价管理、多租户复制与 `ToolExecutor` 执行扣费

- [x] **T009**: 工具定价服务、换算公式、乐观锁与多租户生命周期单元测试（Test-First）
  **文件**: `src/backend/test/dsh/test_tool_pricing.py`
  **逻辑**: 测试按金额（CNY/USD 跨币种换算、`call_count=1000` 向上取整至 6 位小数）与按积分（固定扣分不受积分单价变化影响）换算公式；测试 `call_count` 越界（`0` / `1000001`）与价格越界校验；测试 `version` 乐观锁冲突返回 `26130`；测试超管与本租户管理员可写、普通用户/非管理员被拒；测试子公司初始化复制内置工具价格后总/子独立互不同步；测试 API/MCP 刷新保留原价、新增默认 0、被删工具与删组清价。
  **覆盖 AC**: AC-01, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-14
  **依赖**: T001

- [x] **T010**: 实现 `ToolPricingRepository`、`ToolPricingService` 与工具定价 API 端点
  **文件**: `src/backend/bisheng/dsh/domain/repositories/tool_pricing.py`, `src/backend/bisheng/dsh/domain/services/tool_pricing.py`, `src/backend/bisheng/dsh/api/endpoints/tool_pricing.py`, `src/backend/bisheng/dsh/api/router.py`
  **逻辑**: 实现按 `(tenant_id, tool_id)` 的价格查询与保存（`version` 乐观锁 + `dsh_unified_policy_audit` 审计）、微单位整数 `ceil_div` 换算函数；注册 `GET /api/v1/dsh/admin/tool-pricing` 与 `PUT /api/v1/dsh/admin/tool-pricing/{tool_id}`（`request_scope=S.TENANT`，复用 `UserPayload.get_tenant_admin_user` + `DshManagementService.authorize`）。
  **覆盖 AC**: AC-01, AC-03, AC-04, AC-05, AC-06, AC-09, AC-10
  **依赖**: T001, T009

- [x] **T011**: 接入子公司内置工具价格复制与 API/MCP 工具删改清价联动
  **文件**: `src/backend/bisheng/workstation/domain/services/workstation_service.py`, `src/backend/bisheng/tool/domain/models/gpts_tools.py`
  **逻辑**: 在 `acopy_root_builtin_tools_to_tenant` 中仅对新创建的子租户 `GptsTools` 行复制总公司 `dsh_tool_pricing`（跳过已有 `tool_key`，之后互不同步）；在 `GptsToolsDao.update_tool_type`（按 `delete_tool_id_list`）与 `delete_tool_type` 中联动清理对应 `dsh_tool_pricing` 记录；T009 全部通过。
  **覆盖 AC**: AC-07, AC-08, AC-14
  **依赖**: T010

- [x] **T012**: `ToolExecutor` 扣费埋点与实时拦截单元测试（Test-First）
  **文件**: `src/backend/test/tool/test_tool_executor_billing.py`
  **逻辑**: 测试价格为 0 时不查 Redis、不扣费、不拦截；测试权限/启用/缺 Key 前置校验失败时不扣费；测试非任务模式下收费工具在 `used < limit` 时放行（允许当次轻微透支）且 `used >= limit` 时执行前直接抛 `26121` 不执行不扣费；测试成功/失败/超时/取消均扣费，且 Linsight 软错误转换前准确捕获 `failed` 状态；测试执行中途改价按开始时快照结算；测试开放 API 标记与总开关关闭时跳过扣费。
  **覆盖 AC**: AC-01, AC-11, AC-12, AC-13, AC-14, AC-15, AC-22, AC-25, AC-28
  **依赖**: T008, T010

- [x] **T013**: 在 `ToolExecutor._run / _arun` 接入工具实时拦截与扣费埋点
  **文件**: `src/backend/bisheng/tool/domain/services/executor.py`, `src/backend/bisheng/dsh/domain/services/tool_billing.py`
  **逻辑**: 新建 `ToolBillingService` 封装价格快照直读、换算、非任务模式前置额度检查（`check_tool_quota`）与事后 `asyncio.shield` 写入（`record_tool_usage`）；在 `ToolExecutor._run / _arun` 中于 `_require_current_use` / `ensure_enabled` / `_current_image_tool` 之后、`instance._run / _arun` 之前插入检查，并在 Linsight 软错误转换前捕获真实失败状态（见 design §5 坑 2）；T012 全部通过。
  **覆盖 AC**: AC-01, AC-11, AC-12, AC-13, AC-14, AC-15, AC-25
  **依赖**: T008, T010, T012

---

### Wave 4：助手、工作流、任务模式、开放 API 与托管应用计费

- [x] **T014**: 助手、工作流、任务模式与免登录计费单元测试（Test-First）
  **文件**: `src/backend/test/dsh/test_app_and_task_billing.py`
  **逻辑**: 测试 `chat_credits.governed()` 放行 `assistant`、`workflow`、`hosted_app` 的 `model_gateway`；测试助手/工作流 `admin_selected=True` 豁免员工可选模型限制；测试工作台/调试（扣调试者）/免登录（扣本租户运行身份，拒绝跨租户默认管理员）扣费归属；测试工作流多节点运行中途超额立即中止并抛 `26121`；测试任务模式 `_execute_workflow` / `_continue_workflow` 启动前检一次、生命周期内含 `_resume_workflow`（`ask_user` 恢复）与工具调用全程不拦截。
  **覆盖 AC**: AC-15, AC-16, AC-17, AC-18, AC-19, AC-20, AC-21
  **依赖**: T005, T008, T013

- [x] **T015**: 扩展 `chat_credits.py` 与助手/工作流 LLM 实例化及来源透传
  **文件**: `src/backend/bisheng/dsh/domain/services/chat_credits.py`, `src/backend/bisheng/api/services/assistant_agent.py`, `src/backend/bisheng/workflow/nodes/llm/llm.py`, `src/backend/bisheng/workflow/nodes/agent/agent.py`, `src/backend/bisheng/workflow/nodes/rag/rag.py`, `src/backend/bisheng/workflow/nodes/input/input.py`
  **逻辑**: `chat_credits.governed()` 切换至 `settings.credit_billing.enabled`，新增放行 `assistant`、`workflow` 与受控 `model_gateway`，命中 `open_api_unbilled` 返回 `False`；新增 `billing_context(source_type, source_id, open_api_unbilled)` ContextVar 写入 `UsageEvent`；助手与工作流全部 `get_bisheng_llm` / `get_bisheng_llm_sync` 调用显式置 `admin_selected=True`；免登录路径严格维持 `UserTenant` 校验（不放行跨租户）。
  **覆盖 AC**: AC-17, AC-18, AC-20, AC-21, AC-25
  **依赖**: T005, T008, T014

- [x] **T016**: 工作流 Celery 节点级 `26121` 错误回传与任务模式 `ask_user` 单周期延续（Worker）
  **文件**: `src/backend/bisheng/worker/workflow/tasks.py`, `src/backend/bisheng/worker/workflow/redis_callback.py`, `src/backend/bisheng/linsight/domain/task_exec.py`
  **逻辑**:
  - 工作流 Celery `_execute_workflow` / `_continue_workflow` 依赖既有 `durable_workload_scope`（headers → `current_tenant_id` ContextVar）与 `OpenApiExecutionSnapshot` 恢复租户与来源上下文，**不使用** `admit_round` / `unmetered()`，捕获 `DshMonthlyTokenLimitExceededError` 后向前端下发带状态码 `26121` 的失败事件并中止后续节点。
  - 任务模式 `task_exec.py`：保留 `_execute_workflow` / `_continue_workflow` 的 `admit_round(llm)` 启动检查；调整 `_resume_workflow`（`ask_user` 恢复）不再二次 `probe`，直接进入 `chat_credits.unmetered()` 延续同一任务生命周期（见 design §5 坑 3）；若 `session_model.api_meta.get("channel") == OPEN_API_CHANNEL` 则置 `open_api_unbilled=True` 跳过 `admit_round` 与全部扣费；T014 全部通过。
  **覆盖 AC**: AC-15, AC-16, AC-19, AC-22
  **依赖**: T013, T015

- [x] **T017**: 开放 API 免计费与托管应用 OBO 计费单元测试（Test-First）
  **文件**: `src/backend/test/open_api/test_gateway_credit_billing.py`
  **逻辑**: 测试服务账号与代员工开放 API 调用助手、工作流、深度研究、模型网关全程不算账且不受 `26121` 拦截；测试托管应用（`actor_kind="hosted_app"`）带有效 OBO 令牌扣访问人、无令牌扣应用负责人、审批预览（`preview_session_id`）扣应用负责人、带过期/伪造令牌维持 `26504` 拒绝；测试托管应用额度用完返回 HTTP 429 与 `{"error": {"type": "rate_limit_error", "code": "credit_exhausted", "bisheng_code": 26121}}`。
  **覆盖 AC**: AC-22, AC-23, AC-24
  **依赖**: T015

- [x] **T018**: 实现开放 API 免计费上下文透传与托管应用 `ModelGatewayService` 扣费及 429 映射
  **文件**: `src/backend/bisheng/open_api/domain/services/model_gateway_service.py`, `src/backend/bisheng/open_api/api/exception_handlers.py`, `src/backend/bisheng/open_api/application/access_context.py`, `src/backend/bisheng/open_api/domain/services/execution_context.py`
  **逻辑**:
  - 开放 API 入口（`access_context.py` / `execution_context.py`）对非 `hosted_app` 请求设置 `open_api_unbilled=True` 并随 `OpenApiExecutionSnapshot` 透传至 Celery。
  - `ModelGatewayService._instantiate()` 仅对 `hosted_app` 置 `admin_selected=True` 并按 `preview_session_id -> resource_owner_user_id`、`subject.subject_kind == "user" -> subject.subject_id`、`app_self -> resource_owner_user_id` 确定计费人；`_invoke` / `_stream` 捕获 `DshMonthlyTokenLimitExceededError` 记 `RESULT_LIMIT_EXCEEDED` 并重抛；`exception_handlers.py` 的 `_OPENAI_ERROR_BY_CODE` 新增 `26121: ("rate_limit_error", "credit_exhausted")` 且 `open_api_http_status` 返回 `429`；T017 全部通过。
  **覆盖 AC**: AC-22, AC-23, AC-24
  **依赖**: T015, T016, T017

---

### Wave 5：前端 Platform、前端 Client、托管文档与全量回归

#### 前端 Platform（管理后台）

- [x] **T019**: Platform 工具设价 API 封装与浏览器配置总开关适配
  **文件**: `src/frontend/platform/src/controllers/API/toolPricing.ts`, `src/frontend/platform/src/controllers/API/dshSettings.ts`, `src/frontend/platform/src/pages/SystemPage/dsh/index.tsx`
  **逻辑**: 新增 `getToolPricingApi(tenantId?)` 与 `saveToolPricingApi(toolId, payload, tenantId?)`；扩展 `DshBrowserConfig` 解析 `credit_billing_enabled`；总开关关闭时隐藏管理后台积分设置、积分规则、积分用量菜单/面板，保留桌面端接入配置与模型审计。
  **覆盖 AC**: AC-02, AC-03, AC-28
  **依赖**: T005, T010

- [x] **T020**: Platform 新增统一「设置价格」弹框组件与 `ToolItem.tsx` 价格列接入
  **文件**: `src/frontend/platform/src/pages/BuildPage/tools/ToolPriceDialog.tsx`, `src/frontend/platform/src/pages/BuildPage/tools/ToolItem.tsx`, `src/frontend/platform/src/pages/BuildPage/tools/index.tsx`
  **逻辑**:
  - 新建 `ToolPriceDialog.tsx`：支持计价方式（按金额/按积分）、次数（`1 ~ 1,000,000` 正整数，默认 `1`）、币种、价格（`0 ~ 999999.999999` 最多 6 位小数）、实时单次换算提示、保存与 `26130` 并发冲突提示；不修改 `WebSearchFrom.tsx` 与 `WebFetchForm.tsx`。
  - `ToolItem.tsx` 在内置/API/MCP 三页签（含联网搜索、网页读取）二级工具行统一展示价格与仅管理员可见的「设置价格」按钮；`credit_billing_enabled === false` 时隐藏价格列与按钮。
  - 补充 Vitest 测试：`src/frontend/platform/src/pages/BuildPage/tools/ToolPriceDialog.test.tsx`。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-28
  **手动验证**:
  - 管理员进入「构建 → 工具与技能」三页签，分别展开联网搜索、天眼查、API、MCP 工具组，测试设价校验、实时换算、保存与刷新回显；切换普通用户确认无「设置价格」按钮；切换子公司管理视图确认价格独立读写。
  **依赖**: T019

- [x] **T021**: Platform 三语国际化文案补齐（`zh-Hans` / `en-US` / `ja`）
  **文件**: `src/frontend/platform/public/locales/zh-Hans/tool.json`, `src/frontend/platform/public/locales/en-US/tool.json`, `src/frontend/platform/public/locales/ja/tool.json`
  **逻辑**: 补充工具价格显示（「免费」、「设置价格」、次数/价格校验提示、换算提示、并发冲突文案）三语翻译，运行 `pnpm check-i18n` 通过。
  **覆盖 AC**: AC-02, AC-03, AC-06
  **依赖**: T020

#### 前端 Client（网页工作台）

- [x] **T022**: Client 助手、工作流（启动/中途节点）与免登录访客页接入 `ChatErrorCard`
  **文件**: `src/frontend/client/src/pages/appChat/useWebsocket.ts`, `src/frontend/client/src/pages/appChat/ChatMessages.tsx`, `src/frontend/client/src/pages/appChat/useChatHelpers.ts`
  **逻辑**: 统一拦截助手对话、工作流运行（含启动时与运行中途节点失败帧，解决原仅弹 toast 问题，见 design §5 坑 5）及免登录访客页的 `26121` / `credit_exhausted` 错误，在对话/运行消息流末尾直接渲染现有 `ChatErrorCard` 组件。补充 Vitest 测试 `src/frontend/client/src/pages/appChat/creditExhausted.test.tsx`。
  **覆盖 AC**: AC-18, AC-19, AC-21
  **手动验证**:
  - 员工余额归零后分别在网页工作台使用助手、运行工作流（含运行中途耗尽）以及通过免登录链接访问，确认均直接显示「本月积分已用完」卡片。
  **依赖**: T015, T016

- [x] **T023**: Client 侧边栏余额与模型倍率响应 `credit_billing_enabled` 总开关
  **文件**: `src/frontend/client/src/hooks/useDshDesktop.ts`, `src/frontend/client/src/components/dsh/SidebarCredits.tsx`, `src/frontend/client/src/components/Chat/AiModelSelect.tsx`
  **逻辑**: 解析 `browser-config` 的 `credit_billing_enabled`；当总开关关闭时隐藏 `SidebarCredits` 与模型倍率显示，不影响桌面端/工作台正常选模型与对话。更新 `SidebarCredits.test.tsx`。
  **覆盖 AC**: AC-28, AC-30
  **手动验证**:
  - 将 `credit_billing.enabled` 置 `false` 重启，刷新工作台确认侧边栏无余额、模型下拉框无倍率，对话正常。
  **依赖**: T005

#### 文档与全量验证

- [x] **T024**: 更新托管应用开发文档（OBO 令牌透传与 HTTP 429 `credit_exhausted` 指引）
  **文件**: `docs/architecture/` 或托管应用开发文档对应章节（实现阶段定位现有托管应用接入文档路径并同步更新）
  **逻辑**: 补充两点规范说明：① 调用模型网关时透传平台注入的 `X-BiSheng-Access-Token`（否则计入应用负责人；后台无访问人任务不带；过期/伪造返 `26504`）；② 处理 HTTP 429 `code="credit_exhausted"`（`bisheng_code=26121`）及建议展示文案。
  **覆盖 AC**: AC-32
  **依赖**: T018

- [x] **T025**: 后端静态门禁、单元测试与前端 Vitest / i18n 全量回归
  **文件**: `scripts/arch-guard.sh`（运行验证，不改脚本）
  **逻辑**: 运行 `scripts/arch-guard.sh`、`ruff check`、全量新增 pytest（`test/dsh/`、`test/tool/`、`test/open_api/`）、前端 `pnpm check-i18n` 与 Vitest 测试；确认全部通过。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-24, AC-25, AC-26, AC-27, AC-28, AC-29, AC-30, AC-31, AC-32
  **依赖**: T002, T011, T013, T016, T018, T021, T022, T023, T024

---

## 实际偏差记录

> 只留一行指针，论证写在 `design.md`（决策 / 坑）。

- 已完成 `T001`–`T025` 代码与自动化单测实现；真实浏览器/多容器中间件（MySQL/DM8/Redis/Celery/E2E）手动验收待在联调环境执行。
- 实际补充改动文件：`GraphEngine`（`workflow/graph/graph_engine.py`）增加结构化错误透传；`access_context.py` 与 `http_status.py` 位于 `open_api/domain/`；Platform 新增同步适配 `DshPage/index.tsx` 与 `WorkbenchModel.tsx`；Client 新增同步适配 `api/dsh.ts`、`DshDesktopPanel.tsx` 与 `DshDesktopPane.tsx`；托管应用开发文档落点为 `src/backend/bisheng/dev_toolkit/skills/platform-wiring/SKILL.md`。
