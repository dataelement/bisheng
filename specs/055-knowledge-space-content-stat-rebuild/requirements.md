# 需求说明 Requirements: 知识空间内容统计数据集重建

## 阅读摘要

- 本文档用于从零整理并重建 `mid_knowledge_space_content_stat` 数据集的业务口径、数据结构和维护规则。
- 当前状态：`REQ-001` 至 `REQ-007` 的代码实现与验证已完成，实际索引清空重建等待 T014 破坏性操作确认。
- 本轮已确认：上传人组织和文件所属组织均扩展为公司、部门、科室、班组四级名称维度；新增累计成功收藏动作次数指标。
- 当前停止点：执行前只读预检已完成；未执行会清空历史统计的索引重建。

## 元信息 Metadata

- Feature ID: `055-knowledge-space-content-stat-rebuild`
- Status: `requirements-confirmed`
- Mode: `implementation-awaiting-destructive-confirmation`
- Created: `2026-08-20`
- Updated: `2026-08-20`
- Source request: `重新整理并重建 mid_knowledge_space_content_stat，逐项形成规格；当前已确定组织四级字段和累计成功收藏动作次数口径。`

## 需求入口摘要 Intake Summary

- 问题 Problem: 当前数据集同时存在上传人主部门、上传人全部所属部门和知识库绑定部门等单层或重复字段，不能按公司、部门、科室、班组统一分析，也无法准确表达文件上传人组织与文件所属组织的差异。
- 当前状态 Current state: 数据集提供 `primary_department_id/name`、`space_department_id/name` 和 `uploader_department_infos.department_id/name`，字段重复、层级不足且历史日统计复用当前文件快照。
- 目标结果 Target outcome: 数据集分别提供唯一一套“上传人组织”和“文件所属组织”四级名称维度；文件快照反映当前组织，预览、下载和收藏日统计保留事件发生时维度；新增累计成功收藏动作次数指标。
- 影响对象 Affected users/systems: 数据看板维度和指标选择、`mid_knowledge_space_content_stat` 数据契约、文件快照投影、预览与下载原始事件、收藏业务动作、日统计投影、ES Mapping、增量刷新和重建流程。
- 请求停止点 Requested stopping point: 完成已确认规格的代码实现和验证；破坏性索引重建须单独确认。

## 范围 Scope

### 包含 Includes

- 定义上传人和文件所属组织的公司、部门、科室、班组四级名称字段。
- 定义组织层级的路径解析、部分填充、缺失字段和班组以下子组织归属规则。
- 定义公共库、部门库、科室库、团队库、个人库的文件所属组织来源。
- 定义 `file`、`preview_daily`、`download_daily`、`favorite_daily` 四类记录的组织快照时间口径。
- 定义组织变化后的文件快照刷新、历史日统计不回写、原始事件补偿和失败降级要求。
- 定义旧预览、下载日统计在本次重建中的清理口径。
- 定义累计成功收藏动作次数、收藏日统计以及旧收藏事件不回填的口径。

### 不包含 Excludes

- 本轮不确定总文件数、新增文件数、内容贡献人数、预览次数、下载次数、收藏次数以外的指标。
- 本轮不调整 `portal_engagement_daily` 的数据结构、存储位置或统计口径。
- 本轮不确定最终日统计 `_id` 的拼接或哈希算法，设计阶段只需保证同日不同组织组合可拆分。
- 本轮不制定旧自定义看板引用已移除字段时的迁移方案。
- 本轮不修改生产代码、数据库、ES 索引或实际看板配置。
- 本轮不沿用或合并已有同主题 SDD spec。
- 本次实施仅覆盖 `REQ-001` 至 `REQ-007`；后续新增指标或记录类型必须先更新本规格。

## 需求列表 Requirements

### REQ-001: 提供上传人和文件所属组织四级名称维度

作为看板配置和数据分析人员，我需要分别按上传人组织和文件所属组织的四个层级进行筛选、分组和统计，以便区分“谁上传了文件”和“文件归属哪个组织”。

#### 字段契约 Field Contract

