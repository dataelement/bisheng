# 标签 Tag

> 设计系统 · 标签 v1 · 2026-08-28 建档
> 与 [00-总纲.md](00-总纲.md)、[01-设计规范.md](01-设计规范.md) 配套；颜色见 [基础-色彩规范.mdx](基础-色彩规范.mdx)（§3 功能色四态、§4 标签色对）、字号见 [基础-字体规范.mdx](基础-字体规范.mdx)、圆角见 [基础-圆角与阴影规范.mdx](基础-圆角与阴影规范.mdx)、图标见 [基础-图标规范.mdx](基础-图标规范.mdx)、文案见 [基础-文案规范.md](基础-文案规范.md)。姊妹篇：[组件-Badge徽标.md](组件-Badge徽标.md)（「标签还是状态点」的判别表在那边 §1）。
> 调研来源（不进展示层）：antd Tag（filled / solid / outlined 三款、5 状态色 + 11 预设色、CheckableTag；单一高度 22px）、Arco Tag（20/24/28/32 四档、字重 500、浅底默认 + bordered）、TDesign Tag（20/24/32 三档、light / dark / outline / light-outline 四款、square / round / mark 三形、maxWidth 省略号）。设计师拍板（2026-08-28）：**配色只留浅底深字**，描边 / 实底 / 灰底款不做；尺寸**两档 20 / 24**；收展示型、可关闭、可选中、带 icon / 头像四类。**状态点（点 + 一个词）当日由 [组件-Badge徽标.md](组件-Badge徽标.md) 归口过来**，成为本文 §5 的 `dot` 前缀款。
> 代码现状（2026-08-28 只读扫描，client/src）：`components/ui/Badge.tsx` 是 shadcn pill 标签，实际当 Tag 用（MultiSelect 已选项、MessageSource 来源）；`components/ui/Tag.tsx` 绿描边可移除 chip，0 处引用。迁库时统一归口本文，见给实现窗口。

## 1. 什么时候用

标签给一个对象**贴一个词**：它是什么类型、处在什么状态、属于哪个分类。贴的是「属性」，不是操作。

- 说明「这是什么 / 什么状态」（技能、助手、审批中、已完成），用标签。
- 列表里每行都要标状态、要一眼扫过去，用**带状态点的 small 档标签**（§5 `dot`）：点 + 一个词，行高不变、颜色好扫。
- 说「有多少 / 有没有新的」，用徽标，不用标签，判别表见 [组件-Badge徽标.md](组件-Badge徽标.md) §1。
- 要触发一个动作，用按钮——标签长得像按钮，但点标签不该「发生什么」。
- 一个对象最多贴 **3 个**标签：再多就没人看了，多出来的收进详情。

## 2. 长相与结构

一块浅色底 + 深色字，圆角 4px（sm 档），没有描边、没有实底。**同一语义一个色**，颜色对照 §3。

- 文字水平垂直居中，左右内边距随尺寸档（§4）。
- 可在文字前挂 icon 或头像，可在文字后挂关闭按钮（§5）。
- 标签之间横向间距 8px；一行放不下换行，行间距 8px。
- 深色模式：浅底自动切到深而饱和的色底，字色随功能色深色阶走（《色彩规范》§3），业务不写 `dark:` 覆盖。

## 3. 类型 Type

按「贴什么」分五个语义色，按「能不能动」分三种交互型。语义色管颜色，交互型管行为，两轴各选一个。

### 3.1 语义色 Color

| color | 底色 / 字色 | 贴什么 |
|---|---|---|
| `default`（**默认**） | fill-2 / text-2 | 无语义的普通分类、关键词、已选项 |
| `brand` | 品牌最浅档 / 品牌主色（随蓝⇄绿主题） | 强调类分类：当前版本、推荐、新 |
| `success` | success-tint / success | 已完成、已通过、在线、已发布 |
| `warning` | warning-tint / warning | 待处理、即将到期、草稿 |
| `danger` | danger-tint / danger | 已驳回、失败、已停用、已过期 |

- 固定例外（不随主题切换）：**审批中恒为蓝**、**技能恒为紫**，两组色对见《色彩规范》§4，其余业务不得再新增固定色。
- 一种语义只用一个色：「已完成」全站都是 success，不许这页绿那页蓝。
- 第三方品牌色（各家 logo 色）原样保留，不进语义色（《色彩规范》§4）。

