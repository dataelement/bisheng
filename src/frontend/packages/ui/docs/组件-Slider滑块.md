# 滑块 Slider

> 设计系统 · 滑块 v1 · 2026-10-21 建档
> 与 [组件-InputNumber数字输入框.md](组件-InputNumber数字输入框.md)（并排数字框）、[组件-Tooltip文字提示.md](组件-Tooltip文字提示.md)（数值气泡）、[组件-Input输入框.md](组件-Input输入框.md)（聚焦环）配套；颜色见 [基础-色彩规范.mdx](基础-色彩规范.mdx)、移动端通则见 [基础-多端适配原则.md](基础-多端适配原则.md)。
> 调研 antd 5 Slider（range / marks / dots / step=null / tooltip / onChangeComplete；轨道 4px、滑块 10→12px、2px 描边环）、Arco Slider（showInput 并排数字框 / onlyMarkValue / showTicks）、Carbon Slider（单值与范围都配数字框、无数字框时悬停 / 拖动出气泡、Shift + 方向键 10 步、Home / End、范围忌过大过小）、Apple HIG Sliders（最小值在左、精确值配文本框与步进器、只标两端也够、拖动实时反馈）后制定。设计师 2026-10-21 拍板四项：v1 做单值 + 范围 + 刻度标签（不做竖向、不做整段平移）；数值显示按场景二选一（精确值并排数字框 / 大致调整出气泡）；滑块白底 + 品牌色描边环；只设一档尺寸，轨道 4px、滑块 16px。

## 1. 什么时候用

滑块用来在**一个有边界的区间里调一个大致的值**，拖动时能实时看到效果——音量、温度、透明度、模型的随机性参数。

- 区间不大不小、拖着调比打字顺手，用滑块。
- 只需在当前值上加减一两下（数量、次数），用数字输入框，见 [组件-InputNumber数字输入框.md](组件-InputNumber数字输入框.md)。
- 区间太大（1～10000）拖不准、太小（1～3）不值得拖，都别用滑块：前者用数字输入框，后者用单选或分段控制器。
- 日期、时间不用滑块，用日期选择器。

## 2. 结构

| 部分 | 规则 |
|---|---|
| 轨道 | 4px 高、两端全圆角；未覆盖段灰色，已覆盖段品牌色 |
| 滑块 | 16px 白底圆点 + 2px 品牌色描边环 |
| 刻度与标签 | 可选，见 §3.3 |
| 数值 | 并排数字输入框或数值气泡，二选一，见 §5 |

- **最小值在左、最大值在右**，与所有人的直觉一致。
- 整个控件占 32px 高、轨道垂直居中，和 medium 档的输入框、按钮同排时天然对齐。

## 3. 类型

### 3.1 单值

一个滑块，从最小值到滑块之间是品牌色。绝大多数场景用它。

### 3.2 范围

两个滑块选出一个区间（如价格 100～500），**两个滑块之间**是品牌色。

- 两个滑块**不能交叉**：拖到和另一个重合就停住，允许上下限相等。
- 点击轨道时，**离点击处更近的那个滑块**移过去。

### 3.3 刻度与标签

在轨道上标出关键值。

- **刻度点**：8px 白底圆点 + 2px 描边，未覆盖段用灰色描边（border-base）、已覆盖段用品牌色描边。
- **标签**：放在轨道下方，正对刻度居中；12px 说明文字、辅助文字色（hint）。两端的标签与轨道端点对齐，不伸出轨道。
- **不必每个刻度都标**：只标两端和少数关键值；相邻标签之间留不出 8px 就减少标签，挤成一排读不出来。
- **值只有几个固定档位**（如播放速度 0.5x / 1x / 1.5x / 2x）时，设成「只能停在刻度上」，滑块松手会吸附到最近的刻度。

| ✅ 推荐 | ❌ 不推荐 | 原因 |
|---|---|---|
| 0～1 的参数只标「0」「0.5」「1」 | 0～1 每隔 0.1 标一个数字 | 11 个数字挤在一条轨道下，哪个都读不清；两端加中点已经足够定位 |
| 播放速度设成只能停在刻度上 | 播放速度能拖到 1.37x | 只有几个有效档位时，停在中间的值没有意义，还要用户自己凑整 |

## 4. 尺寸

**只有一档**，不跟控件的 24 / 32 / 40 走：轨道 4px、滑块 16px（悬停与拖动时放大到 18px）、刻度点 8px。

- 滑块圆点比轨道粗一大圈才好抓，放大 2px 是告诉用户「抓住了」。
- **宽度跟随布局**：单独一行时撑满，与数字输入框并排时占去数字框之外的全部宽度；最短不小于 120px，再短就拖不出精度了。

## 5. 数值显示

当前值用下面两种方式之一显示，**不同时用**——同一个数显示两遍，用户反而要确认两处是否一致。

| 方式 | 什么时候用 | 长相 |
|---|---|---|
| **并排数字输入框** | 值需要被准确记住或复用（模型温度 0.7、阈值 85%） | 滑块右侧放一个 small 档数字输入框，间距 16px |
| **数值气泡** | 只看效果、不在乎具体数（音量、缩放、亮度） | 悬停滑块、拖动、键盘聚焦时，滑块正上方出气泡 |

