# 知识空间预览布局修复

## 问题与实现

Windows Desktop 从发现广场打开知识空间预览，返回入口和正文左缘错位，标题前留白叠加，加入状态按钮落在统计行右侧。

源码中 `touch-mobile` 对应视口宽度 ≤1023px。该宽度下正文使用外层 16px 留白，返回栏额外保留 24px，Button 自带 16px 水平内边距，形成 40px 错位。Sheet 的 16px 子项间距与标题 24px 顶部内边距共同形成 40px 空隙；文件区上方同样叠加两层间距。

本次修复由 SheetContent 统一持有水平留白，子区域沿用共同边界。返回按钮保留共享组件尺寸，其图标与正文对齐。相邻区域间距分别由标题区和文件区的 16px 内边距负责。加入状态按钮移至标题右侧，使用共享 Button 的 medium 尺寸；标题自动换行，统计数量按可用宽度换行。浏览器手机布局为右上关闭入口保留专用顶部空间，判定与现有关闭入口共用 `usePrefersMobileLayout`。

## 基线与范围

- 目标：`dataelement/bisheng:feat/bisheng-work-120-main`，基线 `1e495e15a46bcb749a86642e292ff2c35897d847`。
- 分支：`codex/knowledge-preview-layout-20261103`。
- 工作区：`.worktrees/bisheng-knowledge-preview-layout-20261103`。
- 变更范围：Client 预览布局、现有渲染验证脚本及交付记录。导航、权限与订阅业务沿用现有实现。
- 本地渲染宿主：Desktop `011e8e2d0ad3b01941e7b2b39f3b5c4d137ee061`，目录 `.worktrees/bisheng-splash-locale-20261102`；实际 Harness `0.2.1-rc.2`、Electron `43.0.0`，macOS。该 checkout 作为验证夹具提供现有原生宿主和 preload。
- 使用现有已安装依赖及 pnpm `9.15.9`。依赖清单和锁文件沿用发布基线。

## 验证

- 旧版对照确定性失败：返回图标 x=57、标题和文件入口 x=17，水平差值 40px；标题 y=88、返回按钮底边 y=48，间距 40px。旧版操作按钮 y=164，标题 y=88。
- 相关组件回归 3 文件 / 15 项通过：返回、浏览器关闭、路由导航、权限撤销。
- 前端全量 ESLint、类型检查、Client 生产构建、i18n、变更文件架构守卫与差异检查通过。
- macOS Electron 实际宿主布局与导航 54 组通过：窗口宽度 900 / 1280 / 1600、缩放 100% / 125% / 150%、深浅主题、已加入 / 待审核长标题 / 加入三种状态。返回图标与标题的最大横向偏差为 0px。
- 独立浏览器模式 390 / 900 / 1400 三档宽度的布局和关闭验证通过。已检查桌面浅色、长标题深色及手机宽度截图。

渲染脚本使用实际预览组件、共享 Sheet / Button、生产 CSS、Desktop 宿主及 preload。知识 API、权限、列表入口、插图和文件卡片为隔离夹具。断言覆盖图标/标题/文件入口左缘一致、顶部间距、操作与标题同行、长标题边界、水平溢出以及两条返回路径。浏览器分支由独立窗口直接加载页面，验证关闭操作与移动端关闭按钮占位。

复现命令：先构建 Client，然后执行：

```sh
DESKTOP_SOURCE=/absolute/path/to/bisheng-desktop \
  node scripts/verify-knowledge-square-navigation.mjs /absolute/path/to/evidence
```

本地证据：外层工作区 `outputs/knowledge-preview-layout-20261103/`，包括构建、代码检查、组件回归、旧版对照日志，以及 `native/` 的布局测量和截图。构建保留现有字体路径、第三方 eval、PWA 图标警告；渲染日志保留现有 SheetOverlay ref 和夹具 CSP 提示。

## Windows 交付验收

### PR #2591 合并冲突处理

2026-11-03 同步目标分支 `e7319073fbd69ac21b5e720ca760724e8f346ef6`。冲突集中于 `docs/STATUS.md` 首部的独立新增记录，已完整合并双方内容。两份布局组件及原生验证脚本与原提交 `afe6c982ac986c86ce32f5348055cd1f41d0a803` 逐字节一致；目标分支同期的权限和导航修复一并保留。

同步后 3 文件 / 15 项组件回归、前端全量 ESLint、Platform 620 个及 Client 1520 个严格类型文件与 file-viewers 类型检查、Client 生产构建、i18n 和差异检查通过。沿用 pnpm 9.15.9 与现有依赖，日志位于外层工作区 `outputs/knowledge-preview-layout-20261103/pr-sync/`。原生布局证据沿用本记录前述结果，本轮完成合并组合验证。

状态：Client 部署、Windows 安装版和真实账号验收待执行。

1. 部署包含本次提交的 Client，重新打开发现广场中的知识空间详情。
2. 在截图对应窗口尺寸确认返回图标、空间标题和文件列表左缘一致，顶部间距紧凑，加入状态位于标题右侧。
3. 覆盖加入、待审核、已加入，以及长标题、有说明、空列表和文件列表。
4. 覆盖窗口缩放和 Windows 系统 DPI 100% / 125% / 150%、深浅主题，确认返回、文件预览和滚动。
5. 浏览器桌面与手机宽度验证关闭入口，核对真实账号的订阅及权限结果。
