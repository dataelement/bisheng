# Design: Cascader 移动端单面板

关联：[spec.md](./spec.md) · [e2e-checklist.md](./e2e-checklist.md)。版本：v3.0.0-beta1。最后更新：2026-11-02。

## 1. 目标与范围

共享 Cascader 的手机展示沿用 Select 的锚定浮层、32px 菜单行与现有视觉 token，在同一面板内逐级浏览。保留桌面多列、末级回显、完整路径提交及各业务调用。

## 2. 关键约束

遵循 `docs/constitution.md` 与共享 UI 的展示层契约。手机断点沿用 `PHONE_QUERY`，无新增依赖、请求、业务状态或翻译键。本次是单模块小功能，需求与视觉调整由用户直接给定。

## 3. 方案对比与选定

- **外壳**：选现有 Radix Popover，取消独立固定底部容器与遮罩。定位、碰撞、外部点击和 ESC 均由一条路径处理；若以后另有明确的全屏选择器需求，再考虑独立模式。
- **导航**：手机只挂载当前列，返回使用共享 Button 的 `small`、`text`、`iconOnly`（24px/14px 图标）。导航行 32px，不设分割线；菜单项直接使用 Select 的 `optionClass`，不再增加 44px 手机覆盖。
- **多选**：即时调用 `onChange`，不维护草稿、不设完成按钮。用户在调研后明确选择去掉完成。来源及取舍见组件规范的「BISHENG 取舍」第 6 条；将来只有引入草稿、取消、批量提交时才重新考虑确认动作。
- **高度与滚动**：菜单列保留共享 `MENU_COLUMN` 的最大高度，外壳用 Radix 可用高度限制，手机列表通过可收缩的 flex 链适配剩余空间。按列路径保存 `scrollTop`；只调整菜单列，不对选项调用 `scrollIntoView`。

## 4. 系统现状

### 4.1 数据流

触发器展开 → 恢复已选路径 → 同一 Popover 根据断点渲染多列或手机当前列 → 点击父项下钻 / 返回恢复父项高亮 → 选择叶子或复选框 → 原有值 hook 提交结构化路径。

受控 `open`、`defaultOpen` 和点击展开都在真实打开状态发生变化时恢复路径；关闭清除搜索。手机搜索清空后恢复当前列的键盘导航，输入框左右键保留文字编辑用途。单选或 ESC 收起后恢复触发器焦点；外部点击和 Tab 不抢回焦点。

### 4.2 字段与兼容

`value` / `defaultValue` / `onChange` 的完整路径格式保持不变；`doneLabel?: string` 仅保留类型兼容并标记弃用，不再渲染完成按钮。业务调用无须额外配置即可应用新手机布局。

### 4.3 文件职责

| 文件 | 职责 |
|---|---|
| `Cascader.tsx` | 选择状态、路径导航、展开恢复、统一浮层与焦点 |
| `CascaderMobilePanel.tsx` | 同一浮层内的紧凑返回、父级名称、搜索与树容器；不独立定位、不建 Portal |
| `CascaderPanel.tsx` | 共用行样式、可见菜单列、按路径记录滚动、菜单内定位 |
| `sharedCascader.mobile.test.tsx` | 使用既有 platform Vitest/jsdom 基础设施验证共享组件 |

## 5. 已知坑

| 事实 | 忽略后的影响 | 处理 |
|---|---|---|
| 对浮层选项调用 `scrollIntoView` 可能同时滚动外层页面 | 打开或返回时页面跳动 | `CascaderPanel` 使用元素边界差调整菜单列 `scrollTop`；浏览器实测返回前后页面及菜单位置均相同 |
| 手机只挂载最后一列，清空搜索不能把高亮固定回第 0 层 | 显示的选项和方向键操作对象不一致 | `handleKeyword` 在空搜索时恢复 `columns.length - 1` |
| 仅在点击处理器恢复选中路径，覆盖不到外部受控展开和默认展开 | 外部直接打开时显示根级而非已选层级 | 打开状态变化 effect；对应组件测试覆盖 |
| 主动恢复焦点不能覆盖所有关闭来源 | 点外部输入框或按 Tab 后焦点被抢回 | `restoreFocusOnClose` 区分外部 / Tab 与单选 / ESC |

## 6. 对外契约与依赖

Outgoing：现有 `@bisheng/ui` Cascader 参数和回调；原调用统一获得新手机展示。Incoming：既有 Radix Popover 定位变量、共享 Button/Input/Tooltip、`MENU_COLUMN` / `optionClass`、`PHONE_QUERY`，均无新增版本要求。

## 7. 验证与限制

见 [e2e-checklist.md](./e2e-checklist.md)：19 项回归、共享组件 lint/类型检查、桌面及手机浏览器验证。实机 Safari / 软键盘未在本机验证。全量 lint 被两个未改动文件的既有问题阻断，未扩散修复范围。

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-11-02 | 统一锚定浮层、手机单列返回和滚动；32px 行、small 返回、无导航分割线；多选移除完成按钮 | 用户反馈手机内容不可见，并明确视觉与提交方式 |
