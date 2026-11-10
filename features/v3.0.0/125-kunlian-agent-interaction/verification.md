# F125 验证记录

## W1 等待点保存 · T001–T008

在 `src/backend` 使用已有 Python 3.11.14 虚拟环境，`PYTHONPATH` 指向当前后端并使用隔离配置。执行行使用文件型 SQLite，昆联使用隔离 Mock 账本。测试由 Celery 任务夹具传递租户头并执行实际任务体、发布绑定、Workflow 图和节点。Redis 通知、身份、配置、对象存储由夹具替换。

| 证据 | 命令与结果 | 覆盖 |
| --- | --- | --- |
| E-001 | `pytest test/workflow/test_platform_agent_interaction_{contract,wait}.py -q --disable-warnings --tb=short`，9 项通过，退出 0。 | 固定版本能力、原 Run 提交键、明确拒绝与回执丢失。保存等待点后原派发结束且无下游，直接成功输出一次。覆盖旧续跑拒绝、非浏览器拒绝、发布快照错配、坏快照及落库失败无待办。 |
| E-002 | `pytest test/workflow/test_platform_agent*.py test/workflow/test_kunlian_workflow*.py test/workflow/test_workflow_auto_rerun_status.py test/workflow/test_workflow_offline_input.py test/sso/test_kunlian_ws_admission.py -q --disable-warnings --tb=short -rs`，173 项通过、1 项跳过，退出 0。 | 包含 F119 同步、F124 异步、F123 原生输入及相邻会话和准入回归。跳过的 F119 用例需要专用 API／Broker／Worker 与 Mock 用户。 |
| E-003 | 定向 Ruff、逐文件架构守卫、空白及暂存区检查。 | 主要修改及新增 Python 文件 Ruff 通过。共享图引擎和 Worker 文件的既有 Ruff 提示单列。架构守卫无新增提示，暂存区摘要一致。 |

测试先行阶段先观察到交互能力、模拟版本和隔离装配缺失。W1 最终覆盖从发布、浏览器运行受理到 Worker 写入等待点的路径。检查点恢复用例在测试进程内新建图实例验证装载，完整的双 Worker 提交和续跑由 W2 验收。

## W2 提交幂等与跨 Worker 恢复 · T009–T013

沿用 Python 3.11.14 和隔离配置。提交竞争用独立 SQLite 连接及 `BEGIN IMMEDIATE` 写事务模拟串行判定。跨 Worker 验收用两个独立 Python 进程执行真实 Celery 任务体，共用文件型 SQLite 执行记录和独立持久 Mock Agent 账本。消息头、Redis 回调、身份与权限服务为隔离夹具。

| 证据 | 命令与结果 | 覆盖 |
| --- | --- | --- |
| E-004 | `pytest test/workflow/test_platform_agent_interaction_{submit,e2e}.py -q --disable-warnings --tb=short`，11 项通过，退出 0。 | 并发同键只建一份派发，冲突拒绝，阶段期限独立。同键查回、查回不可用、明确拒绝、结果不可用、错 Run 及第二次等待。独立 Worker A 退出后发布 V2，Worker B 恢复原 V1、原 Agent Run 与交互。开始节点、有效提交和下游输出各一次。已完成派发重投无副作用，撤权或快照损坏时无远端提交。 |
| E-005 | `pytest test/workflow/test_platform_agent*.py test/workflow/test_kunlian_workflow*.py test/workflow/test_workflow_auto_rerun_status.py test/workflow/test_workflow_offline_input.py test/sso/test_kunlian_ws_admission.py --ignore=test/workflow/test_platform_agent_interaction_submit.py --ignore=test/workflow/test_platform_agent_interaction_e2e.py -q --disable-warnings --tb=short -rs`，184 项通过、1 项跳过，退出 0。 | 显式路径集合包含 W2 用例，同时回归 F119 同步、F124 普通异步、F123 原生交互及既有会话权限。F119 专用 API／Broker／Worker 用例继续待执行。E-004 与本结果有重叠。 |
| E-006 | 定向 Ruff、逐文件架构守卫、空白及暂存区检查。 | 主要修改与新增文件 Ruff 通过。共享 Worker `tasks.py` 仍有既有导入顺序提示。架构守卫无新增提示，暂存区摘要一致。 |

