# Tasks: F067-知识空间文件重解析可观测性

**关联规格**: [spec.md](./spec.md)
**版本**: v2.6.0
**状态**: Complete（T001-T007 已实现并验证）

---

## 阅读摘要

- 本任务计划增强现有本地重解析脚本，不重写文件筛选或知识解析管线。
- 实施顺序遵循 Test-First：先定义跨线程写入、并发隔离和时间统计的失败测试，再做最小实现。
- 所有生产代码改动限制在 `scripts/reparse_knowledge_space_files.py`；不修改 Celery 入队脚本、数据库模型、业务 Service、API 或配置。
- 自动化测试不得连接真实 MySQL、Milvus、Elasticsearch、MinIO 或执行真实文件解析。
- 同一代码状态下的定向 pytest、Ruff 和 CLI 证据只执行一次并记录到 `verification.md`，不在每个微任务重复跑全套。

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| `spec.md` | ✅ 已确认 | 用户于 2026-07-28 确认线程隔离、JSONL 和时间口径。 |
| `tasks.md` | ✅ 已确认 | 用户于 2026-07-28 授权按 T001-T007 实施。 |
| 实现 | ✅ 已完成 | 7 / 7 完成。 |
| 验证 | ✅ 已完成 | 见 `verification.md`，33 个定向测试通过。 |

---

## 开发模式与边界

- **后端 Test-First**：并发、错误传播、报告持久化和汇总守恒属于独立风险，先建立失败测试。
- **最小改动**：复用现有 `asyncio.Semaphore`、`asyncio.to_thread`、`FileReparseResult`、
  `RunReport` 和候选筛选逻辑。
- **标准库实现**：只使用 `datetime`、`json`、`pathlib`、`queue`、`threading`、`time`、
  `uuid` 等 Python 标准库，不修改依赖或运行时配置。
- **失败边界**：只承诺捕获普通 `Exception`；不新增多进程、超时、取消或硬崩溃恢复。
- **写入安全**：报告路径使用独占创建，已有文件必须拒绝；测试只能在 `tmp_path` 中写报告。
- **共享文件约束**：T001-T006 都会编辑同一个测试或脚本文件，必须按依赖串行执行，避免并行写冲突。

---

## Tasks

### 阶段 1：JSONL 写入边界

- [x] **T001**: 编写 JSONL 写入器、实时刷新和失败传播测试
  - Done when: 测试先定义逐行合法 JSON、公共事件字段、调用关闭前可读取已刷新事件、
    多生产线程只由写入线程操作文件、同一队列顺序保持、已有目标拒绝、目录/打开/序列化/
    写入/刷新失败可由主流程观察；当前实现按预期失败。
  - _Requirements: REQ-002, REQ-006_
  - _Acceptance: AC-03, AC-04, AC-08, AC-10_
  - _Verification: V-002, V-005_
  - _Depends: none_
  - _Boundary: `src/backend/test/knowledge/test_reparse_knowledge_space_files_script.py` only; use `tmp_path` and fake file handles, no production or external I/O_

- [x] **T002**: 实现单写入线程的 JSONL 报告组件与报告路径参数
  - Done when: 脚本提供带 `schema_version/run_id/event_type/timestamp` 的事件构造能力、
    线程安全队列、唯一写入线程、逐行刷新、哨兵关闭、原始写入异常回传、默认
    `./reparse_reports/reparse-{run_id}.jsonl` 和可选 `--report-file`；目标文件以独占模式创建，
    T001 转绿。
  - _Requirements: REQ-002, REQ-006_
  - _Acceptance: AC-03, AC-04, AC-08, AC-10_
  - _Verification: V-002, V-005_
  - _Depends: T001_
  - _Boundary: JSONL report classes/helpers and CLI argument wiring inside `src/backend/scripts/reparse_knowledge_space_files.py`; do not integrate parsing lifecycle yet_

### 阶段 2：文件级计时、并发与进度

