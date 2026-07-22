# 按钮规范 Button

> 设计系统 · 按钮部分 v1 · 2026-07-14
> 参考 antd 规范制定，不迁就现有场景。颜色使用本项目 token：品牌色跟蓝⇄绿主题，危险红固定 `#f53f3f`。
> 与 [00-总纲.md](00-总纲.md)、[01-设计规范.md](01-设计规范.md)、[基础-字体规范.md](基础-字体规范.md) 配套。迁移参考数据见文末附录。

---

## 1. 类型 Type

底层模型采用 **color × variant 双轴**（type 只是组合的别名），对外提供以下常用类型：

> **什么叫双轴**：按钮的样子由两个独立属性拼出来——**color 管颜色**（品牌色 primary / 中性灰 default / 危险红 danger），**variant 管画法**（实心 solid / 描边 outlined / 浅底 filled / 文字 text / 链接 link）。两轴自由组合：红×实心=危险主按钮、红×描边=危险次按钮，3 色 × 5 画法共 15 种组合自动成立，不必逐个定义。

| 类型 | 双轴组合 | 长相 | 用途 |
|---|---|---|---|
| **Primary 主按钮** | `primary` × `solid` | 品牌色实心 + 白字 | 主行动点，**一个操作区域只放一个** |
| **Secondary 次强调** | `primary` × `filled` | 品牌浅底 + 品牌色字，无边框 | 弱于主按钮的品牌强调（如次级新建） |
| **Default 默认按钮** | `default` × `outlined` | 白底 + 灰描边 + 灰字 | 最常用的次级按钮（取消、返回等） |
| **Text 文字按钮** | `default` × `text` | 无底无边，hover 浅灰底 | 最次级操作、表格行内操作、工具栏 |
| **Link 链接按钮** | `primary` × `link` | 品牌色文字，hover 不加底 | 导航型操作，行为如链接 |
| **Danger 危险按钮** | `danger` × `solid / outlined / text` | 红实心 / 红描边 / 红文字 | 删除、移权等，一般配二次确认 |

不设 dashed（虚线）与 ghost（深底透明）类型；「无描边无背景」的诉求由 Text 承接。其余组合（`danger outlined`、`primary text` 等）按双轴自然推导。

**形状 Shape**（第三个独立属性）：`square`（默认，圆角随尺寸 4/6/8px）/ `circle`（正圆，`border-radius: 50%`，**仅用于单 icon 按钮**，文字按钮不可用）。

---

## 2. 尺寸 Size（3 档）

| size             | 高度   | 字号/行高 | 水平 padding※ | 圆角  | 适用            |
| ---------------- | ---- | ----- | ----------- | --- | ------------- |
| `small`          | 24px | 14/22 | 7px         | 4px | 表格行内、紧凑工具条    |
| `medium`（**默认**） | 32px | 14/22 | 15px        | 6px | 绝大多数场景        |
| `large`          | 40px | 16/24 | 15px        | 8px | 登录页、营销页、大表单提交 |

- ※ padding 为含 1px 边框的视觉值；无边框变体（solid/filled/text）取 8 / 16 / 16px，保证同尺寸按钮视觉等宽。
- 高度与圆角：controlHeight 24/32/40、borderRadius 4/6/8。
- 字号行高以 [基础-字体规范.md](基础-字体规范.md) 为准：small/medium 用 `text-body`(14/22)，large 用 `font-size-4`(16/24)；字体规范调整时按钮跟随。
- 垂直方向不设 padding，由高度定死；文字垂直居中。
- 同一视图内相邻按钮必须同尺寸。

---

## 3. 内容形态

### 3.1 单文字按钮
- 文字不换行（`whitespace-nowrap`）、不省略；文案过长说明该用别的控件。
- 字重 400(`font-normal`)，所有尺寸与类型一致。
- 两个汉字的按钮**不加**中间空格（实现时关闭 autoInsertSpace 类行为）。
- 弹窗 footer 的按钮 min-width 60px；移动端 footer 按钮等宽平铺。

