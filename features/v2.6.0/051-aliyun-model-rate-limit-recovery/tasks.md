# Tasks: 阿里百炼模型限流状态与主动恢复

**关联规格**: [spec.md](./spec.md)  
**关联设计**: [design.md](./design.md)  
**版本**: v2.6.0（cofco 分支）  
**任务基线**: 2026-09-02 任务模式换模增量确认版

---

## 状态

| 步骤 | 状态 | 备注 |
|---|---|---|
| spec.md | ✅ 已评审 | 任务模式换模增量口径于 2026-09-02 确认 |
| design.md | ✅ 已评审 | 既有 continue 可选 model_id、双 carrier 联动和失败回滚于 2026-09-02 确认 |
| tasks.md | ✅ 已同步 | 新增 T032–T035；重新打开 T028–T031 验证门 |
| 实现 | ✅ 增量已实施 | T032–T035 已完成；T028/T029 自动化验证通过，T030 真实环境 E2E 待执行 |

当前剩余项：

- T030：在提供完整 Redis/Celery/Linsight worker/fake provider case 的隔离环境执行 15 个外部 E2E；本地已成功收集，因未配置 harness 环境变量全部按设计跳过。
- T031：真实环境 E2E 完成后执行最终交付审查；当前 arch-guard、diff check 和增量代码审查已完成。

---

## 开发模式与全局约束

- 按 Wave 和依赖顺序实施；同一 Wave 内依赖满足的任务可并行。
- 后端遵循 test-first：先让配对测试证明旧实现不满足新契约，再修改实现；不得先把现有测试改成通过错误行为。
- 新后端测试位于 <code>src/backend/test/&lt;module&gt;/</code>；不得在 test 根目录新增文件。
- F051 是 observer，不是 interceptor。任何分类、Redis、Celery、日志或投影故障都不得改变原异常、原调用次数、原任务重试或原失败处理。
- 任务模式 429 必须经过既有 <code>classify_behavior → retry/degrade → _handle_task_failure → continueConversation</code> 链路，不得保留 provider-aware fail-fast guard；普通 Retry 不携带 model_id。
- 任务换模只扩展既有 continue 的可选 <code>model_id</code>：更新现有 session version.model 后投递原 <code>continue_question</code>，不得新增 recovery endpoint、queue 字段、checkpoint 分支、session version 或执行实体。
- 换模校验、入队或网络失败必须保留原失败轮次、原 status、原 model 和输入框选择；不得永久停留 IN_PROGRESS。
- 模型健康状态继续由既有调用装饰器维护；Redis 只保存限流展示状态，两者不得互相推导。
- probe task body 只含 <code>model_id/probe_token/probe_attempt</code>；<code>tenant_id</code> 只走可信 Celery header，version 只保存在 Redis。
- 后台 probe 不得接收、查询、枚举或调度 execution/session/chat/prompt，不得恢复用户会话。
- 不新增 <code>model_call_execution</code>、恢复状态表或前后端手动重试计数；页面刷新后允许限流卡消失。
- 日常、知识、频道的限流失败保留原用户消息，不写失败回答；成功恢复只写一条正常回答。
- Client 只使用 react-query v4 和页面局部状态，不新增 Recoil atom、Context 或第三方状态库。
- 新文案与错误码同时更新 zh-Hans/en/ja 源文件并通过生成流程；不得手改生成产物。
- 每项完成后运行对应 focused test，并执行 <code>/task-review features/v2.6.0/051-aliyun-model-rate-limit-recovery Txxx</code> 后再勾选。
- 若实现必须推翻已确认的 spec/design，立即停止并重新确认，不得只在本文件记录偏差后继续。

---

## Wave 0：现有改动重新定基线

- [x] **T001：当前实现与最终设计差异清单**
  **文件**: 本 Feature 涉及的全部 staged、unstaged、untracked 文件
  **逻辑**: 以 design §2–§4 为唯一判据，列出需保留、需修改、需删除的现有实现；重点定位 provider-aware task guard、<code>status_version</code> probe body、缺失 <code>probe_token</code>、恢复拒绝 SSE 和前端终态映射。
  **验证**: 差异清单必须逐项映射到 T002–T035，不允许以旧 tasks 的完成状态替代证据。
  **覆盖 AC**: AC-08, AC-21, AC-27, AC-34, AC-55, AC-56
  **依赖**: 无