- [x] **T003**: 编写并发上限、异常隔离、文件时间和进度输出测试
  - Done when: 受控假解析函数和同步原语证明活跃解析数不超过 `N`；返回失败与抛出普通异常
    都产生一次完整结果；其他文件继续；有效执行集合满足 `success + failed = total`；每个结果包含
    UTC 开始/结束时间与非负单调用时；标准输出包含开始信息和逐文件完成进度；当前实现按预期失败。
  - _Requirements: REQ-001, REQ-003, REQ-005, REQ-006_
  - _Acceptance: AC-01, AC-02, AC-05, AC-07_
  - _Verification: V-001, V-003, V-004_
  - _Depends: T002_
  - _Boundary: focused runner/result/progress tests in `src/backend/test/knowledge/test_reparse_knowledge_space_files_script.py`; no database-backed selection changes_

- [x] **T004**: 实现文件级计时、统一结果和实时终端进度
  - Done when: 获取并发槽后记录并输出文件开始；普通返回与异常路径都补齐
    `started_at/finished_at/duration_seconds`；主事件循环按完成顺序聚合并输出
    `completed/total`、百分比、成功数、失败数和累计处理耗时；无有效 ID 的候选不会破坏汇总守恒；
    T003 与既有异常隔离测试转绿。
  - _Requirements: REQ-001, REQ-003, REQ-005, REQ-006_
  - _Acceptance: AC-01, AC-02, AC-05, AC-07_
  - _Verification: V-001, V-003, V-004_
  - _Depends: T003_
  - _Boundary: `FileReparseResult`, `RunReport`, `run_reparse_files` and directly related progress helpers in `src/backend/scripts/reparse_knowledge_space_files.py`; preserve `reparse_one_file` business behavior_

### 阶段 3：运行生命周期集成

- [x] **T005**: 编写 apply 生命周期、总耗时与兼容性集成测试
  - Done when: 测试定义 `run_started → selection_completed → processing_started → file_* →
    run_completed` 的顺序和字段；文件间允许交错但单文件开始先于完成；筛选、处理和总耗时非负；
    成功/部分失败/运行失败终态正确；空选择仍写三类运行事件；dry-run 不创建报告；报告初始化或
    运行时失败导致非零退出且不伪报成功；当前实现按预期失败。
  - _Requirements: REQ-002, REQ-004, REQ-006_
  - _Acceptance: AC-03, AC-04, AC-06, AC-08, AC-09, AC-10_
  - _Verification: V-002, V-003, V-005, V-006_
  - _Depends: T004_
  - _Boundary: orchestration-level tests in `src/backend/test/knowledge/test_reparse_knowledge_space_files_script.py`; mock selection, parser, report failures and app-context cleanup_

- [x] **T006**: 将 JSONL 报告接入 apply 主流程并完成运行级汇总
  - Done when: `--apply` 在筛选前启动整次计时和写入器，按契约提交六类事件；文件事件包含身份、
    结果、时间和进度；`run_completed` 包含筛选/处理/总耗时与守恒汇总；空选择正常关闭报告；
    dry-run 完全绕过报告；写入器在 `finally` 中有序关闭并把失败反馈为非零退出；应用上下文仍可靠关闭；
    T005 和现有筛选/状态/解析回归转绿。
  - _Requirements: REQ-002, REQ-004, REQ-006_
  - _Acceptance: AC-03, AC-04, AC-06, AC-08, AC-09, AC-10_
  - _Verification: V-002, V-003, V-005, V-006_
  - _Depends: T005_
  - _Boundary: `run`, report lifecycle helpers and necessary argument serialization inside `src/backend/scripts/reparse_knowledge_space_files.py`; do not alter selection queries, vector deletion, parse pipeline or status eligibility_

### 阶段 4：运维文档与交付验证

