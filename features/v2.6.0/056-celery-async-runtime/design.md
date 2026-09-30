# 设计 Design：Celery 异步运行时单循环收敛

## 阅读摘要

- 本设计复用现有 `bisheng-celery-async`，通过通用同步转异步工具注册首选 bridge loop，使文件编码和相似度刷新共享同一事件循环。
- 设计重点是最小改动、ContextVar 保持、Worker 生命周期和跨循环回归测试。
- Redis 多循环连接池、相似度配置快照、prefork/PID 防护不在本设计中处理。

## 元信息 Metadata

- Feature ID: `056-celery-async-runtime`
- Status: `confirmed`
- Related requirements: `features/v2.6.0/056-celery-async-runtime/requirements.md`
- Created: `2026-07-15`
- Updated: `2026-07-15`

## 上下文 Context

### 当前架构

```text
Celery task thread
  ├─ run_async_task() → bisheng-celery-async
  │    └─ refresh similarity → async Redis/DB
  └─ KnowledgeFilePipeline.run()
       └─ FileEncodingTransformer
            └─ _AsyncRunner → shougang-encoding-async
                 └─ async Redis/DB/LLM
```

`RedisClient` 由全局 `RedisManager` 管理，同时包含同步连接和单一异步连接。异步 Redis Stream/Future 绑定第一次使用它的事件循环，因此两个长期循环不能安全复用同一异步连接。

### 已检查文件

- `src/backend/bisheng/worker/_asyncio_utils.py`
- `src/backend/bisheng/worker/main.py`
- `src/backend/bisheng/utils/async_utils.py`
- `src/backend/bisheng/knowledge/rag/pipeline/transformer/file_encoding.py`
- `src/backend/bisheng/worker/knowledge/file_worker.py`
- `src/backend/bisheng/worker/knowledge/space_migrate_worker.py`
- `src/backend/bisheng/common/services/config_service.py`
- `src/backend/bisheng/core/cache/redis_conn.py`
- `src/backend/bisheng/core/database/connection.py`
- `src/backend/bisheng/knowledge/domain/services/knowledge_version_service.py`
- 用户提供的故障日志。

### 项目约束

- Celery 使用 `-P threads`，知识队列并发为 20。
- 新测试放在 `src/backend/test/<module>/`，不放 `test/` 根目录。
- 必须保留 tenant ContextVar 自动隔离。
- 不得吞掉关键异常；文件编码现有 best-effort 异常边界保持不变。
- 不新增数据库、配置或数据变更。

## 目标 / 非目标 Goals / Non-Goals

### 目标 Goals

- 一个 Celery 进程内受管 sync→async 入口只使用 `bisheng-celery-async`。
- 删除文件编码私有循环并保留 120 秒超时。
- 清理空间迁移 Worker 的 `asyncio.run()`。
- 保留 FastAPI AnyIO 行为；普通同步脚本使用进程级持久后台循环，避免短循环关闭后污染全局异步资源。
- 使用不依赖真实中间件的测试证明跨循环错误被修复。

### 非目标 Non-Goals

- 不创建新的 `ProcessAsyncExecutor`；现有 `run_async_task()` 已承担该职责。
- 不改变 Redis、数据库、HTTP 或 OpenFGA Manager 的资源模型。
- 不扩大到所有业务模块的异步入口治理。
- 不调整相似度算法或配置读取方式。

## 边界承诺 Boundary Commitments

| Boundary | Allowed Change | Disallowed Change | Revalidation Trigger |
|---|---|---|---|
| Worker runtime | 注册/解除首选 bridge loop | 改队列、并发、任务名或参数 | 改用 prefork/gevent/eventlet |
| Async utility | Worker 首选循环路由、上下文和超时保持 | 修改 FastAPI async API 或新增依赖 | AnyIO 行为变化 |
| File encoding | 删除私有 runner，改用通用桥接 | 修改编码算法、提示词、数据库写入语义 | 分类或编码规则变化 |
| Similarity | 仅作为回归调用方验证 | 修改 SimHash/TF-IDF/候选写入 | 算法或配置变化 |
| Space migration | 替换 `asyncio.run()` 调度方式 | 修改复制、删除、回滚业务逻辑 | 迁移状态语义变化 |
| Redis | 不修改 | 不新增多 loop clients/连接池策略 | 决定实施 Redis loop-local hardening |

- Allowed dependencies: none。

## 需求追踪 Requirements Traceability

| Requirement | Acceptance Criteria | Design Element | Verification Strategy |
|---|---|---|---|
| REQ-001 | AC-REQ-001-01..03 | preferred bridge loop + existing worker loop | loop-bound fake resource 与多线程测试 |
| REQ-002 | AC-REQ-002-01..04 | ContextVar/timeout/exception 兼容 | ContextVar、异常、超时、AnyIO 回归测试 |
| REQ-003 | AC-REQ-003-01..04 | Worker register/unregister、移除私有 runner、迁移任务改造 | 生命周期、Transformer、迁移 Worker 测试 |
| REQ-004 | AC-REQ-004-01..03 | 最小文件范围、无 schema/config/API 变更 | diff review、相关回归和回滚审查 |

