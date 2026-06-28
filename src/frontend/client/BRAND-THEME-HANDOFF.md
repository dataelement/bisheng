# 主题色切换（蓝 ⇄ 绿）— 交接文档

> 分支：`feat/2.6.0-beta4-UI` ｜ 仅 **client**（`src/frontend/client/`）｜ 纯前端，不动后端
> 用途：在新对话里继续「空状态插画主题化」时，先读本文件即可无缝衔接。

---

## 1. 这套主题系统是什么

把原本写死的「品牌蓝」改造成一组 **CSS 变量 `--brand-*`**，蓝/绿两套值，靠 `<html>` 上的 `theme-green` class 切换。所有走 token 的地方自动跟随。

### 1.1 核心变量（`src/style.css`）

`:root` 定义**蓝色默认**（RGB 通道格式，为了支持 Tailwind `/<alpha>`）：

```
--brand-50:232 243 255(#E8F3FF)  --brand-100:190 218 255(#BEDAFF)  --brand-200:148 191 255(#94BFFF)
--brand-300:106 161 255(#6AA1FF) --brand-400:64 128 255(#4080FF)   --brand-500:22 93 255(#165DFF 主)
--brand-600:2 77 227(#024DE3 按钮/按下) --brand-700:2 57 171  --brand-800:4 43 128  --brand-900:5 29 82
--brand-main:22 93 255(#165DFF)
```

`.theme-green` 覆盖成**绿色**：

```
--brand-50:228 241 236(#E4F1EC)  --brand-100:204 228 218(#CCE4DA)  --brand-200:163 210 192(#A3D2C0)
--brand-300:111 186 160(#6FBAA0) --brand-400:61 155 120(#3D9B78)   --brand-500:24 124 84(#187C54 主)
--brand-600:19 99 69(#136345)    --brand-700:15 77 54  --brand-800:10 56 38  --brand-900:6 38 25
--brand-main:24 124 84(#187C54)
/* 另外覆盖： */
--primary:154 67% 29%;  --surface-active-alt:rgb(228 241 236);  --surface-primary-alt:#f4faf7;  --search-input:hsla(152,40%,99%,1);
```
（蓝色 `--primary` 默认是 `222 100% 54%`，在 `:root`/`html` 块里。）

### 1.2 Tailwind 接线（`tailwind.config.cjs`）

`blue` 调色板 + `blue-main` 已重指向变量，所以**所有 `blue-*` 工具类自动跟随主题**：
```js
'blue-main': 'rgb(var(--brand-main) / <alpha-value>)',
blue: { 50:'rgb(var(--brand-50) / <alpha-value>)', ... 900:'rgb(var(--brand-900) / <alpha-value>)' }
```

### 1.3 切换机制

- Recoil atom：`store.brandTheme`（值 `'blue' | 'green'`），定义在 `src/store/brand.ts`，localStorage key = `brand-theme`。
- 应用：`src/utils/theme.ts` 的 `applyBrandTheme()` 往 `<html>` 加/去 `theme-green` class；启动时在 `src/hooks/ThemeContext.tsx` 调一次。
- UI 开关：`src/layouts/UserPopMenu.tsx`（左下角用户菜单「主题色」子菜单，PC rail + 移动 drawer 两个变体）。i18n key：`com_nav_theme_color` / `_blue` / `_green`（三语已加）。

---

## 2. 怎么把一个颜色「接入主题」（按场景选）

| 场景 | 做法 |
|---|---|
| Tailwind 类（`text-blue-500`/`bg-blue-600`/`border-blue-500`…） | **已自动跟随**，无需改 |
| 写死的品牌蓝 hex（`#165DFF`/`#024DE3`/`#335CFF`…） | 换成 `blue-*` 类；或在内联 style/CSS 里换 `rgb(var(--brand-NNN))` |
| 选中/hover 浅底 | `bg-blue-500/[0.07]` 这种「主色 + 透明度」（本轮选中态统一用 7%） |
| 内联 style / CSS / 渐变 | `rgb(var(--brand-500))`、`rgb(var(--brand-500)/0.04)`（注意 Tailwind 任意值 `[...]` 内**不能有空格**，斜杠两侧不留空） |
| **SVG**（重点，插画用这个） | 见下 §3 |