- [x] **T002：持久化与历史聚合零新增审计**
  **文件**: <code>src/backend/bisheng/llm/</code>、四入口会话模型和删除链路
  **逻辑**: 确认没有 execution ORM/DAO/DDL、会话限流聚合器、会话扫描或删除联动；原请求只来自既有 ChatMessage 或 Linsight session version。
  **验证**: 全仓搜索不存在 F051 execution 实体、受限会话集合和 probe 到业务恢复器的依赖。
  **覆盖 AC**: AC-27, AC-30, AC-45, AC-51, AC-56
  **依赖**: T001

---

## Wave 1：分类、Observer 与 Redis 状态

- [x] **T003：阿里临时限流分类回归测试**
  **文件**: <code>src/backend/test/llm/test_aliyun_rate_limit_classifier.py</code>
  **断言**: 覆盖阿里临时子码白名单、欠费/未购买/鉴权/内容安全优先排除、非阿里 429 不进入 F051、包装异常展开和终端信息脱敏。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-06, AC-07
  **依赖**: T002

- [x] **T004：阿里分类器实现收敛**
  **文件**: <code>src/backend/bisheng/llm/domain/services/aliyun_rate_limit_classifier.py</code>
  **逻辑**: 分类只返回稳定的限流观察结果，不抛出新的业务控制异常，不决定 retry/fail-fast；永久错误优先排除。
  **测试**: T003 全部通过。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-06, AC-07
  **依赖**: T003

- [x] **T005：Observer fail-open 与健康状态回归测试**
  **文件**: <code>src/backend/test/llm/test_model_rate_limit_observation.py</code>、现有模型健康测试
  **断言**: Redis/分类/Celery/日志任一失败都重新传播同一个原异常；429 仍按旧逻辑写健康 ERROR，成功仍写 NORMAL；成功只 CAS 清除调用开始前观察到的 version。
  **覆盖 AC**: AC-08, AC-09, AC-10, AC-11, AC-17, AC-27, AC-36, AC-56
  **依赖**: T004

- [x] **T006：ModelRateLimit observer 实现**
  **文件**: <code>src/backend/bisheng/llm/domain/services/model_rate_limit.py</code>、<code>src/backend/bisheng/llm/domain/services/call_logger.py</code>
  **逻辑**: 实现 best-effort failure/success observer；只维护 Redis 投影、安排 probe 和记录脱敏诊断，不直接写模型健康状态，不替换原异常。
  **测试**: T005 全部通过。
  **覆盖 AC**: AC-07, AC-08, AC-09, AC-10, AC-11, AC-17, AC-36, AC-52, AC-56
  **依赖**: T005

- [x] **T007：Redis version/probe_token 状态机测试**
  **文件**: <code>src/backend/test/llm/test_model_rate_limit_state.py</code>
  **断言**: tenant/model 隔离、300 秒 TTL、真实 429 刷新 version、scheduled 槽保留 probe_token、running 收到新 429 建立后继槽、claim 同时校验 token/attempt、旧结果 CAS 失败、key 删除重建后旧任务空操作、Celery 重复投递不重复 claim。
  **覆盖 AC**: AC-04, AC-05, AC-12, AC-13, AC-17, AC-18, AC-19, AC-32, AC-34, AC-35, AC-36
  **依赖**: T006

- [x] **T008：Redis ModelRateLimitStateService 实现**
  **文件**: <code>src/backend/bisheng/llm/domain/services/model_rate_limit_state.py</code>
  **逻辑**: 按 design §4.3 实现原子 <code>mark_busy/begin_probe/finish_probe/clear_if_version/list_states</code>；version 保护结果，probe_token 保护排队槽位与 key ABA。
  **测试**: T007 全部通过。
  **覆盖 AC**: AC-04, AC-05, AC-12, AC-13, AC-17, AC-18, AC-34, AC-35, AC-36
  **依赖**: T007

