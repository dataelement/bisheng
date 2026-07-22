# 组件改造 · Modal 弹窗

> 状态：🟨 进行中 · 优先级：最高（第 1 个改造的组件）
> 每个新会话接手本组件前，先读 [00-总纲.md](00-总纲.md) 再读本文件。

---

## 一、现状：两套并行的弹窗体系（乱的根源）

BISHENG client 有 **两套**弹窗，都包着同一个 Radix `@radix-ui/react-dialog`，但样式不同：

### A 套 —— 标准弹窗原语
- 底层原语：`src/components/ui/Dialog.tsx`（`Dialog` / `DialogContent` / `DialogHeader` / `DialogFooter` …）
- 便捷模板：`src/components/ui/DialogTemplate.tsx`
- 遮罩：`bg-black/40` **半透明 + `backdrop-blur-md` 毛玻璃模糊**
- 层级：`z-[100]`

### B 套 —— "Original" 原语（OG 前缀）
- 底层原语：`src/components/ui/OriginalDialog.tsx`（导出 `OGDialogContent` / `OGDialogHeader` …）
- 便捷模板：`src/components/ui/OGDialogTemplate.tsx` ← **用得最多**
- 遮罩：`bg-black/80` **更黑、无模糊**
- 层级：`z-50`

### 差异一览（这就是「同样是弹窗却不一致」的证据）
| 维度 | A 套 (Dialog) | B 套 (OriginalDialog / OG) |
|---|---|---|
| 遮罩颜色 | `bg-black/40`（浅） | `bg-black/80`（深） |
| 毛玻璃模糊 | 有 `backdrop-blur-md` | 无 |
| 层级 z-index | `z-[100]` | `z-50` |
| 便捷模板 | DialogTemplate | OGDialogTemplate |

---

<!-- site-hide -->
## 二、各版本用量（供收敛决策）

> 精确统计（词边界，排除 ui/ 自身与画廊）：

| 组件 | 业务文件数 | 处置建议 |
|---|---|---|
| `OGDialogTemplate`（B 套模板） | **25** | **收敛基准**（用得最多） |
| `DialogTemplate`（A 套模板） | **3** | 迁移到基准后删除 |
| `OriginalDialog`（B 套原语） | 仅被 OGDialogTemplate 内部 import | B 套私有底层，**保留**（非死代码） |
| `Dialog`（A 套原语，含 barrel 直接用） | 若干（多为 barrel 引入，按需迁移） | 保留为底层原语 or 合并 |

**死代码线索**：早前扫描 `Combobox` = 0 业务引用（与 Modal 无关，另行清理）。
`OriginalDialog` 已确认**不是**死代码。

### 已知使用 OGDialogTemplate 的业务文件（25 处，节选）
Bookmarks/BookmarkEditDialog · Bookmarks/DeleteBookmarkButton · Chat/Input/Files/DragDropModal ·
Conversations/ConvoOptions/{DeleteButton,ShareButton,SharedLinkButton} · Endpoints/SaveAsPresetDialog ·
Input/SetKeyDialog/SetKeyDialog · Nav/ExportConversation/ExportModal ·
Nav/SettingsTabs/Data/{ClearChats,DeleteCache,RevokeKeysButton,SharedLinks} ·
Nav/SettingsTabs/General/ArchivedChats · Prompts/{AdminSettings,DeleteVersion} ·
Prompts/Groups/DashGroupItem · SidePanel/Agents/{ActionsPanel,AgentTool,Code/ApiKeyDialog,DeleteButton} ·
SidePanel/Builder/{ActionsPanel,AssistantTool} · pages/appChat/components/AppSidebarConvoItem ·
pages/standaloneChat/components/GuestConvoItem

---

<!-- site-hide -->
## 二点五、二次确认弹窗现状（2026-07-02 扫描，本窗口专项）

> 画廊已建独立版块：`/workspace/gallery` → 左侧「二次确认弹窗」。
> **重要发现：二次确认是两套体系并行**：

