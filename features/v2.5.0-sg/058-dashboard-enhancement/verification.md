# 筛选后的全部明细导出验证

Date: 2026-10-23
Status: MANUAL_VERIFY_REQUIRED（本地实现及回归通过，部署和真实下载待验收）
Scope: T025-EXPORT-FILTERED；EXP-REQ-01～04、EXP-AC-01～03；不覆盖本文件创建之前 F058 的其他任务。

## 变更与原因

原表格整表导出只有悬停图标，且 `ComponentWrapper`、`PivotTable` 调用 `useComponentExport` 时没有传递联动筛选，导致导出缺少图表已经应用的筛选。现将交叉表标题栏改为常显“导出全部明细”；导出 Hook 从该组件的 `chartRefreshTriggers` 读取查询参数，通过与图表查询共用的 `componentQueryFilters` 转换后传给既有接口。显式传入的导出条件仍保留优先级，清空筛选时不保留旧值。保存组件自身的筛选和第一指标过滤继续由后端处理。

导出不使用前端交叉表的当前显示行、列或分页结果。扫描超过现有 50,000 条限制时，先拒绝再拆分工作表，防止不同工作表分别未超限而导出被截断的部分数据。权限检查和对象存储上传接口均沿用现有实现。

## 实际证据

| Evidence | Code State / Command | Result | Scope |
|---|---|---|---|
| E-001 | 修改行为代码前：`npm test -- src/test/useComponentExport.test.ts src/test/pivotExportAllButton.test.tsx` | FAIL，4 failed、6 passed：筛选参数为 undefined，表格没有文字导出入口 | 复现 EXP-AC-01/02 |
| E-002 | 修改行为代码前：`.venv/bin/python -m pytest test/telemetry_search/test_dashboard_export_service.py::test_export_all_rejects_truncated_scan_across_multiple_sheets -q --disable-warnings --tb=short` | FAIL：跨组超过扫描上限时未抛错 | 复现 EXP-AC-03 的部分导出风险 |
| E-003 | 修正后：前端 Hook、入口和未保存守卫定向验证；后端导出服务验证 | PASS：前端 13 passed；后端 8 passed | 常显按钮、筛选传递、禁用状态、跨组超限拒绝 |
| E-004 | 最终前端：`npm test -- src/test/useComponentExport.test.ts src/test/pivotExportAllButton.test.tsx src/test/dashboardQueryExportFilters.test.ts src/test/componentExportUnsavedGuard.test.tsx src/test/queryComponentDimensionFilters.test.ts src/test/pivotDepartmentLabels.test.tsx src/test/pivotMissingDimensionExport.test.tsx src/test/chartTitleInput.test.tsx src/test/pivotColumnDimensionClick.test.tsx src/test/pivotTwoColumnDimensions.test.tsx` | PASS：10 个文件、29 passed，1.38 秒 | EXP-AC-01/02；查询与导出两个真实 HTTP 包装函数的请求参数一致；固定/默认/动态时间、原始组织值及 null 筛选、清空、分类导出；原表格交互和标题回归 |
| E-005 | 最终后端：`.venv/bin/python -m pytest test/telemetry_search -q --disable-warnings --tb=short` | PASS：182 passed、1 warning | EXP-AC-02/03；服务层参数传递、权限、文档去重、完整明细、API 和此前登录指标回归 |
| E-006 | `npm run build` | PASS（exit 0），13.31 秒；存在分包大小及 Browserslist 版本提示 | 前端构建；日志 `/tmp/dashboard-filtered-export-build-20261023.log` |
| E-007 | `.venv/bin/ruff check` 导出服务及两个受影响后端测试；`bash scripts/arch-guard.sh` 受影响前后端文件；`git diff --check` | PASS（exit 0） | 静态与架构约束 |

前端测试日志：`/tmp/dashboard-filtered-export-frontend-tests-20261023.log`。测试构造 601 条独立文档并设置图表仅显示 1 条，导出仍返回全部 601 条；超过扫描上限的跨部门分组数据明确报错且不上传文件。已有空条件、权限、未保存组件以及失败后清理加载状态回归均通过。

## 验收覆盖与限制

| Acceptance | Evidence | Status |
|---|---|---|
| EXP-AC-01 常显一键导出与受控状态 | E-003、E-004 | PASS |
| EXP-AC-02 查询与导出筛选一致 | E-004、E-005 | PASS |
| EXP-AC-03 全明细与超限拒绝 | E-002（修复前失败）、E-005（修复后通过） | PASS |
| 部署后浏览器真实下载 Excel，核对选定组织/上传人与清空后的结果 | 未在本次运行真实后端及对象存储环境 | NOT_RUN |

本次未提交、推送、部署或修改生产数据库 / ES。保留工作区此前累积登录人数修正。导出沿用第一指标和外层维度拆工作表规则，50,000 条上限不扩大。

验证中修复了一个旧表格测试未执行 Zustand selector 的 Mock，使它提供真实形状的空查询参数；没有为通过测试而在生产代码中静默丢弃非法筛选。新增 601 条场景初次因测试数据缺少 timestamp 失败，补齐必要事实字段后单模块 24 passed，再执行 E-005 的最终回归。
