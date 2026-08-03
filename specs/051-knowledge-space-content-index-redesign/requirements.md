# 需求说明 Requirements: 知识空间内容统计索引重设计

## 阅读摘要
- 本文档说明：`mid_knowledge_space_content_stat` 从“文件快照 + 单次预览事件”调整为“文件快照 + 文件每日预览汇总”，并建立准实时、可恢复的投影链路。
- 当前状态：`approved`
- 需要重点确认：规格确认后才可进入实现；真实索引清空必须在实现和只读预检完成后再次确认。
- 本规格完全基于本次会话确认内容和当前代码，不引用项目中已有 SDD spec。

## 元信息 Metadata
- Feature ID: `051-knowledge-space-content-index-redesign`
- Status: `approved`
- Mode: `spec-then-implement`
- Created: `2026-08-03`
- Updated: `2026-08-03`
- Source request: `重设计知识空间内容统计索引，使文件更新覆盖写，并按自然日累计预览次数。`

## 需求入口摘要 Intake Summary
- 问题 Problem: 当前索引同时保存文件快照和每次预览事件；文件快照使用 `file_{file_id}`，预览按事件追加，不符合“一文件一快照、更新覆盖”的核心目标。
- 当前状态 Current state: 文件数据与预览事件共享一个索引；预览次数通过 `value_count(event_id)` 计算；预览失败进入 Redis 重试；查询层对该数据集强制注入 `tenant_id`。
- 目标结果 Target outcome: 文件快照使用文件 ID 作为 ES `_id` 并覆盖写；预览按中国自然日聚合为单条计数记录；看板仍通过原数据集查询文件和预览指标；正常条件下文件变化 30 秒内、成功预览累计 5 秒内可见。
- 影响对象 Affected users/systems: 数据看板、知识空间文件投影、文件预览埋点、Celery 文件同步、Elasticsearch 索引重建和看板权限范围。
- 请求停止点 Requested stopping point: `tasks`

## 范围 Scope

### 包含 Includes
- 重设计 `mid_knowledge_space_content_stat` 的 mapping 和文档契约。
- 文件快照使用 `_id = str(file_id)`，并在文件变化时覆盖写入。
- 仅投影知识空间内当前主版本、普通文件、解析成功的文件。
- 文件更新、删除、恢复和主版本切换成功后，显式触发所有受影响文件的快照重投影。
- 文件和空间刷新使用可租约恢复的 pending/processing 队列，保证处理期间再次发生的同一对象更新不会被旧任务确认掉。
- 全量、增量和重建使用可续租、可校验所有者的共享锁。
- 在同一索引内增加 `preview_daily` 日汇总记录，并以原子更新累计 `preview_count`。
- 日汇总首次创建时固化文件、空间、分类、业务域、上传人和部门等维度。
- 更新看板中预览次数的聚合方式和该数据集的非租户查询范围。
- 明确索引刷新配置、正常态实时性目标和队列积压/延迟观测字段。
- 删除该索引专用的单次预览事件和预览 Redis 重试链路。
- 提供受保护的原索引清空重建脚本、只读预检和运行说明。
- 更新直接相关的后端测试和验证证据。

### 不包含 Excludes
- 不保留或迁移现有历史预览事件，重建后预览次数从 0 开始。
- 不新增独立预览明细索引，不实现单次预览审计、重放或校准。
- 不实现严格 exactly-once 计数，不对失败的预览累计做业务重试。
- 不引入数据库事务 Outbox 或 CDC；业务提交成功但 Redis 入队失败时，仍由每日全量校准兜底，不承诺 30 秒可见。
- 不支持小时级预览汇总；最小统计粒度为中国自然日。
- 不改造数据看板为多索引联合查询，不修改前端数据集选择或图表接口。
- 不为该索引保留 `tenant_id`，不保证未来启用多租户后的隔离兼容性。
- 不修改实时问答统计和全员每日参与度的数据模型或租户过滤。
- 不在规格或代码实现阶段直接清空真实 Elasticsearch 索引。

## 需求列表 Requirements