### 5.1 并排数字输入框

- 两边**双向同步**：拖滑块改数字框，在数字框里输入合法值滑块跟着动。
- 数字框里输入越界值，按数字输入框的规则报错（见 [组件-InputNumber数字输入框.md](组件-InputNumber数字输入框.md) §5.2），**滑块停在最后一个合法值上不动**，不跟着跑到边界外。
- 数字框用 **small 档（24px）**，与滑块那一行（32px）垂直居中：数字框是滑块的附属读数，不该比轨道更抢眼。
- 数字框宽度按最大值的位数给，同数字输入框 §3。
- **范围滑块要精确值时，两端各放一个数字框**：左边放下限、右边放上限，和滑块的方向一致。
- 单位放数字框的后缀（%、℃）。

### 5.2 数值气泡

- 长相与文字提示完全一致（深底白字），见 [组件-Tooltip文字提示.md](组件-Tooltip文字提示.md) §3。
- 拖动过程中**跟着滑块走、一直显示**，松手且指针离开后消失。
- 气泡里写带单位的值（「70%」「1.5x」），格式与刻度标签一致。

| ✅ 推荐 | ❌ 不推荐 | 原因 |
|---|---|---|
| 模型温度：滑块 + 右侧数字框 | 模型温度：只有拖动时才出现的气泡 | 这个值要被记住、被复用，松手就看不见的数字没法核对 |
| 并排数字框时不再出气泡 | 数字框和气泡同时显示同一个值 | 同一个数显示两遍是噪音，用户还要确认两处是否一致 |

## 6. 交互

- **点击轨道**，滑块直接跳到点击处；**拖动滑块**连续调整。
- **键盘**：← / → 或 ↑ / ↓ 调一个步长，Shift + 方向键调 10 个步长，Home / End 跳到最小值 / 最大值。
- **鼠标滚轮不改值**，同数字输入框：滚页面时扫过滑块不该改掉它的值。
- **拖动中实时预览，松手才生效**：拖的过程中立刻看到效果，保存、请求这类动作等松手后只做一次——每拖一像素都发一次请求，接口和用户都受不了。

## 7. 状态

| 状态 | 样式 |
|---|---|
| 常态 | 灰色轨道 + 品牌色已覆盖段 + 16px 白底品牌色描边滑块 |
| 悬停 hover | 指针在滑块上：滑块放大到 18px，指针变「抓手」 |
| 拖动 active | 保持 18px，指针变「抓紧」；用气泡的出气泡并跟随 |
| 聚焦 focus | 键盘 Tab 到才出现：滑块外加 2px 灰色阴影环，同输入框聚焦环（见 [组件-Input输入框.md](组件-Input输入框.md) §5）；用气泡的同时出气泡 |
| 禁用 disabled | 已覆盖段与滑块描边都转灰（禁用灰），「禁止」光标；并排的数字框一起禁用 |

- 滑块本身**没有报错态**：要校验范围，由并排的数字框报错。
- 已覆盖段在悬停时不变色——滑块放大已经是足够的反馈，轨道再变色会让整条控件闪一下。

## 8. 移动端适配

跨组件通则见 [基础-多端适配原则.md](基础-多端适配原则.md)，这里只写滑块自己的细则。

| 项 | 触屏 / 窄屏规则 |
|---|---|
| 触达 | 滑块用透明热区扩到 ≥44×44px，**视觉仍是 16px**；轨道上下也扩出可点区域 |
| 悬停 | 没有悬停态，按下即放大到 18px |
| 数值气泡 | 按住拖动时显示在手指上方，松手即消失 |
| 并排数字框 | 按数字输入框的触屏规则（隐藏步进按钮、弹数字键盘）；窄屏放不下时数字框移到滑块上方右侧，与标签同一行 |

44px 是 WCAG 与 Apple HIG 推荐的触达底线；视觉不变是为了不让一个 44px 的大圆点压住整条轨道。

## 9. 深浅色

颜色全部走 token，深色模式自动翻转：轨道灰随灰阶变深，滑块的白底改为深色页面底色，品牌色描边不变。数值气泡的深色取值跟文字提示走，见 [组件-Tooltip文字提示.md](组件-Tooltip文字提示.md) §3。

<!-- site-hide -->
## 落地（给实现窗口）

