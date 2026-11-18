# DSH 桌面嵌入适配维护说明

适用：Client `/workspace` 在 DSH Electron WebContentsView 中运行时的环境、主题与控件外观适配。这里记录实现入口和已核实的补充规则；Bisheng 通用组件规范仍以 [UI 设计系统](../../packages/ui/docs/index.md) 为准。

本说明是长期维护文档。临时预览、截图、测试日志留在本地，不作为后续适配的源码依据。

## 1. 入口与代码归属

| 要处理的事情 | 现有入口 | 使用方式 |
|---|---|---|
| 容器、设备、系统 | [clientEnvironment](../src/utils/clientEnvironment/index.ts)、[useClientEnvironment](../src/hooks/useClientEnvironment.ts) | 容器看 `channel`；布局看 `layout`；交互看 `input`；确有系统差异时才看 `os` |
| SPA 路由同步 | [ClientEnvironmentSync](../src/routes/ClientEnvironmentSync.tsx) | 路由变化时在绘制前重新采样环境，同步根节点标记与订阅者 |
| 导航与展示桥接 | [DesktopShellBridge](../src/layouts/DesktopShellBridge.tsx)、[presentation](../src/utils/clientEnvironment/presentation.ts) | 复用 `window.dshChatPresentation` 的包装，不另建桥接 |
| 会话进行中状态与重命名同步 | [desktopConversationBridge](../src/components/Chat/desktopConversationBridge.ts) | `useAiChat` 合并流式回答与任务模式运行中的会话，经 `reportRunning` 上报宿主侧栏；路由变化后补发。宿主改名后经 `onConversationRenamed` 通知，网页重新读取会话名。两个方法均可缺省 |
| 桌面主题 | [desktopTheme](../src/components/Chat/desktopTheme.ts)、[useDesktopAppearance](../src/components/Chat/useDesktopAppearance.ts) | 复用 `dshTheme`、`dsh:appearance`、根节点主题标记和 tab 内状态 |
| 桌面语言 | [desktopLocale](../src/locales/desktopLocale.ts)、[useDesktopLocale](../src/layouts/useDesktopLocale.ts) | 复用 `dshLocale`、`dsh:locale`；该路径要求实际桌面桥接，不改网页用户的持久语言偏好 |
| 全窗口弹窗与背景尺寸 | [desktopViewport](../src/layouts/desktopViewport.module.css)、[MainLayout](../src/layouts/MainLayout.tsx)、[useMediaQuery](../src/hooks/useMediaQuery.tsx) | 公共布局常驻加载宿主预留尺寸，不能放在聊天页的按需样式中；背景按内容区域排版，body Portal 仍使用整个原生窗口 |
| 桌面主按钮 | [desktop-buttons.css](../src/desktop-buttons.css) | 命中已有 `.btn-brand-primary`，不逐页复制控件 |
| 指定模块的桌面 Tab | [desktop-tabs.css](../src/desktop-tabs.css) | 在现有 `Tabs` 上加 `.dsh-home-tabs`；当前只接知识空间、工具与技能 |
| 桌面 Switch | [desktop-switches.css](../src/desktop-switches.css) | 通过共享 Switch 的 `data-slot` 接入，统一普通/小号的桌面外观，保留原状态与回调 |
| 聊天专用外观 | [chat-surface.css](../src/components/Chat/chat-surface.css)、[chat-controls.css](../src/components/Chat/chat-controls.css) | 在聊天范围内维护，不把聊天标记当成全站桌面判断 |
| 模块首页与内部页布局 | [ModuleHome](../src/components/ModuleHome/ModuleHome.tsx)、[布局说明](../../../../docs/module-home-layout.md) | 首页、知识空间内部页及频道浏览/阅读态复用桌面框架；局部规则分别位于 KnowledgeSpaceLayout / ChannelLayout CSS module。创建/编辑知识空间和频道共用 ModuleSettingsLayout CSS module。频道分栏容量和设置页双栏均使用扣除外侧留白后的内容容器 |

桌面控件 CSS 由 [style.css](../src/style.css) 导入。桌面外观留在 Client，继续复用 `@bisheng/ui` 的控件逻辑；不为 DSH 改动 Platform 或共享组件的默认外观。

环境边界：