### REQ-001: 文件快照使用文件 ID 覆盖写
作为数据看板维护者，我需要每个有效文件在索引中只有一条可变快照，以便文件属性变化时能直接覆盖而不产生重复文档。

#### 验收标准 Acceptance Criteria
- `AC-REQ-001-01`: WHEN 有效文件被首次投影或再次更新 THEN 系统 SHALL 使用 `str(file_id)` 作为 ES `_id` 完整写入当前文件快照。
- `AC-REQ-001-02`: WHEN 同一文件连续发生名称、分类、业务域、空间或部门维度变化 THEN 系统 SHALL 覆盖同一个 ES 文档，且索引中不得产生第二条该文件快照。
- `AC-REQ-001-03`: IF 文件不存在、不是当前主版本、不是普通文件、解析状态非成功或所属知识对象非知识空间 THEN 系统 SHALL 删除对应文件快照或不创建快照。
- `AC-REQ-001-04`: WHEN 每日全量校准完成 THEN 系统 SHALL 只清理未出现在本轮同步中的 `record_type=file` 文档，不得清理预览日汇总。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-001-01, AC-REQ-001-02 | V-AC-REQ-001-01 | automated test | `test/test_knowledge_space_content_telemetry.py` 验证确定性 `_id` 和覆盖动作 |
| AC-REQ-001-03 | V-AC-REQ-001-03 | automated test | 增量同步测试覆盖成功、等待、缺失和历史版本文件 |
| AC-REQ-001-04 | V-AC-REQ-001-04 | automated test | 全量陈旧清理查询必须限定 `record_type=file` |

### REQ-002: 预览次数按中国自然日原子累计
作为数据看板使用者，我需要按日、周、月和年查看预览次数，以便分析内容消费趋势，同时避免保存每次预览明细。

#### 验收标准 Acceptance Criteria
- `AC-REQ-002-01`: WHEN 一个有效文件发生成功预览 THEN 系统 SHALL 使用 `preview_{file_id}_{YYYY-MM-DD}` 作为 `_id`，原子创建或递增当天的 `preview_count`。
- `AC-REQ-002-02`: WHEN 同一文件在同一中国自然日发生多次预览 THEN 系统 SHALL 只保留一条日汇总，且 `preview_count` 等于成功执行的累计次数。
- `AC-REQ-002-03`: WHEN 同一文件跨中国自然日发生预览 THEN 系统 SHALL 分别写入不同的日汇总文档，且 `timestamp` 对应各自然日零点。
- `AC-REQ-002-04`: WHEN 日汇总首次创建 THEN 系统 SHALL 从当时的文件快照固化可用于看板分组和过滤的维度；后续预览、文件更新、空间更新或文件删除不得改写或删除该历史维度。
- `AC-REQ-002-05`: IF 文件快照不存在或 ES 预览累计失败 THEN 系统 SHALL 记录带 `file_id` 的错误日志并结束，不进入 Redis 或其他业务重试链路。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-002-01, AC-REQ-002-02 | V-AC-REQ-002-01 | automated test | 模拟 ES scripted upsert，验证稳定日汇总 ID、初始值和原子增量脚本 |
| AC-REQ-002-03 | V-AC-REQ-002-03 | automated test | 中国时区日期边界参数化测试 |
| AC-REQ-002-04 | V-AC-REQ-002-04 | automated test | 验证 upsert 固化维度，既有文档路径只更新计数；文件清理仅匹配 `file` |
| AC-REQ-002-05 | V-AC-REQ-002-05 | automated test | 模拟快照缺失和 ES 异常，验证日志及无重试入队 |

### REQ-003: 看板指标保持原数据集可用
作为看板配置者，我需要继续通过 `mid_knowledge_space_content_stat` 使用现有文件与预览指标，以便无需修改前端或重新选择数据集。

