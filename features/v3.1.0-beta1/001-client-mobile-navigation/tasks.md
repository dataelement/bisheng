# Tasks: 工作台窄屏新版完整侧栏

**关联规格**：[spec.md](./spec.md)
**设计**：[design.md](./design.md)
**版本**：v3.1.0-beta1
**工作分支**：`codex/001-client-mobile-navigation`，从 `feat/3.1.0-beta1` 创建。原模板分支名与既有发版分支的 Git ref 前缀冲突，故采用 Codex 默认前缀；最终以当前发版线为合入目标。

## 状态

| 步骤 | 状态 | 备注 |
| --- | --- | --- |
| spec.md | ✅ 已评审 | 2026-10-30 用户明确确认 |
| design.md | ✅ 已评审 | 用户明确修正为主屏右推、露出底层侧栏；按指示更新并实施 |
| tasks.md | ✅ 已拆解 | 已按任务清单自审；前端 Client 实现与验证，无后端改动 |
| 实现 | 🔲 进行中 | 按下列依赖顺序实施；不派发并行 agent |

## Wave 1：导航状态与侧栏内容

- [ ] **T001**：增加窄屏全局导航行为测试。
  **文件**：`src/frontend/client/src/layouts/WorkbenchSidebar/WorkbenchSidebar.mobile.test.tsx`、`src/frontend/client/src/layouts/MainLayout.mobile.test.tsx`。
  **逻辑**：测试新版入口、主屏右推语义、同路径导航收起、焦点与背景恢复、菜单开关及断点切换后的项目状态／页面草稿保留；依赖实际 Radix 行为，业务查询使用受控数据。
  **覆盖 AC**：AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-10, AC-11, AC-12, AC-13, AC-14。
  **依赖**：无。

- [ ] **T002**：使项目和会话区接收稳定控制状态与导航关闭回调。
  **文件**：`src/frontend/client/src/layouts/WorkbenchSidebar/SidebarProjects.tsx`、`src/frontend/client/src/layouts/WorkbenchSidebar/SidebarConversationList.tsx`。
  **逻辑**：内容消费上层共享会话查询；项目展开 id 与列表滚动位置由稳定侧栏控制层持有；保留现有业务动作，导航时显式关闭。
  **验证**：T001 中项目展开、历史会话和滚动恢复场景。
  **依赖**：T001。

- [ ] **T003**：实现稳定挂载的侧栏控制层与底层模态导航外壳。
  **文件**：`src/frontend/client/src/layouts/WorkbenchSidebar/WorkbenchSidebar.tsx`、`src/frontend/client/src/layouts/WorkbenchSidebar/WorkbenchSidebarUnderlay.tsx`。
  **逻辑**：桌面仍使用现有侧栏；窄屏底层容器绝对定位、宽 240px，Radix 管理焦点与滚动，透明拦截层只覆盖右移主屏；保存控制状态与查询订阅，避免关闭后丢失已加载页。详见 design 决策 1–4。
  **验证**：T001；嵌套更多菜单与项目弹窗。
  **依赖**：T002。

- [ ] **T004**：补齐同会话点击及账号入口的关闭回调。
  **文件**：`src/frontend/client/src/components/Conversations/Convo.tsx`、`src/frontend/client/src/layouts/UserPopMenu.tsx`。
  **逻辑**：同会话点击仅关闭菜单，不重复导航；账号设置入口调用显式回调，更多操作与改名不触发导航关闭。
  **验证**：T001 对应行为场景及既有会话测试。
  **依赖**：T003。

## Wave 2：布局接线与窄屏排版

- [ ] **T005**：替换全局旧图标栏，保留主屏右推层级。
  **文件**：`src/frontend/client/src/layouts/MainLayout.tsx`、`src/frontend/client/src/layouts/WorkbenchSidebar/workbench-navigation.css`。
  **逻辑**：删除旧 Sidebar／应用抽屉和失效状态；唯一挂载新版侧栏；主屏右推 240px、左缘圆角；路由／断点变更清理菜单状态；记录焦点触发器；CSS 仅负责导航动效与作用域样式，不修改公共 token。
  **验证**：T001、既有 MainLayout 导航及知识问答交接测试。
  **依赖**：T003, T004。