---

## Wave 2：有界模型探测

- [x] **T009：Celery probe 契约与竞态测试**
  **文件**: <code>src/backend/test/llm/test_model_rate_limit_probe.py</code>
  **断言**: 15/30/60 秒最多三次；task body 只有 model_id/probe_token/probe_attempt；tenant 只从 header 恢复；成功、同类限流、非限流错误、模型删除/停用、Redis 过期、旧 token、重复投递和 enqueue 失败均按 design §3 决策 5 收敛。
  **覆盖 AC**: AC-28, AC-29, AC-30, AC-31, AC-32, AC-33, AC-34, AC-35, AC-36
  **依赖**: T008

- [x] **T010：Celery probe Worker 与注册实现**
  **文件**: <code>src/backend/bisheng/worker/model_rate_limit.py</code>、<code>src/backend/bisheng/worker/main.py</code>
  **逻辑**: 使用固定最小无上下文模型调用；claim 后取 Redis 当前 version；probe 自然经过既有健康装饰器；只更新健康状态与 Redis 投影，不依赖任何用户会话 repository。
  **测试**: T009 全部通过。
  **覆盖 AC**: AC-10, AC-28, AC-29, AC-30, AC-31, AC-32, AC-33, AC-34, AC-35, AC-36
  **依赖**: T009

---

## Wave 3：任务模式完全沿用旧链路

- [x] **T011：任务 429 中间件等价性测试**
  **文件**: <code>src/backend/test/linsight/test_resilience_middleware.py</code>、<code>src/backend/test/linsight/test_rate_limit_recovery.py</code>
  **断言**: 同一 retry 配置下，阿里临时 429 与既有同类 retryable 异常拥有相同调用次数、sleep/backoff、degrade_or_raise 和最终异常；确认 observer 被调用但 observer 失败不改变结果；删除或禁用 provider guard 后测试仍成立。
  **覆盖 AC**: AC-20, AC-21, AC-26, AC-27, AC-56
  **依赖**: T006

- [x] **T012：移除任务 provider-aware 旁路并接入旁观者**
  **文件**: <code>src/backend/bisheng/linsight/domain/services/resilience_middleware.py</code>、模型 handler 接入点
  **逻辑**: 删除在 <code>classify_behavior</code> 前直接抛出阿里 429 的 guard；在不阻断原控制流的位置 best-effort 调用 observer，原异常继续进入既有分类。
  **测试**: T011 全部通过。
  **覆盖 AC**: AC-20, AC-21, AC-26, AC-27, AC-52, AC-56
  **依赖**: T011

- [x] **T013：任务最终失败与用户 Retry 回归测试**
  **文件**: <code>src/backend/test/linsight/test_rate_limit_recovery.py</code>、<code>src/backend/test/linsight/test_hitl_worker.py</code>
  **断言**: 自动重试用尽后仍写既有 status/output_result/失败轮次/错误事件并收敛未完成任务；只允许附加标准限流展示字段；用户 Retry 仍以原 sessionVersionId/question 进入 continueConversation/continue_question。
  **覆盖 AC**: AC-22, AC-23, AC-26
  **依赖**: T012

- [x] **T014：任务错误事件最小增强**
  **文件**: <code>src/backend/bisheng/linsight/domain/task_exec.py</code>、<code>src/backend/bisheng/linsight/api/endpoints/linsight.py</code>、<code>src/backend/bisheng/linsight/worker.py</code>
  **逻辑**: 保持既有失败处理和队列协议，只在最终错误事件已确定为临时限流时附加 error_type/rate_limit_state/model_id；不新增 recovery endpoint、command、attempt、checkpoint 或队列字段。
  **测试**: T013 全部通过。
  **覆盖 AC**: AC-22, AC-23, AC-26, AC-55
  **依赖**: T013

---

## Wave 4：非任务入口主动恢复