| 体系 | 实现 | 业务文件数 | 用在哪 | 样式一致性 |
|---|---|---|---|---|
| B 套模板 | `OGDialogTemplate` + `selection` | 21 | 旧页面：会话/书签/Agent/设置/Prompt（LibreChat 血统） | 差：确认按钮 9 种写法（见下表） |
| **C 套服务** | `useConfirm()`（`Providers/ConfirmContext.tsx`，底层 AlertDialog） | 16 | 新页面：知识空间 / 订阅频道 / 权限 | **好：样式集中一处，destructive/default 两档，改一处全生效** |

> ⚠️ 范围口径（设计师 2026-07-02 拍板）：另有 9 个文件直接手拼 `AlertDialog`（频道成员/知识空间成员/爬取反馈与预览/灵思 TaskModeInput 等），**属于普通弹窗、归 Modal 弹窗改造范围，本期二次确认不动**。其中个别（如 ChannelMemberDialog 的移除成员、红 `#F53F3F` 按钮）带确认性质，留待 Modal 期一并处理。

- C 套即设计师截图那个「红垃圾桶图标 + 红标题 + 暂不/确认删除」的弹窗（知识空间删除）。
- C 套外观：居中卡片 `rounded-[20px] p-6 max-w-[400px]`、图标+标题一行、按钮右对齐（移动端等宽平铺）、危险=红 `#f53f3f`（语义色不换肤）、普通=品牌主色。**它是收敛基准的天然候选。**
- C 套 `useConfirm()` 的 16 个文件：knowledge（index、SpaceDetail/index、VersionHistorySheet、RelateDocumentPanel、SimilarDocumentDialog、CreateKnowledgeSpaceDrawer、sidebar 两个 CardItem/Item）、Subscription（ChannelItem、ChannelActionsMenu、CreateChannelDrawer、AddSourceDropdown、AiChat 三个面板）、permission/PermissionListTab。
- B 套 `selection` 的 21 个文件（`grep "selection={"`，排除 MoveToDialog 同名业务 prop 与 ExportModal 的 `selection={undefined}`）——按用户可见位置分组见下节。

### 确认按钮 selectClasses 的 9 种写法
| # | 写法 | 文件数 | 代表文件 |
|---|---|---|---|
| 1 | `bg-red-700 dark:bg-red-600 hover:bg-red-800 dark:hover:bg-red-800` | **8（最多）** | ConvoOptions/DeleteButton、Bookmarks、AgentTool、SharedLinks、AppSidebarConvoItem、GuestConvoItem… |
| 2 | `bg-red-600 hover:bg-red-700 dark:hover:bg-red-800` | 3 | Agents/DeleteButton、Builder/ContextButton、DashGroupItem（删） |
| 3 | `bg-red-600 hover:bg-red-700 dark:hover:bg-red-600` | 1 | PresetItems（清空） |
| 4 | `bg-destructive hover:bg-destructive/80` | 3 | ClearChats、DeleteCache、RevokeKeysButton |
| 5 | `bg-surface-destructive hover:bg-surface-destructive-hover` | 2 | DeleteVersion、AdminSettings |
| 6 | `bg-green-500 hover:bg-green-600`（确认=绿色） | 2 | SaveAsPresetDialog、ApiKeyDialog |
| 7 | `btn btn-primary`（全局 CSS 类） | 1 | SetKeyDialog |
| 8 | `bg-surface-submit hover:bg-surface-submit-hover` | 1 | DashGroupItem（重命名） |
| 9 | 不传 → 模板默认 `bg-gray-800 … dark:bg-gray-200` | — | OGDialogTemplate defaultSelect |

### 当前写死的解剖值（待设计师定稿后统一）
- 容器：`rounded-2xl p-6 gap-4 shadow-lg`（OriginalDialog.tsx）；遮罩 `bg-black/80` 无模糊
- 标题：`text-lg font-semibold`；正文区 `px-0 py-2`
- 确认按钮：`h-10 rounded-lg px-4 py-2 text-sm`（颜色全靠各页 selectClasses 传）
- 取消按钮：`btn btn-neutral rounded-lg text-sm` —— 走全局 CSS 类，**不是** Button 组件
- 宽度：`w-11/12` + 各页自带 `max-w-[450px]` / `max-w-lg`
- Loading 两种写法并存：`selection.isLoading`（模板内置 Spinner）vs 各页自己把 `<Spinner />` 塞进 `selectText`（ClearChats、DeleteCache、RevokeKeysButton、SharedLinks 共 4 处）

