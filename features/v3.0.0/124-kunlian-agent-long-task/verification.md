# F124 验证记录

4B 使用显式装配的隔离 Mock。工作流执行记录使用文件型 SQLite，昆联事实由独立模拟账本提供，身份、对象存储、Broker 和 WebSocket 传输使用受控夹具。测试执行真实发布绑定、节点、图引擎、现有停止服务和会话状态方法。补偿用例通过另一个服务和仓储实例读取原记录，未验证真实多进程 Broker 或数据库行锁。

| 证据 | 范围 | 实际结果 |
| --- | --- | --- |
| E-001 | W1，`pytest test/workflow/test_platform_agent_long_task_contract.py test/workflow/test_platform_agent_contract.py -q --disable-warnings --tb=short` | 21 项通过。覆盖旧节点缺省同步、固定版本异步能力，以及更换适配器实例后复用原启动和取消关联。 |
| E-002 | W2–W4，`pytest test/workflow/test_platform_agent_long_task*.py -q --disable-warnings --tb=short` | 17 项通过。包含启动回执丢失、错误 Run 结果拒绝、发送前超时与停止、取消回执丢失、受理／拒绝／未确认、撤权、补偿漏投和现有会话状态读取。真实最小图验证 V2 发布后原 Run 保持 V1，以及停止与输出提交的顺序。 |
| E-003 | Client，Jest 对 `appStreamStop.test.tsx` 与 `workflowUnavailable.test.tsx` 的定向测试 | 11 项通过。当前环境的可选 `canvas` 原生模块缺失，使用临时 Node 预加载替身让 jsdom 按无画布模式运行。核对旧消息不会恢复已停止输出，取消确认能更新原执行的状态。 |
| E-004 | Platform，`vitest run src/pages/BuildPage/flow/FlowNode/component/PlatformAgentItem.test.tsx` | 8 项通过。验证既有组件兼容。样例图另经后端保存、发布和执行测试，实际浏览器保存与发布待验。 |
| E-005 | Ruff、架构守卫、TypeScript 单文件转译、多语言键一致性、`git diff --check` | 新增与主要改动 Python 文件的 Ruff 检查通过。共享 `graph_engine.py` 和 `redis_callback.py` 有既有 Ruff 提示，`workflow_client.py` 的两条架构守卫提示可在 HEAD 复现。TSX 转译、三种语言键和空白检查通过，暂存区摘要一致。 |
| E-006 | `pytest test/workflow/test_platform_agent*.py test/workflow/test_kunlian_workflow*.py -q --disable-warnings --tb=short -rs` | 129 项通过，1 项跳过，退出码 0。包含 F124、F119 及相邻昆联 Workflow 回归。跳过项需要 F119 专用 API／Broker／Worker 与测试用户。 |

后端在 `src/backend` 使用已有 Python 3.11 虚拟环境，`PYTHONPATH` 指向当前后端，使用隔离测试配置。扩展回归加入 `test/celery/test_workflow_task_authorization.py` 时，有 5 个旧访客 Worker 用例进入真实会话 DAO 后因隔离配置缺少数据库地址失败。该路径与 4B Mock 账本验证分别记录。另一次前端试跑中的 `workflowAutoRerun.test.ts` 使用 Node 测试环境，现有全局 setup 访问 `Element` 导致该文件未运行。

## Mock 实现审查

对照规格、设计 §4 和任务记录复核了固定版本、启动去重、轮询和输出、停止及补偿、运行人校验与旧同步路径。以下偏差已修复，原有正式接口占位继续保留。

