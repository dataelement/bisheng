# 设计说明 Design: F070 看板配置化数据范围

## 阅读摘要

- 本文档说明：删除独立的服务端数据范围通道，让实时数据集复用普通看板的筛选转换和 Elasticsearch 查询链路。
- 设计重点：只移除 `scope_filters`，保留 `dimension_filters`、组件筛选、时间筛选、指标筛选和看板资源权限。
- 不在本设计中处理：前端自动筛选、索引租户字段补齐和看板权限模型重构。

## 元信息 Metadata

- Feature ID: `070-dashboard-configured-data-scope`
- Status: `approved`
- Related requirements: `features/v2.6.0/070-dashboard-configured-data-scope/requirements.md`
- Created: `2026-08-06`
- Updated: `2026-08-06`

## 上下文 Context

- 现有架构 Existing architecture: `Dashboard API -> DashboardService -> DataQueryService -> SearchEngineService -> Elasticsearch`。
- 已检查文件 Relevant files inspected: `dashboard.py`、`component.py`、`search_engine_service.py`、`test_realtime_dashboard.py`、`test_dashboard_enum_labels.py`、`release-contract.md`。
- 现有测试或验证命令 Existing tests or validation commands: `uv run pytest test/test_realtime_dashboard.py test/telemetry_search/test_dashboard_enum_labels.py`，以及 Ruff 定向检查。
- 项目约束 Constraints from project guidance: 权限策略变更必须先确认、测试先行、V3 相关回归、最小 diff、不得取消资源权限。

## 目标 / 非目标 Goals / Non-Goals

### 目标 Goals

- 指标查询不再计算或传递服务端数据范围。
- 枚举查询不再根据登录用户追加 Elasticsearch `terms` 条件。
- 用户配置的筛选条件保持原有行为。
- 看板资源访问控制保持原有行为。

### 非目标 Non-Goals

- 不更改数据集 schema、指标、维度或中间表。
- 不修改实时数据集的默认当天时间范围。
- 不修改看板发布、编辑或分享规则。

## 边界承诺 Boundary Commitments

| Boundary | Allowed Change | Disallowed Change | Revalidation Trigger |
|---|---|---|---|
| `DashboardService` 查询链路 | 删除服务端范围计算与注入 | 删除看板资源权限校验 | 需要改变查看、编辑或发布规则 |
| `DataQueryService` | 删除 `scope_filters` 模型字段和转换 | 删除用户 `dimension_filters` 或指标筛选 | 用户配置筛选语义变化 |
| 维度枚举 | 删除隐式权限过滤 | 修改分页、搜索、显示标签 | 枚举 API 契约变化 |
| 测试与契约 | 替换旧权限预期并记录新策略 | 扩大到其他权限模块 | 发现跨模块权限依赖 |

- Allowed dependencies: `none`

## 需求追踪 Requirements Traceability

| Requirement | Acceptance Criteria | Design Element | Verification Strategy |
|---|---|---|---|
| REQ-001 | AC-REQ-001-01..03 | 删除 `_get_realtime_scope_filters` 与 `scope_filters` 链路 | service/API-level regression tests |
| REQ-002 | AC-REQ-002-01 | 保留 `async_access_check`、发布状态和实时看板写入守卫 | existing access-control regression tests |

## 架构设计 Architecture

- Pattern: 统一查询管线；所有数据集只消费显式的组件、运行时和时间筛选。
- Rationale: 用户要求数据范围是报表配置，不是后端隐式授权事实。
- Preserved existing patterns: API 参数、`DimensionQueryFilter` 联动、`FilterExpression`、指标内置筛选和 Elasticsearch 聚合。
- Architecture change justification, if any: 删除 2026-07-30 引入的实时数据集专用范围通道，使其与普通数据集一致。

## 文件结构计划 File Structure Plan