#### 验收标准 Acceptance Criteria
- `AC-REQ-003-01`: WHEN 查询总文件数或新增文件数 THEN 系统 SHALL 只聚合 `record_type=file` 的有效文件快照，并对 `file_id` 执行 `value_count`；WHEN 查询内容贡献人数 THEN 系统 SHALL 对文件快照的 `uploader_user_id` 执行 `cardinality`。
- `AC-REQ-003-02`: WHEN 查询预览次数 THEN 系统 SHALL 只聚合 `record_type=preview_daily`，并对 `preview_count` 执行 `sum`。
- `AC-REQ-003-03`: WHEN 按日、周、月或年查询预览次数 THEN 系统 SHALL 根据日汇总 `timestamp` 返回对应时间范围内的计数总和。
- `AC-REQ-003-04`: WHEN 数据集初始化或升级运行 THEN 系统 SHALL 继续使用原 `dataset_code` 和原 `es_index_name`，并刷新为新指标定义。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-003-01, AC-REQ-003-02, AC-REQ-003-04 | V-AC-REQ-003-01 | automated test | `test/test_realtime_dashboard.py` 校验数据集过滤器、聚合类型和索引名 |
| AC-REQ-003-03 | V-AC-REQ-003-03 | automated test | 查询构建测试验证 `sum(preview_count)` 与日期直方图组合 |

### REQ-004: 知识空间数据集不依赖租户字段
作为当前单租户部署的看板使用者，我需要知识空间内容统计不写入或查询 `tenant_id`，以便新索引契约与当前部署范围一致。

#### 验收标准 Acceptance Criteria
- `AC-REQ-004-01`: WHEN 创建文件快照或预览日汇总 THEN 系统 SHALL 不写入 `tenant_id`，文档 `_id` 也不得包含租户信息。
- `AC-REQ-004-02`: WHEN 超级管理员查询知识空间内容统计 THEN 系统 SHALL 不注入 `tenant_id` 过滤。
- `AC-REQ-004-03`: WHEN 部门管理员查询知识空间内容统计 THEN 系统 SHALL 只注入其可管理知识空间 ID 范围，不注入 `tenant_id`；无可管理空间时 SHALL 拒绝全部数据。
- `AC-REQ-004-04`: WHEN 查询实时问答统计或全员每日参与度 THEN 系统 SHALL 保持现有租户过滤行为不变。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-004-01 | V-AC-REQ-004-01 | automated test | 文件快照和日汇总序列化断言中不存在 `tenant_id` |
| AC-REQ-004-02, AC-REQ-004-03, AC-REQ-004-04 | V-AC-REQ-004-02 | automated test | `test/test_realtime_dashboard.py` 权限范围过滤测试 |

### REQ-005: 原索引受保护地清空并重建
作为运维执行者，我需要一个明确限定目标、支持预检并可验证结果的重建入口，以便按新 mapping 重建文件快照，同时接受历史预览数据清零。

#### 验收标准 Acceptance Criteria
- `AC-REQ-005-01`: WHEN 以 dry-run 方式运行重建入口 THEN 系统 SHALL 只读取并报告精确索引名、当前文档分布、MySQL有效文件数和待处理队列状态，不删除或写入任何数据。
- `AC-REQ-005-02`: IF 未提供匹配 `mid_knowledge_space_content_stat` 的显式确认参数 THEN 系统 SHALL 拒绝执行索引删除。
- `AC-REQ-005-03`: WHEN 经确认执行重建 THEN 系统 SHALL 删除并按新 mapping 创建原索引，从 MySQL重建当前有效文件快照，且不迁移旧预览数据。
- `AC-REQ-005-04`: WHEN 重建完成 THEN 系统 SHALL 报告源文件数、文件快照数、预览日汇总数和失败信息；允许重建期间看板为空或显示部分数据。
- `AC-REQ-005-05`: IF 真实索引重建尚未获得运行时预检后的最终确认 THEN 实现流程 SHALL 停止在脚本、测试和 dry-run，不执行真实删除。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-005-01, AC-REQ-005-02 | V-AC-REQ-005-01 | automated test | 重建脚本 dry-run 和确认参数保护测试 |
| AC-REQ-005-03, AC-REQ-005-04 | V-AC-REQ-005-03 | mocked integration + manual | 模拟删除/建索引/重建调用；真实执行后人工核对 ES 计数 |
| AC-REQ-005-05 | V-AC-REQ-005-05 | process inspection | 实现交付记录中不存在真实索引删除证据，除非已有单独最终确认 |

