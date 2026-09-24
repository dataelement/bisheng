# Verification: F067-知识空间文件重解析可观测性

## 阅读摘要

- Overall Status: `VERIFIED`
- Code State: 2026-07-28 最终工作树，涉及脚本、定向测试与 README。
- 自动化结果：33 个定向 pytest 通过，Ruff、CLI `--help` 和 diff 检查通过。
- 未执行真实 `--apply`，未连接生产 MySQL、Milvus、Elasticsearch、MinIO 或真实解析服务。

---

## 元信息 Metadata

- Feature ID: `067-reparse-observability`
- Status: `VERIFIED`
- Mode: `spec-then-implement`
- Verified: `2026-07-28`
- Related spec: `features/v2.6.0/067-reparse-observability/spec.md`
- Related tasks: `features/v2.6.0/067-reparse-observability/tasks.md`

---

## Evidence

| Evidence | Code State | Command / Step | Result | Scope |
|----------|------------|----------------|--------|-------|
| E-001 | 实现前基线 | `uv run --python=.venv/bin/python pytest test/knowledge/test_reparse_knowledge_space_files_script.py -q` | `PASS`，19 passed | 原有筛选、状态和异常隔离基线。 |
| E-002 | T001 红灯 | `pytest ... -k jsonl_report_writer -q` | `EXPECTED FAIL`，4 failed，均因 `JsonlReportWriter` 尚不存在 | 证明 JSONL 测试命中新能力缺口。 |
| E-003 | T002 批次 | `pytest ... -k "jsonl_report_writer or parse_args" -q` | `PASS`，11 passed | JSONL 实时刷新、并发生产、已有文件拒绝、序列化失败和 CLI 参数。 |
| E-004 | T003 红灯 | `pytest ... -k run_reparse_files -q` | `EXPECTED FAIL`，计时字段与有效总数缺失；并发上限基线通过 | 证明计时与汇总测试命中目标缺口。 |
| E-005 | T004 批次 | `pytest ... -k run_reparse_files -q` | `PASS`，3 passed | 并发上限、普通异常隔离、文件时间、汇总守恒和终端进度。 |
| E-006 | T005 红灯 | `pytest ... -k "apply_run or dry_run" -q` | `EXPECTED FAIL`，4 个 apply 报告用例失败；dry-run 兼容通过 | 证明主流程尚未接入 JSONL。 |
| E-007 | T006 批次 | `pytest ... -k "apply_run or dry_run" -q` | `PASS`，6 passed | apply 生命周期、空选择、dry-run、已有路径和关闭失败。 |
| E-008 | 运行级失败红灯 | `pytest ... -k failed_terminal_event -q` | `EXPECTED FAIL`，缺少失败终态事件 | 证明运行级 `failed` 终态缺口。 |
| E-009 | 运行级失败回归 | `pytest ... -k failed_terminal_event -q` | `PASS`，1 passed | 异常重抛前写入 `run_completed/run_status=failed`。 |
| E-010 | 最终代码状态 | `uv run --python=.venv/bin/python pytest test/knowledge/test_reparse_knowledge_space_files_script.py -q` | `PASS`，33 passed in 0.49s | AC-01 至 AC-10 的主要自动化证据，包含批次运行中实时读取文件事件。 |
| E-011 | 最终代码状态 | `uv run --python=.venv/bin/python ruff format --check scripts/reparse_knowledge_space_files.py test/knowledge/test_reparse_knowledge_space_files_script.py` | `PASS`，2 files already formatted | 格式门禁。 |
| E-012 | 最终代码状态 | `uv run --python=.venv/bin/python ruff check scripts/reparse_knowledge_space_files.py test/knowledge/test_reparse_knowledge_space_files_script.py` | `PASS`，All checks passed | 静态检查。 |
| E-013 | 最终代码状态 | `PYTHONPATH=./ uv run --python=.venv/bin/python python scripts/reparse_knowledge_space_files.py --help` | `PASS`，exit 0，显示 `--concurrency` 与 `--report-file` | CLI 可发现性与参数契约。 |
| E-014 | 最终代码状态 | `git diff --check` | `PASS`，exit 0 | 变更空白与补丁结构检查。 |

命令 E-001 至 E-013 均从 `src/backend/` 执行；E-014 从仓库根目录执行。

---

## Acceptance Coverage

| Acceptance | Status | Evidence | 说明 |
|------------|--------|----------|------|
| AC-01 | `PASS` | E-010 | 同步原语证明线程活跃数不超过 `--concurrency`，所有有效文件进入汇总。 |
| AC-02 | `PASS` | E-010 | 单文件抛出 `RuntimeError` 后其他文件继续，最终聚合失败。 |
| AC-03 | `PASS` | E-010 | `tmp_path` 中的 JSONL 在 writer 关闭前可读取，apply 生命周期完整。 |
| AC-04 | `PASS` | E-010 | 并发生产得到逐行合法 JSON；单文件开始事件先于完成事件。 |
| AC-05 | `PASS` | E-010 | 成功、返回失败和异常结果均记录 UTC 时间与非负用时。 |
| AC-06 | `PASS` | E-010 | `run_completed` 汇总筛选、处理、总耗时及守恒计数。 |
| AC-07 | `PASS` | E-010 | stdout 包含开始、`completed/total`、百分比、计数和累计耗时。 |
| AC-08 | `PASS` | E-010 | 报告初始化、序列化和关闭失败可观察并导致非零退出。 |
| AC-09 | `PASS` | E-010 | dry-run 不创建报告、不调用文件解析，原有筛选测试继续通过。 |
| AC-10 | `PASS` | E-010 | 已有报告文件在候选筛选前被拒绝且内容保持不变。 |

---

## 未执行项与人工验证

### 真实 apply

- Status: `NOT_RUN`
- 原因：真实重解析会删除目标文件的旧 Milvus/Elasticsearch 索引并重新执行解析，属于运维数据写入；
  自动化验收按 spec 明确使用 fake/mock 隔离。
- 如需人工验证，应在非生产维护环境先执行 dry-run，选择 2～3 个可恢复文件，设置低并发并保存 JSONL；
  检查数据库最终状态、外部索引、终端进度和 JSONL 时间字段后再扩大范围。

### 环境容量与推荐并发

- Status: `MANUAL_REQUIRED`
- 原因：安全并发值取决于数据库、Milvus、Elasticsearch、MinIO、解析器和宿主机容量，无法由单元测试给出。
- 人工步骤：从 `--concurrency 1` 开始，在监控 CPU、内存、连接池和外部服务延迟的前提下逐级增加。

---

## 已知边界

- 普通 Python `Exception` 按文件隔离；原生崩溃、解释器退出和永久阻塞仍可能影响整个进程。
- JSONL 每行调用 `flush()` 保证运行中可读取，但主机断电或 `SIGKILL` 仍可能丢失最后一个尚未落入操作系统持久存储的事件。
- 报告包含文件名和异常文本，应写入访问受控的路径。
- `features/` 被仓库 `.gitignore` 忽略，本验证文档默认不参与普通 Git 状态或提交。
