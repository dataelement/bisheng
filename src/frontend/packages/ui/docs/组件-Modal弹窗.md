# 弹窗 Modal

> 设计系统 · v1 · 2026-08-20
> 适用：在页面正中打开的打断式浮层，响应式 Web 三档（手机 / 平板 / 桌面）。
> 通用规则见 [基础-多端适配原则.md](基础-多端适配原则.md)、[基础-圆角与阴影规范.mdx](基础-圆角与阴影规范.mdx)、[基础-色彩规范.mdx](基础-色彩规范.mdx)、[组件-Button按钮.md](组件-Button按钮.md)；二次确认是弹窗的专用子类，已独立成文，见 [组件-Confirm二次确认.md](组件-Confirm二次确认.md)。
> 用量台账、迁移记录、代码锚点走文末隐藏区。

弹窗盖在页面正中，要求用户先处理完（确认、填表、看提示）才能回到下面的内容。它和抽屉的区别只有一个：**抽屉留着页面的边，弹窗不留**。

## 1. 什么时候用弹窗

用弹窗：**这件事要用户当场做个决定或完成一小段任务，做完就回到原处**。改名、填一张短表、看一条必须知道的提示，都是。

不用弹窗，改用别的：

| 情况 | 用什么 | 为什么 |
|---|---|---|
| 信息在页面里就地展示得下 | 行内区域 | 每个弹窗都是一次强制打断 |
| 用户要一边看着页面内容、一边改 | 抽屉 Drawer | 弹窗居中夺焦，会把要参照的内容盖住 |
| 只有几行文字或两三个操作 | 气泡卡片 Popover | 弹窗的打断比内容还重 |
| 只是告诉用户「刚才那步成了」 | 轻提示 Toast | 成功反馈不值得要一次点击才能消失 |
| 内容有自己的地址、要能分享 | 独立页面 | 弹窗没有网址，也接不住浏览器的返回键 |

**一次只开一个弹窗。** 弹窗里不能再开弹窗——两层浮层叠着，用户数不清关几次才回得去。弹窗里可以开二次确认，那是一问一答，不算一层。

**破坏性、不可逆的操作要配二次确认**（删除、移交、清空），见 [组件-Confirm二次确认.md](组件-Confirm二次确认.md)。

## 2. 尺寸四档

| 档位 | 宽度 | 装什么 |
|---|---|---|
| small | **400px** | 单字段表单、短提示、确认类 |
| medium（默认） | **600px** | 分组表单、带列表的内容 |
| large | **960px** | 多列表单、数据表格、需要预览区的内容 |
| 全屏 | 铺满窗口 | 文件预览、宽表格；手机档的固定形态（§7） |

**按内容的横向复杂度选档，不按内容长短选档。** 内容长的解法是滚动，不是加宽——加宽只会让每行文字变长、更难读。

**large 档装分栏内容与表格，不装长段落正文。** 长正文放 medium：它的内容区一行正好排 40 个汉字，是无障碍标准（WCAG 1.4.8）给出的中文行长上限；large 一行 66 字，眼睛回扫时会频繁跳错行。

**弹窗最高不超过 `窗口高度 - 64px`**，超出的部分只在主体区滚动，头尾始终看得见。上下各留 32px，弹窗才不会看起来像顶到了屏幕边。

**全屏档按内容类型选，不按窗口宽度选**，它不参与 §3 的降档：手机档（< 576px）自动走全屏；桌面上只给「宽到 960px 还装不下的单件内容」——文件预览、要横向滚动才看得全的宽表格。**内容多不是用全屏的理由**，多的解法是滚动，只有内容宽才轮到它；而一个流程要分好几步走完的，那件事本身应该是一个独立页面。

**全屏档四角直角、不带遮罩**（遮罩底下已经什么都看不见了）。头尾结构与普通弹窗完全一致——头部高 56px、标题左、关闭「×」右，操作按钮在底部；铺满屏幕换的是内容区，不是用户已经记住的那套位置。**底部按钮等宽平铺占满一行**：这么宽的一行里，右下角两个按原宽挤在一起，跟左上角的标题隔了一整个屏幕。

