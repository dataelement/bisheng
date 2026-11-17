# 3.1-beta1 文件列表下载入口检查记录

日期：2026-11-13。范围：每页列表展示后异步批量检查下载资格，在文件行显示下载按钮。

- 专项回归：目录交互、下载权限、上传与原批量流程 44 项通过；历史版本入口另 10 项通过。
- 前端工作区 lint、typecheck 通过；改动文件 arch-guard、git diff --check 通过。
- 覆盖权限慢请求期间勾选、只检查新增页、允许/拒绝、空页、不完整/失败结果、切换搜索后的迟到回包、直接下载及租户切换后旧下载失效。
- 按 sdd-code-review 七维度自查本次增量，无新增接口契约、依赖或数据库变更，实际下载保留后端鉴权，设计文档已同步。
- 未进行真实环境浏览器验收或部署。

## 已确认的既有测试偏差

用 Vitest 加载本次修改前保存的 Files、SpaceDirectoryRow、knowledgeBatch 源码快照，确认以下两项失败同样存在；没有改动对应产品行为：

- `retains the original multiversion/nonfolder gate: { is_multi_version: false }`
- `retires history if a refreshed file stops being multiversion`

## 全量测试快照

平台全量在修复期间运行一次：334 个文件通过、19 个失败；2233 项通过、53 项失败，另有 4 个未处理错误。该次快照包含尚未适配新增后台请求的测试；受影响的下载/上传/历史入口断言随后已修正，并以上述专项结果为准。全量未再次运行，不声明全量通过。

未处理错误涉及 `getMarketInstallPolicy` 缺失的测试 mock，以及请求兼容、图片上传的错误处理。原始日志：`/tmp/bisheng-download-fix/platform-tests.log`。保留该次运行的失败名称以便独立处理：

