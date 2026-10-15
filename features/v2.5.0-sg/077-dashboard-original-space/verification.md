# 验证记录

- Date: 2026-10-15
- Code State: 本功能当前工作区；其他功能已有修改未纳入本次变更
- Overall: VERIFIED locally；未部署、未查询生产

## 执行证据

| Evidence | 实际命令或操作 | 结果 |
|---|---|---|
| E-001a | 后端 `.venv/bin/python -m pytest test/telemetry/test_original_space_dimensions.py test/telemetry/test_knowledge_space_content_event_projection.py test/telemetry_search/test_knowledge_space_content_dataset.py test/test_knowledge_space_content_telemetry.py -q --disable-warnings` | PASS，48 passed；日志 `/tmp/dashboard-original-backend.log` |
| E-001b | 后端扩大相关回归：以上文件及 `test_knowledge_space_content_dimensions.py`、`test_content_stat_reconcile.py`、`test_document_query_contract.py`、`test_document_statistics.py`、`test_dashboard_department_labels.py`、`test_dashboard_org_filter_enums.py`、`test_init_dataset_uploader_dimensions.py`、旧 `test/test_knowledge_space_content_realtime.py` | 初次95 passed、8 failed：5项新增导出测试未提供实际界面会带的displayName，修正测试后见E-001c；3项旧Redis模拟器失败见E-004。日志 `/tmp/dashboard-original-regression.log` |
| E-001c | `.venv/bin/python -m pytest test/telemetry_search/test_document_query_contract.py -q --disable-warnings` | PASS，15 passed；分组、全局去重、原值筛选语法及中文导出列通过。其他测试和产品代码未变化，复用E-001b证据；排除旧队列文件后本次相关用例合计98项通过 |
| E-001d | 使用 `git show HEAD:.../knowledge_space_content_dimensions.py` 计算旧日ID固定摘要；加入固定摘要断言后运行 `.venv/bin/python -m pytest test/telemetry/test_original_space_dimensions.py -q --disable-warnings` | PASS，6 passed；预览、下载、收藏都保持修改前的日ID |
| E-002 | 平台前端 `npm test -- src/test/filterConditionFieldNames.test.tsx src/test/pivotDepartmentLabels.test.tsx src/test/datasetSelectorGrouping.test.tsx` | PASS，6 tests；日志 `/tmp/dashboard-original-frontend.log` |
| E-003 | 用本地Python导出的真实数据集schema加载实际DatasetSelector和FilterConditionDialog，浏览器打开字段列表、选择原始上传库、输入“首次上传库”并保存，再选择原始所属部门 | PASS，五项中文维度可见；保存结果保留 `fieldId=original_space_name`、`operator=equals`、`value=首次上传库`。截图 `/tmp/dashboard-original-dimensions.png`；临时页面和服务已清理 |
| E-004 | 在独立Python进程中加载HEAD版本的 `knowledge_space_content.py`，运行旧 `test/test_knowledge_space_content_realtime.py` | 修改前亦3 failed、2 passed；旧模拟器只支持4个CLAIM键，而现有重试脚本需要6个，且不支持ENQUEUE脚本。未修改该文件或队列脚本；日志 `/tmp/dashboard-original-queue-baseline.log` |
| E-005 | 11个本次Python文件使用项目ruff配置检查，并与HEAD的同类诊断比较；运行架构守卫、`git diff --check` | PASS，新增lint诊断0，架构守卫无违规，diff无空白错误 |

## 验收覆盖

| Acceptance | 状态 | Evidence |
|---|---|---|
| AC-1 原始空间名称、分组、筛选 | PASS | E-001a/c、E-002、E-003 |
| AC-2 四级中文名称与字段兼容 | PASS | E-001a/c、E-002、E-003 |
| AC-3 跨库来源、缺失回退、同租户名称 | PASS | E-001a/d |
| AC-4 事件快照、日投影参数、旧ID兼容 | PASS | E-001a/d |
| AC-5 简称、筛选原值与文档去重 | PASS | E-001b/c、E-002、E-003 |

## 实际限制

- 浏览器证据为真实组件和实际数据集schema的本地隔离验证，未运行登录、审批、线上ES全链路。
- 本地9200端口没有ES服务，新增Painless更新脚本未做真实ES执行验证；已有单调计数协议保持不变，测试检查两种写入路径、更新参数和日ID。
- 历史日事件缺少来源快照时不自动追溯补齐；新事件可补齐同日记录缺失字段，已有来源不覆盖。当前文件新名称字段由既有实时/全量对账更新。
- 三项既有队列模拟器失败已在修改前复现，不属于本次字段改动；不扩大范围修复。
