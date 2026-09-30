# 验证记录 Verification: 交叉表双列维度

## 阅读摘要
- 配置、字段点击与拖拽、查询、透视、两级表头和旧单维兼容均有自动化测试证据。
- 前端生产构建和架构检查通过。
- 真实看板页面加载超时，仍需在可访问环境完成人工视觉检查。

## 元信息 Metadata
- Feature ID: `061-dashboard-pivot-two-column-dimensions`
- Status: `complete`
- Related requirements: `features/v2.5.0-sg/061-dashboard-pivot-two-column-dimensions/requirements.md`
- Related tasks: `features/v2.5.0-sg/061-dashboard-pivot-two-column-dimensions/tasks.md`
- Code state: `feat/2.5.0-sg dirty worktree at 2026-08-21`
- Created: `2026-08-21`
- Updated: `2026-08-21`

## 验证摘要 Verification Summary
- Overall status: `MANUAL_VERIFY_REQUIRED`
- Completed tasks: `T001, T002, T003, T004`
- Remaining tasks: `none`
- Blocked tasks: `none`

## 验证证据 Evidence
| Evidence ID | Code State | Executed At / Stage | Command / Step | Purpose | Exit Code / Observation | Result |
|---|---|---|---|---|---|---|
| E-001 | implementation worktree | regression | `npm test -- --run src/test/pivotTwoColumnDimensions.test.tsx src/test/pivotTimeGranularity.test.tsx src/test/pivotTableSequence.test.tsx src/test/pivotColumnAliases.test.ts` | 双维配置、列路径累计、两级表头、时间粒度、序号和别名兼容 | exit 0；4 files、7 tests passed | PASS |
| E-002 | implementation worktree | regression | `./.venv/bin/python -m pytest test/telemetry_search/test_pivot_column_dimensions.py test/telemetry_search/test_component_time_dimension.py test/telemetry_search/test_knowledge_contribution_ratio.py -q` | 双列查询顺序、日期格式化、旧单列查询和虚拟指标兼容 | exit 0；17 passed | PASS |
| E-003 | implementation worktree | static | `./.venv/bin/ruff check --select E9,F ...` | 后端语法、未定义名称和关键静态错误 | exit 0；All checks passed | PASS |
| E-004 | implementation worktree | build | `npm run build` | 平台前端生产构建 | exit 0；built in 13.11s | PASS |
| E-005 | implementation worktree | architecture | `bash scripts/arch-guard.sh` | 架构边界检查 | exit 0 | PASS |
| E-006 | implementation worktree | static | `git diff --check` | 补丁空白与冲突标记检查 | exit 0 | PASS |
| E-007 | pre-fix worktree | reproduction | `npm test -- --run src/test/pivotColumnDimensionClick.test.tsx` | 复现已有一个堆叠维度后点击添加第二个失败 | exit 1；期望 `timestamp,category_name`，实际仍为 `timestamp` | EXPECTED_FAIL |
| E-008 | bugfix worktree | regression | `npm test -- --run src/test/pivotColumnDimensionClick.test.tsx src/test/pivotTwoColumnDimensions.test.tsx src/test/pivotTimeGranularity.test.tsx src/test/pivotTableSequence.test.tsx src/test/pivotColumnAliases.test.ts` | 点击与拖拽双维配置、非交叉表单维限制、列路径和兼容行为 | exit 0；5 files、9 tests passed | PASS |
| E-009 | bugfix worktree | build | `npm run build` | 平台前端生产构建与 TypeScript 转换 | exit 0；built in 12.67s | PASS |
| E-010 | bugfix worktree | static/architecture | `git diff --check && bash scripts/arch-guard.sh` | 补丁格式与架构边界 | exit 0 | PASS |

## 验收覆盖 Acceptance Coverage
| Acceptance ID | Requirement | Verification Method | Evidence ID | Status |
|---|---|---|---|---|
| AC-REQ-001-01 | REQ-001 | V-AC-REQ-001 | E-007, E-008 | PASS |
| AC-REQ-001-02 | REQ-001 | V-AC-REQ-001 | E-008 | PASS |
| AC-REQ-001-03 | REQ-001 | V-AC-REQ-001 | E-008 | PASS |
| AC-REQ-002-01 | REQ-002 | V-AC-REQ-002 | E-002 | PASS |
| AC-REQ-002-02 | REQ-002 | V-AC-REQ-002 | E-002 | PASS |
| AC-REQ-003-01 | REQ-003 | V-AC-REQ-003 | E-008 | PASS |
| AC-REQ-003-02 | REQ-003 | V-AC-REQ-003 | E-008 | PASS |
| AC-REQ-003-03 | REQ-003 | V-AC-REQ-003 | E-008 | PASS |

## 人工验证 Manual Verification
| Evidence ID | Acceptance ID | Manual Steps | Expected Result | Actual Result | Status |
|---|---|---|---|---|---|
| E-M001 | AC-REQ-001-01, AC-REQ-003-02 | 打开看板编辑器，为交叉表拖入两个堆叠维度，保存并查看图表 | 可添加两个维度，表头按第一层合并并展示第二层叶子列 | 截图中的看板地址加载超时，未进入页面 | NOT_RUN |

## 失败与缺口 Failures and Gaps
- 真实看板环境 `http://10.171.0.30:31134/dashboard/177` 在当前验证环境加载超时，未执行人工视觉检查。
- 交互回归测试由失败转为通过，证明修复覆盖了实际字段点击入口；部署环境仍需重新构建并重启前端后再观察新行为。
- 构建存在项目已有的 ace 非 module、Browserslist 过期、第三方 eval 和大 chunk 警告；本次未新增依赖或相关构建警告。
- 完整 Ruff 规则在历史文件中存在既有现代化告警，本次执行与改动风险相关的 `E9,F` 检查并通过。

## 验证质量门 Verification Quality Gate
- [x] Every acceptance criterion has a status.
- [x] Every completion claim is backed by evidence valid for the recorded code state.
- [x] Test/build/lint/smoke commands include actual result summaries.
- [x] Shared commands are executed once and referenced by evidence ID from all covered acceptance criteria.
- [x] Manual-required checks include clear steps.
- [x] Failures are reported without claiming success.
