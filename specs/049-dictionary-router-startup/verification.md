# 验证记录 Verification: 系统字典路由启动修复

## 元信息 Metadata
- Feature ID: `049-dictionary-router-startup`
- Status: `verified`
- Related requirements: `specs/049-dictionary-router-startup/requirements.md`
- Related tasks: `specs/049-dictionary-router-startup/tasks.md`
- Code state: `dictionary-router-fix worktree @ 2026-07-28`
- Created: `2026-07-28`
- Updated: `2026-07-28`

## 验证摘要 Verification Summary
- Overall status: `VERIFIED`
- Completed tasks: `T001, T002`
- Remaining tasks: `none`
- Blocked tasks: `none`

## 验证证据 Evidence
| Evidence ID | Executed At / Stage | Command / Step | Purpose | Exit Code / Observation | Result |
|---|---|---|---|---|---|
| E-001 | 修复前红灯 | `uv run pytest test/dictionary/test_dictionary_router.py -q` | 稳定复现原始启动异常 | exit 1；`FastAPIError: Prefix and path cannot be both empty` | PASS |
| E-002 | 修复后定向回归 | `uv run pytest test/dictionary/test_dictionary_router.py -q` | 验证路由可注册且集合路径兼容 | exit 0；`1 passed` | PASS |
| E-003 | 全局路由链 | 导入 `bisheng.api.router` 并检查 GET/POST 路由集合 | 验证真实 `/api/v1` 聚合链 | exit 0；两个 `/api/v1/dictionaries` 路由均存在 | PASS |
| E-004 | 静态与格式 | `uv run ruff check ...`、`uv run ruff format --check ...` | 验证代码规范 | exit 0；`All checks passed`、`2 files already formatted` | PASS |
| E-005 | diff 检查 | `git diff --check` | 验证补丁空白和冲突标记 | exit 0 | PASS |

## 验收覆盖 Acceptance Coverage
| Acceptance ID | Requirement | Verification Method | Evidence ID | Status |
|---|---|---|---|---|
| AC-REQ-001-01 | REQ-001 | V-AC-REQ-001-01 | E-001, E-002, E-003 | PASS |
| AC-REQ-001-02 | REQ-001 | V-AC-REQ-001-01 | E-002, E-003 | PASS |

## 失败与缺口 Failures and Gaps
- 未启动依赖数据库、Redis 等中间件的完整服务；本次错误发生在模块导入和路由注册阶段，已由定向测试与全局路由导入覆盖。
- 全局导入过程中出现项目既有的可选依赖和 Pydantic 警告，不影响 dictionary 路由注册。
