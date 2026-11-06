# 项目内新建对话：验证记录

## 3.0 移植验证（2026-11-03）

以下自动化验证在 feat/3.0.0（基线 `463d6fc20c`）上执行。本节之后的「页面验证」是原 3.1 实现的记录，3.0 尚未做页面实测。

- [x] 本功能 5 个 Jest 套件共 19 项通过：`Convo.menuExit`、`ConvoOptions.projects`、`NewChat.project`、`useAiChatSSE.project`、`SidebarProjects.newChat`。
- [x] client 全量 Jest 与未改动的 3.0 基线对比：基线 160/200 套件通过，移植后 165/205 套件通过；失败的 40 个套件两边相同，没有新增失败。
- [x] client `tsc-strict` 全部通过；改动的 14 个 ts/tsx 文件 eslint 通过；`scripts/arch-guard.sh` 通过。
- [ ] 3.0 页面实测：AC-01、AC-02（桌面）、AC-03、AC-04、AC-06～AC-09，以及窄屏下「移入项目」保持隐藏。

## 原 3.1 实现的验证记录

日期：2026-11-02。页面环境：`http://localhost:4001/workspace`，现有登录会话。
本次没有新增或修改 API，验证集中在 UI 与流式创建链路；无需新增后端 API 测试。

### 页面验证

- [x] AC-01：项目“更多”右侧显示新建图标；浏览器实测两个按钮均为 20×20、4px 圆角、同一文字颜色与透明背景，两个按钮边界间距为 4px，悬停与显隐使用同一份样式。
- [x] AC-02：点击 `e2e-项目内新建` 的新建图标，项目展开，进入 `/c/new?projectId=…` 空白普通对话。
- [x] AC-03：发送专用测试消息后，真实会话出现在该项目下，平铺列表没有重复；刷新后项目展开仍可找到会话，并能看到完整回答。
- [x] AC-04：点击全局“新建对话”回到无项目参数的空白页。
- [x] AC-06：对话行“更多”与项目操作复用同一基础样式；浏览器实测均为 20×20、4px 圆角、相同文字颜色且无额外光圈；打开菜单能看到重命名／移入项目／删除，点击后 URL 与会话保持不变，点击页面外部能收起菜单。客户端 lint 与 typecheck 通过。
- [x] AC-06 后续显隐调整：在 `Initial Try` 选中时实测未悬停为 `display: none`／`opacity: 0`；点击会话产生鼠标焦点后，悬停显示为 `display: flex`／`opacity: 1`；菜单能打开，点击页面外部收起后仍选中且按钮隐藏。客户端 lint／typecheck 与 10 项导航、窄屏回归通过。
- [x] AC-07：页面实测“移入项目”子菜单按“新建项目／分割线／已有项目／分割线／移出项目”呈现；自动化验证有项目时两处分割线、无项目时仅保留新建项。
- [x] AC-08：页面实测点击新建项后菜单关闭并进入命名弹窗，输入框获得焦点；取消后当前会话仍在原项目、URL 不变。新增 4 项集成测试覆盖分组、空列表、创建并自动移入、取消不变；客户端 lint 与 typecheck 通过。
- [x] AC-09：新增生命周期回归先复现“退出期间操作区提前变为 display:none”，修复后 10 项导航与项目菜单用例通过。浏览器连续采样确认：主菜单／子菜单在 open 和 closed 的 popup-out 阶段分别保持 x=92／224，触发按钮宽度始终为 20px；菜单消失后按钮才收起，命名弹窗显示并聚焦。客户端 lint／typecheck 通过。
- [x] 回归：项目“更多”正常打开重命名／删除菜单，打开项目内已有会话正常。

### 自动化补充

- [x] AC-02：窄屏新建关闭导航，重新打开时项目保持展开。
- [x] AC-04：连续选择两个项目、全局新建清除参数、快速导航不受旧延迟重置影响。
- [x] AC-05：流式延迟创建仍归入发起项目、重复事件不覆盖后续移动、已删项目不留孤立归属、任务 handoff 正常归属。
- [x] 无项目、未知项目、已有会话、其他模块及自定义 SSE 地址均不误归属；无正式创建 id 不写入占位记录。

三个 Jest 套件共 17 项通过。运行命令：

```bash
NODE_OPTIONS=--require=/tmp/bisheng-project-new-chat-jest.cjs pnpm --filter bishengchat exec jest --runInBand --coverage=false --silent --runTestsByPath src/components/Nav/NewChat.project.test.tsx src/hooks/useAiChatSSE.project.test.ts src/layouts/WorkbenchSidebar/WorkbenchSidebar.mobile.test.tsx
```

客户端 lint、全仓 typecheck、架构守卫及 diff 空白检查通过。全仓 lint 在未修改的 platform 文件先行失败：`controllers/API/linsight.ts` 5 处 any，`test/speechForm.test.tsx` 1 处未使用变量；已用 `git diff HEAD -- <path>` 确认这两个文件无本次改动。

代码复核：边界、既有授权入口、异步归属、信息泄漏、AC 覆盖、风格与文档同步均无新增阻断项。项目仍沿用浏览器本地归属机制。