### 3.2 单 icon 按钮
- 尺寸 24×24 / 32×32 / 40×40，与三档同高；形状可选 `square`（圆角随尺寸）或 `circle`（正圆）。
- icon 尺寸：small 14px / **medium、large 16px**，居中。
- 可用全部 variant（常用 `text`：工具栏图标钮；`outlined`：独立图标钮）。
- **必须带 Tooltip 说明含义**，并设 `aria-label`。
- 图标来源按总纲 §七：bisheng-icons 优先，lucide 兜底。

### 3.3 文字 + icon 按钮
- icon 尺寸与单 icon 按钮同一套：small 14px / **medium、large 16px**；与文字间距 8px(`gap-2`)，small 档可收紧至 4px。
- icon 默认在文字左侧；「下一步 →」这类方向语义可放右侧。
- 一个按钮最多一个 icon；loading 时 spinner 顶替 icon 位（无 icon 则前置）。

---

## 4. 边距与排布

| 场景 | 规格 |
|---|---|
| 同组相邻按钮间距 | 8px（紧凑场景/工具栏）；弹窗 footer 用 12px（对齐 01-设计规范 `gap-3`） |
| 弹窗 footer | 右对齐，**主按钮在最右**，取消在其左；danger 场景主位为 danger solid |
| 页面级操作区 | 主按钮在左首位（与弹窗相反），其余依次向右 |
| 与表单控件同排 | 按钮与 input 同高对齐（medium 32 ↔ 输入框统一高度，待 Input 组件期联动定稿） |
| block 按钮 | `width: 100%`，仅用于移动端/窄侧栏/登录页 |

---

## 5. 状态 State（各类型 × 各状态）

### 5.1 色板约定
- **品牌色**：`--primary` / `--brand-*` token，跟蓝⇄绿主题；hover 亮一档、active 深一档（档位由主题 token 提供，不写裸 hex）。
- **危险红**（不换肤）：base `#f53f3f`、hover `#d6373a`、active `#d02f33`。
- **中性灰**：文字 `#4e5969`、边框 `#e5e6eb`、hover 底 `#f7f8fa`。已建语义 token（`--btn-*` 系，style.css + tailwind `btn-*`），组件内不留裸 hex。

### 5.2 状态表

| 状态       | Primary(solid) | Default(outlined)              | Text              | Danger(solid)    |
| -------- | -------------- | ------------------------------ | ----------------- | ---------------- |
| 常态       | 品牌色底 + 白字      | 白底 + `#e5e6eb` 边 + `#4e5969` 字 | 透明底 + `#4e5969` 字 | `#f53f3f` 底 + 白字 |
| hover    | 品牌色亮一档         | 底 `#f7f8fa`，边字不变               | 底 `#f7f8fa`       | `#d6373a`        |
| active   | 品牌色深一档         | 底再深一档                          | 底再深一档             | `#d02f33`        |
| disabled | 全类型统一，见下       |                                |                   |                  |
| loading  | 全类型统一，见下       |                                |                   |                  |

- **active 档仅触屏生效**：可 hover 设备按下沿用 hover 档（按压时指针必然悬停，单独深档会造成点击闪动）；触屏下 active 是唯一按下反馈，取表中「再深一档」值。实现：active 类包 `coarse-pointer` 媒体查询，与 hover 的包裹互为补集。
- **disabled（全类型统一）**：走 `--btn-disabled-bg` / `--btn-disabled-text` / `--btn-disabled-border` 三个 token（浅色 `#F5F5F5` 底 / `#BFBFBF` 字 / `#D9D9D9` 边，深色自动翻转为可见的低对比灰），`cursor: not-allowed`。
- **loading（全类型统一）**：内置 spinner 顶替 icon 位，期间不可点，整体 opacity 0.65；**禁止业务页自塞 Spinner**。
- **focus**：`focus-visible` 才出外环（键盘可达、鼠标点击不出圈）；外环色随 color（品牌/红）。
- **outlined（各 color 通用）**：hover 一律是**白底染当前色板的淡底**，**边框与文字色不变**（不做纯边框/文字变色式 hover）——primary→`brand-50`、danger→红 10% 透明度、default→`#f7f8fa`；触屏 active 再深一档（`brand-100` / 红 15% / `#f2f3f5`）。
- filled / link 等其余组合的状态按同一逻辑推导：hover 加深底色或染色一档，active 再深一档。
- **色板跟随底色**：hover / active 的底色变化发生在**当前底色所属色板内**——品牌底走品牌板、红底走红阶、灰/白底走灰阶，**禁止跨色板变灰**。存量把品牌浅底手写在 `className` 上的（如 `bg-blue-100 hover:bg-blue-200`），迁移时改用 `primary filled`，不靠 className 叠 hover。

