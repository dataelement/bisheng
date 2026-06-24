# Verification: Workflow User Selected Knowledge

## Metadata
- Feature ID: `046-workflow-user-selected-knowledge`
- Status: `dialog-input-support-pass`
- Updated: `2026-06-24`

## Overall Status
- Automated verification: `PASS`
- Browser smoke verification: `PASS`
- Completion claim: T033-T038 对话框输入支持已完成；代码、单测、构建、diff 检查和 Platform 对话框输入浏览器冒烟均已记录证据。

## Commands

| Command | Purpose | Exit Code | Result | Evidence |
|---|---|---:|---|---|
| `python -m py_compile src/backend/bisheng/workflow/common/runtime_knowledge.py src/backend/bisheng/workflow/common/knowledge.py src/backend/bisheng/workflow/graph/graph_engine.py` | 后端运行态选择与检索 helper 语法检查 | 0 | PASS | 无编译错误。 |
| `cd src/backend && uv run pytest test/workflow/test_user_selected_knowledge.py test/workflow/test_knowledge_space_scope.py` | 后端 workflow 运行态选择、知识库/知识空间范围、旧节点回归 | 0 | PASS | `29 passed, 8 warnings in 3.83s`。 |
| `cd src/frontend/platform && npx vitest run src/test/workflowUserSelectedKnowledge.test.ts src/test/workflowUserSelectedKnowledgePicker.test.tsx` | Platform helper、对话框/表单输入显示合同与 TAB picker 回归 | 0 | PASS | `2` test files passed，`7` tests passed。 |
| `cd src/frontend/client && npx -y -p node@20 node ./node_modules/.bin/jest src/pages/appChat/userSelectedKnowledge.test.ts src/pages/appChat/UserSelectedKnowledgePicker.test.tsx --runInBand --silent --coverage=false` | Client helper、对话框/表单输入显示合同与 TAB picker 回归 | 0 | PASS | `2` test suites passed，`7` tests passed。使用 Node 20 是因为当前 `node_modules/canvas` 为 Node ABI 115。 |
| `cd src/frontend/platform && npm run build` | Platform TypeScript/Vite 构建验证 | 0 | PASS | Vite build 成功，`built in 13.52s`；保留既有 large chunk/eval/Browserslist 警告。 |
| `cd src/frontend/client && npm run build` | Client TypeScript/Vite/PWA 构建验证 | 0 | PASS | Vite/PWA build 成功，`built in 28.52s`；保留既有 PWA glob/Browserslist/eval 警告。 |
| `git diff --check` | diff whitespace 检查 | 0 | PASS | 无 whitespace error。 |
| `rg -n "[ \t]+$" <changed-and-new-files> || true` | 新增未跟踪文件 trailing whitespace 检查 | 0 | PASS | 无输出。 |
| `curl -I --max-time 5 http://127.0.0.1:3001/flow/990d6499fb934bbdb51c8f9a00c4be4a` | Platform dev server 可访问性检查 | 0 | PASS | HTTP `200 OK`。 |

## Browser Smoke Evidence

| Scope | Result | Evidence |
|---|---|---|
| Platform flow page | PASS | 内置浏览器进入 `http://127.0.0.1:3001/flow/990d6499fb934bbdb51c8f9a00c4be4a`，页面标题 `首钢股份知库工作台`，URL 保持目标 workflow。 |
| Dialog input picker visible | PASS | 点击顶部 `运行` 并等待输入 schema 返回后，`#bs-send-input` 为可输入状态，运行面板可见 `自选知识范围`、`整库限选 1 个，文件最多 20 个`、`已选范围：0 / 20`。 |
| Default knowledge tab | PASS | 对话框输入状态下 `[role="tab"]` 中 `文档知识库 aria-selected=true`、`知识空间 aria-selected=false`，默认展示知识库列表 `而为`、`许华亮`。 |
| Missing selection guard | PASS | 未选择知识范围时，在对话框输入框输入 `测试自选知识对话框输入` 并点击发送，页面出现 `请选择知识库或知识空间`，输入框保持可用且内容未被发送清空。 |

## Acceptance Coverage Summary

| Status | Count | Notes |
|---|---:|---|
| PASS | 6 | REQ-001 到 REQ-006 均有代码实现、单测/回归测试、构建或浏览器证据支撑。 |
| BLOCKED | 0 | 无阻塞项。 |
| FAIL | 0 | 未发现自动化验证失败项。 |

## Requirement Coverage

| Requirement | Status | Evidence |
|---|---|---|
| REQ-001 新增自选知识节点 | PASS | 新节点模板、节点注册、浏览器节点面板和后端 pytest 保持通过。 |
| REQ-002 运行态选择入口 | PASS | Platform/Client helper 测试覆盖 `dialog_input` 解锁和 `form_input` 待提交状态都展示自选知识组件；Platform 浏览器冒烟验证对话框输入可见和缺少选择阻止发送。 |
| REQ-003 选择知识库/知识空间/文件范围 | PASS | Platform/Client picker 组件测试继续覆盖 TAB、切换清空、当前 TAB 内树形勾选、知识空间类型分组和 20 文件限制。 |
| REQ-004 运行时 payload 契约 | PASS | Platform 对话框和表单链路均通过同一状态注入保留字段；Client 对话框输入、引导词输入和表单提交统一执行运行态知识选择校验，已选时继续随 payload 传递。 |
| REQ-005 新节点执行行为 | PASS | 后端 `RagUtils` 支持完整 source 与同类型多 source items；pytest 覆盖检索节点、问答节点、多个自选节点共享选择和旧节点回归。 |
| REQ-006 兼容性与权限 | PASS | 无新增 UI/HTTP/state 依赖；自选知识运行时权限兜底和旧节点回归测试通过；Platform/Client build 通过。 |

## Residual Risks

- Client 发布页未做真实浏览器冒烟：本轮未获得发布页访问 URL；已通过 Client Jest helper/组件测试和 Vite build 验证同一选择器显示合同与提交校验。
- 浏览器冒烟未提交真实 workflow 问题：为避免产生运行日志、LLM 调用或检索副作用，本轮只验证对话框输入 UI、缺少选择阻止发送和选择器可见性；运行时 payload 与后端执行由单测覆盖。
- 表单输入真实浏览器冒烟未执行：当前可访问 workflow 为对话框输入状态；表单输入显示合同由 Platform/Client helper 测试覆盖。
- Client Jest 在默认 Node 24 环境会受当前 `canvas.node` ABI 115 影响；本轮使用 Node 20 运行完整 Client Jest 套件并通过。

## Manual Checklist

1. 打开 `http://127.0.0.1:3001/flow/990d6499fb934bbdb51c8f9a00c4be4a`。
2. 点击 `运行`，等待对话框输入解锁。
3. 确认聊天输入框上方出现 `自选知识范围`，且输入框可输入。
4. 不选择知识范围直接发送，确认提示 `请选择知识库或知识空间`，并且消息未发送。
5. 切换输入节点为表单输入后运行，确认表单待提交时聊天输入区上方仍可操作自选知识组件。
6. 在发布页补充一次真实浏览器运行，确认 Client 页面与 Platform 展示和发送同一 payload shape。