## 架构设计 Architecture

### 目标链路

```text
Celery task thread A ─┐
Celery task thread B ─┼─ sync→async bridge ─→ bisheng-celery-async
Celery task thread N ─┘                           ├─ async Redis
                                                 ├─ async DB
                                                 └─ async HTTP/LLM/OpenFGA
```

### Pattern

- Pattern: process-wide preferred bridge loop。
- Rationale: 当前 Worker 已有持久事件循环和 ContextVar 传播能力，新增第二个执行器只会重复生命周期和异常处理，并再次产生资源归属歧义。
- Preserved existing patterns: `run_async_task(coro_factory)` 继续作为 Celery task 直接提交入口；`run_async_safe(coro, timeout=...)` 继续作为通用同步调用入口。
- Architecture change justification: 仅增加两者之间的循环注册关系，使它们在 Worker 进程内汇聚；FastAPI/脚本没有注册时不受影响。

## 组件与接口 Components and Interfaces

### Preferred Bridge Loop Registry

位置：`bisheng/utils/async_utils.py`

建议接口：

```python
def set_preferred_bridge_loop(loop: asyncio.AbstractEventLoop | None) -> None:
    ...


def run_async_safe(
    coro: Awaitable[Any],
    *,
    timeout: float | None = 10,
) -> Any:
    ...
```

执行顺序：

1. 如果调用线程已有 running loop，保持现有保护并要求调用方直接 `await`。
2. 如果位于 AnyIO worker thread，保持现有 `anyio.from_thread.run()` 路径。
3. 如果注册了活动 Worker preferred loop，通过 thread-safe submission 提交到该循环。
4. 如果没有 Worker preferred loop，使用通用工具内部的进程级持久后台循环，不再为每次调用创建并关闭短循环。

提交必须保留当前调用线程 ContextVar；测试以 tenant/trace probe 证明。

后台 fallback 循环仅在普通同步进程首次调用时惰性创建。FastAPI AnyIO worker thread 会在步骤 2 返回，Celery 会在步骤 3 返回，因此两类服务进程不会误用该 fallback。

### Celery Worker Loop Registration

位置：`bisheng/worker/_asyncio_utils.py`、`bisheng/worker/main.py`

- `get_worker_loop()` 创建或取得活动循环后调用 `set_preferred_bridge_loop(loop)`。
- `worker_shutting_down` 调用 `set_preferred_bridge_loop(None)`。
- 不在本 Feature 重写 `run_async_task()` 调度、轮询和线程死亡处理。

### FileEncodingTransformer

位置：`bisheng/knowledge/rag/pipeline/transformer/file_encoding.py`

- 删除 `_AsyncRunner`、`_async_runner`、私有 `new_event_loop()` 和线程。
- `transform_documents()` 改为通过 `run_async_safe(self._do_work(), timeout=120.0)` 执行。
- 继续在当前 `try/except` 边界记录 warning 并返回输入 documents。
- 不改 `_do_work()` 及其业务子方法。

### Space Migration Worker

位置：`bisheng/worker/knowledge/space_migrate_worker.py`

- 将 `asyncio.run(_delete_source_space(...))` 改为 `run_async_safe(_delete_source_space(...), timeout=None)`；Worker 已注册 preferred loop 时仍提交到 `bisheng-celery-async`。
- 保持现有异常捕获、源知识空间状态回滚和返回字符串。

## 文件结构计划 File Structure Plan

### 新增

| Path | Action | Responsibility | Linked Requirement |
|---|---|---|---|
| `src/backend/test/celery/test_celery_async_runtime.py` | modify | 扩展现有 Celery runtime 测试，覆盖单循环、ContextVar、异常和生命周期回归 | REQ-001, REQ-002, REQ-003 |
| `src/backend/test/knowledge/test_file_encoding_async_bridge.py` | create | 文件编码桥接、超时/异常和无私有循环回归 | REQ-001, REQ-002, REQ-003 |
| `src/backend/test/knowledge/test_space_migrate_async_bridge.py` | create | 空间迁移通过通用 bridge 提交异步删除的回归 | REQ-003 |

### 修改

| Path | Action | Responsibility | Linked Requirement |
|---|---|---|---|
| `src/backend/bisheng/utils/async_utils.py` | modify | 支持 Worker 首选 bridge loop | REQ-001, REQ-002, REQ-004 |
| `src/backend/bisheng/worker/_asyncio_utils.py` | modify | 将 Worker 持久循环注册为首选 bridge loop | REQ-001, REQ-003 |
| `src/backend/bisheng/worker/main.py` | modify | Worker shutdown 时解除 bridge loop | REQ-003 |
| `src/backend/bisheng/knowledge/rag/pipeline/transformer/file_encoding.py` | modify | 删除私有循环并复用通用 bridge | REQ-001, REQ-002, REQ-003 |
| `src/backend/bisheng/worker/knowledge/space_migrate_worker.py` | modify | 清除临时 `asyncio.run()` | REQ-003 |

### 不修改

- `core/cache/redis_conn.py`
- `common/services/config_service.py`
- `knowledge/domain/services/knowledge_version_service.py`
- 数据库模型、Alembic、配置、API 和前端。

