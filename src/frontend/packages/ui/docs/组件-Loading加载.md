# 加载 Loading

> 设计系统 · 加载 v1 · 2026-08-28 建档
> 与 [00-总纲.md](00-总纲.md)、[01-设计规范.md](01-设计规范.md) 配套；颜色见 [基础-色彩规范.mdx](基础-色彩规范.mdx)、字号见 [基础-字体规范.mdx](基础-字体规范.mdx)、图标见 [基础-图标规范.mdx](基础-图标规范.mdx)、插画见 [基础-插画规范.md](基础-插画规范.md)、文案见 [基础-文案规范.md](基础-文案规范.md)。姊妹篇：[组件-State状态页.md](组件-State状态页.md)（加载失败的整块区域反馈归那边 §2.2）、[组件-Button按钮.md](组件-Button按钮.md)（按钮内 loading 归那边 §6）。
> 调研来源（不进展示层）：antd Spin（small / default / large 三档 14 / 20 / 32，`delay` 防闪，可包裹内容加遮罩，`fullscreen`，`description`）、Arco Spin（默认 20，`delay`、`dot`、`block`、包裹遮罩）、TDesign Loading（16 / 20 / 24 三档，`delay`、`text`、`fullscreen`、`attach`）、Apple HIG progress indicators（指示器持续在动、位置固定、说明文字讲清在等什么、小型 activity indicator 不配文字）、Carbon loading pattern（骨架屏只给容器与数据组件，加载指示器分全屏 / 内联两级）。Spin 类组件都不管失败；「加载更多」三态（加载中 / 失败重试 / 没有更多）是 antd List、Arco List 的做法。
> 设计师拍板（2026-08-28）：本期收**区域加载 + 列表尾部加载**两种形态，骨架屏不在本期；图形**两档分工**——区域用品牌 12 齿 spinner、列表尾部用 16px 单色圆环；失败**分两级**——区域失败走《状态页》服务异常，列表尾部失败一行「加载失败，点击重试」；延迟**区域 300ms、列表尾部不延迟**。
> 代码现状（2026-08-28 只读扫描，client/src）：区域首屏加载 5 处写法一致（`LoadingIcon` 80px + 「正在加载…」14px text-3）；列表尾部两套并存——`components/InfiniteScroll.tsx`（lucide `Loader2` 16px + 14px text-3，末尾 `text-gray-300`）与 ChannelSquare / KnowledgeSquare / SpaceDetail `LoadMore`（40px 高、纯文字 12px text-4 三态，无 spinner、失败不可重试）；explore 页一处裸 hex `#a9aeb8`。区域失败只有一行「加载失败」，无插画无重试。映射见给实现窗口。

## 1. 什么时候用

加载告诉用户「东西在路上，等一下」。它只回答「在不在等」，不回答「等到了几成」——BISHENG 的接口没有进度可报，不做进度条。

- 一块区域第一次拿数据、或切换来源重新拿数据，用**区域加载**（§2.1）。
- 列表往下滚要拿下一页，用**列表尾部加载**（§2.2）。
- 点了按钮在等接口，用按钮自己的 loading 态，见 [组件-Button按钮.md](组件-Button按钮.md) §6；拨了开关在等确认，见 [组件-Switch开关.md](组件-Switch开关.md) §4。**别在按钮旁边另放一个 spinner**。
- 拿回来是零条，换状态页，见 [组件-State状态页.md](组件-State状态页.md) §1——**加载中不是状态页，状态页也不是加载中**。
- 整块区域打不开（首屏请求失败），走状态页的服务异常，不在这里画。

| ✅ 推荐 | ❌ 不推荐 | 原因 |
|---|---|---|
| 请求期间显示加载，回来零条再换「暂无数据」 | 请求期间就显示「暂无数据」 | 数据明明在路上，先说「没有」再闪回来，用户会以为坏了 |
| 一块区域同一时刻只有一个加载指示 | 区域 spinner 和列表尾部 spinner 同时转 | 两个在转等于没告诉用户到底在等什么 |

## 2. 类型 Type

两种形态，按「等的是整块区域还是下一页」选。

### 2.1 区域加载

整块区域还没有内容，spinner 在区域正中，下面一行说明文字。

- 图形用**品牌 spinner**（12 齿，跟品牌色走，客户可用自己的 logo 动画替换），尺寸随容器分档（§3）。
- 说明文字必带，写「正在加载…」或更具体的「正在加载文件…」；位置在 spinner 下方，间距 16px。
- 区域内已有内容、只是要刷新时（切换筛选、切换来源），**保留旧内容 + 上方盖 spinner**：旧内容降到 40% 不透明、不可点，spinner 居中。整块清空再转会让页面跳一下。
- 整页级（应用启动、路由切换）也是区域加载，容器就是视口。

