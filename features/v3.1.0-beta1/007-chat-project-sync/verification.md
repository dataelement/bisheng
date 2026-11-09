# 项目同步验证记录

更新：2026-11-06。源码位于 Bisheng feat/3.1.0-beta1 与同一 Desktop 工作目录；Desktop 起始分支 V1.3.0，收尾发现并行工作已切至 fix/embedded-page-zoom，HEAD 仍为 7c883d71cf5e52d8d7cd0df4e2db09409d910a70。本任务未创建或切换分支；未创建分支/worktree，未提交或推送，文档仅本地保存。

## 已验证

- 后端：chat_session 全目录、workstation 提交与标题、linsight 标题及统一提交、项目 ASGI/SQL E2E：117 passed。日志 /tmp/bisheng-project-backend-targeted.log。
- Backend 扩展运行最初 18 failed / 412 passed，其中两项标题 mock 已随 Owner 契约调整并通过。其余 16 项在 HEAD 独立源码快照、相同依赖和配置下复现：16 failed / 45 passed，涉及既有导出符号及测试 DB 配置/表。未改这些无关功能，日志 /tmp/bisheng-project-backend-baseline.log。
- Web：最终 9 个相关 Jest suite 43 passed，自动迁移 suite 6 passed；覆盖 shell 挂载、独立分页、不可变意图、SSE 分帧/取消、高水位、失败保稿、批次迁移、来源绑定、账号切换和自动重试。最终日志 /tmp/bisheng-project-web-tests-final.log。
- Web 1838 个 strict 文件 typecheck、ESLint、check-i18n 和生产构建通过。日志 /tmp/bisheng-project-web-{typecheck,lint,build}.log。
- Desktop 相关 5 文件 149 passed；typecheck 与 build 通过。日志 /tmp/bisheng-project-desktop-related.log。
- Desktop 完整回归：333 文件通过、3352 tests passed / 3 timeout / 5 skipped；3 项集中在 PPT 模板，随后该文件独立运行 20 passed。此前 Office 超时文件独立 28 passed；没有将重试结果称为一次完整全绿。完整日志 /tmp/bisheng-project-desktop-full-final.log。
- 真实 macOS Electron 43.0.0，生产 primitives、主进程控制器、私有 Cookie Session、窄 IPC、双 HTTP 客户端、临时 userData：中英/明暗 4 组通过，旧历史、服务端归属、重连和删除失败重试通过；本轮自动同步 25 ms。结果 /tmp/bisheng-chat-project-sync-native/result.json。
- Ruff 新增核心与相关测试通过。arch-guard 对 32 个变更文件运行，返回均为 0；旧 chat.py 跨模块 share_link API import 仍触发 RULE-5，HEAD 中已有相同 import，本次仅传递 login_user，未新增此依赖。
- 两仓库 git diff --check 通过。没有新增依赖或 runtime。

## 实际环境

用户指定 http://192.168.106.119:3006/，并在浏览器登录测试账号。并行发布流程已在 3006 建立四表、SSE 代理和同步接口，API 容器健康；主机上的项目模型哈希与本地一致。实际 Web 创建 SyncCheck1106 后，已运行开发版 Desktop 在未手动刷新的情况下显示同一项目。

首个浏览器保存请求在服务更新期间失败，界面保留输入；重试后保存成功。该现象未仅凭 UI 归因为代码错误。实际双向时延、多账号及全部异常矩阵仍不能由这一次观察替代。

最新用户要求：自动迁移替代手动确认。Web 与 Desktop 已移除迁移入口；Web shell 首次迁移绑定来源到当前账号，失败 2/5/10/30 秒自动重试；原记录保留。该修订已作为 chat-project-auto-20261106-173159 发布到 3006；仅重建 frontend，其他容器 ID、Platform 首页和 nginx/Compose 配置哈希均保持。候选建立在当时服务器源码之上，只覆盖 7 个相关源码文件，核验 467 个构建文件；旧静态资源及上一发布保留。

