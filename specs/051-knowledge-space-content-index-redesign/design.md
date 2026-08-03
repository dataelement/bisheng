# 设计说明 Design: 知识空间内容统计索引重设计

## 阅读摘要
- 本文档说明：在保留单一数据集和单一索引的前提下，将文件事实改为覆盖快照、将预览事实改为每日原子汇总，并建立受保护、可恢复的准实时投影链路。
- 设计重点：双粒度文档契约、稳定 `_id`、租约队列、owner lock、ES 可见性、预览维度固化、看板聚合变更和破坏性重建保护。
- 不在本设计中处理：预览明细、历史迁移、事务 Outbox、严格一次计数、小时级统计、未来多租户兼容和前端改造。
- 本设计未读取或引用项目中已有 SDD spec。

## 元信息 Metadata
- Feature ID: `051-knowledge-space-content-index-redesign`
- Status: `approved`
- Related requirements: `specs/051-knowledge-space-content-index-redesign/requirements.md`
- Created: `2026-08-03`
- Updated: `2026-08-03`

## 上下文 Context
- 现有架构 Existing architecture: `KnowledgeSpaceContentStat` 在 `mid_knowledge_space_content_stat` 中混存 `record_type=file` 快照和 `record_type=preview` 单次事件；文件增量通过 Redis Set + Celery 消费，文件全量每日校准；看板配置从 MySQL `dashboard_dataset` 读取后生成单索引 ES 聚合。
- 实时性缺口 Freshness gaps: 当前 Worker 使用 `SRANDMEMBER -> 处理 -> SREM`；同一 ID 在处理期间再次 `SADD` 会被 Set 去重，并可能被旧任务的 `SREM` 一并删除。同步锁固定 60 秒、没有 owner token 或续租；ES 索引也未显式声明 `refresh_interval`。
- 已检查文件 Relevant files inspected:
  - `src/backend/bisheng/telemetry/domain/mid_table/knowledge_space_content.py`
  - `src/backend/bisheng/telemetry/domain/mid_table/base.py`
  - `src/backend/bisheng/worker/telemetry/mid_table.py`
  - `src/backend/bisheng/telemetry_search/domain/init_dataset.py`
  - `src/backend/bisheng/telemetry_search/domain/services/component.py`
  - `src/backend/bisheng/telemetry_search/domain/services/dashboard.py`
  - `src/backend/bisheng/core/config/settings.py`
  - `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`
  - `src/backend/bisheng/knowledge/domain/services/knowledge_recycle_service.py`
  - `src/backend/bisheng/knowledge/domain/services/knowledge_version_service.py`
  - `src/backend/test/test_knowledge_space_content_telemetry.py`
  - `src/backend/test/test_realtime_dashboard.py`
  - `src/backend/test/knowledge/test_knowledge_recycle_bin.py`
  - `src/backend/test/knowledge/test_knowledge_version_service_set_primary.py`
  - `src/backend/test/knowledge/test_knowledge_version_service_delete.py`
- 现有测试或验证命令 Existing tests or validation commands:
  - `cd src/backend && uv run pytest test/test_knowledge_space_content_telemetry.py -q`
  - `cd src/backend && uv run pytest test/test_realtime_dashboard.py -q`
  - `cd src/backend && uv run ruff format <changed-files>`
  - `cd src/backend && uv run ruff check <changed-files>`
- 项目约束 Constraints from project guidance: 修改前读取上下文；最小必要 diff；行为变更必须有可执行证据；迁移和删除属于高风险操作；实际删除前必须解析精确目标并再次确认；后端 Python 使用类型标注和项目格式工具。

## 目标 / 非目标 Goals / Non-Goals

### 目标 Goals
- 文件更新只覆盖 `_id=str(file_id)` 的单条快照。
- 所有影响文件快照内容或有效性的更新、删除、恢复及版本切换都显式触发受影响文件重投影。
- 正常条件下文件变化 30 秒内、成功预览累计 5 秒内可由看板查询到。
- 同一对象处理期间再次发生变化时不丢刷新信号；Worker 崩溃后租约任务 5 分钟内恢复。
- 全量、增量和重建任务通过可续租 owner lock 串行，非 owner 不得释放锁。
- 预览次数按文件和中国自然日聚合，并支持当前日、周、月、年看板统计。
- 文件和预览指标继续通过原数据集、原索引查询。
- 文件全量校准不影响历史预览日汇总。
- 提供默认只读、精确限定目标的索引重建入口。