- src/controllers/dshRequestCompatibility.test.ts > structured errors after shared request handling > preserves business rejection evidence for every caller
- src/controllers/dshRequestCompatibility.test.ts > structured errors after shared request handling > retains full default rejection and shared toast
- src/controllers/dshRequestCompatibility.test.ts > structured errors after shared request handling > preserves transport evidence with the deprecated option too
- src/controllers/dshRequestCompatibility.test.ts > structured errors after shared request handling > retains cancellation behavior
- src/controllers/dshRequestCompatibility.test.ts > desktop login after an expired browser session > preserves the authorization URL through 401 and SSO=false
- src/controllers/dshRequestCompatibility.test.ts > desktop login after an expired browser session > preserves the authorization URL through 401 and SSO=true
- src/test/approvalPage.test.tsx > ApprovalPage > renders page title and loads scenario/route/node data on mount
- src/test/approvalPage.test.tsx > ApprovalPage > opens add-scenario dialog and creates scenario on confirm
- src/test/approvalPage.test.tsx > ApprovalPage > switches to exception tab and retries an exception
- src/test/approvalPage.test.tsx > ApprovalPage > assigns checked users to an exception with the same retry payload
- src/test/approvalPage.test.tsx > ApprovalPage > requires a cancellation reason and trims it before submitting
- src/test/approvalPage.test.tsx > ApprovalPage > uses historical tasks when an exception has no flow snapshot
- src/test/citationFailure.test.ts > citation request failures > preserves expired reasons on directly rejected business envelopes
- src/test/departmentPageRefresh.test.tsx > DepartmentPage member refresh > refreshes the member table after department settings change
- src/test/f048PermissionDialog.test.tsx > F048 PermissionDialog > keeps the legacy subject tabs, search, add action, and roster layout
- src/test/f118SpaceDetail.test.tsx > mounts ordinary SPACE APIs with actual scope, super=false
- src/test/f118SpaceDetail.test.tsx > mounts ordinary SPACE APIs with actual scope, super=true
- src/test/f118SpaceDetail.test.tsx > mounts visible-only child content when root info fails and never enters legacy chunks
- src/test/f118SpaceDetail.test.tsx > direct child admission uses current folder facts without a root info or visible precondition
- src/test/f118SpaceDirectoryHistory.test.tsx > retains the original multiversion/nonfolder gate: { is_multi_version: false }
- src/test/f118SpaceDirectoryHistory.test.tsx > reads history from an actual file row with only child visible, without root/edit/SUCCESS gates
- src/test/f118SpaceDirectoryHistory.test.tsx > preserves rename/download actions without offering history when file.visible is absent
- src/test/f118SpaceDirectoryHistory.test.tsx > retires history if a refreshed file stops being multiversion
- src/test/hostedAppDeleteEligibility.test.tsx > allows platform super admins alongside the original owner (7, false, false)
- src/test/hostedAppDeleteEligibility.test.tsx > allows platform super admins alongside the original owner (8, false, true)
- src/test/hostedAppDeleteEligibility.test.tsx > allows platform super admins alongside the original owner (8, true, true)
- src/test/hostedAppMenuTrim.test.tsx > ⚙️ menu — hosted application keeps two entries (AC-16 / F054 AC-53) > offers manage-permission and delete, and nothing else
- src/test/hostedAppMenuTrim.test.tsx > ⚙️ menu — hosted application keeps two entries (AC-16 / F054 AC-53) > never offers copy or add-to-template, even to an admin who can edit
- src/test/hostedAppMenuTrim.test.tsx > ⚙️ menu — hosted application keeps two entries (AC-16 / F054 AC-53) > greys delete out while the application is online (F054 AC-42)
- src/test/hostedAppMenuTrim.test.tsx > ⚙️ menu — hosted application keeps two entries (AC-16 / F054 AC-53) > drops the permission entry for a caller who may not manage it
- src/test/knowledgeSpaceGrantSubjects.test.tsx > permission subject discovery business boundary > adds a department carrying the current include-children flag when toggled on
- src/utils/dshRequestError.test.ts > DSH management error messages > preserves business error 26112 in direct and HTTP envelopes
- src/utils/dshRequestError.test.ts > DSH management error messages > preserves business error 26113 in direct and HTTP envelopes
- src/utils/dshRequestError.test.ts > DSH management error messages > preserves seat_limit_reached in operation receipts and HTTP errors
- src/utils/dshRequestError.test.ts > DSH management error messages > preserves seat_revoked in operation receipts and HTTP errors
- src/pages/publicEntries.test.tsx > shows a soft limit while keeping the accessible form label
- src/pages/DataSetPage/CreateDataSet.test.tsx > clears a previous file when switching to QA and submits only selected libraries
- src/pages/DataSetPage/CreateDataSet.test.tsx > loads further QA pages and preserves selections when searching
- src/pages/DataSetPage/CreateDataSet.test.tsx > keeps the newest search result when an older request finishes later
- src/pages/DataSetPage/CreateDataSet.test.tsx > reports a failed QA load and allows retry by reopening the selector
- src/pages/BuildPage/dsh/PluginMarketPage.test.tsx > previews the chosen ZIP and imports it into the resolved tenant
- src/pages/BuildPage/dsh/PluginMarketPage.test.tsx > blocks import when the preview reports a version conflict
- src/pages/BuildPage/bench/IconUploadSection.test.tsx > workbench logo upload > keeps the original logo and shows the server error, then retries the same file
- src/pages/BuildPage/bench/IconUploadSection.test.tsx > workbench logo upload > restores the picker after an image decoding failure and accepts the same file again
- src/pages/BuildPage/bench/IconUploadSection.test.tsx > workbench logo upload > keeps the current icon while a request is in flight and restores the picker afterward
- src/pages/BuildPage/bench/IconUploadSection.test.tsx > workbench logo upload > preserves an absolute uploaded image URL
- src/pages/SystemPage/dsh/ContentSafetyDetails.test.tsx > audit views without detached safety checks > keeps groups available without an unlinked-check entry or query
- src/pages/SystemPage/dsh/ContentSafetyDetails.test.tsx > audit views without detached safety checks > keeps unassociated available without an unlinked-check entry or query
- src/pages/BuildPage/hostedApp/publish/AppSecretSettings.test.tsx > environment settings > opens confirmation without calling rebuild and gives administrators no write buttons
- src/pages/BuildPage/hostedApp/publish/DangerZoneCard.test.tsx > delete visibility and state guard (7, false, stopped)
- src/pages/BuildPage/hostedApp/publish/DangerZoneCard.test.tsx > delete visibility and state guard (8, true, stopped)
- src/pages/BuildPage/hostedApp/publish/DangerZoneCard.test.tsx > delete visibility and state guard (8, true, online)
- src/pages/ModelPage/manage/dsh/ModelAccessDialog.test.tsx > saves visibility while preserving the persisted multiplier outside the dialog

## 2026-11-16 用户端遗漏补修

此前实现只覆盖 platform 管理端，client `/workspace/knowledge` 仍从菜单打开后的单项权限摘要更新下载集合。116 部署产物中管理端已有 `download-permissions`，用户端仍保留原菜单授权逻辑；不是批量接口未部署。

