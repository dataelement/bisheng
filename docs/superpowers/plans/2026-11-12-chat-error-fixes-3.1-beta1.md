# 3.1-beta1 会话报错修复适配计划与清单

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 在最新主版本上补齐近期已验证的通用会话报错修复，保持主版本自己的会话、项目、桌面及内容安全逻辑。

**Architecture:** 不合并中粮分支、不整笔 cherry-pick 定制提交。以主版本现有基础错误分类为底，逐块适配通用修复，保留服务端错误分类与前端临时连接状态的边界。

**Tech Stack:** FastAPI / Python 3.11 / LangChain / React / TypeScript / SSE / WebSocket。

**Spec:** 本次用户要求“整理最近会话报错修复，在主版本 3.1-beta1 处理，先拉最新代码并注意风险”；行为参考下列已落地提交及现有 F051 恢复协议，不新增业务流程。

## 基线与范围

- 2026-11-12 首次 fetch 基线 `6c4f2053a0`；提交前再次 fetch 后，已快进至最新 `origin/feat/3.1.0-beta1` **`f1d18b6248`**。
- 期间新增 `a79261ffc3`、`3fadee91b0` 两笔上游提交，与本次改动无文件重叠；快进无冲突，全部本地改动保留。
- 提交前新增 `c2e5f836ca`、`f1d18b6248`，同样无文件重叠，已快进同步并复核。
- 适配分支：`codex/chat-error-fixes-3.1-beta1`；中粮分支保持原样。
- 主版本已有 `918813fd2` 的安全错误分类、辅助信息与知识检索提示；不重复引入。

| 通用修复 | 来源 | 适配内容 |
|---|---|---|
| 故障时间与折叠详情 | `4345f5290` | 时间转为用户本地时区并注明偏移；详情默认折叠，主提示始终可见 |
| 运行中断网 | `b01dc795e` | 浏览器 offline 及时终止日常等待；任务显示临时网络提示，恢复连接后同步服务端状态 |
| 模型返回格式错误 | `b01dc795e` / `06ab8e96f` | HTTP 200 的无效响应/零 chunk 在模型调用边界内报错并保留模型分类 |
| 模型输出中途结束 | `06ab8e96f` | 保留部分答案，同时识别保守 EOF 特征；任务仍使用独立的两次重试预算 |
| 模型内容过滤 | `06ab8e96f` | 识别 `content_filter` 正常结束标记，转为已分类失败，保持原不重试策略 |
| 重试找不到原问题或答复 | `306402bbb` | 历史重建问题/回答关联，服务端 ID 替换后仍能更新同一答复 |
| 429 切换会话后提示消失 | `06ab8e96f` | 错误展示前持久化错误卡及已有排查元数据，限流状态卡不占用模型有效历史窗口 |
| 任务错误缺少重试入口 | `06ab8e96f` | 内嵌任务卡按既有可恢复错误白名单提供重试，保留只读限制 |

不迁移：知识空间删除/拖拽权限定制、文件变更审批锁提示、产品文案中粮化、文件夹命名修复、已撤回的“手动重试三次再换模型”未提交尝试。

## Global Constraints

- 仅通用会话报错范围；不更新任何测试环境，不修改数据库结构或依赖版本。
- 保留主版本 `projectDraft` / project intent、`flowLeaseId`、桌面运行状态、内容安全 `SensitiveStatus` 与 `referenceId`。
- 保留 SSE 关闭微任务处理，避免 HTTP/SSE 明确错误被抢先改成网络错误。
- 任务断网属于浏览器连接状态，不修改服务端任务为失败，不重新启动任务。
- 不改变限流后台探测、正常重试预算、模型选择和恢复协议；换模策略维持当前主版本。
- 保持 MySQL / DM8 通用 ORM、租户与权限约束；不使用数据库 JSON 方言来过滤错误卡。
- 所有新增前端文件保持小于 600 行；既有大文件只适配相关代码，不以旧分支整文件替换。
- 遵循用户既有约定，不运行本地前端测试、lint、typecheck 或构建；补回归交给镜像/CI验证，结果不得宣称通过。
- 后端验证使用既有 Python 环境及独立 SQLite 测试配置；不写入共享开发环境配置。

## Review Focus

