# 任务拆分 Tasks：Celery 异步运行时单循环收敛

## 阅读摘要

- 本文档按 TDD 顺序实现本次 Bug 修复：先建立跨事件循环失败回归，再实现最小 bridge-loop 修复。
- 任务范围仅限已确认的 `requirements.md` 与 `design.md`，不得加入 Redis 多循环连接池、SimilarityPolicy 或其他业务重构。
- 每个任务完成前必须取得新鲜验证证据。

## 元信息 Metadata

- Feature ID: `056-celery-async-runtime`
- Status: `completed`
- Related requirements: `features/v2.6.0/056-celery-async-runtime/requirements.md`
- Related design: `features/v2.6.0/056-celery-async-runtime/design.md`
- Created: `2026-07-15`
- Updated: `2026-07-15`

## 阶段 1：Celery Bridge 回归与实现

- [x] T001 编写 Celery 单循环与上下文回归测试（RED）
  - Done when: 测试能够证明 preferred loop 未实现时 bridge 不会进入 Worker loop，并覆盖 loop-bound resource、并发 ContextVar、异常传播和普通同步 fallback。
  - _Requirements: REQ-001, REQ-002, REQ-004_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-03, AC-REQ-002-01, AC-REQ-002-02, AC-REQ-004-02_
  - _Verification: V-AC-REQ-001-01, V-AC-REQ-001-02, V-AC-REQ-001-03, V-AC-REQ-002-01, V-AC-REQ-002-02, V-AC-REQ-004-02_
  - _Depends: none_
  - _Boundary: tests only; `src/backend/test/celery/test_celery_async_runtime.py`_

- [x] T002 实现 preferred bridge loop 与 Worker 生命周期注册（GREEN）
  - Done when: `run_async_safe()` 在 Worker 中提交到 `bisheng-celery-async`；AnyIO 保持；普通同步 fallback 复用持久后台循环；Worker 初始化注册、关闭解除；T001 及现有 async utils 测试通过。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-03, AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-04, AC-REQ-003-01, AC-REQ-003-02, AC-REQ-004-02_
  - _Verification: V-AC-REQ-001-01, V-AC-REQ-001-02, V-AC-REQ-001-03, V-AC-REQ-002-01, V-AC-REQ-002-02, V-AC-REQ-002-04, V-AC-REQ-003-01, V-AC-REQ-003-02, V-AC-REQ-004-02_
  - _Depends: T001_
  - _Boundary: `src/backend/bisheng/utils/async_utils.py`, `src/backend/bisheng/worker/_asyncio_utils.py`, `src/backend/bisheng/worker/main.py`_

## 阶段 2：知识任务接入统一循环

- [x] T003 编写文件编码与空间迁移桥接回归测试（RED）
  - Done when: 测试约束文件编码使用通用 bridge 的 120 秒超时和 best-effort 行为，并约束空间迁移通过 `run_async_safe(..., timeout=None)` 提交异步删除。
  - _Requirements: REQ-002, REQ-003_
  - _Acceptance: AC-REQ-002-03, AC-REQ-003-03, AC-REQ-003-04_
  - _Verification: V-AC-REQ-002-03, V-AC-REQ-003-03, V-AC-REQ-003-04_
  - _Depends: T002_
  - _Boundary: tests only; `src/backend/test/knowledge/test_file_encoding_async_bridge.py`, `src/backend/test/knowledge/test_space_migrate_async_bridge.py`_

- [x] T004 删除独立事件循环并接入 Worker bridge（GREEN）
  - Done when: `FileEncodingTransformer` 不再创建私有 loop/thread，使用 `run_async_safe(..., timeout=120.0)`；空间迁移使用 `run_async_safe(..., timeout=None)` 且不再调用 `asyncio.run()`；T003 和既有相关测试通过。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004_
  - _Acceptance: AC-REQ-001-02, AC-REQ-002-03, AC-REQ-003-03, AC-REQ-003-04, AC-REQ-004-01_
  - _Verification: V-AC-REQ-001-02, V-AC-REQ-002-03, V-AC-REQ-003-03, V-AC-REQ-003-04, V-AC-REQ-004-01_
  - _Depends: T003_
  - _Boundary: `src/backend/bisheng/knowledge/rag/pipeline/transformer/file_encoding.py`, `src/backend/bisheng/worker/knowledge/space_migrate_worker.py`_

## 阶段 3：验证与交付

- [x] T005 运行专项、相关回归和静态验证
  - Done when: Celery runtime、async utils、文件编码、空间迁移专项测试通过；Ruff、compileall、source scan 和 `git diff --check` 有新鲜证据；环境允许时完成 Worker 冒烟，否则记录人工步骤和原因。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-03, AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03, AC-REQ-002-04, AC-REQ-003-01, AC-REQ-003-02, AC-REQ-003-03, AC-REQ-003-04, AC-REQ-004-01, AC-REQ-004-02, AC-REQ-004-03_
  - _Verification: V-AC-REQ-001-01, V-AC-REQ-001-02, V-AC-REQ-001-03, V-AC-REQ-002-01, V-AC-REQ-002-02, V-AC-REQ-002-03, V-AC-REQ-002-04, V-AC-REQ-003-01, V-AC-REQ-003-02, V-AC-REQ-003-03, V-AC-REQ-003-04, V-AC-REQ-004-01, V-AC-REQ-004-02, V-AC-REQ-004-03; verification.md_
  - _Depends: T002, T004_
  - _Boundary: verification only_

