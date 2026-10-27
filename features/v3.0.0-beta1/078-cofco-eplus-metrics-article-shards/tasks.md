# Tasks: F078 E+ 事件指标与频道文章主分片迁移

**关联规格**：[spec.md](./spec.md) · [design.md](./design.md)
**状态**：Spec/Design 均已由用户确认；实现及本地验证已完成，客户/中央环境待验项见 e2e-checklist.md。

| 步骤 | 状态 |
| --- | --- |
| Spec | 已确认 |
| Design | 已确认 |
| Tasks | 已完成 |
| 实现 | 完成，已获用户交付授权 |

## Wave 1：配置、终态与连接

- [x] **T001**（基础设施）：配置与域开关。
  **文件**：`src/backend/bisheng/core/config/settings.py`；`src/backend/bisheng/common/services/metric_log.py`
  **逻辑**：注册严格正整数分片配置与存活过期配置，新增两个域映射到 eplus 开关。
  **依赖**：无

- [x] **T002**（测试）：终态字段与脱敏测试。
  **文件**：`src/backend/test/metric_log/test_robot_events.py`
  **逻辑**：验证完整终态、结果分类、稳定用户标识、敏感字段排除、开关与观察器异常。
  **依赖**：T001
  **覆盖 AC**：AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-10, AC-11, AC-12, AC-13

- [x] **T003**（后端 Domain）：只读快照与事件输出。
  **文件**：`src/backend/bisheng/eplus/domain/schemas/metric.py`；`src/backend/bisheng/eplus/infrastructure/metric_events.py`
  **逻辑**：不可变快照及输出器，不持久化统计、不聚合；连接输出器拒绝无租约存活。
  **依赖**：T002

- [x] **T004**（测试）：事务后输出覆盖。
  **文件**：`src/backend/test/eplus/test_terminal_metrics.py`
  **逻辑**：基于 SQLite 与正式 Repository 验证提交/回滚、拒绝、繁忙、正常完成、超时及恢复终态。
  **依赖**：T003
  **覆盖 AC**：AC-01, AC-02, AC-03, AC-05, AC-11, AC-12

- [x] **T005**（后端 Domain）：Repository 快照与提交观察。
  **文件**：`src/backend/bisheng/eplus/domain/repositories/eplus_repository.py`；`src/backend/bisheng/eplus/domain/services/metric_observer.py`
  **逻辑**：复用现有业务读取构造快照，事务内短期缓冲、提交后才通知；不新增统计 SQL 或数据写入。
  **依赖**：T004

- [x] **T006**（后端 Domain）：准入和调度接线。
  **文件**：`src/backend/bisheng/eplus/domain/services/message_service.py`；`src/backend/bisheng/eplus/domain/services/conversation_scheduler.py`
  **逻辑**：注入可选观察器；拒绝、重复、完成、超时和恢复均经提交后输出。
  **依赖**：T005

- [x] **T007**（测试）：连接生命周期指标测试。
  **文件**：`src/backend/test/eplus/test_connection_metrics.py`；`src/backend/test/eplus/test_eplus_connection_supervisor.py`
  **逻辑**：租约有效、认证/心跳/关闭、异常退出、开关、序号和过期字段；复用本地 WebSocket 协议测试。
  **依赖**：T003
  **覆盖 AC**：AC-07, AC-08, AC-09, AC-10, AC-11, AC-12

- [x] **T008**（Worker）：连接观察器接线。
  **文件**：`src/backend/bisheng/eplus/infrastructure/connection_client.py`；`src/backend/bisheng/eplus/infrastructure/connection_supervisor.py`
  **逻辑**：每次连接绑定租约观察回调；finally 记录结束，只有认证及成功心跳宣告存活。沿用 ref.tenant_id 与 Worker _tenant_scope ContextVar；无 Celery 新任务。
  **依赖**：T007

- [x] **T009**（Worker）：正式 Worker 输出接线。
  **文件**：`src/backend/bisheng/eplus/worker.py`
  **逻辑**：仅正式 build_worker_runtime 注入指标；通过 ref 的 tenant_id 及既有 _tenant_scope 恢复上下文，debug 默认不输出。
  **依赖**：T006、T008

## Wave 2：文章配置与维护脚本

- [x] **T010**（测试）：分片配置与创建测试。
  **文件**：`src/backend/test/channel/test_article_index_settings.py`
  **逻辑**：默认 3、自定义、非法类型、同步异步创建、已有实体零重建。
  **依赖**：T001
  **覆盖 AC**：AC-14, AC-15, AC-16, AC-17