| 字段 | 展示名称 | 类型 | 语义 | 缺失规则 |
|---|---|---|---|---|
| `uploader_company_name` | 上传人公司 | `keyword` | 上传人主组织路径中的公司级组织名称 | 无法解析时不写入字段 |
| `uploader_department_name` | 上传人部门 | `keyword` | 上传人主组织路径中的部门级组织名称 | 无法解析时不写入字段 |
| `uploader_office_name` | 上传人科室 | `keyword` | 上传人主组织路径中的科室级组织名称 | 无法解析时不写入字段 |
| `uploader_squad_name` | 上传人班组 | `keyword` | 上传人主组织路径中的班组级组织名称 | 无法解析时不写入字段 |
| `belonging_company_name` | 所属公司 | `keyword` | 文件所属组织路径中的公司级组织名称 | 无法解析时不写入字段 |
| `belonging_department_name` | 所属部门 | `keyword` | 文件所属组织路径中的部门级组织名称 | 无法解析时不写入字段 |
| `belonging_office_name` | 所属科室 | `keyword` | 文件所属组织路径中的科室级组织名称 | 无法解析时不写入字段 |
| `belonging_squad_name` | 所属班组 | `keyword` | 文件所属组织路径中的班组级组织名称 | 无法解析时不写入字段 |

以下旧字段不再属于新数据集的数据契约，也不得继续作为新数据集的可选维度：

- `primary_department_id`
- `primary_department_name`
- `space_department_id`
- `space_department_name`
- `uploader_department_infos.department_id`
- `uploader_department_infos.department_name`

#### 业务规则 Business Rules

1. 四级字段仅保存组织名称，不保存相应组织 ID。
2. `mid_knowledge_space_content_stat` 不写入或暴露 `tenant_id` 字段。
3. 缺失字段采用“不写入”语义，不写空字符串、不写占位名称，也不删除整条文件或日统计记录。
4. 允许只填充能够解析的层级；例如主组织为科室时填写公司、部门、科室，不生成班组字段。
5. 使用名称作为看板分组键，接受不同组织同名时合并为同一名称分组。
6. 组织改名后的新事件使用新名称，既有历史日统计保留旧名称，因此按名称查看跨改名时间段时允许形成两个分组。

#### 验收标准 Acceptance Criteria

- `AC-REQ-001-01`: WHEN 看板加载数据集可选维度 THEN 系统 SHALL 展示上述 8 个组织名称维度，且不得展示已移除的旧组织字段。
- `AC-REQ-001-02`: WHEN 检查新索引 Mapping 和新写入记录 THEN 系统 SHALL 不包含任何上传人或文件所属组织 ID 字段，也不包含 `tenant_id`。
- `AC-REQ-001-03`: GIVEN 某个组织层级无法解析 WHEN 构建记录 THEN 系统 SHALL 省略对应字段，同时保留该记录和其他可解析层级。
- `AC-REQ-001-04`: GIVEN 两个不同组织具有相同层级名称 WHEN 看板按该名称字段分组 THEN 系统 SHALL 将其统计到同一个名称分组。

### REQ-002: 按组织层级标签解析四级路径

作为数据维护人员，我需要所有组织字段统一依据组织架构的层级标签和父子路径生成，以便字段不依赖组织树的展示深度或节点名称猜测。

#### 业务规则 Business Rules

1. 层级标签与字段映射固定为：`company` → 公司、`dept` → 部门、`office` → 科室、`squad` → 班组。
2. 解析从权威起点组织沿父级路径向上查找，并把每个已识别层级的组织名称写入对应字段。
3. 起点组织本身具有某个层级标签时，应同时纳入解析结果。
4. 起点组织位于班组以下时，从公司向下的组织路径中选取首个 `squad` 节点作为班组归属；不得把班组以下的叶子节点当作新的班组。
5. 路径中缺少某个层级时不进行跨层级猜测或名称兜底，只省略缺失层级字段。
6. 当前规格按“系统最终只允许一个公司级标签”的目标约束设计，不支持同一记录保存多个公司名称。

#### 验收标准 Acceptance Criteria

- `AC-REQ-002-01`: GIVEN 起点组织为班组 WHEN 解析组织路径 THEN 系统 SHALL 分别填写其公司、部门、科室和班组名称。
- `AC-REQ-002-02`: GIVEN 起点组织为科室 WHEN 解析组织路径 THEN 系统 SHALL 填写公司、部门和科室名称，并省略班组字段。
- `AC-REQ-002-03`: GIVEN 起点组织是班组的下级节点 WHEN 解析组织路径 THEN 系统 SHALL 使用从公司向下遇到的首个班组节点，且不得使用该下级节点名称填充班组字段。
- `AC-REQ-002-04`: GIVEN 组织路径缺少部门层级但存在公司和科室层级 WHEN 解析组织路径 THEN 系统 SHALL 保留公司和科室字段并省略部门字段。

