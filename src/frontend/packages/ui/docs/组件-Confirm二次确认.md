# 二次确认弹窗 Confirm

> 设计系统 · 二次确认部分 v1 · 2026-07-30 从《组件-Modal弹窗》拆分独立
> 二次确认是弹窗的一个专用子类；通用弹窗规范见 [组件-Modal弹窗.md](组件-Modal弹窗.md)，本文只写二次确认自己的细则。
> 配套：圆角与投影见 [基础-阴影与圆角规范.mdx](基础-阴影与圆角规范.mdx)、颜色见 [基础-色彩规范.mdx](基础-色彩规范.mdx)、按钮见 [组件-Button按钮.md](组件-Button按钮.md)、文案见 [基础-文案规范.md](基础-文案规范.md)、移动端通则见 [基础-多端适配原则.md](基础-多端适配原则.md)。
> 实时预览见「组件 → Confirm」（components/confirm.mdx）。迁移台账与实现细节走文末隐藏区。

## 1. 什么时候用

删除、清空这类**破坏性且不可逆**的操作，点击后先弹一个二次确认，让用户有机会反悔。这一子类已经收敛到统一实现（一套样式、改一处全生效），直接照下面用。

- **动作一旦执行就收不回来**（删知识库、清空聊天、撤销密钥），才值得打断一次去确认。
- **可撤销的普通操作不必套确认**，否则确认框会变成人人无脑点「确定」的噪音。

## 2. 外观

居中的卡片，圆角 16px、四周内边距 20px；顶部一行是图标 + 标题，下面是说明文字，底部按钮右对齐（移动端等宽平铺占满一行）。卡片本身不带右上角的关闭「×」——靠底部按钮明确地关，不给「随手点叉」的模糊出口。

圆角与模态投影随《阴影与圆角规范》，见 [基础-阴影与圆角规范.mdx](基础-阴影与圆角规范.mdx)。

## 3. 两档语气

按操作危险程度选一档：

| 档 | 什么时候用 | 图标 + 标题 | 确认按钮 |
|---|---|---|---|
| **危险 danger** | 删除、清空等破坏性操作 | 红色图标 + 红色标题 | 危险红实心 |
| **普通 primary** | 一般需要确认、但不具破坏性的操作 | 品牌色图标 + 常规标题 | 品牌色实心 |

- **颜色**：危险档用功能色「危险」（常规档 `#f53f3f`，不随蓝⇄绿主题换肤）；普通档用品牌主色（跟主题切换）。取值见 [基础-色彩规范.mdx](基础-色彩规范.mdx)。
- **取消按钮**：白底描边样式，悬停加浅灰底（填充色 `fill-1`）。
- **按钮文案**：用动词说清后果，跟《文案规范》走——删除场景用「暂不 / 确认删除」，不用「否 / 是」。见 [基础-文案规范.md](基础-文案规范.md)。
- **加载**：确认后若要等接口，用组件内置的加载态，按钮转圈、期间不可点；**禁止业务页自己往按钮里塞 Spinner**。

<!-- site-hide -->
## 4. 迁移台账（给实现窗口）

> 二次确认子类的收敛过程与逐页迁移记录，规范结论已上升到 §1–§3，此处只留迁移事实。

### 4.1 两套体系并行（2026-07-02 扫描）

| 体系 | 实现 | 业务文件数 | 用在哪 | 一致性 |
|---|---|---|---|---|
| B 套模板 | `OGDialogTemplate` + `selection` | 21 | 旧页面：会话 / 书签 / Agent / 设置 / Prompt（LibreChat 血统） | 差：确认按钮 9 种写法 |
| **C 套服务** | `useConfirm()`（`Providers/ConfirmContext.tsx`，底层 AlertDialog） | 16 | 新页面：知识空间 / 订阅频道 / 权限 | 好：样式集中一处，danger / primary 两档，改一处全生效 |

- 另有 9 个文件直接手拼 `AlertDialog`（频道成员 / 知识空间成员 / 爬取反馈与预览 / 灵思 TaskModeInput 等），属普通弹窗、归 Modal 范围，二次确认期不动。
- C 套即设计师截图那个「红垃圾桶图标 + 红标题 + 暂不 / 确认删除」的弹窗（知识空间删除），是收敛基准。

### 4.2 确认按钮 selectClasses 的 9 种写法（B 套历史）