### 非目标 Non-Goals
- 不保存预览事件明细、浏览人信息或 `event_id` 去重集合。
- 不从旧索引迁移历史预览数据。
- 不保证预览计数的重放、修复或 exactly-once。
- 不通过数据库事务 Outbox/CDC 实现事务级事件不丢；Redis 入队失败时仍可能等到每日全量校准。
- 不承诺写请求返回后立即 read-your-write；实时性以已确认的 30 秒/5 秒窗口验收。
- 不增加跨索引 Join、前端接口、第三方依赖或多租户兼容层。

## 边界承诺 Boundary Commitments
| Boundary | Allowed Change | Disallowed Change | Revalidation Trigger |
|---|---|---|---|
| `telemetry/domain/mid_table/knowledge_space_content.py` | 文档模型、mapping、文件覆盖写、预览日汇总原子更新、leased queue、owner lock 和索引刷新设置 | 修改其他中间表或通用 ES 基类语义 | 需要跨索引、原始事件或租户隔离时 |
| `worker/telemetry/mid_table.py` | 原子 claim/ack/reclaim、文件增量、全量锁、陈旧文件清理、延迟观测 | 改动其他 telemetry 定时任务 | 需要迁移历史预览或更换队列系统时 |
| `core/config/settings.py` | 为该投影增加 60 秒租约回收检查 | 修改其他 beat 任务周期 | 恢复目标或队列机制变化时 |
| `knowledge/domain/services/` 文件生命周期服务 | 在业务操作成功且状态可读后发送受影响文件刷新 ID | 为统计刷新改变文件业务事务结果，或引入事务 outbox | 要求严格实时、严格不丢事件时 |
| `telemetry_search` | 当前数据集指标配置与知识空间专属 scope filter | 修改实时问答、参与度或前端返回契约 | 启用多租户或拆分数据集时 |
| `scripts/` | 新增精确目标的 dry-run/reset/rebuild 工具及说明 | 自动在启动或部署时删除索引 | 需要无停机或可回滚迁移时 |
| `test/` | 更新直接相关行为和权限测试 | 扩展为全项目无关回归 | 影响面扩展到其他数据集时 |

- Allowed dependencies: `none`

## 需求追踪 Requirements Traceability
| Requirement | Acceptance Criteria | Design Element | Verification Strategy |
|---|---|---|---|
| REQ-001 | AC-REQ-001-01..04 | 文件快照模型、确定性 ID、增量/全量同步 | EG-001 文件投影单元测试 |
| REQ-002 | AC-REQ-002-01..05 | 预览日汇总 scripted upsert、UTC+8 日期、维度固化 | EG-002 原子累计和失败路径测试 |
| REQ-003 | AC-REQ-003-01..04 | 数据集 metric filter 和 `sum(preview_count)` | EG-003 数据集/query builder 测试 |
| REQ-004 | AC-REQ-004-01..04 | 知识空间专属无租户 scope 分支 | EG-004 权限范围测试 |
| REQ-005 | AC-REQ-005-01..05 | 受保护重建脚本、dry-run、结果报告 | EG-005 脚本测试 + 人工运行证据 |
| REQ-006 | AC-REQ-006-01..06 | leased pending/processing、租约回收、owner lock | EG-006 同 ID 重入、崩溃恢复和锁所有权测试 |
| REQ-007 | AC-REQ-007-01..05 | 生命周期触发矩阵、成功后入队、Worker 当前状态投影 | EG-007 更新/删除/恢复/版本服务参数化测试 |
| REQ-008 | AC-REQ-008-01..05 | 30 秒/5 秒 SLO、ES refresh、积压与延迟观测 | EG-008 配置/日志自动测试 + 部署后计时证据 |

