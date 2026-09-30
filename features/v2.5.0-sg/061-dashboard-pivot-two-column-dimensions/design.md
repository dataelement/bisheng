# 设计说明 Design: 交叉表双列维度

## 阅读摘要
- 在交叉表配置中新增 `stackDimensions` 数组，同时保留旧 `stackDimension` 兼容读取。
- 后端复用通用多维聚合，将交叉表列维度追加在行维度之后查询。
- 前端按列路径构造叶子列与两级表头，不改变非交叉表的单堆叠逻辑。

## 元信息 Metadata
- Feature ID: `061-dashboard-pivot-two-column-dimensions`
- Status: `confirmed`
- Related requirements: `features/v2.5.0-sg/061-dashboard-pivot-two-column-dimensions/requirements.md`
- Created: `2026-08-21`
- Updated: `2026-08-21`

## 上下文 Context
- 现有架构 Existing architecture: `DataQueryService` 将维度转换为 ES 聚合表达式，API 返回扁平 `dimensions/value`；平台前端再转换为交叉表模型。
- 已检查文件 Relevant files inspected: `schemas/component.py`、`services/component.py`、`controllers/API/dashboard.ts`、`useChartState.tsx`、`PivotTable.tsx` 及相关测试。
- 现有测试或验证命令 Existing tests or validation commands: 前端 Vitest 与 build、后端 telemetry_search 定向 pytest、`scripts/arch-guard.sh`。
- 项目约束 Constraints from project guidance: 保持前后端分层、无数据库迁移、最小必要修改、兼容当前脏工作树中的用户改动。

## 目标 / 非目标 Goals / Non-Goals

### 目标 Goals
- 交叉表最多配置两个列维度。
- 查询结果维度位置稳定且可由前端无歧义切分。
- 两级列路径可正确展示、累计和计算合计。
- 旧交叉表与其他图表行为不变。

### 非目标 Non-Goals
- 不改造所有图表为多堆叠模型。
- 不实现服务端交叉表分页或 composite aggregation。
- 不扩展多维列别名编辑能力。

## 边界承诺 Boundary Commitments
| Boundary | Allowed Change | Disallowed Change | Revalidation Trigger |
|---|---|---|---|
| 交叉表配置 | 增加最多两个 `stackDimensions` | 非交叉表多堆叠 | 其他图表读取新数组 |
| 查询服务 | 将新列维度追加到普通聚合维度 | 修改 ES 索引或数据集 schema | 查询返回顺序变化 |
| 前端透视/渲染 | 列路径、两级表头和合计 | 服务端分页 | 叶子列上限变化 |

- Allowed dependencies: `none`

## 需求追踪 Requirements Traceability
| Requirement | Acceptance Criteria | Design Element | Verification Strategy |
|---|---|---|---|
| REQ-001 | AC-REQ-001-01..03 | `DataConfig`、`useChartState`、配置抽屉 | hook/交互定向测试 |
| REQ-002 | AC-REQ-002-01..02 | `ComponentDataConfig`、`DataQueryService` | 后端服务定向测试 |
| REQ-003 | AC-REQ-003-01..03 | `transformPivotData`、`PivotTable` | 转换与 DOM 渲染测试 |

## 架构设计 Architecture
- Pattern: 兼容适配层 + 扁平查询结果 + 客户端透视。
- Rationale: 搜索引擎已支持多维递归聚合，复用普通维度可避免扩大底层查询器改动。
- Preserved existing patterns: 旧 `stackDimension` 继续用于非交叉表和旧交叉表；API 响应仍为 `dimensions/value`。
- Architecture change justification, if any: 仅在交叉表配置契约增加数组字段，不改变持久化介质与路由。

## 文件结构计划 File Structure Plan
| Path | Action | Responsibility | Linked Requirement |
|---|---|---|---|
| `src/frontend/platform/src/pages/Dashboard/types/dataConfig.ts` | modify | 新列维度配置类型 | REQ-001 |
| `src/frontend/platform/src/pages/Dashboard/components/config/useChartState.tsx` | modify | 双列维度恢复、限制与保存 | REQ-001 |
| `src/frontend/platform/src/pages/Dashboard/components/config/ComponentConfigDrawer.tsx` | modify | 向堆叠区声明两个维度上限 | REQ-001 |
| `src/backend/bisheng/telemetry_search/domain/schemas/component.py` | modify | 接收新旧列维度配置 | REQ-002 |
| `src/backend/bisheng/telemetry_search/domain/services/component.py` | modify | 查询并排序完整维度路径 | REQ-002 |
| `src/frontend/platform/src/controllers/API/dashboard.ts` | modify | 将扁平结果转换为多级列路径 | REQ-003 |
| `src/frontend/platform/src/pages/Dashboard/types/chartData.ts` | modify | 多级列表头响应类型 | REQ-003 |
| `src/frontend/platform/src/pages/Dashboard/components/charts/PivotTable.tsx` | modify | 渲染一至两级列表头 | REQ-003 |
| `src/backend/test/telemetry_search/test_pivot_column_dimensions.py` | create | 后端契约回归 | REQ-002 |
| `src/frontend/platform/src/test/pivotColumnDimensionClick.test.tsx` | create | 点击添加第二个列维度的交互回归 | REQ-001 |
| `src/frontend/platform/src/test/pivotTwoColumnDimensions.test.tsx` | create | 配置、转换、渲染回归 | REQ-001, REQ-003 |

