# Verification 4D 普通异步 Agent 长任务挂起与恢复

## W1 持久挂起与执行槽释放

2026-11-09 在本地工作区实施 T001–T006。隔离测试显式启用 `enable_long_tasks` 和 `enable_long_task_resume`，通过现有发布服务冻结 V1。执行记录和 Mock Agent 账本分别使用临时文件型 SQLite。Celery 生产者通过只监听回环地址的 Redis 7.2.17 投递，独立 Worker 使用 `solo` 池和一个实际执行槽，消费后调用真实 `execute_workflow` 任务体和 LangGraph。用户资料、权限、节点外部服务和会话回调使用测试夹具。

| 证据 | 验证结果 | 覆盖 |
| --- | --- | --- |
| E-001 · 定向验证 | T001 先在旧路径复现缺少持久等待、非法图未被 4D 准入拦截。实现后 7 项通过。覆盖快照在发送前已提交、已受理和回执未知、V1 与截止固定、重复派发、等待提交失败和旧 4B 继续执行。 | T001、T003–T006，AC-01／AC-07 的 W1 范围 |
| E-002 · 真实本地队列 | V-01 通过。同一独立 Worker 完成两条同队列任务。第一条退出后仍可从另一进程读取持久等待点。第二条成功后，原 Mock Run 仍为 `RUNNING`，原记录及期限保持，首条输出为零，第二条输出为一。 | T002、T006，AC-01 |
| E-003 · 相关回归与静态检查 | 最终组合 224 项通过、1 项跳过，退出 0。跳过为 F119 需要专用 API 和测试身份的 E2E。相关文件 Ruff、架构守卫和 `git diff --check` 通过。已有 SSO WebSocket 替身在关闭时记录缺 `client_state` 的日志，该用例断言通过。 | F119／F124／F125、相关 Workflow 和会话回归 |

### E-002 执行关联

| 事实 | 观测值 |
| --- | --- |
| Worker 与队列 | PID `80959`，实际执行槽 `1`，两条消息的路由均为 `f126_mock_workflow` |
| 第一条任务 | `8b6b4bfe-0335-4f96-8cf2-8e5f800551d4`，执行 `ceec56f3da8241b8aebee028ab33e686`，派发 `DONE`，执行 `WAITING`，阶段 `POLL_WAIT`，只执行开始节点 |
| 第二条任务 | `71f7369b-3cda-4b94-be0a-4d7eddbb1f7d`，在同一 PID 返回 `SUCCESS`，输出一次 |
| 原 Agent Run | `mock-async:6fbad74eaa5dd8cef84513a9589d51677a832f276c76c4264555101c15b7228d`，第二条任务前后均为 `RUNNING`，可控时钟下原截止 `1030.0`，第一条输出为零 |

Broker 和 Worker 由测试夹具关闭，验收结束后核对进程已退出。W1 的输出计数来自回调夹具。跨 Worker 恢复和持久聊天消息的单次提交分别由 W3 验证。

### 复跑方式

从 `src/backend` 使用已有的 Python 3.11 虚拟环境。设置 `BISHENG_TEST_PYTHON` 为 Python 3.11.14 解释器，`BISHENG_TEST_CONFIG` 为隔离后端配置，`F126_REDIS_SERVER` 为本地 Redis 可执行文件。V-01 测试自行启动临时 Redis 和 Worker。

```sh
config="$BISHENG_TEST_CONFIG" PYTHONPATH="$PWD" F126_REDIS_SERVER="$F126_REDIS_SERVER" \
  "$BISHENG_TEST_PYTHON" -m pytest \
  test/workflow/test_platform_agent*.py test/workflow/test_kunlian_workflow*.py \
  test/workflow/test_workflow_auto_rerun_status.py test/workflow/test_workflow_offline_input.py \
  test/sso/test_kunlian_ws_admission.py -q -s --disable-warnings --tb=short -rs
```

只复跑 W1 时，将测试范围缩小为 `test/workflow/test_platform_agent_long_task_resume_wait.py` 和 `test/workflow/test_platform_agent_long_task_resume_e2e.py`。缺少本地 Redis 可执行文件时，V-01 标记为待执行。

## W2 短任务查询与漏投补偿