### 收敛方案（设计师 2026-07-03 拍板，四步走）
> 目标：全平台二次确认只剩 `useConfirm()` 一个组件、一处样式源。

1. **✅ B 套壳子对齐 C 套视觉**（已完成，见改动记录）：遮罩灰底毛玻璃、圆角 16、padding 20、标题 text-base、取消/确认按钮同 C 套；`selection` 增加 `selectVariant: 'danger' | 'primary'` cva 档位，历史 9 种 selectClasses 由模板自动折叠（`red-|destructive`→danger，`green-|btn-primary|surface-submit`→primary，未识别原样放行=特例口子），**21 个业务页零改动**。
2. **✅ C 套 `description` 扩展为 ReactNode**（已完成）：支持富文本正文（如加粗对象名），为迁移铺路。
### 剩余 9 处的入口地图（2026-07-03 三路代码探查结论）
| 功能 | 界面入口 | 门控 | 可达性 |
|---|---|---|---|
| 书签删除 DeleteBookmarkButton | **死 UI**：唯一渲染点是被注释 SidePanel 里的书签表格（BookmarkTableRow）；聊天页 Header 书签菜单只含编辑弹窗，不含此删除确认（主窗口人工复核纠正了探查报告的误判） | — | ❌ 不迁，随 SidePanel 死树清理 |
| 清空预设 PresetItems | 聊天页 Header → Presets 菜单 → Clear all | `interface.presets`（默认 true） | ✅ 可达 |
| 分享链接删除 SharedLinkButton | Header 导出/分享菜单 → 分享弹窗 | `sharedLinksEnabled`（默认 true） | ✅ 可达 |
| 分享链接管理 SharedLinks | 设置 → 数据 → 管理分享链接 | 无 | ✅ 可达 |
| 免登录会话删除 GuestConvoItem | 分享出去的独立工作流/助手聊天页 `/chat/flow/:flowId`（BISHENG 自有功能，含免登录与登录两种模式） | 无 | ✅ 可达（仅分享场景） |
| 删 Agent / Agent 工具 / 删 Assistant / Assistant 工具（4 处） | 右侧 SidePanel —— **`SidePanelGroup.tsx:117-132` 整段被注释，面板不渲染**（书签删除同属这棵死树，合计 5 处死 UI） | — | ❌ **死 UI，不迁**，等死代码清理 |
| （已迁的 Prompts 3 处） | `/d/prompts` 路由存在但**导航无入口**，仅 URL 直达/聊天输入框 Prompts 快捷命令 | `interface.prompts`（默认 true） | ⚠️ 半死页面（已迁完，无损失） |

3. **✅ 真确认迁移完成（2026-07-03）**：用户可见的真确认共 10 处全部迁 C 套（批次：设置数据页 3 → 删会话系 2 → Prompts 3 → 分享链接管理 + 免登录会话 2）。剩 7 处确认全是死 UI（SidePanel 死树 5 + Chat/Header 死树 2，见入口地图），**不迁**，随死代码清理处置。：设计师按页面点名逐批做，每批一笔提交 + 真实页面验证。注意两个行为差异：B 套会把焦点还给触发按钮（C 套命令式没有）；移动端 B 套按钮纵向堆叠 vs C 套横向等宽。
   - ✅ 第一批（设置弹窗-数据页）：ClearChats（清空聊天）、DeleteCache（删缓存）、RevokeKeysButton（撤销密钥，含 SetKeyDialog 内嵌用法）。迁移模式：`const ok = await confirm({ variant: 'destructive', title, description, confirmText }); if (!ok) return; mutate(...)`——标题/正文/确认文案沿用原 i18n key，取消文案用 C 套默认「暂不」。DeleteCache 顺带清了未挂载的 confirmClear/contentRef 死代码，并在清完后重查缓存刷新按钮禁用态。
4. **⬜（Modal 期）** 约 5 处「表单弹窗借 selection 当提交按钮」（SetKeyDialog、SaveAsPresetDialog、ApiKeyDialog、DashGroupItem 重命名、ActionsPanel）随 Modal 统一处理，届时 OGDialogTemplate 退役。