## 架构设计 Architecture
- Pattern: `同索引双粒度投影（mutable file snapshot + append-by-day mutable counter）`
- Rationale: 看板数据集目前只映射一个 `es_index_name`；保留同一索引可避免前端和查询引擎多源改造，同时文件与预览通过 `record_type` 隔离聚合。
- Preserved existing patterns: 继续使用 `BaseMidTable` 管理索引、确定性 ES `_id` 实现幂等覆盖、Redis 合并文件变更、Celery 执行增量/全量投影、数据集 schema 驱动 ES 聚合。
- Architecture change justification, if any: 单次预览事件改为每日计数文档，目的是在保留时间维度的同时消除事件级文档增长；文件 `_id` 改为原始文件 ID；Redis 单 Set 改为 leased pending/processing，目的是消除处理期间同 ID 再入队被旧 ack 删除的窗口。

### 总体数据流

```text
MySQL current successful primary files
  -> file projection builder
  -> ES _id={file_id}, record_type=file (full overwrite)

File lifecycle mutation succeeds and current state is readable
  -> ZADD NX work item into pending ZSET
  -> Worker atomically moves a batch pending -> processing lease
  -> reload MySQL current state
     - eligible: overwrite ES _id={file_id}
     - missing/ineligible: delete record_type=file only
  -> success: ack processing lease only
  -> same item changes during processing: remains in pending for next batch
  -> crash/lease expiry: periodic recovery moves item back to pending

Successful preview
  -> GET ES _id={file_id}
  -> derive China local_date
  -> ES scripted upsert _id=preview_{file_id}_{local_date}
     - create: freeze snapshot dimensions + preview_count=1
     - update: preview_count += 1 only

Shared owner lock
  -> unique token + TTL
  -> renew during each page/batch
  -> compare token before renew/release/write/ack

Dashboard
  -> file metrics filter record_type=file
  -> preview metric filter record_type=preview_daily
  -> sum(preview_count)
```

## 文件结构计划 File Structure Plan
| Path | Action | Responsibility | Linked Requirement |
|---|---|---|---|
| `src/backend/bisheng/telemetry/domain/mid_table/knowledge_space_content.py` | modify | 双粒度模型、文件 ID、预览原子累计、leased queue/owner lock、`refresh_interval=1s`、移除预览重试 | REQ-001, REQ-002, REQ-004, REQ-006, REQ-008 |
| `src/backend/bisheng/worker/telemetry/mid_table.py` | modify | 原子 claim/ack/reclaim、文件增量/全量投影、锁续租、延迟观测、移除预览 payload 消费 | REQ-001, REQ-006, REQ-007, REQ-008 |
| `src/backend/bisheng/core/config/settings.py` | modify | 每 60 秒触发一次过期 processing 回收检查 | REQ-006, REQ-008 |
| `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py` | modify | 文件属性更新、单个/批量/文件夹级联删除成功后刷新全部受影响文件 ID | REQ-007 |
| `src/backend/bisheng/knowledge/domain/services/knowledge_recycle_service.py` | modify | 回收站软删除、恢复、冲突替换和永久删除成功后刷新实际受影响文件 ID | REQ-007 |
| `src/backend/bisheng/knowledge/domain/services/knowledge_version_service.py` | modify | 主版本切换和版本删除成功后刷新新旧及级联关联文件 ID | REQ-007 |
| `src/backend/bisheng/telemetry_search/domain/init_dataset.py` | modify | 预览指标改为 `sum(preview_count)` 并保留原数据集标识 | REQ-003 |
| `src/backend/bisheng/telemetry_search/domain/models/dashboard_dataset.py` | modify | 为累计总数增加向后兼容的可配置基础聚合类型 | REQ-003 |
| `src/backend/bisheng/telemetry_search/domain/services/component.py` | modify | 无时间维度总数查询使用指标声明的基础聚合类型 | REQ-003 |
| `src/backend/bisheng/telemetry_search/domain/services/dashboard.py` | modify | 知识空间数据集移除租户 scope，保留空间管理范围 | REQ-004 |
| `src/backend/scripts/rebuild_knowledge_space_content_stat.py` | create | dry-run、精确确认、删除/建索引、刷新设置、队列状态、重建和结果报告 | REQ-005, REQ-006, REQ-008 |
| `src/backend/scripts/README.md` | modify | 重建前提、命令、风险和运行后验证说明 | REQ-005 |
| `src/backend/test/test_knowledge_space_content_telemetry.py` | modify | 文件覆盖、预览日累计、清理、锁、队列和脚本行为测试 | REQ-001, REQ-002, REQ-005, REQ-006, REQ-007, REQ-008 |
| `src/backend/test/test_knowledge_space_content_realtime.py` | create | 同 ID 重入、原子 claim/ack、租约回收、owner lock、刷新设置和观测字段测试 | REQ-006, REQ-008 |
| `src/backend/test/test_realtime_dashboard.py` | modify | 数据集聚合与无租户知识空间 scope 测试 | REQ-003, REQ-004 |
| `src/backend/test/knowledge/test_knowledge_space_content_projection_events.py` | create | 文件属性更新、单个/批量/文件夹级联删除的刷新触发测试 | REQ-007 |
| `src/backend/test/knowledge/test_knowledge_recycle_bin.py` | modify | 回收站删除、恢复、冲突替换和永久删除触发测试 | REQ-007 |
| `src/backend/test/knowledge/test_knowledge_version_service_set_primary.py` | modify | 主版本切换的新旧文件触发测试 | REQ-007 |
| `src/backend/test/knowledge/test_knowledge_version_service_delete.py` | modify | 版本删除与级联文件触发测试 | REQ-007 |

