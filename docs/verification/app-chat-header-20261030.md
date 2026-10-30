# 应用会话顶部交互 — 2026-10-30

## 基线与范围

- 代码仓库：`dataelement/bisheng`，目标 `feat/bisheng-work-120-main@1954f60c4acba5de5cca5e9385b76fc6b21effc0`。提交前远端复核一致。
- 工作目录：`.worktrees/bisheng-app-chat-header`；分支 `codex/app-chat-header`。
- 对照桌面源码：`dataelement/bisheng-desktop:V1.2.0@e928c8c3bd5d2f188f17b7d93e0fbd7bc13eaf90`。已安装 BISHENG 应用内 Harness 为 `0.2.1-rc.2`。
- 早期 DSH `v0.9.0` 远端分支查询为空；其参考集成工作树检查时干净。截图行为归属当前毕昇应用会话页面，本次修复提交到网页代码仓库。

## 根因与实现

1. `MobileAppHistoryDropdown` 原来通过 body portal 声明 `role=dialog / aria-modal=true`。桌面 `observeEnterpriseModals` 按该语义扩展原生视图到整个窗口，触发 `AppRoot` 的 1023px media query。宽屏卸载下拉组件，桌面随后恢复内容区宽度，紧凑布局再次挂载组件，循环继续。现在历史列表作为有名称的 `region` 展示，窗口级 modal 继续用于真正的对话框。
2. 合并标题栏的菜单原来总是设置移动系统菜单状态；桌面嵌入模式和 768–1023px 浏览器布局都有自己的应用侧栏。`AppRoot` 通过 `onMenuClick` 提供桌面侧栏动作，移动端继续使用原系统菜单。历史展开期间桌面菜单保持可用。
3. `handleCreateNewAppChat` 原来强制收起应用侧栏。现在创建会话保留侧栏状态，列表内的新建/选择操作沿用 `useAppSidebar` 的导航及来源记录。
4. 历史列表支持 Escape 关闭与触发按钮焦点恢复；生命周期清理键盘监听。组件中的两条旧硬编码回退文字复用现有多语言键，ESLint 基线通过工具清理对应的两条历史豁免。

## 自动验证

- `client/src/routes/AppRoot.test.tsx` 联合运行真实 AppRoot、MobileNav 和 MobileAppHistoryDropdown，账号/会话数据与页面导航采用夹具；新增 12 项。覆盖侧栏初始展开/收起、菜单往返、加号及列表新建、列表选择、窗口宽度反馈循环、Escape、重渲染焦点恢复、卸载与移动菜单。
- 基线对照：原实现 9 项失败、3 项通过；反馈循环显示 `[1200,900,1200,900,1200,900]`。修复后连续保持 900px。
- 相关 5 个测试文件 / 26 项通过：AppRoot、appChatOrigin、desktopEmbedding、usePrefersMobileLayout、DesktopShellBridge。
- 前端全量 ESLint 通过（Client、Platform、UI、file-viewers）；类型检查通过（Client 1502 个严格文件、Platform 620 个严格文件、file-viewers tsc）。使用现有依赖树执行与工作区脚本对应的工具，依赖锁文件保持一致。
- Client Vite 生产构建、语言资源一致性、受影响文件架构检查及 `git diff --check` 通过。

## 原生隔离验证与验收边界

- macOS Electron 使用临时 profile、本机 HTTP 夹具、真实 MobileAppHistoryDropdown、真实 media query、真实 Desktop EnterpriseChatView 及 preload。页面数据服务采用夹具，标题按钮通过 DOM 事件激活；Escape 使用 Electron 键盘输入。
- 1100/1200/1280px 窗口各保持 280px 宿主侧栏，内容宽度为 820/920/1000px；历史展开期间每组 20 次原生边界采样稳定，Escape 后保持原边界。
- 本地证据：主工作区 `outputs/app-chat-header-20261030/`，含原生脚本、日志、截图、采样结果与自动验证日志。
- 交付状态为源码修复与本地验证完成。测试环境网页部署、Windows 安装版、真实账号应用会话新建/切换与侧栏持久状态复测待执行。
