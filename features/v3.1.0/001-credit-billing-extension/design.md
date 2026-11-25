# Design: 积分扣费扩展（工具调用 + 助手 / 工作流 / 托管应用 + 计费总开关）

> **本文档定位 — 现状与目标实现快照（Why this How）**
>
> - [spec.md](./spec.md) 回答 **做什么**（目标、AC-01 ~ AC-32、边界）
> - `design.md`（本文）回答 **为什么这么实现**：关键决策、运行时不直观的事实、对外契约
> - [tasks.md](./tasks.md) 是 **流水账**：分波次任务清单与偏差指针

**关联**: [spec.md](./spec.md) · [release-contract.md](../release-contract.md) · [test-cases.md](./test-cases.md) · [tasks.md](./tasks.md)  
**版本**: v3.1.0（F001-credit-billing-extension）  
**最后更新**: 2026-11-24（依据 PRD v1.0 与 2026-11-24 技术评审定稿初版）

---

## 1. 目标与非目标

- **目标**：在不另起积分体系的前提下，扩展 F016/F062 统一积分账本与计费底座，补齐「工具按次扣费」「助手/工作流/托管应用模型扣费」「开放 API 统一免计费」，并解耦原 `settings.dsh.enabled`，以独立全局配置开关控制全平台积分与计费能力。
- **非目标**：
  - 不做员工端工具价格展示、新统计报表页、应用卡片预估积分展示；
  - 不对开放 API（服务账号 / 代员工）、非聊天模型（Embedding/Rerank）、知识库入库、评测、桌面本机工具/自带 Key 计费；
  - 不按搜索引擎分引擎存价（全工具统一按 `(tenant_id, tool_id)` 存「次数 + 价格」）；
  - 不在积分底座放行跨租户免登录默认操作员（由免登录配置侧约束仅选本租户成员）。

---

## 2. 关键约束与 Constitution Check

- **全局架构铁律**：严格遵循 [docs/constitution.md](../../../docs/constitution.md) C1–C8 及 [release-contract.md](../release-contract.md) `INV-1` ~ `INV-6`（不在此重复抄录）。
- **本特性特有硬约束**：
  1. **全整数微单位精度**：复用 F016 约定，`1 积分 = 1,000,000 微积分（billed_tokens）`，金额与汇率放大 `10⁶` 倍以 `BIGINT` 存储，除法一律 `ceil_div` 向上取整，杜绝浮点误差。
  2. **价格直读不走缓存**：工具与模型调用前必须直读 DB 最新价格并冻结为调用快照，保证改价立即对新调用生效、不影响进行中的调用（AC-11）。
  3. **Redis 账本大整数字符串运算**：Lua 侧维持字符串十进制大整数加法，避免 Lua 5.1 双精度浮点超过 `2^53` 丢精度；所有守恒等式须同步兼容无 `:tools:{YM}` 的历史月份。
  4. **DM8 约束重建限制**：`dsh_monthly_usage` 变更唯一键时，达梦需先显式 `DROP CONSTRAINT` 再 `ADD CONSTRAINT`，不得依赖 MySQL 的 `ALTER TABLE ... DROP INDEX` 专有语法。
  5. **配置向后兼容**：移除 `settings.dsh.enabled` / `bs_client.enabled` 门控后，存量 YAML 若仍写有该字段，配置反序列化须平滑忽略而非报错阻断启动（AC-30 / spec §3）。

### Constitution Check（C1–C8 自检）

