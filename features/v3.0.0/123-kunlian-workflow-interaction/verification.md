# F123 实施验证记录

本记录覆盖 4A T001–T012。Mock 使用 Python 3.11.14、隔离 ASGI 应用、文件型 SQLite、可控时钟及本地消息替身；复用真实 Workflow、LangGraph 检查点、运行仓储和候选任务入口。测试身份、授权决策、用户资料和对象存储使用替身。

以下 pytest 命令从 `src/backend` 执行，使用已有 Python 3.11 虚拟环境，`PYTHONPATH` 指向后端目录，`config` 使用隔离测试配置。未安装新依赖。

| 证据 | 阶段与实际命令 | 结果与范围 |
| --- | --- | --- |
| E-001 | W1，`pytest test/workflow/test_kunlian_workflow_interaction.py -k 'mode or pre_supplied or snapshot' -q --disable-warnings --tb=short` | 3 passed，退出 0。验证旧请求摘要、交互受理、冻结文本 Schema、非法图／输入和等待快照往返。独立进程夹具由 E-004 实际执行。 |
| E-002 | W2，`pytest test/workflow/test_kunlian_workflow_interaction.py -k 'concurrent_answer or waiting_deadline or resume_failures' -q --disable-warnings --tb=short` | 6 passed，退出 0。独立连接竞争只受理一次；恢复只消费当前阶段；等待、恢复排队、恢复执行超时和坏快照分别收敛；终态保留最小回执，到期清理。 |
| E-003 | W3，`pytest test/workflow/test_kunlian_workflow_interaction_e2e.py -k http_authorization -q --disable-warnings --tb=short` | 1 passed，退出 0。验证稳定轮询、输入拒绝、不同用户／租户／接入方不可见、权限依赖暂不可用、投递失败补偿、提交后撤权、轮询触发等待超时。 |
| E-004 | W4，`pytest test/workflow/test_kunlian_workflow_interaction_e2e.py -k independent_worker -q --disable-warnings --tb=short` | 1 passed，退出 0。A、B 为两个不同 PID 的 Python 进程，A 保存并退出后 B 读同一隔离数据库。两个进程走候选 Celery 任务入口，验证同会话、同 V1、开始节点仅执行一次，结果包含 A 产生的变量和新答案。补充检查结果和回执到期后的数据库清理，定向复验通过。 |
| E-005 | W4 相关回归，`pytest test/workflow/test_kunlian_workflow*.py test/workflow/test_platform_knowledge*.py test/workflow/test_platform_agent*.py test/workflow/test_workflow_action_map.py test/tenant/test_tenant_filter.py test/sso/test_kunlian_ws_admission.py test/open_api/test_workflow_invoke_input_errors.py -q --disable-warnings --tb=short -rs` | 169 passed、3 skipped，退出 0。含 F123 12 项和 F122 既有执行、幂等与权限回归。跳过为 F119／F120 的专用 API／Broker／Worker 或独立 Redis 验证。 |
| E-006 | W4 静态检查：Ruff check、Ruff format check、逐文件 `scripts/arch-guard.sh`、`git diff --check` 及新增文件的空白检查 | 10 个相关 Python 文件通过 Ruff，架构守卫无输出。候选路由和任务没有接入正式启动路径；实施前后暂存区摘要一致。 |

| Mock 验收 | 证据 |
| --- | --- |
| AC-01、AC-02、AC-03 | E-003～E-005。新 HTTP 请求能读取同一份待填表单；A 退出后 B 按同一 V1 恢复。等待期间发布 V2 并下线当前发布，新调用不能再受理 V1，已受理会话仍输出 V1 结果。 |
| AC-04、AC-05 | E-002～E-005。并发只受理一次，两个恢复投递只执行一次真实输入节点；终态回放原回执。同键改答案或换键重复消费被拒。不同用户、租户、接入方或撤权主体不能读取、提交或重放，提交后撤权时 Worker 不继续。 |
| AC-06、AC-07 | E-001～E-005。验证锁内时钟与条件更新、错误分类、迟到写入拒绝、保留期清理和 F122 原请求摘要、预置输入、无交互结果。 |

任务级检查核对了候选接口与服务分层、统一响应、租户作用域及消息头、复用现有运行行和敏感数据边界。快照只支持已验证的 LangGraph 版本和线性图等待点，未知格式拒绝恢复。候选接口与执行状态符合已确认设计。

## 正式适配及环境