| ✅ 推荐 | ❌ 不推荐 | 原因 |
|---|---|---|
| 「已驳回」用 danger，「待处理」用 warning | 「待处理」也用 danger 红 | 红表示出了问题，待处理只是还没轮到，红多了真出问题时没人当回事 |
| 普通分类词一律 default 灰 | 每个分类各配一种彩色 | 颜色没有语义就只剩装饰，读者会去猜「蓝比绿高级吗」 |

### 3.2 交互型

| 型 | 能做什么 | 用在哪 |
|---|---|---|
| **展示型**（默认） | 只看，不响应鼠标 | 状态、类型、分类 |
| **可关闭** `closable` | 右侧 × 移除自己 | 已选项、筛选条件、已上传文件 |
| **可选中** `checkable` | 点一下切选中 / 未选中，可多选 | 筛选面板、兴趣 / 标签挑选 |

- 可关闭标签：**点 × 立即移除，不弹确认**——移除已选项本来就可逆（再选一次就回来了）。真不可逆的（删除标签定义）用按钮走二次确认。
- 可选中标签固定 `default` 灰底起步，选中后变品牌浅底 + 品牌字（§6）；**不与语义色组合**——选中态已经占用了颜色这一层信号。
- 可关闭标签可以配语义色，但已选项、筛选条件这类场景 **一律 default 灰**：它们是用户自己挑的，不需要颜色再说一遍。

## 4. 尺寸 Size

两档，medium 是默认。标签是贴在别人身上的附属物，**比它所在控件阶梯小一档**。

| size | 高度 | 字号 / 行高 | 左右内边距 | icon | 什么时候用 |
|---|---|---|---|---|---|
| `small` | 20px | 12 / 20 | 6px | 12px | 表格单元格、列表行内、输入框内已选项 |
| `medium`（**默认**） | 24px | 12 / 20 | 8px | 14px | 卡片、详情页头、筛选面板 |

- 字重一律 400；选中态也不加粗，加粗会让标签变宽跳位。
- 同一组标签用同一档：一行里 20 和 24 混着放，参差比什么都显眼。
- 32px 输入框内的已选项用 small（20px）：上下各留 6px 才不顶边。

## 5. 内容形态

- **文案 2～6 个字**，名词或状态词，不带标点、不带动词——「已完成」不是「完成！」，「审批中」不是「正在审批」。写法跟《文案规范》。
- 默认不限宽、不截断。业务传 `maxWidth` 时**省略号截断 + Tooltip 显示全文**（同《Tooltip 规范》的溢出口径）；固定宽度的列（表格）才需要这么做。
- **前缀状态点**（`dot`，2026-08-28 由徽标规范归口过来）：实心圆，尺寸随档 **4 / 6px**，与文字间距 4px，**颜色跟文字色走**（`currentColor`）——选定语义色后点和字自动同色，不做第二次颜色决策。列表行用 small 档。五态沿用 §3.1 的语义色：

| 状态 | color | 例 |
|---|---|---|
| 无语义 / 未开始 | `default` | 未启动、草稿、排队中 |
| 进行中 | `brand` | 运行中、解析中 |
| 成功 | `success` | 在线、已完成 |
| 待办 / 将至 | `warning` | 待处理、即将到期 |
| 失败 / 停止 | `danger` | 已停止、失败、超时 |

- 状态点**不做呼吸 / 波纹动画**：一列几十个点一起闪，什么都看不清。若「运行中」确实需要动态感，归口未来的动效规范。
- **前缀 icon**：尺寸随档 12 / 14px，与文字间距 4px，颜色跟文字色走（`currentColor`）；同一组标签要么都带 icon 要么都不带。
- **前缀头像**：圆形 14 / 16px，左内边距收到 4px 让头像贴边，标签圆角改 **full 胶囊**——头像是圆的，方角包圆像漏了一角。头像标签只用 `default` 灰底。
- **关闭按钮**：× 图标 12px（`Outlined.Close`），与文字间距 4px，**右内边距不收窄、保持档位本身的 8 / 6px**（2026-08-28 改：原定收到 4px，实际看下来 × 像是要掉出标签——头像自带一块实心圆能撑住边缘，一个描边图标撑不住）；默认 text-3，悬停 text-1；热区是标签全高。
- 前缀位只有一个：**状态点 / icon / 头像三选一**，优先级 头像 > 状态点 > icon。

