# 知识空间跳转新聊天自动提交修复

日期：2026-10-28（北京时间）。

## 范围与基线

- 仓库：`dataelement/bisheng`，目标分支 `feat/bisheng-work-120-main`。
- 开始基线：`fd6c95ca1b7986c60ea72d16d896a3de0ed4e9c2`，已读取远端分支确认。
- 交付同步基线：`e468e2f2bcfe3c855e159193c0f96e18aec1453d`，含频道路由、知识分享和工作流修复。
- 修复分支：`codex/knowledge-ask-submit`，工作目录 `.worktrees/bisheng-knowledge-ask-submit`。
- 本次修改平台网页客户端。Desktop 安装包与 Harness 保持原版本。

## 复现与根因

- 在 macOS Chrome 的 13001 环境中，首次从知识空间提问获得回复；返回相同空间再次提问后，地址进入 `/workspace/c/new`，页面停在欢迎页，问题没有提交。
- 部署资源 `index.DgxAiZvf.js` / `main.BoOLjQaW.js` 仍使用早期交接实现：问题保存在 ref，发送依赖知识选择和发送回调变化，并在发送之前清空待发送问题。当前发布分支已有会话就绪与发送接受检查，测试环境仍需更新客户端。
- 当前源码中继续存在两个可复现条件：React 18 `createRoot` 与聊天 KeepAlive 的自动冻结组合，使缓存恢复后 `useLocation()` 留在旧聊天；准备阶段只更新 ref，选择相同且 setter 保持原状态时缺少推进提交的渲染。
- 真实 MainLayout + Router + AliveScope 集成测试明确复现：外部地址回到 `/c/new`，缓存中的 location 仍是 `/c/previous`。macOS 浏览器组件夹具复现相同行为。

## 修改

- 聊天页缓存保留组件和会话状态，并保持路由与流式状态的更新能力：对 `chat_tab` 关闭 `autoFreeze`，符合已安装 react-activation 对 React 18 createRoot 的兼容要求。
- 发送交接使用独立的准备完成状态，准备后推进到下一次渲染，读取已经应用的模型和知识空间后提交。
- 保持新会话就绪检查、发送接受后完成交接、重复激活去重和附件准备流程。
- 同步最新目标分支中的频道路由与系统通知本地化改动，复用目标分支文案和 ESLint 存量记录。

## 验证

- 原始交接实现：新增的 5 个准备/连续提问用例失败；使用独立准备状态后通过。
- 原始聊天缓存：真实 MainLayout 集成用例得到 `/c/previous`；聊天缓存保持更新后得到 `/c/new`。
- 初始 6 组 / 62 项回归通过；同步目标分支并加入频道导航回归后，7 组 / 71 项通过，覆盖真实发送 Hook、会话知识隔离、模型持久化、首轮与连续提问、配置延迟、重复激活、发送重试与文章附件。
- 客户端全量 ESLint、1487 个严格类型文件检查、生产构建、三语言一致性通过；差异与架构检查记录随交付保存。
- macOS Chrome 本地组件验证连续 3 次提交，均进入 `new`，模型 ID 和空间 ID 一致，每个问题提交一次。使用真实 KnowledgeAskBar、交接 Hook、知识选择 Hook 和 KeepAlive；后端发送由验证记录替代。
- 本地证据：`outputs/knowledge-ask-submit-20261028/`，包含原始失败日志、修复后回归、构建、静态检查与 macOS 浏览器截图。

## 发布验收

- 发布路径：合入目标分支并部署配套 client。
- 13001 更新后的真实模型回复与已安装 macOS 原生客户端完整验收待执行。浏览器组件验证单独记录。