用户端改用既有批量下载 inspect：列表/搜索每次成功读到一页后，独立异步检查该页，追加页保留之前结果；列表加载、勾选和普通菜单权限均不等待下载检查。`useFileManager` 保留每页 ID 边界，第一页重载递增 epoch，经现有内容组件传入下载检查钩子。新增轮询行也可独立进入批量检查。

下载集合只来自完整批量检查结果，菜单的下载授权写入已删除；重命名、删除、移动等菜单逻辑继续使用原摘要。保留目录 ZIP 下载：文件和目录分别发送 file/folder 类型。用户/租户/角色、空间、目录及刷新轮次隔离缓存，迟到的 A-B-A 响应不复活旧授权；不可用、不完整或失败结果不暴露下载。已有下载权限的卡片/H5 菜单不会被其他动作的全局 loading 占位遮住。

### 本轮验证

- 10 项初始测试中 9 项先失败；独立复核发现目录下载需一并保留，补充目录用例先失败再修正。最终新增 11 项回归，相关 5 套件合计 21 项通过。
- 使用真实下载权限钩子、批量 API 解包和选择处理，验证慢请求期间仍可选择、权限回包后选择保留、无需打开菜单、菜单不得借单项 download 授权、分页追加、目录 ZIP、异常/不完整响应、空/无效占位及目录/列表/身份 A-B-A。
- 前端工作区 lint、typecheck、架构守卫和 diff check 通过；无新依赖、后端接口、UI 文案或视觉样式。
- 同一完整 client 测试：基线 18f4daa6a6 为 1953 passed / 92 failed（22 failed suites）；修复后沙箱内为 1963 passed / 93 failed（23 failed suites）。原有失败逐项一致，仅多出 ChatFile 本地 HTTP 测试服务器无法启动用例。
- 基线命令有本机网络权限，修复后首次完整命令处于受限沙箱；以同等权限复核 ChatFile 和首次并行运行曾超时的 KnowledgeSpaceAccessMode，2 套件 22 项全部通过。该项不是产品回归。专项没有放宽业务断言；完整测试并非全绿。
- 独立复核最终无阻塞问题。本轮只交付源码，没有执行 116 部署。

### 基线失败用例（本轮未改动）