- `embed=dsh` 是显式桌面入口。JS 使用统一环境入口，CSS 使用 `html[data-bisheng-surface='desktop']`，不要逐组件重新读 URL。桌面身份还可能来自宿主、旧桥接、session 或同一页面的内存状态。
- `embed=mobile-app` 只表示手机 App 提供聊天头部，仍是 `channel='web'`，不能因此启用桌面控件外观。
- [usePrefersMobileLayout](../src/hooks/usePrefersMobileLayout.tsx) 与 MainLayout 共用布局判断：仅网页在 `≤767px` 时使用 H5 布局；DSH 嵌入页始终使用桌面布局。真实内容宽度仍用于桌面布局内部的排版。`touch-mobile:` 实际是 `≤1023px` 的宽度规则，不是触摸或手机设备判断。
- 桌面模块首页沿用插件页的 56px 顶部留白、48px 底部留白和 960px 内容上限。侧边基础留白使用宿主传入的 `--dsh-chat-window-width`，按整窗宽度的 4% 计算并限制在 24–48px。首页与插件页都在右侧稳定预留 5px 滚动条空间。旧宿主缺少整窗宽度时使用内容区宽度。弹窗扩展原生视口时继续按同一个宿主宽度排版。
- macOS 收起侧栏时，宿主可将模块网页放在原生按钮下方。模块外框用 `--dsh-chat-viewport-top` 抵扣这部分顶部距离，页头仍距窗口顶部 56px。Windows 的插件页和嵌入页都从标题栏下方开始，因此不抵扣标题栏高度，页头从内容区顶部起再留 56px（默认缩放时为整窗 `40 + 56 = 96px`）。全屏没有标题栏时，直接从内容区顶部起算。
- [useFinePointer](../src/hooks/useFinePointer.tsx) 判断 `(hover: hover) and (pointer: fine)`，布局、容器与输入能力分开使用。
- sessionStorage 不可用时有同一页面内的内存回退；刷新后需 URL 或宿主重新提供身份，内存不能跨刷新保存。
- 网页已支持可选只读 `hostInfo`，见 [types.ts](../src/utils/clientEnvironment/types.ts)。旧宿主桌面 `os` 保留 `unknown`；仅在原生展示桥存在且 Chromium 报告 Windows 时，环境入口才为旧宿主设置 `data-bisheng-windows-desktop`，用于模块顶部留白。只有 `embed=dsh` 的普通浏览器不会设置此标记。

## 2. 查 DSH 样式时必须一起读取的来源

先核对 **Desktop 实际安装的包**，再对照上游源码。不要只看一个组件的局部 CSS，也不要默认另一个仓库的当前分支与安装包一致。

2026-11-05 核对的 `@deepseek-ai/dsh-client-ui-theme`、`dsh-client-ui-primitives`、`dsh-client-ui-schedule` 版本均为 `0.2.1-rc.2`。

| 来源 | 应读取的内容 |
|---|---|
| Desktop 仓库 `BishengWork` | `node_modules/@deepseek-ai/dsh-client-ui-primitives/lib/Button.module.css`、`lib/types/Button.d.ts`：通用按钮 |
| 同一 Desktop 仓库 | `node_modules/@deepseek-ai/dsh-client-ui-primitives/lib/Switch.module.css`、`lib/types/Switch.d.ts`：开关尺寸、状态颜色、禁用态与正圆曲线 |
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

`corner-shape` 不继承，设置在父容器上不能替代控件自身规则。当前按钮和 Tab 的桌面 CSS 按控件设置，保留 `@supports` 回退；不要把 DSH 全局 `*` 选择器复制到 Bisheng 全站。

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

### Switch 要保留胶囊轨道与正圆滑块

2026-11-06 对照 Desktop 安装的 `ui-primitives/Switch.module.css`（`0.2.1-rc.2`）和上游 `ui-plugin-manager/src/client/PluginManagerPage.tsx`：插件页直接使用通用 Switch，没有额外改尺寸。

| 项目 | DSH 定义与网页适配 |
|---|---|
| 几何 | 轨道 36×20px，滑块 16×16px，内边距 2px，移动距离 16px；普通和 small 都映射到这套桌面尺寸 |
| 圆角曲线 | 轨道 `999px`、滑块 `50%`，两者明确 `corner-shape: round`，不能套按钮/Tab 的超椭圆 |
| 开启轨道 / 滑块 | `--dsw-alias-brand-primary` / `--dsw-alias-label-primary-foreground`；当前 DSH 为明暗翻转的中性色，不跟 Bisheng 蓝绿品牌主题变色 |
| 关闭轨道 / 滑块 | `--dsw-alias-border-l3` / `--dsw-alias-switch-thumb`；深色回退为白色 16% 左右的轨道和 `rgb(173 178 184)` 滑块 |
| 交互和过渡 | 以 `aria-checked` 为颜色依据；滑块过渡 120ms ease；轨道不增加品牌色 hover 或过渡 |
| 禁用 / 保存中 | DSH 禁用透明度 0.5；继续复用 Bisheng loading 锁定与 spinner，保持原请求、回调和错误处理 |
| 键盘焦点 | 沿用 DSH 焦点变量，缺失时回退；保留键盘切换与现有透明触摸热区 |

