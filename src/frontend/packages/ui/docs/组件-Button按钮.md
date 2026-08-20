# 按钮 Button

> 设计系统 · 按钮部分 v1 · 2026-07-14 建档，2026-07-30 对照《元-文档撰写规范》重写正文
> 与 [00-总纲.md](00-总纲.md)、[01-设计规范.md](01-设计规范.md) 配套；字号见 [基础-字体规范.mdx](基础-字体规范.mdx)、颜色见 [基础-色彩规范.mdx](基础-色彩规范.mdx)、圆角见 [基础-圆角与阴影规范.mdx](基础-圆角与阴影规范.mdx)、图标见 [基础-图标规范.mdx](基础-图标规范.mdx)、移动端通则见 [基础-多端适配原则.md](基础-多端适配原则.md)。
> 双轴模型灵感取自 antd 5 的 color × variant，尺寸阶梯对齐 antd / TDesign 的 24/32/40，触达底线取 WCAG / Apple HIG 的 44px；设计师输入「不迁就现有场景、危险色固定红」等需求后成文。迁移台账与实现细节见文末隐藏区。

## 1. 什么时候用

按钮用来触发一个**当下就会发生的动作**——提交、保存、删除、打开弹窗。读者带着「我要做这件事」来找它，所以先判断该不该用按钮，再挑类型和尺寸。

- **要发生动作，用按钮**：点下去立刻执行或打开一个流程。
- **只是跳转去别的页面**，用链接按钮（Link）或直接用链接文字，别用实心按钮——实心按钮会让人以为要「提交」什么。
- **一个操作区域只给一个主行动点**。一屏里最重要的那件事用一个主按钮承接，其余都往次级、文字级退，用户的视线才有落点。

## 2. 类型 Type

### 2.1 两个轴拼出所有按钮

按钮的长相由两个各管一半的属性拼出来，不逐个定义：

- **color 管颜色**：品牌色 `primary`、中性灰 `default`、危险红 `danger`。
- **variant 管画法**：实心 `solid`、描边 `outlined`、浅底 `filled`、文字 `text`、链接 `link`。

两个轴自由组合——红 × 实心 = 危险主按钮，红 × 描边 = 危险次按钮。3 种颜色 × 5 种画法共 15 种组合自动成立，不必一个个命名。挑按钮时先问「什么语气的颜色」，再问「多重的画法」，两步就定下来。

### 2.2 常用类型

日常最常用的是下面六种，先看「什么时候用」，拿不准时对号入座即可；其余组合按双轴自然推导。

| 类型 | 什么时候用 | 双轴组合 | 长相 |
|---|---|---|---|
| **Primary 主按钮** | 一个区域最重要的那一个动作（提交、确定、新建） | `primary` × `solid` | 品牌色实心 + 白字 |
| **Secondary 次强调** | 比主按钮弱、又想带点品牌感的动作（次级新建） | `primary` × `filled` | 品牌浅底 + 品牌色字，无边框 |
| **Default 默认按钮** | 最常见的次级动作（取消、返回） | `default` × `outlined` | 白底 + 灰描边 + 灰字 |
| **Text 文字按钮** | 最次级、成排的轻动作（表格行内、工具栏） | `default` × `text` | 无底无边，悬停才出浅灰底 |
| **Link 链接按钮** | 行为像链接的导航型动作 | `primary` × `link` | 品牌色文字，悬停不加底 |
| **Danger 危险按钮** | 删除、移交等有破坏性、不可逆的动作 | `danger` × `solid / outlined / text` | 红实心 / 红描边 / 红文字，一般配二次确认 |

### 2.3 形状 Shape

形状是第三个独立属性，只有两种：

- **`square`（默认）**：四角圆角随尺寸档走，文字按钮、图标按钮都用它。
- **`circle`（正圆）**：**只用于单 icon 按钮**，文字按钮不可用——正圆里塞文字会挤成一团、也读不出边界。

