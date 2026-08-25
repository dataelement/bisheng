# 输入框 Input

> 设计系统 · 输入框 v1 · 2026-08-20 建档
> 与 [00-总纲.md](00-总纲.md)、[01-设计规范.md](01-设计规范.md) 配套；字号见 [基础-字体规范.mdx](基础-字体规范.mdx)、颜色见 [基础-色彩规范.mdx](基础-色彩规范.mdx)、圆角见 [基础-圆角与阴影规范.mdx](基础-圆角与阴影规范.mdx)、图标见 [基础-图标规范.mdx](基础-图标规范.mdx)、移动端通则见 [基础-多端适配原则.md](基础-多端适配原则.md)、文案见 [基础-文案规范.md](基础-文案规范.md)。
> 调研来源（不进展示层）：尺寸阶梯对齐 antd / TDesign 的 24/32/40 并与本站按钮同档；「聚焦不用主题色、灰描边 + 阴影」为设计师输入的品牌约束，业内同路线先例为 shadcn/ui（Vercel 系）的中性 ring 画法（常态灰边，focus 灰环，错误才上红）；placeholder 与清除按钮的原则取自 Apple HIG。聚焦取值 2026-08-20 定稿：设计师拍板全部取现有 token（描边 border-deep、阴影环 gray-2），参照 client 消息提醒弹窗搜索框（ExpandableSearchField）的既有画法归并而来，归并口径见文末落地区。

## 1. 什么时候用

输入框用来收集**用户自己敲出来的文本**——名称、链接、密码、一段描述。

- 答案要用户自由输入，用输入框。
- 答案在有限选项里挑，用选择器，别让用户打字。
- 一行装不下的长内容，用多行文本域（见 §2）。

## 2. 形态 Type

先挑形态，再定尺寸；拿不准就用基础输入框。

| 形态 | 什么时候用 | 长相 |
|---|---|---|
| **基础 Input** | 绝大多数单行输入 | 白底 + 灰描边 |
| **多行 Textarea** | 描述、备注等一行装不下的内容 | 同基础款，高度多行 |
| **密码 Password** | 密码、密钥等敏感内容 | 默认密文，后缀「明暗切换」icon |
| **搜索 Search** | 列表、表格上方的过滤与检索 | 前缀放大镜 icon，回车即搜 |
| **前后置标签 addon** | 固定的协议前缀、单位（https://、元） | 标签与输入框拼成一体，标签用浅灰底 |

- **Textarea 默认三行高**，允许纵向手动拉伸、禁止横向；自动长高的场景要设上限，别让一个框吃掉整屏。
- **addon 与输入框共享一条外描边**，圆角只保留整体的外侧两角；addon 用浅灰填充底 + 次要文字色，看上去「属于框」而不是一个按钮。
- addon 只放「内容的一部分」（前缀、单位）。清除、明暗切换这类动作放后缀 icon，不做成 addon。

## 3. 尺寸 Size

三档，medium 是默认。高度与按钮同一套阶梯（见 [组件-Button按钮.md](组件-Button按钮.md) §3），同排控件天然对齐；高度定死，不要手写高度、内边距去凑。

| size | 高度 | 字号 / 行高 | 圆角 | 水平内边距 | 什么时候用 |
|---|---|---|---|---|---|
| `small` | 24px | 14 / 22 | 4px | 8px | 表格行内、紧凑工具条 |
| `medium`（**默认**） | 32px | 14 / 22 | 6px | 12px | 绝大多数表单 |
| `large` | 40px | 16 / 24 | 8px | 12px | 登录页、大表单 |

- 字号跟《字体规范》、圆角跟《圆角与阴影规范》控件档，随档取值不单独定义。
- **Textarea 不分档**：字号 14 / 22、圆角 6px、内边距上下 4px 左右 12px；**手动拉伸的下限是 32px**（与 medium 控件同高）——再矮就不像一个能写字的框，像一条拉坏的行。上下 4px 是被这个下限倒推出来的：32 − 2（描边）− 22（行高）= 10，两边各 4px 多一点，那行字才能在拉到底时**完整且垂直居中**；若取 8px，一行字要 40px 的框才装得下，拉到底就成了上下都被切一刀的半行。（4px 也是 antd 5px / Arco 4px 的那一档。）开了字数统计的下限是 56px——得把计数那一格的位置留出来。
- **宽度不定档，跟随布局**：同一表单里同级字段等宽；只有内容长度天然固定的字段（验证码、端口号）才用短框暗示长度。