### REQ-003: 按空间类型确定文件所属组织来源

作为数据分析人员，我需要不同知识空间中的文件使用明确且唯一的所属组织来源，以便所属公司、部门、科室和班组统计具有一致业务含义。

#### 所属组织来源 Ownership Resolution

| 知识空间类型 | 权威起点 | 解析规则 |
|---|---|---|
| 公共库 `public` | 系统唯一的公司级组织 | 直接填写所属公司；无法找到唯一公司时省略全部所属组织字段 |
| 部门库 `department` | 知识库绑定的组织 | 从绑定组织按 `REQ-002` 向上解析 |
| 科室库 `team_ks` | `DepartmentKnowledgeSpace` 绑定的组织 | 从绑定组织按 `REQ-002` 向上解析，不使用创建者组织代替 |
| 团队库 `team` | `KnowledgeSpaceScope.created_by` 对应创建者的主组织 | 从创建者当前主组织按 `REQ-002` 向上解析 |
| 个人库 `personal` | 个人空间所属用户的主组织 | 从所属用户当前主组织按 `REQ-002` 向上解析 |

#### 业务规则 Business Rules

1. 上传人组织的权威起点始终是文件上传人的当前主组织，与文件所属知识空间类型无关。
2. 部门库或科室库缺少有效组织绑定时，不使用空间创建者或文件上传人组织兜底。
3. 团队库必须使用不可变的空间创建者 `created_by`，不使用当前操作人或文件上传人代替。
4. 个人库必须使用个人空间的所属用户，不使用当前查看人代替。
5. 权威起点不存在或无效时，按 `REQ-001` 的缺失规则省略相应一组组织字段。

#### 验收标准 Acceptance Criteria

- `AC-REQ-003-01`: GIVEN 文件位于公共库 WHEN 构建所属组织字段 THEN 系统 SHALL 只根据唯一公司级组织填充所属公司。
- `AC-REQ-003-02`: GIVEN 文件位于部门库或科室库 WHEN 构建所属组织字段 THEN 系统 SHALL 使用知识库绑定组织及其父级路径，不得使用上传人组织兜底。
- `AC-REQ-003-03`: GIVEN 文件位于团队库 WHEN 构建所属组织字段 THEN 系统 SHALL 使用 `KnowledgeSpaceScope.created_by` 对应创建者的主组织路径。
- `AC-REQ-003-04`: GIVEN 文件位于个人库 WHEN 构建所属组织字段 THEN 系统 SHALL 使用个人空间所属用户的主组织路径。
- `AC-REQ-003-05`: GIVEN 文件上传人与文件所属组织不同 WHEN 构建记录 THEN 系统 SHALL 分别保存两套组织字段且互不覆盖。

### REQ-004: 文件快照与事件日统计使用不同时间口径

作为看板使用人员，我需要文件维度反映当前组织状态，同时预览和下载统计保留事件发生时的组织状态，以便当前资产盘点和历史行为分析都具有正确口径。

#### 业务规则 Business Rules

1. `record_type=file` 保存投影时的当前组织快照。
2. `record_type=preview_daily` 和 `record_type=download_daily` 保存成功事件发生时的组织快照。
3. 每次成功预览或下载均重新解析上传人组织和文件所属组织，不得直接复制可能已经过期的 `file` 快照。
4. 原始预览、下载事件同时保存事件发生时的 8 个组织名称，作为日统计补偿和重放的数据来源。
5. 同一文件、同一自然日、同一组织字段组合的成功事件累计到同一条日统计记录。
6. 同一文件在同一自然日出现不同组织字段组合时，必须拆分为多条日统计记录，分别累计次数。
7. 组织字段组合应区分字段缺失与字段有值的情况；最终 `_id` 生成算法在设计阶段确定。

#### 验收标准 Acceptance Criteria

