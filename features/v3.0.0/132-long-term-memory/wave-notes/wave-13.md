# Wave 13 记录：前端 Client（T081–T086）

本 Wave 的 6 个任务全部完成，每个任务单独提交。改动只在 `src/frontend/client/` 与本文件，没有后端改动。`tasks.md` 的勾选留给协调方合并时统一处理。

## 自己定的决定

- T081｜本 worktree 建在 `main`（af1894a538）上，不含 Wave 0–7｜开工前把本分支切到特性基线 `b6a036d4b4`（`git switch -C`，当时没有任何改动）｜任务说明写明基线含 Wave 0–7，`features/.../132-long-term-memory/` 与 `bisheng/memory/` 只在该提交里存在。
- T081｜时区上报挂在哪里｜在 `MainLayout`（所有登录页的外壳）调用 `useMemoryTimezone(user.id)`；localStorage 的键按用户 id 区分，读写都包 try/catch，上报失败不写键｜一处覆盖日常模式、应用聊天与深度研究；按用户分键，同一浏览器换账号时不会漏报；失败不写键，下次加载会重试。
- T081｜`memory` SSE 事件里的 `message_id` 指向哪一行尚无后端实现可查｜不用它改写当前回答的 id，只把标志并入当前回答｜日常模式的后端（T052）在另一个 Wave，避免把回答 id 改错。
- T081｜重新生成路径按临时 id 查找回答，`end` 事件换成真实 id 后就查不到｜查找条件加上"或等于 patch.messageId"｜`memory` 事件可能在 `end` 事件之后到达，否则标志会丢。
- T081｜历史标志何时取｜`getAgentMessages` 成功后再调 `/flags?chat_id` 合并；带 shareToken 的分享页不调｜标志只对本人返回，分享页请求它没有意义。
- T081｜记忆接口出错时怎样提示｜全部接口带 `skip403Redirect: true, showError: false`，业务错误以翻译后的 `api_errors.<code>` 文案 reject，由组件就地显示｜AC-89 与撤销失败都要求显示接口返回的原因，全局 toast 会重复。
- T082｜事件时间用什么控件｜`@bisheng/ui` 的 `Input type="date"`｜组件库里 DatePicker 没有落地。
- T082｜导航与提示图标｜`Outlined.Bulb`（记忆）、`Outlined.History`（归因）｜bisheng-icons 没有"记忆"语义的图标。
- T082｜共用的类型、来源文案放哪里｜新建 `components/Memory/memoryLabels.ts`，设置页与提示组件共用｜同一概念只有一套文案。
- T083｜操作提示的数据何时加载｜有写入标志时立即取 `/turn`（提示文案要按"记下/更正/忘掉"显示）；只有归因标志时点开再取｜历史里每条带归因的回答不必各发一次请求。
- T083｜深度研究没有流式标志｜`MemoryNotice` 增加 `probe` 模式：按 `message_id` 取 `/turn`，没有任何写入、检索、常驻条目就不渲染｜对应 design R8"前端按任务消息行 id 取"。
- T084｜怎样识别脱敏后的记忆工具事件｜工具名以 `memory_` 开头，或 `args`/`results`（含 JSON 字符串形式）带 `redacted: true`，命中就只显示"记忆操作"占位｜`memory_search` 名字里有 `search`，原来的分类会把它当联网搜索卡片，把脱敏结构当网页结果渲染出来。
- T085｜WebSocket 的 `memory` 消息挂到哪条消息上｜帧里有 `message_id` 时按 id 找；否则挂到本轮（最后一个用户提问之后）最后一条回答行；本轮还没有回答行时先暂存，收到 `end`/`end_cover`/`close` 帧时再挂｜助手后端（T056）下发的时机与是否带 id 尚未定，这样两种情况都能落到正确的回答上。
- T085｜应用聊天刷新后的标志从哪来｜不改 `index.tsx` 的历史加载；消息底部用 react-query 按 `chat_id` 取一次 `/flags`，同一会话的所有回答共用缓存｜只在登录态助手会话里发请求，改动面最小。
- T085｜哪些应用聊天显示｜`appMemoryEnabled`：只认 `flow_type === 5`（助手），且不是只读、不是免登录｜spec 规定工作流的最终输出不做归因；免登录与分享视图没有本人身份。
- T086｜TaskTurnPanel 要不要改｜`ResultPanel` 已经拿到本轮任务消息 id，`MemoryNotice` 挂在 `ResultPanel` 的点赞下方，可见条件与点赞相同（本人、非只读、非分享）；`TaskTurnPanel` 只补一段注释说明 id 的来源｜一轮 = 一个 svid = 一条任务消息行（R8），点赞与记忆提示用同一个 id。

## 需要用户确认

### U-13-01 单条删除不做二次确认

- **涉及**：T082、T083；AC-87、AC-89。
- **问题**：AC-89 只要求"清空全部"二次确认。记忆管理页的单条删除和归因里的就地删除，目前点一下就删除，没有确认。删除后只能在管理页重新新增。
- **可选做法**：
  - A. 不确认（现状）。后果：误点会直接删掉一条记忆。
  - B. 单条删除也弹确认。后果：归因里连续删多条时多一步操作。
