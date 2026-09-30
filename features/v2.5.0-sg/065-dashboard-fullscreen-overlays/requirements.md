# 需求说明 Requirements: 数据看板全屏浮层可用性修复

## 阅读摘要
- 修复数据看板进入浏览器原生全屏后，下拉、日期选择等浮层不可见的问题。
- 当前状态：`confirmed`
- 本次仅调整浮层挂载容器，不改变筛选、查询和图表数据逻辑。

## 元信息 Metadata
- Feature ID: `065-dashboard-fullscreen-overlays`
- Status: `confirmed`
- Mode: `bug-fix`
- Created: `2026-09-10`
- Updated: `2026-09-10`
- Source request: `当前数据看板全屏后所有下拉组件无法打开，要求修复`

## 需求入口摘要 Intake Summary
- 问题 Problem: 数据看板对局部容器调用 `requestFullscreen()` 后，Radix 浮层仍默认挂到 `document.body`，位于全屏元素之外而不可见。
- 当前状态 Current state: 普通模式可打开；全屏模式点击下拉后看不到内容。
- 目标结果 Target outcome: 全屏模式下浮层挂到当前全屏元素内；退出全屏后恢复默认挂载行为。
- 影响对象 Affected users/systems: 平台端数据看板预览与编辑页面、共用的 `Popover`、`Select`、`DropdownMenu`、`MultiSelect`。
- 请求停止点 Requested stopping point: `verification`

## 范围 Scope

### 包含 Includes
- 全屏状态变化时同步浮层 Portal 容器。
- 覆盖数据看板使用的多选下拉、日期弹层、普通下拉和菜单基础组件。
- 保持显式传入的 Portal 容器优先级。

### 不包含 Excludes
- 修改全屏页面布局或全屏目标元素。
- 修改筛选项加载、查询请求或图表数据。
- 调整 Dialog、Tooltip 等与本次复现无关的浮层。

## 需求列表 Requirements

### REQ-001: 全屏内正常展示浮层
作为数据看板使用者，我需要在全屏模式下正常打开筛选和菜单浮层，以便继续筛选与操作看板。

#### 验收标准 Acceptance Criteria
- `AC-REQ-001-01`: WHEN 页面进入局部元素全屏后打开 `Popover`、`Select`、`DropdownMenu` 或 `MultiSelect` THEN 浮层 SHALL 挂载在当前全屏元素内部并可见。
- `AC-REQ-001-02`: WHEN 页面退出全屏后再次打开浮层 THEN 浮层 SHALL 使用原有默认挂载行为。
- `AC-REQ-001-03`: IF 组件显式传入 Portal 容器 THEN 系统 SHALL 优先使用显式容器。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-03 | V-AC-REQ-001 | automated test + build | `src/frontend/platform/src/test/fullscreenOverlayPortal.test.tsx`、平台前端生产构建 |

## 非功能需求 Non-Functional Requirements
- `NFR-001`: 不新增依赖，不改变现有组件对外默认行为。
- `NFR-002`: 兼容标准 `fullscreenchange` 和项目已有的 WebKit 全屏事件路径。

## 澄清记录 Clarifications

### Session 2026-09-10
- Bug report: 用户提供全屏看板截图并确认所有筛选下拉均无法打开。
- Expected: 用户要求直接修复。

## 假设 Assumptions
- 数据看板全屏目标仍为现有的 `#view-panne` 或 `#edit-charts-panne`。

## 风险 Risks
- 共享基础组件改动可能影响普通页面；通过非全屏与显式容器回归场景保护兼容行为。

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