| 条款 | 检查结论 | 本设计落点 |
|---|---|---|
| **C1 DDD 分层** | ✅ 通过 | `dsh/api/endpoints/tool_pricing.py` → `ToolPricingService` → `ToolPricingRepository` → ORM；Endpoint 不直接导入 ORM 或写查询 |
| **C2 MySQL + DM8 双库** | ✅ 通过 | `dsh_tool_call.pricing_snapshot` 使用 `dialect_helpers.JsonType`；时间戳使用 `UPDATE_TIME_SERVER_DEFAULT`；Alembic 迁移同时兼容 MySQL/DM8 唯一键变更 |
| **C3 多租户自动注入** | ✅ 通过 | 新表 `dsh_tool_pricing`、`dsh_tool_call` 均含 `tenant_id` 并登记至 `core/database/tenant_filter.py` 的 `_TENANT_AWARE_MODEL_MODULES`；不手写 `WHERE tenant_id = X`（仅 `acopy_root_builtin_tools_to_tenant` 跨租户复制在 `bypass_tenant_filter()` 下显式指定） |
| **C4 统一鉴权** | ✅ 通过 | 工具设价接口沿用 `UserPayload.get_tenant_admin_user` + `DshManagementService.authorize(actor_id, target_tenant_id)`（超管 + 本租户管理员）；资源使用鉴权仍走 F048 `check_business_action` |
| **C5 错误码与三语 i18n** | ✅ 通过 | 复用 `26121`（本月积分已用完）、`26130`（版本冲突）、`26504`（访问人令牌拒绝）；不新增模块号；托管应用 `26121` 通过 `_OPENAI_ERROR_BY_CODE` 映射为 HTTP 429 `credit_exhausted` |
| **C6 无硬编码密钥** | ✅ 通过 | 价格独立建表 `dsh_tool_pricing`，不混入存 API Key 的 `t_gpts_tools_type.extra` |
| **C7 前端分层** | ✅ 通过 | `platform` 管理后台通过 `controllers/API/` 封装 HTTP 调用，`client` 工作台通过既有 WS/API 消费，不在 store 中直接发 HTTP |
| **C8 无本地共享状态** | ✅ 通过 | 所有实时账本、并发锁与异步投影状态均在 Redis + MySQL/DM8 |

---

## 3. 方案对比与选定

### 决策 1：统一账本如何兼容无 `model_id` 的工具扣费

- **备选**：
  - A. 工具扣费仅累加 Redis `:month:{YM}.used`，MySQL `dsh_monthly_usage` 约定 `model_id = 0` 汇总全部工具。
  - B. Redis 新增 `:tools:{YM}` Hash（按 `tool_id` / `tool_key` 累计），升级全部守恒校验为 `sum(:models:{YM}) + sum(:tools:{YM}) == :month:{YM}.used`；MySQL `dsh_monthly_usage` 新增非空列 `usage_type`（`MODEL` / `TOOL`，默认 `MODEL`）并升级唯一键为 `(tenant_id, user_id, usage_month, usage_type, model_id)`（`TOOL` 行在 `model_id` 存 `tool_id`）。
  - C. 为工具完全独立建一套 Redis 额度键与 MySQL 汇总表 `dsh_monthly_tool_usage`。
- **选定**：**B**（2026-11-24 评审会已拍板）
- **原因**：
  - 源码核查证实，Redis 账本在 `admit.lua`、`read_usage.lua`、`policy.lua`（`install` 分支）与 `AutomaticQuotaRecovery.healthy()` **4 处**硬校验 `sum(:models:{YM}) == :month:{YM}.used`，方案 A 会立刻触发 `incomplete_model_ledger` 拒单或死循环恢复；
  - 方案 B 用 `usage_type` 明确区分 `MODEL` 与 `TOOL` 命名空间，既避免 `model_id = 0` 魔术值无法区分工具的问题，也比方案 C 少维护一张月度汇总表，历史行自动默认 `'MODEL'` 零迁移成本。
- **何时该重新考虑**：当未来新增第三类非模型/非工具计费项且需要完全独立的计费周期（如按日额度池）时，再拆独立额度池与汇总表。

### 决策 2：非任务模式工具实时额度拦截 + 事后原子入账

- **备选**：
  - A. 工具全程不做额度拦截（原 PRD v1.0 口径），仅事后入账。
  - B. 工具走完整两阶段模型 `admit.lua`（写 `RUNNING` + `:running` ZSet）→ `settle.lua`。
  - C. 两步轻量路径：非任务模式且价格 > 0 的工具在执行前调用 `check_tool_quota.lua` 校验 `:gate` READY 且 `used < limit`（不写 `RUNNING`）；进入执行后在 `finally` 中通过 `record_tool_usage.lua` 单次原子累加 `:month:{YM}.used`、`:tools:{YM}` 并追加 `:events` Stream。价格 = 0 或任务模式生命周期内跳过前置拦截。
- **选定**：**C**（2026-11-24 评审会已拍板）
- **原因**：
  - 评审会决定除任务模式外所有场景均须实时拦截（AC-13），否定方案 A；
  - 工具调用价格在执行前固定已知且按「开始执行即扣，失败/超时/取消均扣」结算，不存在模型调用的 `USAGE_UNKNOWN` 异步对账态，因此方案 B 写 `:running` ZSet 与两阶段状态机属于冗余复杂度；方案 C 保留 `used < limit` 拦截语义与幂等防重，同时大幅简化恢复状态机。