- [x] **T015：统一 SSE 与恢复公共契约测试**
  **文件**: <code>src/backend/test/llm/test_model_recovery_service.py</code>、四入口 SSE 测试
  **断言**: 真实限流使用 12046/rate_limit；原消息失效、权限失败、模型 busy、短锁冲突统一使用 12048/recovery_rejected；两者都使用统一 SSE envelope，12048 不创建 busy 状态且不伪装为 429。
  **覆盖 AC**: AC-41, AC-42, AC-43, AC-55
  **依赖**: T008

- [x] **T016：恢复公共协议与短锁实现**
  **文件**: <code>src/backend/bisheng/llm/domain/services/model_recovery_service.py</code>、<code>src/backend/bisheng/common/errcode/workstation.py</code>
  **逻辑**: 原消息 ID 只作为传输关联和业务 subject；入口重新鉴权并复核目标模型；使用 5 秒 fail-open 短锁；不持久化 attempt/次数；构造统一 12048 SSE 终态。
  **测试**: T015 全部通过。
  **覆盖 AC**: AC-39, AC-40, AC-41, AC-42, AC-43, AC-45, AC-51, AC-55
  **依赖**: T015

- [x] **T017：日常 Agent 原位置重新调用测试**
  **文件**: <code>src/backend/test/workstation/test_daily_model_rate_limit_recovery.py</code>、<code>src/backend/test/workstation/test_stream_interrupt_persist.py</code>
  **断言**: 首次请求先保存用户消息；限流不写 bot 失败回答；Retry 从原 ChatMessage 读取参数并启动新的日常 Agent 调用，不创建或读取 checkpoint、不重复用户消息；成功只写一条回答。
  **覆盖 AC**: AC-37, AC-38, AC-39, AC-42, AC-43, AC-49, AC-50, AC-51, AC-55
  **依赖**: T016

- [x] **T018：日常 Agent RecoveryPort 与 Endpoint 实现**
  **文件**: <code>src/backend/bisheng/workstation/domain/services/chat_service.py</code>、<code>src/backend/bisheng/workstation/api/endpoints/chat.py</code>
  **逻辑**: 从原 ChatMessage 读取请求，重新验证 owner/tenant/model；重新启动一轮日常调用且不依赖 checkpoint；使用统一 SSE 返回限流、拒绝和成功结果。
  **测试**: T017 全部通过。
  **覆盖 AC**: AC-37, AC-38, AC-39, AC-41, AC-42, AC-43, AC-49, AC-50, AC-51, AC-55
  **依赖**: T017

- [x] **T019：知识与频道只读恢复测试**
  **文件**: <code>src/backend/test/knowledge/test_knowledge_chat_rate_limit_recovery.py</code>、<code>src/backend/test/channel/test_channel_chat_rate_limit_recovery.py</code>
  **断言**: 从原用户 ChatMessage 读取问题并重新执行既有只读链路；确认时重做原权限和模型规则，仅额外拒绝 busy 目标；不新增用户消息或失败回答；成功各写一条正常回答。
  **覆盖 AC**: AC-37, AC-38, AC-39, AC-40, AC-41, AC-42, AC-43, AC-49, AC-50, AC-51, AC-54, AC-55
  **依赖**: T016

- [x] **T020：知识与频道 RecoveryPort/Endpoint 实现**
  **文件**: 知识空间和频道现有 chat service、endpoint
  **逻辑**: 复用原入口业务记录、鉴权、候选集合和只读调用链；不扩大或收窄历史模型集合，不把限流状态写入 ChatMessage 历史。
  **测试**: T019 全部通过。
  **覆盖 AC**: AC-37, AC-38, AC-39, AC-40, AC-41, AC-42, AC-43, AC-49, AC-50, AC-51, AC-54, AC-55
  **依赖**: T019

---

## Wave 5：模型列表投影与 Client 交互

- [x] **T021：工作台配置投影测试**
  **文件**: <code>src/backend/test/workstation/test_model_rate_limit_config.py</code>
  **断言**: workstation config 按 tenant/model 批量叠加 rateLimitState/busyUntil/statusVersion；Redis 故障为无装饰；busy 不改变原模型顺序、默认项、在线状态、权限、能力或可选集合。
  **覆盖 AC**: AC-14, AC-15, AC-16, AC-18, AC-19, AC-53, AC-54
  **依赖**: T008