共享组件只新增 `data-slot='switch'` / `data-slot='switch-thumb'` 作为稳定的适配锚点，不改默认样式。桌面 CSS 同时限定根节点环境和这些锚点，不误改其他自定义开关；不需要逐个页面添加类名。

DSH 原组件不支持框内文字；Bisheng 既有接口继续保留。适配用 `width: max-content` 和最小宽度 36px，允许有文字的控件加宽，也避免无文字开关在 Grid 容器里被自动拉长。对应的宿主 alias 缺失时仍有浅色/深色回退。

### WebContentsView 不会继承宿主页面的 CSS

宿主存在某个 token 或规则，不代表 `/workspace` 文档里也有。当前核对的 `moduleThemePaletteCss()` 主要映射 Bisheng 颜色三元组，如 `--text-1`、`--fill-1`；没有直接转发所有 `--dsw-*` 变量或全局曲线。

| 当前网页适配项 | 优先读取与回退 |
|---|---|
| 主按钮底色、文字、悬停色 | `--dsw-alias-button-primary-fill`、`--dsw-alias-label-primary-foreground`、`--dsw-alias-button-primary-hover`；缺少时按明暗主题回退 |
| 圆角与曲线 | `--dsw-radius-md` / `--dsw-radius-sm` / `--dsw-corner-shape`；缺少时回退到 12px / 8px / `superellipse(1.5)` |
| Tab 颜色 | DSH `interactive-bg-hover`、`label-tertiary`、`label-primary` alias；缺少时用适配色及 Bisheng 语义文字 token |
| 主题标记 | 根节点 `.dark` 或 `data-dsh-host-theme='dark'`；由已有桥接维护 |

不要把尚未转发的 alias 写成宿主已实现的协议。DSH 更新主题或开始转发变量后，重新核对回退值与优先级。

### 弹窗扩展原生视口时，背景继续使用内容区域

2026-11-06 对照 Desktop 的 `src/main/enterprise/chat-dialog-viewport.ts`、`chat-view.ts` 和 `src/preload/enterprise-modal.ts` 确认：模态 body Portal 出现后，WebContentsView 会由右侧内容区扩展到整个窗口，关闭最后一层及其出场动画后恢复。旧宿主在开关时异步注入/移除 `data-dsh-window-dialog` 与定位样式；这能固定最终布局，但弹窗仍会先在内容区显示一帧，再跳到全窗口中心。

同日的闪烁修复将宿主内容区域提前安装为 `data-dsh-chat-viewport='ready'`，常驻提供 `--dsh-chat-viewport-width` / `--dsh-chat-viewport-height`。`#root` 的位置由 CSS 随实际视口变化计算，原生层与 html/body 持续透明，页面底色由原内容区承载。弹窗开关不再更换定位样式或背景透明度。preload 在报告模态状态前同步设置 `data-dsh-modal-open`；视口尚未扩展完成时仅暂缓 body Portal 绘制，不更改焦点、滚动锁或动画定义。Portal 位于 `#root` 外，扩展完成后仍覆盖整个窗口。

网页必须消费这套已存在的尺寸协议：

- 公共布局的宽高保护位于 MainLayout 常驻加载的 desktopViewport CSS module，不依赖是否访问过聊天页。内部滚动壳使用父区域高度，不继续按临时扩大的 `100dvh` 撑高。
- 桌面 MainLayout 定义 `workbench` 内联尺寸查询容器。模块首页、知识空间内部页、频道和创建/编辑页的 768px 桌面样式按这个内容容器判断；频道设置的 900px 双栏仍按表单列判断。预览这些页面时需要包含实际 MainLayout。
- 公共侧边留白按宿主预留宽度的 4% 计算，旧宿主未提供变量时回退为原 `4vw`。紧凑首页、搜索区、表单缩进和底部按钮按同一内容区域保持原布局。
- `useMediaQuery` 对已准备内容区域的桌面单一 px 宽度查询使用预留内容宽度，在原生视口开始变化前便固定断点；同时兼容旧宿主的 `data-dsh-window-dialog`。缺少有效尺寸时回退浏览器；hover/pointer 等能力查询仍取浏览器结果。不把布局标记用于身份或权限判断。
- Radix 的滚动锁、焦点管理及遮罩保持原机制，不通过关闭 modal、删除滚动锁或全局改 body 补偿来隐藏位移。

浏览器复现使用实际 MainLayout、设置页、五种弹窗底座，以及上述 Desktop 的原始视口/模态检测脚本；在 iframe 中模拟 native 区域由 890×760px 扩大到 1130×800px。修复前页头横向移动约 49.41px、底部操作区下移 40px；修复后按窗口坐标核对背景页头、表单、字段和操作区，五种底座全部无位移。700px 内容区扩到 940px 时，单栏、字段缩进、等宽按钮和紧凑首页搜索也保持原位置。嵌套确认返回上层后仍保持扩展，最后一层关闭才恢复；滚动位置 647px 和草稿保持，遮罩下滚轮不推动背景。验证覆盖冷入口及聊天样式已加载两种情况，未重新打包或实机加载安装包。

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