## 明确未完成的环境验收

- DM8、Redis 多节点/cluster、Windows 原生安装和正式安装包升级未运行。
- ASGI 测试认证在现有依赖边界注入独立 actor，不验证真实 JWT/Gateway；Redis 单测模拟传输，数据库为真实隔离 SQLite。
- Electron 循环服务是经过认证的 fixture，不是 3006 后端；25 ms 仅为隔离环境数值。
- 当前改动已构建，不能据此称用户已安装的旧应用包含修复。
- Web Jest 使用临时 preload 将缺失 native canvas 二进制视为未安装可选依赖；未修改仓库依赖或 node_modules。Jest 使用 --forceExit 完成报告，现有 suite 的 open handles 未作为本功能已解决项。

## 发布后实测

真实 Desktop 将 SyncCheck1106 改名为 SyncReady1106 后，读取后台 Chrome 的 3006 页面无须刷新或点击切换，已显示 SyncReady1106；证明反向自动同步。项目内新对话打开 /workspace/c/new?projectId=<已拥有项目 UUID>，未发送测试消息。真实验证没有为测试删除既有聊天，保留该空验收项目供用户核查。

Desktop 截图：/tmp/bisheng-project-sync-real-desktop.jpg。发布结果：/tmp/bisheng-project-deploy-activate.log；服务器 incoming/chat-project-auto-20261106-173159/result.json，index SHA-256 为 931059c227ad4d509a9fe3e8eb3d253f904232f12d5c1f30ce17644e0525cdf6。本次未发布正式 Desktop 安装包。

## 变动的行为测试

| 仓库 | 测试文件 | 结果 |
| --- | --- | --- |
| Backend | test/chat_session/test_projects_repository.py、test_projects_api.py、test_projects_events.py、test_project_session_lifecycle.py | 新增真实 SQL/API/事件/创建生命周期测试，包含在 117 passed 中 |
| Backend | test/chat_session/test_workflow_file_lifecycle.py、test/linsight/test_task_title.py | 更新 Owner 事务/标题契约断言，包含在 117 passed 中 |
| Backend | test/e2e/test_e2e_chat_project_sync.py | 独立 ASGI 双客户端、actor、分页与 cleanup，包含在 117 passed 中 |
| Web | src/api/chatProjects.test.ts、src/hooks/useProjectMigration.test.tsx、src/layouts/WorkbenchSidebar/projectChatCreation.test.ts | 新协议/SSE、自动迁移和不可变意图；包含在最终 43 passed 中 |
| Web | src/hooks/useAiChatSSE.project.test.ts、src/components/Conversations/ConvoOptions/ConvoOptions.projects.test.tsx | 原子意图/重放不再生成、异步移动/失败保稿；包含在 43 passed 中 |
| Web | src/layouts/WorkbenchSidebar/SidebarConversationList.test.tsx、SidebarProjects.newChat.test.tsx、WorkbenchSidebar.mobile.test.tsx | 服务端 selector、项目草稿与旧侧栏交互；包含在 43 passed 中 |
| Desktop | test/chat-project-sync.test.ts、test/chat-projects.test.mjs、test/enterprise-chat-view.test.ts | 新协议、主进程、自动迁移/重试、账号代际；包含在 149 passed 中 |
| Desktop | test/desktop-modes-ui.test.mjs、test/desktop-account-presentation.test.mjs | 服务端归属事件、原侧栏与 modal/native 让出行为；包含在 149 passed 中 |

没有用字符串匹配替代上述主要行为验证。源码契约/fixture 更新仅作补充。旧“确认后导入”断言因用户修订变为“自动开始、原记录保留、失败自动重试、来源不跨账号接管”。



## 用户反馈后的复核与修复（2026-11-06）

上一轮实际联合验收只证明了项目名称新建/改名同步，没有完成“项目内真实发送首条消息→另一端显示同一会话”的验收，不能据此称完整链路通过。

