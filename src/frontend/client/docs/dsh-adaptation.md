# DSH 桌面嵌入适配维护说明

适用：Client `/workspace` 在 DSH Electron WebContentsView 中运行时的环境、主题与控件外观适配。这里记录实现入口和已核实的补充规则；Bisheng 通用组件规范仍以 [UI 设计系统](../../packages/ui/docs/index.md) 为准。

本说明是长期维护文档。临时预览、截图、测试日志留在本地，不作为后续适配的源码依据。

## 1. 入口与代码归属

| 要处理的事情 | 现有入口 | 使用方式 |
|---|---|---|
| 容器、设备、系统 | [clientEnvironment](../src/utils/clientEnvironment/index.ts)、[useClientEnvironment](../src/hooks/useClientEnvironment.ts) | 容器看 `channel`；布局看 `layout`；交互看 `input`；确有系统差异时才看 `os` |
| SPA 路由同步 | [ClientEnvironmentSync](../src/routes/ClientEnvironmentSync.tsx) | 路由变化时在绘制前重新采样环境，同步根节点标记与订阅者 |
| 导航与展示桥接 | [DesktopShellBridge](../src/layouts/DesktopShellBridge.tsx)、[presentation](../src/utils/clientEnvironment/presentation.ts) | 复用 `window.dshChatPresentation` 的包装，不另建桥接 |
| 桌面主题 | [desktopTheme](../src/components/Chat/desktopTheme.ts)、[useDesktopAppearance](../src/components/Chat/useDesktopAppearance.ts) | 复用 `dshTheme`、`dsh:appearance`、根节点主题标记和 tab 内状态 |
| 桌面语言 | [desktopLocale](../src/locales/desktopLocale.ts)、[useDesktopLocale](../src/layouts/useDesktopLocale.ts) | 复用 `dshLocale`、`dsh:locale`；该路径要求实际桌面桥接，不改网页用户的持久语言偏好 |
| 桌面主按钮 | [desktop-buttons.css](../src/desktop-buttons.css) | 命中已有 `.btn-brand-primary`，不逐页复制控件 |
| 指定模块的桌面 Tab | [desktop-tabs.css](../src/desktop-tabs.css) | 在现有 `Tabs` 上加 `.dsh-home-tabs`；当前只接知识空间、工具与技能 |
| 聊天专用外观 | [chat-surface.css](../src/components/Chat/chat-surface.css)、[chat-controls.css](../src/components/Chat/chat-controls.css) | 在聊天范围内维护，不把聊天标记当成全站桌面判断 |
| 模块首页与内部页布局 | [ModuleHome](../src/components/ModuleHome/ModuleHome.tsx)、[布局说明](../../../../docs/module-home-layout.md) | 首页、知识空间内部页和频道浏览态复用桌面框架；局部规则分别位于 KnowledgeSpaceLayout / ArticleListLayout CSS module，阅读分栏宽度还需核对 ChannelLayout |

两个桌面控件 CSS 由 [style.css](../src/style.css) 导入。桌面外观留在 Client，继续复用 `@bisheng/ui` 的控件逻辑；不为 DSH 改动 Platform 或共享组件的默认外观。

环境边界：

- `embed=dsh` 是显式桌面入口。JS 使用统一环境入口，CSS 使用 `html[data-bisheng-surface='desktop']`，不要逐组件重新读 URL。桌面身份还可能来自宿主、旧桥接、session 或同一页面的内存状态。
- `embed=mobile-app` 只表示手机 App 提供聊天头部，仍是 `channel='web'`，不能因此启用桌面控件外观。
- [usePrefersMobileLayout](../src/hooks/usePrefersMobileLayout.tsx) 当前仅判断 `≤767px`，桌面嵌入窄窗口也会返回 `true`。`touch-mobile:` 实际是 `≤1023px` 的宽度规则，不是触摸或手机设备判断。
- [useFinePointer](../src/hooks/useFinePointer.tsx) 判断 `(hover: hover) and (pointer: fine)`，布局、容器与输入能力分开使用。
- sessionStorage 不可用时有同一页面内的内存回退；刷新后需 URL 或宿主重新提供身份，内存不能跨刷新保存。
- 网页已支持可选只读 `hostInfo`，见 [types.ts](../src/utils/clientEnvironment/types.ts)。本次核对的 Desktop `src/preload/enterprise-chat.ts` 尚未暴露它；旧宿主桌面 `os` 保留 `unknown`，不能由 `embed=dsh` 推断 Windows/macOS。