### 2.4 不做 dashed 和 ghost

**不设虚线（dashed）与深底透明（ghost）两种类型**。「无描边、无背景」的诉求已经由 Text 承接，再加类型只会让类型表更长、更难选。

| ✅ 推荐 | ❌ 不推荐 | 原因 |
|---|---|---|
| 一个操作区只放一个 primary solid 主按钮 | 并排放两个实心主按钮 | 两个都在抢注意力，用户不知道先点哪个；主次拉不开等于没有主次 |
| 「无描边无背景」的按钮用 Text | 为它单造一个 ghost 类型 | Text 已经覆盖这个诉求，多一个类型只增加选择成本 |
| 正圆按钮只放一个 icon | 正圆按钮里塞文字 | 文字在正圆里会被裁切、读不出边界，方形按钮才装得下文字 |

## 3. 尺寸 Size

三档尺寸，medium 是默认，绝大多数场景都用它。高度定死，靠它保证同排控件对齐；不要手写高度、内边距、圆角去凑尺寸。

| size | 高度 | 字号 / 行高 | 圆角 | 什么时候用 |
|---|---|---|---|---|
| `small` | 24px | 14 / 22 | 4px | 表格行内、紧凑工具条 |
| `medium`（**默认**） | 32px | 14 / 22 | 6px | 绝大多数场景 |
| `large` | 40px | 16 / 24 | 8px | 登录页、营销页、大表单提交 |

- **字号跟《字体规范》走**：small / medium 用正文档（14 / 22），large 用 16 / 24；字体规范调整时按钮跟随，见 [基础-字体规范.mdx](基础-字体规范.mdx)。
- **圆角跟《圆角与阴影规范》的控件档走**：4 / 6 / 8px 随尺寸档取，见 [基础-圆角与阴影规范.mdx](基础-圆角与阴影规范.mdx)。
- **垂直方向不留内边距**，高度定死、文字垂直居中。水平内边距按尺寸取 8 / 16 / 16px，带边框的描边按钮把边框算进这个视觉值，保证同尺寸按钮看起来一样宽。
- **同一视图内相邻的按钮必须同尺寸**。

| ✅ 推荐 | ❌ 不推荐 | 原因 |
|---|---|---|
| 「确定」和「取消」都用 medium | medium 的「确定」挨着 small 的「取消」 | 尺寸不齐会显得一高一低，像没对齐的补丁 |
| 直接选 `size` 档 | 手写 `height` / `padding` / 圆角凑一个尺寸 | 手写值会和三档慢慢漂移，同名按钮各处高矮不一 |

## 4. 内容形态

一个按钮**最多一个 icon**。图标尺寸随尺寸档取 14 / 16 / 18px（small / medium / large），与《图标规范》同一套，见 [基础-图标规范.mdx](基础-图标规范.mdx)。

### 4.1 纯文字

- **文字不换行、不省略**。文案跟《文案规范》走：用动词说清点下去会发生什么，一般 2–4 个字，见 [基础-文案规范.md](基础-文案规范.md)。文案长到要换行，说明这里该换个控件。
- **两个汉字的按钮不加中间空格**，「确定」就是「确定」，不写成「确 定」。
- 字重统一 400，所有尺寸、所有类型一致。
- 弹窗 footer 里的按钮留最小宽度 60px，太窄的「确定 / 取消」并排会显得局促。

### 4.2 单 icon 按钮

- 尺寸与三档同高（24 / 32 / 40），形状可选 `square` 或 `circle`。
- **必须配 Tooltip 说明含义，并设无障碍标签**。没有文字时图标是唯一线索，缺了说明，读屏用户和不认识这个图标的人都会卡住。
- 图标来源按总纲：bisheng-icons 优先，lucide 兜底。

### 4.3 文字 + icon