## 3. 窗口变窄时逐级降档

弹窗宽度**不随大屏变宽**，只随小屏降档：

| 窗口宽度 | small | medium | large |
|---|---|---|---|
| ≥ 1280px | 400 | 600 | 960 |
| 1024–1280px | 400 | 600 | **600** |
| 768–1024px | 400 | **400** | **400** |
| 576–768px（平板） | 400 | 400 | 400 |
| < 576px（手机） | 见 §7 移动端适配 | | |

**全屏档不在这张表里**——它由内容类型决定，不随窗口宽度升降，见 §2。

另有一条兜底，任何情况都生效：**弹窗最宽不超过 `窗口宽度 - 32px`**。左右各留 16px，弹窗才不会看起来像一块贴死在屏幕上的面板。

大屏不加宽的原因：24 寸显示器上把 960px 的表单拉成 1400px，只会让每行更难读。

## 4. 结构与间距

圆角 16px、模态投影，取值见 [基础-圆角与阴影规范.mdx](基础-圆角与阴影规范.mdx)。从上到下三段：

| 区域 | 内边距 | 说明 |
|---|---|---|
| 头部 Header | 高 56px，左右 16px | 标题 16px / 字重 500，左对齐；关闭按钮 24px，靠右 |
| 主体 Body | 左右 16px，上下不留 | 上下的空隙由头部高度和底部内边距让出来；内容装不下时**只有这里滚动** |
| 底部 Footer | 16px | 按钮右对齐（全屏档与手机档改为等宽平铺占满一行）；没有操作按钮时整段不出现 |

**头部和底部始终固定，只有主体滚动。** 用户滚到哪里都能看见标题和「保存」，不用滚回去找。

**关闭「×」按有没有取消按钮决定**：表单类弹窗必须有，那是它唯一的出口；带取消按钮的确认类不给「×」——两个出口说的是同一件事，反而让人犹豫该点哪个。

底部按钮直接用 Button 组件，排列顺序、间距与最小宽度见 [组件-Button按钮.md](组件-Button按钮.md)：主按钮最右，危险场景主位放危险红实心。

## 5. 遮罩与层级

**遮罩用黑色 40% 不透明，不加模糊。** 遮罩的作用是把页面压暗、让注意力收到弹窗上；一旦模糊到认不出底下是什么，用户会以为自己跳到了新页面，然后去按返回键。

**同一时间只有一层遮罩。** 弹窗里再开二次确认，不叠第二层——叠两层等于把页面又压暗一次，用户会以为自己陷得更深了。

浮层的前后关系分四档，新增浮层一律从这四档里选，不自造数值：

| 层 | z-index |
|---|---|
| 弹窗 · 抽屉（含各自的遮罩） | **1000** |
| 气泡卡片 · 下拉菜单 | **1100** |
| 轻提示 Toast | **1200** |
| 文字提示 Tooltip | **1300** |

排在上面的层要能盖住下面的：弹窗里的下拉菜单得展得开，弹窗里点保存、轻提示得看得见，而任何一个图标按钮——包括弹窗里的——都还要能弹出文字提示。

## 6. 打开与关闭

出现 **200ms**（淡入，同时从 96% 放大到 100%），消失 **160ms**（只淡出，不缩小）。出场比入场快一点——用户关闭时已经做完决定了，等待是纯粹的浪费。

普通弹窗给三条关闭路径，**一条都不能少**：

1. 头部的关闭按钮
2. 点击遮罩
3. 按 Esc 键

**弹窗里有没保存的内容时，点遮罩和按 Esc 都要先弹二次确认。** 填了十分钟的表单，不能因为手滑点到遮罩就没了。

**提交进行中，三条路径全部禁用**，直到接口返回。接口还没回就关掉，用户不知道这一步到底成没成。

全屏弹窗没有遮罩可点，只保留关闭按钮和 Esc。

焦点：打开时焦点移入弹窗、Tab 在弹窗内循环，关闭后焦点回到打开它的那个按钮。

## 7. 移动端适配