---

## 5.5 移动端适配

> 跨组件通用原则（双判定口径、逻辑与依据）见 [基础-多端适配原则.md](基础-多端适配原则.md)，此处只写 Button 自己的细则。

| 项 | 触屏/窄屏规则 |
|---|---|
| hover | 触屏（`hover: none`）下**全类型禁用 hover 态**，按下反馈走 §5.2 的 active 档（danger `#d02f33` 等直接复用），不新增色值 |
| 触达 | medium（32px）与各档 icon-only 用透明热区扩到 ≥44×44，**视觉尺寸不变**；small（24px）在触屏高频场景直接升 medium，不硬撑热区 |
| 字号 | 不随移动端正文抬升，保持 14/14/16（按钮是控件不是正文） |
| 弹层 footer | 窄屏等宽平铺 `flex-1`，桌面 `sm:flex-none` 右对齐 |
| block | 窄屏页面级主操作用 block 占满整行 |
| loading / disabled / focus | 与桌面一致，无额外规则 |

实现注意：hover 禁用与热区扩展**一处生效**，禁止逐业务页处理。hover 禁用用 Tailwind `future.hoverOnlyWhenSupported` 全局开关；组件内**必须写普通 `hover:` 类，禁止自造 hover 变体前缀**——否则 tailwind-merge 认不出冲突，业务页 `className` 的 hover 覆盖会失效。

---

## 6. 落地（给实现窗口）

1. `ui/Button.tsx` 重构为 cva `variants: { color, variant, size, shape }` + `compoundVariants`；保留 `className` 特例口子。基座字重 `font-normal`。
2. 颜色全走 token：品牌用 `--primary`/`--brand-*`（目标替代 `btn-brand-primary` !important 换肤 hack，主题机制暂不动则先沿用并记债）；灰系/红系建语义变量，不留裸 hex。
3. **旧 API 兼容期**：旧入参自动映射（`variant="outline"`→`default outlined`、`submit`→`primary solid`、`destructive`→`danger solid`、`ghost`→`default text`、`secondary`→`default filled`、size 缺省→`medium`），标 deprecated，业务迁完再删——避免一次改 138 个文件。
4. 全局 CSS 类 `btn btn-*` 与 `Generations/Button` 逐批迁入后删除（btn-primary 的写死 ChatGPT 绿即除）。
5. 迁移节奏照总纲：设计师逐批点名、每批一笔提交；画廊 ButtonSection 按本规范重做（标准用法文档 + 现状对比）。
6. 现默认 h-9（36px）归入 medium（32px）全站矮 4px：迁移各批次时**带批量目检回归**。

---
---

## 附录 A：现状扫描存档（2026-07-14，仅迁移参考，不影响规范）

> 规范「不迁就现有场景」，本附录只为迁移排批次、估工作量用。扫描口径：`src/frontend/client/src`，排除 `ui/` 与 `_gallery/`。

### A.1 按钮的 5 路并行体系