- **何时该重新考虑**：若未来出现「按工具实际返回页数/时长后计费」的动态计价工具，需引入类似模型的 `RUNNING` / `USAGE_UNKNOWN` 对账流。

### 决策 3：全工具统一设价交互与数据结构（取消引擎维度 + 支持次数配置）

- **备选**：
  - A. 按原 PRD：搜索类固定每千次、按 `(tenant_id, tool_id, engine)` 存价，并把价格表单嵌入 `WebSearchFrom.tsx` / `WebFetchForm.tsx` 及独立 `/tool/web_search` 保存接口。
  - B. 全工具统一按 `(tenant_id, tool_id)` 存「`call_count`（正整数，默认 1）+ 价格」，联网搜索/网页读取不区分引擎，所有工具统一走列表「设置价格」弹框与独立设价接口。
- **选定**：**B**（2026-11-24 评审会已拍板）
- **原因**：`web_search` 已拆出带 `revision` 锁的专用接口，而 `web_fetch` 仍走 `updateToolApi`，方案 A 会制造两条保存路径与前后端特殊分支；方案 B 让管理员通过自由填写 `call_count`（如 `1000` 次）自然表达千次报价，前后端彻底统一一套弹框、一张表和一条接口。
- **何时该重新考虑**：当企业客户强烈要求同一租户内频繁切换搜索引擎且每个引擎保留不同报价时，再扩展 `engine` 维度。

### 决策 4：工作流节点级实时拦截 vs 任务模式单周期豁免

- **备选**：
  - A. 工作流复用任务模式 `admit_round` + `unmetered()`，仅运行前检一次，中途不打断。
  - B. 工作流取消 `admit_round` / `unmetered()`，所有大模型节点与收费工具节点均实时校验额度并实时扣费；仅任务模式（Linsight）在发起新任务/追问时校验一次，单次任务生命周期内（含 `ask_user` 中断恢复 `_resume_workflow`）全程 `unmetered` 实时入账不拦截。
- **选定**：**B**（2026-11-24 评审会已拍板）
- **原因**：评审会统一收紧口径——仅长周期自主规划的任务模式需要避免中途掐断，工作流与助手均为明确步骤执行，需实时控费（AC-16、AC-19）。同时代码核查发现 `task_exec.py` 的 `_resume_workflow()` 目前也会调 `_get_round_llm` -> `admit_round`，须改为直接进入 `unmetered` 延续同一任务生命周期。
- **何时该重新考虑**：若未来工作流引入「单次运行预冻结预算」能力，可改为预占扣减模型。

### 决策 5：托管应用 OBO 令牌校验与开放 API 豁免分流

- **备选**：
  - A. 托管应用携带过期/伪造 `X-BiSheng-Access-Token` 时降级扣应用负责人（原 PRD 字面）。
  - B. 维持 `model_range_policy.py` 现有安全门控：无令牌 → 扣应用负责人；有效令牌 → 扣访问人；审批预览（`preview_session_id` 非空）→ 扣应用负责人；过期/伪造令牌 → 维持报错 `26504`。非 `hosted_app` 的开放 API 在入口设置 `open_api_unbilled` 上下文标记（并透传至 Celery `execution_snapshot` 与深度研究 `api_meta.channel == "open_api_v2"`）全程跳过计费。
- **选定**：**B**（2026-11-24 评审会已拍板）
- **原因**：防止恶意伪造/过期令牌将费用转嫁给应用负责人；同时复用 `open_api/api/exception_handlers.py` 的 `_OPENAI_ERROR_BY_CODE` 将 `26121` 直接渲染为 OpenAI 兼容 HTTP 429 (`credit_exhausted`)，无需新申请 `265xx` 错误码。
- **何时该重新考虑**：若开放 API 后续上线商业化按调用方计费（服务账号配额池），再移除非 `hosted_app` 的 `open_api_unbilled` 豁免。

### 决策 6：免登录运行身份多租户隔离

- **备选**：
  - A. 在积分底座（`CurrentIdentityRecords` 与 `DshUsageRepository.project_batch`）对免登录默认操作员放行 `UserTenant` 归属检查。
  - B. 积分底座不放行跨租户校验，维持 `UserTenant` 严格隔离；由免登录「运行身份」配置端约束仅选本租户成员。