- `AC-REQ-004-01`: GIVEN 文件快照生成后上传人主组织发生变化 WHEN 再次成功预览该文件 THEN 新预览日统计 SHALL 使用事件发生时的新上传人组织，而既有日统计保持不变。
- `AC-REQ-004-02`: GIVEN 同一文件同一天发生两组不同组织快照的成功预览 WHEN 查询日统计 THEN 系统 SHALL 返回两条记录，且两条记录的 `preview_count` 分别累计。
- `AC-REQ-004-03`: GIVEN 同一文件同一天发生两组不同组织快照的成功下载 WHEN 查询日统计 THEN 系统 SHALL 返回两条记录，且两条记录的 `download_count` 分别累计。
- `AC-REQ-004-04`: WHEN 检查成功预览或下载的原始事件 THEN 事件 SHALL 包含当时可解析的上传人和文件所属组织名称字段。
- `AC-REQ-004-05`: GIVEN `file` 快照中的组织信息已经过期 WHEN 发生成功预览或下载 THEN 日统计 SHALL 以实时解析结果为准，不得继承过期快照。

### REQ-005: 组织变化触发当前文件快照覆写

作为数据维护人员，我需要组织和知识空间归属变化后自动刷新受影响文件的当前快照，以便看板无需等待每日全量任务即可反映新的组织关系。

#### 业务规则 Business Rules

1. 以下变化必须识别受影响文件并触发异步批量重投影：组织名称变化、组织层级标签变化、组织父子关系变化、用户主组织变化、知识库组织绑定变化。
2. 团队库创建者或个人空间所属用户的主组织变化时，必须刷新对应空间内文件的所属组织字段。
3. 文件上传人的主组织变化时，必须刷新该用户已上传文件的上传人组织字段。
4. 刷新使用文件 ID 作为 `file` 快照 `_id`，对当前快照执行覆盖写入，不新增同一文件的第二条 `file` 记录。
5. 组织变化只刷新当前 `file` 快照，不回写既有 `preview_daily`、`download_daily` 或 `favorite_daily` 历史记录。
6. 每日全量校准继续作为增量事件遗漏后的最终一致性保障，但不得作为组织变化生效的唯一机制。

#### 验收标准 Acceptance Criteria

- `AC-REQ-005-01`: GIVEN 用户主组织发生变化 WHEN 增量投影完成 THEN 该用户已上传文件的 `file` 快照 SHALL 被原 `_id` 覆写且只保留一条当前记录。
- `AC-REQ-005-02`: GIVEN 组织改名、层级或父子关系发生变化 WHEN 增量投影完成 THEN 所有受影响 `file` 快照 SHALL 使用新的组织路径。
- `AC-REQ-005-03`: GIVEN 部门库或科室库重新绑定组织 WHEN 增量投影完成 THEN 空间内文件的所属组织字段 SHALL 使用新的绑定组织路径。
- `AC-REQ-005-04`: WHEN 当前文件快照因组织变化被覆写 THEN 既有预览、下载和收藏日统计中的组织字段 SHALL 保持不变。
- `AC-REQ-005-05`: GIVEN 增量触发发生遗漏 WHEN 每日全量校准完成 THEN 当前有效文件的组织字段 SHALL 与权威组织和空间归属数据一致。

### REQ-006: 投影失败不阻断用户行为并支持补偿

作为门户用户，我需要预览和下载操作不因统计系统暂时不可用而失败；作为运维人员，我需要失败事件可以根据持久化原始数据重放。

#### 业务规则 Business Rules

1. 组织解析失败、日统计写入失败或文件快照刷新失败不得改变预览、下载业务操作的成功结果。
2. 成功预览、下载的原始事件是日统计补偿的权威来源，必须携带事件发生时组织快照。
3. 日统计投影失败后必须进入可重试或可重放流程，不得只记录日志后永久丢弃。
4. 补偿重放必须保持幂等，不得因重复消费同一原始事件而重复增加次数。
5. 本次新索引重建不保留旧 `preview_daily` 和 `download_daily` 历史记录，从新版本上线后开始生成符合新组织口径的统计。

#### 验收标准 Acceptance Criteria

- `AC-REQ-006-01`: GIVEN 日统计存储暂时不可用 WHEN 用户成功预览或下载 THEN 业务响应 SHALL 保持成功，失败统计 SHALL 保留可补偿状态。
- `AC-REQ-006-02`: GIVEN 一条失败统计对应的原始事件已持久化 WHEN 执行补偿重放 THEN 系统 SHALL 按原始事件中的组织快照恢复日统计。
- `AC-REQ-006-03`: GIVEN 同一原始事件被重复重放 WHEN 查询日统计 THEN 对应次数 SHALL 只计算一次。
- `AC-REQ-006-04`: WHEN 执行已确认的新索引重建 THEN 系统 SHALL 清空旧预览和下载日统计，且不得将旧事件按当前组织关系重新归属。