- 图一实际页面为 localhost:4001/workspace/c/12f78e3cf81749a1806ba17f841f34aa，本机开发代理指向 173:7860。只读 SQL 确认该会话及 membership 在 173 存在，在 119:3006 不存在；Desktop 当前嵌入页为 119:3006，因此是两个数据库，不是通知漏发。两套原始数据未修改。统一服务地址已询问用户，等待确认。
- 图二 113123 对应 119 的旧会话 0e249daa1f444278b0991e1c7d015bc1，创建时间为 2026-10-29 18:34:26，已有项目归属。页面进入项目新建路径后未清旧状态，历史失败任务被留在“新建”页面。
- Desktop main 的 navigate 对同 URL 提前返回；open(new) 现在始终派发新建操作。dsh:navigate.detail.resetDraft 为 true 时 Web 执行普通新建生命周期，为 false 的设置返回/普通导航保留原草稿。此前两项复现测试先失败，修复后主进程全组通过。
- Web 首条项目意图移到上传/租约等待前捕获；普通与任务统一保持不可变提交上下文。新草稿按逻辑身份隔离，后台旧流只能更新原会话，不能回写新草稿；相同逻辑草稿的二次重置与失败重试保持同一幂等身份。
- 新增 backend test/chat_session/test_project_workbench_creation.py，三个生产入口实际调用真实 Owner 与 SQLite 事务，在后续保存/入队前验证 session 和 membership 已提交；后端相关组 120 passed。
- Desktop 当前相关组 151 passed，typecheck/build 通过，真实 Electron 循环验证 4 组通过。该循环验证不等于真实 Web 首条发送验收。

本轮联调期间机器离开原内网：119/173 的 HTTP 均 Empty reply，119 SSH 连接关闭；未更改系统网络、代理、账号或开发代理配置。新修复尚未部署到真实服务，当前运行的旧 Desktop 进程未重启。需网络恢复和用户确认共同数据源后，才能发布并执行真实普通/任务发送和重连读回。Web 最终回归与候选构建结果见下。


### 本轮最终本地验证

- Web 11 suites / 102 tests passed（项目意图、SSE、同 URL 重建、设置保稿、旧请求迟到、附件隔离、侧栏回归）；Client strict 1839 files、17 文件定向 ESLint、production build 均通过。
- Web 变动的 8 个测试文件：components/Chat/AiChatInput.test.tsx、ChatView.handoff.test.tsx、useDesktopNavigation.test.ts；components/Nav/NewChat.project.test.tsx；hooks/useAiChat.test.ts、useAiChatSSE.project.test.ts；layouts/WorkbenchSidebar/projectChatCreation.test.ts；pages/knowledge/KnowledgeSquarePane.navigation.test.tsx（适配新建钩子所在依赖的路由 mock）。同一组还复验已有 SidebarProjects.newChat / SidebarConversationList / WorkbenchSidebar.mobile。
- 测试使用临时 Node preload 规避本机缺失的可选 canvas 原生包，未修改仓库依赖或 node_modules；Jest 使用 --forceExit 结束既有未关闭句柄。因此不把退出行为列为新功能验证结论。
- Desktop 5 suites / 151 tests、typecheck、build 和 Electron 循环 fixture 的 4 组流程通过；本轮变动的测试为 test/enterprise-chat-view.test.ts。
- Backend 120 tests passed（7 条现有依赖 warnings）；本轮新增 test/chat_session/test_project_workbench_creation.py 的 3 条实际入口原子提交回归。
- 两仓库 git diff --check 通过，未提交、推送、改分支或上传文档。
- 已在上次 119 部署源码缓存上仅覆盖本轮 9 个生产源码构建离线候选，467 个构建文件；不是将包含其他 WIP 的本地整树发布。候选 index SHA-256 为 485990d4be1063266c3e45371eed96f875114df86dcd840719de47b3da96cac7。候选仍在本机，未上传或切换服务。