| 体系 | 实现 | 用量 |
|---|---|---|
| ① 基准组件 | `ui/Button.tsx`（cva,8 变体 × 4 尺寸） | 269 处 / 138 文件（58% 带 className 手改） |
| ② 全局 CSS 类 | `btn btn-primary / btn-neutral / btn-secondary`(style.css:1419-1545) | 42 处 / 28 文件；btn-primary 写死 ChatGPT 绿 `rgb(16,163,127)` 不换肤 |
| ③ 第二个 Button | `components/Input/Generations/Button.tsx` | 3 消费方（Continue/Stop/Regenerate） |
| ④ 原生 `<button>` 手拼 | — | 469 处 / 222 文件（带视觉样式 135 文件，含大量合理图标钮，不全量迁移） |
| ⑤ 衍生包装 | SocialButton、DangerButton 等 | 少量 |

### A.2 现有 variant/size 用量（→ 新规范映射见 §6 第 3 条）

variant：缺省 default 109 + 显式 7 / outline 78 / ghost 40 / secondary 18 / submit 11 / destructive 6 / secondaryBrand 0 / link 0。
size：缺省（h-9） 201 / sm（h-9，与缺省同高名存实亡） 48 / icon 18 / lg 2。

### A.3 className 覆盖三大聚类（与新规范吻合）
- `h-8` 60 处 → 恰为新 medium(32px)；另 h-7×8、h-10×8、h-5×5。
- 6px 圆角 41 处（`rounded-[6px]` 26 + `rounded-md` 15），聚集 knowledge/Subscription 新页面 → 恰为新 medium 圆角。
- Arco 灰系 hex 手拼：`#4e5969`×16、`#e5e6eb`×11、`#666666`×7、`#f7f8fa`×6、`#ebecf0`×6 → 恰为新 Default 按钮取值，可直接折叠。

### A.4 疑点与死代码线索
- `DialogButton` 被 `Nav/SettingsTabs/DangerButton.tsx`（自身 0 消费方，死代码）与 `Chat/Menus/Presets/EditPresetDialog.tsx`（经 PresetsMenu 可达）import，但**全库找不到定义**——理论上打开编辑预设弹窗会崩，与「可达」矛盾，**待实测复核，未证实别当结论**。
- default 变体挂 `btn-brand-primary` 类，由 style.css:195-215 在绿主题下 `!important` 强刷 `#19b476` 三态（换肤 hack，见 §6 第 2 条记债）。

### A.5 代码锚点
- 基准组件：`src/frontend/client/src/components/ui/Button.tsx`
- 全局类：`src/frontend/client/src/style.css:1419-1545`（btn 系）、`:195-215`（换肤 hack）
- 灰描边聚类代表：`pages/Subscription/ArticleList/MultiSourceSelect.tsx`、`pages/knowledge/SpaceDetail/EditTagsModal.tsx`
- 画廊版块：`src/frontend/client/src/pages/_gallery/sections/ButtonSection.tsx`（未按本规范重做，留给组件窗口）

---

## 改动记录