- [x] **T022：工作台配置模型状态投影实现**
  **文件**: <code>src/backend/bisheng/workstation/api/endpoints/config.py</code>、<code>src/backend/bisheng/workstation/domain/schemas/workstation_schema.py</code>
  **逻辑**: 对原模型列表只做 typed Redis 状态装饰；key 不存在即 normal；不得把离线、停用、无权限模型投影为可用。
  **测试**: T021 全部通过。
  **覆盖 AC**: AC-14, AC-15, AC-16, AC-18, AC-19, AC-53, AC-54
  **依赖**: T021

- [x] **T023：Client 模型状态和条件轮询测试**
  **文件**: Client config query、模型选择器相关测试
  **断言**: SSE/WS 限流先更新 Query Cache 并 invalidate；存在 recovering/busy 时每 5 秒 refetch，全部 normal 后停止；普通选择器显示灰态与繁忙后缀但仍可选择；任务/日常/知识/频道展示一致。
  **覆盖 AC**: AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-52, AC-53, AC-54
  **依赖**: T022

- [x] **T024：Client 模型状态投影和选择器实现**
  **文件**: Client config types/query、共享 model option renderer、四入口模型选择器
  **逻辑**: 使用 react-query v4 条件轮询和共享 renderer；常驻换模列表排除当前及 busy 模型，普通选择器不禁用 busy；不新增全局状态。
  **测试**: T023 全部通过。
  **覆盖 AC**: AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-40, AC-52, AC-53, AC-54
  **依赖**: T023

- [x] **T025：Client 限流卡与恢复交互测试**
  **文件**: <code>src/frontend/client/src/hooks/useModelRateLimitRecovery.test.tsx</code>、限流卡及三入口集成测试
  **断言**: Retry 从原消息执行且不新增用户消息；换模入口常驻且无手动次数/自动弹窗；选择模型同步输入框；普通模型错误只展示原错误卡，只有 recovery_rejected 表示恢复拒绝；新消息关闭旧操作；迟到 attempt 不覆盖当前 attempt。
  **覆盖 AC**: AC-38, AC-39, AC-40, AC-41, AC-43, AC-44, AC-45, AC-46, AC-47, AC-48, AC-49, AC-51
  **依赖**: T020, T024

- [x] **T026：Client 主动恢复交互实现**
  **文件**: 共享 recovery hook、限流提示组件及日常/知识/频道接入点
  **逻辑**: execution_id/subject_id/attempt_id 仅保存在当前页面；pending 时禁重复点击；常驻换模入口与输入框模型联动；发送新消息使旧操作失效；页面刷新允许丢失 UI。任务模式在本任务完成时只接入中性繁忙信息和旧 Retry；2026-09-02 新增换模由 T034/T035 独立实施。
  **测试**: T025 全部通过。
  **覆盖 AC**: AC-38, AC-39, AC-40, AC-41, AC-43, AC-44, AC-45, AC-46, AC-47, AC-48, AC-49, AC-51
  **依赖**: T025

- [x] **T027：12046/12048 i18n 与前端终态映射**
  **文件**: <code>src/frontend/packages/locales/src/api_errors/{zh-Hans,en,ja}.json</code>、Client SSE/WS 错误映射
  **逻辑**: 三语言保持 key parity；12046 显示限流卡，12048 显示本地化终态文案并移除 Retry，不得落入 unknown 或优先展示 provider detail；按仓库流程重新生成产物。
  **测试**: i18n parity、错误映射测试和 T025 全部通过。
  **覆盖 AC**: AC-06, AC-41, AC-42, AC-55
  **依赖**: T026

---

## Wave 6：任务模式换模增量