日志：/tmp/bisheng-project-draft-lifecycle-tests.log、/tmp/bisheng-project-creation-fix-typecheck.log、/tmp/bisheng-project-creation-fix-lint.log、/tmp/bisheng-project-creation-fix-build.log、/tmp/bisheng-project-draft-scoped-build.log、/tmp/bisheng-project-newchat-desktop-related.log、/tmp/bisheng-project-backend-creation-combined.log。

实际环境验收仍待网络恢复，并确认共同使用 119 还是 173。恢复后应先复核当前服务版本，再部署相应前端、以原临时开发 Profile 重启 Desktop，完成两端各自项目内真实发送首条消息、后端归属读回、另一端自动出现、同项目重复新建以及设置往返保稿；本轮没有声称这些步骤已经通过。


### 用户确认 119 后的发布（2026-11-06 21:38）

用户已明确两端统一使用 119:3006。网络恢复后：

- 已将 gitignored 的 src/frontend/.env.development.local 的开发 API 目标由 173 改为 119:3006；本机 localhost:4001/workspace/api/v1/env 返回 200。另一套服务的数据未迁移、合并或删除。
- 先只读复核 current 与候选 previous_release 相同，9 个受影响源文件均与候选的服务端缓存基线一致，后端七核心文件与本地一致。
- 已发布 client build 和 9 个修复源码，current 为 releases/chat-project-draft-20261106-191520。发布 helper 验证其他容器 identity、平台根页面、compose/nginx 配置均保持不变；不涉及后端重启或库改写。
- 线上 index SHA-256 为 485990d4be1063266c3e45371eed96f875114df86dcd840719de47b3da96cac7；入口 assets/index.D6jPQAR5.js 实际 HTTP 200、application/javascript，哈希与候选 manifest 完全一致。
- 已用原 /tmp/bisheng-v130-dev.DF2cD5 Profile 运行 npm run dev，新进程记录对应 userData 下的 DSH_HOME 与中立 launch-root。原账号 web session 创建成功、enterprise-chat session_ready，实际 UI 挂载，四个项目与 119 只读快照一致。未发布正式安装包。
- 网页已从错误的 173 旧聊天路径进入 119 的 SyncReady1106 项目新建地址，projectId=25135d76-15f2-4de9-bf7c-e12eb12828a2。

- 另已只读核验 MinIO：后端 sharepoint 为 minio:9000，3006 桶反代的默认 Host 同为 minio:9000，因此本机 VITE_DEV_MINIO_TARGET=http://192.168.106.119:3006 保持正确；实际 Vite served JS 已确认两个开发目标均为 119:3006。

当前剩余限制：CUA 可读取 Chrome/Electron UI，但键盘输入无效、原生坐标操作报 noWindowsAvailable，扩展 DOM 通道也未能取得页面。因此尚未发出真实测试消息，也不能把已打开项目新建页当作发送成功。已请求用户解锁电脑并将 BISHENG Dev 切到当前桌面前台，待界面可操作后完成双向发送/归属读回/自动可见，以及重复新建/设置保稿验收。完整 Desktop 回归另行补记。

发布日志：/tmp/bisheng-project-draft-deploy-prepare.log、/tmp/bisheng-project-draft-deploy-activate.log。运行日志：/tmp/bisheng-project-draft-live-desktop.log（含本机运行时认证信息，不可上传）。


Desktop 全量补测：338 个文件中 332 passed、2 failed、4 skipped；3363 项中 3356 passed、2 failed、5 skipped。两个失败分别为 Office 真实子进程固定端口 127.0.0.1:43129 的 EADDRINUSE（继发 compile-cache 清理 ENOTEMPTY），以及 PPT personal templates 的一项 30 秒超时。项目同步相关 151 项均通过；未为掩盖失败改测试、禁用用例或增加超时。两个失败文件单独复跑的结果另记。完整日志 /tmp/bisheng-project-draft-desktop-full-tests.log。


