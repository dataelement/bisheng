# 设计说明 Design: 知识空间内容统计数据集重建

## 元信息 Metadata

- Feature ID: `055-knowledge-space-content-stat-rebuild`
- Status: `design-updated-awaiting-confirmation`
- Based on: `requirements.md` 中 `REQ-001` 至 `REQ-008`
- Created: `2026-08-20`
- Updated: `2026-08-20`
- Implementation state: `REQ-001` 至 `REQ-007` 的代码实现和只读验证已完成；`REQ-008` 已形成设计和任务，尚未实现；实际索引重建仍需 T014 单独确认

## 1. 设计目标与边界

### 1.1 目标

1. 将 `record_type=file` 重建为“一个有效文件一条当前快照”，ES `_id` 固定为文件 ID，文件更新直接覆盖。
2. 用唯一一套上传人四级组织名称和唯一一套文件所属四级组织名称替换现有重复部门字段。
3. 让 `preview_daily`、`download_daily`、`favorite_daily` 保存事件发生时的文件及组织维度，并支持同日不同维度拆分。
4. 让预览、下载统计失败不影响主业务，并能从带快照的原始事件幂等补偿。
5. 组织、主组织或知识库绑定变化后准实时覆写受影响的 `file` 快照，每日全量任务只作为最终一致性校准。
6. 破坏性重建后只同步当前有效文件，不恢复旧预览、下载、收藏和 `portal_engagement_daily` 历史。
7. 通过可声明的虚拟指标策略提供上传人和文件所属组织知识贡献占比，并支持父级组织及非组织切片分母。

### 1.2 非目标

- 不改变门户全文检索使用的 `portal_engagement_daily` 数据结构和实时累计逻辑。
- 不把收藏次数合并到预览、下载或 `portal_engagement_daily`。
- 不自动迁移已有自定义看板对旧组织字段的引用。
- 不引入 `tenant_id`、组织 ID 或新的关系型数据库表。
- 不修改文件可见性、下载权限、收藏权限和组织管理权限。
- 不为知识贡献占比新增 ES 字段、记录类型、历史回填或索引重建步骤。
- 不强制校验知识贡献占比与组织维度的配对关系。

## 2. 当前实现依据与问题定位

| 位置 | 当前职责 | 与目标的差距 |
|---|---|---|
| `src/backend/bisheng/telemetry/domain/mid_table/knowledge_space_content.py` | 定义索引 Mapping、文件记录、预览日累计和投影队列 | 仍使用旧部门字段；预览复制 `file` 快照；日记录 ID 不能按维度拆分；无收藏记录 |
| `src/backend/bisheng/worker/telemetry/mid_table.py` | 全量及增量构建文件记录、从原始遥测重建下载日统计 | 下载按当前文件维度重建旧历史；队列只支持 `file`、`space` |
| `src/backend/bisheng/common/schemas/telemetry/event_data_schema.py` | 定义门户原始事件字段 | 预览、下载原始事件没有内容统计快照和口径版本 |
| `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py` | 文件预览、下载和收藏成功动作入口 | 收藏实际状态变化后没有内容统计投影；重复收藏与真实新增需在此区分 |
| `src/backend/bisheng/knowledge/domain/services/portal_pdf_download_service.py` | 门户 PDF 下载成功事件 | 只写普通下载事件和全文检索参与度，无四级组织事件快照 |
| `src/backend/bisheng/department/domain/services/department_service.py` | 组织改名、移动 | 变更后未触发内容统计文件重投影 |
| `src/backend/bisheng/user/domain/services/user_department_service.py` | 用户主组织切换 | 变更后未触发内容统计文件重投影 |
| `src/backend/bisheng/points/domain/services/department_org_level_service.py` | 公司根和四级标签维护 | 标签重算或清空后未触发内容统计文件重投影 |
| `src/backend/bisheng/knowledge/domain/services/department_knowledge_space_service.py` | 知识库组织绑定 | 绑定已触发空间刷新，但解绑缺少触发；重绑依赖间接链路 |
| `src/backend/bisheng/telemetry_search/domain/init_dataset.py` | 看板数据集指标和维度定义 | 暴露重复旧部门字段；无 8 个新维度和收藏次数 |
| `src/backend/scripts/rebuild_knowledge_space_content_stat.py` | 删除并重建精确索引 | 预检缺少下载、收藏和门户参与度分类计数；当前重建会恢复旧下载历史 |