### REQ-006: 重建与增量写入不得永久丢失文件快照
作为数据维护者，我需要全量重建和实时文件更新串行协调，以便重建期间产生的文件变化最终仍能投影到索引。

#### 验收标准 Acceptance Criteria
- `AC-REQ-006-01`: WHEN 全量重建占用同步锁 THEN 文件增量消费者 SHALL 不消费并确认待处理文件 ID。
- `AC-REQ-006-02`: WHEN 重建释放同步锁且 Redis 中仍有文件待处理 THEN 系统 SHALL 重新调度增量同步。
- `AC-REQ-006-03`: WHEN 文件增量 upsert 或删除失败 THEN 系统 SHALL 不确认对应待处理 ID，并记录异常。
- `AC-REQ-006-04`: WHEN Worker 已领取某个文件或空间刷新项且同一对象再次发生变化 THEN 新变化 SHALL 重新保留在 pending 队列；当前处理成功时只能确认 processing 中的本次租约，不得删除新变化。
- `AC-REQ-006-05`: WHILE Worker 正常处理长批次 THEN 系统 SHALL 续租 processing 项；IF Worker 在处理或确认前异常退出且租约过期 THEN 系统 SHALL 在最后一次成功领取或续租后的 5 分钟内把未确认项恢复到 pending 并重新调度。
- `AC-REQ-006-06`: WHEN 全量、增量或重建任务持有共享锁 THEN 系统 SHALL 使用唯一 owner token 续租；只有当前 owner 可以续租或释放，失去锁所有权的任务 SHALL 停止继续写入和确认。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-006-01, AC-REQ-006-02 | V-AC-REQ-006-01 | automated test | 全量/增量锁竞争与重调度测试 |
| AC-REQ-006-03, AC-REQ-006-04 | V-AC-REQ-006-03 | automated test | 模拟失败和处理期间同 ID 再入队，验证旧 ack 不删除新 pending |
| AC-REQ-006-05 | V-AC-REQ-006-05 | automated test | 使用可控时钟验证 processing 租约过期回收和 5 分钟恢复界限 |
| AC-REQ-006-06 | V-AC-REQ-006-06 | automated test | owner token 获取、续租、非 owner 释放拒绝和失锁停止测试 |

### REQ-007: 文件生命周期变更完整触发快照刷新
作为数据看板维护者，我需要所有会改变文件快照内容或有效性的业务操作都触发重投影，以便索引及时反映 MySQL 当前状态，而不是只依赖每日全量校准。

#### 验收标准 Acceptance Criteria
- `AC-REQ-007-01`: WHEN 文件创建或解析结果、名称、路径、分类、业务域、标签、当前主版本或其他已投影维度成功变化并可被同步任务读取 THEN 系统 SHALL 将全部受影响的文件 ID 加入快照刷新队列。
- `AC-REQ-007-02`: WHEN 单文件删除、批量删除、文件夹级联删除、版本级联删除、回收站软删除或永久删除成功 THEN 系统 SHALL 将实际受影响的全部文件 ID 加入快照刷新队列。
- `AC-REQ-007-03`: WHEN 文件从回收站恢复或切换当前主版本成功 THEN 系统 SHALL 同时刷新恢复后或新主版本文件，以及因此失效、被替换或发生关联变化的文件 ID。
- `AC-REQ-007-04`: IF 文件业务操作失败或事务回滚 THEN 系统 SHALL 不发送代表成功状态的快照刷新；IF 业务操作已成功但刷新入队失败 THEN 系统 SHALL 记录操作类型和全部受影响文件 ID，并由每日全量校准最终修复。
- `AC-REQ-007-05`: WHEN Worker 消费任一文件刷新 ID THEN 系统 SHALL 重新读取 MySQL 当前状态；有效文件覆盖写 `_id=str(file_id)`，不存在或不再有效的文件只删除对应 `record_type=file` 快照，不得删除 `preview_daily` 历史。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-007-01 | V-AC-REQ-007-01 | automated test | 参数化验证文件属性、标签和可见状态变更成功后入队全部受影响文件 ID |
| AC-REQ-007-02 | V-AC-REQ-007-02 | automated test | 单文件、批量、文件夹及版本删除测试断言实际删除 ID 在持久化成功后入队 |
| AC-REQ-007-03 | V-AC-REQ-007-03 | automated test | 回收站恢复和主版本切换测试断言新旧关联文件 ID 均入队 |
| AC-REQ-007-04 | V-AC-REQ-007-04 | automated test | 模拟事务失败和入队失败，验证无提前事件、结构化日志及全量校准不受影响 |
| AC-REQ-007-05 | V-AC-REQ-007-05 | automated test | Worker 参数化验证当前有效状态走覆盖写、无效状态只删除文件快照 |