- [x] **T032：任务 continue 可选模型契约测试**
  **文件**: <code>src/backend/test/linsight/test_rate_limit_recovery.py</code>、continue endpoint/workbench service 相关测试
  **断言**:
  1. 不传 <code>model_id</code> 时，普通 Retry/后续提问的归属、终态校验、status 更新、queue payload 和 worker 行为与 F035 基线一致。
  2. 传合法 <code>model_id</code> 时，复用现有租户模型解析、权限、在线状态和任务能力规则，更新同一 session version.model；queue payload 仍只有 <code>session_version_id + continue_question</code>。
  3. 不存在、无权限、离线或能力不符的目标在更新和 enqueue 前被现有规则拒绝；不创建新 session version、外层 ChatMessage、checkpoint command 或 queue 字段。
  4. enqueue 失败时，原状态分别为 FAILED/COMPLETED 的用例都恢复 <code>original_status + original_model</code>，不会停在 IN_PROGRESS。
  5. 目标模型执行后再次 429/失败时，仍进入原自动 retry、失败落档和错误事件。
  **覆盖 AC**: AC-20–AC-27, AC-54, AC-55, AC-56
  **依赖**: T014
  **完成证据（2026-09-02）**: <code>test/linsight/test_rate_limit_recovery.py</code> 11 项通过，覆盖无 model_id、合法换模、目标拒绝、FAILED/COMPLETED 回滚与 endpoint 转发。

- [x] **T033：既有 Linsight continue 增量实现**
  **文件**: <code>src/backend/bisheng/linsight/api/endpoints/linsight.py</code>、<code>src/backend/bisheng/linsight/domain/services/workbench_impl.py</code>、既有 session version DAO 调用点
  **逻辑**:
  1. endpoint 只增加可选 <code>model_id</code> 并委托既有 workbench service；不得新增 recovery endpoint 或 DAO 入口。
  2. service 完成 owner/terminal 校验，目标模型存在时复用既有任务模型解析规则；记录 original_status/original_model，并用现有批量更新一次写入 IN_PROGRESS + target model。
  3. 继续调用原 <code>encode_queue_item(session_version_id, continue_question=question)</code>；worker、队列格式和 LangGraph thread/checkpoint 逻辑零修改。
  4. enqueue 异常时恢复 original_status/original_model，返回现有统一错误并记录不含问题正文的结构化日志。
  **测试**: T032 全部通过；arch-guard 无新增违规。
  **覆盖 AC**: AC-23, AC-24, AC-26, AC-27, AC-54, AC-55, AC-56
  **依赖**: T032
  **完成证据（2026-09-02）**: endpoint 仅增加可选 <code>model_id</code> 并委托 workbench service；worker、<code>encode_queue_item</code> 参数和 checkpoint 未改动；arch-guard 通过。

- [x] **T034：任务双 carrier 换模交互测试**
  **文件**: <code>src/frontend/client/src/components/Linsight/Execution/TaskTurnPanel.model-rate-limit.test.tsx</code>、<code>ExecutionFlow</code>/<code>useLinsightManager</code>/<code>api/linsight</code> 相关测试
  **断言**:
  1. 独立 <code>ExecutionFlow</code> 与内嵌 <code>TaskTurnPanel</code> 的可操作限流失败都显示 Retry 和常驻换模；分享/历史只读页、非限流错误不显示换模。
  2. 候选复用现有任务模型列表，排除当前、重复和 recovering/busy；不新增模型集合或能力判断。
  3. 普通 Retry 调用 continue 时不传 model_id；选择目标后同一 API 携带 model_id，pending 禁止双击且不维护次数/自动弹窗。
  4. accepted 后把输入框选择同步为 <code>manual=true, mode=task</code>；统一页更新共享 chatModel，独立页同步 TaskModeInput。
  5. 拒绝、网络错误或 enqueue 失败完整恢复原失败轮次，输入框模型不变；迟到结果不覆盖当前轮次。
  **覆盖 AC**: AC-24, AC-25, AC-27, AC-45, AC-54, AC-55, AC-56
  **依赖**: T024, T025, T033
  **完成证据（2026-09-02）**: Client 5 个专项测试文件共 13 项通过，覆盖双 carrier、只读、候选过滤、API payload、失败轮次恢复和 mode=task 输入模型同步。