### 2.2 列表尾部加载

列表滚到底自动拿下一页，尾部一条 40px 高的状态行，四态见 §5。

- 图形用 **16px 单色圆环**（图标规范的 `Outlined.Loading`），颜色 text-3，左侧带文字「正在加载…」，间距 8px。
- 自动触发：状态行进入视口（提前 200px）就发请求，用户不用点。
- 状态行在列表末尾、跨满整行（网格布局也跨满所有列），水平居中。

| ✅ 推荐 | ❌ 不推荐 | 原因 |
|---|---|---|
| 下一页在路上时列表不动，尾部一行小 spinner | 下一页在路上时整个列表换成大 spinner | 已经在看的内容被换掉，用户找不回刚才的位置 |
| 列表尾部用灰色小圆环 | 列表尾部也用品牌大 spinner | 尾部行是配角，品牌色会把视线从内容上拉走 |

## 3. 尺寸 Size

区域加载的 spinner 按容器分三档，**看容器有多大，不看在等什么**（口径同 [组件-State状态页.md](组件-State状态页.md) §3）。列表尾部固定一档。

| 档位 | spinner | 说明文字 | 用在哪 |
|---|---|---|---|
| **页面级** | 80px | `text-body`（14/22）text-3 | 整块内容区、页面主体、视口 |
| **面板级** | 40px | `text-body`（14/22）text-3 | 卡片内、侧栏、抽屉与弹窗主体、AI dock |
| **内联级** | 16px | `text-body`（14/22）text-3，无文字也可 | 表格单元格、行内、下拉面板；列表尾部固定此档 |

- 内联级用单色圆环，不用品牌 spinner——16px 的 12 齿糊成一团。
- 说明文字与 spinner 的间距：页面级 / 面板级上下排 16px，内联级左右排 8px。
- 一个容器里只出现一档。

## 4. 内容形态

- 说明文字只写「在等什么」，不写「请稍候」「请耐心等待」——用户已经在等了。
- 用「正在 + 动词 + 宾语」：「正在加载…」「正在加载文件…」「正在生成…」，末尾统一用省略号「…」（一个字符），不用三个句点「...」。写法跟《文案规范》。
- 内联级可以不带文字：按钮内、开关内、表格单元格这些位置本身就说明了在等什么。
- 加载不带取消按钮：能取消的是「生成」「上传」这类任务，它们各自的组件负责取消。
- 加载超过 10 秒仍没回来，说明文字不变、spinner 不停——**指示器一停，用户就认为卡死了**。

| ✅ 推荐 | ❌ 不推荐 | 原因 |
|---|---|---|
| 「正在加载文件…」 | 「Loading...」「请耐心等待」 | 前者说了在等什么；英文和「耐心」都是在让用户自己猜 |
| spinner 一直转到结果回来 | 超时后 spinner 停住不动 | 停住的 spinner 和死机没有区别 |

## 5. 状态 State

区域加载三态：加载中、加载完成、加载失败。列表尾部多一态——**全部加载完成**：下一页拿回来是空的，告诉用户「到底了」，别再往下滚。

| 状态 | 区域加载 | 列表尾部加载 |
|---|---|---|
| **加载中** | 品牌 spinner + 「正在加载…」；刷新时旧内容 40% 不透明 | 16px 圆环 + 「正在加载…」，`text-body` text-3 |
| **加载完成** | 内容出现，spinner 消失；零条换状态页 | 新一页接在列表后面，状态行留空、等下一次滚到底再触发 |
| **全部加载完成** | — | 一行「已展示全部内容」，`text-caption`（12/20）text-4，不可点、不再触发请求 |
| **加载失败** | 整块换状态页服务异常（插画 + 「加载失败，请刷新重试」+ 重试按钮），见 [组件-State状态页.md](组件-State状态页.md) §2.2 | 一行「加载失败，点击重试」，`text-body` text-3，整行可点；点击原地重新请求，行内切回加载中 |

