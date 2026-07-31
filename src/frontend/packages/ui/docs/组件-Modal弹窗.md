# 组件改造 · Modal 弹窗

> 状态：🟨 进行中 · 优先级最高（第 1 个改造的组件）
> 本文以现状梳理与收敛台账为主，弹窗的视觉标准多数仍在等设计师拍板，未定项集中列在 §4。已随其它规范定下的部分见 §3。
> 接手本组件前先读 [00-总纲.md](00-总纲.md)。配套：圆角与投影见 [基础-圆角与阴影规范.mdx](基础-圆角与阴影规范.mdx)、按钮见 [组件-Button按钮.md](组件-Button按钮.md)、颜色见 [基础-色彩规范.mdx](基础-色彩规范.mdx)、移动端通则见 [基础-多端适配原则.md](基础-多端适配原则.md)。二次确认弹窗是弹窗的专用子类，已独立成文，见 [组件-Confirm二次确认.md](组件-Confirm二次确认.md)。
> 用量台账、迁移记录、代码锚点等实现细节走文末隐藏区。2026-07-30 对照《元-文档撰写规范》重排：阿拉伯编号、正文/隐藏区分层、同步已定的 16px 圆角与模态投影；设计决策一项未替设计师拍板。

## 1. 这是什么、现在什么状态

弹窗是**打断式的浮层**——盖在页面之上，要求用户先处理完（确认、填表、看提示）才能回到下面的内容。

BISHENG 现在的问题是**同样是弹窗、却有好几套并行**，遮罩深浅、圆角、层级各不相同，看起来不像一个产品。本文的任务就是把它们收敛成一套标准。

<!-- site-hide:start -->
目前进度：

- **「二次确认」这一子类已基本收敛**到一处实现（一套样式、改一处全生效），它的规范已独立成文，见 [组件-Confirm二次确认.md](组件-Confirm二次确认.md)。
- **其余弹窗（表单弹窗、提示弹窗等）的视觉标准还在等设计师定**，未定项见 §4。
- **圆角与投影已随《圆角与阴影规范》定下**（弹窗 16px 圆角 + 模态投影档），见 §3。

<!-- site-hide:end -->

## 2. 什么时候用弹窗

- **需要打断用户、让他当场做个决定或完成一小段任务时，用弹窗**：删除确认、快速表单、重要提示。
- **能不打断就不打断**。信息能在页面里就地展示的，用行内区域、抽屉或气泡，别动辄弹窗——每个弹窗都是一次强制打断。
- **一次只开一个弹窗**。弹窗套弹窗会让用户迷路，也说不清关掉一层会回到哪。
- **破坏性、不可逆的操作要配二次确认**（删除、移交、清空），见 [组件-Confirm二次确认.md](组件-Confirm二次确认.md)。

## 3. 已随基础规范定下的项

下面两项已在《圆角与阴影规范》定稿，弹窗直接遵循，不再单列待决策：

- **圆角 16px**：所有弹窗统一 16px（容器档 `2xl`）。见 [基础-圆角与阴影规范.mdx](基础-圆角与阴影规范.mdx)。
- **模态投影**：弹窗、抽屉用「模态投影」档（大而弥散、浮得最高），可搭配 1px 浅色边框。见 [基础-圆角与阴影规范.mdx](基础-圆角与阴影规范.mdx)。

## 4. 尚未拍板的点（等设计师定）

除二次确认子类外，下面这些是普通弹窗要统一、但**尚未拍板**的点。设计师定了哪一项，就把它从这里移走、写成正式规范。

- [ ] **遮罩**：现在是「浅黑毛玻璃」（A 套 `bg-black/40` + 模糊）和「灰白毛玻璃」（B/C 套 `bg-gray-500/90` + 模糊）二选一——定一套，全局统一。
- [ ] **内边距**：header / body / footer 各多少？现有 20px（`p-5`）与 24px（`p-6`）并存，二次确认先例是 20px。
- [ ] **标题**：字号与字重？现有 `text-base` 下 `font-semibold` 与 `font-medium` 并存。
- [ ] **关闭按钮**：普通弹窗是否保留右上角「×」，样式与位置如何？
- [ ] **footer 按钮**：直接用 Button 组件，还是沿用二次确认那对按钮？间距多少？（按钮排序可对齐 [组件-Button按钮.md](组件-Button按钮.md) 的 footer 规则：主按钮最右、危险场景主位放危险红实心。）
- [ ] **层级 z-index**：现有 `z-50` / `z-[100]` / `z-[110]` 三档并存，统一时需连 Drawer / Sheet / Popover 的叠放关系一起盘。
- [ ] **原语收敛方向**：A 套原语直拼是最大人群（约 22 处），是「把 A 套壳改成标准、业务零改动」，还是「逐批迁到 B 套」？

<!-- site-hide -->
## 5. 现状与用量台账（给实现窗口）

> 以下为迁移排批次、估工作量用的现状数据，不进展示层。数字带扫描口径与日期，过时以最新一次重盘为准。

### 5.1 两套并行的弹窗体系（乱的根源）

BISHENG client 有两套弹窗，都包着同一个 Radix `@radix-ui/react-dialog`，但样式不同：