**手机档（< 576px）弹窗一律走全屏档**，§2 的四档宽度和 §3 的降档表都不再生效。手机屏幕本来就窄，居中弹窗左右都快贴边了，留那点缝既装不下内容、也证明不了「你还在原来那页」——不如把整屏交给这件事。

全屏形态见 §2：铺满窗口、四角直角、不带遮罩，头尾结构不变（头部高 56px、标题左、关闭「×」右，操作按钮在底部等宽平铺）。

**底部另有操作条时，按钮等宽平铺占满一行，并避开手机底部安全区。**

其余通用规则（触屏不显示 hover、可点范围 ≥ 44×44px、控件文字不放大）见 [基础-多端适配原则.md](基础-多端适配原则.md)。

## 给实现窗口（技术细节，设计师可跳过）

**壳已落地为组件库组件 `@bisheng/ui` 的 `Modal`**（`packages/ui/src/components/Modal/Modal.tsx`，实时预览见 components/modal.mdx）：本文 §2–§7 的取值——四档宽度与降档表、遮罩、层级、结构与间距、200/160ms 动效、三条关闭路径与提交锁、手机档全屏——全部写死在壳里，业务页只传内容。下列条目是它的实现口径，同时记录尚未收口的部分。

- **降档断点用 1024 / 1280**，即 Tailwind 的 `lg:` / `xl:`。二者属桌面档（>768）内部的细分排版，不是新增档位断点，符合[基础-多端适配原则.md](基础-多端适配原则.md)「不自造断点」。档位断点仍只有 576 / 768 两个。
- 宽度实现：`width: min(<档位>, calc(100vw - 32px))`，降档表用 `lg:` / `xl:` 前缀覆盖，不写 JS 计算。高度：`max-height: calc(100vh - 64px)`，body 区 `overflow-y: auto` + `overscroll-behavior: contain`。
- 遮罩落地：`rgba(0, 0, 0, 0.4)`，**不加模糊**。毛玻璃已于 2026-08-04 随全站 `backdrop-blur` 清除下线（client 33 处 + platform 7 处），现存三套壳都不带模糊，**只剩颜色要迁**：A 套的 `bg-black/40` 数值即最终值，B / C 套的 `bg-gray-500/90` 改过来——二次确认那 16 处随 `ConfirmContext` 一处生效。
- 嵌套时不叠遮罩：二次确认开在弹窗之上时，把它的遮罩置为透明（弹窗那层已经在压暗页面）。
- z-index 四档已写成 token（`--z-modal: 1000` / `--z-popover: 1100` / `--z-toast: 1200` / `--z-tooltip: 1300`）：`design-token.cjs` 的 `Z_INDEX` 表为名称与取值的 SSOT，两个运行时载体（`packages/ui/src/styles/tokens.css` + `client/src/style.css`）与两份 Tailwind 配置同步落地，类名 `z-modal` / `z-popover` / `z-toast` / `z-tooltip`；组件库 Toaster 容器的临时值 `z-[9999]` 已归并到 1200。**client 现存的 `z-50` / `z-[100]` / `z-[110]` 随两套壳收敛时替换，尚未动。** 本表为层级唯一事实源，[01-设计规范.md](01-设计规范.md) §5 改为指针。
- 动效曲线：进出统一 `cubic-bezier(0.2, 0, 0, 1)`；200ms / 160ms。缩放只做入场，出场纯淡出（缩小会让人误以为「收回到某处」）。落地为 `modal-overlay-in/out` + `modal-content-in/out` 四条 keyframes（两份 Tailwind 配置同步）。两个坑：入场缩放写**独立的 `scale` 属性**而不是 `transform: scale()`，否则会和居中用的 `translate(-50%, -50%)` 打架（手机档又是 `inset: 0`，两档不能共用一条 transform）；卡片不能再包一层居中 div——`Dialog.Portal` 会给每个子节点各套一个 `Presence`，没有自己动画的那层 div 一关就整棵卸载，出场动画根本来不及播。
- 无障碍：`role="dialog"` + `aria-modal="true"` + `aria-labelledby` 指向标题；焦点陷阱在弹窗内，关闭后归还触发元素。全屏档同样带 `aria-modal`。
- 手机档全屏：`< 576px` 时容器 `inset: 0`、圆角归零、不渲染遮罩层；现有 AlertDialog 底座的「贴底 + 仅顶部圆角」写法在弹窗上作废（抽屉仍保留）。底部操作条的安全区用 `padding-bottom: calc(16px + env(safe-area-inset-bottom))`，需 `viewport-fit=cover`。
- **原语收敛**：组件库 `Modal` 落地后多出第三条路——业务页逐步迁到 `@bisheng/ui` 的 `Modal`（与 Button / Toast / StateView 同一收敛方式，client 侧保留旧路径的 re-export 壳）。原「改 A 套 `Dialog.tsx` 的壳、业务零改动」仍是成本最低的过渡手段，两者可并行：先改壳止血，再按页迁到组件库。A 套原语直拼 22 处是最大人群（见下方台账 §1.2）；B 套模板 `OGDialogTemplate` 随二次确认收官后退役（[组件-Confirm二次确认.md](组件-Confirm二次确认.md) §4.3 第 4 步）。**client 两套壳一处未动，迁移批次待排。**
- 新页上线：本文已在 `src/frontend/client/rspress.config.ts` 的 `themeConfig.sidebar` 注册；改配置需重启 dev 服务。

