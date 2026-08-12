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
  "w-fit shrink-0 rounded-md border border-[#ECECEC] bg-white p-[3px] shadow-none";

export const SUBJECT_TAB_TRIGGER_CLASS =
  "min-w-0 rounded-[4px] px-3 py-0.5 text-[14px] font-normal leading-[22px] text-[#818181] shadow-none data-[state=active]:bg-[rgb(var(--brand-500)/0.15)] data-[state=active]:font-medium data-[state=active]:text-blue-500 data-[state=active]:shadow-none";

/**
 * Same switcher rendered with plain buttons instead of Radix Tabs — used where
 * the active segment is driven by external state. Wrap them in
 * `inline-flex items-center justify-center ${SUBJECT_TAB_LIST_CLASS}`.
 */
export const SUBJECT_TAB_BUTTON_CLASS =
  "min-w-0 rounded-[4px] px-3 py-0.5 text-[14px] leading-[22px] transition-colors";

export const SUBJECT_TAB_BUTTON_ACTIVE_CLASS =
  "bg-[rgb(var(--brand-500)/0.15)] font-medium text-blue-500";

export const SUBJECT_TAB_BUTTON_INACTIVE_CLASS = "font-normal text-[#818181]";

/** "包含子部门" toggle sitting next to the tab group. */
export const INCLUDE_CHILDREN_LABEL_CLASS =
  "flex shrink-0 cursor-pointer items-center gap-2 text-[14px] leading-[22px] text-[#212121]";

export const INCLUDE_CHILDREN_CHECKBOX_CLASS =
  "border-[#D9D9D9] data-[state=checked]:border-primary data-[state=indeterminate]:border-primary";

/** Muted caption used by the footer labels ("已选用户:", "统一授权:"). */
export const PERMISSION_FOOTER_LABEL_CLASS =
  "shrink-0 text-[14px] font-normal leading-[22px] text-[#999999]";
