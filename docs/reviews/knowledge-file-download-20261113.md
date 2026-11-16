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
