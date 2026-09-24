# 验证记录 Verification: 部门知识空间重复文档清理脚本

## 阅读摘要

- 本文档记录实际执行过的验证命令、验收覆盖和未验证项。
- 自动化验证使用进程内 fake adapter，不连接真实数据库、Milvus、Elasticsearch、MinIO 或 OpenFGA。
- 真实跨存储删除属于不可逆操作，当前没有执行授权，统一标记为 `MANUAL_REQUIRED`。
- 功能、脚本目录回归、静态检查和安全边界测试均通过；覆盖率插件在当前虚拟环境中不可用。

## 元信息 Metadata

- Feature ID: `057-department-space-document-dedup`
- Status: `manual-verify-required`
- Related requirements: [`requirements.md`](./requirements.md)
- Related tasks: [`tasks.md`](./tasks.md)
- Created: `2026-07-19`
- Updated: `2026-07-19`

## 验证摘要 Verification Summary

- Overall status: `MANUAL_VERIFY_REQUIRED`
- Status rule: Overall status uses `VERIFIED | NOT_VERIFIED | MANUAL_VERIFY_REQUIRED`; acceptance status uses `PASS | FAIL | MANUAL_REQUIRED | NOT_RUN`.
- Completed tasks: `T001-T012`
- Remaining tasks: 无自动化任务；真实基础设施联调需新的数据删除授权。
- Blocked tasks: 无；`V-MANUAL-01` 是交付后的受控人工验证，不是本次实现阻塞。

## 已执行命令 Commands Run

| Command | Purpose | Exit Code | Result | Evidence |
|---|---|---:|---|---|
| `.venv/bin/python -m pytest test/scripts/test_dedupe_department_space_documents.py -q`（实现前） | Test-First RED | 2 | PASS | 脚本尚不存在，测试收集阶段按预期失败 |
| `.venv/bin/python -m pytest test/scripts/test_dedupe_department_space_documents.py -q` | 功能与进程内编排回归 | 0 | PASS | `35 passed in 0.28s` |
| `.venv/bin/python -m pytest test/scripts/ -q` | 完整脚本测试目录回归 | 0 | PASS | `106 passed, 6 warnings in 2.85s`；warnings 来自 SWIG 类型和 `jieba/pkg_resources` 既有依赖 |
| `.venv/bin/python -m ruff format --check scripts/dedupe_department_space_documents.py test/scripts/test_dedupe_department_space_documents.py` | 格式检查 | 0 | PASS | `2 files already formatted` |
| `.venv/bin/python -m ruff check scripts/dedupe_department_space_documents.py test/scripts/test_dedupe_department_space_documents.py` | 静态检查 | 0 | PASS | `All checks passed!` |
| `.venv/bin/python -m py_compile scripts/dedupe_department_space_documents.py` | Python 语法编译 | 0 | PASS | 无错误输出 |
| `.venv/bin/python scripts/dedupe_department_space_documents.py --help` | 直接运行与 CLI 烟测 | 0 | PASS | 显示 dry-run、范围、报告和 resume 参数帮助 |
| `bash scripts/arch-guard.sh` | 项目架构守卫 | 0 | PASS | 无 violation/warning 输出 |
| `git diff --check` | 补丁空白和冲突标记检查 | 0 | PASS | 无错误输出 |
| `rg -n "(sk-...|password=...|secret=...|api_key=...)" scripts/dedupe_department_space_documents.py` | 硬编码秘密扫描 | 1 | PASS | `rg` 无匹配时返回 1；脚本未发现相应字面量 |
| `.venv/bin/python -m pytest ... --cov=...` | 覆盖率报告尝试 | 4 | FAIL | 当前环境未安装 `pytest-cov`；随后确认也没有 `coverage` 模块 |

## 验收覆盖 Acceptance Coverage