| 问题 | 对应验收与任务 | 修复与回归 |
| --- | --- | --- |
| 截止后拒绝输出时，执行行可能仍显示等待或被记成普通失败。 | AC-05、AC-06，T006–T009 | 结果就绪和输出提交的门禁都在执行行事务内记录超时。远端已成功时保留该事实，并记为本地结果不可用。两处截止竞争均以可控时钟验证，输出门禁不放行。 |
| 查询旧执行时，缺少旧摘要会落到当前执行的 Redis 事件流。空执行 ID 也会误用当前引用。 | AC-01、AC-07，T014–T016 | 显式 ID 先验证格式和归属，历史查询只查原执行。测试验证旧执行尚未进入 Agent 节点时也不会读取当前状态。 |
| 主动停止已提交，但旧回调仍占用连接，可能吞掉显式重跑。旧读取器也可能继续发出迟到事件。 | AC-04、AC-05，T014–T016 | 停止后释放当前回调，同一连接显式重跑可跳过已停止执行的残留 Redis 状态。原读取器只能结束自身。测试覆盖待返回的旧事件和替换后的回调。 |
| 前端会被缓冲事件覆盖较新的取消进度，或把前一节点的终态套到同一执行的后续 Agent 节点。 | AC-03、AC-04，T015、T018 | 按执行与节点调用顺序归并，忽略旧状态和旧进度。调用顺序保存在既有执行 JSON 中，早期 Mock 记录按启动时间读取。会话分别展示本地停止或超时与远端取消事实。测试覆盖 JSON 键重排和客户端乱序帧。 |

| 证据 | 范围 | 实际结果 |
| --- | --- | --- |
| E-007 | Client，Jest 对 `appStreamStop.test.tsx` 与 `workflowUnavailable.test.tsx` 的定向回归 | 13 项通过，退出码 0。继续使用 E-003 的可选画布替身，新增覆盖取消状态、进度和节点调用乱序。 |
| E-008 | Platform，`vitest run src/pages/BuildPage/flow/FlowNode/component/PlatformAgentItem.test.tsx` | 8 项通过，退出码 0。 |
| E-009 | Python 定向静态检查、Client 单文件转译、语言资源解析与状态键检查 | 六个改动 Python 文件的 Ruff lint 和格式检查通过，三个 Client TypeScript 文件单独转译通过，三语言状态键一致。 |
| E-010 | `pytest test/workflow/test_platform_agent*.py test/workflow/test_kunlian_workflow*.py test/workflow/test_workflow_auto_rerun_status.py test/workflow/test_workflow_offline_input.py test/sso/test_kunlian_ws_admission.py -q --disable-warnings --tb=short -rs` | 164 项通过，1 项跳过，退出码 0。覆盖本次修复、F119 同步、相邻昆联 Workflow、旧会话状态与离线入口、WebSocket 身份准入。跳过项为需专用 API／Broker／Worker 与测试用户的 F119 用例。 |
| E-011 | 架构守卫、差异空白检查及暂存区校验 | 本次改动未新增架构守卫提示。共享 `workflow_client.py` 的两条 RULE-1 提示与 HEAD 一致。差异及新增文件空白检查通过，暂存区摘要一致。 |

## 阶段状态

| 范围 | 状态 | 边界 |
| --- | --- | --- |
| T001–T016 | 隔离 Mock 验证通过 | 覆盖显式启用、运行、停止和补偿核心路径。 |
| T017–T020 | 自动化部分已有证据，阶段验收待执行 | 最小图保存与执行、Client 消息测试和原会话状态方法已验证。还需在隔离浏览器和完整 API／Worker／Redis 栈中操作发布、断线重连及停止，随后收口 W4。 |
| T021–T022 | `WAITING_EXTERNAL` | 等昆联确认启动与查回、状态与结果、取消及实际用户委托。 |
| T023–T024 | `NOT_RUN` | 受控双库、OpenFGA、Broker／Worker 及双方联调待执行。 |

首轮 Mock 的隔离装配使用 `PlatformAgentService(enable_long_tasks=True)` 和 `register_long_task_reconcile`，将返回的唤醒函数注入服务。仅向隔离 Celery 应用传入明确的测试租户以启用定时补偿。待验浏览器流程使用 `mock-workflow.example.json` 在隔离环境发布 V1，用有会话的正常入口运行并断开重连。再次执行后在 Agent 运行时使用原停止入口，检查本地先停止、昆联 Mock 后确认取消且下游无输出。正式环境验证待执行，未部署。
