# 设计说明 Design：知识空间内容统计增加门户下载次数

## 阅读摘要

- 本设计在每日全量文件投影后，从 `base_telemetry_events` 分页聚合门户下载事件，生成 `download_daily` 日汇总记录。
- 设计重点：事实源过滤、北京时间日桶、当前文件维度补全、确定性文档 ID 和成功后清理。
- 不在本设计中处理：实时投影、下载用户分析、下载链路或权限变更。

## 元信息 Metadata

- Feature ID: `072-dashboard-portal-download-stats`
- Status: `approved`
- Related requirements: `features/v2.6.0/072-dashboard-portal-download-stats/requirements.md`
- Created: `2026-08-06`
- Updated: `2026-08-06`

## 上下文 Context

- 现有架构 Existing architecture: `PortalPdfDownloadService -> PortalTelemetryEventService -> base_telemetry_events` 记录成功下载；`sync_mid_knowledge_space_content_stat -> rebuild_knowledge_space_content_file_projection -> mid_knowledge_space_content_stat` 重建文件快照；数据集按 `record_type` 选择指标事实。
- 已检查文件 Relevant files inspected: `portal_pdf_download_service.py`、`portal_event_service.py`、`base_telemetry_schema.py`、`telemetry_service.py`、`knowledge_space_content.py`、`worker/telemetry/mid_table.py`、`init_dataset.py` 及相关测试。
- 现有测试或验证命令 Existing tests or validation commands: `src/backend/.venv/bin/python -m pytest test/test_knowledge_space_content_telemetry.py test/test_realtime_dashboard.py test/knowledge/pdf/test_portal_pdf_download_service.py -q`；定向 Ruff；`scripts/arch-guard.sh`。
- 项目约束 Constraints from project guidance: 不新增数据库表；保持 DDD 边界；中间表无服务端硬权限过滤；行为改动需回归证据；数据同步失败不得伪成功。

## 目标 / 非目标 Goals / Non-Goals

### 目标 Goals

- 历史及后续门户水印下载可在知识空间内容统计中按日计数。
- 重复全量同步不重复累计。
- 仅保留当前有效文件的下载统计并复用其已有维度。
- 原有四项指标和同步行为保持兼容。

### 非目标 Non-Goals

- 不实现下载事件实时写入中间表。
- 不统计下载人数或下载用户属性。
- 不修改门户下载成功事件的触发时点和内容。
- 不改变看板资源权限和数据范围策略。

## 边界承诺 Boundary Commitments

| Boundary | Allowed Change | Disallowed Change | Revalidation Trigger |
|---|---|---|---|
| 门户下载链路 | 只读取现有成功事件 | 修改下载响应、权限、限额、水印或成功时点 | 事件字段或成功语义变化 |
| 遥测事实源 | 按既有字段过滤、分页聚合 | 修改公共遥测 schema 或重写事件 | 现有事件无法稳定查询 |
| 知识空间中间表 | 新增 download mapping、构建和清理方法 | 改变 file/preview 记录语义 | 需要实时投影或用户维度 |
| 全量同步任务 | 在文件投影后重建下载投影 | 新增调度、数据库迁移或独立队列 | 性能无法满足每日窗口 |
| 看板数据集 | 增加下载次数指标 | 增加硬权限过滤或修改已有指标口径 | 数据范围要求变化 |

- Allowed dependencies: `none`

## 需求追踪 Requirements Traceability

| Requirement | Acceptance Criteria | Design Element | Verification Strategy |
|---|---|---|---|
| REQ-001 | AC-REQ-001-01..04 | `download_daily` 模型、当前文件维度复制、数据集 SUM 指标 | 中间表与数据集契约测试 |
| REQ-002 | AC-REQ-002-01..05 | composite 分页聚合、确定性 ID、sync run cleanup | worker 聚合/幂等/失败路径测试 |
| REQ-003 | AC-REQ-003-01..02 | 独立 `record_type` 与原同步顺序保留 | 既有相关回归集 |

## 架构设计 Architecture

- Pattern: 事件事实源到看板中间表的可重建日汇总投影。
- Rationale: 下载事件已经完整存在于 `base_telemetry_events`，通过全量派生可补历史、可修复且不侵入下载主链路。
- Preserved existing patterns: 与 `preview_daily` 相同的北京时间日粒度和文件维度；与文件全量投影相同的 `sync_run_id` 成功后清理模式。
- Architecture change justification, if any: 仅扩展现有中间表记录类型和全量同步阶段，不新增服务或持久层。

### 数据流

