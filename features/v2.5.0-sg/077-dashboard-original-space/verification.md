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

## 2026-10-20 生产原始组织补齐检查

### 脚本和范围

- 本地脚本：`src/backend/scripts/backfill_dashboard_original_organizations.py`；默认只读。复用现有投影builder，仅补五个原始来源字段空值；无数据库写入、索引结构变更、历史事件回写和全量覆盖。
- 最终SHA256：`c8f8761b716fb29d31bb0c71aab478f4915e39b04f4aa00685f2c5e6e25410e5`。生产容器保存临时副本 `/tmp/backfill_dashboard_original_organizations_20261020_v3.py`，传输后摘要核对一致。
- 生产目标：命名空间 `stpaas-tenant-skm-prod`，容器组 `bisheng-backend-shougang-7694778857-tjrkb`，统计索引 `mid_knowledge_space_content_stat`，租户1。浏览器已有有效登录，未保存凭据。
- 原始空间取当前组织映射；原始库ID缺失继续使用已确认的当前库回退；不能据此声称恢复首次上传历史组织。

### 执行证据

| Evidence | 命令或操作 | 结果 |
|---|---|---|
| E-006 | 后端 `.venv/bin/python -m pytest test/scripts/test_backfill_dashboard_original_organizations.py test/telemetry/test_original_space_dimensions.py -q --disable-warnings` | PASS，20 passed，0.43s；包含预览/固定计划执行/回退CLI、非空保护、租户/身份拒绝、来源缺失、漂移、版本冲突、部分扫描失败、0600输出和字段级回退 |
| E-007 | 两个新增文件 `ruff check`、`ruff format`、架构守卫，脚本 `--help`，`git diff --check` | PASS；无新增依赖、运行时配置或业务代码修改 |
| E-008 | 生产 `/app` 执行 `PYTHONPATH=/app LOGURU_LEVEL=ERROR python /tmp/backfill_dashboard_original_organizations_20261020_v3.py --tenant-id 1 --output /tmp/dashboard-origin-plan-final-20261020.json`，日志重定向 `/tmp/dashboard-origin-preview-final-20261020.log` | PASS，`FINAL_PREVIEW_EXIT:0`。扫描20,424条，unchanged20,372，source_missing2，identity_mismatch50，legacy_fallback142，候选0，业务写入0 |
| E-009 | 真实ES按五字段missing聚合，抽查128429和128427的ES/当前投影 | 原始库名称缺失0；公司236、部门2,753、科室14,918、班组20,250缺失。128429当前库5284，旧统计库4083，原始库“首钢智新”及公司/部门一致；128427当前投影不可用。没有将这些异常记录作为补齐目标 |

最终计划摘要：`e447e7f7874b2b00be1e8625dc6e7c6969ede03cc7e84cc79949098fd90a717e`。

截图：`/tmp/dashboard-original-org-production-preview-20261020.png`。生产计划文件0600，生产脚本、日志和计划均在容器临时目录，容器重建后可能丢失；本地保留脚本和本验证记录。

### 结论与限制

- AC-6 PASS：脚本已编写并完成生产只读预览；当前无可安全补齐候选，因此未运行 `--apply`，无业务数据变更。
- AC-7 PASS locally：固定计划、局部更新、并发保护、写前日志和字段级回退通过模拟ES的可执行测试；生产ES更新与Painless回退尚未执行，不能声称真实写入路径已验证。
- 52条源记录/身份异常未修复；142条历史文件依旧采用当前库回退。恢复真实原始库ID属于事实源回填，需沿版本/发布链确认，不能通过看板空值补齐脚本猜测。
- 公司/部门/科室/班组空值并不都可补齐；本轮有效记录与当前原始库组织映射一致。组织级别未提供、组织映射缺失等来源问题不在脚本中推断补造。
- 本地代码未提交、未推送，未部署业务镜像；仅上传独立脚本并执行只读检查。

## 2026-10-20 原始来源事实核实（待生产写入确认）

进一步核实表明，上轮“零候选”仅适用于以当前数据库来源字段计算的统计空值补齐。数据库缺失原始库ID的142条在沿历史来源解析后，原始库全部与当前回退库不同，存在可修复来源，不能将上轮结果理解为全部来源已正确。

| Evidence | 操作 | 结果 |
|---|---|---|
| E-010 | 比对本地与生产 `scripts/backfill_knowledge_file_original_origin.py` SHA256 | 一致：`69c875307d96b1770472a5c2a370ed49004acef4bc38a07f253c28bddf180b4e` |
| E-011 | 生产运行上述脚本 `--tenant-id 1 --limit 1000 --sample-limit 1000`，不传apply | PASS，退出0；222条候选、221组，would_update222，updated0，conflict0，broken_chain0，skipped0；结果 `/tmp/origin-source-audit-20261020.log` |
| E-012 | 只读诊断脚本将来源审计候选与ES当前文件、数据库当前有效文件交叉核对，使用原始字段独立对象模拟补齐后的builder输出 | PASS，退出0；当前文件142条、142组、实际数据库写入范围142条、额外组内行0；142条原始库ID和原始上传人ID均缺失，原始库全部不同于回退库；统计变化：原始库名称142条、原始所属部门9条、原始所属科室139条，公司/班组不变 |
| E-013 | `.venv/bin/python -m pytest test/knowledge/test_backfill_knowledge_file_original_origin.py -q --disable-warnings` | PASS，8 passed，0.47s；覆盖来源回填的普通文件、发布链、文档组、断链、冲突、跨租户及重复执行保护；日志 `/tmp/origin-source-backfill-tests-20261020.log` |

生产定向清单：`/tmp/origin-source-scoped-plan-20261020.json`（0600，含142条旧值、新值、来源组和统计字段差异）。SHA256：`f3045dc90fc5b3033eb8623956a2321bad6b89cc48ac50245527bb2331b612ea`。

示例97415：当前库3997“培训资源”回退；来源解析为3769“宣传室（党群）”、原始上传人18693。由此补出“北京首钢股份有限公司党群工作部(工会)”及“北京首钢股份有限公司党群工作部(工会)宣传室(企业文化室)”。不能只给统计空字段补值而保留错误的回退库名称。

诊断脚本前两版只读模拟失败：ORM深复制复用状态，随后model_dump将日期序列化成字符串。最终使用SimpleNamespace复制原始字段值，模拟成功；三次尝试均无数据库commit或ES写入。

拟执行范围：仅上述142个文件组，复用已验证的来源解析与条件更新机制，补原始库ID和原始上传人ID，再触发这142条的现有文件统计刷新。写前重新解析来源并比对固定清单，持久化旧值和操作日志；冲突则停止。另80条非当前看板候选、52条既有统计身份/来源异常、历史事件均不纳入本次。

风险和回退：将修改生产数据库来源事实，纠正原来由当前库回退得到的统计展示；不迁移文件、不给已有计数补造事件。数据库源字段回退必须逐条核对仍等于本次新值后恢复旧值，再刷新对应统计；有后续变化时停止人工核对，禁止覆盖。当前尚未执行此写入，生产写入0；需用户确认该明确范围后继续。