## 2. 查 DSH 样式时必须一起读取的来源

先核对 **Desktop 实际安装的包**，再对照上游源码。不要只看一个组件的局部 CSS，也不要默认另一个仓库的当前分支与安装包一致。

2026-11-05 核对的 `@deepseek-ai/dsh-client-ui-theme`、`dsh-client-ui-primitives`、`dsh-client-ui-schedule` 版本均为 `0.2.1-rc.2`。

| 来源 | 应读取的内容 |
|---|---|
| Desktop 仓库 `BishengWork` | `node_modules/@deepseek-ai/dsh-client-ui-primitives/lib/Button.module.css`、`lib/types/Button.d.ts`：通用按钮 |
| 同一 Desktop 仓库 | `node_modules/@deepseek-ai/dsh-client-ui-theme/lib/client.js`：实际打包的变量、主题、曲线、焦点、滚动条样式 |
| 同一 Desktop 仓库 | `node_modules/@deepseek-ai/dsh-client-ui-schedule/lib/client.js`：任务页按钮与筛选标签 |
| DSH 上游 `deepseek-harness` | `packages/client/ui-theme/src/styles/{base,corner-shape,design-platform,focus,scrollbar}.css`：全局规则的可读源码 |
| 同一上游 | `packages/client/ui-schedule/src/client/TaskManagerPage.{tsx,module.css}`：页面局部定制 |
| Desktop 宿主注入 | `src/main/enterprise/chat-module-theme.ts`、`src/preload/enterprise-chat.ts`：网页实际收到的颜色和桥接能力 |

路径相对于各自仓库，不复制本机绝对路径或 `node_modules` 内容进 Bisheng。

## 3. 已确认需要额外适配的内容

### 圆角除了 radius，还有曲线

DSH 全局 `corner-shape.css` 在支持的引擎中设置：

```css
@supports (corner-shape: superellipse(1.5)) {
  :root { --dsw-corner-shape: superellipse(1.5); }
  *, *::before, *::after { corner-shape: var(--dsw-corner-shape); }
}
```

`border-radius` 决定圆角范围，`corner-shape` 决定曲线。默认 `round` 的计算值是 `superellipse(1)`；DSH 用 `superellipse(1.5)`，更偏方。即使高度和 radius 完全相同，形状也不同。**只复制局部组件的 radius 会漏掉这层全局样式。**

`corner-shape` 不继承，设置在父容器上不能替代控件自身规则。当前两个桌面 CSS 文件按控件设置，保留 `@supports` 回退；不要把 DSH 全局 `*` 选择器复制到 Bisheng 全站。

圆形图标按钮和数字徽标保持普通圆弧。DSH 对真正的正圆、胶囊也在所属组件中显式设置 `corner-shape: round`；不能单凭 radius 数值大，就把所有控件都改成普通圆弧。

### 通用 Button 与任务页“新建”规格不同

| DSH 来源 | 高度 | 圆角 | 字号/行高与水平内边距 |
|---|---|---|---|
| 通用 Button `md` | 36px | `--dsw-radius-md`，当前 12px | 14/22，14px |
| 通用 Button `sm` | 28px | `--dsw-radius-sm`，当前 8px | 12/18，10px |
| 任务页 `.newButton` | 32px | 16px | 页面定制：13/20，12px |
| 任务页 `.filterTab` | 28px | 14px | 14/22，10px；标签间距 12px |

当前 Bisheng 主按钮保留原尺寸阶梯 **24/32/40px** 和原排版，常规圆角映射为 12px、小号为 8px，并补齐 DSH 曲线。这是网页侧外观适配，没有直接加载 DSH React Button，也不是所有尺寸都与 DSH 相同。进一步统一高度时，应同时核对同排取消按钮、输入框和弹窗。

不要把任务页 `.newButton` 的 16px 圆角、13px 字号推广成通用 Button 规格。

### WebContentsView 不会继承宿主页面的 CSS

宿主存在某个 token 或规则，不代表 `/workspace` 文档里也有。当前核对的 `moduleThemePaletteCss()` 主要映射 Bisheng 颜色三元组，如 `--text-1`、`--fill-1`；没有直接转发所有 `--dsw-*` 变量或全局曲线。