| 证据 | 验证结果 | 覆盖 |
| --- | --- | --- |
| E-004 · Mock 故障注入 | 测试先行复现 W1 缺少查回、轮询及派发补偿。最终 11 项通过。启动响应丢失或注入 Worker 失联时按原键查回，远端只启动一次。丢失等待唤醒与首次恢复投递后，扫描复用同一派发 ID 和可信租户头。旧启动者、过期轮询租约、其他租户及撤权路径均被拦截。错配 Run／版本、无效结果、人工输入和远端失败不产生恢复派发，成功但结果不可用按原期限结束。 | T007–T010，V-03 的 W2 范围，AC-03／AC-04／AC-06 |
| E-005 · 相关回归与静态检查 | 使用上节命令复跑，235 项通过、1 项跳过，退出 0。F119 专用环境用例继续跳过。Ruff、架构守卫和 `git diff --check` 通过。V-01 同次复验确认 PID `82188` 的单执行槽 Worker 完成第二条任务时，第一条 Run 仍 `RUNNING`，输出次数分别为 0 和 1。 | W1 回归、W2 故障注入及相邻功能 |

W2 使用文件型 SQLite、持久 Mock 账本及可控时钟。启动者失联通过任务中断注入，补投证据来自 Celery 投递夹具，覆盖同一逻辑派发和租户头。只复跑 W2 时，使用上节的 Python 与隔离配置，测试路径为 `test/workflow/test_platform_agent_long_task_resume_reconcile.py`。

## W3 跨 Worker 恢复与单次输出

| 证据 | 验证结果 | 覆盖 |
| --- | --- | --- |
| E-006 · 领取、事务与授权 | 测试先行复现缺少领取与恢复入口。实现后 4 项定向用例通过。纯文本暂存后数据库为零条消息。注入消息 `flush` 后异常，消息和终态同时回滚。原派发换领取者后提交一次，旧领取者的提交和失败写回被拒绝。授权回执读到同一消息 ID，无权用户读回、损坏快照及恢复前撤权均被拒绝。 | T012–T016，V-03 的 W3 范围，AC-02／AC-03／AC-06 |
| E-007 · 真实本地队列恢复 | V-02 通过。A 保存 V1 等待点并退出，再发布 V2。按可控时钟让初次恢复领取过期。B 从 Redis 队列消费补投的同一派发，使用 V1 节点上下文和同一 Agent Run。A 启动 Agent 一次，B 未再次启动，开始节点未重跑。模拟提交后通知丢失，重复派发没有再次通知或写入，授权读回同一条消息。 | T011、T013–T017，V-02，AC-02／AC-03 |
| E-008 · 相关回归与静态检查 | 沿用 W1 组合命令，240 项通过、1 项跳过，退出 0。跳过项为 F119 专用环境用例。单执行槽 V-01 和真实队列 V-02 同次通过。相关文件 Ruff、架构守卫及差异检查通过。 | W1–W3 与相邻 Workflow 回归 |

| E-007 关联 | 观测值 |
| --- | --- |
| Worker 与版本 | A 的 PID `84304`，退出码 `0`。发布 V2 后由 B 的 PID `84315` 接管，执行仍使用 V1，恢复输出包含 A 保存的开始节点变量。 |
| 执行与派发 | 执行 `ed2bdbe9fc044275b8de8bcaef01b67e`，恢复派发 `d3cb268dcfab4bbeb6be5cafce5e9b03`，派发 ID 保持，领取者更新。 |
| Agent Run | `mock-async:0c5175d4eb626817360291f012caff9f3709594558fb2c8adbb157c26b65ec0a` |
| 持久输出 | 消息 ID `1`，数据库记录 `1` 条，通知尝试 `1` 次且模拟丢失，重投后授权读回仍为消息 `1`。 |

E-007 使用真实本地 Redis Broker 和两个独立 Celery Worker 进程。SQL 存储及 Mock Agent 账本使用临时文件型 SQLite，租约使用可控时钟，通知传输和身份服务用隔离夹具。Broker 与 Worker 由测试关闭。浏览器重连和普通历史读取的 4D 接线与验收留在 W5。只复跑 W3 时，使用上节的 Python、隔离配置与本地 Redis，选择 `test/workflow/test_platform_agent_long_task_resume_e2e.py` 和 `test/workflow/test_platform_agent_long_task_resume_output.py`。

## W4 停止、超时与取消确认