## 待决策清单

- [ ] 四档宽度 400 / 600 / 960 / 全屏需在真实页面比对验收（组件库壳已可点，先在 components/modal 预览页比对）
- [ ] client 两套壳的收敛批次：改 A 套壳止血 vs 直接按页迁到组件库 `Modal`，待核工作量后排期

<!-- site-hide -->
## 现状与用量台账（给实现窗口）

> 以下为迁移排批次、估工作量用的现状数据，不进展示层。数字带扫描口径与日期，过时以最新一次重盘为准。

### 1.1 两套并行的弹窗体系（乱的根源）

BISHENG client 有两套弹窗，都包着同一个 Radix `@radix-ui/react-dialog`，但样式不同：

- **A 套（标准弹窗原语）**：原语 `src/components/ui/Dialog.tsx`、模板 `DialogTemplate.tsx`；遮罩 `bg-black/40` 半透明、无模糊；层级 `z-[100]`。
- **B 套（「Original」原语，OG 前缀）**：原语 `src/components/ui/OriginalDialog.tsx`（导出 `OGDialogContent` 等）、模板 `OGDialogTemplate.tsx`（用得最多）；遮罩原为 `bg-black/80`，二次确认期对齐 C 套改为 `bg-gray-500/90`（当时同带毛玻璃，2026-08-04 已清除）；层级 `z-50`。

| 维度 | A 套（Dialog） | B 套（OriginalDialog / OG） |
|---|---|---|
| 遮罩颜色 | `bg-black/40`（浅） | `bg-gray-500/90`（已对齐 C 套；原 `bg-black/80`） |
| 毛玻璃模糊 | 无 | 无（两套 2026-08-04 随全站 `backdrop-blur` 清除） |
| 层级 z-index | `z-[100]` | `z-50` |
| 便捷模板 | DialogTemplate | OGDialogTemplate |

> v1 定稿后两套的目标值：遮罩 `rgba(0,0,0,0.4)` 无模糊、层级 1000、圆角 16、内边距 16（主体只留左右）、标题 `text-base font-medium`。

### 1.2 Modal 期用量重盘（2026-07-09 扫描，最新，§1.1 旧数字以此为准）

> 画廊 Modal 版块已按本节重做。