W2 测试先行时观察到本地答案受理能力缺失。最终通过同一执行行的受理与派发判定，并区分本地收到答案、远端受理和回执未知。Mock 只有在只读查回成功但缺少回执且明确支持同键安全重放时，才在原期限内重放一次。当前证据用于 V-02 和 V-03 的 W2 范围。真实数据库行锁、实际 Broker 投递和昆联回执语义由 V-04 验证。

## W3 停止、超时与补偿 · T014–T016

继续使用 Python 3.11.14、文件型 SQLite 和隔离 Mock Agent 账本。停止与提交的顺序由可控时钟和传输拦截点确定，另一仓储连接写入停止或核对事实。补偿测试直接执行隔离任务体，以替身注入 Celery 租户头和投递异常。跨 Worker 回归沿用 W2 的独立进程。

| 证据 | 命令与结果 | 覆盖 |
| --- | --- | --- |
| E-007 | `pytest test/workflow/test_platform_agent_interaction_reconcile.py -q --disable-warnings --tb=short`，14 项通过，退出 0。 | 停止先于许可或传输接手时远端提交为零。在途停止沿用原 Run 和取消键，取消受理可收敛为已确认。覆盖 120 秒人工等待、30 秒排队和提交核对、30 秒结果等待、15 秒取消窗口。验证漏投只补原派发、已领取任务只查回执、旧核对租约和迟到结果被拦截。覆盖终态材料清理、去重保留期和旧 Mock 记录。 |
| E-008 | `pytest test/workflow/test_platform_agent*.py test/workflow/test_kunlian_workflow*.py test/workflow/test_workflow_auto_rerun_status.py test/workflow/test_workflow_offline_input.py test/sso/test_kunlian_ws_admission.py -q --disable-warnings --tb=short -rs`，198 项通过、1 项跳过，退出 0。 | 包含 E-007、跨进程恢复原 V1、撤权、坏快照、F119 同步、F124 普通异步、F123 原生交互及会话准入。跳过的 F119 用例需要 API、Broker、Worker 和专用 Mock 用户。 |
| E-009 | 修改文件 Ruff、逐文件架构守卫及空白检查均通过。 | 补偿消息只携带原执行、交互与派发标识，租户通过可信头传递，日志只写异常类型。无数据库结构变更，暂存区摘要一致。 |

测试先行复现了许可后停止仍发出答案、终态材料残留和原派发缺少补投。首次合并回归的 3 个失败来自 W2 测试对终态快照的旧断言。调整为恢复前校验 V1 检查点，终态按原派发及 Run 核对版本并断言材料已清理。补偿验证包含失联任务在原阶段截止后的收敛，SQLite 的顺序验证与任务体执行证据仍属于隔离 Mock。

## W4 会话、前端与浏览器验收 · T017–T027