| # | 写法 | 文件数 | 代表文件 |
|---|---|---|---|
| 1 | `bg-red-700 dark:bg-red-600 hover:bg-red-800 dark:hover:bg-red-800` | 8（最多） | ConvoOptions/DeleteButton、Bookmarks、AgentTool、SharedLinks… |
| 2 | `bg-red-600 hover:bg-red-700 dark:hover:bg-red-800` | 3 | Agents/DeleteButton、Builder/ContextButton、DashGroupItem（删） |
| 3 | `bg-red-600 hover:bg-red-700 dark:hover:bg-red-600` | 1 | PresetItems（清空） |
| 4 | `bg-destructive hover:bg-destructive/80` | 3 | ClearChats、DeleteCache、RevokeKeysButton |
| 5 | `bg-surface-destructive hover:bg-surface-destructive-hover` | 2 | DeleteVersion、AdminSettings |
| 6 | `bg-green-500 hover:bg-green-600`（确认=绿色） | 2 | SaveAsPresetDialog、ApiKeyDialog |
| 7 | `btn btn-primary`（全局 CSS 类） | 1 | SetKeyDialog |
| 8 | `bg-surface-submit hover:bg-surface-submit-hover` | 1 | DashGroupItem（重命名） |
| 9 | 不传 → 模板默认 `bg-gray-800 … dark:bg-gray-200` | — | OGDialogTemplate defaultSelect |

### 4.3 收敛方案（设计师 2026-07-03 拍板，四步走）

> 目标：全平台二次确认只剩 `useConfirm()` 一个组件、一处样式源。

1. **✅ B 套壳对齐 C 套视觉**：遮罩灰底毛玻璃、圆角 16、padding 20、标题 `text-base`、取消 / 确认按钮同 C 套；`selection` 增加 `selectVariant: 'danger' | 'primary'` cva 档位，历史 9 种 selectClasses 由模板自动折叠（`red- | destructive`→danger，`green- | btn-primary | surface-submit`→primary，未识别原样放行=特例口子），21 个业务页零改动。
2. **✅ C 套 `description` 扩展为 ReactNode**：支持富文本正文（如加粗对象名），为迁移铺路。
3. **✅ 真确认迁移完成**：用户可见的真确认共 10 处全部迁 C 套（批次：设置数据页 3 → 删会话系 2 → Prompts 3 → 分享链接管理 + 免登录会话 2）。剩 7 处确认全是死 UI（SidePanel 死树 5 + Chat/Header 死树 2），不迁，随死代码清理处置。注意两个行为差异：B 套会把焦点还给触发按钮（C 套命令式没有）；移动端 B 套按钮纵向堆叠 vs C 套横向等宽。
4. **⬜（Modal 期）** 约 5 处「表单弹窗借 selection 当提交按钮」（SetKeyDialog、SaveAsPresetDialog、ApiKeyDialog、DashGroupItem 重命名、ActionsPanel）随 Modal 统一处理，届时 OGDialogTemplate 退役。

### 4.4 剩余入口地图（2026-07-03 代码探查）

| 功能 | 界面入口 | 可达性 |
|---|---|---|
| 书签删除 DeleteBookmarkButton | 死 UI：唯一渲染点在被注释的 SidePanel 书签表格 | ❌ 不迁，随死树清理 |
| 清空预设 PresetItems | 聊天页 Header → Presets 菜单 → Clear all，属 Chat/Header 死树 | ❌ 改判不迁 |
| 分享链接删除 SharedLinkButton | Header 导出 / 分享菜单 → 分享弹窗，属 Chat/Header 死树 | ❌ 改判不迁 |
| 分享链接管理 SharedLinks | 设置 → 数据 → 管理分享链接 | ✅ 已迁 |
| 免登录会话删除 GuestConvoItem | 独立分享聊天页 `/chat/flow/:flowId` | ✅ 已迁 |
| 删 Agent / Agent 工具 / 删 Assistant / Assistant 工具（4 处） | 右侧 SidePanel `SidePanelGroup.tsx:117-132` 整段注释、面板不渲染 | ❌ 死 UI，不迁 |
| Prompts 3 处 | `/d/prompts` 路由存在但导航无入口 | ✅ 已迁（半死页面，无损失） |

已定的样式决策（见 §3）：危险红 `#f53f3f`（语义色不换肤）；普通确认 = 品牌主色（绿色保存按钮一并折叠进来）；取消 = 白底描边（hover 底 `fill-1` = `#f8f8f8`）；Loading 统一走 `selection.isLoading`。

## 改动记录