| 体系 | 实现 | 业务文件数 | 说明 |
|---|---|---|---|
| **A 套 · 原语直接拼** | `Dialog` + `DialogContent` 手拼 | **22（最大人群）** | 新页面为主：知识库 8、订阅 2、审批中心、通知、账号、InviteCode、ShareChat、UploadFileModal、DataTableKnowledge、SearchWebUrls、appChat 2、MarkLabel、MainLayout（全局弹窗） |
| A 套 · 模板 | `DialogTemplate` | 3 | EditPresetDialog、PresetItems、ContextButton（ContextButton 在 SidePanel 死树） |
| B 套 · 模板 | `OGDialogTemplate` | 16（原 25） | 确认迁移后剩余；其中 SidePanel 死树约 6 处 + DeleteBookmarkButton 死 UI |
| B 套 · 原语直接拼 | `OGDialog` + `OGDialogContent` 手拼 | 16 | 设置账号 4、SharedLinks、Prompts 4、Chat/Input/Files 4、ShareAgent、Agents/AdminSettings、ActionsAuth |
| 手拼 AlertDialog | `AlertDialogContent` + 自拼头尾 | 7 | ChannelMemberDialog、ChannelMemberManagementPanel、TaskModeInput、AddSourceDropdown、CrawlFeedback / CrawlPreview、CreateChannelDrawer |
| C 套 · useConfirm（参照） | ConfirmContext | 26（已收敛 ✅） | 二次确认基准，见 [组件-Confirm二次确认.md](组件-Confirm二次确认.md) |

**壳解剖当前真实值**（源码核对）：

- A 套：遮罩 `bg-black/40` 无模糊、`z-[100]`、`sm:rounded-lg`（8px 移动端直角）、`p-5`、border + `shadow-lg`、标题 `text-base font-semibold`、暗色底 `dark:bg-[#303134]` 写死。
- B 套（已对齐 C 套）：遮罩 `bg-gray-500/90` 无模糊、`z-50`、`rounded-2xl`（16px）、`p-5`、border `#ebebeb` + 淡投影、标题 `text-base font-medium`、`bg-background` 跟主题。
- AlertDialog 底座：遮罩同 B（`bg-gray-500/90` 无模糊）、`z-[110]`、`sm:rounded-lg`、`p-6`、无边框无阴影、无内置关闭钮、移动端从底部滑入贴底。
- 层级三档并存：`z-50` / `z-[100]` / `z-[110]`，v1 统一为 1000。

### 1.3 死代码线索

- `OriginalDialog` 已确认**不是**死代码（被 OGDialogTemplate 内部 import）。
- SidePanel 死树：`SidePanelGroup.tsx:117-132` 整段被注释、面板不渲染，牵连约 5 处弹窗（书签删除 + 删 Agent / Agent 工具 / 删 Assistant / Assistant 工具）为死 UI，随死代码清理处置，不迁。
- default 变体挂 `btn-brand-primary` 类的换肤 hack 与 Modal 无关，另见按钮文档。

### 1.4 v1 调研存档（2026-08-20）

七家弹窗定义的关键数值，供后续复核：