| 证据 | 验证结果 | 覆盖 |
| --- | --- | --- |
| E-009 · 定向验证 | `pytest test/workflow/test_platform_agent_long_task_resume_stop.py -q --disable-warnings --tb=short` 初次 4 失败、3 通过，复现了停止后派发仍被领取且等待材料未清理。修复后 7 项通过。 | 停止与成功竞争、截止已到的停止、轮询及恢复超时、取消漏投和未知启动查回。 |
| E-010 · 相关回归 | 沿用 W1 组合命令及同一隔离配置，251 项通过、1 项跳过，退出 0。包含 W4 的 11 个用例、真实本地队列的 V-01 和 V-02。唯一跳过项仍为 F119 专用环境用例。 | AC-03、AC-05、AC-06。新增验证包含消息 `flush` 后到期回滚、远端拒绝、取消未确认、迟到成功不恢复本地运行。 |

停止与到期在原执行行内封存等待材料、结束派发并裁决输出。停止后按原启动键查回及按原取消键核对，远端受理时仍保持本地停止状态，确认结果独立记录。已提交成功保留原消息回执。测试使用隔离 SQLite、持久 Mock Agent 账本及可控时钟，正式取消契约继续保留 TODO。

## W5 会话、授权与浏览器

| 证据 | 验证结果 | 覆盖 |
| --- | --- | --- |
| E-011 · 双前端浏览器闭环 | Chrome Headless 驱动退出 0。Platform 的保存和发布接口返回 200，冻结 Workflow V1 与 `mock:echo / v1`。Client 刷新后保留原执行、Run 和截止。成功输出回读为消息 `1`，SQL 仅一条，刷新后 DOM 只显示一次。另一次运行停止后收到 `ACCEPTED` 和 `CONFIRMED`，输出为零。停止终态刷新后保留，点「重新运行」后才产生新执行与新 Run。其他账号请求原会话返回 `10555`。 | V-04 浏览器，AC-05、AC-06、AC-07 |
| E-012 · Client 回归 | `jest --runInBand --coverage=false --silent src/pages/appChat/agentInteraction.test.tsx src/pages/appChat/appStreamStop.test.tsx src/pages/appChat/workflowUnavailable.test.tsx`，20 项通过。Client 严格类型检查和涉及文件 ESLint 通过。 | 普通长任务主动轮询和重连、旧版本帧拒绝、取消受理后继续核对，兼容现有单文本表单及原生输入。 |
| E-013 · 后端相关回归 | 沿用 W1 组合命令，追加 `test/chat_session/test_deleted_session_access.py`。262 项通过、1 项跳过，退出 0。唯一跳过项是 F119 需专用账号的正常环境用例。 | 包含 V-01、V-02 的真实本地队列复验、原会话和执行权限、结果回读、跨租户／接入方拒绝、通用历史与导出默认隔离、旧会话删除行为及相邻 Workflow。 |

浏览器使用两个实际 Vite 前端、FastAPI 的发布和 Workflow WebSocket 路由、本地 Redis 与独立 Celery Worker。用户身份、权限和 Mock Agent 时钟由隔离夹具提供，存储使用临时 SQLite。浏览器先复现了历史 ID 与 WebSocket 消息 ID 类型不同导致的重复渲染。修复后按同一持久 ID 合并，同时保留已授权历史的原时间等字段。历史与按会话取消息接口另用后端定向用例验证；通用 OpenAPI 历史、工作站读取和导出缺少对应授权上下文时排除受保护正文。

改动文件的定向 Ruff 和差异检查通过。架构守卫的四条提示与 HEAD 基线一致。扩展运行工作站导出测试时，其既有 `test_load_happy_path` 夹具未装配回填配对问题所需的数据库，该用例未计入通过结果。受保护输出的通用导出读取剔除由 E-013 的真实 SQLite 定向用例验证。

## 后续验证

| 范围 | 当前状态 |
| --- | --- |
| V-02 | 隔离 Mock 已通过，见 E-007。 |
| V-03 | W1–W4 已覆盖等待持久化、原启动查回、漏投补偿、过期接管、输出事务、停止与超时竞争。 |
| V-04 | 隔离浏览器、后端及 Client 回归通过，见 E-011～E-013。正式环境不计入本项。 |
| T029–T030 | `WAITING_EXTERNAL`，保留 `# TODO [F126][EXT-01]`～`[EXT-05]` 的正式替换项。 |
| T031／V-05、T032／V-06 | `NOT_RUN`，真实基础设施和昆联环境分别待执行。 |
