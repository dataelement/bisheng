# 移动到弹窗支持文件夹重命名 — 设计

日期：2026-07-08
状态：已评审通过，待实现

## 背景

知识库文件/文件夹的"移动到"弹窗（`MoveFolderDialog`）目前支持：面包屑导航、选择根目录/文件夹作为移动目标、进入子目录、以及**内联新建文件夹**。新建文件夹时名称是随机生成的（如 `未命名文件夹_HP58XW8AB0GN`），用户建完后无法在弹窗内改名，只能关掉弹窗回到列表页重命名，体验割裂。

因此需要：在"移动到"弹窗内支持给（已有）文件夹重命名。

## 目标 / 非目标

- 目标：在移动到弹窗的文件夹列表里，对已有文件夹进行内联重命名。
- 非目标：不改后端、不改其他组件、不引入右键菜单、不支持在弹窗内删除文件夹。

## 影响范围

- **唯一改动文件**：`src/frontend/client/src/pages/knowledge/SpaceDetail/MoveFolderDialog.tsx`
- **复用（不改动）**：
  - API：`renameFolderApi(space_id, folder_id, name)`（`~/api/knowledge`，已存在）。
  - 刷新链路：`dispatchKnowledgeSpaceFilesRefresh(spaceId)` + `onFolderCreated?.()` 回调（已存在，新建流程已在用）。
  - 多语言 key：`com_knowledge.rename`（"重命名"）、`com_knowledge.rename_success`、`com_knowledge.rename_failed`（zh/en/ja 均已存在）。
- 无需新增多语言 key，无需改后端。

## 交互设计

1. **触发**：每个已有文件夹行 hover 时，在现有"进入子目录"箭头**左侧**多出一个铅笔按钮（lucide `Pencil` 图标），`title`/`aria-label` = `localize("com_knowledge.rename")`。默认 `opacity-0`，`group-hover:opacity-100`（与现有 chevron 一致）。
2. **进入编辑**：点铅笔 → 该行原地变成内联输入框，**复用"新建文件夹"那套 input 样式**（蓝色边框 `border-[#165dff]`、`autoFocus`、`onFocus` 全选），初值 = 当前文件夹名。
3. **提交/取消**（与新建一致）：
   - `Enter` 或 `blur` → 提交。
   - `Escape` → 取消并恢复原名。
4. **提交逻辑**：
   - 去空格后为空 **或** 与原名相同 → 直接收起编辑态，不调接口。
   - 否则调用 `renameFolderApi(spaceId, folderId, name)`：
     - 成功：`loadFolders(currentFolderId)` 重拉当前层；调用 `dispatchKnowledgeSpaceFilesRefresh(spaceId)` 与 `onFolderCreated?.()`，同步 SpaceDetail 左树/列表与 Portal 宿主列表的新名字。
     - 失败：交给响应拦截器提示（与新建流程一致），保留编辑态供重试。
   - 用 `renameSubmittingRef`（`useRef(false)`）防止 `Enter` 与 `blur` 双触发导致的重复提交（照抄新建的 `submittingRef` 模式）。

## 状态建模（方案 A：独立 renaming 状态）

在现有状态基础上新增：

- `renamingId: string | null` —— 正在重命名的文件夹 id（`null` = 无）。
- `renamingName: string` —— 编辑框当前值。
- `renameSubmittingRef: React.MutableRefObject<boolean>` —— 双提交守卫。

互斥与重置规则：

- 开始重命名（点铅笔）：设置 `renamingId`/`renamingName`，同时清空 `creatingName`（关闭新建态）。
- 开始新建（点新建文件夹）：`handleStartCreate` 里额外清空 `renamingId`。
- 导航进入子目录 / 点面包屑 / 弹窗重新打开（`open` 的 `useEffect` 重置块）：一并把 `renamingId` 置空。

> 不选方案 B（把新建与重命名合并为统一的 `editingId`/`editingName`）：需重写现有新建逻辑，回归风险大，收益低。

## 渲染改动（文件夹行）

现有文件夹行结构：`Folder 图标 + 名称 span + 进入子目录 chevron 按钮`。改为：

- 当 `renamingId === folder.id`：渲染内联输入框（复用新建行的 input 样式与提交中 spinner）。因新建与重命名互斥、同时只有一个内联编辑，`savingFolder` 状态可同时用于重命名的提交中反馈，无需新增 loading 状态。整行不再响应"点击选为目标"。
- 否则：正常渲染，名称 span 后依次是 **铅笔按钮**（新增）和 **进入子目录 chevron**（原有），二者都 `stopPropagation`。

## 边界与约束

- 铅笔按钮 `onClick` 需 `e.stopPropagation()`，避免点它把该行选成移动目标。
- 行处于重命名态时，行外层 `onClick={() => setSelected(folder.id)}` 被忽略/禁用（输入框接管整行）。
- 正在被移动的文件夹本就已从列表中过滤（`item.id !== movingItemId`），天然不会在此被重命名。
- 根目录行（`currentFolderId === null` 时的 Home 行）不涉及重命名。
- 同一时刻只允许一个内联编辑（新建或重命名），由上面的互斥规则保证。

## 测试计划

按该目录既有 `*.test.tsx` 惯例，为 `MoveFolderDialog` 增补测试：

1. hover 文件夹行出现铅笔按钮；点击进入内联编辑，初值为当前名且被选中。
2. 改名并回车 → 以 `(spaceId, folderId, 新名)` 调用 `renameFolderApi`，成功后触发 `loadFolders` 重拉与刷新回调（`dispatchKnowledgeSpaceFilesRefresh` / `onFolderCreated`）。
3. 空名 / 与原名相同 → 不调用 `renameFolderApi`，编辑态收起。
4. `Escape` → 取消编辑并恢复原名，不调接口。
5. 点铅笔不会把该行选为移动目标（`selected` 不变）。
6. 重命名与新建互斥：开始其中一个会关闭另一个。

## 风险

- 低。单文件、纯前端、复用既有 API 与刷新链路；主要注意点是内联编辑态与"点击选为目标"、"新建态"三者的互斥与事件冒泡处理。
