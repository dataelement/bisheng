# F078 L1 逐任务审查

**日期**：2026-10-27。读取目标文件，对照 Spec/Design/Tasks 检查当前未提交差异。

适用当前 Constitution 与既有 E+ Repository/session factory 边界；无新 ORM/API/UI。旧清单 DAO classmethod/RBAC 表述不覆盖当前租户 bulk-update 约束。

## Task Review: T001

**任务**：配置与域开关。
**类型**：基础设施
**文件**：`src/backend/bisheng/core/config/settings.py`；`src/backend/bisheng/common/services/metric_log.py`

| # | 检查项 | 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | 架构分层 | PASS | 严格正整数配置与两个域开关在基础设施层，无领域反向依赖。 |
| 2 | 命名规范 | N/A | 按任务适用项核对 |
| 3 | 序列化约定 | N/A | 无新 ORM/API 响应 |
| 4 | 数据库约定 | PASS | 按任务适用项核对 |
| 5 | 前端约定 | N/A | 无前端变更 |
| 6 | 信息泄漏 | PASS | 按任务适用项核对 |
| 7 | 设计同步 | PASS | 按任务适用项核对 |

**元数据验证**：文件范围 PASS | 配对测试 N/A | 依赖 PASS。
**结果**：PASS

## Task Review: T002

**任务**：终态字段与脱敏测试。
**类型**：测试
**文件**：`src/backend/test/metric_log/test_robot_events.py`

| # | 检查项 | 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | 架构分层 | N/A | 完整终态字段、稳定用户标识、敏感字段及开关/异常测试。 |
| 2 | 命名规范 | PASS | 按任务适用项核对 |
| 3 | 序列化约定 | N/A | 无新 ORM/API 响应 |
| 4 | 数据库约定 | N/A | 按任务适用项核对 |
| 5 | 前端约定 | N/A | 无前端变更 |
| 6 | 信息泄漏 | N/A | 按任务适用项核对 |
| 7 | 设计同步 | N/A | 按任务适用项核对 |

**元数据验证**：文件范围 PASS | 配对测试 N/A | 依赖 PASS。
**结果**：PASS

## Task Review: T003

**任务**：只读快照与事件输出。
**类型**：后端 Domain
**文件**：`src/backend/bisheng/eplus/domain/schemas/metric.py`；`src/backend/bisheng/eplus/infrastructure/metric_events.py`

| # | 检查项 | 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | 架构分层 | PASS | 只读快照在 Domain schemas，脱敏/日志在 infrastructure；不含业务内容。 |
| 2 | 命名规范 | PASS | 按任务适用项核对 |
| 3 | 序列化约定 | PASS | 无新 ORM/API 响应 |
| 4 | 数据库约定 | PASS | 按任务适用项核对 |
| 5 | 前端约定 | N/A | 无前端变更 |
| 6 | 信息泄漏 | PASS | 按任务适用项核对 |
| 7 | 设计同步 | PASS | 按任务适用项核对 |

**元数据验证**：文件范围 PASS | 配对测试 PASS | 依赖 PASS。
**结果**：PASS

## Task Review: T004

**任务**：事务后输出覆盖。
**类型**：测试
**文件**：`src/backend/test/eplus/test_terminal_metrics.py`

| # | 检查项 | 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | 架构分层 | N/A | 正式 SQLite 事务与 Service/Repository，未 mock 核心业务变更。 |
| 2 | 命名规范 | PASS | 按任务适用项核对 |
| 3 | 序列化约定 | N/A | 无新 ORM/API 响应 |
| 4 | 数据库约定 | N/A | 按任务适用项核对 |
| 5 | 前端约定 | N/A | 无前端变更 |
| 6 | 信息泄漏 | N/A | 按任务适用项核对 |
| 7 | 设计同步 | N/A | 按任务适用项核对 |

**元数据验证**：文件范围 PASS | 配对测试 N/A | 依赖 PASS。
**结果**：PASS

## Task Review: T005

**任务**：Repository 快照与提交观察。
**类型**：后端 Domain
**文件**：`src/backend/bisheng/eplus/domain/repositories/eplus_repository.py`；`src/backend/bisheng/eplus/domain/services/metric_observer.py`

| # | 检查项 | 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | 架构分层 | PASS | LEFT JOIN 复用消息行并保留缺失行原异常；事务快照提交后取出，回滚丢弃。 |
| 2 | 命名规范 | PASS | 按任务适用项核对 |
| 3 | 序列化约定 | PASS | 无新 ORM/API 响应 |
| 4 | 数据库约定 | PASS | 按任务适用项核对 |
| 5 | 前端约定 | N/A | 无前端变更 |
| 6 | 信息泄漏 | PASS | 按任务适用项核对 |
| 7 | 设计同步 | PASS | 按任务适用项核对 |