### 2.1 `REQ-008` 更新时的实现基线

`REQ-001` 至 `REQ-007` 已按本设计实现。新增贡献占比涉及的当前基线如下：

| 位置 | 当前能力 | `REQ-008` 差距 |
|---|---|---|
| `src/backend/bisheng/telemetry_search/domain/models/dashboard_dataset.py` | `MetricConfig` 支持普通聚合、`formula`、`index`、`sum_field` | 没有“占总体/父级”策略、组织层级字段列表和默认格式元数据 |
| `src/backend/bisheng/telemetry_search/domain/services/component.py` | `query_formula_metric` 分两次查询并按相同维度合并 | 分母无法只移除最末级组织维度；直接 divide 会得到逐行自身相除 |
| `src/backend/bisheng/telemetry_search/domain/schemas/query_builder.py` | 支持 term、terms、range、match_all、match_phrase | 缺少显式 `exists` 过滤，无法保证缺失组织字段同时退出分子和分母 |
| `src/frontend/platform/src/pages/Dashboard/components/config/DatasetSelector.tsx` | 传递虚拟指标和 divide 标记 | 未传递数据集级默认数值格式 |
| `src/frontend/platform/src/pages/Dashboard/components/config/useChartState.tsx` | divide 指标默认百分比、2 位小数 | 无法只让两个贡献占比默认 1 位小数 |

## 3. 目标数据模型

### 3.1 物理索引与记录类型

继续使用物理索引 `mid_knowledge_space_content_stat`。内容统计使用四类记录；既有全文检索参与度写入器仍可在同一物理索引写入第五类记录。

| `record_type` | 用途 | `_id` | 重建后初始状态 |
|---|---|---|---|
| `file` | 当前有效文件快照 | `str(file_id)` | 从关系库全量同步 |
| `preview_daily` | 成功预览日统计 | 维度哈希 ID | 清空，从新回放起点开始生成 |
| `download_daily` | 成功下载日统计 | 维度哈希 ID | 清空，从新回放起点开始生成 |
| `favorite_daily` | 成功新增收藏关系日统计 | 维度哈希 ID | 清空，从新回放起点开始生成 |
| `portal_engagement_daily` | 门户全文检索阅读/下载缓存 | 保持现状 | 允许清空，不恢复旧历史；后续新事件继续按原逻辑累计 |

`file`、三个日统计记录均不写 `tenant_id`。所有可选维度以 `model_dump(exclude_none=True)` 写入，缺失字段不落 ES `_source`。

### 3.2 公共文件维度

四类内容统计记录共用以下文件维度：

- 空间：`space_id`、`space_name`、`space_level`、`space_level_name`
- 文件：`file_id`、`file_name`、`file_type`
- 分类：`file_category_code`、`file_category_name`、`file_subcategory_code`、`file_subcategory_name`
- 业务域：`business_domain_code`、`business_domain_name`
- 上传人：`uploader_user_id`、`uploader_user_name`
- 上传人组织：`uploader_company_name`、`uploader_department_name`、`uploader_office_name`、`uploader_squad_name`
- 文件所属组织：`belonging_company_name`、`belonging_department_name`、`belonging_office_name`、`belonging_squad_name`

`file` 额外保留 `sync_run_id` 和 `projection_updated_at`，用于全量校准和运维观察。日统计额外包含 `local_date`、自然日零点的 `timestamp`，以及该记录类型唯一的计数字段。

### 3.3 移除字段

新 Mapping、记录模型和看板数据集均移除：

- `space_department_id`、`space_department_name`
- `primary_department_id`、`primary_department_name`
- `uploader_department_infos`

物理删除旧索引后创建新 Mapping，因此不依赖 ES 对已有字段类型的兼容更新。

## 4. 四级组织解析

### 4.1 单一解析器

新增纯解析模块 `knowledge_space_content_dimensions.py`，集中定义：

