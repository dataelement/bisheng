# 应用会话返回按钮 — 2026-10-31

## 基线

- 仓库与版本：`dataelement/bisheng:feat/bisheng-work-120-main@4cc8f565fb5bc8bd918973ce74f876e6fd66af26`，通过远端 fetch 核对。
- 工作目录：`.worktrees/bisheng-app-chat-back-visible`；分支：`codex/app-chat-back-visible`。
- 本次修改属于 BISHENG 网页应用会话导航。已安装 BISHENG 包版本 `1.2.0-test.2`，应用包内 `@deepseek-ai/dsh-harness-dev-context` 版本 `0.2.1-rc.2`，通过 asar 元数据读取。

## 根因和行为

- 紧凑布局（内容区宽度 ≤1023px）使用 MobileNav。旧逻辑在会话标题加载后隐藏顶栏返回按钮；SideNav 的返回区域同时受 `touch-desktop` 控制，紧凑布局隐藏该区域。侧栏收起时 AppRoot 的宽屏悬浮返回也退出渲染，导致返回入口消失。
- 标题栏现在根据应用返回动作显示返回按钮，标题加载与历史展开均保持入口可用。沿用已有按钮样式，给长标题预留菜单和返回所需的宽度。
- 菜单共用同一处理逻辑：桌面切换应用侧栏，移动端打开系统菜单；操作前关闭历史下拉。
- 返回继续调用现有来源解析：发现广场进入的会话回到 `/square?type=apps`，应用中心进入的会话回到 `/apps`，移动探索回到 `/apps/explore`。

## 验证

- 旧代码对照：新增 3 项标题加载/移动端返回测试均失败，已有 12 项通过。
- 修正后 3 个测试文件、33 项通过。AppRoot 与真实 MobileNav、真实来源解析组合测试覆盖标题加载、侧栏展开/收起、历史展开后的三种来源返回，以及此前菜单、新建和历史下拉行为；探索入口测试使用真实路由验证进入与返回。
- Client 全量 ESLint、1504 个严格类型文件；Platform 全量 ESLint、620 个严格类型文件；UI/file-viewers ESLint、file-viewers tsc 检查通过。Client 生产构建、i18n 与受影响文件架构检查通过。
- macOS Electron 隔离验证使用真实 MobileNav 和生产 CSS，服务与回调采用夹具。390/768/820/920/1000/1023px × 标题加载前后 × 侧栏展开/收起，24 组检查通过：按钮命中区域、与长标题分离、返回回调触发。证据：主工作区 `outputs/app-chat-back-20261031/`。
- 当前状态为源码修复和本地自动验证完成。测试环境部署、macOS/Windows 已安装客户端真实账号的发现广场进入与返回验收待执行。
