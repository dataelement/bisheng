# 需求说明 Requirements：知识空间内容统计增加门户下载次数

## 阅读摘要

- 本文档定义在“知识空间内容统计”数据集中增加门户水印文件“下载次数”指标，并通过现有全量同步任务补齐历史数据。
- 当前状态：`approved`
- 需要重点确认：下载指标在每日 `00:30` 的同步任务或手工重跑后更新，不提供实时刷新。

## 元信息 Metadata

- Feature ID: `072-dashboard-portal-download-stats`
- Status: `approved`
- Mode: `spec-then-implement`
- Created: `2026-08-06`
- Updated: `2026-08-06`
- Source request: 为 `sync_mid_knowledge_space_content_stat` 对应数据集增加门户网站水印文件下载记录统计。

## 需求入口摘要 Intake Summary

- 问题 Problem: 门户水印下载已产生 `PORTAL_DOCUMENT_DOWNLOAD` 遥测事件，但“知识空间内容统计”中间表只包含文件快照和预览日汇总，无法在看板中统计下载次数。
- 当前状态 Current state: 门户水印下载在响应首个文件块发送后记录成功事件；全量同步任务每天 `00:30` 运行，但未读取下载事件。
- 目标结果 Target outcome: 数据集新增“下载次数”，历史和后续门户水印下载均可按已有时间、知识空间、文件和组织维度统计。
- 影响对象 Affected users/systems: 门户水印下载遥测、知识空间内容统计中间表、看板数据集初始化配置、Celery 全量同步任务。
- 请求停止点 Requested stopping point: implementation and verification

## 范围 Scope

### 包含 Includes

- `source_app=shougang_portal` 且状态为成功的 `PORTAL_DOCUMENT_DOWNLOAD` 事件。
- 门户知识库、门户首页搜索、推荐、收藏、详情、分享、问答引用等复用门户水印下载服务的入口。
- 按北京时间自然日和当前有效文件维度汇总下载次数。
- 重跑 `sync_mid_knowledge_space_content_stat` 时补齐全部可用历史事件。
- 在“知识空间内容统计”数据集中增加“下载次数”指标。

### 不包含 Excludes

- `bisheng_my_knowledge` 等非门户来源的普通文件下载事件。
- 下载人数、独立用户数或下载用户维度。
- 已禁用的文件夹或批量下载。
- 同步时已经删除、失效或不在知识空间内容统计范围内的文件。
- 实时或准实时下载指标刷新。
- 下载权限、每日下载限额、下载接口响应或水印生成逻辑变更。

## 需求列表 Requirements

### REQ-001: 门户水印下载次数指标

作为看板使用者，我需要在“知识空间内容统计”数据集中选择“下载次数”，以便分析门户知识文档的下载使用情况。

#### 验收标准 Acceptance Criteria

- `AC-REQ-001-01`: WHEN 门户水印文件成功开始传输并记录一个成功下载事件 THEN 下一次成功同步后系统 SHALL 将对应文件的下载次数增加 `1`。
- `AC-REQ-001-02`: WHEN 同一文件存在多个成功门户下载事件 THEN 系统 SHALL 逐次计数，不按用户或文件去重。
- `AC-REQ-001-03`: WHEN 看板按时间、知识空间、知识库大类、知识分类、业务域、部门、上传人或文件等已有维度筛选 THEN “下载次数” SHALL 使用与当前有效文件快照一致的维度参与聚合。
- `AC-REQ-001-04`: WHEN 数据集初始化或升级 THEN schema SHALL 暴露字段 `download_count`、名称“下载次数”，并仅聚合下载日汇总记录。

#### 验证方式 Verification Methods

| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-001-01, AC-REQ-001-02 | V-AC-REQ-001-01 | automated regression | 门户下载事件按文件和北京时间日期汇总，`doc_count` 映射为 `download_count` |
| AC-REQ-001-03 | V-AC-REQ-001-03 | automated regression | 下载日记录复制当前有效文件快照的既有维度 |
| AC-REQ-001-04 | V-AC-REQ-001-04 | dataset contract test | `init_dataset.py` 中指标名称、过滤器与 SUM 聚合断言 |

### REQ-002: 历史补齐与幂等同步

作为运维人员，我需要重跑全量同步任务时安全补齐历史下载数据，以便部署后无需手工修正统计结果。

#### 验收标准 Acceptance Criteria