**元数据验证**：文件范围 PASS | 配对测试 PASS | 依赖 PASS。
**结果**：PASS

## Task Review: T006

**任务**：准入和调度接线。
**类型**：后端 Domain
**文件**：`src/backend/bisheng/eplus/domain/services/message_service.py`；`src/backend/bisheng/eplus/domain/services/conversation_scheduler.py`

| # | 检查项 | 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | 架构分层 | PASS | 保持既有返回和事务边界；重复观察在已有 commit 后，Service 不加 SQL。 |
| 2 | 命名规范 | PASS | 按任务适用项核对 |
| 3 | 序列化约定 | PASS | 无新 ORM/API 响应 |
| 4 | 数据库约定 | PASS | 按任务适用项核对 |
| 5 | 前端约定 | N/A | 无前端变更 |
| 6 | 信息泄漏 | PASS | 按任务适用项核对 |
| 7 | 设计同步 | PASS | 按任务适用项核对 |

**元数据验证**：文件范围 PASS | 配对测试 PASS | 依赖 PASS。
**结果**：PASS

## Task Review: T007

**任务**：连接生命周期指标测试。
**类型**：测试
**文件**：`src/backend/test/eplus/test_connection_metrics.py`；`src/backend/test/eplus/test_eplus_connection_supervisor.py`

| # | 检查项 | 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | 架构分层 | N/A | 租约/关闭后迟到心跳/协议认证拒绝和诊断失败覆盖；既有测试等待真实认证。 |
| 2 | 命名规范 | PASS | 按任务适用项核对 |
| 3 | 序列化约定 | N/A | 无新 ORM/API 响应 |
| 4 | 数据库约定 | N/A | 按任务适用项核对 |
| 5 | 前端约定 | N/A | 无前端变更 |
| 6 | 信息泄漏 | N/A | 按任务适用项核对 |
| 7 | 设计同步 | N/A | 按任务适用项核对 |

**元数据验证**：文件范围 PASS | 配对测试 N/A | 依赖 PASS。
**结果**：PASS

## Task Review: T008

**任务**：连接观察器接线。
**类型**：Worker
**文件**：`src/backend/bisheng/eplus/infrastructure/connection_client.py`；`src/backend/bisheng/eplus/infrastructure/connection_supervisor.py`

| # | 检查项 | 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | 架构分层 | PASS | 连接观察器异常隔离；ensure_owned 不新增 Redis；无重复接管或结束后存活。 |
| 2 | 命名规范 | N/A | 按任务适用项核对 |
| 3 | 序列化约定 | N/A | 无新 ORM/API 响应 |
| 4 | 数据库约定 | PASS | 按任务适用项核对 |
| 5 | 前端约定 | N/A | 无前端变更 |
| 6 | 信息泄漏 | PASS | 按任务适用项核对 |
| 7 | 设计同步 | PASS | 按任务适用项核对 |

**元数据验证**：文件范围 PASS | 配对测试 N/A | 依赖 PASS。
**结果**：PASS

## Task Review: T009

**任务**：正式 Worker 输出接线。
**类型**：Worker
**文件**：`src/backend/bisheng/eplus/worker.py`

| # | 检查项 | 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | 架构分层 | PASS | 仅正式 build 注入；ref.tenant_id 与既有 _tenant_scope，未新增 Celery 任务。 |
| 2 | 命名规范 | N/A | 按任务适用项核对 |
| 3 | 序列化约定 | N/A | 无新 ORM/API 响应 |
| 4 | 数据库约定 | PASS | 按任务适用项核对 |
| 5 | 前端约定 | N/A | 无前端变更 |
| 6 | 信息泄漏 | PASS | 按任务适用项核对 |
| 7 | 设计同步 | PASS | 按任务适用项核对 |

**元数据验证**：文件范围 PASS | 配对测试 N/A | 依赖 PASS。
**结果**：PASS

## Task Review: T010

**任务**：分片配置与创建测试。
**类型**：测试
**文件**：`src/backend/test/channel/test_article_index_settings.py`

| # | 检查项 | 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | 架构分层 | N/A | 非法值、默认 3、自定义、同步异步和已有实体零创建覆盖。 |
| 2 | 命名规范 | PASS | 按任务适用项核对 |
| 3 | 序列化约定 | N/A | 无新 ORM/API 响应 |
| 4 | 数据库约定 | N/A | 按任务适用项核对 |
| 5 | 前端约定 | N/A | 无前端变更 |
| 6 | 信息泄漏 | N/A | 按任务适用项核对 |
| 7 | 设计同步 | N/A | 按任务适用项核对 |