| ✅ 推荐 | ❌ 不推荐 | 原因 |
|---|---|---|
| 「已完成」「知识库」 | 「已经完成了」「知识库相关内容」 | 标签是词不是句，长了就成了第二行正文 |
| 表格里定宽列截断 + Tooltip | 标签换行撑高表格行 | 一个长标签把整行撑成两行高，表格节奏全乱 |

## 6. 状态 State

展示型标签只有默认和禁用两态，不响应悬停——它不可点，亮起来只会骗人去点。

| 状态 | 展示型 | 可关闭 | 可选中 |
|---|---|---|---|
| 默认 default | 语义色底 + 字（§3.1） | 同左 | fill-2 底 + text-2 字 |
| 悬停 hover | 无 | 仅 × 变 text-1，标签本体不变 | fill-3 底 |
| 选中 checked | — | — | 品牌 7% 透明底 + 品牌字（同列表选中态，《色彩规范》§1.2） |
| 选中悬停 | — | — | 品牌 10% 透明底 |
| 禁用 disabled | fill-1 底 + text-4 字 | 同左，× 同 text-4、不可点 | 同左，选中的禁用项保持品牌字但降为 text-4 底纹 |
| 键盘焦点 focus-visible | — | × 外显示 2px gray-2 聚焦环（同输入框口径，见 [组件-Input输入框.md](组件-Input输入框.md) §5） | 标签外显示同一聚焦环 |

- 可选中标签用鼠标或键盘 Space / Enter 切换，切换即生效、不需要确认。
- 没有 loading 态：标签不发请求；异步移除由业务在 × 点击后自己处理，标签先移除、失败再加回来并用 Toast 说明。

| ✅ 推荐 | ❌ 不推荐 | 原因 |
|---|---|---|
| 展示型标签鼠标移上去没反应 | 展示型标签加 hover 变色 | 变色暗示「可点」，点了没反应就是骗了一次 |
| 已选项用灰底可关闭标签 | 已选项用品牌色可关闭标签 | 品牌色管选中态和主操作，一排品牌色 chip 会抢走真正的主按钮 |

## 7. 移动端适配

跨组件通则见 [基础-多端适配原则.md](基础-多端适配原则.md)，这里只写标签自己的细则。

| 项 | 触屏 / 窄屏规则 |
|---|---|
| 尺寸 | 不变；只有可选中标签在触屏上**统一用 medium**，20px 太难点 |
| 悬停 hover | 触屏没有悬停，关掉 hover 态 |
| 热区 | 可关闭的 × 与可选中标签用透明热区扩到 ≥44px（同按钮口径，WCAG / Apple HIG 推荐值），视觉尺寸不变；相邻标签热区允许重叠，以视觉中心就近判定 |
| 换行 | 标签组正常换行，不横向滚动——筛选条件被藏进滚动区就等于没显示 |

<!-- site-hide -->
## 给实现窗口