```text
base_telemetry_events
  -- filter: portal_document_download + shougang_portal + success
  -- composite: local day + file_id
  -> download buckets
  -> query current valid KnowledgeFile + Knowledge rows
  -> copy current file dimensions
  -> bulk index download_daily
  -> cleanup stale download_daily after successful rebuild
  -> dashboard SUM(download_count)
```

## 文件结构计划 File Structure Plan

| Path | Action | Responsibility | Linked Requirement |
|---|---|---|---|
| `src/backend/bisheng/telemetry/domain/mid_table/knowledge_space_content.py` | modify | 定义下载日记录 mapping、构建方法与 stale cleanup | REQ-001, REQ-002 |
| `src/backend/bisheng/worker/telemetry/mid_table.py` | modify | 查询、分页聚合、补维度并接入全量同步 | REQ-001, REQ-002, REQ-003 |
| `src/backend/bisheng/telemetry_search/domain/init_dataset.py` | modify | 注册“下载次数”SUM 指标 | REQ-001, REQ-003 |
| `src/backend/test/test_knowledge_space_content_telemetry.py` | modify | 中间表、worker、幂等和失败路径回归 | REQ-001, REQ-002, REQ-003 |
| `src/backend/test/test_realtime_dashboard.py` | modify | 数据集指标契约回归 | REQ-001, REQ-003 |
| `docs/dashboard-dataset-metric-calculation.md` | modify | 更新数据集指标计算说明 | REQ-001 |
| `features/v2.6.0/072-dashboard-portal-download-stats/verification.md` | create | 记录实际验证证据 | REQ-001, REQ-002, REQ-003 |

## 组件与接口 Components and Interfaces

### 下载事件聚合查询

- Responsibility: 从遥测索引读取符合统计口径的下载事件，并分页返回文件/日期桶。
- Inputs: `base_telemetry_events`、事件类型、来源、成功状态、composite `after_key`。
- Outputs: `file_id`、北京时间日期桶、`download_count`。
- Dependencies: statistics Elasticsearch sync client。
- Error behavior: 查询或响应解析失败时抛出异常，由 Celery 任务记录并失败。
- Requirements: REQ-002

### 下载日记录构建

- Responsibility: 用当前有效文件投影维度丰富下载桶。
- Inputs: 下载桶、`KnowledgeFile`、`Knowledge`、上传人/部门/分类映射、`sync_run_id`。
- Outputs: `record_type=download_daily` 的中间表记录。
- Dependencies: 复用现有 `_build_knowledge_space_content_records` 或等价维度构建能力。
- Error behavior: 找不到当前有效文件时跳过；构建失败则终止本次全量同步。
- Requirements: REQ-001, REQ-002

### 全量下载投影

- Responsibility: 分批重建全部下载日记录，并在全部写入成功后清理旧记录。
- Inputs: owner lock、`sync_run_id`。
- Outputs: `synced_download_daily`、`deleted_stale_download_daily` 等任务结果字段。
- Dependencies: 现有知识空间投影锁和 ES bulk API。
- Error behavior: 任一查询/写入失败时不执行 stale cleanup，异常继续向上抛出。
- Requirements: REQ-002, REQ-003

### 数据集指标

- Responsibility: 将下载日记录的 `download_count` 求和。
- Inputs: `record_type=download_daily`、允许的 `space_level`、用户配置的时间和维度筛选。
- Outputs: 数值型“下载次数”。
- Dependencies: 现有 `MetricConfig`、`FilterExpression`、`SUM` 聚合。
- Error behavior: 沿用既有数据集查询错误处理。
- Requirements: REQ-001, REQ-003

## 数据 / 状态变化 Data / State Changes

- Entities: Elasticsearch 中间表新增逻辑记录类型 `download_daily`。
- Persistence changes: mapping 新增 `download_count: long`；记录字段复用现有文件/空间/组织维度，另含 `record_type`、`sync_run_id`、`local_date`、`timestamp`。
- Document ID: `download_{file_id}_{YYYY-MM-DD}`，保证同一文件同一天只有一个可覆盖日汇总。
- Migration or rollback: 无数据库迁移；首次部署后手工或定时重跑全量任务即可补历史。回滚代码后可按 `record_type=download_daily` 删除新增记录，已有指标不受影响。
- Compatibility: 现有索引通过 `put_mapping` 增量增加字段；旧数据无需转换。

## 聚合与同步算法

1. 文件快照继续按现有逻辑完成全量投影和 stale file cleanup。
2. 对 `base_telemetry_events` 执行 filter：
   - `event_type=portal_document_download`
   - `event_data.portal_document_download_source_app=shougang_portal`
   - `event_data.portal_document_download_status=success`
