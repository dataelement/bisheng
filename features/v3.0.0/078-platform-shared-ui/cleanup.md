# Migrated UI cleanup

Historical cleanup record. The subsequent2026-10-20 user decision supersedes
keeping primitive adapters: see [direct import plan](direct-import-plan.md).

Scope: platform only. No client/shared library implementation changes, package
installation or dependency removal. Keep accepted button/input/notice adapters:
they delegate to @bisheng/ui and preserve existing call contracts.

Removed8 unused legacy UI files,35 unreferenced local icon implementation files
and35 SVG assets used exclusively by those deleted icons (78 files total).
Pruned unused named exports in the local icon barrel. Scanned static imports,
re-exports, dynamic literal imports and test mocks before deleting; followed
exclusive asset references. A second pass found no orphan bs-ui modules.

Retain lucide-react:109 platform source files still import it, including
unmatched business icons and legacy compound controls. Retain used local icon
modules, especially brand loading/GitHub/file formats. A blanket removal would
break imports. Retain old Switch/Checkbox/Tabs/Tooltip/Badge where shared
permission/selector/compound-control internals still call them; this cleanup
is not a new migration wave. Do not claim the whole legacy library is gone.

Verification: whole frontend typecheck passed; scoped icon-barrel ESLint and
git diff --check passed. Regression/build results below.

## Deleted files