- `OrganizationNameSnapshot`：四个可选名称字段；
- `ContentStatDimensionSnapshot`：公共文件维度和两套组织快照；
- `resolve_organization_names(start_department, path_nodes)`：从权威起点和祖先路径生成四级名称；
- `build_daily_document_id(...)`：生成稳定日统计 ID。

数据库批量加载留在 Worker/Service 的查询层，纯解析器不自行创建 Session，不写 ORM 查询。这样文件全量、增量和事件投影复用同一算法，同时不把数据访问逻辑塞进记录模型。

### 4.2 路径算法

1. 从起点组织的 `path` 提取按公司到叶子顺序排列的组织 ID。
2. 一次批量读取路径节点，只使用状态有效且实际位于该路径的节点。
3. 按 `org_level` 映射 `company/dept/office/squad`，不按节点深度或名称猜测。
4. `company`、`dept`、`office` 各取路径中对应标签的首个节点。
5. `squad` 取从公司向叶子方向遇到的首个 `squad` 节点；班组以下继续标记为 `squad` 的节点不得覆盖它。
6. 缺少某级时该字段为 `None`，写 ES 时省略；其他已解析层级照常保留。
7. 找不到唯一公司节点时，公共库的所属组织快照为空；不以上传人或创建者兜底。

### 4.3 文件所属组织起点

| 空间级别 | 起点解析 |
|---|---|
| `public` | 查询唯一活动 `org_level=company` 节点 |
| `department` | 优先使用 `DepartmentKnowledgeSpace` 绑定；兼容现有部门空间时可读取明确的部门型 Scope owner，但不得回退到上传人 |
| `team_ks` | 只使用 `DepartmentKnowledgeSpace` 绑定 |
| `team` | 读取 `KnowledgeSpaceScope.created_by`，再读取创建者当前主组织 |
| `personal` | 读取 Scope 所属用户 `owner_id`，再读取该用户当前主组织 |

上传人组织始终从 `KnowledgeFile.user_id` 对应用户的当前主组织解析，与空间级别无关。

## 5. 日统计分桶与 ID

### 5.1 纳入签名的字段

日统计签名包含第 3.2 节全部公共文件维度。这样同一文件同一天发生组织改名、主组织变化、空间改名、分类或业务域变化时，会形成不同日记录，不会把不同事件快照混入同一条记录。

### 5.2 规范化与哈希

固定算法如下：

```text
canonical_payload = {
  field: value-or-null
  for field in DAILY_DIMENSION_FIELDS（固定字段顺序）
}
canonical_json = JSON(sort_keys=true, ensure_ascii=false, separators=(',', ':'))
digest = SHA-256(UTF-8(canonical_json)).hexdigest()
_id = "{record_type}:{file_id}:{local_date}:{digest}"
```

- 缺失字段在签名中编码为 JSON `null`，但 ES `_source` 中仍省略该字段。
- 不使用字符串直接拼接维度值，避免分隔符冲突和超长 `_id`。
- `record_type`、`file_id`、`local_date` 位于可读前缀中，完整 SHA-256 保证稳定性。

该决策关闭 `OPEN-004`。

## 6. 事件时快照、可靠投影与幂等补偿

### 6.1 权威事件

只有后端确认的业务成功动作可以生成内容统计事件：

- 预览：文件详情/预览能力校验成功后现有 `_log_file_preview_success` 链路；
- 下载：保持当前下载指标的成功入口和来源范围，不因本次改造扩大统计范围；
- 收藏：`create_shougang_portal_favorite` 实际创建收藏引用成功后；命中 existing 的幂等返回不生成事件；
- 取消收藏：不生成计数事件。

通用 `/telemetry/events` 接口收到的客户端 `portal_favorite` 不作为 `favorite_daily` 权威来源，避免客户端重复上报或未发生状态变化也计数。

### 6.2 原始事件快照

在门户预览、下载、收藏原始事件中增加：

- `content_stat_schema_version=2`
- `content_stat_local_date`
- `content_stat_daily_id`
- `content_stat_snapshot`：第 3.2 节全部事件时文件维度和 8 个组织名称

序列化后仍遵循当前 `BaseTelemetryEvent` 的事件名前缀规则。旧事件没有 `content_stat_schema_version=2`，不会参与新日统计。

