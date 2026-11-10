# 4C 平台 Agent 人工输入浏览器验收

## 前置条件

- 准备隔离的毕昇 API、Redis、Broker 和 Workflow Worker，以及本地 Platform、Client。两端前端指向同一隔离 API。使用专用租户、测试用户和测试工作流。
- API 与 Worker 使用同一隔离 Mock Agent 配置和 Mock 账本，显式装配 `PlatformAgentService(enable_long_tasks=True, enable_interactions=True)`。使用隔离 Celery app 注册 `register_interaction_resume` 和 `register_long_task_reconcile`，把前者返回的任务传入后者的 `resume_task`，配置隔离测试租户与服务的 `long_wake`。确认 Worker 消费启动、恢复和补偿任务。
- 在 Platform 新建测试工作流，导入 [示例图](./mock-workflow.example.json)，或手动连接「开始 → 平台 Agent → 输出 → 结束」。确认节点为「人工输入示例 (模拟)」，固定版本为 `v1`，执行方式为异步，勾选允许 Agent 请求人工输入，输出引用 `platform_agent_example.result#answer`。为测试用户授予该 Workflow 的使用权限。

## 验收步骤

| 用例 | 操作 | 预期结果 |
| --- | --- | --- |
| AC-01、AC-08 · 配置与发布 | 分别检查同步模式和非交互版本；回到模拟 Agent `v1`，选择异步并启用人工输入，保存后重新打开，再发布。 | 只有隔离环境、异步模式和固定版本均满足时可以启用。保存后固定版本与开关可回读，旧图缺省关闭。 |
| AC-01、AC-02 · 刷新与提交 | 从 Client 打开该 Workflow 并启动会话。出现表单后记下执行 ID、Agent Run ID、交互 ID、修订和截止时间。刷新同一会话，填入专用文本并提交。 | 刷新前后关联和截止一致，等待期间没有下游输出。受理后表单关闭，沿用原 Run，输出包含提交文本且只有一次。 |
| AC-03、AC-05 · 回执丢失 | 在独立测试运行中选择模拟版本 `lost`，提交后断开再连接。记录客户端提交标识和状态。 | 按原提交关联查回。未确认时可见核对提示，最终沿用原 Run，重复提交不增加有效受理或输出。 |
| AC-06 · 停止 | 新建会话重新运行 `v1`。表单出现后点击原停止按钮，刷新或重连并继续观察取消状态。 | 表单关闭，工作流停止。取消受理与确认分开显示，迟到状态不会重新打开表单或输出。 |
| AC-04 · 会话隔离 | 用无该执行归属的测试用户请求原执行的状态。 | 响应不含表单和答案，原执行不受影响。 |

T027 固定 V1 浏览器验收已通过，含配置发布、刷新提交、停止后刷新及不同用户读取拒绝。回执丢失场景沿用 V-03 自动化证据。本轮运行关联及状态见[验证记录](./verification.md)。验证记录不保存用户填写的答案、凭据或恢复材料。