| 证据 | 命令与结果 | 覆盖 |
| --- | --- | --- |
| E-010 · 后端会话与回归 | 在 `src/backend` 执行 `pytest test/workflow/test_platform_agent*.py test/workflow/test_kunlian_workflow*.py test/workflow/test_workflow_auto_rerun_status.py test/workflow/test_workflow_offline_input.py test/sso/test_kunlian_ws_admission.py -q --disable-warnings --tb=short -rs`，208 项通过、1 项跳过，退出 0。 | 包含 T017 的 10 项会话测试。校验显式执行、Redis 引用丢失、租户与登录来源、撤权停用、日志脱敏、原生输入和停止。将示例图发布后执行实际启动、恢复任务体与图，原 Run 的结果只生成一次。跳过的 F119 用例需要专用 API、Broker、Worker 和用户。 |
| E-011 · Platform | 在 `src/frontend/platform` 执行 `vitest run src/pages/BuildPage/flow/FlowNode/component/PlatformAgentItem.test.tsx`，12 项通过，退出 0。 | 覆盖隔离可用性、异步模式、固定版本、旧图缺省关闭、验证请求中的显式配置、换版本拦截和输入映射。 |
| E-012 · Client | 在 `src/frontend/client` 执行 `jest --runInBand --coverage=false --silent src/pages/appChat/agentInteraction.test.tsx src/pages/appChat/appStreamStop.test.tsx src/pages/appChat/workflowUnavailable.test.tsx`，15 项通过，退出 0。另用临时 Node 测试配置执行 `workflowAutoRerun.test.ts`，8 项通过，退出 0。 | 待办提示回查、Socket 重连、提交 ID 复用、旧帧拒绝、停止后关闭表单、原生输入及自动重跑兼容。Jest 仅在本次进程屏蔽 jsdom 的可选 `canvas` 解析。Node 用例临时跳过依赖 DOM 的公共 setup。 |
| E-013 · Chrome 组件冒烟 | 使用临时 esbuild 页面和 Chrome Headless 实际操作，退出 0。 | 挂载真实 `PlatformAgentItem`、`WorkflowForm`、`useWebSocket`，用模拟资源接口和 Socket 驱动。点击启用，填写提交，模拟断线后用相同 ID 发送，收到一次模拟输出。在第二次运行点击停止，收到取消确认并拦截旧帧。 |
| E-014 · 静态检查 | 两端严格类型检查、涉及文件 ESLint、`pnpm check-i18n`、空白检查通过。 | 架构守卫的三条 `RULE-1` 提示在暂存基线同样出现。两个共享 Python 文件有既有 Ruff 提示，其他涉及文件定向 Ruff 通过。暂存区摘要一致。 |

后端测试先复现了会话入口缺失。首次合并回归还发现旧会话测试对象未构造浏览器连接字段，调整为先判定是否装配 4C 端口后，历史会话、原生输入和准入回归通过。

W4 首轮已备好 T027 的 [示例图](./mock-workflow.example.json)和[验收清单](./e2e-checklist.md)。当时缺少隔离运行栈，E-013 的 Chrome 结果限于组件和模拟传输。后续完整浏览器证据见 E-018。

## 4C 实现审查与修复

对照规格、设计和 T001–T027，复核固定版本、检查点与领取、阶段截止、补偿及浏览器边界。以下为审查发现及已验证的修复。

| 严重度 | 关联 | 发现与修复 |
| --- | --- | --- |
| P1 | AC-04 · T017–T019 | 新建执行时缺少已有会话归属检查，读取结果期间的授权可能过期。新建与查询复用会话归属检查，输出发送前复核权限，状态拒绝时返回脱敏错误。 |
| P1 | AC-06、AC-08 · T019、T024–T025 | 显式停止传入非 4C 执行或空 ID 时可能回退到普通停止。Client 断线期间的停止也可能丢失。显式停止限定原执行，重连时优先发送待确认的停止并拦截答案重发。普通公开会话继续走已有停止入口。 |
| P1 | AC-03 · T017、T024–T025 | 旧修订等提交错误可能让仍有效的表单永久关闭。Client 重新查询原执行，保留状态版本；拒绝授权时关闭表单、停止轮询并拦截旧帧。 |

| 证据 | 命令与结果 | 范围 |
| --- | --- | --- |
| E-015 · 后端回归 | 沿用 E-010 的 pytest 命令，213 项通过、1 项跳过，退出 0。 | 包含已存在的跨 Worker、状态竞争和兼容用例，以及新建会话归属、错误执行 ID 停止、撤权状态与输出、公开会话停止。跳过项仍是 F119 独立环境用例。 |
| E-016 · 前端回归 | 沿用 E-012 的三套 jsdom Jest 用例，18 项通过；沿用 E-011 的 Platform Vitest 命令，12 项通过。均退出 0。 | 断线停止优先、无效提交后的回查、拒绝授权后的轮询与旧帧拦截，以及原流程兼容。Client 严格类型检查、涉及文件 ESLint 和三语检查通过。 |
| E-017 · Chrome 组件冒烟 | 沿用 E-013 的 Chrome Headless 模拟传输场景，重新执行通过，退出 0。 | 节点开关、文本表单、重连复用提交 ID、模拟结果和停止。独立 API／Redis／Broker／Worker 的完整验收仍为待执行。 |