### 6.3 可重试事件队列

内容统计事件使用独立 Redis 待处理队列，不与 `file/space/user/department` 当前快照队列混存：

```text
业务成功
  → 解析事件时维度并生成稳定 event_id
  → 写入 Redis payload hash + pending zset
  → Worker 以 lease claim
  → 用 event_id 作为 base_telemetry_events 文档 _id 写原始事件
  → 按 daily_id 查询原始事件绝对数量
  → 幂等写日统计
  → ack；失败则保留/租约到期重试
```

事件 Worker 调用一个“失败时抛错”的严格遥测写入入口；现有吞异常的 `log_event_sync` 保持给普通旁路遥测使用。严格入口用 `event_id` 作为 ES `_id`，重复重试只会覆盖同一原始事件。

### 6.4 日统计幂等写

Worker 不执行无条件 `+1`，而是查询同一 `event_type + content_stat_schema_version + content_stat_daily_id` 的原始事件总数，然后通过 scripted upsert 写入：

```text
metric = max(existing_metric, recomputed_raw_event_count)
```

原始事件只追加且以 `event_id` 去重，因此：

- 同一队列消息重复处理不会增加两次；
- Worker 在“日统计已写、ack 前崩溃”后重试不会重复累计；
- 并发事件即使查询和写入交错，也不会用较小的旧结果覆盖较大计数；
- 手工按日期重放只会把结果校准到原始事件绝对值。

### 6.5 回放起点与旧历史隔离

Redis 保存 `REPLAY_FLOOR_KEY`。破坏性重建持有投影锁后记录 `rebuild_started_at`，并把它设置为新回放起点：

- 只有 `occurred_at >= replay_floor` 且 `content_stat_schema_version=2` 的事件可以生成日统计；
- 重建过程中发生、且时间不早于起点的新事件可在释放锁后继续处理；
- 重建前的旧事件即使仍在 `base_telemetry_events`，也不会重新生成被清空的历史；
- 手工补偿命令同样强制应用回放起点，除非未来另行修改规格并显式授权历史恢复。

### 6.6 保留与告警

- 待处理事件不设置业务过期时间，成功前持续重试；处理租约由每分钟恢复任务回收。
- 原始事件沿用 `base_telemetry_events` 现有生命周期，本功能不主动删除；可回放上限受该索引实际保留周期约束。
- 默认批量 500 条；`oldest_pending_age_ms >= 300000` 或积压超过一个批次时记录 `degraded=true`、积压量、最老延迟和失败阶段。
- 提供按 `[start_date, end_date)` 手工重放入口，默认只允许回放新起点之后的数据。

该决策关闭 `OPEN-003`。如果后续平台为原始遥测增加统一 ILM，本功能只需遵循统一保留策略，不在本规格重复维护。

## 7. 当前文件快照维护

### 7.1 文件生命周期

保留现有文件创建、解析成功、更新、移动、分类/业务域变化、主版本切换、回收站恢复等 `enqueue_file_stat_async` 触发点。Worker 对有效文件以 `_id=file_id` 执行覆盖写；文件失效或删除时只删除该文件的 `record_type=file` 当前快照，不因普通文件更新新增第二条快照。

空间删除沿用现有清理语义，不在本次组织改造中重新定义历史保留规则。

### 7.2 扩展当前快照队列

现有队列工作项扩展为：

| kind | 含义 | Worker 行为 |
|---|---|---|
| `file:<id>` | 单文件变化 | 重建或删除该 `file` 快照 |
| `space:<id>` | 空间或绑定变化 | 分页覆写该空间全部有效文件 |
| `user:<id>` | 用户主组织变化 | 刷新该用户上传的文件；同时刷新其创建的团队库和其个人库中的文件 |
| `department:<id>` | 组织名称、路径或标签变化 | 展开受影响子树的主组织用户和绑定空间，再分批入队 `user`/`space` |

所有工作项继续使用现有 pending/processing lease、owner lock、ack 和过期回收机制。大范围组织变化只在一个 Worker 中分页展开，避免请求线程直接扫描大量文件。

### 7.3 触发点