### REQ-008: 看板数据满足准实时可见性和可观测性
作为数据看板使用者和运维人员，我需要知识空间内容统计在依赖健康时快速可见，并能观察积压和处理延迟，以便区分正常刷新、队列阻塞和降级兜底。

正常条件定义为：MySQL、Redis、Celery 和 Elasticsearch 均可用；未进行索引重建；待处理刷新项不超过一个文件批次；ES 更新请求执行成功。

#### 验收标准 Acceptance Criteria
- `AC-REQ-008-01`: WHEN 正常条件下文件创建、更新、删除、恢复或主版本切换成功并完成入队 THEN 对应文件指标 SHALL 在 30 秒内通过看板 ES 查询反映最新状态。
- `AC-REQ-008-02`: WHEN 正常条件下预览日汇总的 ES 原子更新成功 THEN 新 `preview_count` SHALL 在 5 秒内通过看板 ES 查询可见。
- `AC-REQ-008-03`: WHEN 创建或重建 `mid_knowledge_space_content_stat` THEN 系统 SHALL 显式配置 `refresh_interval=1s`；普通文件批量写和预览累计不得逐条执行强制 refresh。
- `AC-REQ-008-04`: WHEN 增量或恢复任务运行 THEN 系统 SHALL 记录或暴露 pending 数量、processing 数量、最老 pending 等待时长、回收数量、批次耗时、投影延迟、最后成功时间和失败阶段。
- `AC-REQ-008-05`: IF Redis 入队在业务提交后失败、依赖不可用、队列超过正常条件或正在重建 THEN 系统 SHALL 明确记录为 degraded，30 秒/5 秒目标不适用；文件快照由每日全量校准最终修复，失败的预览累计仍按已确认策略不重试。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-008-01 | V-AC-REQ-008-01 | integration + manual timing | 可控队列集成测试验证调度上限；部署后从文件操作成功到 ES 查询命中的计时证据不超过 30 秒 |
| AC-REQ-008-02, AC-REQ-008-03 | V-AC-REQ-008-02 | automated + manual timing | 索引设置和无逐条 refresh 测试；部署后成功预览更新到 ES 查询可见不超过 5 秒 |
| AC-REQ-008-04 | V-AC-REQ-008-04 | automated test | 断言成功、失败、租约回收日志或状态报告包含规定观测字段 |
| AC-REQ-008-05 | V-AC-REQ-008-05 | automated test | 模拟 Redis/ES 失败和重建状态，验证 degraded 标记、文件兜底与预览无重试边界 |

## 非功能需求 Non-Functional Requirements
- `NFR-001`: 文件快照写入和预览累计不得新增第三方依赖。
- `NFR-002`: 预览累计必须使用 Elasticsearch 原子更新，并使用 `retry_on_conflict` 处理版本冲突；不得实现应用层读-改-写计数。
- `NFR-003`: 单个文件或预览日汇总文档不得保存随预览量无界增长的 `event_id` 数组。
- `NFR-004`: 错误日志必须包含索引名、`file_id` 和失败阶段，不记录敏感内容。
- `NFR-005`: 真实重建属于不可逆操作，脚本必须限定精确目标并默认 dry-run。
- `NFR-006`: Redis 多键原子操作使用相同 hash tag，确保 Redis Cluster 中 pending、processing、调度标记和锁位于同一 slot。
- `NFR-007`: 实时性验证不得依赖固定 `sleep` 证明正确性；自动测试使用可控时钟，真实时间目标通过独立集成或人工计时证据验证。