- icon **默认放在文字左侧**；只有「下一步 →」这类表达方向、前进语义的才放右侧。
- icon 与文字间距 8px，small 档可收紧到 4px。
- loading 时，转圈的 spinner 顶替 icon 的位置（本来没有 icon 就前置一个）。

| ✅ 推荐 | ❌ 不推荐 | 原因 |
|---|---|---|
| 「确认删除」 | 「是」 | 光看「是」不知道点了会怎样，用动词说清动作 |
| 一个按钮最多一个 icon | 文字两侧各放一个 icon | 两个 icon 抢视线、撑宽按钮，也说不清哪个是主图标 |
| 「下一步 →」的箭头放右侧 | 「保存」的图标放右侧 | 只有方向 / 前进语义才右置，其余一律左置，位置乱了读者得重新找 |
| 单 icon 按钮配 Tooltip + 无障碍标签 | 单 icon 按钮不加任何说明 | 图标是唯一线索，缺说明就没人看得懂这个按钮干嘛 |

## 5. 边距与排布

| 场景 | 规格 |
|---|---|
| 同组相邻按钮间距 | 8px（紧凑场景 / 工具栏）；弹窗 footer 用 12px |
| 弹窗 footer | 右对齐，**主按钮在最右**、取消在它左边；危险场景主位放 danger solid |
| 页面级操作区 | 主按钮在**左侧首位**（与弹窗相反），其余依次向右 |
| 与表单控件同排 | 按钮与输入框同高对齐（medium 32px 对齐输入框高度） |
| block 按钮 | 宽度占满整行，仅用于移动端 / 窄侧栏 / 登录页 |

弹窗和页面级操作区的主按钮位置**故意相反**：弹窗里视线从左读到右、在最右侧收束于确认动作；页面级操作区里主按钮领在最前，是这个页面的入口动作。间距通用规则见 [01-设计规范.md](01-设计规范.md)。

## 6. 状态 State

### 6.1 三态怎么变色

- **悬停变一档、按下再变一档**：品牌色按钮悬停亮一档、按下深一档；描边和文字类按钮悬停加一层当前颜色的淡底、按下再深一档。
- **颜色只在自己的色板里变**：品牌底走品牌色板、红底走红色板、灰 / 白底走灰色板。**禁止悬停 / 按下时跨色板变灰**——品牌浅底按钮一悬停就变灰，会让人以为按钮换了类型或失效了。
- **描边按钮悬停只加淡底，边和字不变色**：不做那种「边框和文字整体变色」的悬停，淡底更稳、不跳。
- 具体色值取《色彩规范》的品牌色与中性语义色，见 [基础-色彩规范.mdx](基础-色彩规范.mdx)；**危险色三态直接取功能色「危险」的常规 / 悬停 / 按下档**（常规档 `#f53f3f`，不随蓝⇄绿主题换肤）。

### 6.2 状态一览

| 状态 | Primary（solid） | Default（outlined） | Text | Danger（solid） |
|---|---|---|---|---|
| 常态 | 品牌色底 + 白字 | 白底 + 灰边 + 灰字 | 透明底 + 灰字 | 红底 + 白字 |
| 悬停 hover | 品牌色亮一档 | 加淡灰底，边、字不变 | 加浅灰底 | 红加深一档 |
| 按下 active | 品牌色深一档 | 底再深一档 | 底再深一档 | 红再深一档 |
| 不可用 disabled | 全类型统一，见下 | | | |
| 加载 loading | 全类型统一，见下 | | | |

- **按下深一档只在触屏上出现**。能悬停的设备（鼠标）按下时沿用悬停那一档——因为按下时指针必然还悬停着，再单独跳一档深色会让人看到一次「闪动」。触屏没有悬停，按下深档就是它唯一的按压反馈。
- **不可用（disabled）全类型一个样**：统一的浅灰底 + 灰字 + 灰边，鼠标移上去是「禁止」光标。
- **加载（loading）全类型一个样**：内置 spinner 顶替 icon 位，整体半透明、期间不可点。**禁止业务页自己往按钮里塞 Spinner**——各写各的会和规范不一致。
- **聚焦环只在键盘操作时出现**：用键盘 Tab 到按钮才出外环，鼠标点击不出；外环颜色随按钮颜色（品牌 / 红）。