| ✅ 推荐 | ❌ 不推荐 | 原因 |
|---|---|---|
| 输入框和旁边的按钮都用 medium | 32px 输入框配 40px 按钮 | 同排控件不同档，一高一低像没对齐的补丁 |
| 直接选 `size` 档 | 手写 `height` / `padding` 凑尺寸 | 手写值会和三档慢慢漂移，同一表单里高矮不一 |

## 4. 内容形态

### 4.1 占位文字 placeholder

- **写例子或格式提示，不写字段名**——placeholder 输入后就消失，把字段名写进去，等于一开始打字就把「这是什么框」弄丢了。字段名交给表单的 label。
- 用提示文字色（hint 档），和正文颜色拉开，见 [基础-色彩规范.mdx](基础-色彩规范.mdx)。

### 4.2 前缀 / 后缀 icon

- icon 尺寸随档取 14 / 16 / 18px，与文字间距 8px、small 档收紧到 4px，同《图标规范》与按钮一套。
- **前缀说明「这个框是什么」**（放大镜、链接），**后缀承载「对内容的动作」**（清除、明暗切换）或单位。
- 后缀最多两个动作 icon（如密码框的清除 + 明暗切换），再多说明该换控件。

### 4.3 一键清除

- 悬停或聚焦、且框内有内容时出现；点击清空并保持聚焦，方便立刻重输。
- 搜索、筛选类输入框默认开启；正式表单字段默认不开——误触清掉一整段辛苦输入的代价太大。

### 4.4 字数统计

- 需要限长才显示，格式「当前 / 上限」：单行放后缀区，多行放框内右下角。
- **超出上限不拦键盘**：字照打、计数照走，超出后计数转危险色，拦截交给表单校验（提交时报错，说清「最多 50 字，现在 53 字」）。到上限就吃掉按键，用户第一反应是键盘坏了或者输入框卡了——尤其粘贴一段话进去，只进去半截还不告诉他为什么。计数刚好等于上限（50 / 50）是合法值，不转红。
- 上限宽裕、几乎不会触到的字段不开计数——计数本身就是一种输入压力。

| ✅ 推荐 | ❌ 不推荐 | 原因 |
|---|---|---|
| placeholder 写「如 138xxxx0000」 | placeholder 写「手机号」 | 字段名输入后就看不见了，用户回头检查时不知道这框是什么 |
| 密码框后缀放明暗切换 icon | 把「显示密码」做成框外按钮 | 动作属于这个框，放后缀顺手可达；框外按钮撑乱表单排版 |
| 备注字段限 500 字不开计数 | 每个输入框都挂「0 / 50」 | 触不到的上限不用提醒，满屏计数只制造焦虑 |

## 5. 状态 State

### 5.1 聚焦不用主题色

**BISHENG 输入框的聚焦是「灰描边加深 + 一圈灰色阴影」，不用主题色细描边。** 表单里输入框成片出现，聚焦只回答「光标在哪」，不承载语义；颜色留给真正需要说话的时刻——校验的危险色与警告色。

### 5.2 状态一览

常态 → 悬停 → 聚焦是同一条灰色渐进链，只变深浅、不换色相。

| 状态 | 样式 |
|---|---|
| 常态 default | 白底 + 灰描边（border-base） |
| 悬停 hover | 描边加深为深边框色（border-deep），底色不变 |
| 聚焦 active | 描边保持深边框色（border-deep），外加 2px 浅灰阴影环（gray-2） |
| 只读 readonly | 浅灰填充底、描边同常态；可选中复制，聚焦不出阴影环 |
| 禁用 disabled | 浅灰底 + 灰字 + 灰描边，与按钮 disabled 同一套（见 [组件-Button按钮.md](组件-Button按钮.md) §6），「禁止」光标 |
| 错误 error | 描边转危险色，聚焦时阴影环同步换成危险色淡环 |
| 警告 warning | 描边转警告色，聚焦时警告色淡环 |