- **区域加载延迟 300ms 出现**：300ms 内回来的请求不显示 spinner，省掉一次闪烁。列表尾部**不延迟**——状态行本来就在视口外，滚进来才看得见。
- 加载中至少停留 300ms 再切走：刚出现就消失的 spinner 也是闪烁。
- 列表尾部失败**不弹轻提示**：失败信息就在用户正在看的位置，再弹一条是重复。失败行悬停变 text-1，触屏无悬停。
- 「已展示全部内容」只要列表有内容就显示，**内容不足一屏、从没触发过加载更多也显示**（设计师 2026-08-28 定）——它是这张列表的句号，不看滚没滚过。零条走状态页。它比加载中和失败行小一号、浅一档（12px text-4）——这是一句「可以不看了」，不该比内容还显眼。
- 请求发出去了再切换来源，旧请求的结果**丢弃**，不允许旧数据盖住新数据。

| ✅ 推荐 | ❌ 不推荐 | 原因 |
|---|---|---|
| 尾部失败：「加载失败，点击重试」整行可点 | 尾部失败：只写「加载失败」 | 用户不知道还能不能往下看，只能刷新整页重来 |
| 首屏失败换状态页给重试按钮 | 首屏失败居中一行「加载失败」 | 一行灰字撑不起整块区域，也没告诉用户下一步 |

## 6. 动效

- 品牌 spinner 与圆环都是匀速旋转，一圈 1s，线性、不缓动——缓动会让转速看起来忽快忽慢。
- 出现与消失都用 0.2s 淡入淡出，不做缩放。
- 刷新时旧内容降到 40% 不透明的过渡 0.2s。
- 系统开启「减弱动态效果」时，spinner 改为不透明度 40%⇄100% 的呼吸，不旋转。

## 7. 移动端适配

跨组件通则见 [基础-多端适配原则.md](基础-多端适配原则.md)，这里只写加载自己的细则。

| 项 | 触屏 / 窄屏规则 |
|---|---|
| 尺寸 | 不变；视口高度不足 480px 时页面级降为面板级 40px |
| 列表尾部失败行 | 热区整行、高度 44px（40px 行 + 上下各 2px 透明热区），同按钮口径 |
| 悬停 hover | 触屏没有悬停，关掉失败行的 hover 态 |
| 下拉刷新 | 本期不做；顶部刷新仍用区域加载的「旧内容 40% + spinner」 |

## 8. 无障碍

- 加载中的区域标 `aria-busy="true"`，spinner 标 `role="status"` + 说明文字作为可读文本；内联级没有文字时给 `aria-label="正在加载"`。
- 列表尾部的失败行是按钮（`<button>`），键盘可达、Enter / Space 触发重试。
- 状态切换（加载中 → 失败 / 全部加载完）用 `aria-live="polite"` 播报，不用 assertive——加载不是紧急事件。

<!-- site-hide -->
## 给实现窗口

1. 组件位置 `packages/ui/src/components/Loading/`，导出两个：`Loading`（区域加载）与 `LoadMore`（列表尾部）。
   - `Loading`：`size: page | panel | inline`（80 / 40 / 16）、`text?: string`（内联级可空）、`delay?: number`（默认 300，内联默认 0）、`spinning?: boolean`（包裹模式，`children` 存在时旧内容 `opacity-40 pointer-events-none`）、`minDuration` 固定 300ms 不暴露。page / panel 渲染品牌 spinner（复用 client `ui/icon/Loading` 的 `LoadingIcon` 逻辑：BRAND_CONFIG 自定义 → `<img>`，否则内联 12 齿 SVG + `bs-tick-spinner` 遮罩动画，`text-primary`）；inline 渲染 `Outlined.Loading` + `animate-spin`，`text-text-3`。
   - `LoadMore`：`status: idle | loading | error | done`、`onLoad`、`onRetry`、`loadingText` / `errorText` / `doneText`（文案由调用方传，组件库不含文案）、`rootMargin`（默认 `200px`）。自带 IntersectionObserver 哨兵，root 取最近的可滚祖先（沿用 `SpaceDetail/LoadMore.tsx` 的 `findScrollableAncestor`，不能只看 viewport）；`status === 'loading' | 'done' | 'error'` 时不触发 `onLoad`。error 渲染 `<button class="h-10 w-full text-body text-text-3 hover:text-text-1">`，done 渲染 `<div class="h-10 text-caption text-text-4">`，容器加 `col-span-full`。
