# Desktop 弹窗模态识别：2026-11-03

## 现场证据与根因

用户截图为工具与技能页面的上传技能弹窗：右侧网页存在灰色遮罩，原生左侧栏保持明亮，弹窗居中基准落在右侧。

本轮核对运行实例为正式 `1.2.0-test9`，页面来自已部署 `e5941f38` 的 13001。读取正式安装包内 `out/preload/enterprise-chat.cjs`，确认监听依据为弹窗 `aria-modal=true`、原生 `:modal` 或根节点 `inert` / `aria-hidden=true`。

实际页面 DOM 中存在两个 `aria-live=polite` 通知区域。Radix 的 `hideOthers` 保留这些区域的可访问性，因而隐藏 `#root` 内的业务内容，保持 `#root` 本身可访问。弹窗 DOM 的 `aria-modal` 同时为空，导致 Desktop 判定模态关闭，原生网页视图维持右侧边界。

先前原生验证页面省略了通知区域，Radix 能直接隐藏根节点，旧监听在该简化结构下通过。本轮补齐真实结构后，旧代码稳定出现 5 项组件回归失败，原生验证首项超时于整窗展开。

## 实现

- `Dialog` / `OriginalDialog` 的 Root 将实际 `modal` 配置通过各自 Context 传递到 Content，并输出对应 `aria-modal`。Portal 保留 Context，`modal=false` 输出 false。
- `AlertDialogContent` 声明其固定的模态语义。
- 原生验证页面加入通知区域和业务子树，断言根节点保持可访问；可通过 `DESKTOP_PRELOAD` 指定已发布包内的监听代码，并在超时时保存上下文。

Client 基线：`feat/bisheng-work-120-main@e5941f38e40a32590d2c7a9b618cd6f370de12e2`。
Desktop 本轮作为验证宿主：已有 `703ad964` 源码，Harness `0.2.1-rc.2` / Electron `43.0.0`；监听代码直接提取自实际 test9 安装包。实现修改范围为 Client。

## 验证

| 检查 | 结果 |
| --- | --- |
| 旧代码 + 新组件回归 | 5 失败、9 通过，覆盖三种弹窗及两种可配置 Root |
| 修复后 DialogPresentation / KnowledgeSpaceDialog | 2 文件、20 项通过 |
| 全量前端 lint / typecheck | 通过 |
| Client 生产构建 / i18n | 通过 |
| macOS 原生矩阵 + test9 原版 preload | 36 组通过 |

原生矩阵为 900/1084 宽度 × 0.8/1/1.25 缩放 × 亮/暗主题 × Dialog/OriginalDialog/AlertDialog。检查视图整窗展开、业务内容原区域保持、遮罩尺寸、侧栏覆盖像素 `[0,0,0,102]`、点击命中、嵌套确认及关闭恢复。焦点、键盘与 Escape 由组件测试覆盖。

首次修复后原生运行通过 18 组后等待超时；该次日志保留，具体等待原因尚未确认。补充阶段诊断后，完整重跑 36 组通过。最终结果以完整重跑的 JSON 为准。

本地证据目录为外层工作区 `outputs/window-overlay-release-audit-20261103/`，包括 baseline、组件与质量检查日志、`fixed-native-recheck/native-results.json` 及视图截图。视图截图是隔离验证服务的单层捕获，侧栏透明区域需结合像素与原生边界断言解读。

## 交付与验收边界

本地实现和上述自动化验证已完成。新修复合入、Client 发布至 13001、macOS/Windows 安装版真实账号原场景复测待执行。当前 13001 的 e5941f38 版本仍具有上述识别缺陷。

部署后在现有 test9 打开工具与技能 → 上传技能，验收整窗蒙层、整窗居中、侧栏交互阻断、关闭恢复、嵌套确认及不同缩放。实际安装版与账号验收单独记录。
