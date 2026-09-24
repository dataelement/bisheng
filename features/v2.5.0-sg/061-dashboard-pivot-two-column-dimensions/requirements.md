# 需求说明 Requirements: 交叉表双列维度

## 阅读摘要
- 本功能让数据看板交叉表的“堆叠项 / 维度”最多支持两个维度，并渲染为两级列表头。
- 当前状态：`confirmed`
- 既有单列维度看板必须继续可查询、可编辑和可展示。

## 元信息 Metadata
- Feature ID: `061-dashboard-pivot-two-column-dimensions`
- Status: `confirmed`
- Mode: `spec-then-implement`
- Created: `2026-08-21`
- Updated: `2026-08-21`
- Source request: `交叉表堆叠项支持两个维度，并按扁平查询结果拼成两级列表头`

## 需求入口摘要 Intake Summary
- 问题 Problem: 交叉表当前只保存、查询和展示一个堆叠维度。
- 当前状态 Current state: 配置与后端契约使用单个 `stackDimension`，前端只读取一个列值。
- 目标结果 Target outcome: 交叉表可配置一至两个列维度，查询结果按完整列路径聚合并展示两级表头。
- 影响对象 Affected users/systems: 数据看板编辑器、遥测查询服务、交叉表数据转换与渲染。
- 请求停止点 Requested stopping point: `verification`

## 范围 Scope

### 包含 Includes
- 交叉表堆叠维度上限从一个调整为两个。
- 保存并恢复 `stackDimensions` 数组配置。
- 后端按行维度后接列维度的固定顺序返回扁平聚合结果。
- 前端按完整列路径拼接单元格、合计和两级表头。
- 兼容只包含旧字段 `stackDimension` 的已有交叉表。

### 不包含 Excludes
- 非交叉表图表支持多个堆叠维度。
- 超过两个列维度。
- 改造为 ES composite aggregation 或新增服务端分页。
- 数据库或 Elasticsearch 索引迁移。

## 需求列表 Requirements

### REQ-001: 配置两个列维度
作为看板编辑者，我需要为交叉表添加最多两个堆叠维度，以便按两层列分类查看指标。

#### 验收标准 Acceptance Criteria
- `AC-REQ-001-01`: WHEN 编辑交叉表 THEN 系统 SHALL 通过字段点击或拖拽入口允许添加两个堆叠维度，并在添加第三个时保持两个维度不变。
- `AC-REQ-001-02`: WHEN 保存并重新打开交叉表 THEN 系统 SHALL 按原顺序恢复两个堆叠维度及时间粒度。
- `AC-REQ-001-03`: WHEN 打开只有 `stackDimension` 的旧交叉表 THEN 系统 SHALL 恢复为一个堆叠维度。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-03 | V-AC-REQ-001 | automated test | `src/frontend/platform/src/test/pivotColumnDimensionClick.test.tsx`, `src/frontend/platform/src/test/pivotTwoColumnDimensions.test.tsx` |

### REQ-002: 查询完整维度路径
作为交叉表使用者，我需要查询结果同时包含两个列维度，以便每个指标值能映射到唯一列组合。

#### 验收标准 Acceptance Criteria
- `AC-REQ-002-01`: WHEN 配置两个列维度 THEN 后端 SHALL 按 `[行维度..., 列维度...]` 顺序输出维度数组。
- `AC-REQ-002-02`: WHEN 旧配置只有一个列维度 THEN 后端 SHALL 保持现有查询结果顺序和行为。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-002-01, AC-REQ-002-02 | V-AC-REQ-002 | automated test | `src/backend/test/telemetry_search/test_pivot_column_dimensions.py` |

### REQ-003: 展示两级列表头
作为交叉表查看者，我需要看到两个列维度形成的分组表头，以便理解每个数值所属的完整列路径。

#### 验收标准 Acceptance Criteria
- `AC-REQ-003-01`: WHEN 两个列维度产生多个组合 THEN 系统 SHALL 以完整列路径区分列并累计相同行列组合的值。
- `AC-REQ-003-02`: WHEN 第一层列值连续相同 THEN 表头 SHALL 合并对应叶子列，并保留列合计、行合计和总计。
- `AC-REQ-003-03`: WHEN 只有一个列维度 THEN 表头 SHALL 保持单行展示。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-003-01, AC-REQ-003-02, AC-REQ-003-03 | V-AC-REQ-003 | automated test | `src/frontend/platform/src/test/pivotTwoColumnDimensions.test.tsx` |

## 非功能需求 Non-Functional Requirements
- `NFR-001`: 交叉表仍最多展示 500 行和 100 个叶子列组合。
- `NFR-002`: 不新增依赖，不修改 Elasticsearch 索引和持久化表结构。

## 澄清记录 Clarifications

### Session 2026-08-21
- Q: 两个维度如何查询和拼接？ -> A: 后端返回扁平维度路径，前端按行路径和列路径透视并渲染两级表头。
- Q: 是否实施？ -> A: 用户确认实施。
- Bug report: 实际前端已有一个堆叠维度后，通过数据字段列表点击添加第二个维度仍提示达到上限。
- Expected: 交叉表的字段点击入口与拖拽入口都允许堆叠维度从一个增加到两个；其他图表仍最多一个。

## 假设 Assumptions
- 两个列维度的顺序以编辑器添加顺序和保存数组顺序为准。
- 现有列别名仅作用于第一个列维度；本次不扩展多维别名配置。

## 风险 Risks
- 两个高基数字段可能产生较多列组合；沿用 100 个叶子列展示上限并显示截断提示。

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