| 维度 | 业内区间 | BISHENG v1 取值与理由 |
|---|---|---|
| 宽度 | 15 家里 8 家用档位制、6 家单值；**4 档最常见，无一家超 5 档**。数值聚成五簇：min-width 地板 280–320、小档 380–464、中文体系默认 480–560、跨体系默认 600–640（9 次，最密集）、大档 900–980 | 四档 400 / 600 / 960 / 全屏。400 落在小档簇正中（Spectrum S、Atlassian small 同值），600 是共识最强的默认值；large 原定 800（只有 Atlassian 一家），2026-08-20 二轮调研后加宽到 960 对齐大档簇；全屏档设计师拍板加入（业内仅 TDesign、M3 有，M3 限手机端） |
| 高度与垂直位置 | **两套配套方案，沿地域线分**：国内四家（antd / Arco / Semi / Element Plus）不设 max-height + 外层页面式滚动 + 距顶固定；西方八家（M3 / Fluent / SLDS / Carbon / Spectrum / Primer / Polaris / shadcn）设 max-height + 主体区内滚 + 垂直居中。Semi 源码注释是唯一写明因果的：垂直居中 + 外层滚动时 `margin:auto` 会按 flexbox 规范塌成 0，弹窗顶部滚不到。上下留白单边：M3 / Fluent 24、Polaris 30、Primer 32、Atlassian 60 | 走西方那一套（居中 + 主体内滚 + 设 max-height），三者配套、内部自洽。上下留白原定 96px（单边 48，比所有人都宽松），2026-08-20 收到 64px（单边 32，与 Primer 同档）。不设 min-height（业内仅 M3 有 140px） |
| 最小高度 | 核了 19 家：**容器级常态 min-height 只有 Material 3 web 一家（140px）**，且硬编码在 `:host` 上不是 token、Compose 端无对应实现、两次提交与 spec 页都未解释这个数。其余为条件性或非容器级：Atlassian `100vh` 仅「滚动视口」模式、Fluent 内容区 32px、TDesign 头尾 56/64px 仅全屏档、M2 动作区 52px（M3 已删）。antd / Arco / Semi / Element Plus / Carbon / SLDS / Spectrum / Polaris / Primer / Radix / shadcn / Apple HIG 全部未定义。业内文档层面从未讨论过「弹窗太矮」，Carbon 对内容少的处方是收窄宽度而非补高度 | **不定 min-height。** 固定头尾已经撑出地板：头部 56 + 底部（16 + 按钮 32 + 16）= 120px，主体空着也有这么高；放一行正文即 142px，与 M3 的 140 基本重合——说明这个数本就是「固定头尾 + 一行字」自然长出来的，不必再写规则保证。若强行垫高，二次确认那类一行字的弹窗会内容贴顶、底下空一块 |
| 行长依据 | WCAG 1.4.8（AAA）明文「不超过 80 字符，**CJK 40 字**」，是中文行长唯一有条文的数值；1 汉字 = 1em 的换算关系有 CSS Values 4（`ic` 单位回退 1em）与 WCAG 官方表述背书。⚠️ 「NN/g 推荐 50–75 字符」查无此说；clreq / JLREQ 都不给中文行长数值 | medium 内容区 = 600 − 32 = 568px，14px 正文约 40 字，正好卡在上限，反过来给 600 作默认档背书；large 内容区 928px 约 66 字，故限定它只装分栏与表格（§2） |
| 遮罩 | 黑色系低不透明度：M3 32% / Fluent 40%（暗色 50%）/ antd 45% / SLDS 50% / Arco 深灰 60%。毛玻璃仅 antd 提供且默认关 | 黑 40% 无模糊。原候选 `bg-gray-500/90` 比七家都重一大截，设计师拍板淘汰 |
| 内边距 | 24 最主流（M3 / Fluent / antd 横向）；TDesign 32、SLDS 16 | 16，主体只留左右（定稿时为四边 20，设计师 2026-08-20 对着预览页收窄，落在 SLDS 一档）|
| 标题 | 中文体系一致 16px（antd / Arco / TDesign）；字重 antd 600 / TDesign 600 / Arco 500。西方体系更大（M3 24 / Fluent 20） | 16px / 字重 500，与抽屉、二次确认现状一致 |
| 关闭「×」 | antd / Arco / TDesign 默认有；M3 basic dialog 无、Fluent 规定「无取消按钮时才加」、Apple alert 无 | 按有无取消按钮决定 |
| footer 按钮 | 主按钮在右为压倒性共识（antd / Arco / TDesign / M3 / Apple / SLDS），仅 Fluent 在左；间距 8（antd / M3 / Fluent）、Arco 12 | 主按钮最右；间距沿用《Button 按钮》已定的 12px，本文不另立 |
| z-index | 基数 + 逐层加：antd 1000 / Arco 1001 / TDesign 2500 / SLDS 9000 | 1000 / 1100 / 1200 / 1300 四档 |
| 移动端 | 仅 M3 给显式断点（<600dp 转全屏）；Fluent 用 480px / 359px CSS 断点；Apple、SLDS 无公开数值 | 沿用本站 576 断点，转全屏档 |

来源：ant.design、arco.design、tdesign.tencent.com、m3.material.io、fluent2.microsoft.design、developer.apple.com/design/human-interface-guidelines、lightningdesignsystem.com（含各家开源实现的 token 源码）。

## 改动记录