---

## 3. SVG 着色（空状态插画关键）

**铁律：SVG 的展示属性 `fill="..."`/`stroke="..."` 里 `var()` 不生效**（只在 CSS 属性里有效）。三种可行手段：

1. **内联 `style`（推荐用于插画）**：`<path style={{ fill: 'rgb(var(--brand-500))' }} />`。这是 CSS，`var()` 生效，自动跟随主题。渐变 stop 同理用 `style={{ stopColor: 'rgb(var(--brand-300))' }}`。已用于 `src/components/icons/FolderIcon.tsx`（可作模板参考）。
2. **Tailwind 类**：`<path className="fill-blue-500" />`（CSS 优先级高于展示属性，能覆盖）。
3. **CSS mask**（仅**单色**图形）：`bg-blue-200` + `mask-image: url(icons.svg)`。多色插画不适用。已用于三个广场头部装饰。

**多 SVG 同屏注意**：把 `id`（gradient/clipPath/mask）用 `useId()` 做唯一化，否则重复 id 串色。FolderIcon 已示范。

### 3.1 插画专用调色板 `--illus-*`（2026-06-24）

空状态插画**不用 `--brand-*`，改用独立的 `--illus-100/300/500`**（`style.css`）。原因：用户画插画用的鲜绿 `#19B476/#BDE6D3/#7CD0B1` 比 UI 品牌绿 `#187C54` 系更亮；若跟 `--brand-*` 会被压暗、与设计稿不符。

- `:root`（蓝模式）：`--illus-*` = 品牌蓝（#165DFF/#6AA1FF/#BEDAFF），所以蓝模式插画仍跟随切蓝。
- `.theme-green`：`--illus-500=#19B476`、`--illus-300=#7CD0B1`、`--illus-100=#BDE6D3`（忠于原图）。

7 张插画组件（EmptyState/ArticleQA/ListWebLink/Crawling/NoPermission/Success/SystemMaintenance）的 `fill/stroke` 都用 `rgb(var(--illus-NNN))`。**新插画一律用 `--illus-*`，不要用 `--brand-*`。** UI 品牌绿 `#187C54`（按钮/链接/选中）不受影响。FolderIcon 等 UI 图标仍用 `--brand-*`。

---

## 4. 本轮已固定为「不跟随主题、永远蓝」的例外（不要误改成绿）

- 审批中心「审批中」状态 tag：`bg-[#e8f3ff] text-[#165dff]`（`ApprovalCenterDialog.tsx`，4 处 pending 配置）。
- 应用中心置顶 pin 图标：固定低饱和深绿 `#5C8A77`（`AgentCard.tsx`，2 处）——注意这个是**固定绿**不是蓝，是用户特意要的muted色，也不跟随切换。
- 各类**语义色**不参与：成功绿 `#00b42a`、失败红 `#f53f3f`、异常橙 `#ff7d00`、技能紫 `#F5E8FF/#722ED1`、助手橙 `#FFF7E8/#FF7D00`、第三方 logo（Google `#4285F4` 等）、灰蓝文字（`#8B8FA8` 等）、azure/sky（`#1677FF/#0285FF`）。

---

## 5. 空状态插画任务 — 推荐方案

**现状**：现有空状态多为 PNG（`public/assets/channel/empty.png`，`WorkbenchEmptyIllustration.tsx` 等引用）+ 若干 `EmptyState` 组件。**PNG 无法主题化**。用户已新画一批插画（绿色，多色调）。

**推荐做法**：把新插画做成 **内联 SVG React 组件**，绿色填充改为 `rgb(var(--brand-NNN))`（§3 手段 1），即可自动蓝/绿切换。

**落地步骤**：
1. 拿到每张插画的 SVG 源码，统计它用的几档绿（通常 2~3 档：主绿 + 浅绿底 +（可选）中绿）。
2. 按「明度」映射到 brand 档位，例如：
   - 主体绿（深，如 #187C54 系）→ `rgb(var(--brand-500))` 或 `brand-600`
   - 浅绿底（如 #CCE4DA / #E4F1EC 系）→ `rgb(var(--brand-100))` 或 `brand-200`
   - 中绿 → `rgb(var(--brand-300/400))`
   - 纯白/灰/描边等非品牌色保持原样
