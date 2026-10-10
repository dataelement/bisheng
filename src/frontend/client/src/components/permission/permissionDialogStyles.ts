/**
 * Shared chrome for the permission dialogs.
 *
 * Extracted verbatim from KnowledgeSpaceShareDialog, which shipped the original
 * "新增授权" dialog. The unified-permission draft picker reuses these so both
 * dialogs stay pixel-identical instead of drifting into two look-alikes.
 */

/** Dialog shell: fixed 80vh card on desktop, full-screen sheet under 768px. */
export const PERMISSION_DIALOG_CONTENT_CLASS =
  "!flex h-[80vh] max-h-[800px] w-[calc(100vw-80px)] max-w-[800px] min-w-0 flex-col gap-0 overflow-hidden p-5 max-[768px]:fixed max-[768px]:inset-0 max-[768px]:h-[100dvh] max-[768px]:max-h-[100dvh] max-[768px]:w-full max-[768px]:max-w-none max-[768px]:translate-x-0 max-[768px]:translate-y-0 max-[768px]:rounded-none max-[768px]:p-4";

/** Subject-type switcher: bordered pill group, brand-tinted active segment. */
export const SUBJECT_TAB_LIST_CLASS =
  "w-fit shrink-0 rounded-md border border-border-base bg-white p-[3px] shadow-none";

export const SUBJECT_TAB_TRIGGER_CLASS =
  "min-w-0 rounded-[4px] px-3 py-0.5 text-[14px] font-normal leading-[22px] text-text-3 shadow-none data-[state=active]:bg-[rgb(var(--brand-500)/0.15)] data-[state=active]:font-medium data-[state=active]:text-blue-500 data-[state=active]:shadow-none";

/**
 * Same switcher rendered with plain buttons instead of Radix Tabs — used where
 * the active segment is driven by external state. Wrap them in
 * `inline-flex items-center justify-center ${SUBJECT_TAB_LIST_CLASS}`.
 */
export const SUBJECT_TAB_BUTTON_CLASS =
  "min-w-0 rounded-[4px] px-3 py-0.5 text-[14px] leading-[22px] transition-colors";

export const SUBJECT_TAB_BUTTON_ACTIVE_CLASS =
  "bg-[rgb(var(--brand-500)/0.15)] font-medium text-blue-500";

export const SUBJECT_TAB_BUTTON_INACTIVE_CLASS = "font-normal text-text-3";

/** "包含子部门" toggle sitting next to the tab group. */
export const INCLUDE_CHILDREN_LABEL_CLASS =
  "flex shrink-0 cursor-pointer items-center gap-2 text-[14px] leading-[22px] text-text-1";

export const INCLUDE_CHILDREN_CHECKBOX_CLASS =
  "border-[#D9D9D9] data-[state=checked]:border-primary data-[state=indeterminate]:border-primary";

/**
 * Footer action pair (cancel + confirm). Right-aligned at their natural width on
 * desktop; under 768px — where the dialog becomes a full-screen sheet — the two
 * tile across one full-width row, each taking half. Same breakpoint as the shell
 * above so both permission dialogs bottom out identically on mobile.
 */
export const PERMISSION_FOOTER_ACTIONS_CLASS =
  "flex shrink-0 gap-3 max-[768px]:[&>button]:flex-1 min-[769px]:justify-end";

/** Muted caption used by the footer labels ("已选用户:", "统一授权:"). */
export const PERMISSION_FOOTER_LABEL_CLASS =
  "shrink-0 text-[14px] font-normal leading-[22px] text-text-3";

/**
 * Subject rows across the three picker tabs (用户 / 部门 / 用户组).
 *
 * 部门 is a tree; 用户 and 用户组 are flat lists. All three share the same row
 * rhythm and fixed 20×20 columns so the checkbox / icon / name land in the same
 * place when switching tabs.
 *
 * Hierarchy language is taken from the knowledge-space sidebar tree
 * (`pages/knowledge/sidebar/KnowledgeFolderTree`) and the in-dialog folder tree
 * (`SpaceDetail/MoveToFolderTree`) — there is no Tree spec in packages/ui/docs
 * yet, so those are the reference implementations: 20px indent per level, 20×20
 * slots, rounded rows with a neutral hover fill, 2px between siblings. Scaled to
 * this dialog's 14px type (32px rows) instead of the sidebar's 12px / 28px.
 */
export const PERMISSION_SUBJECT_LIST_CLASS = "flex flex-col gap-0.5 p-1";

export const PERMISSION_SUBJECT_ROW_CLASS =
  "group flex h-8 shrink-0 select-none items-center rounded-md pr-2 text-[14px] leading-5 text-text-1 transition-colors";

export const PERMISSION_SUBJECT_ROW_INTERACTIVE_CLASS = "cursor-pointer hover:bg-fill-1";

export const PERMISSION_SUBJECT_ROW_DISABLED_CLASS = "cursor-not-allowed opacity-60";

/** 20×20 wrapper holding a 16×16 chevron, entity icon or checkbox. */
export const PERMISSION_SUBJECT_SLOT_CLASS = "flex size-5 shrink-0 items-center justify-center";

/**
 * Chevron/entity icon tint. The sidebar tree hardcodes #8D93A0; `text-3` (#898F9C)
 * is the same rung of the neutral ramp and flips correctly in dark mode.
 */
export const PERMISSION_SUBJECT_ICON_CLASS = "size-4 shrink-0 text-text-3";

/** One indent step (px) — one 20×20 slot, same as the sidebar tree. */
export const PERMISSION_SUBJECT_INDENT_STEP = 20;

/**
 * Left padding for a row at `depth`. The 4px offset plus the list's own `p-1`
 * keeps depth-0 rows 8px off the container border. `extraSlots` shifts secondary
 * rows (load-more, retry) over to the name column.
 */
export function permissionSubjectIndent(depth: number, extraSlots = 0): string {
  return `${(depth + extraSlots) * PERMISSION_SUBJECT_INDENT_STEP + 4}px`;
}