3. 使用 composite aggregation 按 `timestamp` 的北京时间自然日和 `event_data.portal_document_download_file_id` 分桶，并用 `after_key` 分页。
4. 每页批量查询当前有效知识空间文件；不存在、已删除、非成功文件、收藏库或非允许空间层级均不生成记录。
5. 复用当前文件维度构建逻辑，生成确定性 `download_daily` 文档并 bulk index。
6. 所有分页成功后，刷新索引并删除 `record_type=download_daily AND sync_run_id!=current_run` 的旧记录。
7. 将下载同步数量和清理数量写入 Celery 返回结果及结构化日志。

## 测试策略 Testing Strategy

| Acceptance IDs | Risk / Level | Distinct Outcomes | Primary Layer | Evidence Group | Stop Condition |
|---|---|---|---|---|---|
| AC-REQ-001-01..04 | medium/V2 | 下载桶转日记录、重复事件累加、指标契约 | unit/service contract | EG-001 | 下载记录和指标过滤/聚合断言通过 |
| AC-REQ-002-01..04 | medium/V2 | 查询口径、分页、幂等、无效文件跳过与清理 | worker unit with ES/DAO fakes | EG-002 | 所有独立数据结果有回归覆盖 |
| AC-REQ-002-05 | medium/V2 | 失败不清理且任务抛错 | worker failure-path unit | EG-002 | 失败路径断言通过 |
| AC-REQ-003-01..02 | medium/V2 | 原四指标、文件/预览/收藏清理兼容 | existing module regression | EG-003 | 相关既有回归集无失败 |

## 设计决策 Decisions

### Decision: 使用日汇总而不是复制每条下载事件

- Context: 看板只需要下载次数，原始事件已经永久存在于事实索引。
- Options considered: 每事件复制一条记录；直接查询事件索引；按文件/日期生成日汇总。
- Decision: 生成 `download_daily` 日汇总。
- Rationale: 与 `preview_daily` 粒度一致，减少中间表体积，同时保留所有现有业务维度。
- Consequences: 看板不能展示单次下载明细或下载用户；这是已确认的非目标。

### Decision: 全量可重建，不在下载链路实时双写

- Context: 现有下载遥测为异步 best-effort 写入，双写中间表会引入顺序、补偿和重复问题。
- Options considered: 下载成功时实时双写；独立增量消费者；每日全量派生。
- Decision: 由现有 `sync_mid_knowledge_space_content_stat` 每日或手工重建下载投影。
- Rationale: 用户要求补历史且指定该同步任务；全量派生天然可恢复和幂等，改动面最小。
- Consequences: 指标存在最长约 24 小时延迟，手工重跑可立即刷新。

### Decision: 历史记录使用当前文件维度

- Context: 旧下载事件只保存空间/文件 ID，没有文件名称、分类和组织快照。
- Options considered: 无法恢复的维度显示 unknown；只按 ID 统计；关联当前文件快照。
- Decision: 仅关联当前仍有效的文件并使用其当前维度。
- Rationale: 与“知识空间内容统计”当前内容口径一致，并满足用户排除已删除文件的确认。
- Consequences: 维度变更会让历史下载随当前维度展示。

## 风险 / 取舍 Risks / Trade-Offs

| Risk | Impact | Mitigation | Owner / Phase |
|---|---|---|---|
| 历史事件量大 | 同步超过每日窗口 | composite 分页、批量查文件、批量写入；记录耗时和数量 | implementation |
| 动态字段精确查询路径不一致 | 历史下载漏统计 | 针对实际序列化字段写查询契约测试；必要时兼容 keyword 子字段 | implementation |
| 同步中途失败 | 部分新记录写入但旧记录未清理 | 确定性 ID 覆盖；仅全部成功后 cleanup；下次运行修复 | implementation |
| 指标非实时 | 用户刚下载后看板暂未变化 | 文档明确每日调度与手工重跑方式 | release/ops |
| 遥测事件历史缺失 | 无法恢复缺失下载 | 如实沿用事件事实源，不推算数据 | accepted |

## 设计质量门 Design Quality Gate

- [x] Every requirement ID is represented in Requirements Traceability.
- [x] Every acceptance criterion has a verification strategy.
- [x] Verification uses the lowest sufficient layer and avoids duplicate commands across acceptance criteria.
- [x] Test cases map to distinct outcomes/risks instead of tasks, branches, roles, or raw input count.
- [x] One primary test layer is selected per behavior unless a boundary has independent risk.
- [x] Boundary Commitments include allowed and disallowed changes.
- [x] Every changed file has one clear responsibility and linked requirement.
- [x] Existing architecture is preserved or changes are justified.
- [x] Runtime prerequisites, migrations, and risky operations are explicit.
- [x] No speculative abstractions are included.