补充本地复核：Office 单文件顺序复跑 11/11 passed（49.31s），全量端口冲突与临时目录清理失败未复现；没有改实现、fixture 或超时。日志 /tmp/bisheng-project-draft-office-rerun.log。PPT 单文件按原超时顺序复验中。

CUA 补充观察：通过实际 Desktop“在此项目新建对话 · SyncReady1106”按钮，嵌入页明确到达 /workspace/c/new?projectId=25135d76-15f2-4de9-bf7c-e12eb12828a2；旧输入元素被销毁、新输入元素创建，证明已部署 Web 配套新主进程的项目新建生命周期在该实例执行。仍无法通过键盘/文本通道写入测试消息，没有真实首条发送或新增会话，不将此观察等同于最终同步通过。


### 真实首条消息（用户协助输入，2026-11-06 22:09）

解锁并重建 CUA 控制连接后，工具仍出现原生输入/点击与快照不同步、elementHasNoFrame / noWindowsAvailable 及扩展 DOM 通道异常，不能由自动操作结果推断发送成功。因此请用户在实际 Desktop 项目中输入 desktop119sync，用户明确回复已发送。

随后读取真实 Desktop：会话 bd89ebddd6e840cdb612040b3700d0e3，正文显示 desktop119sync 及模型实际回复，位于 SyncReady1106 项目下。后台只读 SQL 独立核验：创建时间 2026-11-06 22:09:35，tenant1/user1，flow_type=15，membership 对应 projectId=25135d76-15f2-4de9-bf7c-e12eb12828a2，有效项目成员 0→1，revision 6→8。旧 18:22 / 18:21 普通会话保持不变。核验未读取其他消息正文或写库。此时仅证明客户端真实发送和原子归属，网页自动显示与反向发送仍待验证。

SQL 摘要 /tmp/bisheng-119-desktop119sync-membership.json。已请求用户在 119 网页确认此对话并项目内新建发送 web119sync；root 保持 Desktop 不刷新，等待反向自动出现。

PPT 单文件复验完成 20/20 passed（243.01s）；两个全量失败文件顺序复跑合计 31 项全通过，未改代码、fixture、超时或禁用测试。日志 /tmp/bisheng-project-draft-ppt-rerun.log。不得将此表述为单次全量全绿。


### 联调追加：项目行标题缓存覆盖

已只读确认 bd89ebddd6e840cdb612040b3700d0e3 的 MessageSession.name=Desktop Sync Issue，update_time=22:09:43，revision=8，但 Desktop 项目行仍 New Chat。代码原因是 ChatProjects 用 Map 合并时将 state.rows 的旧项目页无条件覆盖 host.items 的较新普通历史。候选改为比较服务端 updatedAt，时间相等保留项目页优先；不简单反转数组，以免旧普通历史盖住新项目页。

候选 /tmp/bisheng-project-title-candidate-ofapo1nv/project-title-freshness.patch，涉及 packages/dsh-desktop-client-ui/client.js 和 test/desktop-modes-ui.test.mjs。新增4场景在旧实现2失败/2通过，候选连同已有UI组60/60通过；覆盖双向新鲜度、迟到旧页和首40条之外成员。node --check / git apply --check 通过，正式文件尚未应用。日志 /tmp/bisheng-project-title-baseline-tests.log、/tmp/bisheng-project-title-candidate-tests.log。

保留正式文件的原因：当前承诺保持 Desktop 不刷新等待用户 Web 项目内反向发送。已核对当前 Harness client-hmr 每500ms监视实际client bundle，改正式client.js会触发HMR并干扰这次观察。应在反向观察有结论后立即应用候选、复验、构建并重新加载开发实例，不需再次请求开发权限。


### 最终本地落地与待办（2026-11-06 22:34）

22:28:26 只读元数据确认仍没有 Web 新会话或新的无归属会话。为完成独立代码工作，已向用户说明先落地标题补丁、开发窗口可能热更新，并重新建立反向观察状态；此前的无刷新观察不再用于声称反向通过。

