# Task retry state race hotfix — 2026-11-16

## Failure and scope

The deployed current-model fix was present in both 116 frontend assets and backend code. The affected conversation actually changed from the failing model to the replacement model; replacement calls succeeded and the worker parked for user input. The page kept an old failure until refresh. No model-selection or backend API contract change is needed for this hotfix.

Before the fix, continuation reset the store to Running before its HTTP request was accepted. Running opened a WebSocket; its open handler reconciled persisted state while the backend could still report the previous failed round. That response put the store back in Stoped and retired the new socket. The retry request could subsequently succeed without restoring the live view. A controlled hook test reproduced this ordering.

## Change

- Await continuation acceptance before archiving the old round, clearing errors/queue feedback, and setting Running. The existing retry button loading state stays active during acceptance.
- A reconciliation response may apply only to the same history-array identity captured when the read began. A new accepted round replaces that array; late old version/task responses are ignored atomically against the current store.
- Ignore callbacks from retired sockets and inactive/stopped sessions, so a queued old error callback cannot stop the next round.
- Guard each version against overlapping continuation calls within its manager. ExecutionFlow retry/follow-up share that manager; TaskTurnPanel also retains its own click guard. Release the guard on success or rejection.
- On request rejection, do not append an unaccepted round. Surface the dispatch error without borrowing old model failure metadata; preserve an existing successful answer.

No new atoms, state-management dependencies, UI copy, backend endpoints, permissions, or server deployment. The preexisting current-model selection and share-page restrictions remain covered.

## Verification

- Initial race regression: 5 expected failures before production changes, then passed. Independent review found duplicate-request exposure in standalone ExecutionFlow; its added regression failed with two requests, then passed after the per-version guard.
- Final focused run: 7 suites / 49 tests passed, including 8 new cases. Covers pending acceptance, clarification without refresh, late version/task snapshots, retired/current socket failures, rejection/retry, duplicate calls, and completion before socket open.
- Frontend workspace `pnpm lint` and `pnpm typecheck`: exit 0. Architecture guard and `git diff --check`: passed.
- Final full client suite (`NODE_ENV=development`, Jest CI, in band, coverage off): **1940 passed / 93 failed**, 263 passed / 23 failed suites.
- Same full suite on pre-change beta1 `4c26839b77`: **1932 passed / 93 failed**, 262 passed / 23 failed suites. Exact failed case names and failed suite paths match; **8 added passing cases and no new failures**.
- Existing optional unbuilt canvas was excluded using the documented test-only resolver loader; no dependency manifest changes. Full reports were written to `/tmp/bisheng-retry-state-{baseline,final-full}.json`.
- Independent review rechecked the guard and callers and found no remaining blockers.

## Unchanged full-suite failures

These failures are not included in this hotfix. A zero assertion count denotes a suite startup/import failure.

| Suite (under client/src) | Failed assertions |
| --- | ---: |
| `pages/appChat/conversationShare.test.tsx` | 23 |
| `components/Skills/__tests__/skillPreview.test.ts` | 15 |
| `pages/appChat/components/ChatFile.test.tsx` | 1 |
| `components/Chat/Input/ChatResourceMenu.test.tsx` | 2 |
| `hooks/useAiChat.test.ts` | 5 |
| `pages/appChat/appStreamStop.test.tsx` | 1 |
| `components/approval/AppReviewView.test.tsx` | 1 |
| `pages/skills/SkillCenterPage.test.tsx` | 12 |
| `components/Chat/importFailureContract.test.tsx` | 8 |
| `pages/knowledge/FilePreview/FilePreviewPage.text.test.tsx` | 5 |
| `components/messageApproval/hostedAppNotificationTable.test.ts` | 1 |
| `api/knowledgeUpload.test.ts` | 6 |
| `pages/unifiedPermissionEntryRoutes.test.tsx` | 3 |
| `pages/knowledge/hooks/useFileManager.test.ts` | 3 |
| `pages/settings/desktopSettings.test.ts` | 7 |
| `pages/knowledge/FilePreview/TopBar.test.tsx` | 0 |
| `pages/standaloneChat/guestAccessError.test.ts` | 0 |
| `pages/apps/explore.navigation.test.tsx` | 0 |
| `pages/Subscription/ChannelPreviewDrawer.test.tsx` | 0 |
| `layouts/skillCenterNavigation.test.tsx` | 0 |
| `layouts/DesktopShellBridge.test.tsx` | 0 |
| `components/PersonalTokenDialog.test.tsx` | 0 |
| `components/FailureInfoDetails.test.tsx` | 0 |

### Failed case names

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
- `pages/appChat/components/ChatFile.test.tsx` — download routing with a frontend catch-all requests PDF bytes when the user clicks a valid historical attachment
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