## 组件与接口 Components and Interfaces

### File snapshot projection
- Responsibility: 将当前有效文件及其看板维度序列化为唯一可覆盖快照。
- Inputs: `KnowledgeFile`、`Knowledge`、空间范围、空间部门、上传人、主部门和分类标签。
- Outputs: `_id=str(file_id)`、`record_type=file` 的完整 ES 文档。
- Dependencies: 现有 MySQL DAO/Service、`BaseMidTable.insert_records_sync()`。
- Error behavior: 批量写失败时抛出异常；文件 pending ID 不确认，由既有文件队列再次调度。
- Requirements: `REQ-001`, `REQ-006`, `REQ-007`

### File lifecycle projection triggers
- Responsibility: 在会改变快照字段或投影资格的文件业务操作成功后，将实际受影响文件 ID 送入 pending ZSET；不直接构造 ES 文档。
- Inputs: 业务操作类型、持久化完成后的新增/更新/删除/恢复文件 ID，以及版本或级联计划展开得到的关联 ID。
- Outputs: 去重后的 work item 和一次增量同步调度；重复触发不改变最早等待时间，处理期间新触发会创建下一轮 pending。
- Dependencies: `KnowledgeSpaceContentStat.enqueue_file_stat_async()`、每日全量校准兜底。
- Error behavior: 业务操作失败或回滚时不入队；业务成功后入队失败只记录操作类型和完整 ID，不回滚业务，由每日全量校准最终修复。
- Requirements: `REQ-007`

### Leased projection queue and owner lock
- Responsibility: 无丢信号地领取、确认和恢复文件/空间投影工作，并保证全量、增量和重建串行。
- Inputs: `file:{id}` 或 `space:{id}` work item、当前时间、batch size、lease deadline 和 lock owner token。
- Outputs: pending ZSET、processing ZSET、processing metadata、批次结果和延迟指标。
- Dependencies: Redis ZSET/Hash、Redis Lua/EVAL、Celery Beat；所有多键使用 `{knowledge_space_content}` hash tag 保证 Redis Cluster 同 slot。
- Claim: Lua 按最早入队时间从 pending 原子移入 processing，并记录原入队时间和租约截止时间。
- Ack: 成功后只删除 processing 中本次领取记录；若生产者在处理期间把相同 work item 再次加入 pending，新项保持不变。
- Fail/reclaim: 正常长任务在每页/批次前续租 processing；处理失败不 ack；租约过期后恢复任务把没有更新 pending 的 work item 重新入队并立即调度。
- Lock: value 为唯一 owner token；续租和释放均通过 Lua compare-token；每页/批处理前续租，续租失败立即停止后续写入和 ack。
- Error behavior: Redis 脚本失败时不确认 work item；记录阶段、owner、work item 和异常，等待租约恢复或每日全量兜底。
- Requirements: `REQ-006`, `REQ-008`