## 数据 / 状态变化 Data / State Changes

- Entities: none。
- Persistence changes: none。
- Migration or rollback: 无迁移；回滚 Python 代码提交即可。
- Compatibility: task name/arguments、Redis key、数据库事务和文件解析结果不变。

## 测试策略 Testing Strategy

| Acceptance ID | Test Type | Target | Notes |
|---|---|---|---|
| AC-REQ-001-01..03 | unit/regression | `test/celery/test_celery_async_runtime.py` | fake loop-bound resource，不依赖 Redis |
| AC-REQ-002-01..02 | unit | `test/celery/test_celery_async_runtime.py` | ContextVar 并发隔离与异常传播 |
| AC-REQ-002-03 | unit | `test/knowledge/test_file_encoding_async_bridge.py` | mock timeout/exception，保持 best-effort |
| AC-REQ-002-04 | regression | 现有 `test/test_async_utils.py` + 新 Worker 测试 | 确保 AnyIO/普通同步路径不回归 |
| AC-REQ-003-01..02 | unit | `test/celery/test_celery_async_runtime.py` | register/unregister 生命周期 |
| AC-REQ-003-03 | unit/source check | 文件编码专项测试 + `rg` | 无私有循环 |
| AC-REQ-003-04 | unit | `test/knowledge/test_space_migrate_async_bridge.py` | mock Worker bridge |
| AC-REQ-004-01..03 | regression/review | Ruff、compileall、diff check、相关测试 | 无迁移和契约变化 |

本地中间件可用时增加人工/集成冒烟：启动 `knowledge_celery -P threads -c 20`，连续执行文件解析和相似度刷新，确认日志无 `different loop` 或 `Event loop is closed`。

## 设计决策 Decisions

### AD-01: 复用现有 Worker Loop

- Context: 当前分支已经有 `run_async_task()` 和 `bisheng-celery-async`。
- Options considered: 新建 `ProcessAsyncExecutor`；知识模块直接 import Worker；通用工具注册首选 loop。
- Decision: 通用工具注册首选 loop。
- Rationale: 最少改动，不形成 `knowledge → worker` 依赖，也不重复执行器生命周期。
- Consequences: `utils.async_utils` 增加进程级 loop 引用，但没有 Worker 注册时保持原行为。

### AD-02: 不只切换同步配置读取

- Context: 当前异常发生在 `async_get_knowledge()`，看似可通过同步 Redis 绕开。
- Options considered: Celery 预先同步读取配置；统一循环；Redis 多 loop client。
- Decision: 本 Feature 统一循环。
- Rationale: TF-IDF token cache 等相似度路径仍使用异步 Redis，只切配置读取不能证明根因消失。
- Consequences: `SimilarityPolicy` 可在后续独立 Feature 用于业务解耦，但不是当前修复依赖。

### AD-03: 不修改 RedisClient

- Context: loop-local Redis client 可以从基础设施层防御多循环。
- Options considered: 本次同时修改；后续独立改造。
- Decision: 后续独立改造。
- Rationale: standalone、sentinel、cluster 三种模式及关闭流程都受影响，超出最小 Bug 修复边界。
- Consequences: Celery 必须继续遵守单循环约束。

### AD-04: 借鉴而不直接 cherry-pick 历史提交

- Context: 仓库其他分支提交 `96de66314` 已实现同类 preferred bridge loop，但当前分支的 `async_utils.py` 基线不同，且该提交包含 Workflow callback 等额外改动。
- Options considered: 直接 cherry-pick；移植完整提交；按当前分支最小实现。
- Decision: 按当前分支最小实现并重写专项测试。
- Rationale: 避免带入无关 Workflow 改动和潜在冲突，同时利用已有设计证据降低方案不确定性。
- Consequences: 后续合并分支时需要关注重复实现冲突。

## 风险 / 取舍 Risks / Trade-Offs

| Risk | Impact | Mitigation | Owner / Phase |
|---|---|---|---|
| ContextVar 丢失 | 跨租户读写错误 | 并发 ContextVar 阻断测试 | Implementation |
| shutdown 与提交竞态 | 任务提交到失效 loop | 解除注册、检查 loop 状态、异常不吞 | Implementation |
| 普通同步脚本行为回归 | 非 Worker 调用失败 | 保留 fallback 并运行现有 async_utils 测试 | Verification |
| 其他分支已有同类实现 | 后续 merge 冲突 | 记录提交来源，保持接口命名一致 | Integration |
| 工作区有其他未提交修改 | 覆盖用户改动 | 严格限制 File Structure Plan，不做批量格式化 | All phases |

## 设计质量门 Design Quality Gate

- [x] Every requirement ID is represented in Requirements Traceability.
- [x] Every acceptance criterion has a verification strategy.
- [x] Boundary Commitments include allowed and disallowed changes.
- [x] Every changed file has one clear responsibility and linked requirement.
- [x] Existing architecture is preserved and the bridge change is justified.
- [x] Runtime prerequisites, rollback and risky operations are explicit.
- [x] No speculative abstractions are included.