| ✅ 推荐 | ❌ 不推荐 | 原因 |
|---|---|---|
| loading 用组件内置属性 | 业务页在按钮里手塞一个 Spinner | 手塞的 spinner 位置、大小、禁点逻辑各写各的，和规范对不齐 |
| 品牌浅底按钮悬停仍在品牌色板内变深 | 品牌浅底按钮悬停变成灰底 | 跨色板变灰会让人以为按钮换了类型或失效了 |

## 7. 移动端适配

跨组件的通用原则（双判定口径、依据）见 [基础-多端适配原则.md](基础-多端适配原则.md)，这里只写按钮自己的细则。

| 项 | 触屏 / 窄屏规则 |
|---|---|
| 悬停 hover | 触屏没有悬停，**全类型关掉悬停态**；按下反馈直接用 §6.2 的「按下」档，不新增颜色 |
| 触达 | medium（32px）和各档单 icon 按钮用透明热区扩到 ≥44×44px，**视觉尺寸不变**；small（24px）在触屏高频场景直接升到 medium，不硬撑热区 |
| 字号 | 不随移动端正文放大，保持 14 / 14 / 16——按钮是控件，不是正文 |
| 弹窗 footer | 窄屏按钮等宽平铺占满一行，桌面恢复右对齐 |
| block | 窄屏页面级主操作用 block 占满整行 |
| 加载 / 不可用 / 聚焦 | 与桌面一致，无额外规则 |

44px 是 WCAG 与 Apple HIG 无障碍标准的推荐触达底线，热区扩展就是为了达到它，同时不让视觉尺寸变大、破坏排版。

## 落地（给实现窗口）

1. `ui/Button.tsx` 用 cva 组织 `variants: { color, variant, size, shape }` + `compoundVariants`，保留 `className` 特例口子。基座字重 `font-normal`（400，全尺寸全类型）。
2. 颜色全走 token：品牌用 `--primary` / `--brand-*`（跟蓝⇄绿主题）；中性灰系、危险红系建语义变量（`--btn-*` 系，落 style.css + tailwind `btn-*`），组件内**不留裸 hex**。危险三态：base `#f53f3f`、hover `#d6373a`、active `#d02f33`。中性：文字 `#525865`、边框 `#e5e6e9`、hover 底 `#f8f8f8`。disabled 三 token：浅色 `#F5F5F5` 底 / `#BFBFBF` 字 / `#D9D9D9` 边，深色自动翻转为可见的低对比灰。
3. 水平 padding：含 1px 边框的视觉值为 7 / 15 / 15px，无边框变体（solid / filled / text）取 8 / 16 / 16px，保证同尺寸视觉等宽。高度与圆角：controlHeight 24 / 32 / 40、borderRadius 4 / 6 / 8。
4. icon 阶梯 14 / 16 / 18（small / medium / large），单 icon 与「文字 + icon」同一套；间距 `gap-2`（8px），small 档收紧至 4px。
5. **旧 API 兼容期**：旧入参自动映射（`variant="outline"`→`default outlined`、`submit`→`primary solid`、`destructive`→`danger solid`、`ghost`→`default text`、`secondary`→`default filled`、`size="icon"`→`medium` + iconOnly、裸 `variant="link"`→`primary link`、size 缺省→`medium`），标 deprecated，业务迁完再删——避免一次改 138 个文件。
6. **按下深档仅触屏生效**：15 处 `active:` 包 `coarse-pointer` 媒体查询，与 hover 的 hover-capable 包裹互为补集。触屏 hover 禁用用 Tailwind `future.hoverOnlyWhenSupported` 全局开关实现；组件内**必须写普通 `hover:` 类，禁止自造 hover 变体前缀**——否则 tailwind-merge 认不出冲突，业务页 `className` 的 hover 覆盖会失效（曾导致品牌浅底按钮 hover 变灰的 bug）。
7. **outlined 各 color 通用 hover**：白底染当前色板的淡底、边框与文字色不变——primary→`brand-50`、danger→红 10% 透明度、default→`#f8f8f8`；触屏 active 再深一档（`brand-100` / 红 15% / `#f3f3f4`）。filled / link 等其余组合按同一逻辑推导：hover 加深或染色一档，active 再深一档。
8. 热区 `.btn-touch-hit` 伪元素扩到 ≥44px（medium 与 icon-only），写在 style.css 一处，禁止逐业务页处理。
9. 全局 CSS 类 `btn btn-*` 与 `Generations/Button` 逐批迁入后删除（`btn-primary` 写死的 ChatGPT 绿 `rgb(16,163,127)` 一并除）。现默认 h-9（36px）归入 medium（32px），全站矮 4px，迁移各批次时带批量目检回归。
10. 迁移节奏照总纲：设计师逐批点名、每批一笔提交；画廊 ButtonSection 按本规范重做。