#### 触发矩阵 Trigger Matrix
| Operation | Affected IDs | Trigger point | Expected projection |
|---|---|---|---|
| 文件创建、解析成功/失效、重命名、移动、分类、业务域或标签变化 | 被修改文件；文件夹路径变化时包含全部受影响后代文件 | 新状态持久化成功且可查询后 | 有效文件覆盖；失效文件删除快照 |
| 空间名称或部门归属变化 | 空间内当前有效文件，由现有 space pending 批量解析 | 空间变更成功后 | 批量覆盖文件快照 |
| 单文件、批量或文件夹级联删除 | 删除计划展开后的全部实际文件 ID | 删除/软删除成功后 | 删除文件快照 |
| 回收站恢复、冲突替换或永久删除 | 恢复文件、被替换文件及所有级联关联 ID | 恢复或删除操作成功后 | 按当前状态覆盖或删除 |
| 设置主版本或删除版本 | 新旧主版本及版本关系变化涉及的全部文件 ID | 版本事务成功后 | 新主版本覆盖，失效版本删除 |

### Preview daily counter
- Responsibility: 把成功预览累计到文件当日汇总，不保存事件明细。
- Inputs: `file_id`、当前时间；维度来源为 ES 中当前文件快照。
- Outputs: `_id=preview_{file_id}_{YYYY-MM-DD}`、`record_type=preview_daily`、`preview_count` 和固化维度。
- Dependencies: async Elasticsearch client、UTC+8 日期函数。
- Error behavior: 文件快照不存在或 ES 调用失败时记录包含索引名和 `file_id` 的日志；不抛给业务主流程、不入 Redis 重试。
- Requirements: `REQ-002`, `REQ-008`

### Realtime visibility and observability
- Responsibility: 让成功投影在约定窗口内可查询，并提供定位排队、处理和 ES 可见性延迟的证据。
- Inputs: work item 最早入队时间、批次开始/结束时间、ES 响应、队列计数和最后成功时间。
- Outputs: `refresh_interval=1s` 的索引设置；结构化日志或状态报告字段 `pending_count`、`processing_count`、`oldest_pending_age_ms`、`reclaimed_count`、`batch_duration_ms`、`projection_lag_ms`、`last_success_at`、`failure_stage`。
- Dependencies: Elasticsearch 自动 refresh、现有日志系统和看板直接 ES 查询路径；不新增应用结果缓存。
- Error behavior: 依赖异常、重建或异常积压标记 `degraded=true`，不得把降级结果报告为满足正常 SLO。
- Requirements: `REQ-008`

### Dashboard dataset definition
- Responsibility: 把用户选择的指标转换成只针对正确 `record_type` 的 ES 聚合。
- Inputs: 原 `dataset_code`、组件维度和时间条件。
- Outputs: 文件总数/新增数 `value_count(file_id)`、贡献人数 `cardinality(uploader_user_id)` 与预览 `sum(preview_count)`。
- Dependencies: 现有 `DataQueryService` 和 `SearchEngineService`；`MetricConfig.sum_type` 默认保持 `cardinality`，仅该数据集文件总数显式选择 `value_count`；不修改公共查询接口。
- Error behavior: 继续使用现有数据集/指标错误处理。
- Requirements: `REQ-003`

### Scope filter
- Responsibility: 对知识空间数据集施加空间管理范围，但不施加租户范围。
- Inputs: 登录用户、可管理知识空间 ID。
- Outputs: 超级管理员空 scope；部门管理员 `space_id in (...)`；无空间时 `__deny_all__`。
- Dependencies: `PermissionService`、`SpaceChannelMemberDao`。
- Error behavior: 非管理员且非部门管理员继续拒绝访问；其他两个实时数据集行为不变。
- Requirements: `REQ-004`

### Protected rebuild command
- Responsibility: 显式、可观察地重建唯一目标索引。
- Inputs: `--dry-run` 或精确确认参数；运行时 ES/MySQL/Redis 配置。
- Outputs: 预检报告或重建结果报告。
- Dependencies: `KnowledgeSpaceContentStat`、文件全量同步函数、Redis 同步锁。
- Error behavior: 目标不匹配立即退出；任一步失败记录阶段并返回非零；不得继续扩大删除范围。
- Requirements: `REQ-005`, `REQ-006`, `REQ-008`

## 数据 / 状态变化 Data / State Changes