3. 每张存成组件（参考 `src/components/icons/FolderIcon.tsx` 的写法：`style={{fill:'rgb(var(--brand-NNN))'}}`、`useId()` 唯一化 id），放 `src/components/icons/` 或 `src/components/illustrations/`。
4. 替换现有引用点（grep `empty.png` / `EmptyState` / `WorkbenchEmptyIllustration`）。
5. 验证：`npx tsc --noEmit`（基线错误数 **559**，不应增加）；切到绿/蓝各看一遍。

**插画清单（来自用户截图，需对应 SVG）**：列表网页链接、空状态、文件、爬取中、无权限访问数据、成功态、文章问答、加载中。
> 注意「成功态」插画若是「成功=绿」的语义图标，要确认它该跟随品牌还是固定成功绿——和用户确认。

**给新对话的起手式**：把这批 SVG 源码贴给我（或给路径），我按上表映射逐个做成主题化组件并替换。

### 5.1 进度（2026-06-24）

已把用户新画的 6 张 SVG 做成主题化内联组件，放在 `src/components/illustrations/`（统一从 `index.ts` 导出）。颜色按 §5 映射：`#19B476→rgb(var(--brand-500))`、`#BDE6D3→rgb(var(--brand-100))`、`#7CD0B1→rgb(var(--brand-300))`，white / black-opacity / `#D9D9D9`(mask) 保持原样；带 mask 的两张用 `useId()` 唯一化。

| 组件 | 来源 SVG | 备注 |
|---|---|---|
| `EmptyStateIllustration` | 空状态 | 通用空状态（mask uid 已唯一化） |
| `NoPermissionIllustration` | 无权限访问数据 | 适合 `MenuUnavailablePage` |
| `ArticleQAIllustration` | 文章问答 | |
| `ListWebLinkIllustration` | 列表网页链接 | |
| `CrawlingIllustration` | 爬取中 | mask uid 已唯一化 |
| `SuccessIllustration` | 成功态 | **跟随品牌主题**（用户已确认，非固定语义成功绿） |
| `SystemMaintenanceIllustration` | 系统维护 | 数据库+扳手；无 mask；2026-06-24 新增，组件已建未接槽位 |

**通用空状态已替换（2026-06-24）**：10 处通用 `assets/channel/empty.png` 的 `<img>` 已换成 `<EmptyStateIllustration className="size-[120px] mb-X opacity-90" />`（去掉对内联 SVG 无意义的 `object-contain`）：ChannelMemberManagementPanel、ChannelMemberDialog、KnowledgeSpaceMemberManagementPanel、KnowledgeSpaceMemberDialog、ChannelSquare、Subscription/index、knowledge/index、KnowledgeSquare、SpaceDetail/index、apps/AppEmptyState。

**`AddSourceDropdown.tsx` 两个空态已接（2026-06-24）**：
- `viewMode === "noResultNonUrl"`（按名称搜无收录，文案「输入正确名称或完整的网址」）：`ChannelBookIcon` → `ListWebLinkIllustration`（顺手删掉本文件已无引用的 `ChannelBookIcon` import）。
- `viewMode === "noResultUrl"`（网站尚未入库·待爬取，带「暂不爬取/确认爬取」按钮）：`empty.png` → `EmptyStateIllustration`。

**`CrawlingIllustration` 已接（2026-06-24）**：`Subscription/CreateChannel/CrawlPreviewDialog.tsx` 的 `PreviewBody` `status === "loading"`（爬取中，文案 crawling_waiting/crawling_please_wait）原本用 `ChannelLoadingIcon`（写死蓝 #4D6DFD，静态、不跟随主题）→ 换成 `CrawlingIllustration`。`PreviewBody` 同时被弹窗 `CrawlPreviewDialog`（点队列进行中条目弹出）和内联 `CrawlPreviewPanel` 复用，两处一起生效。`ChannelLoadingIcon` 本文件已无引用，移除 import。