| Acceptance ID | Requirement | Verification Method | Evidence | Status |
|---|---|---|---|---|
| AC-01 | REQ-005, REQ-013 | V-AC-01 | `test_dry_run_writes_report_without_constructing_operations` 断言写 adapter 构造次数为 0 | PASS |
| AC-02 | REQ-002 | V-AC-02 | scope enum/发布状态无关测试；生产枚举按持久化值归一化 | PASS |
| AC-03 | REQ-003, REQ-004 | V-AC-03 | planner fixture 精确命中当前成功文件并保留全部见证 | PASS |
| AC-04 | REQ-004, REQ-013 | V-AC-04 | 空 MD5、空白、大小写差异、非 FILE/非 SUCCESS 参数化覆盖；模型不读取 SimHash | PASS |
| AC-05 | REQ-003, REQ-004 | V-AC-05 | 公共历史版本与部门兼容文件同 MD5 时不命中 | PASS |
| AC-06 | REQ-008, REQ-009, REQ-010 | V-AC-06 | fake adapter 断言历史/当前两个物理文件均进入完整删除序列 | PASS |
| AC-07 | REQ-003, REQ-008 | V-AC-07 | `legacy-file:*` fixture 进入独立删除单元 | PASS |
| AC-08 | REQ-003, REQ-007 | V-AC-08 | 主指针冲突、多个主版本、跨空间版本链均带 reason code 跳过 | PASS |
| AC-09 | REQ-004 | V-AC-09 | 单一部门 unit 保存两个公共 witness | PASS |
| AC-10 | REQ-006 | V-AC-10 | 空间/file/limit 范围测试及公共/历史 file ID 拒绝测试 | PASS |
| AC-11 | REQ-007 | V-AC-11 | 漂移重校验返回 `skipped/plan_drift`，写 adapter 零调用 | PASS |
| AC-12 | REQ-009, REQ-010, REQ-015 | V-AC-12, V-MANUAL-01 | fake 验证删除顺序和公共零修改；真实五类存储未联调 | MANUAL_REQUIRED |
| AC-13 | REQ-010 | V-AC-13 | fake DB session 断言精确删除标签、审核标签、分享、相似候选、推荐投影和目标版本图 | PASS |
| AC-14 | REQ-010, REQ-013 | V-AC-14 | impact report 保留收藏/审计计数，数据库删除集合不包含相关历史表 | PASS |
| AC-15 | REQ-011, REQ-014 | V-AC-15 | 故障注入断言当前 failed、后续 pending、退出码 4、报告持久化 | PASS |
| AC-16 | REQ-012 | V-AC-16 | 缺失主记录只重试派生失效/验证；skipped 保持终态；篡改边界拒绝 | PASS |
| AC-17 | REQ-001, REQ-014 | V-AC-17 | run 级测试断言多租户返回 2，reader 和写 adapter 调用次数为 0 | PASS |
| AC-18 | REQ-015 | V-AC-18, V-MANUAL-01 | fake 残留触发 `ResidualDataError` 和退出码 4；真实残留查询未联调 | MANUAL_REQUIRED |

## 人工验证 Manual Verification

| Acceptance ID | Manual Steps | Expected Result | Actual Result | Status |
|---|---|---|---|---|
| AC-12 | 在隔离的单租户 MySQL 环境构造一个公共当前文件和一个含两版本的部门逻辑文档；同时准备 Milvus、ES、MinIO、OpenFGA 资源。先备份并运行限定 `--file-id` 的 dry-run，审核 JSON 后另行授权执行 `--apply`。再在 DM8 环境重复。 | 部门完整版本链及活动关系、五类外部资源归零；公共文件、版本和对象保持不变；报告状态 completed。 | 未执行：当前授权不包含真实数据删除。 | NOT_RUN |
| AC-16 | 在隔离环境分别注入外部删除中断和数据库已提交/派生失效失败；使用原 apply 报告执行 `--resume-report --apply`。 | 数据库仍存在时重新扫描并幂等收敛；主记录已删除时只运行派生失效与只读验证；skipped/completed 不重试。 | 未执行：当前授权不包含真实数据删除。 | NOT_RUN |
| AC-18 | 在隔离环境故意保留一条 Milvus、ES、MinIO、OpenFGA 或数据库目标残留，执行限定 apply。 | 单元标记 failed、退出码 4、报告给出对应残留计数，公共见证不变。 | 未执行：当前授权不包含真实数据删除。 | NOT_RUN |

## 失败与缺口 Failures and Gaps

- 当前 `.venv` 没有 `pytest-cov`/`coverage`，因此未生成行覆盖率百分比；功能路径由 35 项定向测试和 106 项脚本目录回归覆盖。
- 没有真实执行 dry-run 或 `--apply`，避免读取或修改用户未明确放入测试范围的数据。
- MySQL/DM8、Milvus、Elasticsearch、MinIO、OpenFGA 的真实联调仍为 `V-MANUAL-01`，需要隔离环境、备份和新的删除授权。

## 验证质量门 Verification Quality Gate

- [x] Every acceptance criterion has a status.
- [x] Every completion claim is backed by fresh evidence.
- [x] Test/build/lint/smoke commands include actual result summaries.
- [x] Manual-required checks include clear steps.
- [x] Failures are reported without claiming success.