- [x] **T035：任务双 carrier 换模实现**
  **文件**: <code>src/frontend/client/src/api/linsight.ts</code>、<code>src/frontend/client/src/hooks/useLinsightManager.tsx</code>、<code>src/frontend/client/src/components/Linsight/Execution/{ExecutionFlow,TaskTurnPanel}.tsx</code>、<code>src/frontend/client/src/components/Linsight/Input/TaskModeInput.tsx</code> 及共享候选 helper
  **逻辑**:
  1. 给 <code>continueLinsight/continueConversation</code> 增加可选目标模型；无目标参数的现有调用和 UI 时序不变。
  2. 两个 carrier 复用 <code>ChatErrorCard → ServiceBusyNotice</code> 及既有候选过滤，不新增弹窗、恢复 hook 或全局状态。
  3. 换模分支保存完整本地轮次快照；失败恢复，accepted 后再提交输入框模型与任务模式手动记忆。
  4. 独立页用最小受控 props 同步 <code>TaskModeInput</code>，不借机重构任务输入框；内嵌页复用现有 chatModel atom。
  **测试**: T034 全部通过；普通 Retry、普通 follow-up、只读展示和非限流错误回归通过。
  **覆盖 AC**: AC-23–AC-27, AC-45, AC-54, AC-55, AC-56
  **依赖**: T034
  **完成证据（2026-09-02）**: 两个 carrier 复用 <code>ChatErrorCard → ServiceBusyNotice</code>；换模 accepted 后分别同步共享 chatModel/独立 TaskModeInput，拒绝时保留原失败轮次和输入模型。

---

## Wave 7：验证、E2E 与交付

- [x] **T028：后端 focused 回归**
  **验证**: 运行 F051 的 llm/workstation/knowledge/channel/linsight 测试；同时运行既有 Linsight resilience、任务失败处理、模型健康状态测试。单独记录依赖外部中间件而未运行的测试。
  **完成条件**: 不存在 task 429 旁路测试；probe_token/ABA、observer fail-open、12048 SSE、continue model_id 与 original status/model 回滚均有通过证据。
  **覆盖 AC**: AC-01–AC-43, AC-49–AC-56
  **依赖**: T010, T018, T020, T022, T033
  **历史证据**: 2026-09-02 变更前的 focused 回归曾通过；新增 T032/T033 后必须重跑，旧证据不作为本项完成依据。
  **本次证据（2026-09-02）**: llm/workstation/knowledge/channel/linsight 共 152 项通过；其中 continue 增量专项 11 项通过。

- [x] **T029：前端质量门**
  **验证**: 从 <code>src/frontend/</code> 运行 <code>pnpm lint</code>、<code>pnpm typecheck</code>、相关 Client 单测和 <code>pnpm check-i18n</code>；若存在基线问题，分别记录，不得宣称通过。
  **完成条件**: 无新硬编码中文、无新 any、无手改生成 locale、无新增全局状态或 UI 库。
  **覆盖 AC**: AC-14–AC-19, AC-38–AC-55
  **依赖**: T027, T035
  **历史证据**: 变更前 <code>pnpm lint</code>、33 个专项测试、<code>pnpm check-i18n</code> 通过；<code>pnpm typecheck</code> 存在 <code>AgentToolSelector.tsx</code> 与 <code>ChatFormTools.tsx</code> 两个非本期基线错误。新增 T034/T035 后必须重新记录增量结果。
  **本次证据（2026-09-02）**: Client 完整 lint、<code>pnpm check-i18n</code> 和 13 项新增专项测试通过；typecheck 仍失败于 7 个缺失 Radix 依赖及 <code>AgentToolSelector.tsx</code>、<code>ChatFormTools.tsx</code>、<code>settingsSections.ts</code> 三个非本期文件，本次变更文件无报错。