- 边框只有 base / deep 两档（见「设计变量 Design Token」页），悬停与聚焦共用 deep 档，聚焦靠阴影环与悬停拉开——不为输入框另造第三档灰。
- 错误、警告色取《色彩规范》功能色（淡环取对应 tint 档），禁用色一律引用按钮的取值，不另定义。
- **错误提示文字放输入框下方**，用危险色，说清「怎么改」而不是只说「错了」；文案跟《文案规范》。
- **错误阻断提交，警告不阻断**——警告是「能提交，但值得再看一眼」（如弱密码）。
- **内容有效、只是不让改，用只读；整个字段当前无意义，才用禁用**——禁用的内容读屏读不到、也复制不走。
- **嵌在自带描边容器里的输入框用 `borderless` 形态**（面板头部的搜索框、拼装出来的组合控件）：壳的描边、悬停加深、聚焦环整套关掉——态由容器表达，聚焦看光标本身。保留 1px 透明描边，和带边形态尺寸完全一致。校验色同理归容器管。定档来源：创建频道「添加信息源」面板的搜索框（2026-08-25 设计师拍板 active 不要 border 和 shadow），归档聊天搜索同款。

| ✅ 推荐 | ❌ 不推荐 | 原因 |
|---|---|---|
| 聚焦用灰描边 + 灰阴影环 | 聚焦上主题色细描边 | 表单里框成片出现，聚焦不是语义时刻，主题色应留给校验反馈 |
| 错误提示写「请输入 11 位手机号」 | 错误提示写「格式错误」 | 只说错了不说怎么改，用户还得自己猜规则 |
| 系统生成的 ID 用 readonly 展示 | 用 disabled 展示还需复制的内容 | 禁用态复制不走、读屏也读不到，内容有效就不该禁用 |

## 6. 移动端适配

跨组件通则见 [基础-多端适配原则.md](基础-多端适配原则.md)，这里只写输入框自己的细则。

| 项 | 触屏 / 窄屏规则 |
|---|---|
| 悬停 hover | 触屏没有悬停，关掉 hover 态，从常态直接进聚焦 |
| 字号 | 全档位升到 **16px**——iOS 上小于 16px 的输入框聚焦会触发页面自动放大 |
| 尺寸 | 触屏高频场景 small 直接升 medium；高度不足 44px 的档位用透明热区扩到 ≥44px（同按钮口径） |
| 一键清除 | 聚焦且有内容时常驻显示（触屏没有悬停可言），热区 ≥44×44px |
| 只读 / 禁用 / 错误 | 与桌面一致，无额外规则 |

<!-- site-hide -->
## 落地（给实现窗口）

**v1 组件已落地（2026-08-20）**：`packages/ui/src/components/Input/` —— `Input.tsx`（单行基座）/ `Textarea.tsx` / `PasswordInput.tsx` / `SearchInput.tsx` / `shared.ts`（外壳 cva + 三档取值 + 受控&非受控取值、清空、热区聚焦的共用件），由 `@bisheng/ui` 导出，demo 页 `docs/components/input.mdx`。下面 1–5 条按落地实况回填，第 6 条仍未做。