### 文件快照文档
| Field | Type | Rule |
|---|---|---|
| `_id` | string | `str(file_id)` |
| `record_type` | keyword | 固定 `file` |
| `sync_run_id` | keyword/null | 全量校准批次 |
| `timestamp` | date | 文件创建时间，保持现有新增文件口径 |
| `file_id` | keyword | 保留为看板维度和 cardinality 字段 |
| 文件/空间/分类/业务域/上传人/部门字段 | existing mappings | 每次文件投影完整覆盖 |
| `tenant_id` | absent | 不写入、不映射 |
| 通用用户上下文字段 | absent | 不写入重复的 `user_id`、`user_name`、`user_group_infos`、`user_role_infos`、`user_department_infos` |

### 预览日汇总文档
| Field | Type | Rule |
|---|---|---|
| `_id` | string | `preview_{file_id}_{YYYY-MM-DD}` |
| `record_type` | keyword | 固定 `preview_daily` |
| `local_date` | keyword | 中国自然日 `YYYY-MM-DD` |
| `timestamp` | date | 对应中国自然日零点 epoch second |
| `preview_count` | long | upsert 为 1；已有文档原子加 1 |
| 文件/空间/分类/业务域/上传人/部门字段 | same as snapshot subset | 首次创建从文件快照复制，后续不更新 |
| `sync_run_id` | absent/null | 不参与文件全量清理 |
| `tenant_id`, `event_id`, viewer fields | absent | 不保存租户和单次事件明细 |

### 原子更新语义
- 新文档：`upsert` 使用当前文件快照维度、当天日期和 `preview_count=1`。
- 已有文档：Painless script 只执行 `ctx._source.preview_count += 1`；不得 `putAll` 当前快照。
- 并发冲突：使用 ES `retry_on_conflict`，不在应用层重新提交未知结果的请求。
- 文件快照缺失：记录并跳过；不创建缺少完整维度的日汇总。

### Redis 状态
- 新键统一使用 `telemetry:{knowledge_space_content}:*`，保证 Redis Cluster 多键 Lua 位于同一 slot。
- pending 使用 ZSET，member 为 `file:{id}` 或 `space:{id}`，score 为本轮最早入队时间；生产者使用 `ZADD NX` 去重。
- processing 使用 ZSET 保存租约截止时间，并用 Hash 保存原入队时间；claim/renew/ack/reclaim 必须通过原子脚本改变状态。
- 同一 work item 被领取后已从 pending 移除，因此处理期间再次入队会保留为下一轮 pending；ack 只清理 processing。
- processing 初始租约不超过 4 分钟，正常任务在每页/批次前续租；每 60 秒运行恢复检查，使崩溃工作项在最后一次成功领取或续租后的 5 分钟内回到 pending。
- 调度标记与 owner lock 使用相同 hash tag；owner lock 持有唯一 token，可续租且 compare-token 释放。
- 删除新代码对 `PREVIEW_PENDING_KEY` 的写入和消费。
- 重建脚本可清理精确的旧 Set、预览 pending 和过期 processing 键，避免遗留无消费者数据。

### Elasticsearch 可见性
- 索引创建和重建显式设置 `refresh_interval=1s`，现有索引在执行真实重建前由 dry-run 报告当前设置。
- 文件 bulk 和预览 scripted update 不传逐条 `refresh=true`/`wait_for`，由索引自动 refresh 控制可见性和吞吐。
- 看板继续直接查询 ES，不新增超过实时性窗口的应用缓存。

### Migration or rollback
- Migration: 部署所有新版本 API/Celery 进程后，先 dry-run 并报告旧/新 Redis 键和 ES refresh 设置；最终确认后使用 owner lock 停止消费，删除原索引，按新 mapping 与 `refresh_interval=1s` 创建并全量重建文件快照；不迁移旧预览事件；清理精确旧键，释放锁后调度新 pending。
- Rollback: 代码可以回退，但已清空的历史预览数据不能恢复；因此数据级 rollback 明确为 unavailable。
- Availability: 用户已接受重建期间看板为空或部分可见。
- Compatibility: `dataset_code`、`es_index_name`、前端接口及已有可见指标名称保持不变；未来启用多租户不兼容。

## 测试策略 Testing Strategy
选择以单元/模块测试为主，覆盖并发脚本、删除范围和 scope 过滤；真实 ES 删除只允许在人工确认后的运行验证中执行。