- [ ] **T006**：移除旧主站聊天侧栏挂载与失效导出。
  **文件**：`src/frontend/client/src/routes/Root.tsx`、`src/frontend/client/src/components/Nav/Nav.tsx`、`src/frontend/client/src/components/Nav/index.ts`。
  **逻辑**：确认调用方后删除旧 Nav，保留标题快捷历史下拉和应用专属历史；页面 Outlet 与 KeepAlive 不改变位置和 key。
  **验证**：T001 与既有移动顶栏／应用导航测试。
  **依赖**：T005。

- [ ] **T007**：修复工具与技能首页窄屏页头及列表约束。
  **文件**：`src/frontend/client/src/components/ModuleHome/ModuleHome.tsx`、`src/frontend/client/src/pages/capabilities/CapabilityCenterPage.tsx`。
  **逻辑**：共享页头增加可选窄屏模式，仅本页启用；单一可见标题、搜索整行、分类与上传按宽度换行、列表 min-width 约束，保留原有页面状态与其他调用方默认外观。
  **验证**：T009；浏览器逐档检查收起菜单时无横向越界。
  **依赖**：T005。

- [ ] **T008**：检查聊天菜单热区及导航内触屏操作。
  **文件**：`src/frontend/client/src/components/Nav/MobileNav.tsx`、`src/frontend/client/src/layouts/WorkbenchSidebar/ProjectNameDialog.tsx`。
  **逻辑**：菜单开关使用既有透明 44px 热区，导航内项目子弹窗层级保持可用；其余菜单触发器通过导航作用域提供不重叠的热区，避免扩大业务页面逻辑改动。
  **验证**：T001；浏览器触屏与嵌套弹窗操作。
  **依赖**：T005。

## Wave 3：验证与交付

- [ ] **T009**：验证工具与技能窄屏交互及页头默认兼容。
  **文件**：`src/frontend/client/src/pages/capabilities/CapabilityCenterPage.test.tsx`、`src/frontend/client/src/components/ModuleHome/ModuleHome.test.tsx`。
  **逻辑**：保留搜索／分类／上传／详情行为，重渲染及跨断点不丢失输入；其他页头调用方不启用窄屏模式。
  **覆盖 AC**：AC-08, AC-09, AC-11, AC-12。
  **依赖**：T007。

- [ ] **T010**：执行 E2E、质量检查和任务／特性审查。
  **文件**：本特性 `e2e-checklist.md`、`review.md`。
  **逻辑**：依据 e2e-test skill 验证菜单、层级、背景交互、项目／会话、工具与技能；记录真实环境与受控 API fixture 的边界。运行工作区 lint、typecheck、相关 Jest、i18n 与 arch-guard，执行 task-review 与 sdd-code-review；问题修复后再标完成。
  **覆盖 AC**：AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14。
  **依赖**：T001, T002, T003, T004, T005, T006, T007, T008, T009。

## 实际偏差记录

- 2026-10-30：用户设计确认修正为主屏右推、露出底层侧栏；已同步 spec AC-03、AC-08 与 design 决策 4。
- 2026-10-30：后续用户逐项确认：修复圆角灰底、移除侧栏收起按钮与聊天首页历史标题；窄屏品牌文字 17px、Logo 28px、顶部间距 16px。订阅移动端增加首页，移除模块内广场切换，底部使用通宽 Default 创建按钮；频道与文章采用逐级返回，文章浮动动作随滚动方向显隐。首页卡片按 <576 / 576–768 / >768px 切换 1 / 2 / 3 列。

## 2026-10-30 推送前验证记录

- Client 全量 `pnpm lint`、`pnpm typecheck` 通过。
- 相关 Jest：11 个测试文件、43 个用例通过，覆盖全局导航、侧栏状态、会话导航、工具页、订阅首页、频道返回、文章滚动显隐和错误重试。
- 本地依赖存在未构建的可选 canvas 和未链接的 Babel runtime；测试进程临时禁用 canvas 解析并通过 `--modulePaths` 指向现有 runtime，不修改依赖目录或生产配置。
- 已编译检查卡片 CSS 在 575/576/768/769px 边界处的列数，`git diff --check` 通过。
- 尚未完成真实设备 E2E、完整浏览器验收及特性级审查；以上单测不替代 T010，因此未将整体验收任务标为完成。