| 任务 | 状态 | 待执行或确认 |
| --- | --- | --- |
| T013–T014 | `WAITING_EXTERNAL` | `TODO [F123][EXT-01]` 实际用户身份与权限时效；`TODO [F123][EXT-02]` 表单、提交、回执和错误协议；`TODO [F123][EXT-03]` 等待、恢复和保留窗口、资源上限及升级兼容策略。 |
| T015 | `NOT_RUN`（待执行） | 在 MySQL、中心 DM8、真实 OpenFGA、Broker 和独立 Worker 验证行锁、跨 Worker 恢复、重复投递、撤权和回退。SQLite 的独立连接验证条件写入，不能证明 MySQL／DM8 的锁行为。 |
| T016 | `NOT_RUN`（待执行） | `TODO [F123][EXT-04]` 昆联提供专用环境、测试身份和版本样例后验证双方链路。 |

候选接口和任务仅由隔离测试显式装配，未部署。

## T001–T012 审查与修复

审查按 `spec.md`、`design.md` 和 `tasks.md` 对照候选 HTTP、原生表单、运行仓储、Worker 及 F048 授权边界。规格及功能范围保持不变；下列复现均使用本地隔离环境。

| 发现 | 规格／任务 | 修复和验证 |
| --- | --- | --- |
| R1（P1）必填文本只有空白时仍消耗交互；省略选填项时，原生节点把字段标签用作答案。 | REQ-02、REQ-03、AC-04、T001、T005、T006、T009 | 冻结表单公开必填文本约束；空白返回 `422` 且可重试。恢复时才补空选填项，原提交摘要仍基于原始请求。 |
| R2（P1）首次领取或结束在数据库操作前采样时间，等待锁跨过截止时，旧时间仍可让写入成功。 | REQ-06、AC-06、T004、T007、T011 | 取得运行行锁后读取时钟，并在条件更新中保留状态和领取标识检查。用 SQLite 的 SQL 事件推进时钟，复现领取与结束两个场景；真实数据库行锁仍待验证。 |
| R3（P1）F048 禁用 `use` 时抛出 `InvalidCatalogActionError`，候选接口返回 `500`，Worker 无法把明确拒绝写成终态。 | REQ-05、AC-05、T006、T008、T009、T011 | 沿用既有拒绝策略：轮询、提交和重放返回 `404`，待恢复任务结束为 `FORBIDDEN`。临时不可用仍返回 `503` 或保留待领取。 |
| R4（P1）数据库中的答案变化后，Worker 仍可按与已接受回执不一致的文本执行。 | REQ-03、REQ-04、AC-02、AC-04、T005、T006 | 恢复前用冻结表单及已接受的答案摘要复核持久材料。故障注入后返回 `RESUME_STATE_INVALID`，清除快照和答案，保留原回执。 |
| R5（P2，可靠性）一条待恢复记录缺少交互标识时，补偿遍历抛出 `KeyError`，同批正常会话也无法补投。 | REQ-06、AC-06、T007、T011 | 锁内再次核对状态及归属，只结束损坏会话；同批有效会话继续补投。 |

| 证据 | 实际命令与结果 |
| --- | --- |
| E-007 | 修复前用新增用例复现 R1–R4 的 6 个失败（首次领取及结束分别复现）；另在 R5 修复前观察到补偿失败、其余 6 项通过。全部修复后，`pytest test/workflow/test_kunlian_workflow_interaction{,_e2e}.py -k 'after_waiting_for_database or changed_answer or http_authorization or disabled_use_action or omitted_optional or broken_resume_envelope' -q --disable-warnings --tb=short`：7 passed，退出 0。 |
| E-008 | `pytest test/workflow/test_kunlian_workflow*.py test/tenant/test_tenant_filter.py test/workflow/test_workflow_action_map.py test/open_api/test_workflow_invoke_input_errors.py -q --disable-warnings --tb=short -rs`：73 passed，退出 0。重新验证候选 HTTP、A 退出后由 B 从同一数据库恢复、版本固定、重复提交、F121／F122 兼容和租户边界。 |
| E-009 | 本次改动的 6 个 Python 文件通过 Ruff 检查及格式检查；逐文件架构守卫、文档引用和空白检查通过，暂存区摘要保持不变。 |

本次修复后，T001–T012 仍为 `MOCK_VERIFIED`。T013–T014 为 `WAITING_EXTERNAL`，T015–T016 为 `NOT_RUN`。没有执行真实数据库锁、OpenFGA、Broker／Worker 或昆联联调验证，未部署。
