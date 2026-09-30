# 需求说明 Requirements: F070 看板配置化数据范围

## 阅读摘要

- 本文档说明：移除实时看板数据集的服务端隐式数据范围过滤，恢复为由看板配置决定统计范围。
- 当前状态：`approved`
- 已确认风险：未配置租户、部门或知识空间维度时，查询可能聚合跨租户、跨部门或跨知识空间数据。

## 元信息 Metadata

- Feature ID: `070-dashboard-configured-data-scope`
- Status: `approved`
- Mode: `bug-fix`
- Created: `2026-08-06`
- Updated: `2026-08-06`
- Source request: `用户确认移除全部看板数据集硬过滤，包括 tenant_id，由用户端配置维度筛选`

## 需求入口摘要 Intake Summary

- 问题 Problem: 三个实时数据集在指标查询和维度枚举时被后端隐式追加 `tenant_id`、`primary_department_id` 或 `space_id` 条件，导致结果不能完全由看板配置控制。
- 当前状态 Current state: 服务端 `scope_filters` 会覆盖普通看板数据集的查询语义，部门管理员还可能因没有硬编码范围而被拒绝查询。
- 目标结果 Target outcome: 实时数据集与普通数据集使用相同的数据查询规则，只应用看板配置、运行时联动、时间和指标条件。
- 影响对象 Affected users/systems: 看板设计者、看板查看者、组件数据查询接口、维度枚举接口、Elasticsearch 聚合查询。
- 请求停止点 Requested stopping point: `verification`

## 范围 Scope

### 包含 Includes

- 移除指标查询中的服务端 `scope_filters` 注入。
- 移除维度枚举中的服务端数据范围过滤。
- 保留用户配置的组件筛选和运行时维度联动筛选。
- 保留看板资源本身的读取、写入、发布状态等访问控制。
- 更新与旧硬过滤策略冲突的契约说明和回归测试。

### 不包含 Excludes

- 不修改中间表同步和 Elasticsearch 文档结构。
- 不修改指标计算公式、默认时间范围、枚举显示标签。
- 不修改前端维度筛选组件或新增自动租户筛选。
- 不取消看板资源级读写权限校验。

## 需求列表 Requirements

### REQ-001: 查询范围完全由看板配置决定

作为看板设计者，我需要实时数据集不被后端追加隐式租户、部门或知识空间条件，以便通过维度配置准确决定统计范围。

#### 验收标准 Acceptance Criteria

- `AC-REQ-001-01`: WHEN 查询任意实时数据集组件 THEN 系统 SHALL 不自动追加 `tenant_id`、`primary_department_id`、`space_id` 或 `__deny_all__` 条件。
- `AC-REQ-001-02`: WHEN 组件配置筛选或运行时维度联动筛选 THEN 系统 SHALL 继续把这些用户配置条件应用到 Elasticsearch 查询。
- `AC-REQ-001-03`: WHEN 查询实时数据集维度枚举 THEN 系统 SHALL 不根据当前用户身份自动裁剪枚举值。

#### 验证方式 Verification Methods

| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-001-01 | V-AC-REQ-001-01 | automated regression test | `src/backend/test/test_realtime_dashboard.py` 断言组件查询不传入服务端范围 |
| AC-REQ-001-02 | V-AC-REQ-001-02 | automated regression test | `test_runtime_dimension_filters_are_combined_with_and` |
| AC-REQ-001-03 | V-AC-REQ-001-03 | automated regression test | 枚举查询 DSL 不包含隐式权限 `query.bool.filter` |

### REQ-002: 保留看板资源权限边界

作为系统管理员，我需要数据范围改为配置化时仍保留看板资源的读取和写入控制，以免数据查询策略变化同时扩大看板管理权限。

#### 验收标准 Acceptance Criteria

- `AC-REQ-002-01`: WHEN 用户查询或修改看板 THEN 系统 SHALL 继续执行现有看板资源权限与发布状态校验。

#### 验证方式 Verification Methods

| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-002-01 | V-AC-REQ-002-01 | automated regression test | `src/backend/test/test_realtime_dashboard.py` 既有看板访问与编辑用例 |

## 非功能需求 Non-Functional Requirements

- `NFR-001`: 修改不得新增依赖、数据库迁移或 Elasticsearch 索引变更。
- `NFR-002`: 权限策略变更按 V3 运行允许路径、拒绝路径和相关模块回归。

## 澄清记录 Clarifications

### Session 2026-08-06

- Q: 是否也移除 `tenant_id` 服务端硬过滤？ -> A: `确认移除全部硬过滤`。
- Q: 看板数据范围由谁决定？ -> A: 由用户在看板端自行配置部门等维度筛选。

## 假设 Assumptions

- “全部硬过滤”仅指数据集查询与枚举的数据范围，不包括看板资源本身的读写权限。
- 运行时维度联动属于用户配置查询条件，继续保留。

## 风险 Risks

- 未配置租户维度时，包含 `tenant_id` 的中间表可能产生跨租户聚合结果。
- 获得看板读取权限的用户可能看到跨部门、跨知识空间的指标和枚举值。
- 用户端筛选是统计配置，不再构成安全隔离；此行为已由用户明确确认。

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