| 当前网页适配项 | 优先读取与回退 |
|---|---|
| 主按钮底色、文字、悬停色 | `--dsw-alias-button-primary-fill`、`--dsw-alias-label-primary-foreground`、`--dsw-alias-button-primary-hover`；缺少时按明暗主题回退 |
| 圆角与曲线 | `--dsw-radius-md` / `--dsw-radius-sm` / `--dsw-corner-shape`；缺少时回退到 12px / 8px / `superellipse(1.5)` |
| Tab 颜色 | DSH `interactive-bg-hover`、`label-tertiary`、`label-primary` alias；缺少时用适配色及 Bisheng 语义文字 token |
| 主题标记 | 根节点 `.dark` 或 `data-dsh-host-theme='dark'`；由已有桥接维护 |

不要把尚未转发的 alias 写成宿主已实现的协议。DSH 更新主题或开始转发变量后，重新核对回退值与优先级。

### 状态、图标与组件结构

- `.btn-brand-primary` 覆盖共享主按钮和部分旧按钮；绿色主题与禁用态有 `!important`，必须检查实际计算样式，不能只看 CSS 顺序。
- 主按钮图标继承文字色，避免旧绿色主题白图标覆盖浅底深字。禁用主按钮保留底色并整体透明到 `0.4`，加载继续使用 Bisheng 内置逻辑。
- `.dsh-home-tabs` 中性选中底色替代下划线，保留图标、计数、Radix 键盘切换、焦点环与横向滚动；其他 Tab 不自动改变。
- Tab CSS 依赖共享组件 DOM：列表外包装的分隔线、`tablist` 直接装饰 span、徽标 `.tabular-nums`。Tabs/Badge 结构改变时需同步核对这些选择器。
- hover 仅用于能悬停的精细指针，触摸按下反馈单独处理，不直接照抄 DSH 页面的无条件 hover。
- Portal 弹窗可能位于页面容器之外。全站桌面主按钮规则挂在 `html[data-bisheng-surface]` 下，不能用页面局部类替代。

## 4. 新增一种 DSH 控件时怎么复用

1. 明确复用通用控件还是页面专用样式，核对 Desktop 实际安装包版本。
2. 同时读取局部 CSS、主题变量与全局规则，尤其是曲线、字号/行高、字体、焦点和状态。
3. 复用 Bisheng 已落地组件的交互。桌面外观集中到 Client 适配文件，通过统一环境标记限定范围；局部控件用明确的接入类名。
4. 标清宿主已提供与尚未提供的字段/token，保留旧宿主和变量缺失时的回退。只读宿主信息继续使用现有 `hostInfo`，不另建环境判断。
5. 在同一渲染环境对比 `getComputedStyle()` 与实际边界：高度、radius、`corner-shape`、内边距、字号/行高、颜色。仍有差异再核对缩放、设备像素比，不凭截图猜一个更小的 radius。
6. 按影响范围验证普通网页/手机 App、明暗和蓝绿主题、禁用/加载、圆形图标、Portal、键盘、窄内容区、SPA 与刷新；更新本文对应的已验证规则。

## 5. 验证依据与边界

2026-11-05 已完成：

- 对照上述 Desktop 安装包和上游源码，确认通用 Button、任务页定制与全局曲线规则。
- 浏览器预览固定相同高度和 radius，计算样式从 `superellipse(1)` 变成 `superellipse(1.5)`；正圆、普通网页保持 `superellipse(1)`。
- Tab 预览验证点击、键盘 End 切换与焦点、320px 内容区横滚；做过明暗、蓝绿主题组合和非桌面范围、其他 Tab 的模拟检查。
- 两个页面现有测试共 31 项通过；Tab 接线阶段 workspace lint/typecheck 通过；补齐曲线后 Client 构建、浏览器计算样式、差异检查通过。Jest 使用本机临时配置排除不可用的可选 canvas，没有改仓库测试配置。

以上是源码审查、自动化测试与浏览器模拟，**不代表 Windows/macOS Desktop、iOS/Android 真实客户端已验收**。后续仍需按改动范围做实机验证。

已有环境测试可从 `src/utils/clientEnvironment/*.test.ts`、`src/routes/ClientEnvironmentSync.test.tsx`、`src/components/Chat/useDesktopAppearance.test.ts`、`src/layouts/useDesktopLocale.test.tsx` 查找；本文不替代测试。