## 附录 A：现状扫描存档（2026-07-14，仅迁移参考，不影响规范）

> 规范「不迁就现有场景」，本附录只为迁移排批次、估工作量用。扫描口径：`src/frontend/client/src`，排除 `ui/` 与 `_gallery/`。

### A.1 按钮的 5 路并行体系

| 体系 | 实现 | 用量 |
|---|---|---|
| ① 基准组件 | `ui/Button.tsx`（cva，8 变体 × 4 尺寸） | 269 处 / 138 文件（58% 带 className 手改） |
| ② 全局 CSS 类 | `btn btn-primary / btn-neutral / btn-secondary`(style.css:1419-1545) | 42 处 / 28 文件；btn-primary 写死 ChatGPT 绿 `rgb(16,163,127)` 不换肤 |
| ③ 第二个 Button | `components/Input/Generations/Button.tsx` | 3 消费方（Continue/Stop/Regenerate） |
| ④ 原生 `<button>` 手拼 | — | 469 处 / 222 文件（带视觉样式 135 文件，含大量合理图标钮，不全量迁移） |
| ⑤ 衍生包装 | SocialButton、DangerButton 等 | 少量 |

### A.2 现有 variant/size 用量（→ 新规范映射见「落地」第 5 条）

variant：缺省 default 109 + 显式 7 / outline 78 / ghost 40 / secondary 18 / submit 11 / destructive 6 / secondaryBrand 0 / link 0。
size：缺省（h-9） 201 / sm（h-9，与缺省同高名存实亡） 48 / icon 18 / lg 2。

### A.3 className 覆盖三大聚类（与新规范吻合）

- `h-8` 60 处 → 恰为新 medium(32px)；另 h-7×8、h-10×8、h-5×5。
- 6px 圆角 41 处（`rounded-[6px]` 26 + `rounded-md` 15），聚集 knowledge/Subscription 新页面 → 恰为新 medium 圆角。
- Arco 灰系 hex 手拼：`#4e5969`×16、`#e5e6eb`×11、`#666666`×7、`#f7f8fa`×6、`#ebecf0`×6 → 恰为新 Default 按钮取值，可直接折叠。

### A.4 疑点与死代码线索

- `DialogButton` 被 `Nav/SettingsTabs/DangerButton.tsx`（自身 0 消费方，死代码）与 `Chat/Menus/Presets/EditPresetDialog.tsx`（经 PresetsMenu 可达）import，但**全库找不到定义**——理论上打开编辑预设弹窗会崩，与「可达」矛盾，**待实测复核，未证实别当结论**。
- default 变体挂 `btn-brand-primary` 类，由 style.css:195-215 在绿主题下 `!important` 强刷 `#19b476` 三态（换肤 hack，见「落地」第 2 条记债）。