1. 组件放 `packages/ui/src/components/Slider/`，基于 `@radix-ui/react-slider`（client 现壳已在用，已加进 pnpm catalog 与 `@bisheng/ui` 依赖），由 `@bisheng/ui` 导出。单值 / 范围由 `value` 数组长度决定，`minStepsBetweenThumbs={0}`（允许上下限相等，radix 自身不允许交叉）。
2. 取值：Root `relative flex h-8 w-full min-w-[120px] items-center touch-none select-none`；Track `h-1 rounded-full bg-fill-hover`（gray-3）；Range `bg-blue-500`（已重定向 `--brand-*`）；Thumb `block size-4 rounded-full border-2 border-blue-500 bg-bg-page transition-transform duration-150 hover:scale-[1.125] data-[dragging]:scale-[1.125] cursor-grab data-[dragging]:cursor-grabbing focus-visible:outline-none focus-visible:shadow-focus`——radix Thumb 没有拖动态属性，`data-dragging` 由组件在 pointerdown / pointerup 上自己挂摘（气泡跟随也读它）。禁用：Range 改 `bg-fill-active`、Thumb 改 `border-border-deep`（两者同为 gray-4），`cursor-not-allowed`。
3. 刻度：`marks: Record<number, ReactNode>` + `snapToMarks?: boolean`（true 时 `step` 失效、松手吸附最近刻度）；刻度点 `size-2 rounded-full border-2 bg-bg-page`，未覆盖 `border-border-base`、已覆盖 `border-blue-500`；标签 `text-caption text-text-3`，两端标签分别 `left-0` / `right-0` 对齐不居中。
4. 数值显示：`valueDisplay: 'input' | 'tooltip'`（二选一，默认 `tooltip`）。`input` 内置 `@bisheng/ui` 的 InputNumber，固定 `size="small"`（不开放覆盖），外包 `h-8 items-center` 与滑块行居中，`gap-4`；范围模式左右各一个。`tooltip` 复用 `@bisheng/ui` 的 Tooltip，`open` 受控 = hover ∨ dragging ∨ focus-visible，`side="top"`，`formatValue?: (v) => ReactNode` 同时供气泡与刻度标签使用。
5. 交互：`onValueChange` 拖动中实时触发，`onValueCommit`（radix 原生，pointerup / keyup）做保存；文档与 demo 都要写明「请求放 onValueCommit」。Shift + 方向键 10 步、PageUp / PageDown、Home / End 均为 radix 1.4 自带（已核对源码），无需自补。不监听 wheel。
6. 触屏：Thumb `::before` 伪元素 `inset: -16px`（16px 是 border-box，伪元素按 12px 的 padding box 定位，12 + 32 = 44px），写进 `packages/ui/src/styles/tokens.css` 一处（`.slider-thumb-hit` / `.slider-track-hit`），与 `.btn-touch-hit` 同口径；Track 上下各扩 20px 透明点击区。
7. 现状（2026-10-21 扫描，口径：`client/src` 的 *.tsx，grep `<Slider`）：旧 `client/src/components/ui/Slider.tsx`（radix，轨道 `h-2` 8px `bg-secondary`、滑块 20px `border-primary`，shadcn 旧 token），27 处 / 9 文件，几乎全是设置面板里与旧 `ui/InputNumber` 并排的用法（`Endpoints/Settings/*` 4 个、`SidePanel/Parameters/DynamicSlider`、`Nav/SettingsTabs/Speech/*` 3 个、`Nav/SettingsTabs/Account/Avatar`）——**宜与 InputNumber 同批迁移**；另 `client/src/components/ui/ModelParameters.tsx:148` 1 处原生 `type="range"`。旧壳支持 `onDoubleClick`（PlaybackRate 用双击恢复默认值），规范未收，见待决策清单。迁移批次照总纲节奏，设计师点名后再动。

## 待决策清单

- 双击滑块恢复默认值：现有「播放速度」在用，是否收进规范（需要可发现的提示，否则没人知道能双击）。
- 只读态：v1 未做；若出现「展示一个不可改的区间值」场景，再议是只读滑块还是改用文字 / 进度条。
- 竖向、整段拖动平移、非线性刻度（如 0～10 占一半轨道）：设计师 2026-10-21 明确 v1 不做，出现场景再议。
- 聚焦环沿用输入框灰环（gray-2）：白底滑块外的浅灰环在白页面上辨识度偏低，与 [组件-Checkbox复选框.md](组件-Checkbox复选框.md) 待决策「选择类组件是否改品牌淡环」一并议。

## 改动记录

| 日期 | 改了什么 | 提交 |
|---|---|---|
| 2026-10-21 | 建档 v1：设计师拍板四项（单值 + 范围 + 刻度标签；数值显示并排数字框 / 气泡二选一；滑块白底品牌色描边环；单档尺寸轨道 4px、滑块 16px→悬停 18px）；配套定范围不交叉、只能停在刻度上的吸附、点击轨道就近移动、键盘 Shift 10 步与 Home / End、滚轮不改值、拖动实时预览松手生效、并排数字框越界时滑块停在最后合法值、触屏 44px 热区、深浅色走 token；现状扫描旧 radix 壳 27 处 / 9 文件存档于落地区 7 | 待 committer 窗口提交 |
| 2026-10-21 | 落地 `@bisheng/ui` Slider：数值 API 为 `number \| [number, number]`；`snapToMarks` 拖动中自由移动、`onValueChange` 只报刻度值、松手吸附，键盘一次跳一个刻度；`valueDisplay="input"` 的数字框经 `inputProps` 传单位 / 文案；落地区 5、6 按实际核对修正（Shift 10 步 radix 自带、拇指热区 inset 为 -16px） | 未提交 |
| 2026-10-21 | 设计师调整：与滑块并用的数字框固定 small 档（24px），与滑块行垂直居中；§5 表、§5.1、落地区 4 同步 | 未提交 |