- **建议**：A。AC-87 写的是"就地删除"，单条误删的代价小。
- **目前做法**：按 A。如改为 B，涉及 `pages/settings/sections/MemoryPane.tsx` 与 `components/Chat/MemoryNotice.tsx` 的删除按钮。

### U-13-02 `/continue` 隐藏页的追问轮显示

- **涉及**：T086；AC-21、AC-87；P-01。
- **问题**：`/linsight/new` 页（`ConversationRound`）上的多轮只有前端自造的 `roundId`，没有任务消息 id，这些轮不显示记忆提示。`ExecutionFlow` 页按任务消息 id 取；如果后端把同一 svid 下多个 `/continue` 轮的本轮记录都绑到同一条任务消息行，这里会把多轮的记录合在一起显示。
- **可选做法**：
  - A. 维持现状（P-01 选 C 的延续：隐藏路径不保证逐轮区分）。
  - B. 后端为 `/continue` 轮另给每轮标识（例如经 WS 记忆事件带 `turn_id`），前端按 `turn_id` 取。后果：要改深度研究的 WS 事件与 `useLinsightManager` 的轮次状态。
- **建议**：A。这条路径没有界面入口，与 P-01 的建议一致。
- **目前做法**：按 A。

## 实际偏差

- 基线：worktree 原本建在 `main` 上，开工前切到 `b6a036d4b4`（见第一条决定）。
- T081 除任务点名的三个文件外，还改了 `api/chatApi.ts`（`ChatMessage` 增加 `memory` 字段）、`hooks/useAiChat.ts`（合并流式标志与历史标志）、`layouts/MainLayout.tsx`（挂时区上报）。
- T082 新增 `pages/settings/sections/MemoryItemEditor.tsx`（新增/编辑弹窗）与 `components/Memory/memoryLabels.ts`。
- T084 在 `api/memory.ts` 增加 `isMemoryToolEvent`。
- T085 新增 `pages/appChat/appMemory.ts`，并改了任务未点名的 `pages/appChat/useChatHelpers.ts`（`message.attachMemory`）与 `pages/appChat/ChatMessages.tsx`（计算并传入 `memoryEnabled`）。T085 的提交里顺带修正了 T084 测试里一处 fixture 的类型（JSON 字符串形式的 `args`），不影响断言。
- T086 的改动落在 `ResultPanel.tsx`；`TaskTurnPanel.tsx` 只加注释。`ExecutionFlow`（`/linsight` 页）也用 `ResultPanel`，因此同样显示本轮提示；`ConversationRound` 不传 `messageId`，不显示（见 U-13-02）。
- 测试按 tasks.md 放在 `__tests__/` 目录，与 client 现有"同目录 `*.test.tsx`"的惯例不同；jest 的默认匹配能找到它们。
- 与本 Wave 无关、基线上已失败的 jest 用例（用基线文件替换后复跑确认过 `importFailureContract`、`ChatResourceMenu` 两个）：`importFailureContract.test.tsx`（4 条）、`Input/ChatResourceMenu.test.tsx`（2 条）；`settingsHistory`、`personalTokenEntry`、`filterVisibleKnowledgeSelections`、`desktopEmbedding`、`workflowAutoRerun`、`sharedConversationState`、`workflowMediaAttachment`、`guestAccessError`、`StandaloneChatPage.test.ts` 在 `@jest-environment node` 下因 `test/setupTests.js:59` 的 `Element is not defined` 整个套件起不来；`mapSessionVersionStatus.test.ts` 因 `sse.js` 是 ESM 起不来。

## 验收输出

`cd src/frontend/client && pnpm exec jest --ci api/__tests__/memory MemoryPane MemoryNotice memoryBubble memoryFooter memoryResult`：

```
Test Suites: 6 passed, 6 total
Tests:       38 passed, 38 total
Snapshots:   0 total
Time:        69.269 s
Ran all test suites matching /api\/__tests__\/memory|MemoryPane|MemoryNotice|memoryBubble|memoryFooter|memoryResult/i.
```

`cd src/frontend && pnpm lint`：退出码 0。

`cd src/frontend && pnpm check-i18n`：

```
[check-i18n] info: 84 frontend-only error code(s) (dead-key candidates / gateway codes)
[check-i18n] OK — no new i18n drift
```

`cd src/frontend && pnpm typecheck`：退出码 1，原因在本 Wave 之前就存在。本 worktree 的 `node_modules` 是指向主检出的软链，`@bisheng/ui` 因此解析到主检出的 `packages/ui`，其中的 `DatePicker` 依赖 `react-day-picker`，该包不在这份 `node_modules` 里。第一步 platform 的 `tsc-strict` 因此报 2 个错并中断整条命令。为了看 client，逐个包单独运行：

```
bishengchat（client）  基线：💥 Found 2 errors（均为 packages/ui/src/components/DatePicker）
bishengchat（client）  本 Wave 后：💥 Found 2 errors（同样两条 DatePicker，strict 文件 1761 → 1774）
@bisheng/file-viewers、@bisheng/chat：基线与现在都只有 DatePicker 的错误
@bisheng/api-client：退出码 0
```

本 Wave 新增的 TypeScript 错误为 0。本 Wave 没有改 Python 文件，不需要跑 ruff。