1. ✅ cva `variants: { size, status, state }`（24 / 32 / 40，圆角 4 / 6 / 8，水平内边距含 1px 边框的 7 / 11 / 11），`status: error` 同步置 `aria-invalid`。Password / Search / addon 是同一基座填不同插槽的组合形态，没有另一套 API：`PasswordInput` / `SearchInput` 都只是 `Input` 的薄包装。**边框、填充、圆角、聚焦环全画在外壳 `div` 上，`<input>` 自身透明无边框**——这正是前后缀与 addon 能共用一条描边的原因。
2. ✅ 颜色全走 token，组件内无裸 hex：常态描边 `border-border-base`；disabled 复用按钮三 token；错误 / 警告取功能色 main 档，聚焦环取对应 tint。
3. ✅ **聚焦取值**：hover / 聚焦描边 `border-border-deep`；聚焦环为 Tailwind 类 `shadow-focus`（`tailwind-preset.cjs` + client `tailwind.config.cjs`，SSOT 记在 `design-token.cjs` 的 `FOCUS_RING`，**刻意不并进两档 SHADOW**：它是聚焦指示不是高度，按《圆角与阴影规范》§4 例外条款）。**只有环的颜色是变量 `--shadow-focus-ring`（默认 `--fill-2`），2px 的几何写在类里**——原本想落成一个 `--shadow-focus: 0 0 0 2px rgb(var(--shadow-focus-ring))` 变量，实测不成立：自定义属性里的 `var()` 在**声明它的那一层**就被替换掉，写在 `:root` 就等于把环色钉死在 `:root` 的取值上，错误 / 警告态再怎么覆盖 `--shadow-focus-ring` 都换不动（落地当天踩到并改掉）。现在错误 / 警告态只覆盖 `--shadow-focus-ring` 为 danger-tint / warning-tint，环色在元素上解析。✅ `ExpandableSearchField` 的两个裸 hex 与 `rounded-lg` 已随 client 首批归并（2026-08-25，见落地区 6）。
4. ✅ placeholder 走 `text-text-3`（hint 档）；字数统计常态 hint、**超出**上限转危险色，单行在后缀区、多行在框内右下角（`bg-inherit` 垫底，滚动的正文从它下面过）。`showCount` 必须配 `maxLength`，缺了就不渲染。**`maxLength` 刻意不透传给 DOM**——原生属性会静默吞掉按键；超限时组件另置 `aria-invalid`，读屏用户看不见计数变红，得有个等价信号。
5. ✅ iOS 防缩放：`.input-no-zoom` 在 `@media (max-width: 768px), (hover: none) and (pointer: coarse)` 内把 input / textarea 提到 16px / 24，用 `input.input-no-zoom` 元素+类选择器写，确保压得住档位自己的 `text-[length:…]`。另补 `.input-touch-hit`：**上下各一条透明热区**把可点区域撑到 ≥44px，而不是像按钮那样盖一整块——盖在框上的覆盖层会吃掉「点到第几个字」的那一下，光标只能落到末尾。清除 / 明暗切换按钮仍用按钮那套 `btn-touch-hit`。
6. 🟨 存量迁移进行中（2026-08-25 扫描 + 首批）：
   - **扫描口径**（client/src，grep 文本计数）：旧 `~/components/ui/Input` 的 `<Input>` 57 处 / 52 文件、`<SearchInput>` 3 处；手拼原生 `<input>` 77 处；`<textarea>` 13 处；裸 hex 聚焦对 `#DDDDDD` + `#F1F5F9` 17 处 / 16 文件。
   - **首批已落**（2026-08-25）：① 17 处裸 hex 聚焦对全部归并为 `border-border-deep` + `shadow-focus`（含规范点名的 `ExpandableSearchField`——其 32px 高配的 `rounded-lg` 同步归 md 档 6px、「蓝框」过时注释改写；文件重命名 rename 框 FileCard / FileListRow 三处属常亮环，静态类同步归并）；② 六个手拼搜索框换成 `@bisheng/ui` 的 `SearchInput`：ChannelSquare、KnowledgeSquare、ChannelMemberDialog、ChannelMemberManagementPanel、KnowledgeListPanel、SkillSelector——后两个在 Radix 菜单里，stopPropagation 从 `<input>` 上移到包一层的 wrapper（点放大镜、内边距、清除按钮也不能漏给菜单的 type-ahead / 关闭逻辑）；归并同时把 12px 字号收到档位 14px、28px 高收到 medium 32px；③ 旧 `components/ui/Input.tsx` 挂 `@deprecated` 指针（默认高 40 vs 32、className 落 input vs 落外壳两处语义差写明，不能盲替）。
   - **第二批（2026-08-25，`<Input>` 收官）**：剩余 45 文件 / 50 处旧 `<Input>` 全部迁完。映射决策（用户拍板）：47 处 40px 默认高**全部归 medium**（32px，字号 14 不变）——分布盘点显示它们全是弹窗 / 侧栏表单字段与表格筛选框，正是 medium 档点名的场景，没有真正的登录大表单（LoginForm / ResetPassword 不用旧 Input）。做法：
     - 调用点逐个把 className 从「落在 `<input>`」翻成「落在外壳」：宽度类保留、老壳的 h-10 / border / placeholder 色 / focus 描边全删（壳已内建）；文字样式挪 `inputClassName`（QRPhase 的 mono、PromptName 的 2xl bold 等）。
     - 旧 `components/ui/Input.tsx` 翻成 **re-export**（Button 迁移同款，替换首批的 @deprecated 指针）：45 个文件的 import 一行未动，barrel 照常。
     - 又收编五个手拼搜索框进 `SearchInput`：KnowledgeSpaceSelect（dropdown 内，stopPropagation 包 wrapper）、AddToKnowledgeModal（手拼 X 清除删掉）、ArchivedChatsTable（保留 border-none 形态）、AddSourceDropdown（`onClear` 同步重置搜索态、回车 `onSearch` 提交）、MultiSelect（旧 SearchInput API → 新，`allowClear={false}` 保持原行为）。
     - PasswordForm 换 `PasswordInput`：父级三个明暗 flag 删除（状态归组件），新增 i18n key `com_ui_show_password` / `com_ui_hide_password`（三语同 PR）。
     - ChannelBusinessSettings 的全角计数从绝对定位 overlay 挪进 `suffix` 插槽（计数口径是全角单位，不用组件 showCount）。
     - 例外两处：CreatePromptForm / PromptName 的 2xl 标题字配 `size="large"`（24px 字塞不进 32px 框）；Advanced 的 image-detail 只读徽章保留其非常规外观（`size="small"` + 透明无边）。CrawlPreviewDialog 由 disabled+readOnly 改纯 readonly（§5.2：可复制内容不该禁用）。
     - 迁移带来的行为差：高度 40→32；原生 `maxLength` 不再截断（EditEncodingModal 64、InviteCode 50 改为软上限，拦截归表单校验）。
   - **Textarea 首迁（2026-08-25）**：表单形态的旧 `ui/Textarea` 三处换规范 `Textarea`——创建频道/频道设置的**频道简介**（设计点名）、知识空间设置的描述与自定义标签文本（后者 `rows={5}` 对齐原 112px 高）；旧壳的 min-h / shadow / placeholder 覆写全删（已内建）。旧 `ui/Textarea` 剩 4 个消费者全是**聊天 composer**（appChat ChatInput、MessageBsChoose、灵思 ClarifyCard 两处）——那是自动长高的对话输入形态，不属于表单文本域，不迁，等 composer 自己的规范。
   - **剩余**：原生 `<input>`（77 处）/ `<textarea>` 手拼逐批换壳；聊天 composer 4 处等 composer 规范；`_gallery` 清理后删除旧 `ui/Input.tsx` re-export。

