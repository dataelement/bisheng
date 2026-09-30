# 实施复盘 Retrospective：Celery 异步运行时单循环收敛

## 故障与根因

文件编码通过私有 `shougang-encoding-async` 运行异步配置、Redis 和数据库逻辑；相似度刷新通过 Celery 公共 `bisheng-celery-async` 运行。两个循环复用进程级单一异步 Redis 连接后，Redis Future 被第二个循环使用，触发 `Future attached to a different loop`。

数据库回滚是异常传播后的结果，不是 SQL 或数据库连接本身的直接根因。

## 实际实现

- 通用 `run_async_safe()` 增加 preferred bridge loop 注册能力。
- Celery `get_worker_loop()` 注册公共循环，Worker shutdown 时解除注册。
- 普通同步调用使用惰性、持久 fallback loop，避免连续调用把全局异步资源绑定到已关闭短循环。
- 文件编码删除私有 `_AsyncRunner`，保留 120 秒超时、warning 和 best-effort 返回语义。
- 知识空间迁移删除 `asyncio.run()`，改为 `run_async_safe(..., timeout=None)`。
- 增加单循环、loop-bound resource、并发 ContextVar、异常传播、fallback、shutdown、文件编码和空间迁移回归测试。

## 与设计的偏差

1. 空间迁移最初考虑直接调用 Worker 私有 `run_async_task()`，最终使用通用 `run_async_safe(..., timeout=None)`。这样避免 `knowledge → worker` 直接依赖；在 Celery 进程中仍由 preferred loop 路由到公共循环。
2. 通用非 Worker fallback 从原先每次 `asyncio.run()` 调整为进程级持久后台循环。这是文件编码接入通用 bridge 后发现的兼容性必要条件，并增加了连续复用 loop-bound resource 的回归测试。

两项偏差均已同步到 requirements、design 和 tasks，不扩展业务范围。

## 影响与风险

- 无 API、任务名、任务参数、配置、数据库结构、Redis key/TTL 或文件解析结果契约变化。
- Worker 进程中受管同步转异步任务会共享一个异步循环；耗时异步任务仍由现有协程并发模型调度。
- Redis 多事件循环客户端隔离仍未实现，后续新增 Worker 私有循环仍会重新引入同类风险。
- 当前自动化验证不包含真实 Redis/MySQL/MinIO 的端到端写入链路。

## 回滚方式

本 Feature 不含数据库或缓存迁移，可整体回滚对应 Python 代码和测试提交。回滚会恢复旧的多循环行为，因此只应作为紧急操作，并同步停止相关知识队列或降低任务并发，避免继续触发跨循环故障。

## 后续事项

- 发布前完成 `verification.md` 中的真实 Worker 冒烟。
- 灰度观察 `different loop`、`Event loop is closed`、知识解析失败率和任务耗时。
- 后续独立评估 Redis async client 的 loop-local 防御，不与本次最小修复混合。
- 合并包含历史提交 `96de66314` 的分支时，重点处理 preferred bridge loop 的重复实现冲突。