| Acceptance IDs | Risk / Level | Distinct Outcomes | Primary Layer | Evidence Group | Stop Condition |
|---|---|---|---|---|---|
| AC-REQ-001-01..04 | medium/V2 | 稳定 ID、覆盖、失效删除、预览保留 | module unit tests | EG-001 | 文件投影和清理查询均有可观察断言 |
| AC-REQ-002-01..05 | high/V2 | 首次创建、同日并发、跨日、维度冻结、失败无重试 | unit tests with fake ES | EG-002 | 主路径和两个失败结果均覆盖 |
| AC-REQ-003-01..04 | medium/V2 | 文件聚合、预览 sum、时间聚合、初始化刷新 | schema/query tests | EG-003 | 生成的 metric config/DSL 与契约一致 |
| AC-REQ-004-01..04 | high/V2 | admin、department admin、deny-all、其他数据集不变 | service unit tests | EG-004 | 知识空间与其他实时数据集差异均覆盖 |
| AC-REQ-005-01..05 | high/V3 | dry-run、错误确认、限定删除、重建报告、执行门禁 | script tests + manual | EG-005 | 自动测试不触达真实 ES；人工证据记录精确目标和计数 |
| AC-REQ-006-01..06 | high/V2 | 同 ID 重入、失败不 ack、租约恢复、owner lock 续租/释放 | deterministic worker tests | EG-006 | 可控时钟下无信号丢失且失锁任务停止 |
| AC-REQ-007-01..05 | high/V2 | 更新、级联删除、恢复、主版本变化、事务/入队失败 | service + worker unit tests | EG-007 | 所有触发类别均证明完整 ID 集合和正确投影分支 |
| AC-REQ-008-01..05 | high/V3 | 正常 30 秒/5 秒、刷新设置、观测字段、degraded 边界 | config/unit + timed integration/manual | EG-008 | 自动行为通过且真实环境计时证据满足窗口 |

## 设计决策 Decisions

### Decision: 同一索引保留两种记录粒度
- Context: 一个看板数据集当前只绑定一个 `es_index_name`，用户要求继续使用同一数据集。
- Options considered: 单一索引双类型；拆成两个数据集；扩展查询层跨索引。
- Decision: 使用 `record_type=file` 和 `record_type=preview_daily` 同索引存储。
- Rationale: 最小化查询层和前端影响，并让两类指标通过过滤器明确隔离。
- Consequences: 所有指标必须带 `record_type` 过滤；错误过滤会造成跨粒度误计。

### Decision: 每日汇总而非文件生命周期累计
- Context: 用户需要时间维度统计，单文件累计值无法回溯每日变化。
- Options considered: 生命周期字段；日汇总；单次事件。
- Decision: 每文件每天一条日汇总。
- Rationale: 日粒度能支持现有日/周/月/年聚合，同时显著减少文档数量。
- Consequences: 不支持小时和事件级分析。

### Decision: 预览维度首次创建后冻结
- Context: ES 不支持把日汇总与当前文件快照进行查询时 Join。
- Options considered: 冻结事件时维度；文件更新级联历史；日汇总只存 ID。
- Decision: 首次创建时复制当前文件快照维度，后续只更新计数。
- Rationale: 保留历史统计语义并避免文件更新改写大量历史文档。
- Consequences: 历史记录可能显示旧文件名、旧分类或旧空间名称。

### Decision: 不保存预览原始事件且失败不业务重试
- Context: 用户明确选择只维护日汇总并接受失败少计。
- Options considered: 原始事件 + 校准；重试；日汇总内事件 ID 去重；失败即记录。
- Decision: ES 原子更新失败只记录日志。
- Rationale: 避免重试导致重复累计和文档内无界事件 ID。
- Consequences: 计数不可重放、不可修复，可能少计。

### Decision: 原索引直接清空重建
- Context: mapping 和 `_id` 结构改变，用户不要求保留历史预览。
- Options considered: V2 索引切换；原索引重建并迁移历史；原索引重建且历史清零。
- Decision: 受保护地删除并重建原索引，不迁移预览历史。
- Rationale: 满足用户选择且避免维护双索引。
- Consequences: 不可数据回滚，重建期间数据部分可见；必须独立最终确认。