## 待决策清单

- 聚焦阴影环 gray-2 为不透明色，放在非白底（如 fill-subtle 浅灰底卡片内）上会露一圈浅边；若后续出现灰底表单场景，再议是否改半透明等效值（现按白底表单为主定稿）。
- ~~字数统计超限策略现按「截断录入」写；antd 另有「允许超出、计数标红、提交时拦」路线，若表单校验需要再议。~~ **2026-08-20 结案：走「允许超出」路线**，见 §4.4。
- **`bisheng-icons` 没有 eye 图标**，而组件库契约不许自己画图标，所以 `PasswordInput` 的明暗切换两个图标（`revealIcon` / `hideIcon`）暂由调用方传入。图标包补上之后收成默认值，prop 保留给需要换图标的场景。
- Textarea 自动长高未内建：§2 要求它必须设上限，而目前没有调用场景来定这个上限，等真有场景再定 `autoSize` 的 API 形状。
- Form 表单项（label、必填标记、错误文字字号与间距）未建档，错误提示的排版细节届时归口 Form 规范，本文只定「框下方 + 危险色 + 说清怎么改」。

## 改动记录

| 日期 | 改了什么 | 提交 |
|---|---|---|
| 2026-08-20 | 建档 v1：形态五种（基础 / Textarea / Password / Search / addon）、尺寸三档 24/32/40 对齐按钮阶梯、内容形态四件套（placeholder / 前后缀 / 清除 / 字数）、状态七态含 readonly 与 warning；定稿「聚焦不用主题色，灰描边 + 灰阴影环」原则，具体取值待设计师输入（见待决策清单）；移动端 iOS 16px 防缩放规则 | 待 committer 窗口提交 |
| 2026-08-20 | **聚焦取值定稿**：设计师拍板全取现有 token——hover / 聚焦描边 border-deep（gray-4），聚焦加 2px gray-2 阴影环，错误 / 警告环换对应 tint 档；归并自 ExpandableSearchField 现值（#DDDDDD→gray-4 按意图、#F1F5F9→gray-2 肉眼无差），口径见落地区第 3 条；待决策清单勾销聚焦两项，新记「灰底场景环色再议」 | 待 committer 窗口提交 |
| 2026-08-20 | 站点接线（元规范 §5 上线清单）：`rspress.config.ts` 侧栏「组件规范」注册入口、00-总纲 §四 进度看板由「⬜ 待办 / 待建」改写为 v1 规范行、01-设计规范 §0 索引加行。**文档内容未改**；`components/input.mdx` demo 页未建——`Input.tsx` 尚未落地，照 Tooltip / Popover / Drawer 的先例规范先行，组件落地后再补 | 待 committer 窗口提交 |
| 2026-08-20 | **组件 v1 落地**：`packages/ui/src/components/Input/`（`Input` / `Textarea` / `PasswordInput` / `SearchInput`），三档尺寸、四态外壳、前后缀 / addon / 清除 / 字数、聚焦灰环全部按本文实现；新增环色 token `--shadow-focus-ring` + Tailwind 类 `shadow-focus`（`design-token.cjs` `FOCUS_RING`、两处 tailwind 配置、tokens.css 与 client style.css 双份同步；环的几何刻意留在类里，原因见落地区第 3 条）与两条 CSS 规则 `.input-no-zoom` / `.input-touch-hit`；demo 页 `components/input.mdx` 上线并注册侧栏「数据录入 Data Entry」。文档内容随实况回填落地区，新增两项待决策（eye 图标缺位、Textarea 自动长高） | 待 committer 窗口提交 |
| 2026-08-20 | Textarea 补下限：§3 明确手动拉伸不得低于 32px（与 medium 控件同高），组件落 `min-h-[30px]`（+ 外壳 1px 上下描边 = 32px 可见高）；为让那行字在下限处完整居中，**上下内边距由 8px 改为 4px**（8px 需要 40px 的框，拉到底会把一行字上下各切一刀），常态三行高随之 84→76px；开字数统计的下限另算 56px | 待 committer 窗口提交 |
| 2026-08-20 | **超限策略改为「允许超出」**（勾销待决策清单同名项）：§4.4 由「达到上限停止录入」改写为「字照打、计数照走、超出转危险色、拦截交给表单校验」，转红阈值由「达到」改为「超出」（50 / 50 是合法值）；组件不再把 `maxLength` 透传给 DOM，超限时另置 `aria-invalid` 给读屏 | 待 committer 窗口提交 |
| 2026-08-25 | **client 落地首批**：存量扫描（57 处旧 `<Input>` / 77 处原生 `<input>` / 17 处裸 hex 聚焦对，口径见落地区 6）；17 处裸 hex 全部归并 token（ExpandableSearchField 的 rounded-lg→md、蓝框注释一并修正，勾销落地区 3 的遗留项）；六个手拼搜索框迁 `SearchInput`；旧 `ui/Input.tsx` 挂弃用指针 | 待 committer 窗口提交 |
| 2026-08-25 | **client 第二批（`<Input>` 收官）**：剩余 45 文件 / 50 处旧 `<Input>` 全部迁至 `@bisheng/ui`（40px 默认高全部归 medium，用户拍板）；再收编五个手拼搜索框（KnowledgeSpaceSelect / AddToKnowledgeModal / ArchivedChatsTable / AddSourceDropdown / MultiSelect，累计 11 个）；PasswordForm 换 `PasswordInput` 并删父级明暗 flag（新增三语 key `com_ui_show_password` / `com_ui_hide_password`）；旧 `ui/Input.tsx` 翻成 re-export，import 零改动；例外与行为差见落地区 6 | 待 committer 窗口提交 |
| 2026-08-25 | 新增 **`borderless` 形态**（Input / Textarea，Search / Password 透传）：嵌在自带描边容器里的字段整套关掉描边+悬停+聚焦环，1px 透明边保尺寸；此前用 `border-none` 类名压不干净聚焦环（`shadow-focus` 单独就画出一圈）。AddSourceDropdown、ArchivedChatsTable 两处改用该 prop；定档来源为创建频道添加信息源面板的设计反馈 | 待 committer 窗口提交 |
| 2026-08-25 | **Textarea 首迁**：频道简介（创建频道/频道设置，设计点名）+ 知识空间设置两处文本域换规范 `Textarea`；旧 `ui/Textarea` 剩余 4 个消费者均为聊天 composer 形态，划出表单文本域范围不迁 | 待 committer 窗口提交 |
