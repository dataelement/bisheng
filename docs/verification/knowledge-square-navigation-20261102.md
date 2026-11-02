# 发现广场知识空间预览导航

## 问题与根因

2026-11-02 测试记录 `reczz28TecWh76aD` 重新打开：Windows Desktop 从发现广场进入需审核的知识空间后，页面缺少明确返回入口，重复点击发现广场仍停留在详情。

记录原始附件对应 `/square` 中的知识空间预览抽屉。原逻辑将抽屉状态保存在组件内，打开后 URL 仍为 `/square`；Desktop `EnterpriseChatView.navigate()` 对相同 URL 提前返回，组件因此继续展示抽屉。原抽屉的收起按钮位于左侧中部，固定 1000px 宽度还会使窄视口中的左缘超出可视区域。此前知识空间文件列表的来源 tab 修复覆盖另一条导航路径。

## 实现

- 使用 `previewSpace` 查询参数表示当前预览空间。原生发现广场入口指向列表 URL，路由变化直接关闭预览。
- 关闭预览时清理该参数，保留分类及其他来源参数；列表继续挂载，保留本次列表搜索状态。浏览器前进、后退和直接预览链接均由同一状态来源驱动。
- Desktop 嵌入预览顶部使用共享 Button 和已有翻译展示“返回”；浏览器保留原有关闭入口。抽屉宽度随视口收缩，上限 1000px。
- 交付范围为 Client 网页。知识权限、成员、审批与服务端配置沿用现有实现。

## 基线与环境

- BISHENG：`upstream/feat/bisheng-work-120-main@725ee5bf38d4ff2d067763fb305817a730b238a4`，交付前再次核对远端一致。
- 分支：`codex/knowledge-square-navigation`；工作目录：`.worktrees/bisheng-knowledge-square-navigation-20261102`。
- 原生验证宿主：Desktop `V1.2.0` 基线上的 `011e8e2d0ad3b01941e7b2b39f3b5c4d137ee061`，工作目录 `.worktrees/bisheng-splash-locale-20261102`；Harness `0.2.1-rc.2`，Electron `43.0.0`，macOS。
- 前端工具版本：pnpm `9.15.9`；沿用已安装依赖，依赖清单和锁文件保持一致。

## 自动验证

| 项目 | 结果 |
| --- | --- |
| 原代码对照：新增预览路由回归 | 5 项失败，确定性复现 |
| 修复后导航、撤销权限、来源 tab、嵌入识别、布局、MainLayout 回归 | 7 文件 / 38 项通过 |
| 前端 workspace ESLint | 通过 |
| 前端 workspace typecheck | 通过；Platform 620、Client 1518 个严格类型文件 |
| Client 生产构建、i18n、架构守卫、差异检查 | 通过 |
| macOS 原生 Electron 联合验证 | 12 组通过 |

原生验证使用实际 `KnowledgeSquarePane`、预览抽屉、Sheet、共享 Button、生产 CSS、`useDesktopNavigation`、Desktop preload 和 `EnterpriseChatView`。知识数据、权限 API、列表和插图采用隔离夹具。矩阵覆盖窗口宽度 900/1280、缩放 100%/125%/150%、深浅主题。每组调用实际 `openPage('square')` 并触发顶部返回按钮，验证抽屉关闭、路由参数清理及按钮边界位于视口内。按钮触发通过 DOM；Windows 原生鼠标与系统 DPI 验收单列。

截图已检查窄窗口浅色和宽窗口深色视图。日志包含现有 SheetOverlay ref 和夹具 CSP 提示；生产安全策略沿用原配置。构建包含既有 PWA maskable icon 匹配提示。

复现入口（先构建 Client，Desktop checkout 提供实际宿主源码和 Electron/esbuild 依赖）：

```sh
DESKTOP_SOURCE=/absolute/path/to/bisheng-desktop \
  node scripts/verify-knowledge-square-navigation.mjs /absolute/path/to/evidence
```

本地证据存放外层工作区 `outputs/knowledge-square-navigation-20261102/`：红绿测试、lint/typecheck/build/i18n 日志，`native/electron-results.json` 和视图截图。截图、构建产物和依赖存放仓库快照之外。

## 部署后 Windows 验收

状态：Client 部署、Windows 安装版真实账号验收待执行。

1. 部署包含此提交的 Client，重新进入发现广场，核对网页资源版本。
2. 使用原复现账号打开原知识空间预览，确认顶部出现“返回”。点击后应回到发现广场知识空间列表，分类及搜索上下文保留。
3. 再次打开预览，通过左侧发现广场入口回到广场首页或对应分类。
4. 覆盖审批前、待审核、已加入、权限撤销状态，以及窄窗口、100%/125%/150% Windows 系统缩放、深浅主题。
5. 检查浏览器中的关闭、历史前进/后退和直接链接，核对 Desktop 窗口级模态关闭后侧栏恢复交互。

上述自动化证明路由根因修复及 macOS 原生宿主集成；Windows 安装包、真实服务与账号的最终结果由此清单补齐。