- `DepartmentService.aupdate_department`：名称实际变化后入队 `department`；短名称、排序、角色变化不触发。
- `DepartmentService.amove_department`：事务提交后入队移动子树根 `department`。
- `DepartmentOrgLevelService.set_company_root/clear_company_root`：提交后入队公司子树根 `department`。
- `UserDepartmentService.change_primary_department` 及本地等价主组织切换入口：实际变化后入队 `user`。
- `DepartmentKnowledgeSpaceService.bind/rebind/unbind`：事务提交后入队 `space`；补齐解绑缺失触发，并对重绑增加显式触发保证。

触发和投影失败均采用旁路日志，不回滚已成功的组织或知识库业务操作。每日 00:30 的全量任务会最终校准所有 `file` 快照。

## 8. 全量校准与破坏性重建

### 8.1 每日全量校准

`sync_mid_knowledge_space_content_stat` 改为只做：

1. 分页读取当前有效文件；
2. 使用统一解析器构建当前快照；
3. 按文件 ID 覆盖；
4. 删除本轮未出现的 stale `file` 快照和收藏引用空间快照。

不再扫描旧下载事件，不重建或删除任何日统计记录。事件日统计由第 6 节的事件队列和补偿任务维护。

### 8.2 重建脚本

`rebuild_knowledge_space_content_stat.py` 的 apply 流程：

1. 预检关系库有效文件数、Redis 队列状态、索引总数及五种 `record_type` 数量；
2. 校验 `--confirm-index mid_knowledge_space_content_stat`；
3. 获取内容统计全局 owner lock，记录新 `replay_floor`；
4. 删除精确索引并用新 Mapping 立即重建；
5. 只执行当前文件全量投影；
6. 清理明确列出的 legacy Redis key，不清空新起点之后的事件消息；
7. 校验 `file` 数量与数据源一致，并报告四类被清空历史的数量；
8. 释放锁并重新调度积压消息。

重建不会调用旧下载聚合函数，也不会扫描旧收藏事件。`portal_engagement_daily` 旧数据允许丢失；新门户事件仍由现有写入器继续累计。

由于 `portal_engagement_daily` 写入器不受内容统计 owner lock 控制，生产执行应安排短维护窗口，避免删除与门户实时写入竞争。脚本本身仍只删除精确索引，不操作别名或其他索引。

## 9. 看板数据集契约

### 9.1 指标

| 展示名称 | 字段/聚合 | 过滤 |
|---|---|---|
| 总文件数 | `value_count(file_id)` | `record_type=file`、有效空间级别、`file_type=1` |
| 新增文件数 | `value_count(file_id)` | 同上，由 `timestamp` 时间范围限定 |
| 内容贡献人数 | `cardinality(uploader_user_id)` | `record_type=file`、有效空间级别 |
| 预览次数 | `sum(preview_count)` | `record_type=preview_daily`、有效空间级别 |
| 下载次数 | `sum(download_count)` | `record_type=download_daily`、有效空间级别 |
| 收藏次数 | `sum(favorite_count)` | `record_type=favorite_daily`、有效空间级别 |
| 上传人知识贡献占比 | `share_of_parent(value_count(file_id))` | `record_type=file`、`file_type=1`、有效空间级别、当前上传人组织字段存在 |
| 文件所属知识贡献占比 | `share_of_parent(value_count(file_id))` | `record_type=file`、`file_type=1`、有效空间级别、当前所属组织字段存在 |

收藏次数是独立指标，不读取普通 `portal_favorite` 事件数量，也不读取 `portal_engagement_daily`。

### 9.2 维度

保留时间、空间、文件、分类、业务域、上传人 ID/名称维度；删除三个旧组织维度组，新增 `REQ-001` 的 8 个组织名称维度。

启动时数据集 seed 会刷新系统数据集定义。已有自定义看板若引用已移除字段将失效，本次不自动重写，其迁移仍是独立事项 `OPEN-002`，不阻塞本功能实现。

### 9.3 通用 `share_of_parent` 虚拟指标策略

扩展 `MetricConfig`，增加三个可选且向后兼容的声明字段：