| 日期 | 改了什么 | 影响文件 | 提交 |
|---|---|---|---|
| 2026-07-09 | **Modal 期开工**：全站弹窗重盘（5 体系 64 文件，见台账 §1.2；A 套原语直拼 22 处为最大人群）；画廊 Modal 版块整体重做。未改组件源码，等设计师定标准 | `_gallery/sections/ModalSection.tsx`（重写） | 待 committer 窗口提交 |
| 2026-07-10 | **反馈弹窗抽成共享组件 `ui/CommentDialog`**（标题 + textarea + 取消 / 提交；header/body/footer 各 `px-5`、移动端等宽、每次打开重置草稿、可选异步提交）。MessageFeedbackButtons 改为消费方；MenuUnavailablePage 手写申请权限弹窗迁入——手拼弹窗 -1，新增 ESC / 遮罩 / 焦点圈定 | `ui/CommentDialog.tsx`（新）、`ui/index.ts`、`Chat/MessageFeedbackButtons.tsx`、`pages/MenuUnavailablePage.tsx` | 待提交 |
| 2026-07-30 | **对照《元-文档撰写规范》重排**：汉字编号→阿拉伯；正文分层——可读规范留展示层，用量 / 迁移台账 / 代码锚点下沉隐藏区；同步《圆角与阴影规范》已定的弹窗 16px 圆角 + 模态投影，待决策清单删去「圆角用几 px」一项；引号统一「」、去手写分隔线；修正兄弟文档指向本文旧章节号的引用。**未替设计师拍板任何未定项。** | 本文件、01-设计规范.md、00-总纲.md | 待 committer 窗口提交 |
| 2026-07-30 | **二次确认拆分为独立规范** [组件-Confirm二次确认.md](组件-Confirm二次确认.md)：原二次确认规范正文与迁移台账整体迁出，本文仅留指针。 | 本文件、组件-Confirm二次确认.md（新）、00-总纲.md | 待 committer 窗口提交 |
| 2026-08-20 | 最小高度与全屏档时机：核 19 家后**不定 min-height**（业内仅 M3 web 一家有常态值 140px，存档见台账 §1.4）；§2 补两句写清全屏档按内容类型选、桌面上只给「宽到 960 还装不下的单件内容」，§3 降档表下标明**全屏档不在表内**。规则未增未减，只把原本隐含的说法写显 | 本文件 | 待提交 |
| 2026-08-20 | **宽高二轮调研后调整**（15 家专项，存档见台账 §1.4）：**large 800 → 960**（业内大档聚在 900–980，800 仅 Atlassian 一家），降档表首行同步；**上下留白 96 → 64px**（单边 32，原值比所有体系都宽松）；§2 补一条「large 只装分栏与表格，不装长段落正文」，依据 WCAG 1.4.8 的 40 CJK 字上限。矮视口特例与滚动分隔线两项设计师暂不补。组件库 `Modal` 的 large 宽度与 max-height 已同步 | 本文件、00-总纲.md、`packages/ui/src/components/Modal/Modal.tsx` | 待提交 |
| 2026-08-20 | 设计师批注回填：**手机档（< 576px）弹窗一律走全屏档**，原「从底部上滑、最高 90% 屏高、顶部露一条主内容」那套作废；§2 全屏档补「手机档固定形态」、给实现窗口改为 `inset: 0` + 不渲染遮罩，待决策清单删去已结清的「全屏档首个落地场景」一项 | 本文件、基础-多端适配原则.md、组件-Drawer抽屉.md、00-总纲.md | 待 committer 窗口提交 |
| 2026-08-20 | **升级为 v1 正式规范**：先调研 antd / Arco / TDesign / Material 3 / Fluent 2 / Apple HIG / SLDS 七家的弹窗定义（存档见台账 §1.4），设计师逐项拍板——尺寸四档 400/600/800/全屏（三档沿用抽屉阶梯、全屏档为设计师加入）、遮罩黑 40% 不加模糊（淘汰灰白毛玻璃）、结构与间距抄抽屉（header 56/body 20/footer 12·20）、标题 16px 字重 500、「×」按有无取消按钮决定、footer 排列与间距沿用《Button 按钮》、层级四档 1000/1100/1200/1300 在本文定稿。骨架改为与抽屉同构的 7 节 + 给实现窗口；原「尚未拍板的点」7 项全部结清，待决策清单收窄为 3 项验收类 | 本文件、01-设计规范.md、组件-Drawer抽屉.md、组件-Toast轻提示.md、基础-多端适配原则.md、00-总纲.md | 待 committer 窗口提交 |