## 代码锚点

- 基准组件：`src/frontend/packages/ui/src/components/Button/Button.tsx`（2026-07-23 迁入 `@bisheng/ui`；client 旧路径 `~/components/ui/Button` 现为 re-export 壳）
- 全局类：`src/frontend/client/src/style.css:1419-1545`（btn 系）、`:195-215`（换肤 hack）
- 灰描边聚类代表：`pages/Subscription/ArticleList/MultiSourceSelect.tsx`、`pages/knowledge/SpaceDetail/EditTagsModal.tsx`
- 画廊版块：`src/frontend/client/src/pages/_gallery/sections/ButtonSection.tsx`
- 实时预览页：`src/frontend/packages/ui/docs/components/button.mdx`

## 改动记录

| 日期 | 改了什么 | 影响文件 | 提交 |
|---|---|---|---|
| 2026-07-14 | 现状扫描 + 建文档（Cowork 窗口，只动 docs-ui-refactor/） | 本文件、00-总纲看板 | 不提交（文档夹已 gitignore） |
| 2026-07-14 | 设计师定方向「参考 antd、不迁就现有场景」，写入双轴规范草案 | 本文件 | 不提交 |
| 2026-07-14 | 重构为纯规范文档（类型/尺寸/边距/字号/内容形态/状态矩阵）；现状梳理降级为附录 A | 本文件、00-总纲看板 | 不提交 |
| 2026-07-14 | 拍板：两汉字按钮不加中间空格 | 本文件 | 不提交 |
| 2026-07-14 | 移动端适配落档：新建 [基础-多端适配原则.md](基础-多端适配原则.md)，本文件加移动端节 | 本文件、基础-多端适配原则.md、00-总纲看板 | 不提交 |
| 2026-07-14 | 拍板：dashed 删除、Default hover 灰底、disabled 灰化、h-9→32 目检回归；danger 原红阶候选否决 | 本文件 | 不提交 |
| 2026-07-14 | danger hover 定稿 `#d6373a`；Ghost 删除（诉求由 Text 承接） | 本文件 | 不提交 |
| 2026-07-14 | danger active 定稿 `#d02f33`；全文清理决策过程赘述，**v1 定稿** | 本文件、00-总纲看板 | 不提交 |
| 2026-07-14 | **实现窗口：基准组件按规范重构落地。** `ui/Button.tsx` 重写为 `color×variant×size` cva + 15 组合 compoundVariants + `iconOnly`/`icon`/`loading` 属性；旧 API 全量自动映射并标 deprecated；语义 token `--btn-*` 落入 style.css + tailwind.config；新增 `can-hover`（后改为全局 `hoverOnlyWhenSupported`）与 `.btn-touch-hit` 热区；画廊 ButtonSection 按规范重做。已知债：outlined 白底/灰系暗色模式未适配；`btn-brand-primary` 换肤 hack 沿用。 | Button.tsx、style.css、tailwind.config.cjs、_gallery/sections/ButtonSection.tsx | 待 committer 窗口提交（style.css 与 tailwind.config.cjs 本次属组件一笔） |
| 2026-07-14 | v1 补充三项：新增 shape 属性（square/circle，circle 仅 icon 按钮）；icon 尺寸定为 14/16/18 三档（medium=16×16，单 icon 与文字+icon 同一套）；字重 500→**400** | 本文件、基础-字体规范.mdx | 不提交 |
| 2026-07-14 | **实现窗口：v1 三项补充落地。** `shape` 轴加入 cva（circle 仅 icon 按钮在 resolveVariants 里强制，非 iconOnly 静默回落 square）；基座 `font-medium`→`font-normal`；icon 阶梯统一 14/16/18。浏览器实测通过。 | Button.tsx、_gallery/sections/ButtonSection.tsx | 待 committer 窗口提交（同组件一笔） |
| 2026-07-14 | **拍板 + 落地：outlined 系 hover 改为「淡底」。** hover 一律加当前色板淡底、边字不变——primary→`brand-50`、danger→红 10%、default→灰 `#f7f8fa`；触屏 active 再深一档。 | Button.tsx、本文件 §6 | 待 committer 窗口提交（同组件一笔） |
| 2026-07-14 | **拍板 + 落地：active 深档改为仅触屏生效。** 桌面点击「闪一下」根因是 active 第三跳深色在桌面瞬时呈现；改为可 hover 设备按下沿用 hover 档，触屏保留深档。Button.tsx 15 处 `active:`→`coarse-pointer:active:`。 | Button.tsx、style.css、本文件 §6、基础-多端适配原则.md | 待 committer 窗口提交（同组件一笔） |
| 2026-07-14 | **首例业务迁移：知识空间侧栏「创建知识空间」** 由 `variant="secondary"` + className 手写品牌底迁为 `color="primary" variant="filled"` + `icon`，三态整套走品牌板，按下闪灰根治。 | pages/knowledge/sidebar/KnowledgeSpaceSidebar.tsx、画廊台账 | 待 committer 窗口提交（业务迁移单独一笔） |
| 2026-07-14 | **hover 变灰 bug 修复 + 规范澄清「色板跟随底色」。** 根因：自造 `can-hover:` 前缀 tailwind-merge 认不出冲突→cva 灰 hover 胜出，波及所有手写 hover 覆盖的存量调用。改用全局 `hoverOnlyWhenSupported`，恢复普通 `hover:` 类。§6 增补「色板跟随底色」原则。 | Button.tsx、tailwind.config.cjs、本文件 §6/§7、基础-多端适配原则.md | 待 committer 窗口提交（同组件一笔） |
| 2026-07-30 | **对照《元-文档撰写规范》重写正文**：新增 §1「什么时候用」；正文改为「先讲何时用、祈使句 + 为什么、✅/❌ 对照讲原因」的白话手法；技术细节（cva、`--btn-*` token、tailwind 类、媒体查询、旧 API 映射、padding 视觉值）从正文下沉到「落地（给实现窗口）」隐藏区；字号 / 圆角 / 颜色 / 图标 / 移动端通则改为引用对应基础规范（§0.2 规则只有一个家）；引号统一「」、章节改阿拉伯数字、修正跨文档链接扩展名（.md→.mdx）；修正正文 icon 尺寸旧值（14/16→14/16/18，与实现一致）。**设计决策一字未改，仅调整呈现与合规。** | 本文件 | 待 committer 窗口提交 |
| 2026-07-30 | **中性灰阶统一色温（拍板方案 B）。** ① 最浅档 `gray-1` 由 Arco 偏蓝的 `#F7F8FA` 改为纯中性 `#F8F8F8`；② 由此暴露出整条灰阶色相在 252°–277°（OKLCH）游走、饱和度非单调，遂重制中间档：全部锁到单一色相 264°（取自固定的 gray-10），饱和度从 gray-1 的 0 平滑爬升。gray-1 / 5 / 10 不动，其余各档 ΔE ≤ 0.8。**每档 OKLab 明度原样保留，故对比度零变化**（text-2 = 7.1、text-3 = 3.24、text-1 = 16.13）。按钮受影响的取值：文字/solid 底 `#4e5969`→`#525865`、边框 `#e5e6eb`→`#e5e6e9`、hover 底 `#f7f8fa`→`#f8f8f8`、active 底 `#f2f3f5`→`#f3f3f4`、filled hover `#e5e6eb`→`#e5e6e9`、filled active `#c9cdd4`→`#cacdd4`。改的是 token 值，组件代码与类名不动。深色阶未动。 | design-token.cjs、tokens.css、client/style.css、本文件「落地」§2/§7 | 待 committer 窗口提交（token 一笔） |