- **选定**：**B**（2026-11-24 评审会已拍板）
- **原因**：代码核查显示 `guest_link.py`（`_validate_new_operator`）与 `guest_policy.py`（`_load_operator_payload`）已在保存与运行时强制校验本租户成员，不应在积分账本层破坏多租户隔离不变量（`INV-4`）。
- **何时该重新考虑**：仅当平台产品定义改为允许全局超管在无租户成员关系下拥有跨租户计费账本时。

### 决策 7：取消 `settings.dsh.enabled`，解耦全局「积分与计费总开关」

- **备选**：
  - A. 继续沿用 `settings.dsh.enabled` 同时控制桌面端接入与积分计费。
  - B. 做成后台数据库可动态切换的租户级 UI 开关。
  - C. 取消 `settings.dsh.enabled` 对桌面端与积分的耦合（桌面端基础接入常驻可用），在 `Settings` 新增全局进程级配置开关 `credit_billing.enabled`（默认 `True`），关闭时停用全平台（含桌面端与网页端）积分/计费/额度拦截，保留平台原有模型可见范围（`visible_workbench_models`），前后端隐藏积分与工具价格入口。
- **选定**：**C**（2026-11-24 评审会已拍板）
- **原因**：解耦企业桌面客户端与积分计费（关闭积分不影响桌面端登录与对话），复用 `open_platform` 相同的三阶段进程配置模式（YAML → env → appConfig），无运行期热切换并发撕裂风险。
- **何时该重新考虑**：当 SaaS 多租户需要允许各子公司管理员在界面上独立开关本租户积分体系时，再下沉为租户 DB 配置。

---

## 4. 系统现状与目标实现（接手必读）

### 4.1 核心数据流

1. **工具设价与多租户生命周期流**：
   - 设价：`Platform ToolItem.tsx` → `PUT /api/v1/dsh/admin/tool-pricing/{tool_id}` → `ToolPricingService.save_price`（校验超管/本租户管理员 + `call_count ∈ [1, 1_000_000]` + `version` 乐观锁）→ 写 `dsh_tool_pricing` + 写 `dsh_unified_policy_audit`。
   - 子公司初始化：`WorkStationService.acopy_root_builtin_tools_to_tenant` → 仅对新创建的 `GptsTools` 复制对应 `dsh_tool_pricing`（保留 `pricing_mode`/`currency`/`price_micro`/`call_count`，`version=1`）。
   - API/MCP 刷新与删除：`GptsToolsDao.update_tool_type` / `delete_tool_type` → 按被删 `tool_id` 集合同步清理 `dsh_tool_pricing`。