1. 组件位置 `packages/ui/src/components/Tag/`（2026-08-28 已落地），`size: small | medium` × `color: default | brand | success | warning | danger | approving | skill`（后两个即 §3.1 的固定例外，独立取值而非 `brand` 的别名——`brand` 会跟着主题变绿，它们不会），行为用 props：`closable` / `onClose` / `closeLabel`、`checkable` / `checked` / `defaultChecked` / `onChange`、`dot` / `icon` / `avatar`、`maxWidth`、`disabled`。状态点写成 `bg-current`（跟字同色，禁用时自动跟着降到 text-4），`size-1` / `size-1.5`，`aria-hidden`——旁边的词才是内容。可选中标签渲染为 `<button aria-pressed>`，可关闭的 × 是独立 `<button aria-label="移除 {label}">`（文案由调用方传，组件库不含文案），展示型渲染为 `<span>`。**`closable` 在 `checkable` 上不生效**：button 套 button 是非法 HTML，而「挑中它 / 丢掉它」本来就是同一个问题的两种答法。
2. 颜色全走 token：default `bg-fill-2 text-text-2`；brand `bg-blue-50 text-blue-500`（随蓝⇄绿主题，深色由品牌深色阶自动翻转）；success / warning / danger 用 `--success-tint` / `--success` 等功能色四态 token（深色 tint 已是深而饱和的色底，无需覆盖）；固定例外「审批中蓝」「技能紫」已在 `tokens.css` 落成独立 token（`--tag-approving` / `--tag-approving-tint`、`--tag-skill` / `--tag-skill-tint`，明暗两套，**值写死、不引用 `--brand-*`**，`.theme-green` 不覆盖它们），类名 `bg-tag-approving-tint text-tag-approving`，不写裸 hex。选中态 `bg-blue-500/[0.07]`、选中悬停 `bg-blue-500/10`；禁用 `bg-fill-1 text-text-4`，选中的禁用项 `bg-text-4/20 text-blue-500`。
3. 圆角 `rounded-sm`（4px）；带 `avatar` 时切 `rounded-full`。高度 `h-5` / `h-6`，字号 `text-caption`（12/20），`font-normal`；padding `px-1.5` / `px-2`，**只有头像那一侧**收到 `pl-1`，× 那一侧保持档位 padding。前缀 icon 的档位类要写成 `[&>svg]`（直接子元素）而不是 `[&_svg]`：× 嵌在自己的 button 里，后代选择器会以 (0,2,0) 压过 × 自己的 `size-3`，把它顶成 14px。
4. 截断：`maxWidth` 生效时 `truncate` + 包一层 Tooltip（复用组件库 Tooltip，仅在实际溢出时才挂——用 `scrollWidth > clientWidth` 判断，避免每个标签都挂一个 Tooltip 监听）。
5. 触屏：可交互标签复用 `btn-touch-hit` 热区口径；hover 类照常写普通 `hover:`，禁止自造前缀（原因见 [组件-Button按钮.md](组件-Button按钮.md) 给实现窗口第 6 条）。
6. 迁移映射（本次只读扫描，2026-08-28，范围 `client/src`，排除 node_modules）：
   - `components/ui/Badge.tsx`（shadcn，5 款 variant）→ 归口本组件：`default` / `secondary` / `gray` → `color="default"`；`destructive` → `color="danger"`；`outline` 款废弃（本规范无描边款），使用处改 `default`。使用处：`components/ui/MultiSelect.tsx`（已选项，2 处，含 `bg-primary/20 text-primary` 品牌色 chip → 改 default 灰 + `closable`）、`pages/appChat/components/MessageSource.tsx`（1 处，可点击的「来源」→ 不是标签，改成文字按钮）。
   - `components/ui/Tag.tsx`（绿描边 chip，`rounded-3xl border-2 border-green-600`）：0 处引用，直接删除。**待迁**。
   - **已迁（2026-08-28）**：知识空间文件状态标签三处 → `<Tag size="small" dot color="default | danger | approving">`。`SpaceDetail/FileListRow.tsx` 的 `StatusBadge`（桌面列表行）、`SpaceDetail/FileCard.tsx` 的 `renderStatusOverlayTag`（卡片视图的图标浮层 + H5 列表行 inline 款）与同函数里的「上传中」占位胶囊。**本款的现实参照就是它们**（20px、圆角 4、12/20 字、4px 点 + 词，点色恒等于字色），画法一致，三处按本规范收敛：左右内边距 8 → 6px（§4 的 small 档取值）；三套裸 hex 换成 token（`#f2f4f7/#6b7785` → fill-2/text-2，`#fff2f0/#f53f3f` → danger-tint/danger）；**审批中由 `bg-blue-50` 改走固定例外色 `approving`**——原写法在绿主题下会跟着变绿，正是 §3.1 固定例外要防的那件事。状态 → 语义色的映射表留在各自页面，只把三值联合类型 `KnowledgeStatusTone` 提到 `pages/knowledge/knowledgeUtils.ts` 共用。
   - **已迁（2026-08-28）**：审批中心的状态标签 → `StatusBadge` 内部改渲染 `<Tag>`（`components/approval/approvalPresentation.tsx`），**三处一律用带状态点的标签**（设计师拍板）：列表行（`ApprovalPane`，待我处理 / 已处理 / 我的申请）与审批进度的节点标签用 small，详情页头用 medium（单个对象的状态要醒目，§4 的档位）。同一个状态在三处长得一样，所以 `StatusBadge` 不开 `dot` 开关——它不是调用点的选择。唯一要留意的是节点标签那处：时间轴左侧本来就有一颗节点圆点，同一行会出现两颗（一颗是节点进度、一颗在标签里），验收时看一眼。语义色映射：`pending` → `approving`（原 `#e8f3ff/#165dff`，正是这条固定例外要保住的蓝）、`approved`/`executed` → success、`rejected` → danger、`exception`/`execute_failed` → warning、`cancelled`/`skipped`/`withdrawn` → default。同排的「已撤销授权」灰胶囊一并换成 default 标签。画法收敛三处：圆角 full → 4px、字重 500 → 400、节点标签字号 11 → 12px。
   - 未迁：`SpaceDetail/VersionHistorySheet.tsx` 的版本状态胶囊（同样的裸 hex 色对，但**不带点**，且配置里的 `dot` 字段是死的），下一个迁移窗口一并收。
   - 全站散落的手拼状态标签（`rounded-* bg-[#xxx] text-[#xxx]` 的 span）未扫描，迁移窗口用「`bg-[#` + 状态词」grep 后补附录。
   - **组件名归位**：迁库后 `Badge` 这个导出名让给 [组件-Badge徽标.md](组件-Badge徽标.md) 的徽标组件，本组件导出 `Tag`；client 侧 `~/components/ui/Badge` re-export 在迁移完成前保留为 `Tag` 的别名，迁完删。
