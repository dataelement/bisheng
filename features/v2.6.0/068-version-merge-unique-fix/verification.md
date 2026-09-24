# 验证记录 Verification: F068 版本合并唯一键冲突修复

## 元信息 Metadata

- Feature ID: `068-version-merge-unique-fix`
- Status: `complete`
- Related requirements: `features/v2.6.0/068-version-merge-unique-fix/requirements.md`
- Related tasks: `features/v2.6.0/068-version-merge-unique-fix/tasks.md`
- Code state: `2026-07-30 worktree F068 diff`
- Created: `2026-07-30`
- Updated: `2026-07-30`

## 验证摘要 Verification Summary

- Overall status: `VERIFIED`
- Completed tasks: `T001, T002`
- Remaining tasks: `none`
- Blocked tasks: `none`

## 验证证据 Evidence

| Evidence ID | Code State | Executed At / Stage | Command / Step | Purpose | Exit Code / Observation | Result |
|---|---|---|---|---|---|---|
| E-001 | 修复前 | regression baseline | `.venv/bin/python -m pytest test/knowledge/test_knowledge_version_service_similar_scan.py::test_merge_force_allows_document_without_simhash -q` | 复现唯一关系被重复插入 | exit 1；`UNIQUE constraint failed: knowledge_document_version.knowledge_file_id` | FAIL |
| E-002 | F068 implementation | focused regression | 同 E-001 | 验证合并结果及版本行身份保持 | exit 0；`1 passed` | PASS |
| E-003 | F068 implementation | related behavior batch | `.venv/bin/python -m pytest test/knowledge/test_knowledge_version_service_similar_scan.py test/test_favorite_version_notify.py -q` | 验证相似文件/反向合并与收藏通知相关行为 | exit 0；`31 passed` | PASS |
| E-004 | F068 implementation | static | `.venv/bin/python -m ruff check --ignore RUF003 bisheng/knowledge/domain/services/knowledge_version_service.py test/knowledge/test_knowledge_version_service_similar_scan.py` | 排除服务文件既有中文标点规则后检查代码 | exit 0；`All checks passed` | PASS |
| E-005 | F068 implementation | diff hygiene | `git diff --check` | 检查空白和补丁格式 | exit 0 | PASS |
| E-006 | F068 implementation | broader related regression | `.venv/bin/python -m pytest test/knowledge/test_knowledge_version_service_*.py test/knowledge/test_knowledge_document_version_*.py test/test_favorite_version_notify.py -q` | 扩展检查版本服务和模型 | exit 1；`82 passed, 3 failed`，失败均为其他路径旧测试夹具的 `MagicMock.user_name` 校验错误 | FAIL |

## 验收覆盖 Acceptance Coverage

| Acceptance ID | Requirement | Verification Method | Evidence ID | Status |
|---|---|---|---|---|
| AC-REQ-001-01 | REQ-001 | V-AC-REQ-001-01 | E-002, E-003 | PASS |
| AC-REQ-001-02 | REQ-001 | V-AC-REQ-001-01 | E-002 | PASS |
| AC-REQ-001-03 | REQ-001 | V-AC-REQ-001-01 | E-002 | PASS |

## 失败与缺口 Failures and Gaps

- 未忽略规则的 Ruff 命中 `knowledge_version_service.py` 中本次修改前已存在的 9 个中文全角标点 `RUF003`；为避免无关格式化，本次未修改。
- `ruff format --check` 报告服务文件整体需要格式化，但测试文件已格式化；本次不对大型既有服务文件做无关全文件格式化。
- 扩展回归中的 3 条失败分别来自正向关联和切换主版本测试，失败原因是测试 `login_user.user_name` 为 `MagicMock`，与 F068 持久化路径无关。本次目标回归和对应通知测试均已通过。
- 未运行真实 MySQL/DM8 E2E；唯一关系语义由 ORM 模型约束下的 SQLite 集成测试覆盖，线上 MySQL 错误与修复前复现一致。

## 验证质量门 Verification Quality Gate

- [x] Every acceptance criterion has a status.
- [x] Every completion claim is backed by evidence valid for the recorded code state.
- [x] Test/build/lint/smoke commands include actual result summaries.
- [x] Shared commands are executed once and referenced by evidence ID from all covered acceptance criteria.
- [x] Manual-required checks include clear steps.
- [x] Failures are reported without claiming success.