- [x] **T007**: 更新使用文档并记录最终验证证据
  - Done when: 模块 docstring 和 `scripts/README.md` 包含默认/显式报告路径、JSONL 事件、
    实时进度示例、普通异常隔离边界、已有文件拒绝、报告失败语义和高并发资源风险；
    `verification.md` 记录定向 pytest、Ruff、CLI `--help`、diff 检查的实际命令、退出码和摘要，
    所有 AC 标记为 `PASS`、`FAIL`、`MANUAL_REQUIRED` 或 `NOT_RUN`，不声称执行真实 `--apply`。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006_
  - _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10_
  - _Verification: V-001, V-002, V-003, V-004, V-005, V-006, V-007_
  - _Depends: T006_
  - _Boundary: `src/backend/scripts/reparse_knowledge_space_files.py` module docstring, `src/backend/scripts/README.md`, F067 `verification.md`, read-only validation commands and formatting limited to F067 touched Python files_

---

## Verification Checkpoints

| Checkpoint | 触发点 | 最低证据 | 禁止事项 |
|------------|--------|----------|----------|
| CP-01 | T002 完成 | T001 写入器与路径测试通过。 | 不运行真实解析，不写 `tmp_path` 外的报告。 |
| CP-02 | T004 完成 | T003 并发、异常、时间和输出测试通过。 | 不连接真实数据库或外部存储。 |
| CP-03 | T006 完成 | T001/T003/T005 相关脚本测试统一通过。 | 不重复执行相同代码状态下的同范围成功命令。 |
| CP-04 | T007 完成 | V-007 全部命令及 AC 状态写入 `verification.md`。 | 不执行真实 `--apply`，不伪报未运行项。 |

### V-007 最终命令范围

所有命令从 `src/backend/` 执行：

```bash
uv run pytest test/knowledge/test_reparse_knowledge_space_files_script.py
uv run ruff format --check scripts/reparse_knowledge_space_files.py \
  test/knowledge/test_reparse_knowledge_space_files_script.py
uv run ruff check scripts/reparse_knowledge_space_files.py \
  test/knowledge/test_reparse_knowledge_space_files_script.py
PYTHONPATH=./ uv run python scripts/reparse_knowledge_space_files.py --help
```

另执行仓库根目录的文档与变更检查：

```bash
git diff --check
```

---

## Coverage Matrix

| Requirement | Acceptance Criteria | Tasks | Verification |
|-------------|---------------------|-------|--------------|
| REQ-001 | AC-01, AC-02 | T003, T004, T007 | V-001, V-007 |
| REQ-002 | AC-03, AC-04, AC-10 | T001, T002, T005, T006, T007 | V-002, V-007 |
| REQ-003 | AC-05 | T003, T004, T007 | V-003, V-007 |
| REQ-004 | AC-06 | T005, T006, T007 | V-003, V-007 |
| REQ-005 | AC-07 | T003, T004, T007 | V-004, V-007 |
| REQ-006 | AC-02, AC-04, AC-08, AC-09, AC-10 | T001, T002, T003, T004, T005, T006, T007 | V-001, V-002, V-005, V-006, V-007 |

---

## 任务质量门

- [x] 每个任务引用至少一个 `REQ-*`。
- [x] 每个行为任务引用至少一个 `AC-*`。
- [x] AC-01 至 AC-10 均被任务和 verification 覆盖。
- [x] 每个任务具有可观察的 Done when。
- [x] 共享文件任务明确串行依赖，未安排冲突并行。
- [x] 测试按独立风险拆分，未按每条 AC 机械复制。
- [x] 最终验证复用同一代码状态的证据，不为每个 task 重跑全套。
- [x] 未包含多进程、超时、恢复、Celery、Schema、API、前端或依赖变更。
- [x] 用户确认 `tasks.md`（2026-07-28）。

---

## 实际偏差记录

- 无范围或架构偏差；实现保持线程并发、JSONL、时间口径及既有解析行为。
- 补充了运行级异常的 `run_completed/run_status=failed` 回归，落实 T005 已声明的失败终态要求。
- 工作区已有与 F067 无关的 `src/backend/celerybeat-schedule.db` 修改；实施阶段必须保持不变。
- `features/` 被仓库 `.gitignore` 忽略；F067 SDD 文档默认不会出现在普通 `git status` 中，
  是否纳入版本控制由用户另行决定，本任务不自行 `git add -f`。