```text
calculation = "share_of_parent"
share_dimension_hierarchy = [company_field, department_field, office_field, squad_field]
default_number_format = {type: "percent", decimalPlaces: 1, thousandSeparator: false}
```

- `calculation` 使用新枚举 `VirtualMetricCalculationEnum.SHARE_OF_PARENT`；已有 `formula`、`index` 和 `sum_field` 语义不变。
- `share_dimension_hierarchy` 由数据集声明，不在查询服务中硬编码 `mid_knowledge_space_content_stat` 或具体指标字段名。
- 两个贡献指标分别声明上传人和文件所属组织的四级字段顺序。
- `default_number_format` 只作为新指标首次加入组件时的默认值；保存后的组件格式继续以自身 `data_config.metrics[].numberFormat` 为准。

查询算法：

1. 将普通维度和堆叠维度按结果顺序视为统一维度列表。
2. 从 `share_dimension_hierarchy` 中找出当前查询已经选择的字段，并按声明层级选取最深字段作为 `target_dimension`，不依赖拖放顺序。
3. 分子查询保留全部维度和全部筛选，使用指标声明的 `value_count(file_id)`，并追加 `exists(target_dimension)`。
4. 分母查询复制全部筛选和聚合，但从分组维度中只移除 `target_dimension`；父级组织、时间、业务域、空间等其他维度全部保留，同时追加相同的 `exists(target_dimension)`。
5. 以“分子结果去掉目标维度后的上下文键”关联分母结果，返回原始完整维度列和 `numerator / denominator`。
6. 分母缺失或为 0 时返回 `0`；分子或分母都不做百分数乘 100，展示层负责格式化。
7. 若未选择任何声明的组织维度，不抛配对错误；将当前过滤和非组织分组上下文视为整体，非空上下文返回 `1`。该行为只保证查询稳定，不属于组织贡献口径的推荐用法。

`query_builder.py` 新增通用 `ExistsOp`，生成 `{ "exists": { "field": ... } }`。它属于查询 Schema 的向后兼容扩展，也可被其他数据集复用。

### 9.4 结果形状与排序兼容

- `query_share_of_parent_metric` 始终返回与分子查询相同的完整维度列顺序，因此 `query_all_metrics` 仍可按现有 tuple key 合并多个指标。
- 分母查询内部减少一个维度，但其结果不直接暴露给前端。
- 排序、Top N 和组件结果限制继续在占比计算完成后执行；Top N 只限制展示行，不缩小分母，所以只展示部分组织时可见占比之和允许小于 100%。
- 看板条件筛选和联动维度筛选同时作用于分子与分母；即使筛选字段等于目标组织字段，也不移除该筛选条件。

### 9.5 文件结构计划 File Structure Plan

| 文件 | 变更 | 目的 |
|---|---|---|
| `src/backend/bisheng/telemetry_search/domain/models/dashboard_dataset.py` | 修改 | 新增通用虚拟计算策略、层级字段列表和默认格式元数据 |
| `src/backend/bisheng/telemetry_search/domain/schemas/query_builder.py` | 修改 | 新增通用 `ExistsOp` |
| `src/backend/bisheng/telemetry_search/domain/services/component.py` | 修改 | 实现父级/总体分母查询和维度键合并；保留现有 divide 路径 |
| `src/backend/bisheng/telemetry_search/domain/init_dataset.py` | 修改 | 注册两个知识贡献占比指标及两套组织层级 |
| `src/backend/test/telemetry_search/test_knowledge_contribution_ratio.py` | 新增 | 参数化覆盖单层、多层、非组织切片、空值、零分母和回归 |
| `src/backend/test/telemetry_search/test_knowledge_space_content_dataset.py` | 修改 | 固定两个指标的数据集声明契约 |
| `src/frontend/platform/src/controllers/API/dashboard.ts` | 修改 | 补齐真实数据集 MetricConfig 类型及默认格式字段 |
| `src/frontend/platform/src/pages/Dashboard/components/config/DatasetSelector.tsx` | 修改 | 将默认格式随指标选择/拖拽传递 |
| `src/frontend/platform/src/pages/Dashboard/components/config/useChartState.tsx` | 修改 | 首次配置时优先采用数据集默认百分比格式 |
| `src/frontend/platform/src/test/knowledgeContributionMetricFormat.test.ts` | 新增 | 验证两个指标默认 percent + 1 位小数，已有 divide 默认不变 |