先用定向测试复现了错误停止目标、撤权查询无安全回包、新建缺少归属校验、断线停止丢失和无效提交后无法再填。修复后复验了新发现及已有相关行为。正式契约占位继续保留。

## T027 固定 V1 隔离浏览器验收

以独立临时目录启动两个实际 Vite 前端、FastAPI、Redis 7.2.17 和独立 Celery Worker。所有服务只监听回环地址。Redis 同时承载消息队列、状态流和 Mock Agent 账本，执行与会话记录使用文件型 SQLite。FastAPI 挂载仓库里的保存、发布、Agent 资源和 Workflow WebSocket 路由。登录、权限、非关键页面接口与存储边界使用隔离夹具。Redis 使用[官方发布包](https://download.redis.io/releases/)在临时目录构建。

| 证据 | 操作与结果 |
| --- | --- |
| E-018 · 完整浏览器闭环 | Chrome Headless 打开 Platform 的 V1 草稿，勾选人工输入并发布。实际 `PUT /api/v1/workflow/versions/1` 与 `PATCH /api/v1/workflow/status` 均返回 200。发布绑定为 `mock:interaction/v1`、`async`、`allow_interaction=true`。随后通过 Client 的真实 WebSocket 走提交和停止两条路径。浏览器驱动退出 0。 |
| E-019 · 后端回归 | 沿用 E-010 的 pytest 命令，216 项通过、1 项跳过，退出 0。新增覆盖断线清理、刷新保留已停止终态及显式重跑兼容。跳过的是 F119 专用环境用例。 |
| E-020 · 前端回归 | 沿用 E-012 的三套 jsdom Jest 用例，19 项通过，退出 0。Client 类型检查、涉及文件 ESLint、定向 Ruff 和差异检查通过。 |

Workflow ID 为 `12500000000000000000000000000001`，发布版本记录 ID 为 `1`。

| 路径 | 执行 ID | 交互 ID | Agent Run ID | 结果 |
| --- | --- | --- | --- | --- |
| 刷新后提交 | `ef2122bb0456409c80614b09a423a7e9` | `36bd01da678e41639c786cb9d99461d7` | `mock-async:dcf73148bae7a02bf4b52b33b0c14cfa562ee461322acbdcb301e2ec0858e249` | 刷新前后会话、执行、交互、修订和截止时间一致。等待时输出为零，提交后原 Run 成功。Worker 收到启动和恢复派发各一次，浏览器和会话历史各记录一个输出。另一测试用户查询此交互返回 `10555`，响应中无表单。 |
| 等待时停止 | `05d66762140f42548f736e92b828bc05` | `0fcc85635fd342019275abd394eb1c21` | `mock-async:53209a7fe147b3ae9f2d7f986bfa9a2e6b9618f7cd4196b17aef393f3c56d35d` | 本地 `STOPPED`，取消依次到 `INTENT`、`ACCEPTED`、`CONFIRMED`，远端 `CANCELLED`。没有答案提交或输出。再次刷新仍是原执行和原终态，执行记录数量仍为一条。 |

浏览器先复现了两处刷新问题。被动断线清理会向已关闭的 WebSocket 发送帧；已停止且无历史消息的会话会被首次页面连接再次启动。修复后区分被动清理和主动停止，并通过 `initial_open` 区分页面连接与主动重跑。最终复验的 API 日志无上述断线异常。

## 待执行

| 范围 | 状态 |
| --- | --- |
| V-02 | 隔离 Mock 跨进程恢复已通过。受控环境的跨 Worker 验收归 V-04。 |
| V-03 | W1～W4 有定向及相关回归证据。 |
| T028–T029 | `WAITING_EXTERNAL`。正式接口占位保留。 |
| T030–T031、V-04 | `NOT_RUN`。MySQL／DM8、OpenFGA、Broker／Worker 及昆联联调待执行。 |