- [ ] **T030：四入口 E2E 与手工验证**
  **文件**: <code>src/backend/test/e2e/test_e2e_aliyun_model_rate_limit_state.py</code>、<code>src/backend/test/e2e/test_e2e_model_call_recovery.py</code>、<code>e2e-checklist.md</code>
  **场景**: 日常/知识/频道限流、Retry、常驻换模与输入模型联动、新消息关闭旧操作、后台 probe/TTL 后页面恢复；任务 429 自动重试成功、重试用尽失败、普通 Retry、双 carrier 换模成功、目标失效、enqueue 回滚和输入框联动；永久错误和非阿里 429 回归。
  **验证**: 使用 <code>/e2e-test features/v2.6.0/051-aliyun-model-rate-limit-recovery</code>，并记录无法在本地验证的真实 Celery/Redis/供应商场景。
  **覆盖 AC**: AC-01–AC-56
  **依赖**: T028, T029
  **历史证据**: 变更前两个外部 harness E2E 文件可成功收集；本地因未提供 <code>E2E_F051_STATE_CASES_JSON</code>/<code>E2E_F051_RECOVERY_CASES_JSON</code> 共跳过 14 项。任务换模场景尚未执行，真实环境步骤见 <code>e2e-checklist.md</code>。
  **本次证据（2026-09-02）**: 新增 <code>task_continue_switch</code> 外部用例后两个 harness 共 15 项成功收集；本地未配置外部环境变量，15 项全部按设计跳过，未标记为 E2E 通过。

- [ ] **T031：最终架构与代码审查**
  **验证**: 运行 <code>scripts/arch-guard.sh</code>、<code>/code-review --base &lt;目标基线&gt;</code>，逐项复核 design §7.6 完成门槛；确认 spec/design/tasks/release-contract 和实际代码一致。
  **完成条件**: 无未解释 P0/P1；所有完成任务有验证证据；偏差已回写 design 并按需重新确认。
  **覆盖 AC**: AC-01–AC-56
  **依赖**: T030
  **历史证据**: 变更前 <code>scripts/arch-guard.sh</code> 已通过；新增 T032–T035 后必须重新执行，最终状态等待 T028–T030。
  **当前证据（2026-09-02）**: <code>scripts/arch-guard.sh</code>、<code>git diff --check</code> 通过；最终状态仍等待 T030 真实环境验证。

---

## AC 覆盖检查

| 范围 | 主要任务 |
|---|---|
| AC-01–AC-11 分类、原链路与健康状态 | T003–T006 |
| AC-12–AC-19 Redis 状态与页面投影 | T007–T008, T021–T024 |
| AC-20–AC-27 任务模式原链路与换模 | T011–T014, T032–T035 |
| AC-28–AC-36 后台 probe | T007–T010 |
| AC-37–AC-51 非任务当前页面恢复 | T015–T020, T025–T027 |
| AC-52–AC-56 一致性与降级 | T006, T014, T020, T024, T027–T035 |

---

## 实际偏差记录

> 只记录已确认设计与实施之间的实际偏差指针；不能用本节推翻 spec/design。

- 2026-09-01：T017/T018 从“日常 checkpoint 续跑”调整为“基于原 ChatMessage 重新调用”，已同步更新 spec AC-39/AC-50 与 design 决策 7；用户已明确确认日常模式不采用任务 checkpoint。
- 2026-09-02：产品新增任务模式换模能力，但明确不引入任务 recovery 状态机。新增 T032–T035，复用既有 continue/session model/queue 协议；旧 T028–T031 验证状态重新打开。

---

## 修订历史

| 日期 | 内容 | 原因 |
|---|---|---|
| 2026-09-02 | 新增任务模式换模增量 T032–T035，并重新打开 T028–T031 验证门 | Design 已确认：continue 增加可选 model_id，双 carrier 联动，queue/worker/checkpoint 不变，失败恢复原 status/model |
| 2026-09-01 | 日常模式 Retry 移除 checkpoint，改为重新执行原问题 | 日常模式不属于任务断点续跑；现场 checkpoint 子图错误导致 recover 返回 200 SSE 后立即失败 |
| 2026-08-28 | 完整重写 tasks，所有实现状态重置为待重新核验 | spec/design 最终确认后发现旧任务清单仍要求任务 429 旁路并使用旧 probe 参数，不能继续作为执行依据 |
