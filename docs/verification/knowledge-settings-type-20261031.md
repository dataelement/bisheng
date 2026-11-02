# 桌面知识空间设置字号 — 2026-10-31

## 基线与范围

- BISHENG 网页仓库，版本分支 `feat/bisheng-work-120-main@6d5651ad4849964cd587fee5e53ee4a8df3bc9d5`；提交前远端核对一致。
- 工作目录 `.worktrees/bisheng-knowledge-settings-desktop-type`，分支 `codex/knowledge-settings-desktop-type`。
- 已安装 BISHENG 包版本 `1.2.0-test.2`；同会话读取应用包元数据确认 Harness 包 `@deepseek-ai/dsh-harness-dev-context@0.2.1-rc.2`。
- 本次变更属于网页前端。知识空间设置页面及共享控件继续使用原有文字层级、交互和业务逻辑；桌面窄内容区使用桌面字号。

## 根因及修正

- 桌面宿主侧栏占用窗口宽度后，内嵌网页的内容宽度可能落入 ≤768px 的移动断点。布局 Hook 已通过 `embed=dsh` 和会话标记识别桌面身份，CSS 仅按宽度选择移动字号。
- 字体语义变量把正文 14/22 切为 16/24；两处移动输入控件规则还会放大输入框及文本域。截图中的局部字号差异可由这一组合稳定复现。
- 网页启动时把既有桌面身份同步到根元素 `data-bisheng-surface`。移动字体映射、共享输入控件防缩放规则和客户端旧输入控件防缩放规则共同使用该身份，桌面内容区沿用原始桌面字阶。
- 浏览器/H5 保留原有窄屏字阶与 16px 输入体验。桌面窗口尺寸和页面排版断点仍参与原有布局适配。
- 此处修复作用于使用同一身份与字阶的桌面嵌入页面；字号数值与组件样式定义保持原值。

## 验证

- 7 文件、35 项相关自动回归通过，含首次桌面入口、路由重定向/重载、独立浏览器、存储不可用时的显式入口、桌面主题和布局、空间设置结构及此前应用返回按钮行为。
- 使用真实 KnowledgeSpaceSettingsPage、Input/Textarea、权限设置控件、生产 CSS 和桌面暗色主题代码，在 macOS Electron 中执行原版/修正版对照；数据服务和授权名单使用夹具。
- 原版/修正版 × 桌面/浏览器 × 752/768/769/920px CSS 内容宽度 × 100%/125%/150% Chromium 页面缩放，共 48 组检查通过。每组核对实际内容宽度、标题/字段标签/输入框/文本域字号与横向溢出；真实保存处理函数调用夹具保存并返回空间页。
- 原版 752/768px 桌面：16px/24px；修正版同宽桌面：14px/22px；同宽浏览器保留 16px/24px。
- Client/Platform/UI/file-viewers 全量 ESLint，Client 1505 个与 Platform 620 个严格类型文件，UI/file-viewers 类型检查，Client 生产构建、i18n 和差异检查通过。
- 证据位于主工作区 `outputs/knowledge-settings-type-20261031/`，包括 `before.png`、`after.png`、`native-results.json` 和验证脚本。

## 验收边界

- 当前状态为源码修复和本地自动验证完成。上述缩放为 macOS Electron 的 Chromium 页面缩放。
- 测试环境镜像部署、Windows 已安装客户端及其 100%/125%/150% 系统 DPI、真实账号空间设置读取和保存验收待执行。