已定的样式决策：危险红 = `#f53f3f`（语义色不换肤）；普通确认 = 品牌主色（跟蓝⇄绿主题，绿色保存按钮一并折叠进来）；取消按钮 = C 套白底描边样式（hover `#f7f8fa`）；Loading 统一走 `selection.isLoading`（4 处自塞 Spinner 的随第三步迁移清理）。

<!-- site-hide -->
## 二点六、Modal 期用量重盘（2026-07-09，本窗口开工扫描）

> §二 的旧数字（OGDialogTemplate 25 等）已过时，以本节为准。画廊 Modal 版块已按本节重做。

| 体系 | 实现 | 业务文件数 | 说明 |
|---|---|---|---|
| **A 套 · 原语直接拼** | `Dialog`+`DialogContent` 手拼 | **22（最大人群）** | 新页面为主：知识库 8（EditTags/EditEncoding/MoveTo/VersionMgmt/Share/Similar/VersionHistory/index）、订阅 2、审批中心、通知、账号、InviteCode、ShareChat、UploadFileModal、DataTableKnowledge、SearchWebUrls、appChat 2、MarkLabel、**MainLayout（全局弹窗）** |
| A 套 · 模板 | `DialogTemplate` | 3 | EditPresetDialog、PresetItems、ContextButton（ContextButton 在 SidePanel 死树） |
| B 套 · 模板 | `OGDialogTemplate` | 16（原 25） | 确认迁移后剩余；其中 SidePanel 死树约 6 处（AgentTool/DeleteButton/ActionsPanel×2/AssistantTool/ApiKeyDialog）+ DeleteBookmarkButton 死 UI |
| B 套 · 原语直接拼 | `OGDialog`+`OGDialogContent` 手拼 | 16 | 设置账号 4（Avatar/BackupCodes/DeleteAccount/2FA）、SharedLinks、Prompts 4、Chat/Input/Files 4、ShareAgent、Agents/AdminSettings、ActionsAuth |
| 手拼 AlertDialog | `AlertDialogContent`+自拼头尾 | 7 | ChannelMemberDialog、ChannelMemberManagementPanel、TaskModeInput、AddSourceDropdown、CrawlFeedback/CrawlPreview、CreateChannelDrawer |
| C 套 · useConfirm（参照） | ConfirmContext | 26（已收敛 ✅） | 视觉基准：圆角 16 / p-5 / 灰底毛玻璃 |

**壳解剖当前真实值**（源码核对）：
- A 套：遮罩 `bg-black/40`+blur、`z-[100]`、`sm:rounded-lg`（8px 移动端直角）、`p-5`、border+`shadow-lg`、标题 `text-base font-semibold`、暗色底 `dark:bg-[#303134]` 写死。
- B 套（已对齐 C 套）：遮罩 `bg-gray-500/90`+blur、`z-50`、`rounded-2xl`(16px)、`p-5`、border `#ebebeb`+淡投影、标题 `text-base font-medium`、`bg-background` 跟主题。
- AlertDialog 底座：遮罩同 B、`z-[110]`、`sm:rounded-lg`、`p-6`、**无边框无阴影**、无内置关闭钮、移动端从底部滑入贴底。
- 遮罩的「毛玻璃 vs 纯深色」之争已不存在（black/80 在二次确认期淘汰），现在是**浅黑毛玻璃（A） vs 灰白毛玻璃（B/C）** 二选一。
- 层级三档并存：z-50 / z-[100] / z-[110]，统一时需盘 Drawer/Sheet/Popover 关系。

**待设计师定夺**（画廊 §④ 同步列出）：遮罩、圆角 8vs16、内边距 20vs24、标题字重、关闭钮、footer 按钮（Button 组件 vs C 套那对）与间距、层级、以及**原语收敛方向**——A 套 22 处直拼是最大人群，是「把 A 套壳改成标准（业务零改动）」还是「逐批迁 B 套」。

## 三、收敛策略（待设计师拍板的决策点）

1. **选基准**：建议以 `OGDialogTemplate`（B 套，用量最大）为便捷模板基准，底层原语二选一或合并成一套。
2. **定遮罩**：A 套毛玻璃 vs B 套纯深色 —— **二选一，全局统一**（见 01-设计规范 §二·遮罩）。
3. **定圆角/内边距/按钮间距**：按 01-设计规范定稿值。
4. **删死代码**：确认后删除 0 引用版本。
5. **迁移顺序**：设计师逐批点名页面，从基准模板开始替换，每批正常发版。