- `AC-REQ-002-01`: WHEN `sync_mid_knowledge_space_content_stat` 执行 THEN 系统 SHALL 从 `base_telemetry_events` 读取全部符合口径的门户下载事件，并按文件与北京时间自然日汇总。
- `AC-REQ-002-02`: WHEN 同一批历史事件被重复同步 THEN 系统 SHALL 覆盖同一确定性日汇总记录，不得重复累加。
- `AC-REQ-002-03`: IF 下载事件对应文件在同步时已删除、失效、属于收藏库或不属于知识空间成功文件 THEN 系统 SHALL 忽略该事件且清理其既有下载汇总记录。
- `AC-REQ-002-04`: IF 事件来源不是 `shougang_portal`、事件类型不是门户文档下载或状态不是成功 THEN 系统 SHALL 不将其计入下载次数。
- `AC-REQ-002-05`: IF 下载事件读取或下载投影写入失败 THEN 全量任务 SHALL 失败并保留可诊断日志，不得清理未成功重建的既有下载汇总。

#### 验证方式 Verification Methods

| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-002-01, AC-REQ-002-04 | V-AC-REQ-002-01 | worker unit test with ES fake | 事件查询过滤器、北京时间日期桶和分页行为 |
| AC-REQ-002-02 | V-AC-REQ-002-02 | deterministic projection regression | 相同 file/date 使用相同 ES ID，重复执行结果不翻倍 |
| AC-REQ-002-03 | V-AC-REQ-002-03 | worker regression | 当前文件查询过滤与 stale download cleanup |
| AC-REQ-002-05 | V-AC-REQ-002-05 | failure-path regression | 写入失败时不调用 stale cleanup，异常向 Celery 传播 |

### REQ-003: 既有统计行为兼容

作为现有看板使用者，我需要新增下载指标不影响文件数、贡献人数和预览次数，以便已有看板继续按原口径工作。

#### 验收标准 Acceptance Criteria

- `AC-REQ-003-01`: WHEN 新增下载日汇总记录 THEN 总文件数、新增文件数、内容贡献人数和预览次数 SHALL 继续通过各自 `record_type` 过滤，统计结果不包含下载记录。
- `AC-REQ-003-02`: WHEN 全量同步完成 THEN 原有文件快照、预览记录、增量队列和收藏库清理行为 SHALL 保持不变。

#### 验证方式 Verification Methods

| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-003-01 | V-AC-REQ-003-01 | dataset contract regression | 五个指标各自 `record_type` 过滤保持隔离 |
| AC-REQ-003-02 | V-AC-REQ-003-02 | existing regression suite | 知识空间中间表、看板与门户下载相关既有测试通过 |

## 非功能需求 Non-Functional Requirements

- `NFR-001`: 历史事件必须使用 Elasticsearch 分页聚合读取，不能一次加载全部原始事件。
- `NFR-002`: 下载日汇总使用确定性 ES 文档 ID，保证重复同步幂等。
- `NFR-003`: 不新增数据库表、Alembic 迁移、依赖或 Celery 调度项。
- `NFR-004`: 下载统计沿用数据集的无隐式硬权限过滤策略，由看板维度配置控制数据范围。

## 澄清记录 Clarifications

### Session 2026-08-06

- Q: 统计哪些下载入口？ -> A: 统计门户网站水印文件下载，包括门户知识库、门户首页搜索等入口。
- Q: 什么算下载成功？ -> A: 沿用现有口径，开始传输即计数。
- Q: 增加哪些指标？ -> A: 只增加“下载次数”。
- Q: 是否补齐历史？ -> A: 从已有下载事件补齐历史数据。
- Q: 已删除文件是否保留？ -> A: 不保留，只统计同步时仍有效的文件。

## 假设 Assumptions

- 门户水印下载服务记录的 `source_app=shougang_portal` 是识别本需求统计范围的稳定事实。
- 指标可接受在每日同步或手工重跑后更新，因为用户指定的落点是现有全量同步任务，且未要求实时统计。

## 风险 Risks

- `base_telemetry_events.event_data` 使用动态映射，实施前必须用测试锁定实际字段路径和精确值查询形式。
- 文件重命名、分类或归属调整后，历史下载会随当前有效文件快照显示当前维度，而不是事件发生时的旧维度。
- 遥测写入本身为 best-effort；未成功写入 `base_telemetry_events` 的下载无法由历史同步恢复。

## 需求质量门 Requirements Quality Gate

- [x] Every requirement has a stable `REQ-*` ID.
- [x] Every requirement has at least one `AC-*` acceptance criterion.
- [x] Every acceptance criterion has a stable `AC-*` ID.
- [x] Every acceptance criterion has at least one `V-*` verification ID.
- [x] Every acceptance criterion has a verification method.
- [x] Acceptance criteria sharing one behavior reuse an evidence target instead of duplicating commands.
- [x] No orphan `AC-*` or `V-*` entries exist.
- [x] Scope includes and excludes are explicit.
- [x] No critical ambiguity remains.
- [x] Requirements avoid implementation details unless explicitly required.