### REQ-007: 统计累计成功收藏动作次数

作为看板使用人员，我需要按日期、文件和组织维度统计累计成功收藏动作次数，以便分析哪些知识内容被用户主动收藏以及不同组织范围内的收藏趋势。

#### 指标与记录契约 Metric and Record Contract

| 项目 | 值 | 说明 |
|---|---|---|
| 记录类型 | `favorite_daily` | 被收藏文件的每日收藏动作统计 |
| 指标字段 | `favorite_count` | 非负整数，记录成功新增收藏动作次数 |
| 看板展示名称 | 收藏次数 | 对 `favorite_count` 求和 |
| 时间字段 | `timestamp`、`local_date` | 按收藏成功发生时的自然日归档 |

#### 业务规则 Business Rules

1. “成功收藏动作”是指被收藏文件实际从“未收藏”变为“已收藏”，并成功创建收藏关系。
2. 对已经收藏的文件重复调用幂等收藏接口时，不增加 `favorite_count`。
3. 取消收藏只改变当前收藏状态，不扣减已经形成的历史 `favorite_count`。
4. 用户取消收藏后再次成功建立收藏关系，应视为新的成功收藏动作并再次计数。
5. `favorite_daily` 保存收藏发生时的被收藏文件维度，以及按 `REQ-001` 至 `REQ-003` 解析的上传人和文件所属组织快照。
6. 同一被收藏文件、同一自然日、相同文件与组织维度快照的成功收藏动作累计到同一条 `favorite_daily` 记录。
7. 同一被收藏文件在同一自然日出现不同维度快照时，必须拆分为多条 `favorite_daily` 记录并分别累计。
8. 组织或文件维度后续发生变化时，不回写既有 `favorite_daily` 历史记录。
9. 旧收藏事件不回填为 `favorite_daily`；该指标从新版本上线后开始统计。
10. 新增收藏次数不得改变 `portal_engagement_daily`、`preview_daily`、`download_daily` 及其现有指标口径。

#### 验收标准 Acceptance Criteria

- `AC-REQ-007-01`: GIVEN 文件当前未被用户收藏 WHEN 成功创建收藏关系 THEN 对应 `favorite_daily.favorite_count` SHALL 增加 1。
- `AC-REQ-007-02`: GIVEN 文件已经被用户收藏 WHEN 重复调用幂等收藏接口 THEN `favorite_count` SHALL 不增加。
- `AC-REQ-007-03`: GIVEN 用户取消收藏 WHEN 查询历史收藏日统计 THEN 已记录的 `favorite_count` SHALL 不减少。
- `AC-REQ-007-04`: GIVEN 用户取消后再次成功收藏同一文件 WHEN 查询收藏日统计 THEN `favorite_count` SHALL 再增加 1。
- `AC-REQ-007-05`: GIVEN 同一文件同一天发生相同维度快照的多次成功收藏 WHEN 查询日统计 THEN 系统 SHALL 返回一条 `favorite_daily` 记录并累计全部成功动作次数。
- `AC-REQ-007-06`: GIVEN 同一文件同一天发生不同维度快照的成功收藏 WHEN 查询日统计 THEN 系统 SHALL 按维度快照拆分记录，且每条记录保留事件发生时的组织字段。
- `AC-REQ-007-07`: WHEN 新版本首次创建或重建索引 THEN 系统 SHALL 不根据旧收藏事件生成 `favorite_daily` 历史记录。
- `AC-REQ-007-08`: WHEN 新增收藏次数指标 THEN `portal_engagement_daily`、预览次数和下载次数的现有记录与查询行为 SHALL 保持不变。

## 验证方式 Verification Methods

