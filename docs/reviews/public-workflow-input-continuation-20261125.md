# 免登录工作流输入续跑修复与审查

日期：2026-11-25。目标分支：`feat/3.1.0-beta2`。基线：`a46daca7d7c1d7f713ab362bf9fccb7b603b08c6`。范围为兼容性热修复，无新接口、数据库变更或依赖。

## 根因与改动

此前现场排查确认：公开入口完成初始化后，Worker 以 `source=api` 保存 public_v3 会话，WS 的 `RedisCallback` 却默认使用 platform。提交输入时进入自然人 `ConversationPersistence.scope`，被正确地以 403 拒绝，尚未调用模型。外层包装仅记录异常，没有错误帧，页面持续等待。保存执行图的修复解决初始化，未覆盖此续跑路径。

自然人持久化守卫由 `eb90c77d213f57f2164145a06daa4b175e370b93`（2026-11-16 13:35:28 +0800）引入；来源不一致早已存在，该守卫使其表现为 403。修复不撤掉此守卫。

- `WorkflowClient` 统一初始化与重连的回调构造，按端点注入的执行快照选择来源，与 Worker 保持一致。浏览器无法选择存储来源或覆盖快照。
- input/stop 的 `SessionSubject` 校验原样保留；验证输入时，API 来源也校验消息所属会话、资源和用户。pending 消息、节点和字段的原检查保留。
- 工作流请求的业务异常保留错误码；HTTP 403/404 反馈既有错误；未知异常记堆栈并反馈 10541，避免泄露内部信息。错误后发送 `processing/close`，结束页面等待。根资源换绑及并发额度拒绝也走同一反馈出口。错误不清理 pending 或续跑状态。
- 不修改通用 BaseClient 或其他应用的错误处理，不移除任何会话归属规则，不修改公开展示图脱敏策略。设计快照同步至 F006 design §4.11。

## 回归证据

新增 `test/workflow/test_public_workflow_continuation.py` 21 项：

| 覆盖 | 证据 |
| --- | --- |
| 完整对话与重连 | 实际 v3 WS ASGI 路由 → ChatManager → WorkflowClient → 服务端 SQLite 保存图 → Worker 内部执行/续跑 → 实际 Start/Input/LLM/Output/End 节点 → WS 模型内容 → SQLite 问答落库；首次和重连两种情形 |
| 多轮对话 | 输出后循环回输入；旧提示重放拒绝，正确第二轮正常输出，模型仅执行两次 |
| 会话和消息归属 | 自然人会话、资源/租户错配、删除会话、连接换绑、消息不存在/其他用户/其他资源/其他会话均拒绝；不写消息、不投递续跑、不调模型 |
| 输入校验 | pending 丢失、额外字段及旧消息重放拒绝 |
| 错误反馈 | HTTP 403、业务 10543、内部异常 10541 返回错误及结束等待帧；内部异常标记不进入响应 |
| 保留原守卫 | 将回调人为改回 platform，实际 `ConversationPersistence.scope` 仍拒绝 public_v3 会话，且不续跑 |
| 其他拒绝反馈 | 初始化的 HTTP 403 保留错误码；输入时的并发额度拒绝返回 12045 并结束等待，不消耗本轮输入 |

外部边界使用内存 Redis、同步的 Celery 投递适配和合成模型响应；权限投影/发布发现使用普通非管理员身份的允许结果。会话主体查询、消息写入、图引擎和节点执行为真实代码。没有真实 Celery broker、跨进程快照恢复、真实模型服务或部署后浏览器验收证据。

将新测试复制到未改动基线，首轮完整对话在 `platform != api` 断言失败；三个异常反馈测试均因未收到帧超时（4 项失败）。证明回归能捕捉原缺陷。

扩展后端选集：`test_wf_public_saved_execution`、`test_wf_entry`、`test_wf_client_admission`、`test_workflow_auto_rerun_status`、`test_workflow_offline_input`、`test_execution_boundary`、`test_security_merge_regressions`、`test_moderation_continuation`，加上新增 21 项后为 **143 passed / 4 failed**。相同既有选集在干净基线为 **122 passed / 4 failed**，失败集合一致：

1. `test_refreshed_browser_reads_owned_home_history_under_managed_target`：原断言期望两条历史，实际零条。
2. `test_workflow_input_update_uses_original_conversation_tenant`：旧手造回调未配置 workflow_pending_key。
3. `test_workflow_title_reads_storage_owner_but_uses_execution_models`：旧配置桩不接受 slots 参数。
4. `test_workflow_async_input_update_restores_execution_before_enqueue`：旧手造回调未配置 workflow_pending_key。

上述旧失败未在本次范围内修订或豁免校验。自然人守卫的正反向证据另有新测试覆盖。

页面回归 `workflowUnavailable.test.tsx`、`workflowAutoRerun.test.ts` 共 **20 passed**，新增 4 项验证 403/404/10543/10541 的现有本地化提示、等待结束和不自动重跑。Jest 仅在当前进程将未编译的可选 canvas 标为不可用，没有改依赖或锁文件。生产前端未改动。

Ruff、`git diff --check`、前端全工作区 `pnpm lint` 和 `pnpm typecheck` 均通过。隔离工作区复用已有依赖，不安装新包，不修改锁文件。

## 七维审查

| 维度 | 结果与边界 |
| --- | --- |
| 边界条件 | PASS：新建、重连、循环、pending 丢失、旧消息及额外字段均覆盖 |
| 权限认证 | PASS：可信端点快照判来源；主体检查不变；验证消息归属收紧；自然人守卫不变 |
| 并发安全 | PASS：保留 pending 校验与原状态写入流程；错误不主动清理状态；未新增锁或并发协议；未证明并行重复提交的原流程可线性化 |
| 信息泄漏 | PASS：HTTP 内部 detail 和未知异常文本不返回页面；既有本地化错误码，内部堆栈留日志 |
| 测试覆盖 | PASS：21 项后端真实对话链路及 4 项新增页面断言；扩展失败与基线一致；真实中间件验证待部署 |
| 风格与架构 | 无新增分层依赖；Ruff 与差异检查通过。架构守卫仍报告 legacy WorkflowClient 两条 RULE-1，基线相同（原有 common → domain/api 导入），本次未新增或豁免此债务 |
| 文档同步 | PASS：design §4.11、已知坑、修订历史与本报告同步 |

审查结论：本次增量未发现新增 HIGH/MEDIUM 问题。基线测试与架构债务如上，不宣称全仓检查全绿。

## 部署后验收清单

1. 用新的免登录会话打开目标工作流，提交两轮输入，逐轮看到实际模型内容。
2. 到达输入节点后断开并重连，原会话提交输入能够续跑且历史归属不变。
3. 提交已消费的旧 message_id，页面显示输入失效原因并结束等待；新一轮合法输入仍可执行。
4. 普通登录工作流正常运行；跨会话/跨资源/跨租户输入仍被拒绝。

本次交付仅代码合入与推送，不代表 116/120 已更新镜像或通过现场验收。