| 2026-08-20 | **v1 规范落地为组件库组件**：`@bisheng/ui` 新增 `Modal`（四档尺寸 + 降档表、黑 40% 无模糊遮罩、结构与间距、三条关闭路径 + `beforeClose` 拦截 + `submitting` 锁、手机档全屏、焦点陷阱与 `aria-modal`），底层沿用 `@radix-ui/react-dialog`；层级四档写成 token（`Z_INDEX` 进 design-token.cjs，两个 CSS 载体 + 两份 Tailwind 配置同步），Toaster 的 `z-[9999]` 归并到 `z-toast`；动效四条 keyframes 落地；文档站 components/modal.mdx 重写为实时预览 + API。**client 两套旧壳未动**（迁移批次见待决策清单） | `packages/ui/src/components/Modal/*`（新）、`packages/ui/src/index.ts`、`packages/ui/design-token.cjs`、`packages/ui/src/styles/tokens.css`、`packages/ui/tailwind-preset.cjs`、`packages/ui/src/components/Toast/Toaster.tsx`、`packages/ui/docs/components/modal.mdx`、`packages/ui/docs/design-token.mdx`、`client/src/style.css`、`client/tailwind.config.cjs`、`packages/ui/package.json` + `pnpm-workspace.yaml`（radix dialog 进 catalog） | 待提交 |

| 2026-08-20 | 设计师对着预览页调整内边距：**三段左右 20 → 16px**、**底部上下 12 → 16px**（底部即四边 16）、**主体上下内边距去掉**（上下空隙交给头部高度和底部内边距）；头部仍靠 56px 定高。§4 表、手机档安全区公式、台账目标值与 §1.4 调研取值同步 | 本文件、`packages/ui/src/components/Modal/Modal.tsx`、`packages/ui/docs/components/modal.mdx` | 待提交 |
| 2026-08-20 | 遮罩现状回填：三套壳的毛玻璃 2026-08-04 已随全站 `backdrop-blur` 清除（client 33 + platform 7），文档里「灰底毛玻璃 / `+ blur`」的旧描述全部作废——**遮罩只剩颜色待迁**（B / C 套 `bg-gray-500/90` → 黑 40%）。二次确认预览页规格表同步 | 本文件、`packages/ui/docs/components/confirm.mdx` | 待提交 |
| 2026-08-20 | 设计师对着预览页调整全屏档：**关闭「×」回到右上角、主操作回到底部**，原「左侧关闭 + 右侧主操作」的头部作废——全屏档与普通弹窗共用同一套头尾位置；**底部按钮等宽平铺占满一行**（与手机档同一条规则，卡片档仍是右对齐原宽）。组件同步删掉为它开的 `headerAction` prop | 本文件、`packages/ui/src/components/Modal/Modal.tsx`、`packages/ui/docs/components/modal.mdx` | 待提交 |

## 代码锚点

- A 套原语：`src/frontend/client/src/components/ui/Dialog.tsx`
- A 套模板：`src/frontend/client/src/components/ui/DialogTemplate.tsx`
- B 套原语：`src/frontend/client/src/components/ui/OriginalDialog.tsx`
- B 套模板：`src/frontend/client/src/components/ui/OGDialogTemplate.tsx`
- 反馈共享壳：`src/frontend/client/src/components/ui/CommentDialog.tsx`
- 画廊 Modal 版块：`src/frontend/client/src/pages/_gallery/sections/ModalSection.tsx`
- 组件库实现（v1 壳）：`src/frontend/packages/ui/src/components/Modal/Modal.tsx`
- 层级 token：`src/frontend/packages/ui/design-token.cjs`（`Z_INDEX`）→ `packages/ui/src/styles/tokens.css` + `client/src/style.css`（`--z-*`）→ `packages/ui/tailwind-preset.cjs` + `client/tailwind.config.cjs`（`zIndex` / keyframes）
- 实时预览页：`src/frontend/packages/ui/docs/components/modal.mdx`