### 待决策清单（等设计师给链接/数值）
- [ ] 遮罩：毛玻璃 or 纯深色？
- [ ] 圆角：弹窗用几 px？
- [ ] 内边距：header / body / footer 各多少？
- [ ] 关闭按钮样式与位置？
- [ ] 标题字号/字重？
- [ ] 是否保留两套原语，还是彻底合并成一套？

---

## 四、改动记录（每次改完在此追加）

| 日期 | 改了什么 | 影响文件 | 提交 |
|---|---|---|---|
| — | 尚未改动组件源码，当前为现状梳理 + 画廊搭建 | — | — |
| 2026-07-02 | 二次确认弹窗现状扫描（两套体系：B 套 21 文件 9 种按钮写法、C 套 useConfirm 16 文件；手拼 AlertDialog 9 文件划归 Modal 范围），画廊新增「二次确认弹窗」版块（体系总览表 + 9 种写法清单 + 解剖表 + 11 个可打开 demo 含 useConfirm 两档）；未改组件源码 | `_gallery/sections/ConfirmDialogSection.tsx`（新）、`_gallery/GalleryApp.tsx` | 待 committer 窗口提交 |
| 2026-07-02 | **C 套第一笔定稿改动**：padding 24→20（`p-6`→`p-5`）、圆角 20→16（`rounded-[20px] sm:rounded-[20px]`→`rounded-2xl sm:rounded-2xl`），16 处业务全场生效 | `Providers/ConfirmContext.tsx` | 待 committer 窗口提交 |
| 2026-07-02 | C 套焦点环改 `focus-visible`：鼠标打开弹窗不再显示按钮灰圈，键盘 Tab 导航仍显示（无障碍保留）；只在 ConfirmContext 覆盖层做，未动 AlertDialog 底层 | `Providers/ConfirmContext.tsx` | 待 committer 窗口提交 |
| 2026-07-02 | C 套图标 lucide→bisheng-icons：Trash2→`Outlined.Delete`、AlertCircle→`Outlined.Attention`（Attention 字形待设计师目检确认） | `Providers/ConfirmContext.tsx` | 待 committer 窗口提交 |
| 2026-07-02 | C 套取消按钮 hover 从不可见的 `bg-white/70` 改为 `bg-[#f7f8fa]`，与知识空间工具栏按钮 hover 一致 | `Providers/ConfirmContext.tsx` | 待 committer 窗口提交 |
| 2026-07-03 | **收敛第一、二步**：B 套壳对齐 C 套（遮罩 `bg-gray-500/90`+blur、`p-5`、`rounded-2xl`+边框淡投影、标题 `text-base font-medium`）；OGDialogTemplate 按钮重写（取消=C 套样式，确认=cva `danger`/`primary` 两档，旧 selectClasses 自动折叠，未识别放行）；C 套 `description` 改 ReactNode。**注意：OriginalDialog 壳子改动影响所有 OG 弹窗（含表单类），非仅确认弹窗**。tsc 通过 | `ui/OriginalDialog.tsx`、`ui/OGDialogTemplate.tsx`、`Providers/ConfirmContext.tsx`、画廊 | 待 committer 窗口提交 |
| 2026-07-03 | B 套 danger 档标题变红 `#f53f3f`（对齐 C 套危险态）；仅 selection 解析为 danger 时生效，表单弹窗不受影响 | `ui/OGDialogTemplate.tsx` | 待 committer 窗口提交 |
| 2026-07-03 | **第三步第一批迁移（3/16）**：设置-数据页 3 处确认弹窗 B→C（useConfirm）。⚠️ 这批是业务页面文件，按双窗口规则应尽快单独提交一笔（confirm-migration batch 1），别和组件笔混 | `Nav/SettingsTabs/Data/{ClearChats,DeleteCache,RevokeKeysButton}.tsx` | 待 committer 窗口提交 |
| 2026-07-03 | **第三步第四批迁移（收官）**：最后 2 处可达真确认 B→C。SharedLinks（设置→数据→分享链接管理行删除，连带清掉 isDeleteOpen/deleteRow 状态与自塞 Spinner——至此「页面自塞 Spinner」清零）、GuestConvoItem（独立分享聊天页会话删除）。另：入口复查发现清空预设（PresetItems）与分享弹窗删除（SharedLinkButton）属 Chat/Header 死树，改判不迁。画廊全面更新为收官状态。⚠️ 业务文件，尽快单独提交（batch 4）| `SettingsTabs/Data/SharedLinks.tsx`、`standaloneChat/components/GuestConvoItem.tsx`、画廊 | 待 committer 窗口提交 |
| 2026-07-03 | **第三步第三批迁移**：Prompts 3 处 B→C（useConfirm）。DeleteVersion（版本删除，整组件瘦身为按钮+confirm）、DashGroupItem 的删除（重命名表单弹窗保留归 Modal 期）、AdminSettings 的管理员权限变更确认（外层设置表单保留，删除 confirmAdminUseChange 状态机改为直接 await confirm）。画廊同步：⑤ surface-destructive 清零删卡、② red-600 计数 3→2、总览 B 14 / C 24。⚠️ 业务文件，尽快单独提交（batch 3）| `Prompts/{DeleteVersion,AdminSettings}.tsx`、`Prompts/Groups/DashGroupItem.tsx`、画廊 | 待 committer 窗口提交 |
| 2026-07-09 | **Modal 期开工**：全站弹窗重盘（5 体系 64 文件，见 §二点六；新发现 A 套原语直拼 22 处为最大人群）；画廊 Modal 版块整体重做——用量总览表、壳解剖表（源码真实值）、同一内容装进 5 个壳的并排 demo + C 套参照、待决策清单 §④。未改组件源码，等设计师定标准 | `_gallery/sections/ModalSection.tsx`（重写） | 待 committer 窗口提交 |
| 2026-07-10 | **反馈弹窗抽成共享组件 `ui/CommentDialog`**（标题+textarea+取消/提交；容器零 padding、header/body/footer 各 `px-5`、移动端 `calc(100%-48px)` 宽 + 标题居中 + 按钮等宽、每次打开重置草稿、可选 `submitting`/`submittingText` 支持异步提交）。MessageFeedbackButtons 改为消费方（视觉/点踩延迟落库逻辑不变）；MenuUnavailablePage 手写申请权限弹窗迁入共享壳——手拼弹窗 -1，行为新增 ESC/遮罩/焦点圈定，桌面端标题改左对齐。画廊「点赞点踩反馈」demo 即真实组件，已实测桌面+移动端 | `ui/CommentDialog.tsx`（新）、`ui/index.ts`、`Chat/MessageFeedbackButtons.tsx`、`pages/MenuUnavailablePage.tsx` | 待提交 |
| 2026-07-03 | **第三步第二批迁移**：删会话确认 B→C。新建共享 hook `useDeleteConversationConfirm`（confirm → 删除 → 若删的是当前会话则跳走），三个消费方接线：会话侧栏菜单 ConvoOptions、归档会话表格 ArchivedChatsTable（复用同一组件被迫同批）、应用会话 AppSidebarConvoItem。**删除 `ConvoOptions/DeleteButton.tsx`**，barrel 出口同步更新。正文为纯文本 `确认删除 "标题"`（C 套 description 为字符串）。⚠️ 业务文件，尽快单独提交（batch 2）| `ConvoOptions/{useDeleteConversationConfirm.ts 新,ConvoOptions.tsx,index.ts,DeleteButton.tsx 删}`、`ArchivedChatsTable.tsx`、`AppSidebarConvoItem.tsx` | 待 committer 窗口提交 |

---

## 五、代码锚点
- A 套原语：`src/frontend/client/src/components/ui/Dialog.tsx`
- A 套模板：`src/frontend/client/src/components/ui/DialogTemplate.tsx`
- B 套原语：`src/frontend/client/src/components/ui/OriginalDialog.tsx`
- B 套模板：`src/frontend/client/src/components/ui/OGDialogTemplate.tsx`
- 画廊 Modal 版块：`src/frontend/client/src/pages/_gallery/sections/ModalSection.tsx`
- 画廊二次确认版块：`src/frontend/client/src/pages/_gallery/sections/ConfirmDialogSection.tsx`