2. **工具执行与按次扣费流**：
   - `ToolExecutor._run / _arun`（[executor.py](file:///Users/wenruli/code/project/bisheng/bisheng/src/backend/bisheng/tool/domain/services/executor.py)）→ 执行既有权限/启用/密钥校验（失败直接抛错，不扣费）→ 检查 `settings.credit_billing.enabled` 与免计费标记（`open_api_unbilled`）→ 直读 `dsh_tool_pricing`（按 `(tenant_id, tool_id)`）与租户 `dsh_credit_setting`，冻结 `ToolPricingSnapshot` 并整数 `ceil_div` 算得 `billed_tokens` → 若 `billed_tokens == 0` 直接执行不入账；若 `billed_tokens > 0` 且非任务模式 `unmetered` 生命周期，先调 `QuotaRedis.check_tool_quota()` 校验 `used < limit`（不足抛 `DshMonthlyTokenLimitExceededError` / `26121` 不执行）→ 执行 `instance._run / _arun`（在 `LINSIGHT` 软错误转换前捕获真实 `failed`/`timeout`/`cancelled` 状态）→ `finally` 中以 `asyncio.shield` 调 `record_tool_usage.lua` 原子累加 `:month:{YM}.used` 与 `:tools:{YM}[tool_key]` 并写 `:events` Stream → `DshProjectionService` 异步投影落库 `dsh_tool_call` 与 `dsh_monthly_usage(usage_type='TOOL')`。

3. **助手、工作流与任务模式模型扣费流**：
   - 助手 / 工作流实例化 `BishengLLM` 时统一传 `admin_selected=True` 并注入 `source_type` / `source_id`；`chat_credits.governed()` 放行 `daily_chat`、`linsight`、`knowledge_space`、`assistant`、`workflow` 及 `hosted_app` 场景的 `model_gateway`（仅当 `settings.credit_billing.enabled` 为 `True` 且未命中 `open_api_unbilled`）。
   - 工作流 Celery [tasks.py](file:///Users/wenruli/code/project/bisheng/bisheng/src/backend/bisheng/worker/workflow/tasks.py)：`_execute_workflow` 与 `_continue_workflow` 均**不**包 `unmetered()`，每个模型节点（`account_sync`）与收费工具节点（`_run`）实时检查并扣费；捕获 `DshMonthlyTokenLimitExceededError` 后置失败并向前端回传 `26121`；工作台 `useWebsocket.ts` / `ChatMessages.tsx` 收到 `26121` 直接在对话/运行流末尾渲染 `ChatErrorCard`。
   - 任务模式 [task_exec.py](file:///Users/wenruli/code/project/bisheng/bisheng/src/backend/bisheng/linsight/domain/task_exec.py)：`_execute_workflow` 与 `_continue_workflow` 入口调 `admit_round(llm)` 检一次额度后置 `_round_admitted=True`；`_resume_workflow`（`ask_user` 恢复）不再二次 `probe`，直接置 `_round_admitted=True` 延续单次任务生命周期，期间模型与工具均实时入账但不拦截。

4. **托管应用与开放 API 分流**：
   - `/api/v2` 入口根据 `OpenApiPrincipal.actor_kind` 分流：非 `hosted_app`（`service_account` / `natural_person`）设置 `open_api_unbilled=True`，透传至 Celery `OpenApiExecutionSnapshot` 与深度研究 `api_meta`（`channel == "open_api_v2"`），模型与工具扣费均跳过；
   - `hosted_app` 调用 `ModelGatewayService`：`resolve_range_and_subject()` 维持令牌验签（过期/伪造抛 `26504`）；`_instantiate()` 置 `admin_selected=True`，扣费人按 `preview_session_id -> resource_owner_user_id`、`subject.subject_kind == "user" -> subject.subject_id`、`app_self -> resource_owner_user_id` 取值；`_invoke` / `_stream` 捕获 `DshMonthlyTokenLimitExceededError` 记 `RESULT_LIMIT_EXCEEDED` 并交由 `render_openai_error` 返回 HTTP 429 + `code: "credit_exhausted"` + `bisheng_code: 26121`。

5. **总开关关闭流（`settings.credit_billing.enabled == False`）**：
   - `chat_credits.governed()` 返回 `False`，`ToolExecutor` 跳过读价与扣费；
   - 桌面端 `DshModelService.complete()` 与 `/dsh/models` 跳过 Redis 额度门控，按 `visible_workbench_models` 返回平台可见模型，`/dsh/credits` 返回 `{unlimited: true, billing_enabled: false}`；
   - `/api/v1/dsh/browser-config` 保持桌面端 `management_enabled: true` 常驻，新增 `credit_billing_enabled: false` 供 `platform` / `client` 前端隐藏全部积分设置、规则、用量、余额、倍率与工具价格入口。

### 4.2 关键数据结构 / 字段约定

| 表 / 结构 | 核心字段与约束 | 说明与消费方 |
|---|---|---|
| `dsh_tool_pricing`（新表） | `id`、`tenant_id`、`tool_id`、`pricing_mode` (`MONEY`/`CREDITS`)、`currency` (`CNY`/`USD`/NULL)、`price_micro` (BIGINT ≥ 0)、`call_count` (BIGINT, `1..1_000_000`, default `1`)、`version` (BIGINT)、`updated_by`、`update_time`；唯一键 `(tenant_id, tool_id)` | 租户隔离（登记 `tenant_filter.py`）；管理后台读/写、`ToolExecutor` 直读、子公司初始化复制 |
| `dsh_tool_call`（新表） | `request_id` (PK, VARCHAR(36))、`tenant_id`、`user_id`、`usage_month` (VARCHAR(7))、`tool_group_id`、`tool_group_name`、`tool_id`、`tool_key`、`engine` (可空排查字段)、`pricing_snapshot` (`JsonType`)、`billed_tokens` (BIGINT)、`cost_micro` (可空 BIGINT)、`currency` (可空 VARCHAR(3))、`result` (`success`/`failed`/`timeout`/`cancelled`)、`source_type`、`source_id`、`started_at`、`ended_at`；索引 `(tenant_id, user_id, started_at)`、`(tenant_id, tool_key, started_at)` | `DshProjectionService` 异步写入；`recovery_snapshot` 重建账本；审计排查 |
| `dsh_model_call`（加列） | 新增可空列 `source_type` (VARCHAR(32))、`source_id` (VARCHAR(64)) | 区分 `daily_chat`、`linsight`、`knowledge_space`、`assistant`、`workflow`、`hosted_app`、`debug`、`guest` 等来源；历史行保持 NULL |
| `dsh_monthly_usage`（加列+改唯一键） | 新增非空列 `usage_type` (VARCHAR(16), default `'MODEL'`, `CHECK (usage_type IN ('MODEL','TOOL'))`)；唯一键变更为 `(tenant_id, user_id, usage_month, usage_type, model_id)` | `MODEL` 行存 `model_id`，`TOOL` 行在 `model_id` 列存 `tool_id`；`persisted_usage` / `recovery_snapshot` 消费 |
| Redis `:tools:{YM}`（新键） | Hash：`{ "<tool_id_or_key>": "<microcredits_str>" }`，与 `:models:{YM}` 同 hash tag `dsh_quota:{tenant:user}` | 参与 4 处等式守恒 `sum(:models) + sum(:tools) == :month.used` |
| Redis `:events` Stream 载荷 | 模型事件沿用原 `UsageEvent`（无 `event_kind` 视为 `"model"`）；工具事件带 `event_kind: "tool"` + `ToolUsageEvent` JSON | `DshProjectionService` 按 `event_kind` 分流；`AutomaticQuotaRecovery` 合并回放 |
| 配置 `Settings.credit_billing` | `CreditBillingConf(enabled: bool = True)`（YAML `credit_billing.enabled` / env） | 替代原 `settings.dsh.enabled` 对积分/计费的门控；`browser-config` 透传 `credit_billing_enabled` |

### 4.3 关键模块职责

| 模块 / 文件 | 职责（做什么） | 边界（不做什么） |
|---|---|---|
| `dsh/domain/services/tool_pricing.py` & `dsh/domain/repositories/tool_pricing.py` | 工具价格 CRUD、微单位整数换算、乐观锁校验、审计记录、子公司复制与删工具清理 | 不做 HTTP 路由解析，不直接调用 Redis 账本 |
| `dsh/api/endpoints/tool_pricing.py` | 工具设价查询/修改 HTTP 入口与管理员权限门控 | 不直接导入 ORM 或编写 SQL（C1） |
| `dsh/infrastructure/quota_redis.py` & `lua/{check_tool_quota,record_tool_usage,admit,read_usage,policy}.lua` | 工具前置额度检查、原子入账、全量守恒校验与自动恢复 | 不读取 MySQL、不做价格换算 |
| `dsh/domain/services/projection.py` & `dsh/domain/repositories/usage.py` | `:events` Stream 分流落库 `dsh_model_call` / `dsh_tool_call` / `dsh_monthly_usage` 及 `recovery_snapshot` 重建 | 不做在线限流拦截 |
| `dsh/domain/services/chat_credits.py` | 统一计费开关判定、来源上下文（`source_type`/`source_id`/`open_api_unbilled`）、模型与工具的计费入口协调 | 不绕过 `UserTenant` 校验 |
| `tool/domain/services/executor.py` | 在前置校验后触发价格快照读取、非任务模式额度检查及 `finally` 扣费 | 不关心工具设价 UI 与价格表维护 |
| `open_api/domain/services/model_gateway_service.py` & `exception_handlers.py` | 托管应用扣费人路由、`admin_selected=True`、将 `26121` 映射为 OpenAI HTTP 429 `credit_exhausted` | 不修改 `model_range_policy.py` 的 `26504` 令牌验签规则 |
| `frontend/platform/src/pages/BuildPage/tools/` | 三页签二级工具价格展示、统一设价弹框（次数+价格+实时换算+乐观锁提示）、总开关显隐控制 | 不改动 `WebSearchFrom.tsx` / `WebFetchForm.tsx` |
| `frontend/client/src/pages/appChat/` | 助手、工作流（启动/中途节点）、免登录访客页统一识别 `26121` 渲染 `ChatErrorCard` | 不新增自定义积分错误卡片样式 |

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | **Redis 账本守恒校验共有 4 处，而非仅 `admit.lua`** | 只改 `admit.lua` 会导致员工查余额（`read_usage.lua`）、管理员改配额（`policy.lua` `install`）或健康检查（`AutomaticQuotaRecovery.healthy()`）持续报 `incomplete_model_ledger` 并触发死循环恢复 | `admit.lua`、`read_usage.lua`、`policy.lua`、`automatic_quota_recovery.py` 全部同步升级为 `sum(:models) + sum(:tools) == :month.used` |
| 2 | **Linsight `ToolExecutor._arun` 会把工具异常吞掉转成软 JSON 字符串** | 若在 `wrapper_tool` 外层或 `instance._arun` 返回后才判断异常，任务模式工具失败会被误记为 `result="success"` | `tool/domain/services/executor.py` 的 `_arun` 中，在 `LINSIGHT` `except` 转软 JSON 之前记录真实 `result="failed"`（以及 `TimeoutError`/`CancelledError`） |
| 3 | **任务模式 `ask_user` 恢复（`_resume_workflow`）目前会重新调用 `admit_round`** | 用户回答 `ask_user` 继续同一任务时，若中途积分刚好用完，会被二次拦截打断，违反「单次任务生命周期内不拦截」（AC-16） | `linsight/domain/task_exec.py`：仅 `_execute_workflow` / `_continue_workflow` 调 `admit_round`；`_resume_workflow` 直接置 `_round_admitted=True` |
| 4 | **`new_user_proof` 和 `new_month_proof` 会校验历史为空** | 若用户当月只调过收费工具未调过模型，初始化月份或新用户证明时漏查 `dsh_tool_call` 会误判历史为空导致覆盖账本 | `dsh/domain/repositories/usage.py:new_month_proof` 与 `dsh/domain/repositories/policy.py:new_user_proof` 同步检查 `DshToolCall` |
| 5 | **工作流 `useWebsocket.ts` 当前对 `error` 帧只弹 `showToast`，不写消息区** | 工作流启动或中途节点被 `26121` 拦截后，只闪一下 toast 消失，用户看不到「本月积分已用完」卡片，违反 AC-19 | `client/src/pages/appChat/useWebsocket.ts` & `ChatMessages.tsx` 针对 `26121` / `credit_exhausted` 在消息流末尾追加 `ChatErrorCard` 节点 |
| 6 | **`DshSettings` 启用了 `extra="forbid"`（strict 模式）** | 直接删除 `DshSettings.enabled` 而不做前置兼容剥离，会导致存量部署 YAML 中仍写着 `dsh.enabled` / `bs_client.enabled` 时服务启动直接报 `ValidationError` | `core/config/settings.py:normalize_client_settings` 兼容忽略旧 `enabled` 键并打 deprecation 告警 |
| 7 | **工作流在 Celery 进程同步执行，且任务模式开放 API 在异步 Worker 执行** | 仅靠 HTTP 请求线程的 `ContextVar` 无法把 `open_api_unbilled` 和 `source_type`/`source_id` 传进 Celery 或 Linsight Worker，会导致开放 API 调工作流/深度研究误扣分 | 通过 `OpenApiExecutionSnapshot`（Celery）与 `session_model.api_meta["channel"] == OPEN_API_CHANNEL`（Linsight）显式恢复上下文 |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 契约 | 形式 | 说明与消费方 |
|---|---|---|
| `GET /api/v1/dsh/admin/tool-pricing` | HTTP API | 查询当前租户（或指定管理视图 `tenant_id`）全部工具价格映射；`platform` 工具列表页消费 |
| `PUT /api/v1/dsh/admin/tool-pricing/{tool_id}` | HTTP API | 请求体 `{pricing_mode, currency?, price, call_count, version}`；超管/本租户管理员可写，乐观锁冲突返 `26130`；`platform` 设价弹框消费 |
| `GET /api/v1/dsh/browser-config` | HTTP API | 新增字段 `credit_billing_enabled: bool`；桌面端 `management_enabled` 改为常驻 `true`；`platform` 与 `client` 前端消费 |
| `/api/v2/model/v1/chat/completions`（429 响应） | OpenAI 兼容 HTTP 错误 | 托管应用计费主体额度用完返回 HTTP 429，`{"error": {"message": ..., "type": "rate_limit_error", "code": "credit_exhausted", "bisheng_code": 26121}}`；托管应用消费 |
| `chat_credits.billing_context(...)` & `ToolBillingService` | 内部 Python API | 供 `assistant`、`workflow`、`linsight`、`model_gateway`、`tool/executor.py` 注入来源、免计费标记与触发工具扣费 |

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 风险点 |
|---|---|---|
| F016 `dsh_credit_setting` & `pricing.py` | 内部 Repository / 换算精度 | 若积分单价/汇率微单位约定变化，工具换算公式须同步调整 |
| F051/F054 `model_range_policy.resolve_range_and_subject` | 内部 Python API | 若访问人令牌验签或 `preview_session_id` 字段名变更，托管应用扣费归属会失效 |
| `WorkStationService.acopy_root_builtin_tools_to_tenant` | 内部方法 | 若子公司复制内置工具逻辑重构，需确保价格复制钩子仍在同一事务内执行 |
| `GptsToolsDao.update_tool_type` / `delete_tool_type` | 内部 DAO | 若 API/MCP 工具增删改不再经此两方法，可能残留孤儿价格记录 |
| `client/src/components/ChatErrorCard.tsx` | 前端共享组件 | 依赖既有 `errorType="credit_exhausted"` 渲染与三语文案 |

---

## 7. 测试与可观测

- **分层测试策略**：
  - **后端单元测试（无外部中间件，PR 门禁）**：工具微单位换算与边界校验、乐观锁 `26130`、Lua 脚本（`check_tool_quota.lua` / `record_tool_usage.lua` / 4 处等式守卫）与 `AutomaticQuotaRecovery` 重建测试、`chat_credits` 场景矩阵（助手/工作流/任务模式/开放 API/托管应用/总开关关闭）、`ToolExecutor` 前置拦截与 Linsight 软错误状态捕获测试、配置兼容测试。
  - **前端组件测试（Vitest，无外部中间件）**：`ToolItem.tsx` 价格展示与权限隐藏、统一设价弹框校验与实时换算、`appChat` 助手/工作流/免登录三处 `26121` → `ChatErrorCard` 渲染、总开关关闭时 UI 隐藏测试。
  - **E2E 与双库回归**：按 `/e2e-test` 执行完整 API + 页面验证清单（覆盖 `AC-01` ~ `AC-32`）；DM8 迁移与真实中间件集成交由中央回归环境验证（C2）。
- **手动验证路径**：
  1. 管理后台「构建 → 工具与技能」给「天眼查 · 企业股东」设 `1 次 · 2 积分`、给「联网搜索」设 `1000 次 · ¥5`；切换普通用户验证无按钮且直接 `PUT` 被拒。
  2. 工作台将测试员工月度额度设为 `1` 积分：日常对话/助手调模型与收费工具触发扣分与 `26121` 卡片；工作流多节点运行中途耗尽即中止并落卡片；任务模式启动后消耗超额仍跑完不打断。
  3. 用开放 API 调深度研究/助手/工作流验证不扣分；用托管应用分别测试带有效 OBO 令牌、无令牌、审批预览、过期令牌（26504）及超额（HTTP 429 `credit_exhausted`）。
  4. 将配置 `credit_billing.enabled` 置 `false` 重启：验证桌面端正常登录调用模型、无 `26121`、前后端隐藏积分与工具价格入口。
- **关键可观测点**：
  - 工具设价变更写入 `dsh_unified_policy_audit`（`resource="tool_pricing:{tool_id}"`）；
  - `dsh_tool_call` 与 `dsh_model_call` 记录 `source_type`、`source_id`、`pricing_snapshot`、`result`；
  - 关键结构化日志：`tool_billing.quota_rejected`、`tool_billing.recorded`、`credit_billing.disabled_bypass`。

---

## 8. 后续改进 / 不打算做的事

- **用量统计报表页（按应用/工具/场景聚合）**：本期已有 `dsh_tool_call`、`dsh_model_call(source_type, source_id)` 和 `dsh_monthly_usage(usage_type)` 完整数据底座，后续可直接基于这些表出报表，本期不做界面。
- **工作流预估成本 / 运行前预算冻结**：当前采用节点级实时拦截，未来若需要「运行前预估所需积分」再另起特性。
- **租户级 UI 动态总开关**：当前为全局进程级配置开关，待多租户商业化需要子公司独立开关时再下沉。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-11-24 | 初版（依据 PRD v1.0 与 2026-11-24 技术评审定稿编写） | F001 Spec 确认后进入 Design 阶段 |