| Acceptance IDs | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-001-01, AC-REQ-001-02 | V-ORG-SCHEMA-001 | automated test + mapping inspection | 数据集 schema、记录模型和 ES Mapping 仅包含 8 个新组织名称字段，不包含旧组织字段、组织 ID 或 `tenant_id` |
| AC-REQ-001-03, AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03, AC-REQ-002-04 | V-ORG-RESOLVE-001 | parameterized unit test | 参数化覆盖四级完整路径、从科室起步、班组以下节点、路径缺层和无起点组织 |
| AC-REQ-001-04 | V-ORG-NAME-GROUP-001 | query integration test | 两个不同组织使用相同名称时，按名称聚合形成一个分组 |
| AC-REQ-003-01, AC-REQ-003-02, AC-REQ-003-03, AC-REQ-003-04, AC-REQ-003-05 | V-ORG-OWNERSHIP-001 | parameterized service test | 参数化覆盖五类知识空间的权威起点和上传人/所属组织相互独立 |
| AC-REQ-004-01, AC-REQ-004-02, AC-REQ-004-03, AC-REQ-004-05 | V-ORG-EVENT-SNAPSHOT-001 | integration test | 同文件同日发生组织变化后，预览和下载按组织组合拆分，历史记录不变化且不复制过期文件快照 |
| AC-REQ-004-04, AC-REQ-006-01, AC-REQ-006-02, AC-REQ-006-03 | V-ORG-REPLAY-001 | failure-path integration test | 模拟日统计写入失败，业务操作成功；原始事件含组织快照；重复重放保持幂等 |
| AC-REQ-005-01, AC-REQ-005-02, AC-REQ-005-03, AC-REQ-005-04, AC-REQ-005-05 | V-ORG-REFRESH-001 | event-trigger integration test + full-sync comparison | 组织、用户主组织和空间绑定变化触发受影响文件覆写；预览、下载和收藏历史不回写；全量校准结果一致 |
| AC-REQ-006-04 | V-ORG-REBUILD-001 | rebuild dry-run + post-rebuild inspection | 重建计划显示旧日统计将被清理，执行后索引不含旧 `preview_daily`、`download_daily` 记录 |
| AC-REQ-007-01, AC-REQ-007-02, AC-REQ-007-03, AC-REQ-007-04 | V-FAVORITE-COUNT-001 | state-transition integration test | 覆盖首次收藏、重复幂等收藏、取消收藏和取消后重新收藏，断言历史次数变化符合计数规则 |
| AC-REQ-007-05, AC-REQ-007-06 | V-FAVORITE-DAILY-001 | daily projection integration test | 相同维度快照聚合为一条记录，不同快照拆分并保留事件发生时组织字段 |
| AC-REQ-007-07 | V-FAVORITE-REBUILD-001 | rebuild dry-run + post-rebuild inspection | 重建不读取旧收藏事件生成 `favorite_daily`，上线前日期无收藏日统计 |
| AC-REQ-007-08 | V-FAVORITE-REGRESSION-001 | targeted regression test | 新增收藏投影前后，`portal_engagement_daily`、预览和下载记录及查询结果保持一致 |

## 非功能需求 Non-Functional Requirements

- `NFR-001`: 组织变化通过事件触发准实时投影，不得仅依赖每日全量任务。
- `NFR-002`: 组织字段解析必须复用同一套层级标签和路径算法，避免文件快照、预览、下载和收藏产生不同口径。
- `NFR-003`: 文件快照覆盖、预览/下载日统计累计与补偿重放、收藏状态转移计数必须具备幂等性。
- `NFR-004`: 统计链路故障不得阻断门户预览和下载的主业务链路。
- `NFR-005`: 规格未完成且未取得单独的破坏性操作确认前，不得删除或重建实际索引。
- `NFR-006`: 新增组织解析和原始事件字段不得改变现有用户权限或文件可见性判断。

## 澄清记录 Clarifications

### Session 2026-08-20

- Q: 上传人和所属组织字段是否保存 ID？ → A: 仅保存四级名称字段，共 8 个维度。
- Q: 班组以下子组织如何归属？ → A: 归入公司路径向下遇到的首个班组，不使用更深叶子节点作为班组。
- Q: 无法解析完整组织路径时如何处理？ → A: 允许部分填充；无法解析的字段不记录，文件仍保留。
- Q: 组织字段适用于哪些记录？ → A: 适用于 `file`、`preview_daily` 和 `download_daily`。
- Q: 文件快照和历史日统计采用什么时间口径？ → A: `file` 使用当前组织；预览、下载使用事件发生时组织。
- Q: 旧预览和下载历史如何处理？ → A: 重建时清空，不保留也不按当前组织关系回填。
- Q: 同一文件同一天发生组织变化时如何累计？ → A: 按组织字段组合拆成多条日统计。
- Q: 事件组织字段是否复用文件快照？ → A: 每次成功事件重新解析，不复用可能过期的文件快照。
- Q: 只保存名称可能发生同名合并和改名分段，是否接受？ → A: 接受。
- Q: 原始事件是否记录组织快照？ → A: 记录，用于准确补偿和重放。
- Q: 统计失败是否阻断用户行为？ → A: 不阻断，原始事件落地后补偿。
- Q: 组织关系变化是否刷新文件快照并保持历史不变？ → A: 确认。
- Q: 是否需要 `tenant_id`？ → A: 不需要，当前系统不使用租户功能。
- Q: 多个公司级标签如何处理？ → A: 按后续系统只能绑定一个公司级标签规划，不设计多公司结构。
- Q: 新增收藏指标表示动作次数还是当前存量？ → A: 表示累计成功收藏动作次数，不表示当前仍处于收藏状态的文件数量。
- Q: 重复收藏、取消和重新收藏如何计数？ → A: 只有实际新建收藏关系计数；重复幂等调用不计数；取消不扣减；取消后重新收藏再次计数。
- Q: 收藏日统计是否回填旧事件？ → A: 不回填，从新版本上线后开始统计。
- Q: 是否同时调整 `portal_engagement_daily`、预览和下载口径？ → A: 不调整，不属于本次收藏指标修改范围。
- Q: 重建原物理索引时是否允许清空既有 `portal_engagement_daily`？ → A: 允许清空，不保留也不自动恢复其历史记录。