| 日期 | 改了什么 | 影响文件 | 提交 |
|---|---|---|---|
| 2026-07-14 | 现状扫描 + 建文档（Cowork 窗口，只动 docs-ui-refactor/） | 本文件、00-总纲看板 | 不提交（文档夹已 gitignore） |
| 2026-07-14 | 设计师定方向「参考 antd、不迁就现有场景」，写入双轴规范草案 | 本文件 | 不提交 |
| 2026-07-14 | 重构为纯规范文档（类型/尺寸/边距/字号/内容形态/状态矩阵）；现状梳理降级为附录 A | 本文件、00-总纲看板 | 不提交 |
| 2026-07-14 | 拍板：两汉字按钮不加中间空格 | 本文件 | 不提交 |
| 2026-07-14 | 移动端适配落档：新建 [基础-多端适配原则.md](基础-多端适配原则.md)，本文件加 §5.5 | 本文件、基础-多端适配原则.md、00-总纲看板 | 不提交 |
| 2026-07-14 | 拍板：dashed 删除、Default hover 灰底、disabled 灰化、h-9→32 目检回归；danger 原红阶候选否决 | 本文件 | 不提交 |
| 2026-07-14 | danger hover 定稿 `#d6373a`；Ghost 删除（诉求由 Text 承接） | 本文件 | 不提交 |
| 2026-07-14 | danger active 定稿 `#d02f33`；全文清理决策过程赘述，**v1 定稿**（§7 待确认清单清空删除） | 本文件、00-总纲看板 | 不提交 |
| 2026-07-14 | **实现窗口：基准组件按 §6 重构落地。** ① `ui/Button.tsx` 重写为 `color×variant×size` cva + 15 组合 compoundVariants + `iconOnly`/`icon`/`loading` 属性（spinner 用 `Outlined.Loading`）；旧 API 全量自动映射（§6.3，含 `size="icon"`→medium+iconOnly、裸 `variant="link"`→primary link），标 deprecated；`buttonVariants()` 导出保持兼容（Pagination/BackToChat 消费方不动）。② 语义 token `--btn-*` 落入 style.css :root + tailwind.config `btn-*` 色（danger 三态、灰系 text/border/fill-1..4、disabled 边）；disabled 用 `black/[0.04]`+`black/25` 免 token。③ §5.5 落地：新增 tailwind `can-hover` 变体（`not ((hover:none) and (pointer:coarse))`）包裹全部 hover 态；`.btn-touch-hit` 伪元素热区 ≥44px(medium+icon-only)，写在 style.css 一处。④ 画廊 ButtonSection 按规范重做（常用类型/15 格矩阵/尺寸/内容形态/disabled+loading/旧 API 迁移台账）。**实现期推导值待设计师画廊确认**：灰 active=`#F2F3F5`、default filled 三态=`F2F3F5/E5E6EB/C9CDD4`（Arco 灰阶顺推）、default solid=深灰实心（规范未定义的稀有组合）、danger filled/link 用红 8%–20% 透明度阶。已知债：outlined 白底/灰系为亮色模式取值，暗色模式未适配；`btn-brand-primary` 换肤 hack 照 §6.2 沿用。**类型兼容修复**：`color` 轴与原生 HTML color 属性冲突，类型放宽为 `ButtonColor \| (string & {})` + 运行时白名单（SharedLinkButton 的 TooltipAnchor 透传场景）。 | Button.tsx、style.css、tailwind.config.cjs、_gallery/sections/ButtonSection.tsx | 待 committer 窗口提交（注意：**style.css 与 tailwind.config.cjs 本次属组件一笔**，总纲的按路径分 add 清单未含这两个文件，提交时需一并 add） |
| 2026-07-14 | v1 补充三项：新增 shape 属性（square/circle,circle 仅 icon 按钮）；icon 尺寸定为 14/16/18 三档（medium=16×16，单 icon 与文字+icon 同一套）；字重 500→**400**（字体规范 §3 的「按钮」用途同步移出 500 档） | 本文件、基础-字体规范.md | 不提交 |
| 2026-07-14 | **实现窗口：v1 三项补充落地。** ① `shape` 轴加入 cva（square 空/circle=`rounded-full`，声明在 size 之后以覆盖每档圆角）；**circle 仅 icon 按钮在 resolveVariants 里机械强制**——非 iconOnly 时静默回落 square，业务写错不会出现圆角文字按钮。② 基座 `font-medium`→`font-normal`（全尺寸全类型 400）。③ icon 阶梯统一 14/16/18:size 轴 svg 尺寸改为 3.5/4/[18px],icon-only 的 compoundVariants 不再单独覆盖 svg（与文字+icon 同一套）。画廊同步：纯 icon 卡加 circle 示例（outlined 灰 + primary 实心）、字重/icon 尺寸描述更新、规则区补 circle 限制。浏览器实测：字重 400、circle `border-radius:9999px` 32×32、icon 实测 24→14/32→16/40→18（loading spinner 包围盒 22px 系 animate-spin 旋转对角线，非尺寸问题）。 | Button.tsx、_gallery/sections/ButtonSection.tsx | 待 committer 窗口提交（与上一行基准重构同一笔） |
| 2026-07-14 | **拍板 + 落地：outlined 系 hover 改为「淡底」。** 原实现 primary/danger outlined 的 hover 只变边框和文字色（antd 式），设计师定为：hover 一律加当前色板的淡底、边字不变——primary→`brand-50`、danger→红 10%、default 原本就是灰 `#f7f8fa`，三列行为同构；触屏 active 再深一档（`brand-100`/红 15%）。§5.2 增补 outlined 通用规则，Button.tsx 两处 compound 更新。 | Button.tsx、本文件 §5.2 | 待 committer 窗口提交（同组件一笔） |
| 2026-07-14 | **拍板 + 落地：active 深档改为仅触屏生效。** 设计师反馈迁移后的「创建知识空间」桌面点击仍「闪一下」——根因即 active 深一档（50→100→200 的第三跳）在桌面瞬时呈现。拍板：可 hover 设备按下沿用 hover 档（指针按压时必然悬停，天然显示 hover 色，无闪动）；触屏保留深一档作唯一按压反馈（适配原则 §1 的 active 补偿不受影响）。落地：Button.tsx 全部 15 处 `active:` → `coarse-pointer:active:`（触屏媒体，与 hover 的 hover-capable 包裹互为补集）；style.css 绿主题 `btn-brand-primary` hack 的 `:active` 同样包进触屏媒体（桌面绿主按钮同步不闪）；§5.2/适配原则 §1/画廊文案同步。注意：业务页若有自写 `active:` 覆盖（现存约 19 处、多为原生按钮），桌面上仍按其自身写法生效。 | Button.tsx、style.css、本文件 §5.2、基础-多端适配原则.md §1、画廊文案 | 待 committer 窗口提交（同组件一笔） |
| 2026-07-14 | **首例业务迁移（设计师点名）：知识空间侧栏「创建知识空间」** 由 `variant="secondary"` + className 手写品牌底（`bg-blue-100 hover:bg-blue-200`，无 active）迁为新 API `color="primary" variant="filled"` + `icon={<Outlined.Plus />}`(lucide Plus→bisheng-icons),className 只剩 `w-full`。三态整套走品牌板（50→100→200），按下闪灰问题根治；底色比原来浅一档（blue-100→blue-50）属规范 Secondary 取值，预期内。画廊台账 secondary 计数 18→17。**注意：此文件是业务页，按总纲规则 5 应尽快单独提交一笔并知会日常窗口**（不与组件笔混合，git add 只加此文件）。 | pages/knowledge/sidebar/KnowledgeSpaceSidebar.tsx、画廊台账 | 待 committer 窗口提交（**业务迁移单独一笔**） |
| 2026-07-14 | **hover 变灰 bug 修复 + 规范澄清「色板跟随底色」。** 设计师发现知识空间侧栏「创建知识空间」（品牌浅底 `className="bg-blue-100 hover:bg-blue-200"` + 旧 `variant="secondary"`）hover 变灰。根因：上轮 cva hover 用了自造 `can-hover:` 前缀，tailwind-merge 认不出它与业务 `hover:bg-*` 冲突→cva 灰 hover 胜出，**波及所有手写 hover 覆盖的存量调用**。修复：改用 Tailwind `future.hoverOnlyWhenSupported` 全局开关实现触屏 hover 禁用（全 app 生效，顺带落实适配原则 §1）,Button 恢复普通 `hover:` 类，删除 `can-hover` 变体；node 实测 tw-merge 去重恢复（品牌 hover 胜出）。规范侧：§5.2 增补「色板跟随底色」原则（品牌底 hover 走品牌板，禁跨色板变灰），§5.5 实现注意改写（禁止自造 hover 变体前缀），多端适配原则 §1 记全局落地。遗留：该按钮按下仍闪灰（`active:bg-btn-fill-4` 无业务覆盖），根治需迁移该按钮为 `primary filled`——列入迁移点名清单。 | Button.tsx、tailwind.config.cjs、本文件 §5.2/§5.5、基础-多端适配原则.md | 待 committer 窗口提交（同组件一笔） |
