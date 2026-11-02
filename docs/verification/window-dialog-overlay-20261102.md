# 桌面弹窗整窗蒙层 — 2026-11-02

## 展示规则与实现

桌面内打开技能上传、预览或二次确认时，弹窗使用黑色 40% 蒙层。左侧会话栏及右侧内容统一变暗，弹窗本身保持清晰。取值沿用 `src/frontend/packages/ui/docs/组件-Modal弹窗.md` §5 的设计规范。

`dialogOverlayStyle` 为三类 Client 弹窗统一生成桌面蒙层样式，并保留调用方传入的层级等布局属性。浏览器入口继续使用组件及调用方自身的展示规则。

Desktop 的既有窗口级模态协议负责将 body portal 展示到整个原生窗口，页面根节点保持原内容区坐标。Client 负责蒙层颜色，最后一层弹窗关闭后由 Desktop 恢复内容区。知识空间使用的 `@bisheng/ui` Modal 已采用相同的 40% 蒙层。

## 基线

- Client：`dataelement/bisheng:feat/bisheng-work-120-main@3120e714fa4ed492884cade11a128341d03eb105`。
- 提交 PR 前同步目标 `780723543c408013d0011a2d8053fdc6bb712420`，保留同期应用附件下载和已删除会话读取修复及双方状态记录。
- 原生组合验证：`dataelement/bisheng-desktop:V1.2.0@09c22fe34e5c89193c15387685810fbaa45e73fc`，Harness `0.2.1-rc.2`，Electron `43.0.0`，macOS arm64。
- Frontend 依赖使用相同锁文件及包清单的独立副本；命令使用仓库指定的 pnpm `9.15.9`。

## 验证结果

- `DialogPresentation.test.tsx` 更新展示契约，并覆盖布局样式保留、输入对象稳定、浏览器展示、主题、路由切换、焦点约束及 Esc。新契约在原逻辑上出现 4 项失败；修复后与 `KnowledgeSpaceDialog.test.tsx` 合计 14 项通过。
- `Skills/__tests__/skillPreview.test.ts` 使用其 Node 测试配置执行，17 项通过，覆盖技能文件解析和个人技能持久化。
- 同步目标后，将弹窗、知识空间及历史附件下载组合复测，3 组 / 31 项通过；连同技能文件的 Node 检查，本轮相关回归共 48 项通过。
- Workspace 全量 ESLint、Platform 的 620 个严格类型文件、Client 的 1,511 个严格类型文件、file-viewers 类型检查通过；Client 生产构建、`check-i18n` 和 `git diff --check` 通过。
- 原生联合验证 36 组通过：Dialog / OriginalDialog / AlertDialog × 900 / 1084 窗口宽度 × 0.8 / 1 / 1.25 缩放 × 深 / 浅主题。执行实际 Client 组件、当前构建的生产 CSS、Desktop 原生视图及 production preload/IPC，企业账号服务采用隔离夹具。
- 每组验证原生视图和蒙层覆盖整个窗口、页面根节点坐标保持、蒙层计算值为 `rgba(0, 0, 0, 0.4)`、弹窗不透明。子视图截图在侧栏坐标的像素为黑色且 alpha=102/255，证明该区域携带相同蒙层。截图记录的是原生子视图表面；侧栏内容由下层宿主 renderer 绘制。
- 原生检查验证嵌套确认期间的窗口覆盖、侧栏坐标命中蒙层、取消及关闭后的内容区恢复；通过渲染器中的实际取消按钮触发 React/Radix 关闭处理。Tab、Esc、焦点约束及焦点返回由组件用例覆盖，系统级键鼠交互列入安装版验收。

## 复现命令

在 `src/frontend/` 运行 `pnpm lint`、`pnpm typecheck`、`pnpm build:client` 和 `pnpm check-i18n`。

在 `src/frontend/client/` 运行：

```sh
NODE_PATH=../node_modules/.pnpm/node_modules node node_modules/jest/bin/jest.js src/components/ui/DialogPresentation.test.tsx src/components/Chat/Input/KnowledgeSpaceDialog.test.tsx --runInBand --coverage=false
NODE_PATH=../node_modules/.pnpm/node_modules node node_modules/jest/bin/jest.js --config jest.skill-center.config.mjs src/components/Skills/__tests__/skillPreview.test.ts --runInBand
```

`NODE_PATH` 仅供该测试命令解析 Babel runtime；应用运行方式沿用原有契约。技能文件测试使用仓库提供的 Node 配置。

原生组合验证需准备已安装依赖的 Desktop V1.2.0 目录，并先构建 Client。在仓库根目录运行：

```sh
DESKTOP_SOURCE=/path/to/bisheng-desktop node scripts/verify-desktop-dialog-overlay.mjs /path/to/evidence
```

脚本使用临时 Profile，输出原生检查 JSON 与深浅主题子视图截图。

## 验收范围

本轮交付包括代码、自动化验证和 macOS 原生组合验证。Client 网页发布、真实账号技能上传、Windows 安装包及系统 DPI 交互验收待执行。安装包需包含既有 Desktop 窗口级模态协议，网页需包含本次 Client 展示修复。
