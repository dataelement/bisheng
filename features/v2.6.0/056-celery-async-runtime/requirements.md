# 需求 Requirements：Celery 异步运行时单循环收敛

## 阅读摘要

- 本文档说明 Celery 进程中多个事件循环复用全局异步 Redis 客户端导致的故障、期望行为和回归验收方式。
- 当前状态：`confirmed`。
- 需要重点确认：本 Feature 先修复直接根因并清理同类 Worker 入口；Redis 多循环连接池和相似度配置快照延期到独立 Feature。

## 元信息 Metadata

- Feature ID: `056-celery-async-runtime`
- Status: `confirmed`
- Mode: `bug-fix`
- Created: `2026-07-15`
- Updated: `2026-07-15`
- Version: `v2.6.0`
- Source request: 修复知识文件解析后相似度刷新出现的 `Future attached to a different loop`，并形成 Celery 进程内统一异步执行方案。

## 需求入口摘要 Intake Summary

- 问题 Problem: 同一 Celery 进程存在 `bisheng-celery-async` 和 `shougang-encoding-async` 两个长期事件循环，共享的异步 Redis 连接只能归属其中一个循环。
- 当前状态 Current state: 文件解析可以成功，但随后的相似度候选刷新可能在异步 Redis 读取时跨循环失败，数据库 Session 随之回滚。
- 目标结果 Target outcome: 本次涉及的 Celery 同步转异步调用全部在 `bisheng-celery-async` 执行，保留上下文、超时和异常语义。
- 影响对象 Affected systems: Knowledge Celery Worker、文件编码 Transformer、相似度刷新、知识空间迁移异步删除。
- Requested stopping point: `implementation`，但按照项目 SDD 暂停点，当前先停在规格确认。

## 故障复现与证据

### 生产日志链路

```text
parse_knowledge_file_celery(file_id=4540) succeeded
→ refresh_file_similarity_candidates_celery(file_id=4540)
→ KnowledgeVersionService._calculate_similarity_candidate_rows()
→ settings.async_get_knowledge()
→ RedisClient.aget()
→ RuntimeError: got Future attached to a different loop
```

日志来源：`/Users/wenruli/.codex/attachments/93e21318-1cec-4912-9c7c-72b7b627a90b/pasted-text.txt`。

### 根因事实

- `worker/_asyncio_utils.py` 创建进程级 `bisheng-celery-async`。
- `file_encoding.py` 独立创建 `shougang-encoding-async`。
- `RedisClient` 同时持有一个进程级 `async_connection`，没有按事件循环隔离。
- `FileEncodingTransformer._do_work()` 会读取异步配置和数据库，可能先把 Redis 连接绑定到私有循环。
- 相似度刷新通过 `run_async_task()` 在 Celery 公共循环再次使用同一连接，产生跨循环 Future。

## 范围 Scope

### 包含 Includes

- 为通用同步转异步工具增加可注册的 Worker 首选事件循环。
- 普通同步脚本在没有 AnyIO/Worker bridge 时复用进程级持久后台循环，避免连续调用留下绑定到已关闭循环的异步连接。
- Celery Worker 创建公共循环时注册该循环，关闭时解除注册。
- `FileEncodingTransformer` 删除私有 `_AsyncRunner`，通过通用桥接执行 `_do_work()`。
- 保留文件编码 `120` 秒超时和当前异常降级行为。
- `space_migrate_worker.py` 的异步删除改为通过通用 bridge 执行；在 Celery 进程中路由到 Worker 公共循环。
- 增加不依赖真实 Redis/MySQL 的跨事件循环回归测试和相关 Worker 测试。
- 进行本地 Redis/MySQL 条件允许时的 Worker 冒烟验证。

### 不包含 Excludes

- 不修改 `RedisClient` 的连接池数据结构。
- 不修改 `settings.get_knowledge()` / `settings.async_get_knowledge()` 对外语义。
- 不引入 `SimilarityPolicy` 或修改相似度算法方法签名。
- 不修改 `KnowledgeVersionService` 的相似度、TF-IDF 或缓存算法。
- 不全面治理非 Worker 模块的全部 `asyncio.run()`。
- 不新增 PID/fork 模式、Celery prefork 支持或运行时配置开关。
- 不关闭或重建历史 Redis 连接，不自动重试历史失败任务。

## 需求列表 Requirements

### REQ-001: Celery 单一异步桥接循环