## 10. 并发、失败与兼容性

### 10.1 并发控制

- `file` 覆盖由确定性 `_id` 保证幂等。
- 当前快照队列沿用 owner lock 和 claim lease，新增 kind 不改变现有锁粒度。
- 事件原始记录由 `event_id` 作为 ES `_id` 去重。
- 日统计由维度哈希 `_id` 和绝对计数的单调 `max` 更新保证并发安全。
- 重建、当前快照全量和事件队列共享重建锁；重建期间消息可入队但不消费。
- 知识贡献占比执行两次只读聚合查询，不维护共享状态；同一查询请求内使用深拷贝隔离分子和分母的维度、过滤配置。

### 10.2 失败语义

| 失败位置 | 主业务结果 | 恢复方式 |
|---|---|---|
| 事件组织解析部分失败 | 业务成功；事件保留可解析字段 | 按缺失字段分桶，不猜测 |
| Redis 事件入队失败 | 业务成功；记录高优先级 degraded 日志 | 运维告警；基础设施恢复后新事件继续，无法凭空恢复未持久化动作 |
| 原始事件 ES 写失败 | 业务已成功 | 消息不 ack，租约恢复后重试 |
| 日统计写失败 | 业务已成功、原始事件已存在 | 消息重试或按日期手工回放 |
| 当前文件投影失败 | 组织/文件业务已成功 | 当前队列重试；每日全量最终校准 |
| 占比分子或分母查询失败 | 当前看板组件查询失败 | 沿用查询服务错误响应和日志；不返回伪造比例，不影响数据写入 |
| 占比分母为 0 或找不到匹配上下文 | 当前看板组件查询成功 | 返回 `0` |

在 Redis 和 ES 同时不可用时，系统仍优先保证用户操作成功；此时只能通过告警暴露无法持久化的统计风险，不能虚假承诺绝对零丢失。

### 10.3 兼容性

- 不新增数据库迁移，MySQL/DM8 查询只使用 SQLModel/SQLAlchemy 的通用表达式。
- 普通门户遥测调用保持原接口；新增严格写入口只供可重试 Worker 使用。
- `portal_engagement_daily` 的字段和查询保持不变。
- 新索引与旧 Mapping 不兼容，必须通过已确认的删除重建切换，不支持原地映射回退。
- `MetricConfig` 新字段全部可选；未声明 `calculation=share_of_parent` 的数据集继续走原 `formula/index/sum_field/普通聚合` 分支。
- 已保存组件继续使用自身 `numberFormat`，新增默认格式只影响以后首次添加的贡献占比指标。
- `REQ-008` 不需要数据库迁移、ES Mapping 更新或再次重建索引；系统数据集 seed 刷新后即可暴露新指标。

## 11. 验证设计

| Verification ID | 主要测试落点 | 证据 |
|---|---|---|
| `V-ORG-SCHEMA-001` | Mapping、记录序列化、数据集 seed 测试 | 仅 8 个组织名称，无旧字段/组织 ID/`tenant_id` |
| `V-ORG-RESOLVE-001` | 新纯解析器参数化单测 | 四级、科室、班组下级、缺层、空起点 |
| `V-ORG-NAME-GROUP-001` | ES 查询构造/集成测试 | 同名按 keyword 合并 |
| `V-ORG-OWNERSHIP-001` | Worker 批量构建服务测试 | 五类空间起点和两套组织独立 |
| `V-ORG-EVENT-SNAPSHOT-001` | 事件 + 日统计集成测试 | 同日变更拆桶，不复制旧 file 快照 |
| `V-ORG-REPLAY-001` | 队列 lease、原始 ES 和 scripted upsert 失败路径测试 | 失败可重试、重复重放不重复计数 |
| `V-ORG-REFRESH-001` | 组织/用户/绑定触发测试 + 全量比较 | 准实时覆写和最终校准一致 |
| `V-ORG-REBUILD-001` | 重建脚本测试 | 只恢复 file；四类旧历史均为 0 |
| `V-FAVORITE-COUNT-001` | 收藏 Service 状态转移测试 | 首次、重复、取消、再收藏 |
| `V-FAVORITE-DAILY-001` | 收藏事件分桶测试 | 相同快照累计、不同快照拆分 |
| `V-FAVORITE-REBUILD-001` | 重建与回放起点测试 | 旧收藏事件不恢复 |
| `V-FAVORITE-REGRESSION-001` | 门户参与度及预览/下载回归 | 原有独立口径不被收藏改造改变 |
| `V-CONTRIBUTION-SCHEMA-001` | 数据集 seed 契约测试 | 两个指标声明正确，Mapping 和重建脚本无持久化变化 |
| `V-CONTRIBUTION-QUERY-001` | `DataQueryService` 参数化服务测试 | 单层、父级、多维切片、exists、零分母与两套组织层级 |
| `V-CONTRIBUTION-FORMAT-001` | 前端指标选择状态测试 | 新贡献指标默认 percent + 1 位小数，保存后格式可覆盖 |
| `V-CONTRIBUTION-REGRESSION-001` | 查询服务定向回归 | 既有 divide、普通虚拟指标、多个指标结果合并不变 |