### Decision: 显式生命周期触发加每日全量兜底
- Context: 现有更新入口已有部分 `enqueue_file_stat_async()` 调用，但单文件和批量删除等入口没有完整触发，导致索引只能等待每日校准。
- Options considered: 仅每日全量；各业务入口显式触发；新增事务 outbox。
- Decision: 所有影响快照的业务入口在成功后显式发送实际受影响 ID，并保留每日全量校准兜底；本次不引入 outbox。
- Rationale: 复用 Redis/Celery 投影机制即可获得及时、幂等的覆盖或删除，同时控制改动范围。
- Consequences: 入队与数据库事务之间不是原子提交，入队失败时可能在下一次全量校准前短暂陈旧，但不影响文件业务操作结果。

### Decision: leased dirty queue 替代单 pending Set
- Context: `peek -> process -> SREM` 会在同一 ID 处理期间再次更新时丢失新信号，且 Worker 崩溃没有 processing 租约可恢复。
- Options considered: 保留单 Set；pending/processing 租约；Redis Stream；数据库事务 Outbox。
- Decision: 使用 Redis Cluster 同 slot 的 pending/processing ZSET + metadata Hash，通过 Lua 原子 claim/ack/reclaim；每 60 秒检查过期租约。
- Rationale: 在不新增数据库表和第三方依赖的前提下消除已确认的重复更新竞态，并支持 5 分钟内崩溃恢复。
- Consequences: 保证的是队列内刷新不丢，不保证业务提交与首次 Redis 入队的事务原子性。

### Decision: owner token lock 与 ES 自动 refresh
- Context: 固定 TTL、无 owner 的锁可能过期重入并被旧任务误删；未声明 ES refresh 无法形成可验证的可见性目标。
- Options considered: 固定 TTL 锁；owner token + 续租；外部分布式锁依赖；每次写强制 refresh；索引自动 refresh。
- Decision: owner token 锁按页/批续租并 compare-token 释放；索引设置 `refresh_interval=1s`，不逐条强制 refresh。
- Rationale: 避免长任务并发写和错误解锁，同时在吞吐与 5 秒预览可见目标之间取得平衡。
- Consequences: 依赖健康且无异常积压时才能满足 SLO；真实环境仍需计时验证。

## 风险 / 取舍 Risks / Trade-Offs
| Risk | Impact | Mitigation | Owner / Phase |
|---|---|---|---|
| 预览累计失败不可恢复 | 预览数少计 | 结构化错误日志和监控；不伪装成功重试 | implementation/operations |
| 双粒度过滤遗漏 | 文件或预览指标误计 | 数据集配置测试和查询 DSL 测试 | implementation |
| 旧进程写回旧文档 | 重建后混入 `preview` 或 `file_*` | 重建前确认 API/Celery 全部部署新版本 | operations |
| 全量与增量竞争 | 新文件快照被陈旧清理误删 | 共享锁；重建后处理积压 pending | implementation |
| 同一 ID 处理期间再次更新 | 新信号被旧 ack 删除，快照陈旧至每日校准 | pending/processing 原子 claim，ack 只清 processing | implementation |
| 长任务锁过期或旧 owner 误释放 | 全量、增量或重建并发写 | token 化锁、续租、compare-token 释放和失锁停止 | implementation |
| processing 租约恢复异常 | 工作项永久卡住或重复处理 | 60 秒检查、5 分钟恢复目标、幂等覆盖和可控时钟测试 | implementation/operations |
| Redis Cluster 跨 slot | Lua 多键操作失败 | 所有相关键共享 `{knowledge_space_content}` hash tag | implementation |
| ES 自动 refresh 或队列积压超标 | 30 秒/5 秒 SLO 不满足 | 显式 1 秒 refresh、队列/延迟观测和 degraded 标记 | implementation/operations |
| 生命周期入口漏发刷新 | 更新或删除后快照短暂陈旧 | 显式触发矩阵、服务参数化测试和每日全量兜底 | implementation |
| 业务成功后入队失败 | 快照延迟到每日校准才修复 | 记录操作类型和完整 ID；监控日志；不回滚业务 | implementation/operations |
| 原索引删除不可恢复 | 历史预览永久丢失 | dry-run、精确确认、显示计数、独立最终确认 | operations |
| 移除租户隔离 | 未来多租户数据混合 | 明确 non-goal；启用前更新 spec 和索引 | future scope |

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