- `src/frontend/platform/src/components/bs-ui/dialog/DialogForceUpdate.tsx`
- `src/frontend/platform/src/components/bs-ui/input/editTitle.tsx`
- `src/frontend/platform/src/components/bs-ui/multiSelect.tsx/Example.tsx`
- `src/frontend/platform/src/components/bs-ui/radio/radioCard.tsx`
- `src/frontend/platform/src/components/bs-ui/radio-group.tsx`
- `src/frontend/platform/src/components/bs-ui/sharedBadge/index.tsx`
- `src/frontend/platform/src/components/bs-ui/toggle-group.tsx`
- `src/frontend/platform/src/components/bs-icons/DownIcon.tsx`
- `src/frontend/platform/src/components/bs-icons/addTo/index.tsx`
- `src/frontend/platform/src/components/bs-icons/avatar/index.tsx`
- `src/frontend/platform/src/components/bs-icons/bookOpen/index.tsx`
- `src/frontend/platform/src/components/bs-icons/clear/index.tsx`
- `src/frontend/platform/src/components/bs-icons/dashboard/index.tsx`
- `src/frontend/platform/src/components/bs-icons/down/index.tsx`
- `src/frontend/platform/src/components/bs-icons/en/index.tsx`
- `src/frontend/platform/src/components/bs-icons/expand/index.tsx`
- `src/frontend/platform/src/components/bs-icons/form/index.tsx`
- `src/frontend/platform/src/components/bs-icons/go/index.tsx`
- `src/frontend/platform/src/components/bs-icons/label/index.tsx`
- `src/frontend/platform/src/components/bs-icons/menu/application/index.tsx`
- `src/frontend/platform/src/components/bs-icons/menu/approval/index.tsx`
- `src/frontend/platform/src/components/bs-icons/menu/dshDesktop/index.tsx`
- `src/frontend/platform/src/components/bs-icons/menu/evaluation/index.tsx`
- `src/frontend/platform/src/components/bs-icons/menu/label/index.tsx`
- `src/frontend/platform/src/components/bs-icons/menu/log/index.tsx`
- `src/frontend/platform/src/components/bs-icons/menu/model/index.tsx`
- `src/frontend/platform/src/components/bs-icons/menu/technology/index.tsx`
- `src/frontend/platform/src/components/bs-icons/menu/tenant/index.tsx`
- `src/frontend/platform/src/components/bs-icons/moon/index.tsx`
- `src/frontend/platform/src/components/bs-icons/moveOne/index.tsx`
- `src/frontend/platform/src/components/bs-icons/office/index.tsx`
- `src/frontend/platform/src/components/bs-icons/plus/index.tsx`
- `src/frontend/platform/src/components/bs-icons/plusBox/index.tsx`
- `src/frontend/platform/src/components/bs-icons/prompt/index.tsx`
- `src/frontend/platform/src/components/bs-icons/quit/index.tsx`
- `src/frontend/platform/src/components/bs-icons/save/index.tsx`
- `src/frontend/platform/src/components/bs-icons/search/index.tsx`
- `src/frontend/platform/src/components/bs-icons/send/index.tsx`
- `src/frontend/platform/src/components/bs-icons/tab/index.tsx`
- `src/frontend/platform/src/components/bs-icons/thumbs/index.tsx`
- `src/frontend/platform/src/components/bs-icons/toast/index.tsx`
- `src/frontend/platform/src/components/bs-icons/user/index.tsx`
- `src/frontend/platform/src/components/bs-icons/addTo/AddTo.svg`
- `src/frontend/platform/src/components/bs-icons/avatar/Avatar.svg`
- `src/frontend/platform/src/components/bs-icons/bookOpen/BookOpen.svg`
- `src/frontend/platform/src/components/bs-icons/clear/Clear.svg`
- `src/frontend/platform/src/components/bs-icons/down/DropDown.svg`
- `src/frontend/platform/src/components/bs-icons/en/En.svg`
- `src/frontend/platform/src/components/bs-icons/form/Form.svg`
- `src/frontend/platform/src/components/bs-icons/go/Go.svg`
- `src/frontend/platform/src/components/bs-icons/label/Label.svg`
- `src/frontend/platform/src/components/bs-icons/menu/application/Application.svg`
- `src/frontend/platform/src/components/bs-icons/menu/evaluation/Evaluation.svg`
- `src/frontend/platform/src/components/bs-icons/menu/label/Label.svg`
- `src/frontend/platform/src/components/bs-icons/menu/log/Log.svg`
- `src/frontend/platform/src/components/bs-icons/menu/model/Model.svg`
- `src/frontend/platform/src/components/bs-icons/menu/technology/Technology.svg`
- `src/frontend/platform/src/components/bs-icons/moon/Moon.svg`
- `src/frontend/platform/src/components/bs-icons/moveOne/MoveOne.svg`
- `src/frontend/platform/src/components/bs-icons/office/Word.svg`
- `src/frontend/platform/src/components/bs-icons/plus/Plus.svg`
- `src/frontend/platform/src/components/bs-icons/plusBox/PlusBox.svg`
- `src/frontend/platform/src/components/bs-icons/plusBox/PlusBox-dark.svg`
- `src/frontend/platform/src/components/bs-icons/prompt/Prompt.svg`
- `src/frontend/platform/src/components/bs-icons/quit/Quit.svg`
- `src/frontend/platform/src/components/bs-icons/save/icon.svg`
- `src/frontend/platform/src/components/bs-icons/search/Search.svg`
- `src/frontend/platform/src/components/bs-icons/send/Send.svg`
- `src/frontend/platform/src/components/bs-icons/tab/icon.svg`
- `src/frontend/platform/src/components/bs-icons/thumbs/copy.svg`
- `src/frontend/platform/src/components/bs-icons/thumbs/like.svg`
- `src/frontend/platform/src/components/bs-icons/thumbs/unLike.svg`
- `src/frontend/platform/src/components/bs-icons/toast/Info.svg`
- `src/frontend/platform/src/components/bs-icons/toast/Success.svg`
- `src/frontend/platform/src/components/bs-icons/toast/Warning.svg`
- `src/frontend/platform/src/components/bs-icons/toast/Error.svg`
- `src/frontend/platform/src/components/bs-icons/user/User.svg`
- `src/frontend/platform/src/components/bs-ui/toggle.tsx`

## Regression results

49 tests in9 files passed: shared control/notice adapters, class merging,
sidebar/workspace/menu permissions, segmented header navigation, lazy tool
permissions, service-account grants/mutations and subject user search.
Updated the old24px sidebar assertion to the user-requested16px size.

An additional existing knowledgeSpaceGrantSubjects suite has2 assertion
mismatches: department subjects now carry path metadata; user-group search
uses50-item paging plus cancellation instead of the old200-item call. The
implementation files involved were not edited in this cleanup; leave these
expectations to the permission work rather than changing its contract here.

Production platform build passed in44.28s (existing Ace/eval/chunk warnings).
