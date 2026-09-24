# 验证记录

- Feature ID: `066-dashboard-document-statistics`
- Overall status: `LOCAL_PASSED / DEPLOYMENT_NOT_VERIFIED`
- Date: 2026-09-21

## 实际执行证据

1. 后端模块回归：`.venv/bin/python -m pytest -q test/telemetry test/telemetry_search test/test_knowledge_space_content_telemetry.py test/scripts/test_export_portal_category_usage.py test/scripts/test_migrate_knowledge_document_statistics.py --tb=short`，186 passed，7 warnings，4.30s。包含新日期口径、数据库真实 ORM 查询、脚本、增量投影、查询/导出与错误路径。
2. 随后补强迁移 scroll 读取的空页超时、分片失败、精确总条数检查并修复回退预检锁回调，再执行迁移测试文件：11 passed，0.31s。与第 1 项有重复用例，不能直接相加为不同测试总数。
3. 前端 Vitest：`documentStatisticsTotals.test.ts`、`dashboardPivotGroupDimension.test.ts`、`dashboardCrossTabGrouping.test.ts`、`pivotTwoColumnDimensions.test.tsx`、`pivotColumnDimensionClick.test.tsx`，29 passed。包含交叉表合计、小计、比例及组件渲染交互。
4. 新模块、迁移脚本、导出脚本和对应测试 Ruff 通过；既有受影响 Python 模块 py_compile 通过；`git diff --check` 通过。
5. 前端完整 `tsc --noEmit --pretty false` 未通过：当前 1242 条错误，HEAD 独立临时副本 1246 条。去除行号和临时目录差异后，没有新增诊断。未宣称全项目类型检查通过，也未修复无关历史错误。
6. 迁移 `--help` 可执行；未运行真实配置的 `--apply`。`docker ps` 返回本机 Docker socket 不存在，无法在当前本机运行容器 ES 集成验证。

## 验收映射

| Acceptance | 本地证据 | 边界 |
| --- | --- | --- |
| AC-001 / AC-006 | `test_export_portal_category_usage` 使用 SQLite 实际 ORM 验证文档/版本身份、组织子树及租户；统计测试验证分类冲突 | 看板使用 ES 库存，须等待组织与库存同步；组织名称重名须用上传人 ID 等价筛选 |
| AC-002 / AC-005 | `test_document_query_contract` 验证服务、合计和去重导出；前端测试证明跨组与跨月不再求和 | 实际数据量内存与耗时未压测 |
| AC-003 / AC-004 | `test_document_statistics`、`test_document_reader` 验证跨日、跨月、非个人跨组织调用、比例；北京时间动态边界测试 | 来源为日统计，不能还原日内历史调用时间及已删除历史库存 |
| AC-007 | 迁移 11 项：零写入预检、保留历史及未知记录、备份校验、失败不切换、禁止覆盖、无新增写入回退、空页不完整检测 | 使用模拟 ES 接口；真实克隆与原子别名切换仍未验收 |
| AC-008 | 既有增量/全量投影测试及新增仓储身份查询；PIT 关闭、分页、部分失败检查 | 生产版本、调度和实时并发需维护窗口核实 |

## 发布待办

确认真实 ES 版本、单实体/单别名拓扑、磁盘与克隆权限，实际数据量压测；暂停请求及后台写入；新索引迁移并核对摘要；上线同版本 API/worker/前端并等待同步；逐分类对账；维护窗口内演练回退。已物理删除且没有身份关系的历史记录只能保留并报告，重导索引不能恢复已丢失源数据。

操作步骤：`src/backend/scripts/knowledge_document_statistics_migration.md`。未提交、推送、部署或操作生产数据；工作区其他知识迁移、SSO 和配置改动保持原样。