### 11.1 `REQ-008` 追踪关系

| Requirement | Design | Tasks | Verification |
|---|---|---|---|
| `REQ-008` 指标声明与默认格式 | 9.1、9.3、9.5 | `T016`, `T017` | `V-CONTRIBUTION-SCHEMA-001`, `V-CONTRIBUTION-FORMAT-001` |
| `REQ-008` 父级/总体分母与空值 | 9.3、9.4 | `T015` | `V-CONTRIBUTION-QUERY-001` |
| `REQ-008` 兼容性与无持久化变化 | 9.5、10.3、12 | `T015`, `T016`, `T017`, `T018` | `V-CONTRIBUTION-REGRESSION-001`, `V-CONTRIBUTION-SCHEMA-001` |

## 12. 回退策略

代码可回退，但删除重建后的旧索引内容不可恢复。本次明确不创建历史备份，因此回退只能：

1. 停止新事件和当前快照 Worker；
2. 回退应用代码；
3. 再次删除并按旧代码重建当前文件数据；
4. 已清空的预览、下载、收藏和 `portal_engagement_daily` 历史仍无法恢复。

实际执行破坏性重建前必须再次展示 preflight 数量并取得执行确认。

`REQ-008` 本身没有数据迁移或不可逆操作，可独立回退：移除两个数据集指标声明、前端默认格式透传和 `share_of_parent` 查询分支即可；已有索引文档与已保存组件数据不需要恢复。

## 13. 设计决策摘要

- `DEC-001`: 文件 `_id=file_id`，更新覆盖。
- `DEC-002`: 日统计 ID 使用完整公共维度规范 JSON 的 SHA-256。
- `DEC-003`: 缺失组织字段在签名中为 `null`、在 ES `_source` 中省略。
- `DEC-004`: 预览/下载/收藏以带 `schema_version=2` 的后端成功事件为权威来源。
- `DEC-005`: 原始事件用 `event_id` 去重；日统计写原始事件绝对数的单调最大值。
- `DEC-006`: 重建设置回放起点，禁止旧事件重新生成已清空历史。
- `DEC-007`: 每日全量只校准 `file`，不再按当前维度重建下载历史。
- `DEC-008`: 组织变化通过 `user`、`department` 队列扇出，历史日统计不回写。
- `DEC-009`: 收藏次数只由实际新建收藏关系触发，不信任客户端普通收藏遥测作为计数依据。
- `DEC-010`: `portal_engagement_daily` 旧历史随重建清空，结构和后续实时写入逻辑不改。
- `DEC-011`: 知识贡献占比使用通用 `share_of_parent` 虚拟指标策略，不为两个指标写硬编码查询分支。
- `DEC-012`: 分母只移除最末级匹配组织维度，保留上级组织、非组织分组及全部筛选，并以 `exists(target_dimension)` 同时排除空组织文件。
- `DEC-013`: 数据集通过 `default_number_format` 声明 percent + 1 位小数；已有组件自身格式优先，不改变其他 divide 指标默认行为。