## 组件与接口 Components and Interfaces

### 配置兼容
- Inputs: `stackDimensions?: DimensionField[]`、`stackDimension?: DimensionField`。
- Outputs: 交叉表保存数组并保留第一个旧字段；读取优先数组、回退旧字段。
- Error behavior: 第三个维度触发既有上限提示且不改变当前状态。
- Requirements: REQ-001

### 点击添加入口修复
- Current erroneous behavior: 拖拽入口按图表类型计算上限，但字段点击入口仍以 `stackDimensions.length === 0` 判断是否可添加，已有一个维度时拒绝第二个。
- Root cause: 同一个上限规则在两个交互入口中分别实现，点击入口未随双列需求同步更新。
- Fix strategy: 字段点击入口按图表类型计算最大堆叠维度数；交叉表为 2，其他堆叠图为 1，并继续复用现有追加状态逻辑。
- Regression boundary: 使用组件交互测试从数据字段列表点击第二个列维度，断言堆叠区由一个变成两个。

### 查询服务
- Inputs: 行维度、一至两个有效列维度、单个指标。
- Outputs: `dimensions[i] = [row..., column...]`，`value[i]` 对应同索引指标值。
- Dependencies: 现有 `convert_dimensions`、`SearchEngineService`。
- Error behavior: 无效字段继续抛出既有 `QueryDimensionNotFoundError`。
- Requirements: REQ-002

### 交叉表转换与渲染
- Inputs: 扁平维度数组、指标数组、配置中的行/列维度数量。
- Outputs: 唯一叶子列路径、对齐的行值、行列合计、多级表头分组。
- Error behavior: 缺失维度值显示“未分类”；超过 500 行或 100 个叶子列标记截断。
- Requirements: REQ-003

## 数据 / 状态变化 Data / State Changes
- Entities: Dashboard component JSON configuration。
- Persistence changes: 新交叉表保存可选 `stackDimensions` JSON 字段；无表结构变化。
- Migration or rollback: 无批量迁移；删除新字段相关代码即可回滚，旧字段仍可使用。
- Compatibility: 新保存配置同时保留首个 `stackDimension`；旧配置读取时转为单元素状态。

## 测试策略 Testing Strategy
| Acceptance IDs | Risk / Level | Distinct Outcomes | Primary Layer | Evidence Group | Stop Condition |
|---|---|---|---|---|---|
| AC-REQ-001-01..03, AC-REQ-003-01..03 | medium/V2 | 双维主路径、单维兼容、列值累计与分组表头 | Vitest | EG-001 | 定向测试与前端 build 通过 |
| AC-REQ-002-01..02 | medium/V2 | 双维顺序、旧单维路径 | pytest | EG-002 | 定向服务测试通过 |

## 设计决策 Decisions
### Decision: 列维度复用普通多维聚合
- Context: 现有 `SearchEngineService` 的 `dimensions` 已支持多级递归聚合，而 `stack_dimension` 是单值兼容字段。
- Options considered: 扩展底层为 `stack_dimensions`；把新列维度追加到普通维度。
- Decision: 新数组配置走普通维度聚合，旧单字段保持原路径。
- Rationale: 返回顺序相同、改动更小，并隔离非交叉表行为。
- Consequences: 查询服务需要显式统一新旧配置并在排序、时间格式化中使用有效列维度列表。

## 风险 / 取舍 Risks / Trade-Offs
| Risk | Impact | Mitigation | Owner / Phase |
|---|---|---|---|
| 高基数列组合 | 查询和页面数据量上升 | 保持 100 个叶子列显示上限与截断提示 | implementation |
| 新旧字段同时存在 | 可能重复查询第一维 | 读取时数组优先且不拼接旧字段 | implementation |
| 用户已有未提交改动 | 合并冲突或覆盖 | 小范围补丁并检查 diff | implementation |

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