1. typed SSE 错误与 close 顺序竞争：明确业务错误应优先于浏览器断线兜底。
2. 正常停止、最终答复、任务 handoff、切换会话：不得产生虚假的网络错误或取消后台任务。
3. HTTP 200 的坏响应、EOF、过滤信号与合法空文本/usage/tool 帧：分类正确且不改变原重试策略。
4. 429 出现后立即离开、多次连续 429：历史卡必须持久化，但不能挤掉真实上下文或改变恢复输入。
5. 主版本独有的项目、租约、桌面及内容安全变化：旧分支代码不能覆盖这些逻辑。

### Task 1: 模型响应校验

**Files:** `llm/domain/llm/llm.py`、新增 `response_validation.py`、`linsight/domain/services/resilience_middleware.py`、`test/llm/` 与 `test/linsight/` 相关回归。

**Interfaces:** 复用 `failure_boundary` 与 `FailureContextAdapter`；保留同步/异步生成及流式接口；共享 `IncompleteStreamError` 不改变分类器协议。

- [x] 读取主版本调用链与 Linsight 指令，对现有相关用例建立基线。
- [x] 增加真实 SDK + MockTransport 的坏响应、EOF、过滤信号和兼容帧回归并确认红灯。
- [x] 只适配模型边界校验及原独立两次 EOF 重试预算，不修改主版本其他模型能力。
- [x] 运行相关后端回归、Ruff 和架构检查，记录命令、结果与既有失败。

### Task 2: 会话历史与答复重试关联

**Files:** `database/models/message.py`、`workstation/domain/services/{chat_service,workstation_service}.py`、`client/src/api/chatApi.ts`、`client/src/hooks/useAiChat.ts` 及对应测试；主版本无 `useChatSend.ts`，不新建旧分支文件。

**Interfaces:** 消息 ID、原问题 ID 与现有恢复元数据保持原协议；消息 DAO 分页参数若新增须可选且不改变旧调用。

- [x] 对主版本历史、重试及限流持久化相关用例建立基线。
- [x] 增加保存前切走、部分答案、超过窗口的限流卡、原问题和服务端答复 ID 回归。
- [x] 局部适配持久化/有效历史回补与前端关联更新，保留主版本项目/租约/内容安全上下文。
- [x] 后端回归、Ruff、架构检查通过；前端补测试但不在本地执行。

### Task 3: 时间、断网与任务重试交互

**Files:** `FailureInfoDetails.tsx`、`useAiChatSSE.ts`、`hooks/Websocket/index.tsx`、`Linsight/Execution/{ExecutionFlow,TaskTurnPanel}.tsx` 及对应回归。

**Interfaces:** 临时 `networkFailure` 仅由连接 hook 返回；任务状态和既有 `onError/onEnd` 协议不变。

- [x] 读取当前 UI 规范；核对已有断网关闭竞争回归和翻译键。
- [x] 适配时间/折叠、offline 监听、连接重挂载与重连；保留主版本微任务兜底。
- [x] 内嵌任务卡沿用现有 transient 白名单，分享/显式只读卡保持无操作，普通历史任务沿用既有继续执行接口。
- [x] 补前端回归；做静态差异与架构检查，不宣称未执行的前端验证通过。

### Task 4: 风险收口与交付

- [x] 逐项复核来源/主版本差异，排除定制代码、撤回逻辑和无关文件。
- [x] 独立审查、修复发现的问题，确认没有数据库迁移和配置变更。
- [x] fetch 主版本并核对基线是否继续前进；必要时仅在最新主版本上重做局部适配。
- [x] 更新本文完成状态与实际验证结果，报告剩余验证边界；未经本轮指示不部署环境。

## 验证记录

- 最新基线上的最终后端组合回归：**386 passed, 1 skipped**；7 条既有依赖告警。包含模型 SDK 边界、同步/异步与流/非流接口、内容过滤、原生 Ollama、两次 EOF 预算、历史分页、错误先存后发、附件、内容安全输出和引用处理。
- 新增后端用例在实施前验证失败：模型边界 38 failed / 60 passed；历史持久化与分页 8 failed / 8 passed。适配后相关回归转绿。
- Ruff：其余 11 个修改/新增 Python 文件通过；`resilience_middleware.py` 的 F821 检查通过，其完整 Ruff 保留与基线相同的 34 条 RUF001（原中文提示标点），没有新增忽略规则。
- 对全部 29 个本次改动文件逐文件运行架构守卫：0 findings；`git diff --check` 通过。
- 前端已补时间/折叠、断网、重挂载、分享限制及重试消息关联回归，**未在本地执行测试、lint、typecheck 或构建，仍需 CI/镜像验证**。
- 独立静态审查已完成；修正了分享路由未显式传只读属性时可能出现的重试入口，并将故障元数据与脱敏详情合并为一个折叠入口。SSE 测试遵守主版本 `agent_answer/end → processing/close` 结束序列，没有扩大生产协议。

