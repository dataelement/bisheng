# Feature: Celery 异步运行时单循环收敛

**Feature ID**: `056-celery-async-runtime`  
**Status**: Implemented / Automated Verification Passed  
**Mode**: Bug Fix / Runtime Hardening  
**Created**: 2026-07-15  
**Updated**: 2026-07-15  
**优先级**: P0  
**所属版本**: v2.6.0

## 1. 概述

知识文件解析过程中，`FileEncodingTransformer` 使用私有事件循环执行异步 Redis、数据库和 LLM 调用；解析完成后的相似度刷新任务则使用 Celery 公共事件循环。两条路径共享同一个进程级异步 Redis 客户端，导致连接在一个事件循环创建后被另一个事件循环复用，触发 `Future attached to a different loop`。

本 Feature 将 Celery 进程中的同步转异步入口汇聚到已有 `bisheng-celery-async` 事件循环，删除文件编码私有事件循环，并清理知识空间迁移任务中的临时 `asyncio.run()`。不新增第二套 Celery 执行器，不改变业务算法、API、配置或数据结构。

详细需求与设计见：

- [requirements.md](./requirements.md)
- [design.md](./design.md)
- [tasks.md](./tasks.md)

## 2. 故障事实

- 文件 `4540` 的 `parse_knowledge_file_celery` 成功完成。
- 随后的 `refresh_file_similarity_candidates_celery` 在读取 `config:initdb_config` Redis 缓存时失败。
- 异常为 `RuntimeError: ... got Future <Future pending> attached to a different loop`。
- 回滚发生在异步数据库 Session 边界，但根因是 Redis Stream/Future 绑定了另一个事件循环，并非数据库 SQL 失败。

## 3. 目标

- Celery 进程中所有受本 Feature 管理的同步转异步调用共享 `bisheng-celery-async`。
- 文件编码后执行相似度刷新时，不再发生跨事件循环 Redis Future 错误。
- 保留租户、Trace 等 `ContextVar`。
- 保留文件编码 120 秒超时和现有 best-effort 行为。
- Worker 关闭时解除公共桥接循环注册。
- 删除本次涉及路径中的私有事件循环和临时 `asyncio.run()`。

## 4. 非目标

- 不改造 Redis 为按事件循环维护多个异步连接池。
- 不在本 Feature 引入 `SimilarityPolicy` 配置快照。
- 不重写相似度、TF-IDF、文件编码或空间迁移业务逻辑。
- 不修改 Celery 队列、并发数或 `-P threads` 部署方式。
- 不新增数据库表、迁移、API、前端或配置项。
- 不自动重跑历史失败任务。

## 5. 核心验收摘要

| ID | 场景 | 预期结果 |
|---|---|---|
| AC-01 | 文件编码异步逻辑后执行相似度异步逻辑 | 两者运行在同一个 Celery 事件循环，不发生跨循环错误 |
| AC-02 | 多个 Celery 工作线程并发提交 | 共享同一事件循环，返回值和异常保持隔离 |
| AC-03 | 调用线程设置 tenant/trace ContextVar | 协程读取到对应调用线程的值，不串租户 |
| AC-04 | 文件编码超过 120 秒或内部异常 | 保持现有超时、日志和 best-effort 返回语义 |
| AC-05 | Worker 关闭 | 公共桥接循环解除注册，不再接收后续桥接调用 |
| AC-06 | 知识空间迁移执行异步删除 | 使用 Celery 公共循环，不创建临时事件循环 |

稳定追踪 ID 和验证方式以 [requirements.md](./requirements.md) 为准。

## 6. 架构决策摘要

| ID | 决策 | 结论 |
|---|---|---|
| AD-01 | 新建执行器还是复用现有 Worker Loop | 复用 `worker/_asyncio_utils.py` 中的持久循环 |
| AD-02 | 知识模块是否直接依赖 Worker 模块 | 不直接依赖；通过通用 `utils.async_utils` 桥接 |
| AD-03 | 是否只改相似度配置为同步 Redis | 不采用；TF-IDF 等路径仍使用异步 Redis，不能消除根因 |
| AD-04 | 是否本次改造 Redis 多循环连接池 | 延后为独立基础设施 Feature，控制回归范围 |
| AD-05 | 是否直接 cherry-pick 其他分支历史提交 | 不采用；仅移植与当前分支兼容的桥接设计及专项测试 |

## 7. 影响范围

- 影响 Celery Worker 的同步转异步桥接、文件编码 Transformer、相似度刷新前置资源归属和知识空间迁移异步删除。
- 不影响 FastAPI 异步接口自身的事件循环；没有 Worker 注册时继续走现有非 Worker 行为。
- 不影响 Redis key、缓存 TTL、数据库事务语义、MinIO、ETL4LM 图片或 bbox。
- 不改变文件解析成功/失败状态规则。

## 8. 发布与回滚

- 先运行无 Redis/数据库依赖的事件循环回归测试，再进行本地 Redis/MySQL Worker 冒烟。
- 优先灰度 `knowledge_celery` 队列，观察 `different loop`、`Event loop is closed`、任务耗时和失败率。
- 代码变更不包含数据迁移；出现异常时可整体回滚本 Feature 提交。
- 历史失败的相似度任务需人工重试，本 Feature 不自动补偿。

## 9. 当前状态

- Spec Discovery：已完成并获得开始实施确认。
- `requirements.md`：已确认。
- `design.md`：已确认。
- `tasks.md`：T001-T006 已完成。
- 生产代码：已完成最小范围实现，专项与相关回归合计 46 passed。
- 静态验证：F/I、格式、compileall、架构守卫、source scan 和差异检查通过；完整 Ruff 的 16 项既有债务已记录。
- 发布前验证：真实 Redis/MySQL Worker 冒烟仍需在可控测试环境执行。

## 相关文档

- [v2.6.0 Release Contract](../release-contract.md)
