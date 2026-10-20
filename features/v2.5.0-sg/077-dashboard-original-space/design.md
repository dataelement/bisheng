# 设计

## 数据流与落点

1. `telemetry_search/domain/init_dataset.py` 新增 `original_space_name` 中文维度，四级中文名称调整为“原始所属…”，保留 `original_upload_*` 标识；沿用启动时数据集幂等刷新。
2. `telemetry/domain/repositories/{interfaces,implementations}/knowledge_statistics_repository*` 批量读取原始空间名称及租户，避免逐文件查询。
3. `worker/telemetry/mid_table.py` 复用 `original_knowledge_id` 及现有回退、组织映射；仅使用同租户的空间名称。
4. `telemetry/domain/mid_table/knowledge_space_content.py` 增加可空名称及 keyword mapping，文件构建器接收名称；继续通过差异对账写入当前文件投影。
5. `knowledge_space_content_dimensions.py` 扩展事件快照字段。将旧日ID参与字段单独固定，新增来源字段不加入hash，避免新旧事件同一天形成不同身份、重放后重复计数。日投影继续使用单调绝对计数；新事件可补齐同一日记录缺失的来源字段，已有来源值不覆盖，旧事件重放不清空新字段。
6. 通用查询、枚举、导出已使用数据集维度；复用现有组织简称解析，不新增前端字段特判。

## 验证及回退

V2：测试同文档不同入口的原始库归属、缺失回退、跨租户拒绝名称、数据集中文契约、事件投影和稳定ID、中文筛选组件。复用现有统计去重、对账和导出测试，进行真实浏览器组件检查。无需关系库迁移及外部数据变更。回退代码后额外ES字段可忽略，旧字段标识和日ID保持兼容。

## 风险

旧日记录没有保存来源字段，不能依靠刷新自动恢复；本次只保证后续事件携带新维度。历史文件无原始ID时沿用已确认回退口径。已有图表自定义显示名继续保留。

## 运维补齐脚本

`scripts/backfill_dashboard_original_organizations.py` 扫描指定租户的 ES `file` 快照，复用线上投影 builder 批量读取当前文件与原始空间组织。只提交五个来源字段的缺失值；非空冲突整条跳过，缺失来源不能推断则报告。原始ID缺失沿用当前库回退并计数。计划包含目标索引UUID、租户、空间、文档身份、原值和补充值；正式执行再读取数据库和ES，计划漂移或并发更新立即停止。

ES 写入使用局部 update 和 `if_seq_no` / `if_primary_term`，无 upsert，不创建或删除统计记录。每次写入前将回退信息以0600权限日志fsync，写后读回验证。回退只移除或恢复日志涉及的字段，遇到当前值已变化或身份不同则停止，不恢复整个源文档。预览不会创建索引或更新mapping；正式写入前要求五字段已有keyword mapping，避免隐式结构变更。历史事件与关系数据库不写入。
