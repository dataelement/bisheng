# F122 实施验证记录

| Evidence | 阶段与命令 | 结果与范围 |
| --- | --- | --- |
| E-001 | 修改前，`pytest test/workflow/test_kunlian_workflow_publication.py test/open_api/test_workflow_invoke_input_errors.py -q --disable-warnings` | 17 passed，退出 0。F121 发布与既有开放调用基线。 |
| E-002 | W1，`pytest test/workflow/test_kunlian_workflow_invocation.py -q --disable-warnings --tb=short` | 初始定向用例在实现前因运行仓储尚未定义而收集失败。实现后 2 passed，退出 0。隔离 SQLite 验证版本冻结、重放、输入拒绝和撤权重试。F048 决策由测试控制。 |
| E-003 | W2，同 E-002 的定向命令 | 3 passed，退出 0。新增验证投递结果未知后的补投、重复消息只启动一次、租户隔离、超时迟到写入及保留窗口。图输出在此用例由替身提供。 |
| E-004 | W3／W4 定向，`pytest test/workflow/test_kunlian_workflow_invocation{,_e2e}.py -q --disable-warnings --tb=short` | 6 passed，退出 0。候选 HTTP、F121 发布、实际图引擎及测试任务适配连通。身份、授权决策和 Broker 由测试替身提供，SQLite 使用独立数据库连接。 |
| E-005 | 最终相关回归，`pytest test/workflow/test_kunlian_workflow*.py test/workflow/test_platform_knowledge*.py test/workflow/test_platform_agent*.py test/workflow/test_workflow_action_map.py test/tenant/test_tenant_filter.py test/sso/test_kunlian_ws_admission.py test/open_api/test_workflow_invoke_input_errors.py -q --disable-warnings --tb=short -rs` | 155 passed、3 skipped，退出 0。其中 F122 6 项全部通过。跳过为 F119／F120 的专用 API／Broker／Worker 或独立 Redis 用例。 |
| E-006 | Ruff check、Ruff format check、逐文件架构守卫、`git diff --check` 和正式路由／任务装配检查 | 11 个相关 Python 文件通过 Ruff，架构守卫无输出。正式路由和 Worker 启动配置未发现候选接线。实施前后的暂存区摘要一致。 |

测试使用现有 Python 3.11.14 虚拟环境，`PYTHONPATH` 指向当前后端目录，`config` 使用回环占位的隔离测试配置。MySQL／DM8、真实 OpenFGA、跨进程 Broker／Worker 与昆联联调均为 `NOT_RUN`。

## Mock 验收

| 验收 | 本地证据 |
| --- | --- |
| AC-01、AC-02 | E-005。原 HTTP 客户端关闭后，可通过新请求读取 V1 结果。V2 替换不影响已受理的 V1。V2 下线后，已受理 V2 继续执行，新调用被拒。 |
| AC-03、AC-04 | E-005。输入和身份覆盖被拒。附带输出文件的旧参数别名无法进入最小图。验证运行使用 B，拒绝不同租户、接入方、用户以及撤权后的查询、重放和 Worker 启动。 |
| AC-05 | E-005。独立连接并发同键只产生一个会话，同键改版本冲突，受理后重复请求恢复原会话。补投和重复消息只执行一次，迟到结果不能覆盖超时。 |
| AC-06 | E-005。查询区分待运行、运行中与终态，失败结果可重读且不暴露原异常。权限依赖暂不可用返回 `503`，恢复后仍能查询原结果。 |

任务级静态自审核对了分层、租户上下文、候选错误响应、数据库模型、Celery 租户消息头及设计同步。Mock 实现沿用隔离 ASGI 应用、候选错误分类和测试夹具。正式接口、业务错误码、对接身份和保留策略留待 T013–T014。T015–T016 待专用环境及授权。

## 规格对照审查与修复

审查覆盖 `spec.md`、`design.md`、`tasks.md` 的 T001–T012，以及 F121 发布准入、F048 授权上下文、运行仓储、候选 HTTP、Worker 和图引擎的直接调用边界。

| 发现 | 追溯 | 修复和验证 |
| --- | --- | --- |
| R1（P1）F048 优先使用请求上下文已有的权限主体，可能以服务账号或访客身份替代本次核验的实际用户。 | REQ-03、AC-04、T004、T009 | F048 检查时隔离开放接口、权限主体和访客上下文，检查结束恢复调用方原有上下文。用有权限的外层主体与无权限的实际用户复现，确认提交被拒且无投递。 |
| R2（P1）接入方标识依赖数据库文本比较。比较忽略大小写时，可命中其他接入方的幂等记录或登记记录，补偿也可能处理异属会话。 | REQ-01、REQ-03、REQ-04、AC-03、AC-04、AC-05、T002、T003、T007 | 读取后严格核对接入方。幂等记录不匹配时拒绝，版本资料异属或格式异常时不可调用，补投、超时及过期清理跳过异属记录。用 SQLite `COLLATE NOCASE` 模拟比较行为。 |
| R3（P2）查询在权限复核期间跨过保留截止时间时，仍可能返回过期结果。 | REQ-05、AC-01、AC-06、T009 | 权限复核后再次检查截止时间。用可控时钟让查询在授权期间过期，结果为 `404`，响应无输出。 |
| R4（P2）图引擎把原始异常写入内部日志。异常可能含业务数据。 | REQ-06、AC-06、T006、T012 | F122 显式启用异常脱敏，图引擎只记异常类型，Worker 按会话记录安全失败分类。用同一模拟异常检查内部图日志及 HTTP 响应均不包含异常原文。既有图引擎调用默认使用原日志行为。 |

| Evidence | 命令 | 结果 |
| --- | --- | --- |
| E-007 | `pytest test/workflow/test_kunlian_workflow_invocation{,_e2e}.py -q --disable-warnings --tb=short` | 修复前复现 R1–R3 共 3 个失败，随后单独复现 R4 的日志断言失败。修复后 8 passed，退出 0。 |
| E-008 | 最终相关回归，命令同 E-005 | 157 passed、3 skipped，退出 0，包含 F122 8 项及相关 F121、平台 Agent、知识库、租户和既有开放调用测试。跳过项同 E-005。 |
| E-009 | Ruff、逐文件架构守卫、`git diff --check`、暂存区摘要核对 | 6 个 F122 直接相关 Python 文件通过 Ruff 检查与格式检查。两个共享图文件有 14 项既有 Ruff 提示，与 `HEAD` 对照无新增。架构守卫和 diff 检查通过，暂存区摘要一致。 |

T001–T012 保持本地 Mock 完成。T013–T014 等待正式契约。T015 的 MySQL／DM8、真实 OpenFGA、跨进程 Broker／Worker，以及 T016 的双方联调均标记为待执行（`NOT_RUN`）。本次证据来自隔离环境，未部署。