| Path | Action | Responsibility | Linked Requirement |
|---|---|---|---|
| `src/backend/bisheng/telemetry_search/domain/services/dashboard.py` | modify | 停止计算和注入服务端数据范围 | REQ-001, REQ-002 |
| `src/backend/bisheng/telemetry_search/domain/services/component.py` | modify | 删除 `scope_filters` 输入和转换 | REQ-001 |
| `src/backend/test/test_realtime_dashboard.py` | modify | 新策略回归和资源权限回归 | REQ-001, REQ-002 |
| `src/backend/test/telemetry_search/test_dashboard_enum_labels.py` | modify | 删除旧方法 mock，验证枚举契约 | REQ-001 |
| `features/v2.5.0-sg/release-contract.md` | modify | 更新统计投影授权边界说明 | REQ-001, REQ-002 |
| `features/v2.6.0/070-dashboard-configured-data-scope/*.md` | create | SDD 追踪和验证证据 | REQ-001, REQ-002 |

## 组件与接口 Components and Interfaces

### 组件数据查询

- Responsibility: 根据显式筛选和指标配置生成聚合结果。
- Inputs: `component.data_config`、`time_filters`、`dimension_filters`。
- Outputs: `DataQueryResult`。
- Dependencies: 数据集 schema、`SearchEngineService`。
- Error behavior: 保留数据集、指标、维度不存在等既有错误。
- Requirements: `REQ-001`

### 维度枚举查询

- Responsibility: 对允许的 schema 维度执行搜索、分页和标签映射。
- Inputs: dataset、field、keyword、exact values。
- Outputs: enum values/options。
- Dependencies: Elasticsearch。
- Error behavior: 非 schema 字段继续拒绝。
- Requirements: `REQ-001`

## 数据 / 状态变化 Data / State Changes

- Entities: `none`
- Persistence changes: `none`
- Migration or rollback: 无迁移；回滚代码可恢复原强制过滤行为。
- Compatibility: API 请求响应字段不变，但统计结果和枚举范围可能扩大。

## 测试策略 Testing Strategy

| Acceptance IDs | Risk / Level | Distinct Outcomes | Primary Layer | Evidence Group | Stop Condition |
|---|---|---|---|---|---|
| AC-REQ-001-01, AC-REQ-001-03 | high/V3 | 组件与枚举都没有隐式范围 | service integration with fakes | EG-001 | 修复前因隐式范围失败、修复后通过 |
| AC-REQ-001-02 | medium/V2 | 显式联动筛选仍进入查询 | unit | EG-001 | 既有运行时筛选断言通过 |
| AC-REQ-002-01 | high/V3 | 有权访问和无权编辑路径保持 | service integration with fakes | EG-002 | 相关访问控制回归通过 |

## 设计决策 Decisions

### Decision: 删除而不是增加禁用开关

- Context: 普通数据集没有服务端范围通道，需求要求恢复统一行为。
- Options considered: 配置开关；只删除部门/空间过滤；删除全部范围过滤。
- Decision: 删除全部 `scope_filters` 链路，包括 `tenant_id`。
- Rationale: 用户明确确认“移除全部硬过滤”，且不需要保留双路径。
- Consequences: 查询逻辑简化；统计安全范围完全依赖看板资源权限和用户筛选配置。

### Decision: 保留看板资源权限

- Context: 数据集范围与看板资源访问是不同边界。
- Options considered: 同时删除实时看板访问限制；只修改数据范围。
- Decision: 保留现有看板资源读取、写入与发布状态校验。
- Rationale: 用户确认的是硬查询过滤，不是取消资源授权。
- Consequences: 用户仍需先获得看板访问权，才能执行不带隐式数据范围的查询。

## 风险 / 取舍 Risks / Trade-Offs

| Risk | Impact | Mitigation | Owner / Phase |
|---|---|---|---|
| 未配置 `tenant_id` 时跨租户聚合 | 统计结果包含多个租户 | 用户已确认接受；由看板配置显式限制 | dashboard author |
| 枚举暴露全部索引值 | 用户可发现跨部门/空间维度值 | 看板读取权限仍保留；风险已确认 | product/security |
| 契约与旧实现不一致 | 后续开发重新引入硬过滤 | 更新 release contract 与回归测试 | implementation |

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