作为 Celery Worker 维护者，我需要同一进程中受本 Feature 管理的同步转异步入口共享一个持久事件循环，以避免复用异步连接时跨循环失败。

#### 验收标准 Acceptance Criteria

- `AC-REQ-001-01`: WHEN Worker 公共循环已注册且同步代码调用通用异步桥接 THEN 协程 SHALL 在该 Worker 公共循环执行。
- `AC-REQ-001-02`: WHEN 文件编码异步逻辑完成后相似度刷新通过 `run_async_task()` 使用同一个 loop-bound 资源 THEN 两次调用 SHALL 返回相同事件循环标识且不抛出 `attached to a different loop`。
- `AC-REQ-001-03`: WHEN 多个 Celery 工作线程并发提交异步任务 THEN 所有协程 SHALL 使用同一个 Worker 公共循环，并分别返回正确结果或异常。

#### 验证方式 Verification Methods

| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-001-01 | V-AC-REQ-001-01 | automated test | 注册测试事件循环，断言 `run_async_safe()` 内运行循环 ID |
| AC-REQ-001-02 | V-AC-REQ-001-02 | regression test | loop-bound fake resource 依次经文件编码桥接与 `run_async_task()` 调用 |
| AC-REQ-001-03 | V-AC-REQ-001-03 | concurrent unit test | 多线程 Barrier/Executor 并发提交，断言单一 loop ID 与结果隔离 |

### REQ-002: 调用上下文与错误语义保持

作为多租户系统维护者，我需要统一桥接保留调用线程的上下文、超时和异常传播语义，避免修复运行时故障时引入租户串扰或行为变化。

#### 验收标准 Acceptance Criteria

- `AC-REQ-002-01`: WHEN 不同调用线程设置不同的 tenant/trace `ContextVar` 后提交协程 THEN 每个协程 SHALL 读取到对应调用线程的值。
- `AC-REQ-002-02`: WHEN 桥接协程抛出异常 THEN 同步调用方 SHALL 收到原始异常类型和信息。
- `AC-REQ-002-03`: WHEN `FileEncodingTransformer._do_work()` 超过 120 秒或抛出异常 THEN Transformer SHALL 沿用现有 warning 日志并返回原始 documents，不改变文件解析主流程语义。
- `AC-REQ-002-04`: WHEN FastAPI AnyIO 工作线程调用 `run_async_safe()` 且没有 Celery 首选循环 THEN 调用 SHALL 继续回到 AnyIO 所属事件循环。

#### 验证方式 Verification Methods

| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-002-01 | V-AC-REQ-002-01 | automated test | 参数化 ContextVar 并发测试，断言值不串扰 |
| AC-REQ-002-02 | V-AC-REQ-002-02 | automated test | 自定义异常通过 bridge 原样传播 |
| AC-REQ-002-03 | V-AC-REQ-002-03 | automated test | mock bridge timeout/exception，断言日志与 documents 返回值 |
| AC-REQ-002-04 | V-AC-REQ-002-04 | existing + regression test | 保留并运行 `test_async_utils.py` AnyIO/timeout 用例 |

### REQ-003: Worker 生命周期与同类入口清理

作为 Worker 运维人员，我需要桥接循环随 Worker 生命周期注册和解除，同时清除本次识别出的独立事件循环入口。

#### 验收标准 Acceptance Criteria

- `AC-REQ-003-01`: WHEN `get_worker_loop()` 首次创建或返回活动循环 THEN 通用桥接 SHALL 指向该循环。
- `AC-REQ-003-02`: WHEN Worker 收到 shutdown signal THEN 通用桥接 SHALL 解除 Worker 循环注册。
- `AC-REQ-003-03`: WHEN `FileEncodingTransformer.transform_documents()` 执行 THEN 模块 SHALL 不创建 `shougang-encoding-async` 或其他私有事件循环。
- `AC-REQ-003-04`: WHEN `space_migrate_celery` 执行源空间异步删除 THEN 调用 SHALL 通过 `run_async_safe(..., timeout=None)` 路由到 Worker 公共循环，不调用 `asyncio.run()`。

#### 验证方式 Verification Methods

| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-003-01 | V-AC-REQ-003-01 | automated test | `get_worker_loop()` 后断言 bridge 目标循环 |
| AC-REQ-003-02 | V-AC-REQ-003-02 | automated test | 调用 shutdown handler，断言 bridge 已清除 |
| AC-REQ-003-03 | V-AC-REQ-003-03 | automated test + source scan | 文件编码专项测试；目标模块无 `new_event_loop`/私有 Runner |
| AC-REQ-003-04 | V-AC-REQ-003-04 | automated test | mock `run_async_safe`，断言异步删除协程以 `timeout=None` 提交 |

### REQ-004: 外部兼容与最小变更

作为系统使用者，我需要运行时修复不改变现有业务、数据和部署契约。

#### 验收标准 Acceptance Criteria

- `AC-REQ-004-01`: WHEN 本 Feature 部署 THEN API、Celery task name/arguments、Redis key/TTL、数据库结构和文件解析结果契约 SHALL 保持不变。
- `AC-REQ-004-02`: WHEN 没有 Worker 注册首选循环的普通同步脚本连续调用 `run_async_safe()` THEN 调用 SHALL 复用同一个进程级后台循环，loop-bound 资源不得绑定到已关闭循环。
- `AC-REQ-004-03`: WHEN 本 Feature 需要回滚 THEN SHALL 通过回滚代码提交完成，不需要数据库或缓存数据迁移。

#### 验证方式 Verification Methods

| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-004-01 | V-AC-REQ-004-01 | diff review + related tests | 无 schema/config/API/task signature 变更；知识和 Worker 相关测试通过 |
| AC-REQ-004-02 | V-AC-REQ-004-02 | automated test | 清除 preferred loop 后连续两次调用同一 loop-bound fake resource，断言 loop ID 一致 |
| AC-REQ-004-03 | V-AC-REQ-004-03 | design review | 变更仅为 Python 代码和测试，无迁移文件 |

## 非功能需求 Non-Functional Requirements

- `NFR-001`: 不新增第三方依赖。
- `NFR-002`: Worker 并发仍由现有 `-P threads` 和 Celery concurrency 控制，不在桥接层串改任务业务顺序。
- `NFR-003`: 关键路径必须记录包含 loop/thread 上下文的可诊断日志或由测试提供可观察 loop ID。
- `NFR-004`: 关键跨循环回归路径自动化覆盖率目标为 100%。

## 澄清记录 Clarifications

### Session 2026-07-15

- Q: 是否可以分别提供同步 Redis 给 Celery、异步 Redis 给接口？ -> A: 配置层已有同步/异步入口，但只切换配置读取不能覆盖 TF-IDF 等异步 Redis 调用，因此需先统一 Celery 事件循环。
- Q: Celery 进程内异步执行器如何实现？ -> A: 一个 Worker 进程内多任务线程提交到一个持久事件循环，并保留 ContextVar、异常和生命周期管理。
- Q: 是否开始实施？ -> A: 用户已确认开始；详细规格仍需按项目 SDD 暂停点确认。
- Q: 是否确认本规格并继续实施？ -> A: 用户于 2026-07-15 确认。

## 假设 Assumptions

- 当前生产部署继续使用项目文档中的 `-P threads`；本 Feature 不承诺新增 prefork 行为。
- `RedisClient.async_connection` 仍是单一连接对象，因此必须保证 Celery 中受管异步调用进入同一个循环。
- 历史提交 `96de66314` 提供了同类 bridge-loop 设计证据，但当前分支未包含该实现，不能视为当前代码已修复。

## 风险 Risks

- ContextVar 未正确传播会导致租户数据串扰，因此 `AC-REQ-002-01` 是阻断上线项。
- Worker 关闭期间桥接目标失效可能导致提交失败，因此必须先解除注册并保持异常可见。
- 将 Redis 改为多循环连接池会影响 standalone/sentinel/cluster 全部模式，本 Feature 明确不包含该高风险改造。
- 当前工作区有其他未提交变更；实现必须限定文件清单，禁止覆盖 ETL4LM 图片与门户配置改动。

## 需求质量门 Requirements Quality Gate

- [x] Every requirement has a stable `REQ-*` ID.
- [x] Every requirement has at least one `AC-*` acceptance criterion.
- [x] Every acceptance criterion has a stable `AC-*` ID.
- [x] Every acceptance criterion has at least one `V-*` verification ID.
- [x] Every acceptance criterion has a verification method.
- [x] No orphan `AC-*` or `V-*` entries exist.
- [x] Scope includes and excludes are explicit.
- [x] No critical ambiguity remains.