2026-11-06 Switch 补充验证：

- 与 DSH Switch 原 CSS 在同一浏览器中对照：默认/小号、开启/关闭、禁用状态的轨道尺寸、滑块尺寸及位置、颜色、透明度和曲线一致；加载时额外保留 Bisheng spinner。
- 浏览器模拟验证 Space 键切换、2px 外侧焦点、保存中 disabled 与 spinner、明暗和蓝绿主题，以及非桌面范围恢复原尺寸。保存中不能再次拨动，完成后恢复操作。
- 工具与技能相关现有测试 7 项通过；workspace lint/typecheck、共享 UI typecheck、Client 构建、架构守卫和差异检查通过。

2026-11-06 弹窗背景稳定性补充验证：

- 使用实际 MainLayout、设置页及五种弹窗底座，配合本机宿主原始模态/视口脚本模拟窗口扩展，背景坐标、滚动与草稿保持；700px 紧凑内容区及嵌套确认验证见上文。
- 宽度 hook、环境身份、弹窗焦点/键盘、页面导航、首页和内部页相关 22 套件共 148 项测试通过；workspace lint/typecheck、差异检查及架构守卫通过。

同日闪烁修复补充：

- Desktop 在 macOS 的真实 Electron WebContentsView / IPC 中，使用本地语义 Portal 夹具订阅实际绘制帧，并对定位脚本的异步交付增加 50ms 延迟以覆盖繁忙渲染进程。900/1084px 两档窗口、0.8/1/1.25 缩放及明暗主题的 12 个组合通过。每个采样帧背景探针位置保持，弹窗探针只在全窗口视口出现；覆盖嵌套、遮罩点击及 Esc 关闭。夹具单独保证其测试窗口可见；产品隐藏窗口时暂停观察的策略不变。
- 浏览器使用实际 MainLayout、知识空间设置页及五种弹窗底座验证常驻区域协议。开关与嵌套确认期间页头、表单和底部位置保持，滚动锁和输入焦点正常；组件保留挂载，以覆盖正常退出动画。
- 以上原生验证使用本地测试页面与隔离 Profile，不代表已安装发布版已更新，也不替代 Windows 验收。宿主修复需要更新 Desktop 构建；网页 hook 同时保留旧宿主兼容。
- 此次补充的 Client 相关 3 套件共 27 项、Desktop 相关 3 套件共 80 项通过；workspace lint/typecheck、Desktop typecheck/build、差异检查及架构守卫通过。Desktop 全量首跑 3302 项通过、7 项失败；失败所在的 5 套件共 50 项在降低并发、为 Python 检查使用 3.11 后复跑全部通过。

同日用户在 Electron 开发窗口仍观察到底层页面短暂消失/变色，说明上述网页帧检查没有覆盖宿主最终合成时的空白。Desktop 进一步在 `src/main/enterprise/chat-dialog-backing.ts` 中保留原内容区截图：先让宿主底图完成 decode 和绘制，再改变原生视口；关闭时等新区域的首帧可用后释放。底图只在内存中、不可点击，不重挂载业务页面；导航、隐藏、切换账号和过期请求都会清理。待展开期间暂停 Portal 的动画时钟，避免准备底图消耗出场动画。未变化的原生可见性、几何和背景色不再重复设置。

新的原生夹具同时读取宿主渲染层的像素探针，验证原生子视图丢帧时底层仍是原页面；12 个窗口/缩放/主题组合通过。底图准备、关闭后重开、过期捕获、decode 取消、隐藏清理和失败超时相关 5 套件共 89 项通过。Mac 手动解锁后已退出旧开发实例，以原开发 Profile 重建并启动新实例；在真实知识空间页面完成权限弹窗打开、关闭及再打开，未出现底图捕获/交付失败日志。用户表示稍后进行肉眼复测，最终闪烁感受仍待反馈。

此次 Desktop typecheck/build、差异与架构检查通过；全量检查为 3346 项通过、6 项失败，失败集中在未改动的 Office/PPT 文件转换、重算和导入渲染用例（其中 4 项超时）。这些全量失败没有在本次弹窗任务中改动或标记为已解决。

以上是源码审查、自动化测试与浏览器模拟，**不代表 Windows/macOS Desktop、iOS/Android 真实客户端已验收**。后续仍需按改动范围做实机验证。

已有环境测试可从 `src/utils/clientEnvironment/*.test.ts`、`src/routes/ClientEnvironmentSync.test.tsx`、`src/components/Chat/useDesktopAppearance.test.ts`、`src/layouts/useDesktopLocale.test.tsx` 查找；本文不替代测试。