- [x] T006 更新 SDD 验证与复盘记录
  - Done when: `verification.md` 对每个 AC 标记 PASS/FAIL/MANUAL_REQUIRED/NOT_RUN，`retrospective.md` 记录实际范围、偏差、遗留项和回滚方式，所有已完成任务状态与证据一致。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-03, AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03, AC-REQ-002-04, AC-REQ-003-01, AC-REQ-003-02, AC-REQ-003-03, AC-REQ-003-04, AC-REQ-004-01, AC-REQ-004-02, AC-REQ-004-03_
  - _Verification: verification.md, retrospective.md_
  - _Depends: T005_
  - _Boundary: docs/spec only_

## 计划验证命令

```bash
cd src/backend

./.venv/bin/python -m pytest test/celery/test_celery_async_runtime.py -q
./.venv/bin/python -m pytest test/knowledge/test_file_encoding_async_bridge.py -q
./.venv/bin/python -m pytest test/knowledge/test_space_migrate_async_bridge.py -q
./.venv/bin/python -m pytest test/test_async_utils.py test/test_file_encoding_transformer.py test/test_space_migrate_worker.py -q

./.venv/bin/python -m ruff check \
  bisheng/utils/async_utils.py \
  bisheng/worker/_asyncio_utils.py \
  bisheng/worker/main.py \
  bisheng/knowledge/rag/pipeline/transformer/file_encoding.py \
  bisheng/worker/knowledge/space_migrate_worker.py \
  test/celery/test_celery_async_runtime.py \
  test/knowledge/test_file_encoding_async_bridge.py \
  test/knowledge/test_space_migrate_async_bridge.py

./.venv/bin/python -m compileall \
  bisheng/utils/async_utils.py \
  bisheng/worker/_asyncio_utils.py \
  bisheng/worker/main.py \
  bisheng/knowledge/rag/pipeline/transformer/file_encoding.py \
  bisheng/worker/knowledge/space_migrate_worker.py

rg -n "asyncio\\.run\\(|new_event_loop\\(|shougang-encoding-async" \
  bisheng/knowledge/rag/pipeline/transformer/file_encoding.py \
  bisheng/worker/knowledge/space_migrate_worker.py

git diff --check
```

## 覆盖矩阵 Coverage Matrix

| Requirement | Acceptance Criteria | Tasks | Verification |
|---|---|---|---|
| REQ-001 | AC-REQ-001-01..03 | T001, T002, T004, T005, T006 | V-AC-REQ-001-01..03 |
| REQ-002 | AC-REQ-002-01..04 | T001-T005, T006 | V-AC-REQ-002-01..04 |
| REQ-003 | AC-REQ-003-01..04 | T002-T006 | V-AC-REQ-003-01..04 |
| REQ-004 | AC-REQ-004-01..03 | T001, T002, T004-T006 | V-AC-REQ-004-01..03 |

## 任务质量门 Task Quality Gate

- [x] Every task references at least one requirement ID.
- [x] Every behavioral task references acceptance criteria.
- [x] Every acceptance criterion is covered by at least one task or verification entry.
- [x] Every task has an observable done condition.
- [x] Dependencies are explicit where ordering is not obvious.
- [x] Boundary annotations prevent unrelated code edits.
- [x] No task implements work outside requirements or design.

## 实现记录 Implementation Notes

- 当前工作区包含与 F056 无关的 ETL4LM 图片、门户配置、脚本和 Celery Beat 数据库变更；F056 实施不得覆盖或格式化这些文件。
- `features/` 被仓库 `.gitignore` 忽略；规格文件已落盘，后续若提交需显式 `git add -f features/v2.6.0/056-celery-async-runtime/`，本任务不自动暂存。
- 当前工作分支包含未提交用户改动，因此不在 F056 中自动切换分支；如需提交，再单独确认分支与暂存范围。
- T001 RED：`test/celery/test_celery_async_runtime.py` 运行结果为 4 failed / 3 passed；失败覆盖 loop ID、loop-bound resource、并发单循环和缺少 preferred-loop API。
- T002 GREEN：Celery runtime 与现有 async utils 合计 12 passed，包含 shutdown 子进程验证。
- T003 RED：文件编码与空间迁移 bridge 专项测试 5 failed，失败分别命中缺少 `run_async_safe`、私有 `_AsyncRunner` 和 `asyncio.run()`。
- T004 GREEN：文件编码、空间迁移专项及既有相关测试 33 passed；目标模块 source scan 无私有 loop、`asyncio.run()` 或旧线程名。
- T005 验证：Celery 与知识库相关测试合并执行 46 passed；Ruff F/I 和 format check、compileall、arch-guard、source scan、`git diff --check` 均通过。
- T005 静态债务：完整 Ruff 在本次触及的旧文件中仍报告 16 项既有问题，均为中文全角标点、`typing.List`、旧 dict comprehension 和旧 `noqa`，不属于本 Feature，未扩大修复。
- T005 环境限制：未启动真实 Redis/MySQL/MinIO 和 `knowledge_celery -P threads -c 20`，避免在未确认测试数据与清理策略时写入外部状态；发布前按 `verification.md` 执行人工冒烟。

## 实际偏差记录

> 实施阶段发现设计或范围不匹配时，必须先在此记录并更新 requirements/design，再继续代码修改。

- T003 前置设计适配：空间迁移由计划中的直接 `run_async_task()` 调整为通用 `run_async_safe(..., timeout=None)`。原因是该模块现有测试通过 side-load 隔离 Worker package，新增 Worker 私有模块依赖会破坏模块边界；运行时语义不变，Celery preferred loop 已由 T002 注册。
- T005 前置兼容审查：文件编码切换到通用 bridge 后，普通同步脚本若继续使用每次新建的 `asyncio.run()` 会让全局异步连接绑定到已关闭 loop；T002 增补持久 fallback loop 和连续调用回归，不改变 Celery/AnyIO 路径。