- **A 套（标准弹窗原语）**：原语 `src/components/ui/Dialog.tsx`、模板 `DialogTemplate.tsx`；遮罩 `bg-black/40` 半透明 + `backdrop-blur-md` 毛玻璃；层级 `z-[100]`。
- **B 套（「Original」原语，OG 前缀）**：原语 `src/components/ui/OriginalDialog.tsx`（导出 `OGDialogContent` 等）、模板 `OGDialogTemplate.tsx`（用得最多）；遮罩原为 `bg-black/80` 更黑无模糊（二次确认期已对齐灰白毛玻璃）；层级 `z-50`。

| 维度 | A 套（Dialog） | B 套（OriginalDialog / OG） |
|---|---|---|
| 遮罩颜色 | `bg-black/40`（浅） | `bg-gray-500/90`（已对齐 C 套；原 `bg-black/80`） |
| 毛玻璃模糊 | 有 `backdrop-blur-md` | 二次确认期已加 |
| 层级 z-index | `z-[100]` | `z-50` |
| 便捷模板 | DialogTemplate | OGDialogTemplate |

### 5.2 Modal 期用量重盘（2026-07-09 扫描，最新，§5.1 旧数字以此为准）

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

- A 套：遮罩 `bg-black/40` + blur、`z-[100]`、`sm:rounded-lg`（8px 移动端直角）、`p-5`、border + `shadow-lg`、标题 `text-base font-semibold`、暗色底 `dark:bg-[#303134]` 写死。
- B 套（已对齐 C 套）：遮罩 `bg-gray-500/90` + blur、`z-50`、`rounded-2xl`（16px）、`p-5`、border `#ebebeb` + 淡投影、标题 `text-base font-medium`、`bg-background` 跟主题。
- AlertDialog 底座：遮罩同 B、`z-[110]`、`sm:rounded-lg`、`p-6`、无边框无阴影、无内置关闭钮、移动端从底部滑入贴底。
- 层级三档并存：`z-50` / `z-[100]` / `z-[110]`，统一时需盘 Drawer / Sheet / Popover 关系。

### 5.3 死代码线索

- `OriginalDialog` 已确认**不是**死代码（被 OGDialogTemplate 内部 import）。
- SidePanel 死树：`SidePanelGroup.tsx:117-132` 整段被注释、面板不渲染，牵连约 5 处弹窗（书签删除 + 删 Agent / Agent 工具 / 删 Assistant / Assistant 工具）为死 UI，随死代码清理处置，不迁。
- default 变体挂 `btn-brand-primary` 类的换肤 hack 与 Modal 无关，另见按钮文档。

## 改动记录

| 日期 | 改了什么 | 影响文件 | 提交 |
|---|---|---|---|
| — | 尚未改动组件源码，当前为现状梳理 + 画廊搭建 | — | — |
| 2026-07-09 | **Modal 期开工**：全站弹窗重盘（5 体系 64 文件，见 §5.2；A 套原语直拼 22 处为最大人群）；画廊 Modal 版块整体重做。未改组件源码，等设计师定标准 | `_gallery/sections/ModalSection.tsx`（重写） | 待 committer 窗口提交 |
| 2026-07-10 | **反馈弹窗抽成共享组件 `ui/CommentDialog`**（标题 + textarea + 取消 / 提交；header/body/footer 各 `px-5`、移动端等宽、每次打开重置草稿、可选异步提交）。MessageFeedbackButtons 改为消费方；MenuUnavailablePage 手写申请权限弹窗迁入——手拼弹窗 -1，新增 ESC / 遮罩 / 焦点圈定 | `ui/CommentDialog.tsx`（新）、`ui/index.ts`、`Chat/MessageFeedbackButtons.tsx`、`pages/MenuUnavailablePage.tsx` | 待提交 |
| 2026-07-30 | **对照《元-文档撰写规范》重排**：汉字编号→阿拉伯；正文分层——可读规范留展示层，用量 / 迁移台账 / 代码锚点下沉隐藏区；同步《圆角与阴影规范》已定的弹窗 16px 圆角 + 模态投影，待决策清单删去「圆角用几 px」一项；引号统一「」、去手写分隔线；修正兄弟文档指向本文旧章节号的引用。**未替设计师拍板任何未定项。** | 本文件、01-设计规范.md、00-总纲.md | 待 committer 窗口提交 |
| 2026-07-30 | **二次确认拆分为独立规范** [组件-Confirm二次确认.md](组件-Confirm二次确认.md)：原 §3 二次确认规范正文与 §7 迁移台账整体迁出，本文仅在 §2 与 §1 留指针；二次确认相关的改动记录与代码锚点一并移入新文档。随之 §4 已定项→§3、§5 尚未拍板→§4、§6 现状台账→§5 顺次上移。 | 本文件、组件-Confirm二次确认.md（新）、00-总纲.md | 待 committer 窗口提交 |

## 代码锚点

- A 套原语：`src/frontend/client/src/components/ui/Dialog.tsx`
- A 套模板：`src/frontend/client/src/components/ui/DialogTemplate.tsx`
- B 套原语：`src/frontend/client/src/components/ui/OriginalDialog.tsx`
- B 套模板：`src/frontend/client/src/components/ui/OGDialogTemplate.tsx`
- 反馈共享壳：`src/frontend/client/src/components/ui/CommentDialog.tsx`
- 画廊 Modal 版块：`src/frontend/client/src/pages/_gallery/sections/ModalSection.tsx`
- 实时预览页：`src/frontend/packages/ui/docs/components/modal.mdx`