- `api/knowledgeUpload.test.ts` — does not replay an upload if the management scope changes
- `api/knowledgeUpload.test.ts` — does not upload if reading the target space fails
- `api/knowledgeUpload.test.ts` — pins upload to the server-confirmed tenant without requiring a tenant picker
- `api/knowledgeUpload.test.ts` — preserves caller headers on multipart requests
- `api/knowledgeUpload.test.ts` — preserves the explicit filename when uploading a folder entry
- `api/knowledgeUpload.test.ts` — retains compatibility with backends that do not send a management tenant header
- `components/Chat/Input/ChatResourceMenu.test.tsx` — knowledge base read failures offer retry instead of an empty list
- `components/Chat/Input/ChatResourceMenu.test.tsx` — knowledge bases can be selected independently of spaces, without loading the list before opening
- `components/Chat/importFailureContract.test.tsx` — app import UI endpoint keeps the original local fallback and only closes after an actual successful import
- `components/Chat/importFailureContract.test.tsx` — app import UI endpoint retains business evidence and leaves the picker open without a second toast
- `components/Chat/importFailureContract.test.tsx` — app import UI endpoint retains canceled evidence and leaves the picker open without a second toast
- `components/Chat/importFailureContract.test.tsx` — app import UI endpoint retains global evidence and leaves the picker open without a second toast
- `components/Chat/importFailureContract.test.tsx` — daily import UI endpoint keeps the original local fallback and only closes after an actual successful import
- `components/Chat/importFailureContract.test.tsx` — daily import UI endpoint retains business evidence and leaves the picker open without a second toast
- `components/Chat/importFailureContract.test.tsx` — daily import UI endpoint retains canceled evidence and leaves the picker open without a second toast
- `components/Chat/importFailureContract.test.tsx` — daily import UI endpoint retains global evidence and leaves the picker open without a second toast
- `components/Skills/__tests__/skillPreview.test.ts` — personal skill persistence persists bytes, enables by default and isolates account and tenant scope
- `components/Skills/__tests__/skillPreview.test.ts` — personal skill persistence rejects duplicate add and keeps the original bytes
- `components/Skills/__tests__/skillPreview.test.ts` — personal skill persistence updates in place, preserves disabled state and rejects stale changes
- `components/Skills/__tests__/skillPreview.test.ts` — skill package validation accepts a valid archive at the 50 MiB upload boundary
- `components/Skills/__tests__/skillPreview.test.ts` — skill package validation caps actual manifest output even when its compressed size is small
- `components/Skills/__tests__/skillPreview.test.ts` — skill package validation checks the 200 MiB expanded boundary with 0 extra bytes
- `components/Skills/__tests__/skillPreview.test.ts` — skill package validation checks the 200 MiB expanded boundary with 1 extra bytes
- `components/Skills/__tests__/skillPreview.test.ts` — skill package validation extracts a UTF-8 manifest without executing the instructions
- `components/Skills/__tests__/skillPreview.test.ts` — skill package validation rejects duplicate metadata
- `components/Skills/__tests__/skillPreview.test.ts` — skill package validation rejects empty instructions
- `components/Skills/__tests__/skillPreview.test.ts` — skill package validation rejects invalid identifier
- `components/Skills/__tests__/skillPreview.test.ts` — skill package validation rejects missing YAML
- `components/Skills/__tests__/skillPreview.test.ts` — skill package validation rejects missing and multiple manifests
- `components/Skills/__tests__/skillPreview.test.ts` — skill package validation rejects traversal before JSZip normalized names can hide it
- `components/Skills/__tests__/skillPreview.test.ts` — skill package validation supports a packaged skill and preserves its resources
- `components/approval/AppReviewView.test.tsx` — AppReviewView shows the refusal message rather than an empty frame when the reads are denied
- `components/messageApproval/hostedAppNotificationTable.test.ts` — §3.0.3 — statements stay statements treats a cancelled-by-delete notice as a statement
- `hooks/useAiChat.test.ts` — project draft through the real SSE serializer does not adopt a later project when an ordinary draft waits for its lease
- `hooks/useAiChat.test.ts` — project draft through the real SSE serializer keeps the project on a same-draft retry, task mode=false
- `hooks/useAiChat.test.ts` — project draft through the real SSE serializer keeps the project on a same-draft retry, task mode=true
- `hooks/useAiChat.test.ts` — project draft through the real SSE serializer keeps the project selected before an asynchronous lease, task mode=false
- `hooks/useAiChat.test.ts` — project draft through the real SSE serializer keeps the project selected before an asynchronous lease, task mode=true
- `pages/appChat/appStreamStop.test.tsx` — production assistant stop frames restore input and persist the truncated terminal through the next round
- `pages/appChat/conversationShare.test.tsx` — derives sharing from the destination conversation while the active store switches
- `pages/appChat/conversationShare.test.tsx` — enables both entries after a attachment submission and clears them for a new conversation
- `pages/appChat/conversationShare.test.tsx` — enables both entries after a form submission and clears them for a new conversation
- `pages/appChat/conversationShare.test.tsx` — enables both entries after a text submission and clears them for a new conversation
- `pages/appChat/conversationShare.test.tsx` — keeps a read-only shared conversation read-only
- `pages/appChat/conversationShare.test.tsx` — keeps both share entries hidden for automated output
- `pages/appChat/conversationShare.test.tsx` — keeps both share entries hidden for configured welcome
- `pages/appChat/conversationShare.test.tsx` — keeps both share entries hidden for empty
- `pages/appChat/conversationShare.test.tsx` — keeps both share entries hidden for workflow form
- `pages/appChat/conversationShare.test.tsx` — keeps both share entries hidden for workflow welcome
- `pages/appChat/conversationShare.test.tsx` — renders empty share for 10 with personal history=false and greeting=Configured greeting
- `pages/appChat/conversationShare.test.tsx` — renders empty share for 10 with personal history=false and greeting=null
- `pages/appChat/conversationShare.test.tsx` — renders empty share for 10 with personal history=true and greeting=Configured greeting
- `pages/appChat/conversationShare.test.tsx` — renders empty share for 10 with personal history=true and greeting=null
- `pages/appChat/conversationShare.test.tsx` — renders empty share for 5 with personal history=false and greeting=Configured greeting
- `pages/appChat/conversationShare.test.tsx` — renders empty share for 5 with personal history=false and greeting=null
- `pages/appChat/conversationShare.test.tsx` — renders empty share for 5 with personal history=true and greeting=Configured greeting
- `pages/appChat/conversationShare.test.tsx` — renders empty share for 5 with personal history=true and greeting=null
- `pages/appChat/conversationShare.test.tsx` — renders existing shared history as read-only
- `pages/appChat/conversationShare.test.tsx` — requires the existing app sharing permission
- `pages/appChat/conversationShare.test.tsx` — shares loaded user history for flow type 10
- `pages/appChat/conversationShare.test.tsx` — shares loaded user history for flow type 5
- `pages/appChat/conversationShare.test.tsx` — starts a new conversation from the ordinary app empty state
- `pages/knowledge/FilePreview/FilePreviewPage.text.test.tsx` — TXT preview content loaded from a search-result route renders the TXT body for original=/bisheng/original/6.txt and preview=
- `pages/knowledge/FilePreview/FilePreviewPage.text.test.tsx` — TXT preview content loaded from a search-result route renders the TXT body for original=/bisheng/original/source.txt and preview=/bisheng/original/6.txt
- `pages/knowledge/FilePreview/FilePreviewPage.text.test.tsx` — TXT preview content loaded from a search-result route renders the TXT body for original=/workspace/bisheng/original/6.txt and preview=
- `pages/knowledge/FilePreview/FilePreviewPage.text.test.tsx` — TXT preview content loaded from a search-result route renders the TXT body for original=/workspace/workspace/bisheng/original/6.txt and preview=
- `pages/knowledge/FilePreview/FilePreviewPage.text.test.tsx` — TXT preview content loaded from a search-result route renders the TXT body for original=http://storage.internal:9000/bisheng/original/6.txt and preview=
- `pages/knowledge/hooks/useFileManager.test.ts` — SpaceDetail UI — F027 infinite-scroll guards declares hasMore prop on KnowledgeSpaceContentProps
- `pages/knowledge/hooks/useFileManager.test.ts` — SpaceDetail UI — F027 infinite-scroll guards declares the append callback on KnowledgeSpaceContentProps
- `pages/knowledge/hooks/useFileManager.test.ts` — SpaceDetail UI — F027 infinite-scroll guards renders the <LoadMore> sentinel through a shared bottom status
- `pages/settings/desktopSettings.test.ts` — accepts account with host language and theme parameters
- `pages/settings/desktopSettings.test.ts` — accepts ai-access with host language and theme parameters
- `pages/settings/desktopSettings.test.ts` — accepts desktop-usage with host language and theme parameters
- `pages/settings/desktopSettings.test.ts` — accepts my-requests with host language and theme parameters
- `pages/settings/desktopSettings.test.ts` — accepts my-tasks with host language and theme parameters
- `pages/settings/desktopSettings.test.ts` — accepts notifications with host language and theme parameters
- `pages/settings/desktopSettings.test.ts` — requires native embedding and the explicit content-mode marker
- `pages/skills/SkillCenterPage.test.tsx` — explains a failed switch with the server reason and keeps the previous state
- `pages/skills/SkillCenterPage.test.tsx` — explains a missing bundle and offers an update
- `pages/skills/SkillCenterPage.test.tsx` — hides the enable switch on an enterprise skill
- `pages/skills/SkillCenterPage.test.tsx` — keeps my skills when an old square link is opened
- `pages/skills/SkillCenterPage.test.tsx` — keeps the card and explains a failed delete
- `pages/skills/SkillCenterPage.test.tsx` — keeps the skill list when a skill cannot be opened
- `pages/skills/SkillCenterPage.test.tsx` — returns to the list when the open skill is gone and leaves the others
- `pages/skills/SkillCenterPage.test.tsx` — searches within my skills
- `pages/skills/SkillCenterPage.test.tsx` — shows the chosen skill file
- `pages/skills/SkillCenterPage.test.tsx` — shows the enterprise skill body
- `pages/skills/SkillCenterPage.test.tsx` — splits my skills into the two groups and counts each source
- `pages/skills/SkillCenterPage.test.tsx` — stays on the detail when the user turns off their own skill
- `pages/unifiedPermissionEntryRoutes.test.tsx` — F050 unified permission entry structure gives knowledge create and settings pages an inner scrolling shell
- `pages/unifiedPermissionEntryRoutes.test.tsx` — F050 unified permission entry structure keeps generic file/folder permission UI while old resource-only dialogs are gone
- `pages/unifiedPermissionEntryRoutes.test.tsx` — F050 unified permission entry structure registers the four create/settings routes behind the existing plugin gates

以下为相同的套件启动/导入失败：

- `pages/knowledge/FilePreview/TopBar.test.tsx`
- `pages/standaloneChat/guestAccessError.test.ts`
- `pages/apps/explore.navigation.test.tsx`
- `pages/Subscription/ChannelPreviewDrawer.test.tsx`
- `layouts/skillCenterNavigation.test.tsx`
- `layouts/DesktopShellBridge.test.tsx`
- `components/PersonalTokenDialog.test.tsx`
- `components/FailureInfoDetails.test.tsx`