### 已识别的既有失败与验证边界

扩展验证中发现以下 **8 项基线已有失败**，均不计入上述通过集合；后续上游更新没有改动这些后端代码：

- `test_voicengine_provider.py`：websearch 凭据缺失，以及两项旧 Responses 载荷断言。
- `test_minimax_provider.py`：前端端点源码字符串断言，以及枚举引号形式断言。
- `test_daily_failure_feedback.py`：部分知识检索失败的 AST 测试夹具不完整。
- `test_workbench_content_safety_input.py`：两项测试缺少 `model_default_tenant_required` 的初始化。

未运行全部后端集成测试，也未请求真实模型服务或读写外部中间件。模型协议兼容性使用实际 SDK + MockTransport 覆盖；不能据此宣称所有供应商已完成线上验证。

### 主版本适配差异与风险控制

- 主版本没有中粮线的限流探测服务和 `status_version` 观察链路，不新增该定制服务；保留主版本已有的错误/排查字段及恢复行为。
- 主版本共用回答入库路径，因此对已分类错误统一采用“先保存回答及引用，再发送错误事件”，同时保存部分回答。失败后不额外调用模型生成标题；内容安全替换仍优先，租约释放逻辑保留。
- 模型校验位于通用调用层，影响的不仅是会话；因此同时回归主/子任务、工具调用、合法空文本、usage 帧、reasoning、额度及上下文异常。EOF 只识别既有保守特征，保持与普通异常分开的两次预算。
- 任务网络提示只属于浏览器连接；重连查询已有任务状态，不改后台任务状态、不重新提交任务。新增手动重试只开放既有三类 transient 错误，分享/只读禁用并防重复点击。
- 保留主版本项目上下文、flow lease、桌面活动、内容安全、排查 ID、积分不足和上下文溢出的专用提示；不以旧分支整文件覆盖。
- 没有数据库迁移、配置、依赖或部署文件变更；按用户后续授权提交、推送到独立适配分支，本轮不部署。后续发布需要包含前后端修复的镜像并由 CI 验证前端。

### 可重复的后端验证命令

在 `src/backend/` 下运行（使用既有 Python 环境和独立 SQLite 配置）：

```sh
env config=/private/tmp/cofco-folder-guard-unit.yaml PYTHONDONTWRITEBYTECODE=1 \
  /Users/shanghang/dataelem/ca-bisheng/src/backend/.venv/bin/python -m pytest \
  test/llm/test_provider_response_validation.py \
  test/llm/test_model_invalid_stream_failure.py \
  test/linsight/test_provider_response_resilience.py \
  test/llm/test_bisheng_llm_non_streaming_generate.py \
  test/llm/test_bisheng_llm_context_overflow.py \
  test/llm/test_openai_compatible_image_payload.py \
  test/llm/test_model_status_credit_rejection.py \
  test/linsight/test_resilience_middleware.py \
  test/linsight/test_llm_error_classifier.py \
  test/linsight/test_incomplete_stream_guard.py \
  test/linsight/test_truncated_turn_guard.py \
  test/linsight/test_truncation_guard.py \
  test/linsight/test_turn_budget.py \
  test/llm/test_reasoning_content_compat.py \
  test/llm/test_reasoning_passback.py \
  test/llm/test_openai_compatible_provider.py \
  test/llm/test_provider_chatmodels.py \
  test/llm/test_qwen_provider.py \
  test/llm/test_tencent_provider.py \
  test/llm/test_model_invoke_cancel.py \
  test/llm/test_bisheng_llm_summarization_trigger.py \
  test/workstation/test_stream_interrupt_persist.py \
  test/workstation/test_unified_daily_history.py \
  test/workstation/test_message_history_paging.py \
  test/workstation/test_daily_history_attachments.py \
  test/workstation/test_chat_rate_limit.py \
  test/workstation/test_workbench_content_safety_output.py \
  test/workstation/test_daily_chat_citation_handles.py \
  test/workstation/test_daily_chat_citation_backstop.py \
  --confcutdir=test -p no:cacheprovider -q
```

本机最终日志：`/private/tmp/chat-errors-31-final.log`。
