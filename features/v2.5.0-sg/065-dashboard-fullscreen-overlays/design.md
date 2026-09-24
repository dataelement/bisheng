# 设计说明 Design: 数据看板全屏浮层可用性修复

## 阅读摘要
- 通过共享 hook 跟踪当前全屏元素，并作为 Radix Portal 的默认容器。
- 显式 `portalContainer` 继续优先；无全屏时保持 Radix 默认挂到 `document.body`。
- 不改变数据看板业务状态、请求和布局。

## 元信息 Metadata
- Feature ID: `065-dashboard-fullscreen-overlays`
- Status: `confirmed`
- Related requirements: `features/v2.5.0-sg/065-dashboard-fullscreen-overlays/requirements.md`
- Created: `2026-09-10`
- Updated: `2026-09-10`

## 上下文 Context
- 现有架构 Existing architecture: 数据看板分别对 `#view-panne`、`#edit-charts-panne` 调用浏览器 Fullscreen API；筛选控件基于 Radix Portal。
- 已检查文件 Relevant files inspected: `DashboardDetail.tsx`、`EditorCanvas.tsx`、`MultiSelect`、`Popover`、`Select`、`DropdownMenu`、`AdvancedDatePicker.tsx`、`QueryFilter.tsx`、`DimensionFilter.tsx`。
- 现有测试或验证命令 Existing tests or validation commands: Vitest、`npm run build`、`scripts/arch-guard.sh`。
- 项目约束 Constraints from project guidance: TypeScript、函数组件、无新增 UI/状态库、最小必要修改、保护脏工作树。

## 目标 / 非目标 Goals / Non-Goals

### 目标 Goals
- 全屏切换后，受影响基础浮层选择正确的 Portal 容器。
- 普通模式和显式容器行为保持兼容。
- 同一根因由共享实现统一处理。

### 非目标 Non-Goals
- 不修改 Fullscreen API 调用目标。
- 不重构 Radix 组件结构或业务筛选组件。

## 边界承诺 Boundary Commitments
| Boundary | Allowed Change | Disallowed Change | Revalidation Trigger |
|---|---|---|---|
| `bs-ui` 浮层 | Portal 容器解析与全屏事件订阅 | 视觉样式、选择行为、数据请求 | 组件公开交互或样式变化 |
| 数据看板 | 复用修复后的基础组件 | 查询、布局、保存逻辑 | 业务配置发生变化 |

- Allowed dependencies: `none`

## 需求追踪 Requirements Traceability
| Requirement | Acceptance Criteria | Design Element | Verification Strategy |
|---|---|---|---|
| REQ-001 | AC-REQ-001-01..03 | `useOverlayPortalContainer` 及四类 Portal 包装组件 | Vitest DOM 回归 + 生产构建 |

## 架构设计 Architecture
- Pattern: 共享容器解析 hook + 基础组件适配。
- Rationale: 全屏状态属于所有浮层的共同运行时条件，集中处理可避免业务组件逐个传参和遗漏。
- Preserved existing patterns: Radix Portal、已有 `portalContainer` 显式覆盖能力、标准 `fullscreenchange` 事件。
- Architecture change justification, if any: 新增一个无持久状态的 UI hook，统一已有分散的 Portal 容器决策。

## 文件结构计划 File Structure Plan
| Path | Action | Responsibility | Linked Requirement |
|---|---|---|---|
| `src/frontend/platform/src/components/bs-ui/useOverlayPortalContainer.ts` | create | 跟踪全屏元素并解析 Portal 容器优先级 | REQ-001 |
| `src/frontend/platform/src/components/bs-ui/popover/index.tsx` | modify | Popover 使用解析后的容器 | REQ-001 |
| `src/frontend/platform/src/components/bs-ui/select/index.tsx` | modify | Select 使用解析后的容器 | REQ-001 |
| `src/frontend/platform/src/components/bs-ui/dropdownMenu/index.tsx` | modify | DropdownMenu 与子菜单 Portal 使用解析后的容器 | REQ-001 |
| `src/frontend/platform/src/components/bs-ui/multiSelect.tsx/index.tsx` | modify | 看板 MultiSelect 使用解析后的容器 | REQ-001 |
| `src/frontend/platform/src/test/fullscreenOverlayPortal.test.tsx` | create | 复现并验证全屏、退出全屏和显式容器行为 | REQ-001 |

## 组件与接口 Components and Interfaces

### `useOverlayPortalContainer`
- Responsibility: 返回 `explicitContainer ?? fullscreenElement ?? undefined`，并在全屏状态变化时刷新。
- Inputs: 可选显式 `Element | DocumentFragment | null`。
- Outputs: Radix Portal 可接受的容器。
- Dependencies: React state/effect、浏览器 Fullscreen API。
- Error behavior: SSR 或无 Fullscreen API 时返回显式容器或 `undefined`。
- Requirements: REQ-001

## 数据 / 状态变化 Data / State Changes
- Entities: `none`
- Persistence changes: `none`
- Migration or rollback: 删除 hook 与四处接入即可回滚。
- Compatibility: 非全屏状态保持默认 body Portal；显式容器优先级不变。

## 测试策略 Testing Strategy
| Acceptance IDs | Risk / Level | Distinct Outcomes | Primary Layer | Evidence Group | Stop Condition |
|---|---|---|---|---|---|
| AC-REQ-001-01..03 | medium/V2 | 全屏挂载、退出恢复、显式覆盖 | Vitest DOM integration | EG-001 | 回归测试、相关既有测试和前端 build 通过 |

## 设计决策 Decisions
### Decision: 不改变全屏目标，改为动态选择 Portal 容器
- Context: 改为对 `document.documentElement` 全屏会把看板外页面一并展示。
- Options considered: 对整个文档全屏；业务组件逐个传容器；基础浮层统一解析。
- Decision: 基础浮层统一解析当前全屏元素。
- Rationale: 保持当前全屏视觉范围，并覆盖所有同根因组件。
- Consequences: 共享组件订阅全屏事件，但不引入新依赖或持久状态。

## 风险 / 取舍 Risks / Trade-Offs
| Risk | Impact | Mitigation | Owner / Phase |
|---|---|---|---|
| 共享组件普通页面回归 | 下拉挂载位置变化 | 无全屏时返回 `undefined`，增加退出和显式容器测试 | implementation |
| 组件已挂载后才进入全屏 | 容器值陈旧 | 监听 `fullscreenchange` 与 `webkitfullscreenchange` | implementation |

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