**元数据验证**：文件范围 PASS | 配对测试 N/A | 依赖 PASS。
**结果**：PASS

## Task Review: T011

**任务**：索引配置构造。
**类型**：后端 Domain
**文件**：`src/backend/bisheng/channel/domain/es/article_index.py`

| # | 检查项 | 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | 架构分层 | PASS | 深复制基础 settings；仅新建注入分片，逻辑名称保持 channel_articles。 |
| 2 | 命名规范 | PASS | 按任务适用项核对 |
| 3 | 序列化约定 | PASS | 无新 ORM/API 响应 |
| 4 | 数据库约定 | PASS | 按任务适用项核对 |
| 5 | 前端约定 | N/A | 无前端变更 |
| 6 | 信息泄漏 | PASS | 按任务适用项核对 |
| 7 | 设计同步 | PASS | 按任务适用项核对 |

**元数据验证**：文件范围 PASS | 配对测试 PASS | 依赖 PASS。
**结果**：PASS

## Task Review: T012

**任务**：迁移规划及指纹测试。
**类型**：测试
**文件**：`src/backend/test/channel/test_article_reshard_plan.py`

| # | 检查项 | 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | 架构分层 | N/A | 复制策略、pipeline/routing、完整指纹与安全名称测试。 |
| 2 | 命名规范 | PASS | 按任务适用项核对 |
| 3 | 序列化约定 | N/A | 无新 ORM/API 响应 |
| 4 | 数据库约定 | N/A | 按任务适用项核对 |
| 5 | 前端约定 | N/A | 无前端变更 |
| 6 | 信息泄漏 | N/A | 按任务适用项核对 |
| 7 | 设计同步 | N/A | 按任务适用项核对 |

**元数据验证**：文件范围 PASS | 配对测试 N/A | 依赖 PASS。
**结果**：PASS

## Task Review: T013

**任务**：迁移规划/核验模块。
**类型**：后端 Domain
**文件**：`src/backend/scripts/article_reshard_plan.py`

| # | 检查项 | 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | 架构分层 | PASS | 固定文章范围；完整扫描每批 500；异常拒绝切换。 |
| 2 | 命名规范 | PASS | 按任务适用项核对 |
| 3 | 序列化约定 | PASS | 无新 ORM/API 响应 |
| 4 | 数据库约定 | PASS | 按任务适用项核对 |
| 5 | 前端约定 | N/A | 无前端变更 |
| 6 | 信息泄漏 | PASS | 按任务适用项核对 |
| 7 | 设计同步 | PASS | 按任务适用项核对 |

**元数据验证**：文件范围 PASS | 配对测试 PASS | 依赖 PASS。
**结果**：PASS

## Task Review: T014

**任务**：迁移状态机故障测试。
**类型**：测试
**文件**：`src/backend/test/channel/test_repartition_channel_articles.py`；`src/backend/test/channel/article_reshard_fake.py`

| # | 检查项 | 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | 架构分层 | N/A | 可观察 ES double 断言零写、容量/冲突/复制/内容/切换/最终 ack 失败边界。 |
| 2 | 命名规范 | PASS | 按任务适用项核对 |
| 3 | 序列化约定 | N/A | 无新 ORM/API 响应 |
| 4 | 数据库约定 | N/A | 按任务适用项核对 |
| 5 | 前端约定 | N/A | 无前端变更 |
| 6 | 信息泄漏 | N/A | 按任务适用项核对 |
| 7 | 设计同步 | N/A | 按任务适用项核对 |

**元数据验证**：文件范围 PASS | 配对测试 N/A | 依赖 PASS。
**结果**：PASS

## Task Review: T015

**任务**：迁移状态机。
**类型**：后端 Domain
**文件**：`src/backend/scripts/article_reshard_runtime.py`

| # | 检查项 | 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | 架构分层 | PASS | 原子备份预留、屏障刷新、独立核验后切换；不自动重放、恢复或清理。 |
| 2 | 命名规范 | PASS | 按任务适用项核对 |
| 3 | 序列化约定 | PASS | 无新 ORM/API 响应 |
| 4 | 数据库约定 | PASS | 按任务适用项核对 |
| 5 | 前端约定 | N/A | 无前端变更 |
| 6 | 信息泄漏 | PASS | 按任务适用项核对 |
| 7 | 设计同步 | PASS | 按任务适用项核对 |

**元数据验证**：文件范围 PASS | 配对测试 PASS | 依赖 PASS。
**结果**：PASS

## Task Review: T016

**任务**：迁移 CLI 与双 ES 配置测试。
**类型**：测试
**文件**：`src/backend/test/channel/test_article_reshard_cli.py`

