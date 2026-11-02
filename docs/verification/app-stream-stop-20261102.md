# 应用流式回答手动停止标识 — 2026-11-02

## 基线与问题

- 仓库 `dataelement/bisheng`，目标 `feat/bisheng-work-120-main@9a985f4214be93eb74e5d4f04c0dca681ffd16ac`。
- 工作目录 `.worktrees/bisheng-app-stream-stop-status`，分支 `codex/app-stream-stop-status`。
- 应用页仅用 `end` 表示消息结束，手动停止后的截断回答与正常完成共用展示。助手后端已用 `remark=break_answer` 存储中断回答，前台历史渲染尚未消费该语义。
- 工作模式对照：本地安装的 Harness `@deepseek-ai/dsh-client-ui-chat@0.2.1-rc.2` 在 interrupted 回答下方显示“已停止”。本次修改属于 BISHENG 网页应用对话，Desktop 宿主及 Harness 依赖沿用各自基线。

## 修复行为

- 用户手动停止时，将本轮仍在输出的消息标为 stopped；已有正文、思考内容和已完成消息继续保留。进行中的工具卡片使用既有 interrupted 状态。
- 停止后到达的内容事件由停止状态处理；结束事件可补齐对应回答的持久化消息 ID。新的用户输入开启正常消息处理。
- 回答下方显示“已停止”，纯思考回答同样可见；中断思考使用停止状态。正常完成保留原有展示。
- 助手历史回答通过既有 `break_answer` 恢复停止标识。工作流即时回答显示停止状态，历史数据继续由现有工作流持久化链路提供；本次交付覆盖前台状态处理及助手既有中断历史标记。
- 工作流手动停止保留手动重跑入口，正常结束显示原有本轮完成分隔；中文、英文、日文同步。

## 验证

- 原版对照选取 7 项新增状态/渲染用例：2 组中 5 项失败、2 项通过；修复实现全部通过。
- 应用对话目录 8 组 / 48 项通过，覆盖首个 token 到达前停止、流式停止与正常结束、延迟内容/结束事件、消息 ID、工具中断、前轮隔离、后续提问、思考、助手历史恢复、工作流离线、重跑与附件。
- Client 全量 ESLint 通过；ESLint suppression 经工具收缩一项既有未使用变量记录。
- Client 1511 个严格文件、Platform 620 个严格文件及 file-viewers 类型检查通过；Client、Platform、UI、file-viewers 全量 ESLint 通过；Client Vite 生产构建、语言资源、受影响文件架构检查和差异检查通过。
- 验证使用已有依赖树；新工作目录单独连接工作区包及已安装的 react-query 4.44.0。锁文件保持一致。测试工具使用安装树的 `.pnpm/node_modules` 解析 Babel runtime。
- 测试采用 React/Recoil/WebSocket 与 API 夹具。测试环境网页部署、真实账号端到端、Windows 安装版实机验收待执行。