| 日期 | 改了什么 | 影响文件 | 提交 |
|---|---|---|---|
| 2026-07-30 | **从《组件-Modal弹窗》拆分为独立规范**：二次确认的规范正文（何时用 / 外观 / 两档 / 细则）与迁移台账整体迁入本文；Modal 文档仅在 §2 留指针。设计内容一字未改，仅调整落位。 | 本文件（新）、组件-Modal弹窗.md | 待 committer 窗口提交 |
| 2026-07-02 | 二次确认弹窗现状扫描（B 套 21 文件 9 种按钮写法、C 套 useConfirm 16 文件；手拼 AlertDialog 9 文件划归 Modal 范围），画廊新增「二次确认弹窗」版块；未改组件源码 | `_gallery/sections/ConfirmDialogSection.tsx`（新）、`_gallery/GalleryApp.tsx` | 待 committer 窗口提交 |
| 2026-07-02 | **C 套第一笔定稿改动**：padding 24→20（`p-6`→`p-5`）、圆角 20→16（`rounded-[20px]`→`rounded-2xl`），16 处业务全场生效 | `Providers/ConfirmContext.tsx` | 待 committer 窗口提交 |
| 2026-07-02 | C 套焦点环改 `focus-visible`：鼠标打开不显示按钮灰圈，键盘 Tab 仍显示 | `Providers/ConfirmContext.tsx` | 待 committer 窗口提交 |
| 2026-07-02 | C 套图标 lucide→bisheng-icons：Trash2→`Outlined.Delete`、AlertCircle→`Outlined.Attention`（Attention 字形待设计师目检） | `Providers/ConfirmContext.tsx` | 待 committer 窗口提交 |
| 2026-07-02 | C 套取消按钮 hover 从不可见的 `bg-white/70` 改为 `bg-[#f7f8fa]`，与知识空间工具栏按钮 hover 一致 | `Providers/ConfirmContext.tsx` | 待 committer 窗口提交 |
| 2026-07-03 | **收敛第一、二步**：B 套壳对齐 C 套（遮罩灰底毛玻璃、`p-5`、`rounded-2xl` + 边框淡投影、标题 `text-base font-medium`）；OGDialogTemplate 按钮重写（取消 = C 套样式，确认 = cva `danger` / `primary` 两档，旧 selectClasses 自动折叠）；C 套 `description` 改 ReactNode。注意：OriginalDialog 壳改动影响所有 OG 弹窗（含表单类）。tsc 通过 | `ui/OriginalDialog.tsx`、`ui/OGDialogTemplate.tsx`、`Providers/ConfirmContext.tsx`、画廊 | 待 committer 窗口提交 |
| 2026-07-03 | B 套 danger 档标题变红 `#f53f3f`（对齐 C 套危险态）；仅 selection 解析为 danger 时生效 | `ui/OGDialogTemplate.tsx` | 待 committer 窗口提交 |
| 2026-07-03 | **第三步第一批迁移（3/16）**：设置-数据页 3 处确认弹窗 B→C。⚠️ 业务文件，单独提交一笔（batch 1） | `Nav/SettingsTabs/Data/{ClearChats,DeleteCache,RevokeKeysButton}.tsx` | 待 committer 窗口提交 |
| 2026-07-03 | **第三步第二批迁移**：删会话确认 B→C。新建共享 hook `useDeleteConversationConfirm`，三个消费方接线；删除 `ConvoOptions/DeleteButton.tsx`，barrel 同步。⚠️ 业务文件，单独提交（batch 2） | `ConvoOptions/*`、`ArchivedChatsTable.tsx`、`AppSidebarConvoItem.tsx` | 待 committer 窗口提交 |
| 2026-07-03 | **第三步第三批迁移**：Prompts 3 处 B→C（DeleteVersion、DashGroupItem 删除、AdminSettings 权限变更确认）。画廊同步。⚠️ 业务文件，单独提交（batch 3） | `Prompts/*`、画廊 | 待 committer 窗口提交 |
| 2026-07-03 | **第三步第四批迁移（收官）**：最后 2 处可达真确认 B→C（SharedLinks、GuestConvoItem）——至此「页面自塞 Spinner」清零。入口复查将清空预设与分享弹窗删除改判为死树不迁。⚠️ 业务文件，单独提交（batch 4） | `SettingsTabs/Data/SharedLinks.tsx`、`standaloneChat/components/GuestConvoItem.tsx`、画廊 | 待 committer 窗口提交 |
| 2026-07-30 | 取消按钮 hover 底跟随 token 调整：`fill-1` 由 `#f7f8fa` 改为 `#f8f8f8`（纯中性灰）。仅 token 值变化，ConfirmContext 的裸 hex 仍待迁到 `bg-fill-1`。 | design-token.cjs、tokens.css、client/style.css、本文件 §3、confirm.mdx | 待 committer 窗口提交（token 一笔） |

## 代码锚点

- C 套服务：`src/frontend/client/src/Providers/ConfirmContext.tsx`
- 底层原语：`AlertDialog`（`src/frontend/client/src/components/ui/` 下）
- 画廊二次确认版块：`src/frontend/client/src/pages/_gallery/sections/ConfirmDialogSection.tsx`
- 实时预览页：`src/frontend/packages/ui/docs/components/confirm.mdx`