## 澄清记录 Clarifications

### Session 2026-08-03
- Q: 文件更新是否要求覆盖写？ -> A: 是；每个文件保存一份快照，`_id` 对应文件 ID。
- Q: 预览数能否放在文件快照中累计？ -> A: 不能；预览数需要时间维度统计。
- Q: 文件和预览是否拆数据集？ -> A: 不拆；选择同一索引包含文件快照和日汇总（1A）。
- Q: 最小时间粒度？ -> A: 中国自然日（2A）。
- Q: 是否保留预览原始事件用于重放？ -> A: 不保留，只维护日汇总（3B）。
- Q: 是否需要 `tenant_id`？ -> A: 不需要，当前系统不使用租户功能。
- Q: 预览累计失败是否重试？ -> A: 不做业务重试，只记录日志（1A）。
- Q: 哪些文件进入快照？ -> A: 仅当前主版本、普通文件、解析成功、知识空间文件（2A）。
- Q: 现有数据如何迁移？ -> A: 直接清空并重建原索引，不保留历史预览数据。
- Q: 预览日汇总的维度是否随文件更新？ -> A: 不更新；固化事件发生时维度，文件删除后保留历史（A）。
- Q: 重建期间是否允许部分数据？ -> A: 允许看板短暂为空或显示部分数据（A）。
- Q: 文件更新和删除是否需要显式触发覆盖或清理？ -> A: 需要；所有影响快照内容或有效性的成功操作必须刷新实际受影响文件 ID，不能只等待每日全量校准。
- Q: 当前实时性是否需要重新设计？ -> A: 需要局部重设计；采用准实时最终一致方案，文件变化正常 30 秒内、成功预览累计 5 秒内可见，Worker 异常租约 5 分钟内恢复，不引入事务 Outbox。
- Q: 四个看板指标是否可由新索引支撑？ -> A: 可以；总文件数和新增文件数使用 `value_count(file_id)`，内容贡献人数使用 `cardinality(uploader_user_id)`，预览次数使用 `sum(preview_count)`。前三项基于当前仍存在的文件快照，删除文件不保留历史文件事实。
- Q: 是否继续保存通用用户上下文字段？ -> A: 不保存重复的 `user_id`、`user_name`、`user_group_infos`、`user_role_infos`、`user_department_infos`；上传人维度只使用 `uploader_*` 字段。

## 假设 Assumptions
- `KnowledgeFile.id` 在当前单租户部署中全局唯一，因此可直接作为文件快照 `_id`。
- 中国自然日继续采用当前系统的 UTC+8 业务时区。
- 已有数据集字段名 `preview_count` 保持不变，前端无需修改。
- 现有门户或其他通用埋点如被其他功能使用，不在本次范围内删除；本需求只移除该中间索引的单次预览事件和专用重试链路。

## 风险 Risks
- 直接清空原索引会永久删除历史预览数据，且不提供数据级回滚。
- 不保留原始预览事件且不做业务重试，ES 写入失败会导致少计且无法恢复。
- 删除 `tenant_id` 后，该索引不具备未来多租户隔离能力；启用多租户前必须更新本规格。
- 同一索引存在文件快照和预览日汇总两种粒度，所有指标必须带正确的 `record_type` 过滤。
- 文件生命周期入口较多，任何入口漏发刷新都会造成文件快照在每日全量校准前短暂陈旧；必须用触发矩阵和参数化测试覆盖。
- pending/processing 原子脚本或 owner lock 实现错误会造成丢信号、重复处理或并发写入；必须覆盖同 ID 重入、任务崩溃、租约过期和非 owner 释放。
- 30 秒/5 秒属于依赖健康且无异常积压时的目标；业务成功后 Redis 入队失败仍可能延迟到每日全量校准，事务级不丢事件不在本次范围内。
- 重建脚本若与旧版本 API/Celery 进程并存，旧进程可能重新写入旧结构；真实重建前必须确认运行进程版本一致。

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