**`NoPermissionIllustration` 已接（2026-06-24）**：频道广场 / 知识广场预览抽屉里「内容不可见」空态（原本写死 `assets/channel/review.png`）共 3 处换成 `NoPermissionIllustration`：
- `Subscription/ChannelPreviewDrawer.tsx`（频道待审核，channel_content_needs_approval）
- `knowledge/KnowledgeSpacePreviewDrawer.tsx`（APPROVAL 可见性 space_view_requires_approval + 需加入 space_view_requires_join，两处同一张图一起换）

> 注：`MenuUnavailablePage`（经 `WorkbenchEmptyIllustration` 用 ai... 实为 empty.png）也是无权限语境，但仍走旧 `WorkbenchEmptyIllustration`，未动（见下）。

**`SuccessIllustration` 已接（2026-06-24）**：创建成功界面（原 `ChannelSuccessIcon`，写死蓝）→ `SuccessIllustration`（跟随品牌主题）：
- `Subscription/CreateChannel/CreateChannelSuccess.tsx`（频道创建成功）
- `knowledge/CreateKnowledgeSpaceDrawer.tsx`（知识空间创建成功）

→ **6 张插画全部有落地槽位。**

**`AddToKnowledgeModal` 已接（2026-06-24）**：「加入知识空间」弹窗（标题 key `add_to_knowledge_space`，挂在 `ArticlePage`）两个空态（`no_selectable_knowledge_space` + `no_matching_knowledge_space`，原 `empty.png` 渲染为旧六边形图）→ `EmptyStateIllustration`。（注：原计划接 ListWebLink，用户改为 empty。）

**`ArticleList` 两空态已接（2026-06-24）**：`Subscription/ArticleList/ArticleList.tsx` 频道内文章列表——搜索/筛选无匹配态（`no_results`，原纯文字，**新增**插画）+ 频道无文章态（`no_related_content`，原 `empty.png`，**替换**）均用 `EmptyStateIllustration`，各自保留原文案。

**`WorkbenchEmptyIllustration` 已接（2026-06-24）**：菜单无权限页 `MenuUnavailablePage`（路由 `/workspace/menu-unavailable`，菜单审批模式下访问无权限菜单时跳转）。`WorkbenchEmptyIllustration.tsx` 内部从 `empty.png` 改为渲染 `NoPermissionIllustration`（仅此一处引用，一改全跟）。

**→ 全仓 `assets/channel/empty.png` 实际引用已清零；6 张插画全部落地完成。** （`illustrations/index.ts` 注释里还提到 empty.png 一词，仅为说明文字。）

`CrawlingIllustration` / `SuccessIllustration` 暂无槽位。

**AI 问答前置插画已接 `ArticleQAIllustration`（2026-06-24）**：知识空间 + 订阅模块的 AI 助手空状态原本是 `assets/channel/ai-home.png`，现统一换成 `ArticleQAIllustration`（`size-[80px]`）。
- 知识空间：`KnowledgeAiBottomDock.tsx` 自带的两处空态 `<img>`（移动 drawer + PC 变体，覆盖文件夹提问与单文件提问——该 dock 浮在 SpaceDetail/文件预览之上）已直接替换。
- 订阅模块：`ArticleAiDock`(2)、`FileAiDock`(2)、`AiAssistantPanel`(1) 通过 `AiChatMessages` 渲染空态——给 `AiChatMessages` 新增可选 prop `emptyStateIllustration?: ReactNode`（默认仍是 ai-home.png），这些 dock 传入 `<ArticleQAIllustration/>`。
- **后续也统一了（2026-06-24）**：`appChat/ChatEmptyState.tsx`（应用对话空态，appChat + AppChatEntry 删除态 + standaloneChat 共用）和 `AiChatMessages` 默认值（ShareView 空分享会话）也从 `ai-home.png` 换成 `ArticleQAIllustration`。这两处是低频兜底空态（应用配了开场白/引导问题就不会出现；对话基本删不空）。→ 全仓 `ai-home.png` 引用清零。

`tsc --noEmit` 基线 559 未增加。

---

## 6. 验证命令

```bash
cd src/frontend/client
npx tsc --noEmit -p tsconfig.json   # 基线 559 个错误，本轮改动不应增加
npm run dev                          # :4001（strictPort:true，已固定）
```