| # | 检查项 | 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | 架构分层 | N/A | 参数互斥、共享配置、init/close、业务与统计 ES 差异测试。 |
| 2 | 命名规范 | PASS | 按任务适用项核对 |
| 3 | 序列化约定 | N/A | 无新 ORM/API 响应 |
| 4 | 数据库约定 | N/A | 按任务适用项核对 |
| 5 | 前端约定 | N/A | 无前端变更 |
| 6 | 信息泄漏 | N/A | 按任务适用项核对 |
| 7 | 设计同步 | N/A | 按任务适用项核对 |

**元数据验证**：文件范围 PASS | 配对测试 N/A | 依赖 PASS。
**结果**：PASS

## Task Review: T017

**任务**：脚本入口与帮助。
**类型**：后端 Domain
**文件**：`src/backend/scripts/repartition_channel_articles.py`；`src/backend/scripts/README.md`

| # | 检查项 | 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | 架构分层 | PASS | argparse/bootstrap；共享 settings/app context，默认 dry-run，README 恢复完整。 |
| 2 | 命名规范 | PASS | 按任务适用项核对 |
| 3 | 序列化约定 | PASS | 无新 ORM/API 响应 |
| 4 | 数据库约定 | PASS | 按任务适用项核对 |
| 5 | 前端约定 | N/A | 无前端变更 |
| 6 | 信息泄漏 | PASS | 按任务适用项核对 |
| 7 | 设计同步 | PASS | 按任务适用项核对 |

**元数据验证**：文件范围 PASS | 配对测试 PASS | 依赖 PASS。
**结果**：PASS

## Task Review: T018

**任务**：端到端演练入口。
**类型**：测试
**文件**：`src/backend/test/e2e/test_e2e_cofco_article_shards.py`；`features/v3.0.0-beta1/078-cofco-eplus-metrics-article-shards/e2e-checklist.md`

| # | 检查项 | 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | 架构分层 | N/A | 真实 ES 8.12.2 三项演练；无 HTTP/UI；客户 E+、双数据库、多节点待验单列。 |
| 2 | 命名规范 | PASS | 按任务适用项核对 |
| 3 | 序列化约定 | N/A | 无新 ORM/API 响应 |
| 4 | 数据库约定 | N/A | 按任务适用项核对 |
| 5 | 前端约定 | N/A | 无前端变更 |
| 6 | 信息泄漏 | N/A | 按任务适用项核对 |
| 7 | 设计同步 | N/A | 按任务适用项核对 |

**元数据验证**：文件范围 PASS | 配对测试 N/A | 依赖 PASS。
**结果**：PASS_WITH_NOTES（环境待验见 e2e-checklist.md）

## Task Review: T019

**任务**：日志合同及部署配置示例。
**类型**：文档
**文件**：`docs/observability/metric-log-contract.md`；`docker/bisheng/config/config.yaml`

| # | 检查项 | 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | 架构分层 | PASS | 日志合同只追加；去重分母/窗口、90 秒过期与部署分片配置同步。 |
| 2 | 命名规范 | PASS | 按任务适用项核对 |
| 3 | 序列化约定 | PASS | 无新 ORM/API 响应 |
| 4 | 数据库约定 | PASS | 按任务适用项核对 |
| 5 | 前端约定 | N/A | 无前端变更 |
| 6 | 信息泄漏 | PASS | 按任务适用项核对 |
| 7 | 设计同步 | PASS | 按任务适用项核对 |

**元数据验证**：文件范围 PASS | 配对测试 PASS | 依赖 PASS。
**结果**：PASS

## Task Review: T020

**任务**：全量定向回归与评审。
**类型**：验证
**文件**：`features/v3.0.0-beta1/078-cofco-eplus-metrics-article-shards/validation.md`；`features/v3.0.0-beta1/078-cofco-eplus-metrics-article-shards/code-review.md`

| # | 检查项 | 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | 架构分层 | PASS | Ruff/arch-guard/diff 与定向回归；七维度审查及证据边界记录。 |
| 2 | 命名规范 | PASS | 按任务适用项核对 |
| 3 | 序列化约定 | PASS | 无新 ORM/API 响应 |
| 4 | 数据库约定 | PASS | 按任务适用项核对 |
| 5 | 前端约定 | N/A | 无前端变更 |
| 6 | 信息泄漏 | PASS | 按任务适用项核对 |
| 7 | 设计同步 | PASS | 按任务适用项核对 |

**元数据验证**：文件范围 PASS | 配对测试 PASS | 依赖 PASS。
**结果**：PASS_WITH_NOTES（环境待验见 e2e-checklist.md）