## 待确认事项 Open Questions

- `OPEN-002`: 已有自定义看板引用旧组织字段时，是在重建前阻止并提示迁移，还是允许字段失效后人工修复。

## 设计阶段已决策事项 Resolved in Design

- `OPEN-003`: 待处理事件成功前持续重试；原始事件沿用统一遥测索引生命周期；默认积压告警阈值和手工回放边界见 `design.md` 第 6.6 节。
- `OPEN-004`: 日统计使用固定公共维度的规范 JSON，缺失值编码为 `null`，并以完整 SHA-256 生成稳定 `_id`，见 `design.md` 第 5 节。

## 假设 Assumptions

- `ASSUMPTION-001`: 上传人、团队创建者和个人空间所属用户的主组织是组织解析的权威用户归属来源。
- `ASSUMPTION-002`: `Department.org_level` 的稳定值为 `company`、`dept`、`office`、`squad`，组织父子关系可沿权威路径向上查询。
- `ASSUMPTION-003`: `KnowledgeSpaceScope.created_by` 在空间生命周期中保持创建者语义，不随管理员或成员变化而改变。
- `ASSUMPTION-004`: 后续组织配置会限制只能存在一个公司级标签；本规格不处理多个公司值。
- `ASSUMPTION-005`: 旧预览、下载和 `portal_engagement_daily` 历史允许不可恢复地清空；实际执行索引重建前仍需单独取得破坏性操作确认。

## 风险 Risks

- 仅保存名称会把同名组织合并到同一分组；组织改名后历史和新数据会形成不同名称分组，这是已接受的数据口径。
- 删除旧组织字段会使引用这些字段的自定义组件失效，迁移策略仍待确认。
- 用户主组织或组织树变化可能影响大量文件，增量扇出、批量大小和全量校准成本需在设计阶段评估。
- 原始事件如果未成功持久化，后续无法精确补偿；持久化失败处理和告警必须在设计阶段明确。
- 清空旧预览、下载历史属于不可逆数据操作，实际执行前必须展示影响范围、备份/回退能力并再次确认。
- 当前物理索引还承载 `portal_engagement_daily`；直接删除索引会同时清空门户累计阅读和下载历史，这是用户已经确认接受的重建影响。
- 旧收藏事件不生成 `favorite_daily`，因此新版本上线前的收藏动作不会出现在收藏次数趋势中，这是已确认的数据边界。

## 需求质量门 Requirements Quality Gate

- [x] Every requirement has a stable `REQ-*` ID.
- [x] Every requirement has at least one `AC-*` acceptance criterion.
- [x] Every acceptance criterion has a stable `AC-*` ID.
- [x] Every acceptance criterion has at least one `V-*` verification ID.
- [x] Every acceptance criterion has a verification method.
- [x] Acceptance criteria sharing one behavior reuse an evidence target instead of duplicating commands.
- [x] No orphan `AC-*` or `V-*` entries exist.
- [x] Scope includes and excludes are explicit.
- [x] 本轮组织维度和收藏次数指标不存在关键歧义。
- [x] 本次实施范围已冻结为 `REQ-001` 至 `REQ-007`；后续新增需求必须先更新 spec。
- [x] Requirements avoid implementation details unless required to define the confirmed data contract and time semantics.