7. 站点接线（元规范 §5）：本文 + `components/tag.mdx` demo 页均已注册进 `rspress.config.ts` 侧栏，front matter `component: Tag` 已写（组件已进库）；00-总纲 §四 与 01-设计规范 §0 索引行随建档更新。

## 待决策清单

- 描边款 outline、实底款 solid、灰底 neutral 款本期均不做——设计师拍板只留浅底深字；真长出「一屏几十个状态标签浅底糊成一片」的场景再议描边款。
- 可选中标签的选中底取品牌 7% 透明底（与列表 / 菜单选中态同源），未在真实筛选面板上验收；若与页面选中态互相干扰，备选是品牌最浅档实色（brand-50）。
- 标签组的横向间距 8px 为本次建档取值（Arco 8px、antd 8px），待验收。间距由使用方的容器给（组件不带外边距），组件库不代管标签组布局。
- 「技能紫」的深色取值 `#33004D` 底 / `#9B5DE0` 字为落地时按功能色同一套深色算法推的，紫色不在 Arco 官方深色阶里，**待设计师在深色模式下验收**；「审批中蓝」深色直接锁定深色品牌蓝的值（`#000D4D` / `#3C7EFF`），不随 `.theme-green` 变。
- 「一个对象最多 3 个标签」是产品口径，不是组件硬限制；组件不截断数量。

## 改动记录

| 日期 | 改了什么 | 提交 |
|---|---|---|
| 2026-08-28 | **接手状态点**：徽标规范的「点 + 一个词」归口本文，成为 §5 的 `dot` 前缀款（点随档 4 / 6px、`currentColor` 跟字同色、五态沿用 §3.1 语义色、不做动画）；前缀位改为「状态点 / icon / 头像三选一」；§1 判别表与迁移映射同步，现实参照是知识空间文件列表的 `StatusBadge` | 待 committer 窗口提交 |
| 2026-08-28 | 落地后设计师验收两处修正：可关闭标签的**右内边距不再收到 4px**，保持档位的 8 / 6px（§5）；× 图标锁死 12px（前缀 icon 的档位类改用直接子元素选择器，原后代选择器把 medium 档的 × 顶成了 14px） | 待 committer 窗口提交 |
| 2026-08-28 | 组件落地 `packages/ui/src/components/Tag/`：五语义色 + `approving` / `skill` 两个固定例外色（新增 `--tag-approving-*` / `--tag-skill-*` 明暗 token 与 tailwind 接线）；展示 / 可关闭 / 可选中三型、两档尺寸、icon / 头像、`maxWidth` 溢出才挂 Tooltip、禁用五态全部按本文实现；`closable` 与 `checkable` 互斥（见给实现窗口 1）；demo 页 `components/tag.mdx` 上线。client 侧 `ui/Badge.tsx`、`ui/Tag.tsx` 的替换仍待迁 | 待 committer 窗口提交 |
| 2026-08-28 | 建档 v1：只留浅底深字一款（描边 / 实底 / 灰底款不做）；语义色五档 default / brand / success / warning / danger + 审批中蓝、技能紫两处固定例外归《色彩规范》§4；交互型三种（展示 / 可关闭 / 可选中），可选中固定灰底起步、选中品牌 7% 底；尺寸两档 20 / 24、字 12 / 400、圆角 4（头像款 full）；状态表分交互型三列；移动端可选中统一 medium + ≥44px 热区。与 [组件-Badge徽标.md](组件-Badge徽标.md) 同日建档，判别表归其 §1 | 待 committer 窗口提交 |