- [x] **T011**（后端 Domain）：索引配置构造。
  **文件**：`src/backend/bisheng/channel/domain/es/article_index.py`
  **逻辑**：深复制基础 settings 并注入共享配置；同步异步共用构造函数。
  **依赖**：T010

- [x] **T012**（测试）：迁移规划及指纹测试。
  **文件**：`src/backend/test/channel/test_article_reshard_plan.py`
  **逻辑**：测试 settings 复制、pipeline、routing、指纹和模板/源解析失败边界。
  **依赖**：T011
  **覆盖 AC**：AC-18, AC-19, AC-20, AC-22, AC-23, AC-24

- [x] **T013**（后端 Domain）：迁移规划/核验模块。
  **文件**：`src/backend/scripts/article_reshard_plan.py`
  **逻辑**：只读源解析、配置净化、metadata 与有界全量指纹；不访问其他业务索引。
  **依赖**：T012

- [x] **T014**（测试）：迁移状态机故障测试。
  **文件**：`src/backend/test/channel/test_repartition_channel_articles.py`；`src/backend/test/channel/article_reshard_fake.py`
  **逻辑**：可观察 fake ES 演练真实编排：屏障/刷新顺序、恢复副本、task 失败、内容不一致、切换不明、冲突重试与已达标零写。
  **依赖**：T013
  **覆盖 AC**：AC-19, AC-20, AC-21, AC-22, AC-23, AC-24, AC-25, AC-26

- [x] **T015**（后端 Domain）：迁移状态机。
  **文件**：`src/backend/scripts/article_reshard_runtime.py`
  **逻辑**：原子预留恢复实体、停写屏障、refresh、reindex、核验、aliases 切换与后验检查；记录共享 ES _meta 并保留失败现场。
  **依赖**：T014

- [x] **T016**（测试）：迁移 CLI 与双 ES 配置测试。
  **文件**：`src/backend/test/channel/test_article_reshard_cli.py`
  **逻辑**：验证共享 settings/default connection、参数/退出码、dry-run 零写、完整初始化与清理。
  **依赖**：T015
  **覆盖 AC**：AC-18, AC-19, AC-20, AC-25, AC-27

- [x] **T017**（后端 Domain）：脚本入口与帮助。
  **文件**：`src/backend/scripts/repartition_channel_articles.py`；`src/backend/scripts/README.md`
  **逻辑**：路径 bootstrap、argparse、initialize/close、机器可读摘要与完整运维恢复说明。
  **依赖**：T016

## Wave 3：交付验证

- [x] **T018**（测试）：端到端演练入口。
  **文件**：`src/backend/test/e2e/test_e2e_cofco_article_shards.py`；`features/v3.0.0-beta1/078-cofco-eplus-metrics-article-shards/e2e-checklist.md`
  **逻辑**：生成真实 ES 8.x 环境可运行的隔离演练：停刷新新增/更新/删除，迁移后读写及回退；记录真实 E+ 双 Worker/DM8 未执行项。
  **依赖**：T009、T017
  **覆盖 AC**：AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-24, AC-25, AC-26, AC-27

- [x] **T019**（文档）：日志合同及部署配置示例。
  **文件**：`docs/observability/metric-log-contract.md`；`docker/bisheng/config/config.yaml`
  **逻辑**：字段、公式、过期规则、仅终态消费样例与默认分片配置，保持已有域合同。
  **依赖**：T009、T011

- [x] **T020**（验证）：全量定向回归与评审。
  **文件**：`features/v3.0.0-beta1/078-cofco-eplus-metrics-article-shards/validation.md`；`features/v3.0.0-beta1/078-cofco-eplus-metrics-article-shards/code-review.md`
  **逻辑**：运行定向测试、Ruff/arch-guard/diff 检查并按七维度审查未提交差异；真实中间件证据与模拟测试明确区分。
  **依赖**：T018、T019

## 实际偏差记录

- T005：只读快照用当前事务的 session.info 作短期缓冲，提交后输出；不新增查询或持久状态。Design §4.2 同步此实现细节。

- T007：既有 supervisor 测试改为等待 AUTHENTICATED，修正把“client 已创建”当作“认证已完成”的异步竞态；不改业务行为。
- T014：增加可观察 ES double 独立文件，断言真实编排的故障边界；未将 fake 结果当真实 ES 验收。
- T018：无新增 HTTP/UI；真实演练直接调用维护编排及专用 ES，不创建应用租户或触碰正式业务集群。真实 E+ 双 Worker、MySQL/DM8 与生产验收保持待执行。

逐任务 L1 审查见 [task-review.md](./task-review.md)，最终七维度审查见 [code-review.md](./code-review.md)。
