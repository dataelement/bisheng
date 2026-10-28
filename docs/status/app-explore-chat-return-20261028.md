# 发现广场应用对话返回修复

## 范围与基线

- 修改仓库：`dataelement/bisheng`，目标 `feat/bisheng-work-120-main`。
- 开始基线：`e468e2f2bcfe3c855e159193c0f96e18aec1453d`；PR 交付基线：`174394b3237d10460477fdefd0d4ba8871c7a913`。
- 工作目录：`.worktrees/bisheng-app-explore-chat-return`；分支：`codex/app-explore-chat-return`。
- 本次修改平台网页客户端。参考 macOS 测试运行时：Electron `43.0.0`；本机毕昇 Work 依赖 Harness `0.2.1-rc.2`。DSH Desktop v0.9.0 集成目录已查为干净，本次源码归属毕昇客户端。

## 根因与实现

- `MainLayout` 将应用中心和应用对话放入同一 `apps_tab` 缓存。应用中心会话 → 发现广场 → 应用分类进入会话后，地址更新，但缓存组件仍读旧会话与旧返回目标。
- 应用探索卡片保存旧 `/apps/explore` 地址，发现广场实际入口已为 `/square?type=apps`。
- 应用对话路由改为读取当前路由上下文；来源保存为当前广场的应用分类。返回目标白名单纳入该明确地址，同时保持应用中心、移动端探索及首页的已有返回路径。

## 验证

- 使用实际 MainLayout、AliveScope、React Router、ExplorePlaza、AppChatEntry、AppRoot、SideNav。应用列表、账号及对话服务使用夹具。
- 原始实现下 3 项回归失败，其中跨入口场景复现地址与页面内部会话不一致。
- 修复后相关 4 组 / 25 项回归通过：广场新会话与历史会话、跨入口重入、应用中心返回、移动端返回、来源白名单及原有频道导航。
- 客户端、平台、UI 和文件预览库 ESLint；客户端与平台严格类型检查、文件预览库类型检查；生产构建、i18n、架构守卫和差异检查通过。
- macOS Electron 43.0.0 本地组件窗口：应用中心会话 → 广场分类 → 新会话 → 返回广场应用，随后应用中心会话 → 返回应用中心，两条路径通过。
- 提交 PR 前同步知识空间聊天导航修复，应用与知识空间组合回归 5 组 / 26 项通过；客户端 1,490 个严格类型文件、ESLint 与生产构建通过。平台 619 个严格类型文件及 ESLint 检查记录保留在前轮证据。
- 证据目录：`outputs/app-explore-chat-return-20261028/`，包含原始失败、回归、静态检查、构建和 Electron 结果。

## 交付边界

源码修复及自动验证完成。测试环境部署、真实账号数据和已安装 macOS 客户端完整验收待执行。Electron 验证范围为实际导航组件与服务夹具。