2. 颜色全走 token：文字 `text-text-3` / `text-text-4` / hover `text-text-1`，品牌 spinner `text-primary`，遮罩用 `opacity-40` 不加底色；不写裸 hex（explore 页 `#a9aeb8` 收编为 `text-text-4`）。
3. 动效：旋转 `animate-spin`（1s linear infinite）；淡入淡出 `transition-opacity duration-200`；`motion-reduce:` 前缀下改 `animate-pulse`（opacity 呼吸）并去掉旋转。
4. 无障碍按 §8：区域容器 `aria-busy`，spinner `role="status"`，LoadMore 状态行 `aria-live="polite"`。
5. 迁移映射（2026-08-28 只读扫描，范围 `client/src`，排除 node_modules）：
   - `components/InfiniteScroll.tsx`（ArticleList、ChannelPreviewDrawer 共 2 处引用）→ `LoadMore`；lucide `Loader2` → `Outlined.Loading`；末尾 `text-gray-300` → `text-text-4`；`emptyText` 语义即 `doneText`。
   - `pages/knowledge/SpaceDetail/LoadMore.tsx`（1 处引用）→ 库内 `LoadMore`，删除页面私有版本；SpaceDetail 的 `listBottomStatus` 三元分支收成 `status` 一个入参。
   - `pages/ChannelSquare.tsx`、`pages/knowledge/KnowledgeSquare.tsx`、`pages/apps/index.tsx`、`pages/apps/explore.tsx` 尾部手拼三态（`loadingMore ? … : loadMoreError ? … : !hasMorePage ? …`）→ `LoadMore`，失败态由此获得重试。
   - 区域首屏 5 处（ChannelSquare / KnowledgeSquare / SpaceDetail / apps index / apps explore）`LoadingIcon size-20 + span` → `<Loading size="page" text=… />`；同处的 `initialError` 一行「加载失败」→ 状态页服务异常（`StateView` 的 SystemMaintenance + 重试按钮），此项属状态页迁移，本组件只留指针。
   - `components/messageApproval/NotificationPane.tsx`、`components/permission/SubjectSearchUser.tsx`、`components/Chat/Input/KnowledgeListPanel.tsx` 各有一套滚动加载（onScroll 距底 10px 触发），**待迁**，迁时同样收成 `LoadMore`。
   - 其余 58 处 `animate-spin` 未逐一扫描（含按钮内、文件预览等），迁移窗口用 `animate-spin` grep 后补附录；按钮内的归《Button》，不动。
6. 站点接线（元规范 §5）：本文注册进 `rspress.config.ts` 侧栏 `/` 分组；demo 页 `components/loading.mdx` 待组件落地后建，front matter `component: Loading`；00-总纲 §四 与 01-设计规范 §0 索引行随建档更新。

## 待决策清单

- 骨架屏 Skeleton 不在本期：何时用骨架、何时用 spinner、请求多久没回来才显示骨架——等有第二个真实骨架场景再立文档（现 `ui/Skeleton.tsx` 8 处引用沿用）。本文只划清「加载中不用状态页」的边界，与《状态页》§11 那条对应。
- 面板级 40px 为本次建档取值（介于页面级 80 与内联 16 之间、与列表尾部行高同值），未在真实卡片 / 抽屉里目检，待验收。
- 区域刷新的「旧内容 40% 不透明」与《Modal 弹窗》遮罩黑 40% 数值相同但机制不同（这里是内容自身降透明、不加遮罩层），若在深色模式下对比不够再议加 fill 底。
- 列表尾部失败是否在连续失败 3 次后改成「请稍后重试」并停止自动触发：本次不做限制，每次点击都重试。

## 改动记录

| 日期 | 改了什么 | 提交 |
|---|---|---|
| 2026-08-28 | §2.2 / §5：列表尾部由三态改四态，「全部加载完成（已展示全部内容）」从加载完成里拆出来单列一行（设计师指出）；「内容不足一屏也显示」由待决策转为 §5 规则（设计师定）；数值与文案未改 | 待 committer 窗口提交 |
| 2026-08-28 | 建档 v1：先调研 antd / Arco / TDesign / Apple HIG / Carbon，设计师拍板四项——范围收区域加载 + 列表尾部加载（骨架屏不做）、图形两档分工（区域品牌 12 齿 spinner、列表尾部 16px 圆环）、失败分两级（区域走状态页服务异常、尾部一行可点重试）、延迟区域 300ms / 尾部 0。展示层 8 节：两形态、尺寸三档 80/40/16 看容器、文案「正在 + 动词」、三态表、动效 1s 线性 + 0.2s 淡入淡出 + 减弱动态改呼吸、移动端失败行 44px 热区、无障碍 aria-busy / status / polite。隐藏区：`Loading` + `LoadMore` 两个导出的 API、client 两套尾部加载与 5 处首屏加载的迁移映射 | 待 committer 窗口提交 |