- 标题候选已正式应用于 packages/dsh-desktop-client-ui/client.js、test/desktop-modes-ui.test.mjs。Desktop 本轮正式改动共4文件（另为 src/main/enterprise/chat-view.ts、test/enterprise-chat-view.test.ts），没有新增分支、worktree、提交或推送。
- 最终 Desktop 相关5套/155项通过，node --check、typecheck、build、git diff --check通过。日志 /tmp/bisheng-project-final-desktop-related.log、/tmp/bisheng-project-final-typecheck.log、/tmp/bisheng-project-final-build.log。
- 最终独立 Electron fixture 的4组通过（账号本地临时profile、认证loopback，23ms仅指fixture）；/tmp/bisheng-project-final-native/result.json，未替代真实双端首条消息验收。
- 已正常停止本次拥有的旧开发Electron进程，再用相同 /tmp/bisheng-v130-dev.DF2cD5 userData 启动，DSH_HOME和launch-root保持，web session / actual UI挂载通过。22:34起的新开发实例展开SyncReady1106后，已从服务器读到正确项目行 Desktop Sync Issue。当前没有发布正式安装包。
- Desktop真实首条项目消息和归属通过，用户手动输入后root读取UI/SQL验证。旧截图 /tmp/bisheng-project-sync-first-message-desktop.jpg 仅证明该实际消息，截图时标题缓存修复尚未加载，不用它声称项目行标题已正确。
- 实际 Web 的自动显示、Web反向项目内发送、Desktop不刷新自动出现，仍等用户上方请求的 web119sync 操作。CUA控制通道异常不能当作产品发送成功证据；不将这项未完成验收写成通过。

新实例日志 /tmp/bisheng-project-final-live-desktop.log 含本机运行时认证信息，不可上传。23ms fixture数据也不可写成真实119服务同步延迟。


### 目标环境双向普通对话验收完成（2026-11-06 22:44）

本节更新此前“网页反向待验收”的状态。用户明确确认：119:3006 网页已看到先前 Desktop 项目内的 desktop119sync，并已在同一个 SyncReady1106 项目内新建发送 web119sync。两次输入由用户手动协助，root 核对实际客户端 UI 与独立后端只读元数据，没有通过写库或构造会话伪造验收。

root 此轮只调用 getAXState / getAXStateAndScreenshot，没有刷新、重启或导航客户端：项目下已同时出现 Web Sync Discussion 和 Desktop Sync Issue；当前内容可读取 web119sync 及真实模型回复，UI 会话 ID=37a87ee329724c11b38ebdce888254e0。

22:44:06 单次只读 SQL 独立确认：新 Web 会话 name=Web Sync Discussion，create_time=2026-11-06 22:42:56，update_time=22:43:01，flow_type=15，tenant1/user1，唯一 projectId=25135d76-15f2-4de9-bf7c-e12eb12828a2。与客户端 ID 完全一致；目标项目有效成员从1增至2，revision从8增至10，原 Desktop 会话 bd89ebddd6e840cdb612040b3700d0e3 / Desktop Sync Issue 继续保留。未出现新的无归属误落。查询未读取正文、未改库或配置，没有轮询。

已完成的实际范围：共同使用119；Desktop项目内新建真实普通对话、唯一归属与模型回复；Web看到Desktop会话；Web项目内新建真实普通对话，未刷新的Desktop出现同一会话、项目、标题和内容。未精确测量生产同步时延，不把loopback的23ms用于生产结论。任务模式、异常恢复、多账号/租户、迁移等目标环境余项仍按 e2e-checklist.md 区分行为测试与实际环境，不扩称全部通过。正式安装包未发布；当前实际运行的是开发客户端。

证据：/tmp/bisheng-119-web119sync-confirmed-membership.json；/tmp/bisheng-project-sync-web-to-desktop-verified.jpg（同时显示两条项目会话，正文为Web首条消息与回复）。用户协助的正向确认与此次无刷新读取，共同完成本次项目内普通对话双向数据互通的真实验收。
